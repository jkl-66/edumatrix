"""Focused, owner-scoped chat persistence and attachment parsing for F7-T04."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import Field
from sqlalchemy import func

from app.auth import get_current_user
from app.agent_audit import append_public_run_event, build_chat_agent_audit
from app.authorization import require_course_access
from app.database import (
    DBChatAttachment,
    DBChatConversation,
    DBChatMessage,
    DBCourse,
    DBKnowledgePoint,
    DBLearningPath,
    DBPathNode,
    DBSourceDocument,
    DBSourceRef,
    DBProfileSnapshot,
    DBStudentProfile,
    DBUser,
    run_db_op,
)
from app.m2_contracts import StrictModel
from app.models import ContextResolutionError, resolve_context_ref
from app.resource_bundles import (
    GENERATION_RESOURCE_TYPES,
    ResourceBundleError,
    create_generation_job,
    execute_generation_job,
    execute_generation_job_demo,
    generation_job_payload,
)
from app.schemas import ContextRef
from app.source_refs import chat_source_ref, project_source_ref
from app.profile_adaptation import build_profile_adaptation, profile_has_signal, profile_prompt_context
from app.profile_onboarding import latest_profile_snapshot_for_course
from config import CONFIG
from document_parser import DocumentParseError, parse_document


router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

DOCUMENT_FORMATS = {"pdf", "ppt", "pptx", "docx", "md", "txt"}
IMAGE_FORMATS = {"png", "jpg", "jpeg", "webp"}
SUPPORTED_FORMATS = DOCUMENT_FORMATS | IMAGE_FORMATS
PERMANENT_PARSE_ERRORS = {
    "document_empty",
    "document_encoding_invalid",
    "document_format_unsupported",
    "document_limit_rejected",
    "document_text_empty",
    "image_invalid",
}


class ConversationInput(StrictModel):
    course_id: str | None = Field(default=None, max_length=128)
    course_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    title: str = Field(default="", max_length=256)


class ConversationArchiveInput(StrictModel):
    expected_lock_version: int = Field(ge=1)


class AttachmentActionInput(StrictModel):
    expected_lock_version: int = Field(ge=1)


class MessageInput(StrictModel):
    content: str = Field(default="", max_length=50000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=8)
    context_refs: list[ContextRef] = Field(default_factory=list, max_length=8)
    idempotency_key: str = Field(min_length=8, max_length=128)
    intent: Literal["chat", "general_qa", "course_qa", "image_qa", "code_qa", "resource_generation", "path_bundle"] = "chat"
    resource_types: list[str] = Field(default_factory=list, max_length=9)
    context_snapshot_id: str = Field(default="", max_length=128)
    return_to: str = Field(default="", max_length=2048)


class ResourceActionInput(StrictModel):
    resource_type: Literal["handout", "mind_map", "quiz"]
    expected_lock_version: int = Field(ge=1)
    knowledge_point_id: str | None = Field(default=None, max_length=64)


RESOURCE_MESSAGE_TYPES = (
    "handout",
    "mind_map",
    "quiz",
    "training_task",
    "code_sandbox",
    "video",
    "deck",
    "interactive_model",
    "feynman",
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fail(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _canonical_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return _sha256_text(text)


def _safe_return_to(value: str) -> str:
    target = str(value or "").strip()
    if not target:
        return ""
    if not target.startswith("/") or target.startswith("//"):
        _fail(422, "chat_return_path_invalid", "返回地址必须是系统内页面")
    return target


def _message_resource_types(payload: MessageInput) -> list[str]:
    values = [str(item).strip() for item in payload.resource_types if str(item).strip()]
    if len(values) != len(set(values)):
        _fail(422, "chat_resource_type_duplicate", "同一资源类型不能重复选择")
    unsupported = [item for item in values if item not in RESOURCE_MESSAGE_TYPES]
    if unsupported:
        _fail(422, "chat_resource_type_invalid", "存在不支持的资源类型")
    if payload.intent not in {"resource_generation", "path_bundle"} and values:
        _fail(422, "chat_resource_intent_required", "选择资源类型时必须使用资源生成意图")
    if payload.intent in {"resource_generation", "path_bundle"} and not values:
        _fail(422, "chat_resource_types_required", "资源生成消息至少需要一种资源类型")
    return values


def _course(db: Any, actor: DBUser, course_id: str | None) -> DBCourse | None:
    if not course_id:
        return None
    row = db.get(DBCourse, course_id)
    if row is None:
        _fail(404, "chat_course_unknown", "课程不存在")
    require_course_access(
        db,
        actor,
        course_id=row.id,
        action="read",
        visibility=row.visibility,
    )
    if row.status in {"archived", "withdrawn"}:
        _fail(409, "chat_course_unavailable", "课程已归档或不可用，不能用于新的对话上下文")
    from course_catalog import course_is_selectable
    if not course_is_selectable(db, row):
        _fail(409, "chat_course_unavailable", "这门课程当前没有可用学习资料，请先完成资料解析")
    return row


def _conversation_courses(db: Any, row: DBChatConversation) -> list[dict[str, Any]]:
    """Project the latest message's frozen course set without adding a second store."""
    latest = (
        db.query(DBChatMessage)
        .filter_by(
            conversation_id=row.id,
            owner_public_id=row.owner_public_id,
            role="user",
        )
        .order_by(DBChatMessage.sequence.desc())
        .first()
    )
    refs = list(latest.context_refs or []) if latest is not None else []
    courses: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        course = ref.get("course") or {}
        course_id = str(course.get("id") or ref.get("courseId") or "")
        if not course_id or course_id in seen:
            continue
        seen.add(course_id)
        courses.append({
            "id": course_id,
            "title": str(course.get("title") or course_id),
            "version": course.get("version"),
            "status": course.get("status"),
        })
    if not courses and latest is None and row.course_id:
        course = db.get(DBCourse, row.course_id)
        if course is not None:
            courses.append({
                "id": course.id,
                "title": course.title,
                "version": course.version,
                "status": course.status,
            })
    return courses


def _chat_course_catalog(db: Any, actor: DBUser) -> list[dict[str, Any]]:
    """Return only readable, currently usable courses for the chat picker."""
    from course_catalog import MASTER_COURSE_ID, course_is_selectable

    items: list[dict[str, Any]] = []
    for course in db.query(DBCourse).order_by(DBCourse.title, DBCourse.id).all():
        if not course_is_selectable(db, course):
            continue
        try:
            require_course_access(
                db,
                actor,
                course_id=course.id,
                action="read",
                visibility=course.visibility,
            )
        except HTTPException:
            continue
        items.append({
            "id": course.id,
            "title": course.title,
            "subject": course.subject or "",
            "version": course.version,
            "manifestVersion": course.manifest_version,
            "status": course.status,
            "visibility": course.visibility,
        })
    items.sort(key=lambda item: (0 if item["id"] == MASTER_COURSE_ID else 1, item["title"], item["id"]))
    return items


def _owned_conversation(db: Any, actor: DBUser, conversation_id: str) -> DBChatConversation:
    row = db.query(DBChatConversation).filter_by(
        id=conversation_id,
        owner_public_id=actor.public_id,
    ).first()
    if row is None:
        _fail(404, "chat_conversation_unknown", "对话不存在")
    return row


def _owned_attachment(db: Any, actor: DBUser, attachment_id: str) -> DBChatAttachment:
    row = db.query(DBChatAttachment).filter_by(
        id=attachment_id,
        owner_public_id=actor.public_id,
    ).first()
    if row is None:
        _fail(404, "chat_attachment_unknown", "附件不存在")
    return row


def _owned_message(db: Any, actor: DBUser, message_id: str) -> DBChatMessage:
    row = db.query(DBChatMessage).filter_by(
        id=message_id,
        owner_public_id=actor.public_id,
    ).first()
    if row is None:
        _fail(404, "chat_message_unknown", "消息不存在")
    return row


def _attachment_public_state(row: DBChatAttachment) -> str:
    if row.status == "failed" and row.retryable:
        return "failed_retryable"
    return row.status


def attachment_payload(row: DBChatAttachment) -> dict[str, Any]:
    metadata = dict(row.parse_metadata or {})
    summary = {
        key: metadata[key]
        for key in ("page_count", "slide_count", "paragraph_count", "width", "height", "ocr_region_count")
        if key in metadata
    }
    return {
        "id": row.id,
        "conversationId": row.conversation_id,
        "filename": row.filename,
        "fileFormat": row.file_format,
        "mimeType": row.mime_type,
        "fileSize": row.file_size,
        "sourceSha256": row.source_sha256,
        "parserVersion": row.parser_version,
        "parseVersion": row.parse_version,
        "status": _attachment_public_state(row),
        "stage": row.stage,
        "progress": row.progress,
        "summary": summary,
        "parsedPreview": row.parsed_text[:240],
        "locations": list(row.locations or []),
        "warnings": list(row.warnings or []),
        "failure": {
            "code": row.error_code,
            "message": row.error_message,
            "retryable": bool(row.retryable),
        } if row.status in {"partial_failed", "failed"} else None,
        "partialConfirmed": bool(row.partial_confirmed),
        "canSend": row.status == "ready" or (row.status == "partial_failed" and row.partial_confirmed),
        "lockVersion": row.lock_version,
        "createdAt": row.created_at.isoformat() if row.created_at else "",
        "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
    }


def _message_source_refs(
    row: DBChatMessage,
    *,
    db: Any | None,
    actor: DBUser | None,
    course_id: str | None,
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for frozen in list(row.source_refs or []):
        source_ref_id = frozen.get("sourceRefId") or frozen.get("source_ref_id")
        if frozen.get("kind") != "canonical_source" or not source_ref_id or db is None or actor is None:
            refs.append(dict(frozen))
            continue
        projection = project_source_ref(
            db,
            str(source_ref_id),
            actor=actor,
            expected_course_id=(
                frozen.get("courseId")
                or frozen.get("course_id")
                or course_id
            ),
            frozen=frozen,
            permission_as_unavailable=True,
        )
        projected = chat_source_ref(projection)
        for key in ("selection", "selectionReason", "selection_reason"):
            if key in frozen:
                projected[key] = frozen[key]
        refs.append(projected)
    return refs


def _audit_input_refs(row: DBChatMessage) -> list[str]:
    refs = []
    for item in list(row.source_refs or []):
        source_ref_id = item.get("sourceRefId") or item.get("source_ref_id")
        if item.get("kind") == "canonical_source" and source_ref_id:
            refs.append(f"source:{source_ref_id}")
    refs.extend(f"attachment:{attachment_id}" for attachment_id in list(row.attachment_ids or []))
    return list(dict.fromkeys(refs))


def _historical_answer(db: Any, row: DBChatMessage) -> dict[str, Any] | None:
    previous = (
        db.query(DBChatMessage)
        .filter(
            DBChatMessage.owner_public_id == row.owner_public_id,
            DBChatMessage.conversation_id == row.conversation_id,
            DBChatMessage.role == "assistant",
            DBChatMessage.status == "completed",
            DBChatMessage.sequence < row.sequence,
        )
        .order_by(DBChatMessage.sequence.desc())
        .first()
    )
    if previous is None:
        return None
    return {
        "label": "历史已完成回答（非本次结果）",
        "messageId": previous.id,
        "completedAt": previous.completed_at.isoformat() if previous.completed_at else "",
        "preview": " ".join(str(previous.content or "").split())[:180],
        "route": f"/learn?conversation_id={row.conversation_id}&message_id={previous.id}",
    }


def _set_message_agent_audit(
    row: DBChatMessage,
    status: str,
    *,
    failure_message: str = "",
    historical_result: dict[str, Any] | None = None,
) -> None:
    source_count = sum(
        1
        for item in list(row.source_refs or [])
        if item.get("kind") == "canonical_source" and item.get("available", True)
    )
    source_unavailable_count = sum(
        1
        for item in list(row.source_refs or [])
        if item.get("kind") == "canonical_source" and item.get("available") is False
    )
    checkpoint = dict(row.stream_checkpoint or {})
    execution_mode = str(checkpoint.get("modelState") or "")
    checkpoint["agentAudit"] = build_chat_agent_audit(
        message_id=row.id,
        status=status,
        input_refs=_audit_input_refs(row),
        source_count=source_count,
        source_unavailable_count=source_unavailable_count,
        attachment_count=len(list(row.attachment_ids or [])),
        received_characters=len(row.content or ""),
        answer_has_inline_citations=bool(re.search(r"\[(?:S|A)\d+\]", row.content or "")),
        failure_message=failure_message,
        historical_result=historical_result,
        execution_mode=execution_mode,
        run_events=checkpoint.get("runEvents") or (),
    )
    row.stream_checkpoint = checkpoint


def mark_stream_model_state(
    db: Any,
    actor: DBUser,
    assistant_message_id: str,
    *,
    provider: str,
    model: str,
) -> DBChatMessage:
    row = _owned_message(db, actor, assistant_message_id)
    checkpoint = dict(row.stream_checkpoint or {})
    checkpoint["modelState"] = "deterministic_local" if provider == "deterministic" else "live"
    checkpoint["model"] = str(model or "")[:128]
    row.stream_checkpoint = checkpoint
    _set_message_agent_audit(row, row.status)
    row.lock_version += 1
    db.commit()
    db.refresh(row)
    return row


def append_chat_stage_event(
    db: Any,
    actor: DBUser,
    assistant_message_id: str,
    *,
    event_type: str,
    stage_id: str,
    public_status: str,
    owner: str,
    summary: str,
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
    progress: float | None = None,
    retryable: bool = False,
) -> DBChatMessage:
    """Append one real public stage event to the canonical assistant checkpoint."""
    row = _owned_message(db, actor, assistant_message_id)
    checkpoint = dict(row.stream_checkpoint or {})
    checkpoint = append_public_run_event(
        checkpoint,
        run_id=str(checkpoint.get("runId") or f"chat-run-{row.id}"),
        event_type=event_type,
        stage_id=stage_id,
        public_status=public_status,
        owner=owner,
        summary=summary,
        input_refs=input_refs or [],
        output_refs=output_refs or [],
        progress=progress,
        retryable=retryable,
    )
    row.stream_checkpoint = checkpoint
    _set_message_agent_audit(row, row.status)
    row.lock_version += 1
    db.commit()
    db.refresh(row)
    return row


def record_chat_orchestration_metadata(
    db: Any,
    actor: DBUser,
    assistant_message_id: str,
    *,
    mode: str,
    grounding_level: str,
    answerability: str,
    course_grounding: str,
    agent_roles: list[str] | None = None,
    claims: list[dict[str, Any]] | None = None,
) -> DBChatMessage:
    """Persist public, replayable orchestration facts beside the message."""
    row = _owned_message(db, actor, assistant_message_id)
    checkpoint = dict(row.stream_checkpoint or {})
    checkpoint["orchestration"] = {
        "mode": str(mode or "general")[:64],
        "groundingLevel": str(grounding_level or "")[:16],
        "answerability": str(answerability or "")[:32],
        "courseGrounding": str(course_grounding or "")[:32],
        "agentRoles": [str(item)[:80] for item in (agent_roles or [])[:16]],
    }
    checkpoint["claims"] = [
        dict(item) for item in (claims or [])[:32] if isinstance(item, dict)
    ]
    row.stream_checkpoint = checkpoint
    _set_message_agent_audit(row, row.status)
    row.lock_version += 1
    db.commit()
    db.refresh(row)
    return row


def message_payload(
    row: DBChatMessage,
    *,
    db: Any | None = None,
    actor: DBUser | None = None,
    course_id: str | None = None,
) -> dict[str, Any]:
    checkpoint = dict(row.stream_checkpoint or {})
    return {
        "id": row.id,
        "conversationId": row.conversation_id,
        "replyToMessageId": row.reply_to_message_id,
        "sequence": row.sequence,
        "role": row.role,
        "status": row.status,
        "content": row.content,
        "contextRefs": list(row.context_refs or []),
        "attachmentIds": list(row.attachment_ids or []),
        "idempotencyKey": row.idempotency_key,
        "sourceRefs": _message_source_refs(row, db=db, actor=actor, course_id=course_id),
        "resourceLinks": list(row.resource_links or []),
        "streamCheckpoint": checkpoint,
        "contextSnapshot": checkpoint.get("contextSnapshot"),
        "intent": checkpoint.get("intent", "chat"),
        "resourceTypes": list(checkpoint.get("resourceTypes") or []),
        "resourceJobId": checkpoint.get("resourceJobId", ""),
        "resourceStatus": checkpoint.get("resourceStatus", ""),
        "resourceManifest": dict(checkpoint.get("resourceManifest") or {}),
        "contextSnapshotId": checkpoint.get("requestedContextSnapshotId") or (
            checkpoint.get("contextSnapshot") or {}
        ).get("context_snapshot_id", ""),
        "runId": checkpoint.get("runId", ""),
        "runEvents": list(checkpoint.get("runEvents") or []),
        "orchestration": dict(checkpoint.get("orchestration") or {}),
        "claims": list(checkpoint.get("claims") or []),
        "agentAudit": checkpoint.get("agentAudit"),
        "failure": {
            "code": row.error_code,
            "message": row.error_message,
        } if row.status == "failed" else None,
        "lockVersion": row.lock_version,
        "createdAt": row.created_at.isoformat() if row.created_at else "",
        "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
        "completedAt": row.completed_at.isoformat() if row.completed_at else "",
    }


def conversation_payload(
    db: Any,
    row: DBChatConversation,
    *,
    actor: DBUser | None = None,
    include_messages: bool = True,
) -> dict[str, Any]:
    courses = _conversation_courses(db, row)
    payload = {
        "id": row.id,
        "courseId": row.course_id,
        "courseIds": [item["id"] for item in courses],
        "courses": courses,
        "contextMode": "course" if courses else "general",
        "title": row.title,
        "status": row.status,
        "lockVersion": row.lock_version,
        "createdAt": row.created_at.isoformat() if row.created_at else "",
        "updatedAt": row.updated_at.isoformat() if row.updated_at else "",
    }
    if include_messages:
        messages = db.query(DBChatMessage).filter_by(
            conversation_id=row.id,
            owner_public_id=row.owner_public_id,
        ).order_by(DBChatMessage.sequence).all()
        attachments = db.query(DBChatAttachment).filter_by(
            conversation_id=row.id,
            owner_public_id=row.owner_public_id,
        ).order_by(DBChatAttachment.created_at, DBChatAttachment.id).all()
        payload["messages"] = [
            message_payload(item, db=db, actor=actor, course_id=row.course_id)
            for item in messages
        ]
        payload["attachments"] = [attachment_payload(item) for item in attachments]
    return payload


def _parse_image(raw: bytes, filename: str, source_sha256: str) -> dict[str, Any]:
    try:
        from PIL import Image, UnidentifiedImageError

        with Image.open(BytesIO(raw)) as opened:
            opened.load()
            image = opened.convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise DocumentParseError("image_invalid", "图片损坏或无法读取", file_format=Path(filename).suffix.lstrip(".")) from exc

    width, height = image.size
    locations = [{
        "kind": "image",
        "index": 1,
        "label": filename,
        "char_start": 0,
        "char_end": 0,
        "page_number": 1,
        "image_region": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
        "metadata": {"width": width, "height": height},
    }]
    metadata = {"width": width, "height": height, "mode": image.mode, "ocr_region_count": 0}
    warnings: list[str] = []
    text = ""
    parser_version = "edumatrix-image-metadata-v1"

    from app.media_ocr import RapidOCROfflineAdapter

    adapter = RapidOCROfflineAdapter()
    available, engine_version = adapter.runtime()
    if not available:
        warnings.append("本地 OCR 未安装；图片仍可发送，但文字识别依赖当前多模态模型能力。")
        return {
            "status": "ready",
            "text": text,
            "parser_version": parser_version,
            "locations": locations,
            "metadata": metadata,
            "warnings": warnings,
        }
    try:
        page_image_sha256 = _sha256_bytes(image.tobytes())
        regions = adapter.recognize(
            image,
            page_number=1,
            source_sha256=source_sha256,
            page_image_sha256=page_image_sha256,
        )
        text = "\n".join(region.text for region in regions if region.text).strip()
        metadata.update({"ocr_engine": "rapidocr-onnxruntime", "ocr_engine_version": engine_version, "ocr_region_count": len(regions)})
        locations.extend({
            "kind": "image_region",
            "index": index,
            "label": f"图片文字区域 {index}",
            "char_start": 0,
            "char_end": 0,
            "page_number": 1,
            "image_region": dict(region.bbox),
            "metadata": {"regionId": region.region_id, "regionType": region.region_type, "confidence": region.confidence},
        } for index, region in enumerate(regions, 1))
        if not text:
            warnings.append("图片中未识别到可提取文字；回答将依赖当前多模态模型能力。")
        parser_version = "edumatrix-image-ocr-v1"
        return {
            "status": "ready",
            "text": text,
            "parser_version": parser_version,
            "locations": locations,
            "metadata": metadata,
            "warnings": warnings,
        }
    except Exception:
        warnings.append("图片已读取，但本地 OCR 失败；确认后仍可按原图发送。")
        return {
            "status": "partial_failed",
            "text": text,
            "parser_version": parser_version,
            "locations": locations,
            "metadata": metadata,
            "warnings": warnings,
            "error_code": "image_ocr_failed",
            "error_message": "图片文字识别失败，可确认使用原图继续或重试。",
            "retryable": True,
        }


def _parse_attachment_bytes(raw: bytes, filename: str, file_format: str, source_sha256: str) -> dict[str, Any]:
    if file_format in IMAGE_FORMATS:
        return _parse_image(raw, filename, source_sha256)
    parsed = parse_document(raw, filename)
    return {
        "status": "ready",
        "text": parsed.text,
        "parser_version": parsed.parser_version,
        "locations": [location.to_dict() for location in parsed.locations],
        "metadata": dict(parsed.metadata),
        "warnings": list(parsed.warnings),
    }


def _parse_failure(exc: Exception) -> tuple[str, str, bool]:
    if isinstance(exc, DocumentParseError):
        return exc.code, str(exc), exc.code not in PERMANENT_PARSE_ERRORS
    return "attachment_parse_failed", "附件解析暂时失败，请重试。", True


def _resolve_contexts(db: Any, actor: DBUser, conversation: DBChatConversation, refs: list[ContextRef]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for ref in refs:
        try:
            item = resolve_context_ref(db, user=actor, context=ref)
        except ContextResolutionError as exc:
            _fail(exc.status_code, exc.code, str(exc))
        payload = item.model_dump(by_alias=True, exclude_none=True)
        course = payload.get("course") or {}
        if str(course.get("status") or "") in {"archived", "withdrawn"}:
            _fail(409, "chat_course_unavailable", "课程已归档或不可用，不能用于新的对话上下文")
        resolved.append(payload)
    return resolved


def _sendable_attachments(
    db: Any,
    actor: DBUser,
    conversation: DBChatConversation,
    attachment_ids: list[str],
) -> list[DBChatAttachment]:
    if len(set(attachment_ids)) != len(attachment_ids):
        _fail(422, "chat_attachment_duplicate", "同一附件不能重复发送")
    rows = []
    for attachment_id in attachment_ids:
        row = _owned_attachment(db, actor, attachment_id)
        if row.conversation_id != conversation.id:
            _fail(409, "chat_attachment_conversation_mismatch", "附件不属于当前对话")
        if row.status == "partial_failed" and not row.partial_confirmed:
            _fail(409, "chat_attachment_partial_confirmation_required", f"附件 {row.filename} 需要先确认可用部分")
        if row.status != "ready" and not (row.status == "partial_failed" and row.partial_confirmed):
            _fail(409, "chat_attachment_not_ready", f"附件 {row.filename} 尚不可发送")
        rows.append(row)
    return rows


def _attachment_source_ref(row: DBChatAttachment) -> dict[str, Any]:
    return {
        "kind": "chat_attachment",
        "attachmentId": row.id,
        "filename": row.filename,
        "sourceSha256": row.source_sha256,
        "parserVersion": row.parser_version,
        "parseVersion": row.parse_version,
        "locations": list(row.locations or []),
    }


def _context_source_refs(
    db: Any,
    actor: DBUser,
    conversation: DBChatConversation,
    contexts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    explicit_source_ids: set[str] = set()
    for item in contexts:
        source = item.get("sourceRef") or {}
        if source.get("id"):
            explicit_source_ids.add(str(source["id"]))
            projection = project_source_ref(
                db,
                str(source["id"]),
                actor=actor,
                expected_course_id=(
                    source.get("courseId")
                    or source.get("course_id")
                    or conversation.course_id
                ),
            )
            if not projection["available"]:
                # A version/document drift is a real Level-D conflict.  Keep the
                # frozen projection so the professional run can explain the
                # conflict and request confirmation instead of failing before a
                # run exists.  Missing identities remain hard errors.
                if projection.get("reason_code") not in {
                    "source_ref_version_changed",
                    "source_ref_content_changed",
                    "source_document_changed",
                    "document_version_changed",
                    "source_unavailable",
                }:
                    _fail(409, "chat_source_unavailable", projection["reason"] or "当前来源不可用")
            frozen = chat_source_ref(projection)
            frozen["selection"] = "selected"
            refs.append(frozen)

    # Selecting a course is sufficient to enter the course-grounded branch.
    # When the caller did not choose a specific source, read the course's
    # canonical source refs under the existing source/permission contract.
    if not explicit_source_ids:
        course_ids: list[str] = []
        chapter_ids: set[str] = set()
        for item in contexts:
            course = item.get("course") or {}
            course_id = str(course.get("id") or item.get("courseId") or "").strip()
            if course_id and course_id not in course_ids:
                course_ids.append(course_id)
            chapter = item.get("chapter") or {}
            chapter_id = str(chapter.get("id") or item.get("chapterId") or "").strip()
            if chapter_id:
                chapter_ids.add(chapter_id)
        if conversation.course_id and conversation.course_id not in course_ids:
            course_ids.insert(0, str(conversation.course_id))
        from app.canonical_retrieval import list_canonical_source_refs
        for course_id in course_ids:
            projections = list_canonical_source_refs(
                db,
                course_id=course_id,
                actor=actor,
                chapter_ids=sorted(chapter_ids) if chapter_ids else None,
            )
            for projection in projections:
                source_ref_id = str(projection.get("source_ref_id") or "")
                if source_ref_id in explicit_source_ids:
                    continue
                if not projection["available"] and projection.get("reason_code") not in {
                    "source_ref_version_changed",
                    "source_ref_content_changed",
                    "source_document_changed",
                    "document_version_changed",
                    "source_unavailable",
                }:
                    # Do not weaken missing-object or permission protections for
                    # automatically discovered sources.
                    continue
                frozen = chat_source_ref(projection)
                frozen["selection"] = "adopted" if projection["available"] else "candidate"
                refs.append(frozen)
    return refs


def _latest_profile_snapshot_for_course(
    db: Any,
    actor: DBUser,
    course_id: str | None,
) -> DBProfileSnapshot | None:
    """Use the existing learner snapshot as the read-only profile/mastery input."""
    rows = (
        db.query(DBProfileSnapshot)
        .filter_by(owner_public_id=actor.public_id)
        .order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc())
        .all()
    )
    for row in rows:
        body = row.snapshot if isinstance(row.snapshot, dict) else {}
        scoped_course = body.get("course_id") or (body.get("course_context") or {}).get("courseId")
        if not course_id or scoped_course in {None, course_id}:
            return row
    return None


def _context_snapshot(
    db: Any,
    actor: DBUser,
    conversation: DBChatConversation,
    contexts: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    attachments: list[DBChatAttachment],
    conversation_message_ids: list[str],
) -> dict[str, Any]:
    """Freeze the complete read boundary for one chat run without a second store."""
    course_ids: list[str] = []
    chapter_id = ""
    knowledge_scope: list[str] = []
    for item in contexts:
        course = item.get("course") or {}
        course_id = str(course.get("id") or item.get("courseId") or "")
        if course_id and course_id not in course_ids:
            course_ids.append(course_id)
        chapter = item.get("chapter") or {}
        if not chapter_id and chapter.get("id"):
            chapter_id = str(chapter["id"])
        point = item.get("knowledgePoint") or {}
        if point.get("id") and str(point["id"]) not in knowledge_scope:
            knowledge_scope.append(str(point["id"]))
    if conversation.course_id and conversation.course_id not in course_ids:
        course_ids.insert(0, str(conversation.course_id))
    course_id = course_ids[0] if course_ids else None
    source_ref_ids = list(dict.fromkeys(
        str(item.get("sourceRefId") or item.get("source_ref_id"))
        for item in source_refs
        if item.get("kind") == "canonical_source"
        and (item.get("sourceRefId") or item.get("source_ref_id"))
    ))
    profile = _latest_profile_snapshot_for_course(db, actor, course_id)
    profile_snapshot_id = profile.id if profile is not None else None
    profile_body = profile.snapshot if profile is not None and isinstance(profile.snapshot, dict) else {}
    profile_row = db.get(DBStudentProfile, actor.username)
    point = db.get(DBKnowledgePoint, knowledge_scope[0]) if knowledge_scope else None
    adaptation = build_profile_adaptation(
        profile,
        profile=profile_row,
        knowledge_point=(
            {"id": point.id, "title": point.title, "code": point.code}
            if point is not None else None
        ),
    ) if profile_has_signal(profile, profile_row) else {}
    has_mastery = any(
        profile_body.get(key)
        for key in ("concept_mastery", "mastery", "knowledge_traces", "mastery_evidence")
    )
    mastery_snapshot_id = profile_snapshot_id if has_mastery else None
    source_material = [
        {
            "sourceRefId": item.get("sourceRefId") or item.get("source_ref_id"),
            "contentHash": item.get("contentHash") or item.get("content_hash"),
            "documentVersion": item.get("documentVersion") or item.get("document_version"),
            "parserVersion": item.get("parserVersion") or item.get("parser_version"),
            "available": item.get("available", True),
        }
        for item in source_refs
        if item.get("kind") == "canonical_source"
    ] + [
        {
            "attachmentId": row.id,
            "sourceSha256": row.source_sha256,
            "parseVersion": row.parse_version,
            "parserVersion": row.parser_version,
        }
        for row in attachments
    ]
    snapshot = {
        "schema_version": "edumatrix.chat-context-snapshot.v1",
        "course_id": course_id,
        "course_ids": course_ids,
        "chapter_id": chapter_id or None,
        "knowledge_scope": knowledge_scope,
        "source_ref_ids": source_ref_ids,
        "attachment_ids": [row.id for row in attachments],
        "profile_snapshot_id": profile_snapshot_id,
        "mastery_snapshot_id": mastery_snapshot_id,
        "profile_context": profile_prompt_context(adaptation) if adaptation else {},
        "profile_adaptation_plan": profile_prompt_context(adaptation) if adaptation else {},
        "profile_adaptation_summary": str(adaptation.get("summary") or "") if adaptation else "",
        "conversation_message_ids": list(dict.fromkeys(conversation_message_ids)),
        "source_snapshot_hash": _canonical_hash(source_material),
    }
    snapshot["context_snapshot_id"] = "ctx-" + _canonical_hash(snapshot)[:32]
    return snapshot


def _message_knowledge_point_id(row: DBChatMessage, requested_id: str | None) -> str:
    if requested_id:
        return requested_id
    for context in list(row.context_refs or []):
        knowledge_point = context.get("knowledgePoint") or {}
        if knowledge_point.get("id"):
            return str(knowledge_point["id"])
    _fail(422, "chat_resource_knowledge_point_required", "当前问答没有明确知识点，请先从学习路径或资源页进入对话")


def _message_source_ref_ids(row: DBChatMessage) -> list[str]:
    ids = [
        str(item.get("sourceRefId") or item.get("source_ref_id"))
        for item in list(row.source_refs or [])
        if item.get("kind") == "canonical_source" and (item.get("sourceRefId") or item.get("source_ref_id"))
        and item.get("selection", "selected") == "selected"
    ]
    unique = list(dict.fromkeys(ids))
    if not unique:
        _fail(422, "chat_resource_source_required", "当前回答没有可追溯的课程来源，暂不能生成学习资源")
    return unique


def _stream_source_materials(
    db: Any,
    actor: DBUser,
    conversation: DBChatConversation,
    source_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    materials: list[dict[str, Any]] = []
    for frozen in source_refs:
        source_ref_id = frozen.get("sourceRefId") or frozen.get("source_ref_id")
        if frozen.get("kind") != "canonical_source" or not source_ref_id:
            continue
        projection = project_source_ref(
            db,
            str(source_ref_id),
            actor=actor,
            expected_course_id=(
                frozen.get("courseId")
                or frozen.get("course_id")
                or conversation.course_id
            ),
            frozen=frozen,
            permission_as_unavailable=True,
        )
        material = chat_source_ref(projection)
        if frozen.get("selection"):
            material["selection"] = frozen["selection"]
        materials.append(material)
    return materials


_RESOURCE_LABELS = {
    "handout": "个性化讲义",
    "mind_map": "思维导图",
    "quiz": "测验题",
    "training_task": "实训任务书",
    "code_sandbox": "代码沙盒",
    "video": "视频推荐",
    "deck": "PPT/网页课件",
    "interactive_model": "可交互模型",
    "feynman": "费曼复述任务",
}


def _resource_context_values(
    db: Any,
    row: DBChatMessage,
    conversation: DBChatConversation,
) -> dict[str, Any]:
    checkpoint = dict(row.stream_checkpoint or {})
    snapshot = dict(checkpoint.get("contextSnapshot") or {})
    contexts = list(row.context_refs or [])
    course_id = str(conversation.course_id or snapshot.get("course_id") or "")
    knowledge_point_id = str((snapshot.get("knowledge_scope") or [""])[0] or "")
    path_id = ""
    task_id = ""
    for context in contexts:
        point = context.get("knowledgePoint") or {}
        knowledge_point_id = knowledge_point_id or str(point.get("id") or "")
        task = context.get("task") or {}
        task_id = task_id or str(task.get("id") or context.get("taskId") or "")
        path_id = path_id or str(task.get("pathId") or context.get("pathId") or "")
        course = context.get("course") or {}
        course_id = course_id or str(course.get("id") or context.get("courseId") or "")
    if not path_id and task_id:
        # ContextResolution exposes the authorized path node as a task summary;
        # resolve its parent path here without widening the client context
        # schema or trusting a caller-supplied path id.
        path_node = db.query(DBPathNode).filter_by(id=task_id).first()
        if path_node is not None:
            path = (
                db.query(DBLearningPath)
                .filter_by(
                    id=path_node.learning_path_id,
                    owner_public_id=conversation.owner_public_id,
                    course_id=course_id,
                )
                .first()
            )
            if path is not None:
                path_id = str(path.id)
    source_ref_ids = list(dict.fromkeys(
        str(item.get("sourceRefId") or item.get("source_ref_id"))
        for item in list(row.source_refs or [])
        if item.get("kind") == "canonical_source"
        and (item.get("sourceRefId") or item.get("source_ref_id"))
    ))
    return {
        "course_id": course_id,
        "knowledge_point_id": knowledge_point_id,
        "profile_snapshot_id": str(snapshot.get("profile_snapshot_id") or ""),
        "context_snapshot_id": str(
            checkpoint.get("requestedContextSnapshotId")
            or snapshot.get("context_snapshot_id")
            or ""
        ),
        "source_ref_ids": source_ref_ids,
        "path_id": path_id,
        "task_id": task_id,
        "snapshot": snapshot,
    }


def _resource_links_from_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    job_id = str(job.get("job_id") or "")
    job_status = str(job.get("status") or "")
    for item in list(job.get("items") or []):
        resource_type = str(item.get("type") or "")
        if not resource_type:
            continue
        resource = item.get("resource") or {}
        published = item.get("state") == "succeeded" and bool(resource.get("resource_id"))
        route = str(resource.get("route") or "") if published else f"/workspace/resources/bundles/{job_id}"
        state = "completed" if published else "failed" if item.get("state") == "failed" else "generating"
        links.append({
            "kind": "generation_job",
            "type": resource_type,
            "title": str(item.get("title") or _RESOURCE_LABELS.get(resource_type, resource_type)),
            "taskId": job_id,
            "status": state,
            "route": route,
            "resourceId": str(resource.get("resource_id") or ""),
            "resourceVersionId": str((resource.get("version") or {}).get("id") or ""),
        })
    return links


def _resource_chat_adaptation_note(snapshot: dict[str, Any]) -> str:
    """Return one short learner-facing note for the resource-run reply."""
    plan = snapshot.get("profile_adaptation_plan") or snapshot.get("profile_context") or {}
    if not isinstance(plan, dict) or not plan:
        return "本轮资源会按当前学习情况组织内容。"
    label = str(plan.get("difficulty_label") or "当前难度").strip()
    focus = str(plan.get("content_focus") or "当前知识点").strip()
    style = str(plan.get("explanation_style") or "适合你的讲解方式").strip()
    return f"本轮已按你的学习情况采用“{label}”，围绕{focus}并以{style}组织内容。"


def _project_resource_events(
    checkpoint: dict[str, Any],
    *,
    job: dict[str, Any],
) -> dict[str, Any]:
    """Project the resource task's sanitized event list into the Chat run."""
    run_id = str(checkpoint.get("runId") or "")
    job_id = str(job.get("job_id") or "")
    next_checkpoint = dict(checkpoint)
    for raw in list(job.get("events") or []):
        event = dict(raw or {})
        event_type = str(event.get("event_type") or event.get("eventType") or "")
        if event_type not in {
            "stage.started", "stage.progress", "stage.completed", "stage.failed",
            "resource.item.started", "resource.item.progress", "resource.item.completed",
            "resource.item.failed", "review_gate.started", "review_gate.passed",
            "review_gate.failed", "publish.completed", "run.completed", "run.failed",
        }:
            continue
        input_refs = list(event.get("input_refs") or event.get("inputRefs") or [])
        output_refs = list(event.get("output_refs") or event.get("outputRefs") or [])
        if job_id:
            input_refs.append(f"resource-job:{job_id}")
        original_run_id = str(event.get("run_id") or event.get("runId") or "")
        if original_run_id and original_run_id != run_id:
            input_refs.append(f"run:{original_run_id}")
        next_checkpoint = append_public_run_event(
            next_checkpoint,
            run_id=run_id,
            event_type=event_type,
            stage_id=str(event.get("stage_id") or event.get("stageId") or ""),
            resource_item_id=str(event.get("resource_item_id") or event.get("resourceItemId") or ""),
            public_status=str(event.get("status") or event.get("publicStatus") or "queued"),
            owner=str(event.get("owner") or "Resource Supervisor"),
            summary=str(event.get("summary") or ""),
            input_refs=input_refs,
            output_refs=output_refs,
            progress=event.get("progress"),
            retryable=bool(event.get("retryable", False)),
        )
    next_checkpoint["resourceJobId"] = job_id
    next_checkpoint["resourceStatus"] = str(job.get("status") or "")
    next_checkpoint["resourceManifest"] = dict(job.get("manifest") or {})
    return next_checkpoint


def execute_resource_chat_run(
    db: Any,
    actor: DBUser,
    assistant_message_id: str,
    *,
    event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Create/reuse and execute one B09 resource job for a canonical Chat message."""
    row = _owned_message(db, actor, assistant_message_id)
    if row.role != "assistant":
        _fail(409, "chat_resource_assistant_required", "资源运行必须绑定回答消息")
    conversation = _owned_conversation(db, actor, row.conversation_id)
    checkpoint = dict(row.stream_checkpoint or {})
    resource_types = [
        str(value) for value in (checkpoint.get("resourceTypes") or [])
        if str(value) in GENERATION_RESOURCE_TYPES
    ]
    if not resource_types:
        _fail(422, "chat_resource_types_required", "资源生成消息至少需要一种资源类型")
    context_values = _resource_context_values(db, row, conversation)
    missing = [
        label for label, value in (
            ("课程", context_values["course_id"]),
            ("学习画像", context_values["profile_snapshot_id"]),
            ("课程来源", context_values["source_ref_ids"]),
        ) if not value
    ]
    if missing:
        _fail(422, "chat_resource_context_required", f"资源生成需要明确的{'、'.join(missing)}上下文")
    if len(resource_types) == 1:
        scope = "single"
    elif 2 <= len(resource_types) <= len(GENERATION_RESOURCE_TYPES):
        scope = "bundle"
    task_id = str(checkpoint.get("resourceJobId") or "")
    if task_id:
        job = generation_job_payload(db, actor, task_id)
    else:
        base_title = str(row.content or "当前课程资源").strip()[:120]
        labels = [(_RESOURCE_LABELS.get(item, item), item) for item in resource_types]
        items = [{
            "type": resource_type,
            "title": f"{label} · {base_title}"[:256],
            "source_ref_ids": context_values["source_ref_ids"],
            "completion_rule": f"完成{label}并做一次简短回顾。",
        } for label, resource_type in labels]
        try:
            job = create_generation_job(
                db,
                actor,
                course_id=context_values["course_id"],
                knowledge_point_id=context_values["knowledge_point_id"] or None,
                profile_snapshot_id=context_values["profile_snapshot_id"],
                idempotency_key=f"chat-resource-run-{row.id}",
                items=items,
                scope=scope,
                path_id=context_values["path_id"] or None,
                task_id=context_values["task_id"] or None,
                learning_goal=base_title,
                conversation_id=conversation.id,
                message_id=row.id,
                resource_intent=str(checkpoint.get("intent") or "resource_generation"),
                user_instruction=row.content or "",
                context_snapshot_id=context_values["context_snapshot_id"] or None,
                selected_resource_types=resource_types,
            )
        except ResourceBundleError as exc:
            _fail(422, exc.code, str(exc))
        task_id = str(job.get("job_id") or "")

    if str(job.get("status") or "") not in {"succeeded", "completed"}:
        # The browser showcase deliberately runs with the local deterministic
        # provider. Keep that mode on the same Chat-created job, but use the
        # existing governed demo executor instead of requiring a live model.
        # Production and configured OpenAI-compatible providers retain the
        # real Planner/Supervisor execution path below.
        if (
            CONFIG.demo_mode
            and CONFIG.chat_resource_demo_execution
            and CONFIG.llm_provider.lower().strip() == "deterministic"
        ):
            job = execute_generation_job_demo(db, actor, task_id)
        else:
            job = execute_generation_job(db, actor, task_id, event_callback=event_callback)
    checkpoint = _project_resource_events(checkpoint, job=job)
    resource_links = _resource_links_from_job(job)
    job_status = str(job.get("status") or "")
    if job_status in {"succeeded", "completed", "partial_success"}:
        row.status = "completed"
        row.error_code = ""
        row.error_message = ""
        row.content = (
            f"资源生成已完成：成功 {len(job.get('checkpoint', {}).get('succeeded_types') or [])} 项，"
            f"失败 {len(job.get('checkpoint', {}).get('failed_types') or [])} 项。\n\n"
            f"{_resource_chat_adaptation_note(context_values['snapshot'])}"
        )
    else:
        row.status = "failed"
        row.error_code = str(job.get("failure_code") or "chat_resource_generation_failed")[:64]
        row.error_message = str(job.get("failure_reason") or "资源生成失败，可重试失败资源项。")[:1000]
        checkpoint["resourceFailure"] = {"code": row.error_code, "message": row.error_message}
    row.content_sha256 = _sha256_text(row.content or "")
    row.resource_links = resource_links
    row.stream_checkpoint = checkpoint
    _set_message_agent_audit(row, row.status, failure_message=row.error_message)
    row.completed_at = _now()
    row.lock_version += 1
    db.commit()
    db.refresh(row)
    return {
        "job": job,
        "message": message_payload(row, db=db, actor=actor, course_id=conversation.course_id),
        "run_events": list(checkpoint.get("runEvents") or []),
        "resource_links": resource_links,
    }


def create_message_pair(db: Any, actor: DBUser, conversation_id: str, payload: MessageInput) -> dict[str, Any]:
    conversation = _owned_conversation(db, actor, conversation_id)
    if conversation.status != "active":
        _fail(409, "chat_conversation_archived", "已归档对话不能继续发送消息")
    content = payload.content.strip()
    return_to = _safe_return_to(payload.return_to)
    intent = str(payload.intent or "chat")
    resource_types = _message_resource_types(payload)
    requested_context_snapshot_id = str(payload.context_snapshot_id or "").strip()
    attachments = _sendable_attachments(db, actor, conversation, payload.attachment_ids)
    if not content and not attachments:
        _fail(422, "chat_message_empty", "请输入问题或添加可发送附件")
    contexts = _resolve_contexts(db, actor, conversation, payload.context_refs)
    frozen_attachments = [_attachment_source_ref(row) for row in attachments]
    source_refs = _context_source_refs(db, actor, conversation, contexts) + frozen_attachments
    fingerprint = _canonical_hash({
        "conversationId": conversation.id,
        "content": content,
        "attachments": frozen_attachments,
        "contexts": contexts,
        "intent": intent,
        "resourceTypes": resource_types,
        "contextSnapshotId": requested_context_snapshot_id,
        "returnTo": return_to,
    })
    existing = db.query(DBChatMessage).filter_by(
        owner_public_id=actor.public_id,
        idempotency_key=payload.idempotency_key,
    ).first()
    if existing is not None:
        if existing.conversation_id != conversation.id or existing.role != "user" or existing.content_sha256 != fingerprint:
            _fail(409, "chat_message_idempotency_conflict", "同一操作标识已经用于其他消息")
        assistant = db.query(DBChatMessage).filter_by(
            owner_public_id=actor.public_id,
            conversation_id=conversation.id,
            reply_to_message_id=existing.id,
            role="assistant",
        ).first()
        if assistant is None:
            _fail(409, "chat_message_pair_incomplete", "消息状态不完整，请刷新后重试")
        return {
            "created": False,
            "userMessage": message_payload(existing, db=db, actor=actor, course_id=conversation.course_id),
            "assistantMessage": message_payload(assistant, db=db, actor=actor, course_id=conversation.course_id),
        }

    last_sequence = db.query(func.max(DBChatMessage.sequence)).filter_by(conversation_id=conversation.id).scalar() or 0
    user_message = DBChatMessage(
        conversation_id=conversation.id,
        owner_public_id=actor.public_id,
        sequence=last_sequence + 1,
        role="user",
        status="completed",
        content=content,
        content_sha256=fingerprint,
        idempotency_key=payload.idempotency_key,
        context_refs=contexts,
        attachment_ids=[row.id for row in attachments],
        source_refs=source_refs,
        stream_checkpoint={"status": "completed", "returnTo": return_to},
        completed_at=_now(),
    )
    db.add(user_message)
    db.flush()
    previous_message_ids = [
        str(item.id)
        for item in db.query(DBChatMessage)
        .filter(
            DBChatMessage.conversation_id == conversation.id,
            DBChatMessage.owner_public_id == actor.public_id,
            DBChatMessage.id != user_message.id,
            DBChatMessage.status == "completed",
        )
        .order_by(DBChatMessage.sequence)
        .all()
    ]
    context_snapshot = _context_snapshot(
        db,
        actor,
        conversation,
        contexts,
        source_refs,
        attachments,
        [*previous_message_ids, str(user_message.id)],
    )
    user_message.stream_checkpoint = {
        "status": "completed",
        "returnTo": return_to,
        "intent": intent,
        "resourceTypes": resource_types,
        "requestedContextSnapshotId": requested_context_snapshot_id,
        "contextSnapshot": context_snapshot,
    }
    assistant_key = "assistant-" + _sha256_text(f"{actor.public_id}:{user_message.id}")[:40]
    assistant_message = DBChatMessage(
        conversation_id=conversation.id,
        owner_public_id=actor.public_id,
        reply_to_message_id=user_message.id,
        sequence=last_sequence + 2,
        role="assistant",
        status="queued",
        content="",
        content_sha256=_sha256_text(""),
        idempotency_key=assistant_key,
        context_refs=contexts,
        attachment_ids=[row.id for row in attachments],
        source_refs=source_refs,
        stream_checkpoint={
            "status": "queued",
            "receivedCharacters": 0,
            "returnTo": return_to,
            "intent": intent,
            "resourceTypes": resource_types,
            "requestedContextSnapshotId": requested_context_snapshot_id,
            "contextSnapshot": context_snapshot,
        },
    )
    db.add(assistant_message)
    db.flush()
    checkpoint = append_public_run_event(
        dict(assistant_message.stream_checkpoint or {}),
        run_id=f"chat-run-{assistant_message.id}",
        event_type="run.started",
        public_status="queued",
        owner="Chat Orchestrator",
        summary="已接收问题，等待真实回答运行开始。",
        input_refs=[f"chat:{user_message.id}"],
        progress=0.0,
        retryable=False,
    )
    checkpoint = append_public_run_event(
        checkpoint,
        run_id=f"chat-run-{assistant_message.id}",
        event_type="context.frozen",
        stage_id="context",
        public_status="completed",
        owner="Context Builder",
        summary=f"已冻结课程、来源和 {len(attachments)} 个附件的本次上下文。",
        input_refs=[f"chat:{user_message.id}"],
        output_refs=[f"context:{context_snapshot['context_snapshot_id']}"],
        progress=1.0,
        retryable=False,
    )
    profile_summary = str(context_snapshot.get("profile_adaptation_summary") or "").strip()
    if profile_summary:
        checkpoint = append_public_run_event(
            checkpoint,
            run_id=f"chat-run-{assistant_message.id}",
            event_type="stage.completed",
            stage_id="profile_adaptation",
            public_status="completed",
            owner="Context Builder",
            summary=f"本轮按学习者画像调整：{profile_summary[:260]}",
            input_refs=[
                f"profile:{context_snapshot.get('profile_snapshot_id')}"
            ] if context_snapshot.get("profile_snapshot_id") else [],
            output_refs=[f"context:{context_snapshot['context_snapshot_id']}"],
            progress=0.3,
            retryable=False,
        )
    assistant_message.stream_checkpoint = checkpoint
    _set_message_agent_audit(assistant_message, "queued")
    conversation.updated_at = _now()
    conversation.lock_version += 1
    db.commit()
    return {
        "created": True,
        "userMessage": message_payload(user_message, db=db, actor=actor, course_id=conversation.course_id),
        "assistantMessage": message_payload(assistant_message, db=db, actor=actor, course_id=conversation.course_id),
    }


def load_stream_context(db: Any, actor: DBUser, user_message_id: str) -> dict[str, Any]:
    user_message = _owned_message(db, actor, user_message_id)
    if user_message.role != "user":
        _fail(409, "chat_stream_user_message_required", "流式回答必须绑定用户消息")
    conversation = _owned_conversation(db, actor, user_message.conversation_id)
    assistant = db.query(DBChatMessage).filter_by(
        owner_public_id=actor.public_id,
        conversation_id=conversation.id,
        reply_to_message_id=user_message.id,
        role="assistant",
    ).first()
    if assistant is None:
        _fail(409, "chat_stream_assistant_missing", "回答消息不存在")
    attachments = _sendable_attachments(db, actor, conversation, list(user_message.attachment_ids or []))
    history_rows = (
        db.query(DBChatMessage)
        .filter(
            DBChatMessage.owner_public_id == actor.public_id,
            DBChatMessage.conversation_id == conversation.id,
            DBChatMessage.sequence < user_message.sequence,
            DBChatMessage.status == "completed",
        )
        .order_by(DBChatMessage.sequence.desc())
        .limit(10)
        .all()
    )
    return {
        "conversation": conversation,
        "user_message": user_message,
        "assistant_message": assistant,
        "history": [
            message_payload(row, db=db, actor=actor, course_id=conversation.course_id)
            for row in reversed(history_rows)
        ],
        "attachments": [{
            "id": row.id,
            "filename": row.filename,
            "file_format": row.file_format,
            "mime_type": row.mime_type,
            "raw_bytes": bytes(row.raw_bytes or b""),
            "parsed_text": row.parsed_text,
            "parser_version": row.parser_version,
            "parse_version": row.parse_version,
            "locations": list(row.locations or []),
            "source_sha256": row.source_sha256,
            "warnings": list(row.warnings or []),
        } for row in attachments],
        "context_refs": list(user_message.context_refs or []),
        "context_snapshot": dict((user_message.stream_checkpoint or {}).get("contextSnapshot") or {}),
        "intent": str((user_message.stream_checkpoint or {}).get("intent") or "chat"),
        "resource_types": list((user_message.stream_checkpoint or {}).get("resourceTypes") or []),
        "requested_context_snapshot_id": str((user_message.stream_checkpoint or {}).get("requestedContextSnapshotId") or ""),
        "source_refs": list(user_message.source_refs or []),
        "source_materials": _stream_source_materials(
            db, actor, conversation, list(user_message.source_refs or [])
        ),
        "return_to": str((user_message.stream_checkpoint or {}).get("returnTo") or ""),
    }


def begin_stream_message(db: Any, actor: DBUser, assistant_message_id: str) -> DBChatMessage:
    row = _owned_message(db, actor, assistant_message_id)
    if row.role != "assistant":
        _fail(409, "chat_stream_assistant_required", "当前消息不是回答消息")
    if row.status == "completed":
        return row
    if row.status not in {"queued", "streaming"}:
        _fail(409, "chat_stream_not_startable", "当前回答需要先点击继续")
    row.status = "streaming"
    checkpoint = dict(row.stream_checkpoint or {})
    checkpoint["status"] = "streaming"
    if checkpoint.get("orchestration", {}).get("mode") not in {"course_professional", "resource_generation"}:
        checkpoint = append_public_run_event(
            checkpoint,
            run_id=str(checkpoint.get("runId") or f"chat-run-{row.id}"),
            event_type="stage.started",
            stage_id="answer_generation",
            public_status="running",
            owner="Answer Agent",
            summary="正在根据已冻结的上下文生成回答。",
            input_refs=[f"chat:{row.reply_to_message_id or row.id}"],
            progress=0.1,
            retryable=True,
        )
    row.stream_checkpoint = checkpoint
    _set_message_agent_audit(row, "streaming")
    row.lock_version += 1
    db.commit()
    db.refresh(row)
    return row


def persist_stream_content(db: Any, actor: DBUser, assistant_message_id: str, content: str) -> DBChatMessage:
    row = _owned_message(db, actor, assistant_message_id)
    if row.role != "assistant" or row.status != "streaming":
        _fail(409, "chat_stream_not_active", "回答已经停止或结束")
    row.content = content
    row.content_sha256 = _sha256_text(content)
    checkpoint = dict(row.stream_checkpoint or {})
    checkpoint.update({"status": "streaming", "receivedCharacters": len(content)})
    row.stream_checkpoint = checkpoint
    _set_message_agent_audit(row, "streaming")
    row.lock_version += 1
    db.commit()
    db.refresh(row)
    return row


def complete_stream_message(
    db: Any,
    actor: DBUser,
    assistant_message_id: str,
    *,
    content: str,
    source_refs: list[dict[str, Any]] | None = None,
    resource_links: list[dict[str, Any]] | None = None,
) -> DBChatMessage:
    row = _owned_message(db, actor, assistant_message_id)
    if row.role != "assistant":
        _fail(409, "chat_stream_assistant_required", "当前消息不是回答消息")
    if row.status == "stopped":
        return row
    row.content = content
    row.content_sha256 = _sha256_text(content)
    row.status = "completed"
    row.source_refs = list(source_refs or row.source_refs or [])
    row.resource_links = list(resource_links or [])
    checkpoint = dict(row.stream_checkpoint or {})
    checkpoint.update({"status": "completed", "receivedCharacters": len(content)})
    run_id = str(checkpoint.get("runId") or f"chat-run-{row.id}")
    professional = checkpoint.get("orchestration", {}).get("mode") == "course_professional"
    checkpoint = append_public_run_event(
        checkpoint,
        run_id=run_id,
        event_type="stage.completed",
        stage_id="synthesizer" if professional else "answer_generation",
        public_status="completed",
        owner="Synthesizer" if professional else "Answer Agent",
        summary=(
            f"已综合课程证据核验结果并保存回答，共 {len(content)} 个字符。"
            if professional
            else f"回答已生成并保存，共 {len(content)} 个字符。"
        ),
        input_refs=[f"chat:{row.reply_to_message_id or row.id}"],
        output_refs=[f"chat:{row.id}"],
        progress=0.9,
        retryable=False,
    )
    checkpoint = append_public_run_event(
        checkpoint,
        run_id=run_id,
        event_type="run.completed",
        public_status="completed",
        owner="Chat Orchestrator",
        summary="本次回答运行完成，公开轨迹已保存。",
        input_refs=[f"chat:{row.reply_to_message_id or row.id}"],
        output_refs=[f"chat:{row.id}"],
        progress=1.0,
        retryable=False,
    )
    row.stream_checkpoint = checkpoint
    _set_message_agent_audit(row, "completed")
    row.error_code = ""
    row.error_message = ""
    row.completed_at = _now()
    row.lock_version += 1
    db.commit()
    db.refresh(row)
    return row


def fail_stream_message(db: Any, actor: DBUser, assistant_message_id: str, code: str, message: str) -> DBChatMessage:
    row = _owned_message(db, actor, assistant_message_id)
    if row.role != "assistant" or row.status in {"completed", "stopped"}:
        return row
    row.status = "failed"
    row.error_code = str(code or "chat_stream_failed")[:64]
    row.error_message = str(message or "回答暂时失败，请重试。")[:1000]
    checkpoint = dict(row.stream_checkpoint or {})
    checkpoint.update({"status": "failed", "receivedCharacters": len(row.content or "")})
    run_id = str(checkpoint.get("runId") or f"chat-run-{row.id}")
    professional = checkpoint.get("orchestration", {}).get("mode") == "course_professional"
    checkpoint = append_public_run_event(
        checkpoint,
        run_id=run_id,
        event_type="stage.failed",
        stage_id="synthesizer" if professional else "answer_generation",
        public_status="failed",
        owner="Synthesizer" if professional else "Answer Agent",
        summary=(
            "课程综合回答模型失败，已保留当前内容。"
            if professional
            else "真实模型回答失败，已保留当前内容。"
        ),
        input_refs=[f"chat:{row.reply_to_message_id or row.id}"],
        progress=None,
        retryable=True,
    )
    checkpoint = append_public_run_event(
        checkpoint,
        run_id=run_id,
        event_type="run.failed",
        public_status="failed",
        owner="Chat Orchestrator",
        summary="本次运行失败，可从保留的内容继续或重试。",
        input_refs=[f"chat:{row.reply_to_message_id or row.id}"],
        progress=None,
        retryable=True,
    )
    row.stream_checkpoint = checkpoint
    _set_message_agent_audit(
        row,
        "failed",
        failure_message=row.error_message,
        historical_result=_historical_answer(db, row),
    )
    row.lock_version += 1
    db.commit()
    db.refresh(row)
    return row


@router.post("/conversations", status_code=201)
async def create_conversation(payload: ConversationInput, current_user: DBUser = Depends(get_current_user)):
    def operation(db: Any) -> dict[str, Any]:
        requested_ids = [str(item).strip() for item in payload.course_ids if str(item).strip()]
        if payload.course_id and payload.course_id not in requested_ids:
            requested_ids.insert(0, payload.course_id)
        if len(set(requested_ids)) != len(requested_ids):
            _fail(422, "chat_course_duplicate", "同一门课程不能重复选择")
        courses = [_course(db, current_user, course_id) for course_id in requested_ids]
        course = courses[0] if courses else None
        title = " ".join(payload.title.split())[:256] or (f"{course.title}对话" if course else "新对话")
        row = DBChatConversation(owner_public_id=current_user.public_id, course_id=course.id if course else None, title=title)
        db.add(row)
        db.commit()
        result = conversation_payload(db, row, actor=current_user)
        if courses:
            result["courseIds"] = [item.id for item in courses]
            result["courses"] = [{
                "id": item.id,
                "title": item.title,
                "version": item.version,
                "status": item.status,
            } for item in courses]
            result["contextMode"] = "course"
        return result
    return await run_db_op(operation)


@router.get("/courses")
async def list_chat_courses(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(
        lambda db: {
            "schemaVersion": "edumatrix.chat-course-catalog.v1",
            "courses": _chat_course_catalog(db, current_user),
        }
    )


@router.get("/conversations")
async def list_conversations(current_user: DBUser = Depends(get_current_user)):
    def operation(db: Any) -> dict[str, Any]:
        rows = db.query(DBChatConversation).filter_by(
            owner_public_id=current_user.public_id,
            status="active",
        ).order_by(DBChatConversation.updated_at.desc(), DBChatConversation.id).all()
        return {
            "schemaVersion": "edumatrix.chat-conversation-list.v1",
            "items": [conversation_payload(db, row, actor=current_user, include_messages=False) for row in rows],
        }
    return await run_db_op(operation)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(
        lambda db: conversation_payload(
            db,
            _owned_conversation(db, current_user, conversation_id),
            actor=current_user,
        )
    )


@router.post("/conversations/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: str,
    payload: ConversationArchiveInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db: Any) -> dict[str, Any]:
        row = _owned_conversation(db, current_user, conversation_id)
        if row.lock_version != payload.expected_lock_version:
            _fail(409, "chat_conversation_conflict", "对话已经更新，请刷新后重试")
        if row.status != "archived":
            row.status = "archived"
            row.archived_at = _now()
            row.lock_version += 1
            db.commit()
        return conversation_payload(db, row, actor=current_user)
    return await run_db_op(operation)


@router.post("/conversations/{conversation_id}/attachments", status_code=201)
async def upload_attachment(
    conversation_id: str,
    idempotency_key: str = Form(..., min_length=8, max_length=128),
    file: UploadFile = File(...),
    current_user: DBUser = Depends(get_current_user),
):
    raw = await file.read(CONFIG.max_upload_bytes + 1)
    if len(raw) > CONFIG.max_upload_bytes:
        _fail(413, "chat_attachment_too_large", "附件超过允许大小")
    filename = Path(file.filename or "").name[:256]
    file_format = Path(filename).suffix.lower().lstrip(".")
    if file_format not in SUPPORTED_FORMATS:
        _fail(422, "chat_attachment_format_unsupported", "支持 PPT、PDF、PPTX、DOCX、Markdown、文本和常见图片")
    if not raw:
        _fail(422, "chat_attachment_empty", "附件内容为空")
    source_sha256 = _sha256_bytes(raw)

    def operation(db: Any) -> dict[str, Any]:
        conversation = _owned_conversation(db, current_user, conversation_id)
        if conversation.status != "active":
            _fail(409, "chat_conversation_archived", "已归档对话不能添加附件")
        existing = db.query(DBChatAttachment).filter_by(
            owner_public_id=current_user.public_id,
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            if existing.conversation_id != conversation.id or existing.source_sha256 != source_sha256:
                _fail(409, "chat_attachment_idempotency_conflict", "同一操作标识已经用于其他附件")
            return {"created": False, "attachment": attachment_payload(existing)}
        row = DBChatAttachment(
            conversation_id=conversation.id,
            owner_public_id=current_user.public_id,
            filename=filename,
            file_format=file_format,
            mime_type=(file.content_type or "application/octet-stream")[:128],
            file_size=len(raw),
            source_sha256=source_sha256,
            raw_bytes=raw,
            idempotency_key=idempotency_key,
        )
        db.add(row)
        conversation.updated_at = _now()
        conversation.lock_version += 1
        db.commit()
        return {"created": True, "attachment": attachment_payload(row)}
    return await run_db_op(operation)


@router.post("/attachments/{attachment_id}/parse")
async def parse_attachment(
    attachment_id: str,
    payload: AttachmentActionInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db: Any) -> dict[str, Any]:
        row = _owned_attachment(db, current_user, attachment_id)
        if row.lock_version != payload.expected_lock_version:
            _fail(409, "chat_attachment_conflict", "附件状态已经更新，请刷新后重试")
        if row.status == "removed":
            _fail(409, "chat_attachment_removed", "已移除附件不能重新解析")
        if row.status == "ready":
            return attachment_payload(row)
        if row.status == "parsing":
            _fail(409, "chat_attachment_parsing", "附件正在解析")
        row.status = "parsing"
        row.stage = "parsing"
        row.progress = 0.2
        row.error_code = ""
        row.error_message = ""
        row.retryable = False
        row.partial_confirmed = False
        row.parse_version += 1
        row.lock_version += 1
        db.commit()
        try:
            result = _parse_attachment_bytes(bytes(row.raw_bytes), row.filename, row.file_format, row.source_sha256)
            row.parsed_text = str(result.get("text") or "")
            row.parser_version = str(result.get("parser_version") or "")[:64]
            row.locations = list(result.get("locations") or [])
            row.parse_metadata = dict(result.get("metadata") or {})
            row.warnings = list(result.get("warnings") or [])
            row.status = str(result.get("status") or "ready")
            row.stage = "ready" if row.status == "ready" else "failed"
            row.progress = 1.0
            row.error_code = str(result.get("error_code") or "")[:64]
            row.error_message = str(result.get("error_message") or "")[:1000]
            row.retryable = bool(result.get("retryable"))
        except Exception as exc:
            code, message, retryable = _parse_failure(exc)
            row.status = "failed"
            row.stage = "failed"
            row.error_code = code[:64]
            row.error_message = message[:1000]
            row.retryable = retryable
            row.progress = 0.2
        row.lock_version += 1
        db.commit()
        return attachment_payload(row)
    return await run_db_op(operation)


@router.post("/attachments/{attachment_id}/confirm-partial")
async def confirm_partial_attachment(
    attachment_id: str,
    payload: AttachmentActionInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db: Any) -> dict[str, Any]:
        row = _owned_attachment(db, current_user, attachment_id)
        if row.lock_version != payload.expected_lock_version:
            _fail(409, "chat_attachment_conflict", "附件状态已经更新，请刷新后重试")
        if row.status != "partial_failed":
            _fail(409, "chat_attachment_not_partial", "当前附件不需要确认部分结果")
        row.partial_confirmed = True
        row.lock_version += 1
        db.commit()
        return attachment_payload(row)
    return await run_db_op(operation)


@router.post("/attachments/{attachment_id}/remove")
async def remove_attachment(
    attachment_id: str,
    payload: AttachmentActionInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db: Any) -> dict[str, Any]:
        row = _owned_attachment(db, current_user, attachment_id)
        if row.lock_version != payload.expected_lock_version:
            _fail(409, "chat_attachment_conflict", "附件状态已经更新，请刷新后重试")
        if row.status != "removed":
            row.status = "removed"
            row.stage = "removed"
            row.progress = 1.0
            row.raw_bytes = b""
            row.parsed_text = ""
            row.locations = []
            row.parse_metadata = {}
            row.partial_confirmed = False
            row.removed_at = _now()
            row.lock_version += 1
            db.commit()
        return attachment_payload(row)
    return await run_db_op(operation)


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def create_message(
    conversation_id: str,
    payload: MessageInput,
    current_user: DBUser = Depends(get_current_user),
):
    return await run_db_op(create_message_pair, current_user, conversation_id, payload)


@router.post("/messages/{message_id}/stop")
async def stop_message(
    message_id: str,
    payload: AttachmentActionInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db: Any) -> dict[str, Any]:
        row = _owned_message(db, current_user, message_id)
        if row.role != "assistant":
            _fail(409, "chat_assistant_message_required", "只能停止当前回答")
        if row.lock_version != payload.expected_lock_version:
            _fail(409, "chat_message_conflict", "回答状态已经更新，请刷新后重试")
        if row.status in {"queued", "streaming"}:
            row.status = "stopped"
            checkpoint = dict(row.stream_checkpoint or {})
            checkpoint.update({"status": "stopped", "receivedCharacters": len(row.content or "")})
            checkpoint = append_public_run_event(
                checkpoint,
                run_id=str(checkpoint.get("runId") or f"chat-run-{row.id}"),
                event_type="run.stopped",
                stage_id="answer_generation",
                public_status="stopped",
                owner="Chat Orchestrator",
                summary="用户停止了本次回答，已保留当前内容。",
                input_refs=[f"chat:{row.reply_to_message_id or row.id}"],
                progress=None,
                retryable=True,
            )
            row.stream_checkpoint = checkpoint
            _set_message_agent_audit(row, "stopped")
            row.lock_version += 1
            db.commit()
        conversation = _owned_conversation(db, current_user, row.conversation_id)
        return message_payload(row, db=db, actor=current_user, course_id=conversation.course_id)
    return await run_db_op(operation)


@router.post("/messages/{message_id}/continue")
async def continue_message(
    message_id: str,
    payload: AttachmentActionInput,
    current_user: DBUser = Depends(get_current_user),
):
    def operation(db: Any) -> dict[str, Any]:
        row = _owned_message(db, current_user, message_id)
        if row.role != "assistant":
            _fail(409, "chat_assistant_message_required", "只能继续回答消息")
        if row.lock_version != payload.expected_lock_version:
            _fail(409, "chat_message_conflict", "回答状态已经更新，请刷新后重试")
        if row.status not in {"stopped", "failed"}:
            _fail(409, "chat_message_not_continuable", "当前回答不需要继续")
        row.status = "queued"
        row.error_code = ""
        row.error_message = ""
        checkpoint = dict(row.stream_checkpoint or {})
        checkpoint.update({"status": "queued", "receivedCharacters": len(row.content or "")})
        checkpoint = append_public_run_event(
            checkpoint,
            run_id=str(checkpoint.get("runId") or f"chat-run-{row.id}"),
            event_type="run.retry",
            stage_id="answer_generation",
            public_status="queued",
            owner="Chat Orchestrator",
            summary="已创建新的回答尝试，保留之前失败/停止历史。",
            input_refs=[f"chat:{row.reply_to_message_id or row.id}"],
            progress=0.0,
            retryable=False,
        )
        row.stream_checkpoint = checkpoint
        _set_message_agent_audit(row, "queued")
        row.lock_version += 1
        db.commit()
        conversation = _owned_conversation(db, current_user, row.conversation_id)
        return message_payload(row, db=db, actor=current_user, course_id=conversation.course_id)
    return await run_db_op(operation)


@router.post("/messages/{message_id}/resource-actions", status_code=201)
async def create_message_resource_action(
    message_id: str,
    payload: ResourceActionInput,
    current_user: DBUser = Depends(get_current_user),
):
    labels = {
        "handout": ("个性化讲义", "完成讲义阅读并提交其中的小测"),
        "mind_map": ("思维导图", "查看核心节点并完成一次回顾"),
        "quiz": ("测验题资源", "提交至少一道题并获得服务端判分"),
    }

    def operation(db: Any) -> dict[str, Any]:
        row = _owned_message(db, current_user, message_id)
        if row.role != "assistant" or row.status != "completed":
            _fail(409, "chat_resource_answer_incomplete", "回答完成后才能生成学习资源")
        if row.lock_version != payload.expected_lock_version:
            _fail(409, "chat_message_conflict", "回答状态已经更新，请刷新后重试")
        conversation = _owned_conversation(db, current_user, row.conversation_id)
        if not conversation.course_id:
            _fail(422, "chat_resource_course_required", "当前对话没有课程上下文，暂不能生成学习资源")
        point_id = _message_knowledge_point_id(row, payload.knowledge_point_id)
        source_ref_ids = _message_source_ref_ids(row)
        profile = latest_profile_snapshot_for_course(
            db,
            current_user.public_id,
            conversation.course_id,
        )
        if profile is None:
            _fail(422, "chat_resource_profile_required", "尚未形成学习画像，请先完成首次画像")
        title, completion_rule = labels[payload.resource_type]
        idempotency_key = f"chat-resource-{row.id}-{payload.resource_type}"
        try:
            job = create_generation_job(
                db,
                current_user,
                course_id=conversation.course_id,
                knowledge_point_id=point_id,
                profile_snapshot_id=profile.id,
                idempotency_key=idempotency_key,
                items=[{
                    "type": payload.resource_type,
                    "title": title,
                    "source_ref_ids": source_ref_ids,
                    "completion_rule": completion_rule,
                }],
                scope="single",
                learning_goal=(row.content or "围绕当前问答继续学习")[:512],
            )
        except ResourceBundleError as exc:
            status_code = 404 if exc.code.endswith("unknown") else 403 if "forbidden" in exc.code else 409 if "conflict" in exc.code else 422
            _fail(status_code, exc.code, str(exc))
        link = {
            "kind": "generation_job",
            "type": payload.resource_type,
            "title": title,
            "taskId": job["job_id"],
            "status": job["status"],
            "route": f"/workspace/resources/bundles/{job['job_id']}",
        }
        links = list(row.resource_links or [])
        existing = next((item for item in links if item.get("kind") == "generation_job" and item.get("type") == payload.resource_type), None)
        if existing is None:
            links.append(link)
            row.resource_links = links
            row.lock_version += 1
            db.commit()
            db.refresh(row)
        else:
            link = existing
        return {
            "created": bool(job.get("created")),
            "job": job,
            "resourceLink": link,
            "message": message_payload(
                row,
                db=db,
                actor=current_user,
                course_id=conversation.course_id,
            ),
        }

    return await run_db_op(operation)
