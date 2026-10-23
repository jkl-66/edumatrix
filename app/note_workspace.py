from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import HTTPException

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBDocumentSelection,
    DBLearningEvent,
    DBNote,
    DBNoteVersion,
    DBReviewPlan,
    DBUser,
)
from app.identity import new_public_id, normalize_role
from app.source_refs import project_selection, project_source_ref


SOURCE_LABELS = {
    "manual": "手动记录",
    "conversation": "智能对话",
    "knowledge_selection": "知识库选区",
    "handout": "个性化讲义",
    "code_sandbox": "代码沙盒",
    "review_task": "复习任务",
    "wrong_question_reflection": "错题本反思",
}
RESOURCE_SOURCE_TYPES = {"handout", "code_sandbox"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:40]
    return f"{prefix}-{digest}"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _request_hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def normalize_concepts(concepts: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for concept in concepts or []:
        parts = [concept]
        for separator in ("与", "和"):
            parts = [item for part in parts for item in part.split(separator)]
        normalized.extend(item.strip() for item in parts if item.strip())
    return list(dict.fromkeys(normalized))


def _student_owner(db: Any, student_id: str) -> DBUser | None:
    return db.query(DBUser).filter(DBUser.username == student_id).first()


def _assert_actor_scope(actor: DBUser | None, student_id: str) -> None:
    if actor is None or actor.username == student_id or normalize_role(actor.role) in {"admin", "teacher"}:
        return
    raise HTTPException(status_code=403, detail="无权访问该学生的笔记")


def prepare_source_metadata(
    db: Any,
    *,
    actor: DBUser,
    source_type: str,
    metadata: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    source_type = str(source_type or "manual").strip()
    raw = dict(metadata or {})
    if source_type in {"manual", "conversation", "wrong_question_reflection"}:
        return source_type, {}
    if source_type == "knowledge_selection":
        selection_id = str(raw.get("selection_id") or "")
        selection = db.get(DBDocumentSelection, selection_id) if selection_id else None
        if selection is None:
            raise HTTPException(status_code=404, detail="知识库选区不存在")
        if selection.owner_public_id != actor.public_id:
            raise HTTPException(status_code=403, detail="无权引用该知识库选区")
        return source_type, {
            "source_type": source_type,
            "selection_id": selection.id,
            "source_document_id": selection.source_document_id,
            "source_ref_id": selection.source_ref_id,
            "document_version": selection.document_version,
            "selection_type": selection.selection_type,
            "section_id": selection.section_id,
            "page_number": selection.page_number,
            "char_start": selection.char_start,
            "char_end": selection.char_end,
            "quote": selection.quote or selection.ocr_text or "",
            "normalized_rect": selection.normalized_rect,
            "crop_ref": selection.crop_ref or "",
        }
    if source_type in RESOURCE_SOURCE_TYPES:
        resource_id = str(raw.get("resource_id") or "")
        resource_version_id = str(raw.get("resource_version_id") or "")
        artifact = db.get(DBArtifact, resource_id) if resource_id else None
        if artifact is None:
            raise HTTPException(status_code=404, detail="来源资源不存在")
        if artifact.owner_public_id != actor.public_id and normalize_role(actor.role) != "admin":
            raise HTTPException(status_code=403, detail="无权引用该学习资源")
        version = db.get(DBArtifactVersion, resource_version_id) if resource_version_id else None
        if version is None or version.artifact_id != artifact.id:
            raise HTTPException(status_code=409, detail="来源资源版本不存在或不匹配")
        from app.m5_resources import canonical_resource_type, resource_route

        actual_type = canonical_resource_type(artifact.artifact_type, dict(version.metadata_json or {}))
        if actual_type != source_type:
            raise HTTPException(status_code=409, detail="来源资源类型不匹配")
        route = resource_route(actual_type, artifact.id) or ""
        if route:
            route = f"{route}?{urlencode({'version_id': version.id})}"
        return source_type, {
            "source_type": source_type,
            "resource_id": artifact.id,
            "resource_version_id": version.id,
            "course_id": artifact.course_id,
            "title": artifact.title,
            "route": route,
        }
    if source_type == "review_task":
        source_id = str(raw.get("source_id") or "")
        if not source_id.isdigit():
            raise HTTPException(status_code=422, detail="复习任务标识无效")
        plan = db.get(DBReviewPlan, int(source_id))
        if plan is None:
            raise HTTPException(status_code=404, detail="复习任务不存在")
        if plan.student_id != actor.username and normalize_role(actor.role) not in {"admin", "teacher"}:
            raise HTTPException(status_code=403, detail="无权引用该复习任务")
        return source_type, {
            "source_type": source_type,
            "source_id": str(plan.id),
            "title": f"{plan.concept}复习任务",
            "concept": plan.concept,
            "route": f"/workspace/review?review_task=review-plan:{plan.id}",
        }
    raise HTTPException(status_code=422, detail="不支持的笔记来源类型")


def _operation_event(
    db: Any,
    *,
    note: DBNote,
    action: str,
    idempotency_key: str,
    request_hash: str,
    version_number: int | None,
    task_id: str | None = None,
) -> tuple[DBLearningEvent, bool]:
    owner = _student_owner(db, note.student_id)
    event_id = _stable_id("le-note", owner.public_id if owner else note.student_id, action, idempotency_key)
    payload = {
        "note_id": note.id,
        "version_number": version_number,
        "lock_version": int(note.lock_version or 1),
        "source_type": str((note.source_metadata or {}).get("source_type") or note.source),
        "request_hash": request_hash,
        "task_id": task_id or None,
        "mastery_updated": False,
    }
    existing = db.get(DBLearningEvent, event_id)
    if existing is not None:
        if existing.action != action or str((existing.payload or {}).get("request_hash")) != request_hash:
            raise HTTPException(status_code=409, detail="同一操作标识已经绑定其他笔记操作")
        return existing, False
    event = DBLearningEvent(
        id=event_id,
        owner_public_id=owner.public_id if owner else None,
        legacy_student_id=note.student_id,
        course_id=str((note.source_metadata or {}).get("course_id") or "") or None,
        event_type=f"note.{action}",
        schema_version="f8.note.v1",
        idempotency_key=f"note:{action}:{idempotency_key}"[:128],
        source="note_workspace",
        trace_id=_stable_id("trace-note", note.id, idempotency_key),
        object_type="note",
        object_id=note.id,
        action=action,
        context_ref={
            "note_id": note.id,
            "version_number": version_number,
            "resource_id": (note.source_metadata or {}).get("resource_id"),
            "source_ref_id": (note.source_metadata or {}).get("source_ref_id"),
            "selection_id": (note.source_metadata or {}).get("selection_id"),
        },
        evidence_strength=0.0,
        evidence_status="none",
        evidence_reason="笔记行为可追溯，但不是知识掌握证据",
        mastery_eligible=False,
        completion_effect="none",
        payload_version="1",
        payload=payload,
        occurred_at=_now(),
    )
    db.add(event)
    db.flush()
    return event, True


def _next_history_version_number(db: Any, note: DBNote) -> int:
    latest = (
        db.query(DBNoteVersion)
        .filter(DBNoteVersion.note_id == note.id)
        .order_by(DBNoteVersion.version_number.desc())
        .first()
    )
    return int(latest.version_number if latest is not None else 0) + 1


def _append_version(
    db: Any,
    note: DBNote,
    *,
    change_type: str,
    event_id: str | None,
    restored_from_version: int | None = None,
    version_number: int | None = None,
) -> DBNoteVersion:
    history_version = int(version_number or note.current_version_number or note.lock_version or 1)
    version = DBNoteVersion(
        id=_stable_id("notev", note.id, str(history_version)),
        note_id=note.id,
        version_number=history_version,
        content=note.content,
        tags=list(note.tags or []),
        concepts=list(note.concepts or []),
        source=note.source,
        source_metadata=dict(note.source_metadata or {}),
        change_type=change_type,
        restored_from_version=restored_from_version,
        event_id=event_id,
        created_at=_now(),
    )
    db.add(version)
    db.flush()
    return version


def create_note_record(
    db: Any,
    *,
    student_id: str,
    source: str,
    content: str,
    tags: list[str] | None = None,
    concepts: list[str] | None = None,
    source_metadata: dict[str, Any] | None = None,
    note_id: str | None = None,
    idempotency_key: str | None = None,
    actor: DBUser | None = None,
    task_id: str | None = None,
) -> tuple[DBNote, bool]:
    _assert_actor_scope(actor, student_id)
    normalized_tags = list(dict.fromkeys(item.strip() for item in tags or [] if item.strip()))
    normalized_concepts = normalize_concepts(concepts)
    metadata = dict(source_metadata or {})
    operation_key = str(idempotency_key or new_public_id("note-op"))
    if note_id is None:
        note_id = _stable_id("note", actor.public_id if actor else student_id, operation_key)
    request = {
        "note_id": note_id,
        "student_id": student_id,
        "source": source,
        "content": content,
        "tags": normalized_tags,
        "concepts": normalized_concepts,
        "source_metadata": metadata,
    }
    request_hash = _request_hash(request)
    existing = db.get(DBNote, note_id)
    if existing is not None:
        if existing.student_id != student_id or _request_hash({
            "note_id": existing.id,
            "student_id": existing.student_id,
            "source": existing.source,
            "content": existing.content,
            "tags": list(existing.tags or []),
            "concepts": list(existing.concepts or []),
            "source_metadata": dict(existing.source_metadata or {}),
        }) != request_hash:
            raise HTTPException(status_code=409, detail="同一操作标识已经绑定其他笔记")
        return existing, False
    note = DBNote(
        id=note_id,
        student_id=student_id,
        source=source,
        content=content,
        tags=normalized_tags,
        concepts=normalized_concepts,
        source_metadata=metadata,
        lock_version=1,
        current_version_number=1,
        ai_suggestion="",
        ai_suggestion_metadata={},
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(note)
    db.flush()
    event, _ = _operation_event(
        db,
        note=note,
        action="created",
        idempotency_key=operation_key,
        request_hash=request_hash,
        version_number=1,
        task_id=task_id,
    )
    _append_version(db, note, change_type="created", event_id=event.id)
    return note, True


def update_note_record(
    db: Any,
    *,
    note_id: str,
    student_id: str | None,
    content: str,
    tags: list[str] | None,
    concepts: list[str] | None,
    expected_version: int | None,
    idempotency_key: str | None,
    actor: DBUser | None,
    change_type: str = "saved",
    task_id: str | None = None,
) -> tuple[DBNote | None, bool]:
    query = db.query(DBNote).filter(DBNote.id == note_id)
    if student_id:
        query = query.filter(DBNote.student_id == student_id)
    note = query.first()
    if note is None:
        return None, False
    _assert_actor_scope(actor, note.student_id)
    normalized_tags = list(note.tags or []) if tags is None else list(dict.fromkeys(item.strip() for item in tags if item.strip()))
    normalized_concepts = list(note.concepts or []) if concepts is None else normalize_concepts(concepts)
    operation_key = str(idempotency_key or new_public_id("note-op"))
    request_hash = _request_hash({
        "note_id": note.id,
        "content": content,
        "tags": normalized_tags,
        "concepts": normalized_concepts,
        "expected_version": expected_version,
        "change_type": change_type,
    })
    event_id = _stable_id(
        "le-note",
        (_student_owner(db, note.student_id).public_id if _student_owner(db, note.student_id) else note.student_id),
        change_type,
        operation_key,
    )
    replay = db.get(DBLearningEvent, event_id)
    if replay is not None:
        if str((replay.payload or {}).get("request_hash")) != request_hash:
            raise HTTPException(status_code=409, detail="同一操作标识已经绑定其他笔记操作")
        return note, False
    if expected_version is not None and int(note.lock_version or 1) != int(expected_version):
        raise HTTPException(
            status_code=409,
            detail={"code": "note_version_conflict", "message": "笔记已在别处更新，本地草稿未提交。", "current_version": note.lock_version},
        )
    if note.content == content and list(note.tags or []) == normalized_tags and list(note.concepts or []) == normalized_concepts:
        return note, False
    note.content = content
    note.tags = normalized_tags
    note.concepts = normalized_concepts
    note.lock_version = int(note.lock_version or 1) + 1
    note.updated_at = _now()
    note.ai_suggestion = ""
    note.ai_suggestion_metadata = {}
    next_history_version = _next_history_version_number(db, note)
    note.current_version_number = next_history_version
    event, _ = _operation_event(
        db,
        note=note,
        action=change_type,
        idempotency_key=operation_key,
        request_hash=request_hash,
        version_number=next_history_version,
        task_id=task_id,
    )
    _append_version(
        db,
        note,
        change_type=change_type,
        event_id=event.id,
        version_number=next_history_version,
    )
    return note, True


def save_ai_suggestion(
    db: Any,
    *,
    note_id: str,
    actor: DBUser,
    expected_version: int,
    idempotency_key: str,
    content: str,
    tags: list[str],
    concepts: list[str],
) -> DBNote:
    note = db.get(DBNote, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    _assert_actor_scope(actor, note.student_id)
    request_hash = _request_hash({
        "note_id": note_id,
        "expected_version": expected_version,
        "content": content,
        "tags": tags,
        "concepts": concepts,
    })
    owner = _student_owner(db, note.student_id)
    event_id = _stable_id("le-note", owner.public_id if owner else note.student_id, "ai_suggestion_created", idempotency_key)
    existing = db.get(DBLearningEvent, event_id)
    if existing is not None:
        if str((existing.payload or {}).get("request_hash")) != request_hash:
            raise HTTPException(status_code=409, detail="同一操作标识已经绑定其他 AI 建议")
        return note
    if int(note.lock_version or 1) != int(expected_version):
        raise HTTPException(
            status_code=409,
            detail={"code": "note_version_conflict", "message": "笔记已更新，请基于最新正文重新生成建议。", "current_version": note.lock_version},
        )
    note.ai_suggestion = content
    note.ai_suggestion_metadata = {
        "base_version": note.lock_version,
        "tags": list(tags),
        "concepts": normalize_concepts(concepts),
        "created_at": _now().isoformat(),
    }
    note.updated_at = _now()
    _operation_event(
        db,
        note=note,
        action="ai_suggestion_created",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        version_number=note.lock_version,
    )
    return note


def restore_note_version(
    db: Any,
    *,
    note_id: str,
    version_number: int,
    expected_version: int,
    idempotency_key: str,
    actor: DBUser,
) -> tuple[DBNote, bool]:
    note = db.get(DBNote, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    _assert_actor_scope(actor, note.student_id)
    target = db.query(DBNoteVersion).filter_by(note_id=note.id, version_number=version_number).first()
    if target is None:
        raise HTTPException(status_code=404, detail="笔记历史版本不存在")
    request_hash = _request_hash({
        "note_id": note.id,
        "version_number": version_number,
        "expected_version": expected_version,
    })
    owner = _student_owner(db, note.student_id)
    event_id = _stable_id("le-note", owner.public_id if owner else note.student_id, "restored", idempotency_key)
    existing = db.get(DBLearningEvent, event_id)
    if existing is not None:
        if str((existing.payload or {}).get("request_hash")) != request_hash:
            raise HTTPException(status_code=409, detail="同一操作标识已经绑定其他恢复操作")
        return note, False
    if int(note.lock_version or 1) != int(expected_version):
        raise HTTPException(
            status_code=409,
            detail={"code": "note_version_conflict", "message": "笔记已更新，本地状态未覆盖。", "current_version": note.lock_version},
        )
    note.content = target.content
    note.tags = list(target.tags or [])
    note.concepts = list(target.concepts or [])
    note.source = target.source
    note.source_metadata = dict(target.source_metadata or {})
    note.current_version_number = int(version_number)
    note.lock_version = int(note.lock_version or 1) + 1
    note.ai_suggestion = ""
    note.ai_suggestion_metadata = {}
    note.updated_at = _now()
    event, _ = _operation_event(
        db,
        note=note,
        action="restored",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        version_number=version_number,
    )
    return note, True


def source_projection(db: Any, *, actor: DBUser, note: DBNote) -> dict[str, Any]:
    metadata = dict(note.source_metadata or {})
    source_type = str(metadata.get("source_type") or note.source or "manual")
    if source_type == "knowledge_selection":
        selection = db.get(DBDocumentSelection, str(metadata.get("selection_id") or ""))
        if selection is not None and selection.owner_public_id == actor.public_id:
            return project_selection(db, actor, selection)
        projection = project_source_ref(
            db,
            str(metadata.get("source_ref_id") or ""),
            actor=actor,
            frozen=metadata,
            permission_as_unavailable=True,
            allow_missing_ref=True,
        )
        projection.update({
            "selection_id": metadata.get("selection_id"),
            "selection_type": metadata.get("selection_type"),
            "image_region": metadata.get("normalized_rect"),
            "quote": metadata.get("quote") or projection.get("quote") or "",
        })
        return projection
    if source_type in RESOURCE_SOURCE_TYPES:
        artifact = db.get(DBArtifact, str(metadata.get("resource_id") or ""))
        version = db.get(DBArtifactVersion, str(metadata.get("resource_version_id") or ""))
        available = bool(
            artifact
            and version
            and version.artifact_id == artifact.id
            and artifact.owner_public_id == actor.public_id
            and artifact.archived_at is None
        )
        return {
            "kind": "learning_resource",
            "source_type": source_type,
            "title": metadata.get("title") or (artifact.title if artifact else SOURCE_LABELS[source_type]),
            "course_id": metadata.get("course_id") or (artifact.course_id if artifact else ""),
            "resource_id": metadata.get("resource_id"),
            "resource_version_id": metadata.get("resource_version_id"),
            "route": metadata.get("route") or "",
            "available": available,
            "reason": "" if available else "来源资源已撤回、版本失效或当前账号无权查看",
            "historical": True,
        }
    if source_type == "review_task":
        raw_id = str(metadata.get("source_id") or "")
        plan = db.get(DBReviewPlan, int(raw_id)) if raw_id.isdigit() else None
        available = bool(plan and plan.student_id == note.student_id and actor.username == note.student_id)
        return {
            "kind": "review_task",
            "source_type": source_type,
            "title": metadata.get("title") or SOURCE_LABELS[source_type],
            "concept": metadata.get("concept") or (plan.concept if plan else ""),
            "route": (
                f"/workspace/review?review_task=review-plan:{plan.id}"
                if available
                else metadata.get("route") or "/workspace/review"
            ),
            "available": available,
            "reason": "" if available else "复习任务已失效或当前账号无权查看",
            "historical": True,
        }
    return {
        "kind": "personal_note",
        "source_type": source_type,
        "title": SOURCE_LABELS.get(source_type, note.source or "学习笔记"),
        "route": "",
        "available": True,
        "reason": "",
        "historical": False,
    }


def note_payload(db: Any, *, actor: DBUser, note: DBNote) -> dict[str, Any]:
    _assert_actor_scope(actor, note.student_id)
    version_count = db.query(DBNoteVersion).filter(DBNoteVersion.note_id == note.id).count()
    suggestion_metadata = dict(note.ai_suggestion_metadata or {})
    suggestion = None
    if note.ai_suggestion:
        suggestion = {
            "content": note.ai_suggestion,
            "base_version": suggestion_metadata.get("base_version"),
            "tags": list(suggestion_metadata.get("tags") or []),
            "concepts": list(suggestion_metadata.get("concepts") or []),
            "created_at": suggestion_metadata.get("created_at"),
        }
    return {
        "id": note.id,
        "student_id": note.student_id,
        "source": note.source,
        "content": note.content,
        "tags": list(note.tags or []),
        "concepts": list(note.concepts or []),
        "source_metadata": dict(note.source_metadata or {}),
        "source_context": source_projection(db, actor=actor, note=note),
        "lock_version": int(note.lock_version or 1),
        "current_version_number": int(note.current_version_number or 1),
        "version_count": version_count,
        "ai_suggestion": suggestion,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }


def note_versions_payload(db: Any, *, actor: DBUser, note: DBNote) -> list[dict[str, Any]]:
    _assert_actor_scope(actor, note.student_id)
    versions = db.query(DBNoteVersion).filter(DBNoteVersion.note_id == note.id).order_by(DBNoteVersion.version_number.desc()).all()
    return [
        {
            "id": version.id,
            "version_number": version.version_number,
            "content": version.content,
            "tags": list(version.tags or []),
            "concepts": list(version.concepts or []),
            "source": version.source,
            "source_metadata": dict(version.source_metadata or {}),
            "change_type": version.change_type,
            "restored_from_version": version.restored_from_version,
            "created_at": version.created_at.isoformat() if version.created_at else None,
        }
        for version in versions
    ]
