from __future__ import annotations

import asyncio
import hashlib
import json
import ipaddress
import os
import socket
import shutil
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any
import re
import uuid
from urllib.parse import urlparse
from dataclasses import replace

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Request, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import Field

from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseMembership,
    DBCourseDocument,
    DBCourseMembership,
    DBKnowledgeDocument,
    DBKnowledgePoint,
    DBStudentProfile,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
    run_db_op,
)
from app.auth import enforce_student_access, get_current_user
from app.legacy_repositories import LegacyReadRepository
from app.legacy_migration_governance import (
    KnowledgeSourceNoteCanonicalReader,
    observe_legacy_shadow_read,
    project_model_row,
    project_model_tree,
)
from app.m2_contracts import StrictModel
from app.m5_gateway import StreamingModelCallLifecycle
from app.m5_legacy_calls import audited_legacy_text_call, model_identity
from app.knowledge_graph import build_course_graph
from course_catalog import MASTER_COURSE_ID, course_is_selectable
from app.source_admission import (
    CandidateAdmission,
    CandidateCreate,
    complete_candidate_import,
    create_candidate,
    list_candidates,
    mark_candidate_stage,
    prepare_candidate_admission,
    reject_candidate,
    search_web_materials,
    serialize_candidate,
    withdraw_candidate,
)
from config import CONFIG
from document_parser import (
    DocumentParseError,
    ParsedDocument,
    chunk_document,
    parse_uploaded_file,
    parse_document,
    parse_pptx_slides,
    parse_pdf_visually,
)
from app.media_ocr import detect_sensitive_categories
from rag_engine import hybrid_rag
from ingestion import build_graph_after_upload, _get_graph_builder
from swarm_factory import build_swarm_from_headers
from llm_client import parse_json_object

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

DEFAULT_SHELF_COURSE_ID = "course-machine-learning-foundations-v1"
RECOMMENDATION_KEYWORDS = (
    "人工智能",
    "机器学习",
    "深度学习",
    "RAG",
    "检索",
    "边缘",
    "嵌入式",
    "数据",
    "Python",
    "模型",
)

# Document-level recommendations are intentionally a separate discovery layer.
# They never become canonical course evidence just because they are displayed.
_MATERIAL_FILE_TYPES = {
    "pdf", "doc", "docx", "ppt", "pptx", "md", "markdown", "txt", "text",
    "ipynb", "notebook", "py", "python_code", "json",
}
_MATERIAL_EXCLUDED_PREFIXES = ("[网页]", "[web]", "[html]")
_MATERIAL_WEB_MARKERS = ("csdn", "知乎", "博客", "百科", "baidu", "bilibili")
_MATERIAL_TOPIC_HINTS = (
    "教材", "教学", "课程", "机器学习", "深度学习", "神经网络", "算法", "实践",
    "指南", "笔记", "python", "pytorch", "transformer", "rag", "agent", "模型",
)

PROJECT_ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.getenv("EDUMATRIX_UPLOAD_DIR", "data/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_EXTENSIONS = {
    ".md": "markdown",
    ".txt": "text",
    ".pdf": "pdf",
    ".ppt": "presentation",
    ".docx": "word",
    ".json": "json",
    ".py": "python_code",
    ".pptx": "presentation",
    ".ipynb": "notebook",
    ".mp4": "video",
    ".avi": "video",
    ".mov": "video",
    ".mkv": "video",
    ".webm": "video",
    ".flv": "video",
}


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{kind}-{digest}"


def _personal_course_id(owner_public_id: str) -> str:
    return _stable_id("personal", owner_public_id)


class CourseCreateInput(StrictModel):
    title: str = Field(min_length=2, max_length=100)
    subject: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=1000)


class _ReadableHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            clean = " ".join(data.split())
            if clean:
                self.parts.append(clean)

    def text(self) -> str:
        return "\n".join(line.strip() for line in " ".join(self.parts).splitlines() if line.strip())


def _ensure_personal_course(
    session,
    *,
    owner_public_id: str,
    uploader_public_id: str,
    course_id: str = "",
) -> DBCourse:
    target_id = course_id.strip() or _personal_course_id(owner_public_id)
    course = session.get(DBCourse, target_id)
    if course is None and course_id.strip():
        raise HTTPException(status_code=404, detail="目标课程不存在")
    if course is None:
        course = DBCourse(
            id=target_id,
            version="1",
            title="个人知识库（内部）",
            subject="personal-knowledge",
            description="用户私有上传文档的 canonical 来源权限边界",
            domain_pack="personal",
            language="zh-CN",
            content_origin="local-upload",
            license_text="user-provided",
            visibility="private",
            status="draft",
            owner_public_id=owner_public_id,
            manifest_version="personal-v1",
            manifest_data={"kind": "personal_source_boundary", "owner": owner_public_id},
        )
        session.add(course)
        session.flush()
    if course.owner_public_id != owner_public_id:
        raise HTTPException(status_code=403, detail="只能向自己创建的学习课程添加资料")
    if course.status not in {"draft", "published"}:
        raise HTTPException(status_code=409, detail="当前课程状态不允许添加资料")
    membership_specs = [(owner_public_id, "student")]
    if uploader_public_id != owner_public_id:
        membership_specs.append((uploader_public_id, "teacher"))
    for member_public_id, role in membership_specs:
        membership = session.query(DBCourseMembership).filter_by(
            course_id=course.id,
            user_public_id=member_public_id,
        ).first()
        if membership is None:
            session.add(DBCourseMembership(
                id=_stable_id("cm", course.id, member_public_id),
                course_id=course.id,
                user_public_id=member_public_id,
                role=role,
                status="active",
            ))
        else:
            membership.status = "active"
    return course


def _write_upload_file(*, student_id: str, document_id: str, ext: str, raw: bytes) -> Path:
    doc_dir = UPLOAD_DIR / student_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    final_path = doc_dir / f"{document_id}{ext}"
    temporary_path = doc_dir / f".{document_id}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary_path.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, final_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return final_path


def _ocr_asset_dir(*, student_id: str, document_id: str) -> Path:
    return UPLOAD_DIR / student_id / document_id / "ocr"


def _validated_public_url(value: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="资料地址必须是不含账号信息的公开 HTTP(S) 地址")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        }
    except OSError as exc:
        raise HTTPException(status_code=400, detail="无法解析资料地址的域名") from exc
    for value in addresses:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise HTTPException(status_code=422, detail="不允许从本机、局域网或保留网络地址导入资料")
    return parsed.geturl()


def _remote_extension(url: str, hinted_format: str, content_type: str) -> str:
    if "text/html" in content_type.lower():
        return ".md"
    hint = hinted_format.strip().lower().lstrip(".")
    if hint and f".{hint}" in SUPPORTED_EXTENSIONS:
        return f".{hint}"
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in SUPPORTED_EXTENSIONS:
        return suffix
    type_map = {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "video/mp4": ".mp4",
        "text/plain": ".txt",
        "text/markdown": ".md",
    }
    for mime, extension in type_map.items():
        if mime in content_type.lower():
            return extension
    raise HTTPException(status_code=422, detail="无法确定远程资料格式，请使用 PDF、DOCX、PPTX、视频或可读网页")


def _remote_download_error(code: str, message: str, *, status_code: int = 502) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "retryable": True,
        },
    )


async def _download_remote_bytes(
    *,
    url: str,
    headers: dict[str, str],
    timeout_seconds: float = 30.0,
    max_attempts: int = 2,
) -> tuple[bytes, str, str]:
    """Download one public resource with the same bounded policy for every import entry point."""
    import httpx

    safe_url = _validated_public_url(url)
    transient_statuses = {408, 425, 429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
                async with client.stream("GET", safe_url, headers=headers) as response:
                    for redirect in [*getattr(response, "history", ()), response]:
                        _validated_public_url(str(getattr(redirect, "url", safe_url) or safe_url))
                    if response.status_code != 200:
                        if response.status_code in transient_statuses and attempt + 1 < max_attempts:
                            await asyncio.sleep(0.4)
                            continue
                        code = f"download_http_{response.status_code}"
                        raise _remote_download_error(
                            code,
                            f"资料下载失败，HTTP 状态码 {response.status_code}；已自动重试 {max(0, attempt)} 次，请稍后重试。",
                        )
                    declared = response.headers.get("content-length")
                    if declared:
                        try:
                            declared_size = int(declared)
                        except (TypeError, ValueError) as exc:
                            raise _remote_download_error(
                                "download_content_length_invalid",
                                "资料下载响应的大小信息无效，请重试或更换来源。",
                            ) from exc
                        if declared_size > CONFIG.max_upload_bytes:
                            raise HTTPException(status_code=413, detail=f"资料超过大小限制 ({CONFIG.max_upload_bytes} bytes)")
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes(64 * 1024):
                        total += len(chunk)
                        if total > CONFIG.max_upload_bytes:
                            raise HTTPException(status_code=413, detail=f"资料超过大小限制 ({CONFIG.max_upload_bytes} bytes)")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    final_url = str(getattr(response, "url", safe_url) or safe_url)
                    content_type = response.headers.get("content-type", "")
            break
        except HTTPException:
            raise
        except httpx.TimeoutException as exc:
            last_error = exc
            if attempt + 1 < max_attempts:
                await asyncio.sleep(0.4)
                continue
            raise _remote_download_error(
                "download_timeout",
                f"资料下载超时；已自动重试 {max(0, attempt)} 次，请稍后重试。",
            ) from exc
        except httpx.RequestError as exc:
            last_error = exc
            if attempt + 1 < max_attempts:
                await asyncio.sleep(0.4)
                continue
            detail = str(exc).strip() or type(exc).__name__
            raise _remote_download_error(
                "download_connection_error",
                f"资料连接失败（{detail}）；已自动重试 {max(0, attempt)} 次，请稍后重试。",
            ) from exc
        except Exception as exc:
            last_error = exc
            if attempt + 1 < max_attempts:
                await asyncio.sleep(0.4)
                continue
            detail = str(last_error).strip() or type(last_error).__name__
            raise _remote_download_error(
                "download_failed",
                f"资料下载失败（{detail}）；已自动重试 {max(0, attempt)} 次，请稍后重试。",
            ) from exc
    if not raw:
        raise _remote_download_error(
            "download_empty",
            "原站返回了空文件，未创建课程资料；请重试或更换来源。",
            status_code=422,
        )
    return raw, final_url, content_type


async def _download_remote_material(*, url: str, hinted_format: str, title: str) -> tuple[bytes, str, str]:
    headers = {
        "User-Agent": "EduMatrix-Course-Importer/1.0 (+local educational use)",
        "Accept": "text/html,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation,video/*,text/plain,*/*;q=0.5",
    }
    raw, final_url, content_type = await _download_remote_bytes(url=url, headers=headers)
    extension = _remote_extension(final_url, hinted_format, content_type)
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:80] or "联网资料"
    if extension == ".md" and "text/html" in content_type.lower():
        charset_match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
        charset = charset_match.group(1) if charset_match else "utf-8"
        try:
            html = raw.decode(charset, errors="replace")
        except LookupError:
            html = raw.decode("utf-8", errors="replace")
        parser = _ReadableHtml()
        parser.feed(html)
        body = parser.text()
        if len(body) < 80:
            raise HTTPException(status_code=422, detail="网页没有提取到足够的公开正文")
        raw = f"# {safe_title}\n\n来源：{final_url}\n\n{body}\n".encode("utf-8")
    return raw, f"{safe_title}{extension}", final_url


def _visual_page_externalization_allowed(parsed: ParsedDocument) -> bool:
    if detect_sensitive_categories(parsed.text):
        return False
    report = (parsed.metadata or {}).get("ocr")
    if not isinstance(report, dict) or report.get("status") in {"unavailable", "failed"}:
        return False
    return int(report.get("sensitive_region_count") or 0) == 0


def _resolve_upload_target(session, *, student_id: str, current_user: DBUser, course_id: str) -> tuple[str, str]:
    target_user = session.query(DBUser).filter_by(username=student_id).first()
    owner_public_id = target_user.public_id if target_user else current_user.public_id
    if not course_id.strip():
        return owner_public_id, _personal_course_id(owner_public_id)
    course = session.get(DBCourse, course_id.strip())
    if course is None:
        raise HTTPException(status_code=404, detail="目标课程不存在")
    if course.owner_public_id != owner_public_id:
        raise HTTPException(status_code=403, detail="只能向自己创建的学习课程添加资料")
    if course.status not in {"draft", "published"}:
        raise HTTPException(status_code=409, detail="当前课程状态不允许添加资料")
    return owner_public_id, course.id


_SEMANTIC_DOCUMENT_FORMATS = {"docx", "pdf"}


def _resource_structure_model(llm: Any) -> dict[str, Any]:
    """Return the only model policy allowed for resource structure extraction."""
    provider, model = model_identity(llm)
    thinking = str(getattr(llm, "thinking_mode", CONFIG.llm_thinking_mode or "max") or "").strip().lower()
    reasoning = str(getattr(llm, "reasoning_effort", CONFIG.llm_reasoning_effort or "max") or "").strip().lower()
    fallback_enabled = os.getenv("EDUMATRIX_ALLOW_LLM_FALLBACK", "0") == "1"
    wrapper = llm.__class__.__name__ == "FallbackAsyncLLMWrapper" or hasattr(llm, "fallback")
    if (
        model != "deepseek-v4-flash"
        or provider not in {"openai", "openai-compatible", "deepseek"}
        or thinking not in {"enabled", "max"}
        or reasoning != "max"
        or fallback_enabled
        or wrapper
    ):
        raise RuntimeError(
            "课程资料结构提取需要 deepseek-v4-flash、thinking enabled、reasoning_effort=max 且禁止 fallback"
        )
    return {
        "provider": provider,
        "model": model,
        "thinking": "enabled",
        "reasoning_effort": "max",
        "allow_fallback": False,
    }


def _structure_chapter_title(filename: str) -> str:
    title = Path(filename).stem.strip() or filename.strip() or "课程资料"
    return title[:256]


def _clamp_range(start: Any, end: Any, text_length: int) -> tuple[int, int]:
    try:
        lower = max(0, min(text_length, int(start)))
    except (TypeError, ValueError):
        lower = 0
    try:
        upper = max(lower, min(text_length, int(end)))
    except (TypeError, ValueError):
        upper = text_length
    return lower, upper


def _anchor_offset(text: str, value: Any, *, default: int) -> int:
    anchor = " ".join(str(value or "").split())
    if not anchor:
        return default
    compact_text = re.sub(r"\s+", " ", text)
    index = compact_text.find(anchor)
    if index >= 0:
        # The compacted offset is only an anchor; use the original text when possible.
        direct = text.find(anchor)
        return direct if direct >= 0 else default
    return default


def _normalize_knowledge_points(value: Any, *, source_id: str = "") -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    points: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value, 1):
        if isinstance(item, str):
            title = " ".join(item.split())
            point = {"code": f"KP-{index:03d}", "title": title, "level": "core", "prerequisites": []}
        elif isinstance(item, dict):
            title = " ".join(str(item.get("title") or item.get("name") or "").split())
            code = " ".join(str(item.get("code") or "").split())[:64]
            point = {
                "code": code or f"KP-{index:03d}",
                "title": title,
                "level": " ".join(str(item.get("level") or "core").split())[:32] or "core",
                "prerequisites": [" ".join(str(value).split())[:128] for value in (item.get("prerequisites") or []) if str(value).strip()],
            }
        else:
            continue
        if not point["title"]:
            continue
        key = point["title"].casefold()
        if key in seen:
            continue
        seen.add(key)
        points.append(point)
    return points[:80]


def _normalize_structure_payload(value: Any, *, parsed: ParsedDocument, model_meta: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("资料结构模型输出必须是 JSON 对象")
    chapters_value = value.get("chapters") or value.get("sections")
    root_points = _normalize_knowledge_points(value.get("knowledge_points") or value.get("knowledgePoints"))
    text_length = len(parsed.text)
    chapters: list[dict[str, Any]] = []
    if isinstance(chapters_value, list):
        for index, item in enumerate(chapters_value, 1):
            if not isinstance(item, dict):
                continue
            title = " ".join(str(item.get("title") or item.get("name") or "").split())[:256]
            if not title:
                continue
            start, end = _clamp_range(item.get("char_start", item.get("start")), item.get("char_end", item.get("end")), text_length)
            if item.get("char_start") is None and item.get("start_text") is not None:
                start = _anchor_offset(parsed.text, item.get("start_text"), default=start)
            if item.get("char_end") is None and item.get("end_text") is not None:
                end = _anchor_offset(parsed.text, item.get("end_text"), default=end)
                end = min(text_length, end + len(str(item.get("end_text") or "")))
            if end <= start:
                continue
            chapters.append({
                "title": title,
                "char_start": start,
                "char_end": end,
                "heading_level": max(1, min(6, int(item.get("heading_level") or 1))),
                "knowledge_points": _normalize_knowledge_points(item.get("knowledge_points") or item.get("knowledgePoints")),
            })
    if not chapters:
        raise ValueError("资料结构模型没有返回有效语义章节")
    chapters.sort(key=lambda item: (item["char_start"], item["char_end"], item["title"]))
    for index, chapter in enumerate(chapters, 1):
        chapter["position"] = index
    if root_points:
        chapters[0]["knowledge_points"] = _normalize_knowledge_points(
            [*chapters[0].get("knowledge_points", []), *root_points]
        )
    return {
        "status": "ready",
        "chapter_strategy": "llm_semantic_sections",
        "model": dict(model_meta),
        "chapters": chapters,
        "knowledge_point_count": sum(len(item.get("knowledge_points") or []) for item in chapters),
        "error": None,
    }


def _pending_structure(parsed: ParsedDocument, *, model_meta: dict[str, Any] | None, error_code: str, message: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "chapter_strategy": "single_resource_pending_llm",
        "model": dict(model_meta or {}),
        "chapters": [{
            "title": _structure_chapter_title(parsed.filename),
            "char_start": 0,
            "char_end": len(parsed.text),
            "heading_level": 1,
            "knowledge_points": [],
            "position": 1,
        }],
        "knowledge_point_count": 0,
        "error": {"code": error_code, "message": str(message)[:500], "retryable": True},
    }


async def _extract_resource_structure(
    parsed: ParsedDocument,
    *,
    llm: Any,
    owner_public_id: str,
    course_id: str,
) -> dict[str, Any]:
    """Extract resource knowledge with the governed model; never fabricate content."""
    model_meta: dict[str, Any] | None = None
    try:
        model_meta = _resource_structure_model(llm)
        system_prompt = (
            "你是 EduMatrix 课程资料结构抽取 Agent。只根据给定的资料原文和格式，捕捉真实语义章节并提取可追溯知识点。"
            "文档必须按真实章节边界返回 char_start/char_end 或 start_text/end_text；不要按每个段落机械切分。"
            "非文档资源仍需返回一个覆盖全文的章节。只输出 JSON："
            "{chapters:[{title,char_start,char_end,start_text,end_text,heading_level,knowledge_points:[{code,title,level,prerequisites}]}]}。"
            "不要输出解释、Markdown、prompt 或 reasoning。"
        )
        user_prompt = json.dumps({
            "filename": parsed.filename,
            "file_format": parsed.file_format,
            "parser_metadata": {
                "heading_candidates": (parsed.metadata or {}).get("heading_candidates", []),
                "location_count": len(parsed.locations),
            },
            "content": parsed.text[:32000],
        }, ensure_ascii=False)
        raw = await audited_legacy_text_call(
            llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            role="课程资料结构与知识点提取 Agent",
            operation="course_resource_structure_extraction",
            capability="course_resource_structure_extraction",
            owner_public_id=owner_public_id,
            course_id=course_id or None,
            input_summary={"filename": parsed.filename, "file_format": parsed.file_format, "content_chars": len(parsed.text)},
            response_validator=lambda value: parse_json_object(value),
        )
        payload = _normalize_structure_payload(parse_json_object(raw), parsed=parsed, model_meta=model_meta)
        if parsed.file_format not in _SEMANTIC_DOCUMENT_FORMATS:
            # P079: non-document resources are exactly one chapter; only their points come from the model.
            points = _normalize_knowledge_points([
                point
                for chapter in payload["chapters"]
                for point in (chapter.get("knowledge_points") or [])
            ])
            payload["chapters"] = [{
                "title": _structure_chapter_title(parsed.filename),
                "char_start": 0,
                "char_end": len(parsed.text),
                "heading_level": 1,
                "knowledge_points": points,
                "position": 1,
            }]
            payload["chapter_strategy"] = "single_resource"
            payload["knowledge_point_count"] = len(points)
        return payload
    except Exception as exc:
        return _pending_structure(
            parsed,
            model_meta=model_meta,
            error_code="course_resource_structure_extraction_failed",
            message=exc,
        )


def _persist_personal_canonical_source(
    session,
    *,
    document: DBKnowledgeDocument,
    parsed: ParsedDocument,
    owner_public_id: str,
    uploader_public_id: str,
    course_id: str = "",
    structure: dict[str, Any] | None = None,
    source_path: Path | str | None = None,
) -> tuple[DBSourceDocument, list[DBSourceRef]]:
    course = _ensure_personal_course(
        session,
        owner_public_id=owner_public_id,
        uploader_public_id=uploader_public_id,
        course_id=course_id,
    )

    structure_payload = dict(structure or _pending_structure(
        parsed,
        model_meta=None,
        error_code="course_resource_structure_not_requested",
        message="资料结构提取尚未执行",
    ))
    source_parser_metadata = {
        **dict(parsed.metadata or {}),
        "resource_structure": {
            "status": structure_payload.get("status"),
            "chapter_strategy": structure_payload.get("chapter_strategy"),
            "model": structure_payload.get("model") or {},
            "knowledge_point_count": int(structure_payload.get("knowledge_point_count") or 0),
            "error": structure_payload.get("error"),
        },
    }
    structure_status = str(structure_payload.get("status") or "failed")
    structure_error = structure_payload.get("error") or {}
    stored_source_path = Path(source_path) if source_path else UPLOAD_DIR / document.student_id / f"{document.id}.{parsed.file_format}"
    try:
        source_path_value = stored_source_path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        # Keep the absolute value for the reader's project-boundary check to
        # reject explicitly configured paths outside the application root.
        source_path_value = str(stored_source_path)
    source = DBSourceDocument(
        id=_stable_id("src", document.id, parsed.parser_version),
        course_id=course.id,
        legacy_document_id=document.id,
        title=document.title,
        filename=document.filename,
        file_format=parsed.file_format,
        content_hash=parsed.processed_sha256,
        source_sha256=parsed.source_sha256,
        processed_sha256=parsed.processed_sha256,
        file_size=document.file_size,
        source_path=source_path_value,
        license_text="user-provided",
        uploader_public_id=uploader_public_id,
        parser_version=parsed.parser_version,
        parser_metadata=source_parser_metadata,
        parse_warnings=list(parsed.warnings),
        processing_error_code=(
            str(structure_error.get("code") or "course_resource_structure_extraction_failed")
            if structure_status != "ready"
            else ""
        ),
        processing_status="ready" if structure_status == "ready" else "failed",
    )
    session.add(source)
    session.flush()

    chapter_specs = list(structure_payload.get("chapters") or [])
    if not chapter_specs:
        chapter_specs = [{
            "title": _structure_chapter_title(parsed.filename),
            "char_start": 0,
            "char_end": len(parsed.text),
            "heading_level": 1,
            "knowledge_points": [],
            "position": 1,
        }]
    chapters: list[DBChapter] = []
    for ordinal, spec in enumerate(chapter_specs, 1):
        start, end = _clamp_range(spec.get("char_start"), spec.get("char_end"), len(parsed.text))
        stable_key = f"personal:{document.id}:semantic:{ordinal}"
        chapter = DBChapter(
            id=_stable_id("ch", source.id, stable_key),
            course_id=course.id,
            source_document_id=source.id,
            stable_key=stable_key,
            title=" ".join(str(spec.get("title") or _structure_chapter_title(parsed.filename)).split())[:256],
            position=ordinal,
            heading_level=max(1, min(6, int(spec.get("heading_level") or 1))),
            char_start=start,
            char_end=end,
        )
        session.add(chapter)
        session.flush()
        chapters.append(chapter)

    refs: list[DBSourceRef] = []
    for ordinal, location in enumerate(parsed.locations, 1):
        midpoint = (int(location.char_start or 0) + int(location.char_end or 0)) // 2
        chapter = next((item for item in chapters if item.char_start <= midpoint <= item.char_end), chapters[0])
        stable_key = f"personal:{document.id}:{location.kind}:{location.index}"
        parser_version = parsed.parser_version if not any(
            ref.chapter_id == chapter.id for ref in refs
        ) else f"{parsed.parser_version}:location-{location.index}"
        quote = parsed.text[location.char_start:location.char_end][:300]
        ref = DBSourceRef(
            id=_stable_id("ref", source.id, parsed.parser_version, stable_key),
            source_document_id=source.id,
            chapter_id=chapter.id,
            parser_version=parser_version,
            page_number=location.page_number,
            char_start=location.char_start,
            char_end=location.char_end,
            image_region=dict(location.image_region) if location.image_region else None,
            location_kind=location.kind,
            location_index=location.index,
            location_label=location.label,
            location_metadata={
                **dict(location.metadata),
                "slide_number": location.slide_number,
                "cell_index": location.cell_index,
                "cell_type": location.cell_type,
            },
            content_hash=parsed.processed_sha256,
            quote=quote,
        )
        session.add(ref)
        refs.append(ref)

    point_counter = 0
    for chapter, spec in zip(chapters, chapter_specs):
        for point in _normalize_knowledge_points(spec.get("knowledge_points")):
            point_counter += 1
            code = re.sub(r"[^0-9A-Za-z一-龥_-]+", "-", str(point.get("code") or "").strip())[:64] or f"KP-{point_counter:03d}"
            point_id = _stable_id("kp", source.id, code)
            knowledge = session.get(DBKnowledgePoint, point_id)
            if knowledge is None:
                knowledge = DBKnowledgePoint(
                    id=point_id,
                    domain_pack=f"resource:{source.id}",
                    code=code,
                    version=parsed.processed_sha256[:16],
                    title=str(point.get("title") or code)[:256],
                    level=str(point.get("level") or "core")[:32],
                    prerequisites=list(point.get("prerequisites") or []),
                    status="active",
                )
                session.add(knowledge)
                session.flush()
            relation_id = _stable_id("ckp", chapter.id, knowledge.id, "teaches")
            if session.get(DBChapterKnowledgePoint, relation_id) is None:
                session.add(DBChapterKnowledgePoint(
                    id=relation_id,
                    chapter_id=chapter.id,
                    knowledge_point_id=knowledge.id,
                    relation_type="teaches",
                ))
    return source, refs


def _index_canonical_chunks(
    evidence_chunks: tuple,
    *,
    source_document_id: str,
    source_ref_ids: list[str],
    source_status: str,
    owner_id: str,
) -> list[str]:
    """Index only ready canonical sources and annotate legacy evidence with provenance."""
    if source_status != "ready":
        return ["rag_index_skipped_source_unavailable"]
    if not evidence_chunks:
        return []
    primary_ref = source_ref_ids[0] if source_ref_ids else ""
    locatable = tuple(
        replace(
            item,
            metadata={
                **dict(getattr(item, "metadata", {}) or {}),
                "source_document_id": source_document_id,
                "source_ref_id": primary_ref,
                "canonical_source": True,
                "processing_status": "ready",
            },
        )
        for item in evidence_chunks
    )
    try:
        hybrid_rag.ingest_user_documents(locatable, owner_id=owner_id)
    except Exception:
        return ["rag_index_deferred"]
    return []


def _personal_source_provenance(
    source: DBSourceDocument | None,
    refs: list[DBSourceRef] | tuple[DBSourceRef, ...] = (),
) -> dict[str, Any]:
    if source is None:
        return {
            "source_document_id": "",
            "source_parser_version": "",
            "source_sha256": "",
            "processed_sha256": "",
            "source_processing_status": "legacy_unmigrated",
            "source_processing_error_code": "",
            "source_parser_metadata": {},
            "source_parse_warnings": [],
            "source_locations": [],
        }
    return {
        "source_document_id": source.id,
        "source_parser_version": source.parser_version,
        "source_sha256": source.source_sha256 or source.content_hash,
        "processed_sha256": source.processed_sha256 or source.content_hash,
        "source_processing_status": source.processing_status,
        "source_processing_error_code": source.processing_error_code or "",
        "source_parser_metadata": source.parser_metadata or {},
        "source_parse_warnings": source.parse_warnings or [],
        "source_locations": [
            {
                "source_ref_id": ref.id,
                "kind": ref.location_kind,
                "index": ref.location_index,
                "label": ref.location_label,
                "page_number": ref.page_number,
                "char_start": ref.char_start,
                "char_end": ref.char_end,
                "quote": ref.quote,
                "image_region": ref.image_region,
                "metadata": ref.location_metadata or {},
            }
            for ref in refs
        ],
    }


def _course_manifest_provenance(course, document) -> dict[str, Any]:
    manifest = course.manifest_data if isinstance(course.manifest_data, dict) else {}
    for item in manifest.get("files", []):
        expected = f"{item.get('repository_key')}@{item.get('git_revision')}:{item.get('source_path')}"
        if document.source_path == expected or Path(str(item.get("path", ""))).name == document.filename:
            return {
                "source_sha256": item.get("source_sha256", ""),
                "source_license_spdx": item.get("license_spdx", ""),
                "source_license_file": item.get("license_file", ""),
                "source_license_sha256": item.get("license_sha256", ""),
                "source_obligations": item.get("obligations", []),
                "source_repository_key": item.get("repository_key", ""),
                "source_git_revision": item.get("git_revision", ""),
            }
    return {
        "source_sha256": "",
        "source_license_spdx": "",
        "source_license_file": "",
        "source_license_sha256": "",
        "source_obligations": [],
        "source_repository_key": "",
        "source_git_revision": "",
    }


def _canonical_course_provenance(course, document, source, source_ref, chapter) -> dict[str, Any]:
    return {
        **_course_manifest_provenance(course, document),
        "source_url": source.source_url if source else "",
        "source_document_id": source.id if source else "",
        "source_parser_version": source.parser_version if source else "",
        "processed_sha256": (
            (source.processed_sha256 or source.content_hash) if source else ""
        ),
        "source_processing_status": source.processing_status if source else "",
        "source_parser_metadata": (source.parser_metadata or {}) if source else {},
        "source_parse_warnings": (source.parse_warnings or []) if source else [],
        "source_ref_id": source_ref.id if source_ref else "",
        "source_ref_char_start": source_ref.char_start if source_ref else None,
        "source_ref_char_end": source_ref.char_end if source_ref else None,
        "source_ref_quote": source_ref.quote if source_ref else "",
        "source_ref_location_kind": source_ref.location_kind if source_ref else "",
        "source_ref_location_index": source_ref.location_index if source_ref else None,
        "source_ref_location_label": source_ref.location_label if source_ref else "",
        "source_chapter_id": chapter.id if chapter else "",
        "source_chapter_title": chapter.title if chapter else "",
    }


def build_canonical_course_source_detail(session, current_user: DBUser, source_document_id: str) -> dict[str, Any]:
    source = session.get(DBSourceDocument, source_document_id)
    if source is None:
        raise HTTPException(status_code=404, detail="课程来源未找到")
    course = session.get(DBCourse, source.course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="课程未找到")
    membership = session.query(DBCourseMembership).filter_by(
        course_id=course.id,
        user_public_id=current_user.public_id,
        status="active",
    ).first()
    default_shelf_access = (
        course.id == DEFAULT_SHELF_COURSE_ID
        and course.visibility == "public"
        and course.status == "published"
    )
    if current_user.role != "admin" and membership is None and not default_shelf_access:
        raise HTTPException(status_code=403, detail="无权读取该课程来源")

    course_document = (
        session.get(DBCourseDocument, source.legacy_document_id)
        if source.legacy_document_id
        else None
    )
    personal_document = (
        session.get(DBKnowledgeDocument, source.legacy_document_id)
        if source.legacy_document_id
        else None
    )
    is_multimodal = False
    multimodal_metadata: dict[str, Any] = {}
    if (
        course_document is not None
        and course_document.course_id == course.id
        and course_document.status == "published"
    ):
        content = course_document.content or ""
        raw = content.encode("utf-8")
        actual_hash = hashlib.sha256(raw).hexdigest()
        expected_hash = str(source.processed_sha256 or "")
        if expected_hash and actual_hash.lower() != expected_hash.lower():
            raise HTTPException(status_code=409, detail="课程解析正文哈希与冻结记录不一致")
    elif personal_document is not None:
        content = personal_document.content or ""
        raw = content.encode("utf-8")
        actual_hash = hashlib.sha256(raw).hexdigest()
        expected_hash = str(source.processed_sha256 or source.content_hash or "")
        if expected_hash and actual_hash.lower() != expected_hash.lower():
            raise HTTPException(status_code=409, detail="个人资料解析正文哈希与记录不一致")
        is_multimodal = bool(personal_document.is_multimodal)
        multimodal_metadata = personal_document.multimodal_metadata or {}
    else:
        project_root = Path(__file__).resolve().parent
        source_path = Path(str(source.source_path or ""))
        resolved = (source_path if source_path.is_absolute() else project_root / source_path).resolve()
        if resolved != project_root and project_root not in resolved.parents:
            raise HTTPException(status_code=409, detail="课程来源路径超出项目边界")
        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="课程来源文件不存在")
        raw = resolved.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        expected_hash = str(source.source_sha256 or source.content_hash or "")
        if expected_hash and actual_hash.lower() != expected_hash.lower():
            raise HTTPException(status_code=409, detail="课程来源文件哈希与冻结记录不一致")
        content = raw.decode("utf-8", errors="replace")

    refs = session.query(DBSourceRef).filter_by(source_document_id=source.id).order_by(
        DBSourceRef.location_index, DBSourceRef.id,
    ).all()
    source_ref = refs[0] if refs else None
    chapter = session.get(DBChapter, source_ref.chapter_id) if source_ref and source_ref.chapter_id else None
    return {
        "id": source.id,
        "filename": source.filename,
        "file_type": source.file_format,
        "file_size": source.file_size or len(raw),
        "title": source.title,
        "content": content,
        "tags": [course.subject] if course.subject else [],
        "chunk_count": len(refs),
        "is_multimodal": is_multimodal,
        "multimodal_metadata": multimodal_metadata,
        "created_at": source.created_at.isoformat() if source.created_at else "",
        "scope": "course",
        "deletable": False,
        "course_id": course.id,
        "course_title": course.title,
        "course_version": course.version,
        "course_description": course.description,
        "course_domain_pack": course.domain_pack,
        "course_origin": course.content_origin,
        "course_license": source.license_text or course.license_text,
        "chapter_order": chapter.position if chapter else None,
        "content_hash": source.content_hash or actual_hash,
        "source_path": source.source_path,
        "source_url": source.source_url or "",
        "source_document_id": source.id,
        "source_sha256": source.source_sha256 or actual_hash,
        "processed_sha256": source.processed_sha256 or source.content_hash or actual_hash,
        "source_parser_version": source.parser_version or "",
        "source_parser_metadata": source.parser_metadata or {},
        "source_parse_warnings": source.parse_warnings or [],
        "source_processing_status": source.processing_status or "",
        "source_ref_id": source_ref.id if source_ref else "",
        "source_ref_char_start": source_ref.char_start if source_ref else None,
        "source_ref_char_end": source_ref.char_end if source_ref else None,
        "source_ref_quote": source_ref.quote if source_ref else "",
        "source_ref_location_kind": source_ref.location_kind if source_ref else "",
        "source_ref_location_index": source_ref.location_index if source_ref else None,
        "source_ref_location_label": source_ref.location_label if source_ref else "",
        "source_chapter_id": chapter.id if chapter else "",
        "source_chapter_title": chapter.title if chapter else "",
        "source_git_revision": course.manifest_version,
        "source_license_file": "",
        "source_license_sha256": "",
    }


@router.post("/upload")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    student_id: str = "default",
    course_id: str = "",
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    student_id = enforce_student_access(student_id, current_user)
    owner_public_id, target_course_id = await run_db_op(
        lambda session: _resolve_upload_target(
            session,
            student_id=student_id,
            current_user=current_user,
            course_id=course_id,
        )
    )

    filename = file.filename or "unnamed"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(SUPPORTED_EXTENSIONS.keys())
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}，支持 {allowed}")

    raw = await file.read(CONFIG.max_upload_bytes + 1)
    file_size = len(raw)
    if file_size > CONFIG.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"文件超过大小限制 ({CONFIG.max_upload_bytes} bytes)")

    source_sha256 = hashlib.sha256(raw).hexdigest()

    def find_existing(session):
        source = session.query(DBSourceDocument).filter_by(
            course_id=target_course_id,
            source_sha256=source_sha256,
            processing_status="ready",
        ).first()
        if source is None or not source.legacy_document_id:
            return None
        document = session.get(DBKnowledgeDocument, source.legacy_document_id)
        if document is None:
            return None
        ref_count = session.query(DBSourceRef).filter_by(source_document_id=source.id).count()
        return {
            "id": document.id,
            "filename": document.filename,
            "file_type": document.file_type,
            "file_category": SUPPORTED_EXTENSIONS.get(f".{document.file_type}", "document"),
            "file_size": document.file_size,
            "chunk_count": document.chunk_count,
            "tags": document.tags or [],
            "is_multimodal": document.is_multimodal,
            "multimodal_metadata": document.multimodal_metadata or {},
            "doc_guide_status": "existing",
            "content_preview": (document.content or "")[:300],
            "course_id": target_course_id,
            "source_document_id": source.id,
            "source_ref_count": ref_count,
            "source_parser_version": source.parser_version,
            "source_sha256": source.source_sha256,
            "processed_sha256": source.processed_sha256,
            "source_processing_status": source.processing_status,
            "source_parser_metadata": source.parser_metadata or {},
            "source_parse_warnings": source.parse_warnings or [],
            "indexing_warnings": [],
            "duplicate": True,
        }

    existing = await run_db_op(find_existing)
    if existing is not None:
        return existing

    doc_id = _stable_id("kdoc", target_course_id, source_sha256)
    # A failed extraction is retained for audit/retry, but must not block a new
    # attempt with the same bytes. Ready sources still take the idempotent path
    # above; only an existing non-ready attempt receives a fresh attempt id.
    failed_attempt_exists = await run_db_op(
        lambda session: session.query(DBKnowledgeDocument.id).filter_by(id=doc_id).first() is not None
    )
    if failed_attempt_exists:
        doc_id = _stable_id("kdoc-attempt", target_course_id, source_sha256, uuid.uuid4().hex)

    file_category = SUPPORTED_EXTENSIONS[ext]
    is_multimodal = file_category in ("video", "presentation")

    # 原始上传先落盘。解析失败时不丢失用户文件，数据库不会伪造 ready 来源。
    doc_file_path = _write_upload_file(
        student_id=student_id, document_id=doc_id, ext=ext, raw=raw
    )
    ocr_dir = _ocr_asset_dir(student_id=student_id, document_id=doc_id)
    try:
        parsed = parse_document(
            raw,
            filename,
            offline_ocr=ext == ".pdf",
            ocr_asset_dir=ocr_dir if ext == ".pdf" else None,
        )
    except DocumentParseError as exc:
        if ocr_dir.parent.exists():
            shutil.rmtree(ocr_dir.parent)
        raise HTTPException(
            status_code=422,
            detail={
                "code": exc.code,
                "message": str(exc),
                "file_format": exc.file_format,
                "original_file_retained": True,
                "original_file_path": str(doc_file_path),
                "document_id": doc_id,
                "retryable": True,
            },
        ) from exc
    except Exception as exc:
        if ocr_dir.parent.exists():
            shutil.rmtree(ocr_dir.parent)
        raise HTTPException(
            status_code=422,
            detail={
                "code": "document_parse_failed",
                "message": "资料解析失败，原文件已保留，请重试。",
                "file_format": ext.lstrip("."),
                "original_file_retained": True,
                "original_file_path": str(doc_file_path),
                "document_id": doc_id,
                "retryable": True,
            },
        ) from exc
    text_content = parsed.text
    evidence_chunks = chunk_document(text_content, source=filename)

    # B28 专用真实模型边界：结构/章节/知识点提取失败时保留 failed 状态，
    # 绝不以模板或确定性内容伪造 LLM 成功结果。
    try:
        resource_llm = build_swarm_from_headers(request.headers)
        resource_structure = await _extract_resource_structure(
            parsed,
            llm=resource_llm.llm,
            owner_public_id=current_user.public_id,
            course_id=target_course_id,
        )
    except Exception as exc:
        resource_structure = _pending_structure(
            parsed,
            model_meta=None,
            error_code="course_resource_structure_model_unavailable",
            message=exc,
        )

    # ── 成员 3 任务 1: PDF 多模态视觉解析 ──
    visual_evidence: list = []
    if ext == ".pdf" and _visual_page_externalization_allowed(parsed):
        try:
            visual_evidence = parse_pdf_visually(
                raw,
                filename,
                owner_public_id=current_user.public_id,
                model_call_context={"trace_id": f"m5-pdf-upload-{uuid.uuid4().hex}"},
            )
            if visual_evidence:
                # 注册视觉证据到 VisRAG 索引
                hybrid_rag.visual_index.index.upsert(tuple(visual_evidence))
        except Exception as e:
            print(f"  [knowledge_api] PDF 视觉解析失败（非致命）: {e}")

    # ── 成员 3 任务 2: 增量图谱自生长（句级别 diff + 三元组提取）──
    graph_report = build_graph_after_upload(evidence_chunks, source=filename, previous_text="")

    extra_metadata = {}
    if ext in (".pptx", ".ppt"):
        try:
            slides = parse_pptx_slides(raw)
            extra_metadata["slide_count"] = len(slides)
            extra_metadata["has_images"] = any(s["images"] for s in slides)
        except Exception:
            pass
    elif file_category == "video":
        extra_metadata["video_duration"] = _estimate_video_duration(raw)

    db_doc = DBKnowledgeDocument(
        id=doc_id,
        student_id=student_id,
        filename=filename,
        file_type=ext.lstrip("."),
        file_size=file_size,
        title=os.path.splitext(filename)[0],
        content=text_content,
        tags=list({tag for chunk in evidence_chunks for tag in chunk.tags}),
        chunk_count=len(evidence_chunks),
        is_multimodal=is_multimodal,
        multimodal_metadata=extra_metadata,
    )
    
    def save_doc(session):
        session.add(db_doc)
        session.flush()
        source, refs = _persist_personal_canonical_source(
            session,
            document=db_doc,
            parsed=parsed,
            owner_public_id=owner_public_id,
            uploader_public_id=current_user.public_id,
            course_id=target_course_id,
            structure=resource_structure,
            source_path=doc_file_path,
        )
        session.commit()
        return (
            source.id,
            len(refs),
            source.processing_status,
            source.processing_error_code,
            [ref.id for ref in refs],
        )

    try:
        (
            source_document_id,
            source_ref_count,
            source_processing_status,
            source_processing_error_code,
            source_ref_ids,
        ) = await run_db_op(save_doc)
    except Exception:
        if doc_file_path.exists():
            doc_file_path.unlink()
        if ocr_dir.parent.exists():
            shutil.rmtree(ocr_dir.parent)
        raise

    indexing_warnings = _index_canonical_chunks(
        evidence_chunks,
        source_document_id=source_document_id,
        source_ref_ids=source_ref_ids,
        source_status=source_processing_status,
        owner_id=student_id,
    )

    try:
        from learning_strategy import invalidate_graph_cache
        invalidate_graph_cache()
    except Exception:
        pass

    # 调度异步文档导读生成（NotebookLM 风格）
    if text_content.strip():
        background_tasks.add_task(
            _generate_doc_guide_for_document,
            doc_id=doc_id,
            student_id=student_id,
            owner_public_id=current_user.public_id,
            text_content=text_content[:12000],
        )

    return {
        "id": doc_id,
        "filename": filename,
        "file_type": ext.lstrip("."),
        "file_category": file_category,
        "file_size": file_size,
        "chunk_count": len(evidence_chunks),
        "tags": list({tag for chunk in evidence_chunks for tag in chunk.tags}),
        "is_multimodal": is_multimodal,
        "multimodal_metadata": extra_metadata,
        "doc_guide_status": "pending",
        "content_preview": text_content[:300],
        "course_id": target_course_id,
        "source_document_id": source_document_id,
        "source_ref_count": source_ref_count,
        "source_parser_version": parsed.parser_version,
        "source_sha256": parsed.source_sha256,
        "processed_sha256": parsed.processed_sha256,
        "source_processing_status": source_processing_status,
        "source_processing_error_code": source_processing_error_code,
        "source_parser_metadata": {
            **dict(parsed.metadata or {}),
            "resource_structure": resource_structure,
        },
        "source_parse_warnings": list(parsed.warnings),
        "knowledge_extraction": resource_structure,
        "indexing_warnings": indexing_warnings,
        # 成员 3: 视觉解析 & 图谱自生长
        "visual_pages_parsed": len(visual_evidence),
        "ocr": (parsed.metadata or {}).get("ocr", {}),
        "graph_triplets_extracted": graph_report.raw_triplets if graph_report else 0,
        "graph_candidate_relations": graph_report.candidate_edges if graph_report else 0,
        "graph_edges_written": graph_report.written_edges if graph_report else 0,
        "graph_backend": graph_report.backend if graph_report else "",
        "duplicate": False,
    }


def _estimate_video_duration(raw: bytes) -> float:
    try:
        import io
        from moviepy import VideoFileClip
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(raw)
            tmp = f.name
        try:
            with VideoFileClip(tmp) as clip:
                return clip.duration
        finally:
            os.unlink(tmp)
    except Exception:
        pass
    return 0.0


@router.post("/upload-batch")
async def upload_document_batch(
    request: Request,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    student_id: str = "default",
    course_id: str = "",
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """Process each document independently and report sanitized per-item outcomes."""
    if not files:
        raise HTTPException(status_code=400, detail="至少需要一个文件")
    if len(files) > 20:
        raise HTTPException(status_code=413, detail="单批最多上传 20 个文件")
    results: list[dict[str, Any]] = []
    for file in files:
        filename = file.filename or "unnamed"
        try:
            payload = await upload_document(
                request=request,
                background_tasks=background_tasks,
                file=file,
                student_id=student_id,
                course_id=course_id,
                current_user=current_user,
            )
            results.append({
                "filename": filename,
                "status": "ready" if payload.get("source_processing_status") == "ready" else "failed",
                "document": payload,
            })
        except HTTPException as exc:
            detail = exc.detail
            if isinstance(detail, dict):
                error = {
                    "code": str(detail.get("code") or "document_rejected"),
                    "message": str(detail.get("message") or "文档处理失败"),
                }
                for key in ("original_file_retained", "original_file_path", "document_id", "retryable"):
                    if key in detail:
                        error[key] = detail[key]
            else:
                error = {"code": "document_rejected", "message": str(detail)}
            results.append({
                "filename": filename,
                "status": "failed",
                "http_status": exc.status_code,
                "error": error,
            })
        except Exception:
            results.append({
                "filename": filename,
                "status": "failed",
                "http_status": 500,
                "error": {"code": "document_processing_failed", "message": "文档处理失败"},
            })
    succeeded = sum(item["status"] == "ready" for item in results)
    return {
        "schema_version": "edumatrix.document-batch.v1",
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@router.get("/list")
async def list_documents(
    student_id: str = "default",
    current_user=Depends(get_current_user),
) -> list[dict[str, Any]]:
    student_id = enforce_student_access(student_id, current_user)
    def fetch_docs(session):
        legacy, course = LegacyReadRepository(session).knowledge_library_rows(student_id)
        observe_legacy_shadow_read(
            session, chain_id="knowledge-source-note", legacy_result=(legacy, course),
            canonical_loader=lambda: KnowledgeSourceNoteCanonicalReader(session).knowledge_library_rows(student_id),
            legacy_projector=project_model_tree,
            actor_public_id=current_user.public_id,
        )
        legacy_ids = [document.id for document in legacy]
        sources = session.query(DBSourceDocument).filter(
            DBSourceDocument.legacy_document_id.in_(legacy_ids)
        ).all() if legacy_ids else []
        return legacy, course, {source.legacy_document_id: source for source in sources}

    legacy_documents, course_documents, personal_sources = await run_db_op(fetch_docs)
    course_rows = [
        {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "title": doc.title,
            "content_preview": (doc.content or "")[:200],
            "tags": doc.tags or [],
            "chunk_count": doc.chunk_count,
            "is_multimodal": False,
            "multimodal_metadata": {},
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
            "scope": "course",
            "deletable": False,
            "course_id": course.id,
            "course_title": course.title,
            "course_version": course.version,
            "course_description": course.description,
            "course_domain_pack": course.domain_pack,
            "course_origin": course.content_origin,
            "course_license": course.license_text,
            "chapter_order": doc.chapter_order,
            "content_hash": doc.content_hash,
            "source_path": doc.source_path,
        }
        | _canonical_course_provenance(course, doc, source, source_ref, chapter)
        for doc, course, source, source_ref, chapter in course_documents
    ]
    legacy_rows = [
        {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "title": doc.title,
            "content_preview": (doc.content or "")[:200],
            "tags": doc.tags or [],
            "chunk_count": doc.chunk_count,
            "is_multimodal": doc.is_multimodal,
            "multimodal_metadata": doc.multimodal_metadata or {},
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
            "scope": "personal" if doc.student_id == student_id else "legacy_public",
            "deletable": doc.student_id == student_id,
            "owner_id": doc.student_id,
            **_personal_source_provenance(personal_sources.get(doc.id)),
        }
        for doc in legacy_documents
    ]
    return course_rows + legacy_rows


def _course_recommendation_basis(profile: DBStudentProfile | None) -> dict[str, Any]:
    if profile is None:
        return {
            "mode": "neutral_course_catalog",
            "labels": [],
            "explanation": "尚无可用画像证据，按已审核课程目录和当前书架关系推荐。",
        }
    values = [
        str(profile.target_course or ""),
        str(profile.knowledge_base or ""),
        str(profile.cognitive_style or ""),
        *[str(item) for item in (profile.learning_goals or [])],
        *[str(item) for item in (profile.weak_points or [])],
    ]
    profile_text = " ".join(value for value in values if value).strip()
    labels = [keyword for keyword in RECOMMENDATION_KEYWORDS if keyword.lower() in profile_text.lower()]
    return {
        "mode": "profile_evidence" if profile_text else "neutral_course_catalog",
        "labels": labels[:3],
        "explanation": (
            "使用当前画像中的课程目标、学习目标和薄弱方向进行本地匹配。"
            if profile_text
            else "画像尚未形成有效学习方向，按已审核课程目录和当前书架关系推荐。"
        ),
    }


def _recommendation_for_course(
    course: DBCourse,
    *,
    basis: dict[str, Any],
    shelf_courses: list[DBCourse],
) -> tuple[int, str]:
    course_text = " ".join(
        [
            str(course.title or ""),
            str(course.subject or ""),
            str(course.description or ""),
            str(course.domain_pack or ""),
        ]
    ).lower()
    matched = [label for label in basis.get("labels", []) if str(label).lower() in course_text]
    if matched:
        return 300 + len(matched), f"与你画像中的“{'、'.join(matched)}”学习方向相关"

    shelf_text = " ".join(
        f"{item.title} {item.subject} {item.domain_pack}" for item in shelf_courses
    ).lower()
    shared = [keyword for keyword in RECOMMENDATION_KEYWORDS if keyword.lower() in course_text and keyword.lower() in shelf_text]
    if shared:
        return 200 + len(shared), f"与你书架课程同属“{shared[0]}”方向，可作为延伸学习"
    return 100, "已完成来源和许可审核的本地课程，可用于扩展当前学习范围"


def _material_file_type(document: DBKnowledgeDocument) -> str:
    raw = str(document.file_type or "").strip().lower()
    if raw:
        return raw.lstrip(".")
    return Path(str(document.filename or "")).suffix.lower().lstrip(".")


def _material_is_candidate(document: DBKnowledgeDocument, source: DBSourceDocument | None) -> bool:
    """Keep only readable textbook-like documents for the auxiliary shelf."""
    filename = " ".join(str(document.filename or "").split()).strip().lower()
    title = " ".join(str(document.title or "").split()).strip().lower()
    file_type = _material_file_type(document)
    content = str(document.content or "").strip()
    if not content or len(content) < 900 or int(document.chunk_count or 0) < 4:
        return False
    if file_type not in _MATERIAL_FILE_TYPES:
        return False
    if filename.startswith(_MATERIAL_EXCLUDED_PREFIXES):
        return False
    if any(marker in filename or marker in title for marker in _MATERIAL_WEB_MARKERS):
        return False
    if str((document.multimodal_metadata or {}).get("import_kind") or "").lower() == "web_dehydrated":
        return False
    if source is not None and source.processing_status != "ready":
        return False
    return True


def _material_quality(document: DBKnowledgeDocument) -> tuple[int, str]:
    """Score completeness without pretending the document is course-approved."""
    chunks = max(0, int(document.chunk_count or 0))
    chars = len(str(document.content or ""))
    score = min(chunks, 120) + min(chars // 1000, 80)
    if chunks >= 40 or chars >= 50000:
        return score, "完整教材"
    if chunks >= 16 or chars >= 12000:
        return score, "系统课程资料"
    return score, "章节/课件补充"


def _material_recommendations(
    session,
    *,
    current_user: DBUser,
    shelf_course_ids: set[str],
    profile_basis: dict[str, Any],
    limit: int = 12,
    include_personal: bool = True,
) -> list[dict[str, Any]]:
    """Project owner/public legacy documents as recommendations, read-only.

    Legacy documents are useful discovery candidates even when an older upload
    never received a canonical source row. They are explicitly marked as
    auxiliary and can only be previewed until a course owner admits them.
    """
    # The course shelf is a shared discovery surface.  It opts out of the
    # caller's private uploads so one account's history cannot change another
    # account's recommended-material set.  Direct callers can keep the
    # historical owner-inclusive behavior by leaving include_personal=True.
    student_scope = ["public", "system"]
    if include_personal:
        student_scope.insert(0, current_user.username)
    documents = session.query(DBKnowledgeDocument).filter(
        DBKnowledgeDocument.student_id.in_(student_scope),
    ).order_by(DBKnowledgeDocument.created_at.desc(), DBKnowledgeDocument.id).all()
    document_ids = [document.id for document in documents]
    source_rows = (
        session.query(DBSourceDocument)
        .filter(DBSourceDocument.legacy_document_id.in_(document_ids))
        .order_by(DBSourceDocument.processing_status.desc(), DBSourceDocument.updated_at.desc(), DBSourceDocument.id)
        .all()
        if document_ids
        else []
    )
    source_by_document: dict[str, DBSourceDocument] = {}
    for source in source_rows:
        # Prefer a ready source if a legacy document has duplicate historical rows.
        existing = source_by_document.get(source.legacy_document_id)
        if existing is None or (
            source.processing_status == "ready" and existing.processing_status != "ready"
        ):
            source_by_document[source.legacy_document_id] = source

    course_ids = {source.course_id for source in source_rows if source.course_id}
    courses = session.query(DBCourse).filter(DBCourse.id.in_(course_ids)).all() if course_ids else []
    course_by_id = {course.id: course for course in courses}
    source_ids = [source.id for source in source_rows if source.id]
    chapter_rows = (
        session.query(DBChapter)
        .filter(DBChapter.source_document_id.in_(source_ids))
        .order_by(DBChapter.position, DBChapter.id)
        .all()
        if source_ids
        else []
    )
    chapter_by_source: dict[str, DBChapter] = {}
    for chapter in chapter_rows:
        chapter_by_source.setdefault(chapter.source_document_id, chapter)

    # A shared shelf must expose the same material set to every account.  The
    # owner-inclusive compatibility helper still supports profile weighting,
    # but the public/system projection deliberately uses deterministic quality
    # ordering so one learner's labels cannot push different documents into
    # the limited recommendation window.
    labels = (
        [str(label).strip() for label in (profile_basis.get("labels") or []) if str(label).strip()]
        if include_personal
        else []
    )
    candidates_by_content: dict[str, tuple[int, dict[str, Any]]] = {}
    for document in documents:
        source = source_by_document.get(document.id)
        if source is not None and source.course_id in shelf_course_ids:
            continue
        if not _material_is_candidate(document, source):
            continue
        content = str(document.content or "")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        quality_score, quality_label = _material_quality(document)
        searchable = " ".join([
            str(document.title or ""),
            str(document.filename or ""),
            " ".join(str(item) for item in (document.tags or [])),
            content[:6000],
        ]).lower()
        matched = [label for label in labels if label.lower() in searchable]
        topic_hit = any(hint.lower() in searchable for hint in _MATERIAL_TOPIC_HINTS)
        if not topic_hit and quality_score < 18:
            continue
        source_course = course_by_id.get(source.course_id) if source else None
        if (
            source_course is not None
            and source_course.visibility != "public"
            and source_course.owner_public_id != current_user.public_id
        ):
            # A public legacy row must not bypass a private course boundary.
            continue
        chapter = chapter_by_source.get(source.id) if source else None
        is_canonical = bool(source and source.processing_status == "ready")
        traceability = "canonical_source" if is_canonical else "legacy_document"
        reason_parts = []
        if matched:
            reason_parts.append(f"与你画像中的“{'、'.join(matched[:2])}”方向相关")
        reason_parts.append(quality_label)
        reason_parts.append("已有可定位解析来源" if is_canonical else "已有正文和分块，加入主课程前需审核")
        score = quality_score + (len(matched) * 30) + (25 if is_canonical else 0)
        payload = {
            "id": document.id,
            "title": str(document.title or document.filename or "未命名教材").strip(),
            "filename": document.filename or "",
            "file_type": _material_file_type(document),
            "file_size": int(document.file_size or 0),
            "chunk_count": int(document.chunk_count or 0),
            "content_preview": " ".join(content.split())[:260],
            "tags": list(document.tags or [])[:8],
            "course_id": source.course_id if source else "",
            "course_title": source_course.title if source_course else "",
            "source_document_id": source.id if is_canonical else "",
            "chapter_id": chapter.id if chapter else "",
            "chapter_title": chapter.title if chapter else "",
            "source_processing_status": source.processing_status if source else "legacy_unmigrated",
            "traceability": traceability,
            "quality_score": score,
            "quality_label": quality_label,
            "matched_profile_labels": matched[:3],
            "recommendation_reason": "；".join(reason_parts),
            "material_kind": "textbook" if quality_label == "完整教材" else "courseware",
            "requires_review": True,
            "open_mode": "reader" if is_canonical else "preview",
            "owner_scope": "personal" if document.student_id == current_user.username else "public",
            # Keep the legacy document scope explicit so operator previews can
            # request the same owner boundary that was used for the candidate.
            # Students still resolve this to their own username in the client;
            # the repository includes public/system rows in that scope.
            "owner_id": document.student_id,
        }
        existing = candidates_by_content.get(content_hash)
        if existing is None or score > existing[0]:
            candidates_by_content[content_hash] = (score, payload)

    candidates = list(candidates_by_content.values())
    candidates.sort(key=lambda pair: (-pair[0], pair[1]["title"], pair[1]["id"]))
    return [payload for _score, payload in candidates[:limit]]


def _course_catalog_payload(session, current_user: DBUser) -> dict[str, Any]:
    active_memberships = session.query(DBCourseMembership).filter_by(
        user_public_id=current_user.public_id,
        status="active",
    ).all()
    membership_by_course = {item.course_id: item for item in active_memberships}
    published_courses = (
        session.query(DBCourse)
        .filter(DBCourse.status == "published")
        .order_by(DBCourse.title, DBCourse.id)
        .all()
    )
    visible_courses = []
    for course in published_courses:
        if course.visibility != "public" and course.id not in membership_by_course:
            continue
        manifest = course.manifest_data if isinstance(course.manifest_data, dict) else {}
        is_owned_empty_personal = (
            course.owner_public_id == current_user.public_id
            and manifest.get("kind") == "personal_course"
        )
        if course_is_selectable(session, course) or is_owned_empty_personal:
            visible_courses.append(course)
    course_ids = [course.id for course in visible_courses]
    documents = (
        session.query(DBCourseDocument)
        .filter(
            DBCourseDocument.course_id.in_(course_ids),
            DBCourseDocument.status == "published",
        )
        .order_by(DBCourseDocument.course_id, DBCourseDocument.chapter_order)
        .all()
        if course_ids
        else []
    )
    sources = (
        session.query(DBSourceDocument)
        .filter(DBSourceDocument.course_id.in_(course_ids))
        .order_by(DBSourceDocument.course_id, DBSourceDocument.filename)
        .all()
        if course_ids
        else []
    )
    legacy_document_ids = [source.legacy_document_id for source in sources if source.legacy_document_id]
    personal_documents = (
        session.query(DBKnowledgeDocument)
        .filter(DBKnowledgeDocument.id.in_(legacy_document_ids))
        .all()
        if legacy_document_ids
        else []
    )
    personal_document_by_id = {document.id: document for document in personal_documents}
    chapters = (
        session.query(DBChapter)
        .filter(DBChapter.course_id.in_(course_ids))
        .order_by(DBChapter.course_id, DBChapter.position)
        .all()
        if course_ids
        else []
    )
    chapter_ids = [chapter.id for chapter in chapters]
    chapter_relations = (
        session.query(DBChapterKnowledgePoint)
        .filter(DBChapterKnowledgePoint.chapter_id.in_(chapter_ids))
        .all()
        if chapter_ids
        else []
    )

    documents_by_course: dict[str, list[DBCourseDocument]] = {}
    sources_by_course: dict[str, list[DBSourceDocument]] = {}
    chapters_by_course: dict[str, list[DBChapter]] = {}
    source_by_id = {source.id: source for source in sources}
    relations_by_chapter: dict[str, set[str]] = {}
    for document in documents:
        documents_by_course.setdefault(document.course_id, []).append(document)
    for source in sources:
        sources_by_course.setdefault(source.course_id, []).append(source)
    for chapter in chapters:
        chapters_by_course.setdefault(chapter.course_id, []).append(chapter)
    for relation in chapter_relations:
        relations_by_chapter.setdefault(relation.chapter_id, set()).add(relation.knowledge_point_id)

    default_course_id = DEFAULT_SHELF_COURSE_ID if any(
        course.id == DEFAULT_SHELF_COURSE_ID and course.visibility == "public"
        for course in visible_courses
    ) else next((course.id for course in visible_courses if course.visibility == "public"), "")
    shelf_ids = set(membership_by_course)
    if default_course_id:
        shelf_ids.add(default_course_id)
    shelf_courses = [course for course in visible_courses if course.id in shelf_ids]
    profile = session.get(DBStudentProfile, current_user.username)
    basis = _course_recommendation_basis(profile)

    def serialize(course: DBCourse, *, recommendation_reason: str = "") -> dict[str, Any]:
        course_documents = documents_by_course.get(course.id, [])
        course_sources = sources_by_course.get(course.id, [])
        course_chapters = chapters_by_course.get(course.id, [])
        effective_document_count = len(course_documents) or len(course_sources)
        kp_ids = {
            knowledge_point_id
            for chapter in course_chapters
            for knowledge_point_id in relations_by_chapter.get(chapter.id, set())
        }
        ready_source_count = sum(source.processing_status == "ready" for source in course_sources)
        indexed_document_count = (
            sum(int(document.chunk_count or 0) > 0 for document in course_documents)
            if course_documents
            else sum(
                int((personal_document_by_id.get(source.legacy_document_id).chunk_count or 0)) > 0
                for source in course_sources
                if source.legacy_document_id and personal_document_by_id.get(source.legacy_document_id)
            )
        )
        manifest = course.manifest_data if isinstance(course.manifest_data, dict) else {}
        manifest_files = manifest.get("files") if isinstance(manifest.get("files"), list) else []
        license_ready = bool(str(course.license_text or "").strip()) and all(
            str(item.get("license_spdx") or "").strip() and str(item.get("license_file") or "").strip()
            for item in manifest_files
        )
        source_health = (
            "ready"
            if effective_document_count
            and len(course_sources) >= effective_document_count
            and ready_source_count == len(course_sources)
            else "partial" if course_sources else "missing"
        )
        index_status = (
            "ready"
            if effective_document_count and indexed_document_count == effective_document_count
            else "partial" if indexed_document_count else "missing"
        )
        chapter_preview = []
        for chapter in course_chapters[:4]:
            source = source_by_id.get(chapter.source_document_id)
            chapter_preview.append(
                {
                    "id": chapter.id,
                    "position": chapter.position,
                    "title": chapter.title,
                    "document_id": source.legacy_document_id if source and source.legacy_document_id else "",
                    "source_document_id": source.id if source else "",
                    "knowledge_point_count": len(relations_by_chapter.get(chapter.id, set())),
                }
            )
        membership = membership_by_course.get(course.id)
        return {
            "id": course.id,
            "title": course.title,
            "subject": course.subject or "",
            "description": course.description or "",
            "version": course.version,
            "manifest_version": course.manifest_version,
            "domain_pack": course.domain_pack or "",
            "language": course.language or "",
            "content_origin": course.content_origin or "",
            "license": course.license_text or "",
            "visibility": course.visibility,
            "authority_status": "authoritative",
            "review_status": "approved" if license_ready else "source_review_required",
            "source_health": source_health,
            "index_status": index_status,
            "chapter_count": len(course_chapters),
            "document_count": effective_document_count,
            "knowledge_point_count": len(kp_ids),
            "source_count": len(course_sources),
            "ready_source_count": ready_source_count,
            "indexed_document_count": indexed_document_count,
            "repository_count": int((manifest.get("source_audit") or {}).get("approved_repository_count") or 0),
            "chapter_preview": chapter_preview,
            "first_document_id": (
                course_documents[0].id
                if course_documents
                else next((source.legacy_document_id for source in course_sources if source.legacy_document_id), "")
            ),
            "in_shelf": course.id in shelf_ids,
            "shelf_origin": (
                "team_preloaded" if course.id == default_course_id else "membership" if membership else ""
            ),
            "membership_role": membership.role if membership else None,
            "can_manage": course.owner_public_id == current_user.public_id,
            "course_kind": str(manifest.get("kind") or "curated_course"),
            "recommendation_reason": recommendation_reason,
            "requires_upload": bool(
                course.owner_public_id == current_user.public_id
                and effective_document_count == 0
            ),
        }

    shelf = sorted(
        [serialize(course) for course in shelf_courses],
        key=lambda item: (item["shelf_origin"] != "team_preloaded", item["title"], item["id"]),
    )
    ranked_recommendations = []
    for course in visible_courses:
        if course.id in shelf_ids:
            continue
        score, reason = _recommendation_for_course(course, basis=basis, shelf_courses=shelf_courses)
        ranked_recommendations.append((score, serialize(course, recommendation_reason=reason)))
    recommendations = [
        item for _score, item in sorted(
            ranked_recommendations,
            key=lambda pair: (-pair[0], pair[1]["title"], pair[1]["id"]),
        )
    ]
    material_recommendations = _material_recommendations(
        session,
        current_user=current_user,
        shelf_course_ids=shelf_ids,
        profile_basis=basis,
        include_personal=False,
    )
    return {
        "schema_version": "edumatrix.knowledge-course-shelf.v1",
        "requires_course_upload": False,
        "profile_basis": basis,
        "shelf": shelf,
        "recommendations": recommendations,
        "material_recommendations": material_recommendations,
        "material_recommendations_scope": "shared_public_system",
        "discovery": {
            "route": "/knowledge/discover",
            "status": "entry_available",
            "authority_boundary": "联网资料先作为候选来源，完成来源和许可确认后才能进入课程权威库。",
        },
    }


def _context_list(value: Any, *, limit: int = 12) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []
    return list(dict.fromkeys(" ".join(str(item).split())[:160] for item in values if str(item).strip()))[:limit]


def _profile_conditioned_discovery_context(
    session,
    current_user: DBUser,
    *,
    course_id: str = "",
    profile_snapshot_id: str = "",
) -> dict[str, dict[str, Any]]:
    """Read one owner-scoped course/profile snapshot for FB-27 without writing state."""
    requested_course_id = str(course_id or "").strip()
    course = session.get(DBCourse, requested_course_id) if requested_course_id else None
    if requested_course_id and course is None:
        raise HTTPException(status_code=404, detail="当前课程不存在")
    from course_catalog import course_is_selectable
    if course is not None and not course_is_selectable(session, course):
        raise HTTPException(status_code=409, detail="当前课程已停止发布或没有可用学习资料")
    if course is not None and course.visibility != "public" and course.owner_public_id != current_user.public_id:
        membership = session.query(DBCourseMembership).filter_by(
            course_id=course.id,
            user_public_id=current_user.public_id,
            status="active",
        ).first()
        if membership is None:
            raise HTTPException(status_code=403, detail="当前用户无权使用该课程进行联网推荐")

    explicit_snapshot_id = str(profile_snapshot_id or "").strip()
    snapshot = session.get(DBProfileSnapshot, explicit_snapshot_id) if explicit_snapshot_id else None
    if explicit_snapshot_id and snapshot is None:
        raise HTTPException(status_code=404, detail="画像快照不存在")
    if snapshot is not None and snapshot.owner_public_id != current_user.public_id:
        raise HTTPException(status_code=403, detail="当前用户无权使用该画像快照")

    snapshots = []
    if snapshot is None:
        snapshots = session.query(DBProfileSnapshot).filter_by(
            owner_public_id=current_user.public_id,
        ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).all()
        for candidate in snapshots:
            body = candidate.snapshot if isinstance(candidate.snapshot, dict) else {}
            candidate_course_id = str(body.get("course_id") or "").strip()
            if course is None or not candidate_course_id or candidate_course_id == course.id:
                snapshot = candidate
                break
    body = snapshot.snapshot if snapshot is not None and isinstance(snapshot.snapshot, dict) else {}
    snapshot_course_id = str(body.get("course_id") or "").strip()
    if course is not None and snapshot_course_id and snapshot_course_id != course.id:
        raise HTTPException(status_code=409, detail="画像快照与当前课程不一致，请选择同一课程的画像版本")
    if course is None and snapshot_course_id:
        candidate_course = session.get(DBCourse, snapshot_course_id)
        if candidate_course is not None:
            if not course_is_selectable(session, candidate_course):
                raise HTTPException(status_code=409, detail="画像绑定的课程已停止发布或没有可用学习资料")
            if candidate_course.visibility != "public" and candidate_course.owner_public_id != current_user.public_id:
                raise HTTPException(status_code=403, detail="当前画像绑定的课程不可用于联网推荐")
            course = candidate_course

    manifest = course.manifest_data if course is not None and isinstance(course.manifest_data, dict) else {}
    course_goals = _context_list(
        manifest.get("course_goals")
        or manifest.get("course_objectives")
        or manifest.get("learning_objectives")
        or manifest.get("objectives")
    )
    if not course_goals and course is not None and course.description:
        course_goals = _context_list([course.description], limit=3)
    profile_projection = body.get("profile_projection") if isinstance(body.get("profile_projection"), dict) else {}
    learning_goals = _context_list(body.get("learning_goals") or profile_projection.get("learning_goals"))
    weak_directions = _context_list(
        body.get("weak_points")
        or body.get("weak_directions")
        or body.get("weak_knowledge_point_ids")
        or profile_projection.get("weak_points")
    )
    preferences = _context_list(
        body.get("interaction_preferences")
        or body.get("preferences")
        or profile_projection.get("interaction_preferences"),
        limit=8,
    )
    time_budget = " ".join(str(body.get("time_budget") or body.get("weekly_time_budget") or "").split())[:120]
    course_context = {
        "course_id": course.id if course is not None else snapshot_course_id,
        "title": course.title if course is not None else "",
        "subject": course.subject if course is not None else "",
        "description": course.description if course is not None else "",
        "course_goals": course_goals,
        "version": course.version if course is not None else "",
    }
    profile_context = {
        "profile_snapshot_id": snapshot.id if snapshot is not None else "",
        "profile_version": snapshot.profile_version if snapshot is not None else "",
        "course_id": snapshot_course_id or course_context["course_id"],
        "course_goals": course_goals,
        "learning_goals": learning_goals,
        "weak_directions": weak_directions,
        "preferences": preferences,
        "time_budget": time_budget,
    }
    return {"course": course_context, "profile": profile_context}


def _ensure_course_profile_snapshot(session, *, course: DBCourse, current_user: DBUser) -> DBProfileSnapshot:
    """Create one owner/course profile context when a personal course is first created."""
    snapshot_id = _stable_id("course-profile", current_user.public_id, course.id)
    existing = session.get(DBProfileSnapshot, snapshot_id)
    if existing is not None:
        return existing

    profile = session.get(DBStudentProfile, current_user.username)
    projection: dict[str, Any] = {}
    profile_fields = (
        "major", "target_course", "knowledge_base", "cognitive_style",
        "motivation_type", "focus_level", "cognitive_load", "frustration_index",
        "learning_goals", "weak_points", "interaction_preferences",
        "misconception_patterns", "dimension_states", "mental_state_history",
    )
    if profile is not None:
        for field in profile_fields:
            value = getattr(profile, field, None)
            if value not in (None, "", [], {}):
                projection[field] = value

    # Registration snapshots may contain richer confirmed wording than the
    # legacy profile row. Copy only profile signals, never course mastery.
    source_snapshot_id = ""
    snapshots = session.query(DBProfileSnapshot).filter_by(
        owner_public_id=current_user.public_id,
    ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).all()
    for candidate in snapshots:
        body = candidate.snapshot if isinstance(candidate.snapshot, dict) else {}
        source_projection = body.get("profile_projection")
        if not isinstance(source_projection, dict):
            continue
        scoped_course = str(
            body.get("course_id")
            or (body.get("course_context") or {}).get("courseId")
            or ""
        ).strip()
        if scoped_course and scoped_course != course.id:
            continue
        for field in profile_fields:
            if field not in projection and source_projection.get(field) not in (None, "", [], {}):
                projection[field] = source_projection[field]
        source_snapshot_id = candidate.id
        break

    snapshot_data = {
        "kind": "course_profile_bootstrap",
        "owner_public_id": current_user.public_id,
        "legacy_student_id": current_user.username,
        "course_id": course.id,
        "course_context": {
            "courseId": course.id,
            "title": course.title,
            "source": "personal_course_creation",
        },
        "profile_projection": projection,
        "profile_source_snapshot_id": source_snapshot_id or None,
        "mastery_status": "awaiting_assessment",
        "mastery_evidence": [],
    }
    content_hash = hashlib.sha256(
        json.dumps(snapshot_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    snapshot = DBProfileSnapshot(
        id=snapshot_id,
        owner_public_id=current_user.public_id,
        legacy_student_id=current_user.username,
        profile_version="course.profile.v1",
        snapshot=snapshot_data,
        content_hash=content_hash,
        trace_id=f"course-profile:{course.id}",
    )
    session.add(snapshot)
    session.flush()
    return snapshot


@router.get("/courses")
async def list_course_shelf(current_user: DBUser = Depends(get_current_user)) -> dict[str, Any]:
    return await run_db_op(lambda session: _course_catalog_payload(session, current_user))


@router.post("/courses", status_code=201)
async def create_personal_course(
    payload: CourseCreateInput,
    current_user: DBUser = Depends(get_current_user),
) -> dict[str, Any]:
    def create(session):
        title = " ".join(payload.title.split())
        course_id = _stable_id("course", current_user.public_id, title.casefold())
        course = session.get(DBCourse, course_id)
        created = course is None
        if course is None:
            course = DBCourse(
                id=course_id,
                version="1",
                title=title,
                subject=" ".join(payload.subject.split()),
                description=payload.description.strip(),
                domain_pack="personal-course",
                language="zh-CN",
                content_origin="user-curated",
                license_text="用户自主管理；每份资料保留独立来源和许可说明",
                visibility="private",
                status="published",
                owner_public_id=current_user.public_id,
                manifest_version="personal-course-v1",
                manifest_data={
                    "kind": "personal_course",
                    "owner": current_user.public_id,
                    "created_from": "knowledge_course_creator",
                    "files": [],
                },
            )
            session.add(course)
            session.flush()
        elif course.owner_public_id != current_user.public_id:
            raise HTTPException(status_code=409, detail="课程标识已被占用")
        membership = session.query(DBCourseMembership).filter_by(
            course_id=course.id,
            user_public_id=current_user.public_id,
        ).first()
        if membership is None:
            session.add(DBCourseMembership(
                id=_stable_id("cm", course.id, current_user.public_id),
                course_id=course.id,
                user_public_id=current_user.public_id,
                role="student" if current_user.role == "student" else str(current_user.role or "student"),
                status="active",
            ))
        else:
            membership.status = "active"
        course_profile = _ensure_course_profile_snapshot(
            session,
            course=course,
            current_user=current_user,
        )
        session.commit()
        catalog = _course_catalog_payload(session, current_user)
        course_payload = next(
            (item for item in catalog["shelf"] if item["id"] == course.id),
            {
                "id": course.id,
                "title": course.title,
                "subject": course.subject or "",
                "description": course.description or "",
                "version": course.version,
                "visibility": course.visibility,
                "status": course.status,
                "selectable": False,
                "requires_upload": True,
                "in_shelf": True,
                "document_count": 0,
                "source_count": 0,
                "knowledge_point_count": 0,
            },
        )
        return {
            "schema_version": "edumatrix.personal-course.v1",
            "created": created,
            "course": course_payload,
            "profile_snapshot_id": course_profile.id,
        }

    return await run_db_op(create)


@router.post("/courses/{course_id}/shelf")
async def add_course_to_shelf(
    course_id: str,
    current_user: DBUser = Depends(get_current_user),
) -> dict[str, Any]:
    def add(session):
        course = session.get(DBCourse, course_id)
        if course is None or not course_is_selectable(session, course):
            raise HTTPException(status_code=404, detail="课程不存在或尚未发布")
        membership = session.query(DBCourseMembership).filter_by(
            course_id=course.id,
            user_public_id=current_user.public_id,
        ).first()
        if course.visibility != "public" and membership is None:
            raise HTTPException(status_code=403, detail="该课程不能直接加入书架")
        created = membership is None
        if membership is None:
            role = str(current_user.role or "student")
            if role not in {"admin", "teacher", "assistant", "student", "visitor"}:
                role = "student"
            membership = DBCourseMembership(
                course_id=course.id,
                user_public_id=current_user.public_id,
                role=role,
                status="active",
            )
            session.add(membership)
        else:
            membership.status = "active"
        session.commit()
        payload = _course_catalog_payload(session, current_user)
        course_payload = next((item for item in payload["shelf"] if item["id"] == course.id), None)
        return {
            "schema_version": "edumatrix.knowledge-course-shelf-membership.v1",
            "created": created,
            "course": course_payload,
            "shelf_count": len(payload["shelf"]),
        }

    return await run_db_op(add)


@router.get("/courses/{course_id}/graph")
async def get_course_knowledge_graph(
    course_id: str,
    current_user: DBUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await run_db_op(lambda session: build_course_graph(session, current_user, course_id))


@router.get("/discovery/search")
async def discover_web_materials(
    request: Request,
    q: str,
    max_results: Annotated[int, Field(ge=1, le=12)] = 8,
    course_id: str = "",
    profile_snapshot_id: str = "",
    current_user: DBUser = Depends(get_current_user),
) -> dict[str, Any]:
    context = await run_db_op(
        lambda session: _profile_conditioned_discovery_context(
            session,
            current_user,
            course_id=course_id,
            profile_snapshot_id=profile_snapshot_id,
        )
    )
    llm = None
    if context["profile"]["profile_snapshot_id"]:
        # The factory returns the orchestration container; profile query planning
        # needs the configured text backend held by its ``llm`` attribute.
        # Passing the swarm itself leaves no ``generate`` method and turns every
        # real profile-conditioned search into a provider failure before the
        # DeepSeek request is made.
        swarm = build_swarm_from_headers(request.headers)
        llm = getattr(swarm, "llm", swarm)
    return await search_web_materials(
        q,
        max_results,
        course_context=context["course"],
        profile_context=context["profile"],
        llm=llm,
        owner_public_id=current_user.public_id,
    )


@router.get("/discovery/candidates")
async def get_web_source_candidates(
    review_status: str | None = None,
    current_user: DBUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await run_db_op(lambda session: list_candidates(session, current_user, review_status))


@router.post("/discovery/candidates")
async def save_web_source_candidate(
    payload: CandidateCreate,
    current_user: DBUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await run_db_op(lambda session: create_candidate(session, current_user, payload))


@router.post("/discovery/candidates/{candidate_id}/admit")
async def admit_web_source_candidate(
    candidate_id: str,
    payload: CandidateAdmission,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: DBUser = Depends(get_current_user),
) -> dict[str, Any]:
    async def record_failure(stage: str, error: Exception) -> None:
        detail = getattr(error, "detail", None)
        if isinstance(detail, dict):
            message = str(detail.get("message") or detail.get("detail") or detail.get("code") or "处理失败")
            source_code = str(detail.get("code") or "")
        else:
            message = str(detail or error or "处理失败")
            source_code = ""
        lowered = f"{source_code} {message}".lower()
        code = source_code or f"{stage}_failed"
        if stage == "download" and not source_code and ("timeout" in lowered or "超时" in message):
            code = "download_timeout"
        try:
            await run_db_op(
                lambda session: mark_candidate_stage(
                    session,
                    current_user,
                    candidate_id,
                    stage=stage,
                    status="failed",
                    code=code,
                    message=message[:500],
                    retryable=True,
                )
            )
        except Exception:
            # Preserve the original HTTP/parse error if the diagnostic projection itself is unavailable.
            pass

    def prepare(session):
        candidate = prepare_candidate_admission(session, current_user, candidate_id, payload)
        _resolve_upload_target(
            session,
            student_id=current_user.username,
            current_user=current_user,
            course_id=payload.course_id,
        )
        return serialize_candidate(candidate)

    candidate = await run_db_op(prepare)
    if candidate["reviewStatus"] == "imported":
        return {"created": False, "candidate": candidate, "document": candidate.get("importResult") or {}}

    try:
        raw, filename, final_url = await _download_remote_material(
            url=candidate["url"],
            hinted_format=candidate["fileFormat"],
            title=candidate["title"],
        )
    except Exception as exc:
        await record_failure("download", exc)
        raise
    upload = UploadFile(filename=filename, file=BytesIO(raw))
    try:
        document = await upload_document(
            request=request,
            background_tasks=background_tasks,
            file=upload,
            student_id=current_user.username,
            course_id=payload.course_id,
            current_user=current_user,
        )
    except Exception as exc:
        await record_failure("parse", exc)
        raise

    def complete(session):
        source = session.get(DBSourceDocument, document["source_document_id"])
        if source is None:
            raise HTTPException(status_code=500, detail="资料已解析但来源投影缺失")
        source.source_url = final_url
        source.license_text = payload.license_text.strip() or payload.license_status
        source.parser_metadata = {
            **dict(source.parser_metadata or {}),
            "web_candidate_id": candidate_id,
            "author_or_organization": payload.author_or_organization.strip(),
            "usage_hint": payload.usage_hint.strip(),
            "trust_level": payload.trust_level,
        }
        session.commit()
        return complete_candidate_import(
            session,
            current_user,
            candidate_id,
            course_id=payload.course_id,
            document_id=document["id"],
            source_document_id=document["source_document_id"],
        )

    try:
        result = await run_db_op(complete)
    except Exception as exc:
        await record_failure("citation", exc)
        raise
    return {**result, "document": document}


@router.post("/discovery/candidates/{candidate_id}/reject")
async def reject_web_source_candidate(
    candidate_id: str,
    current_user: DBUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await run_db_op(lambda session: reject_candidate(session, current_user, candidate_id))


@router.post("/discovery/candidates/{candidate_id}/withdraw")
async def withdraw_web_source_candidate(
    candidate_id: str,
    current_user: DBUser = Depends(get_current_user),
) -> dict[str, Any]:
    return await run_db_op(lambda session: withdraw_candidate(session, current_user, candidate_id))



# ── 成员 3 任务 2: 图谱统计端点 ──
@router.get("/graph/stats")
async def graph_stats() -> dict[str, Any]:
    """返回当前知识图谱的统计信息（节点数、边数、后端类型）。"""
    try:
        builder = _get_graph_builder()
        if builder is None:
            return {"status": "unavailable", "nodes": 0, "edges": 0, "backend": "none"}
        repo = builder.repository
        backend = "neo4j" if hasattr(repo, "_driver") and repo._driver else "memory"
        governance = repo.governance_counts() if hasattr(repo, "governance_counts") else {}
        return {
            "status": "ok",
            "nodes": repo.count_nodes(),
            "edges": repo.count_edges(),
            "backend": backend,
            "governance": governance,
            "canonical_seed": getattr(builder, "canonical_seed_report", {}),
        }
    except Exception as e:
        return {"status": "error", "detail": str(e), "nodes": 0, "edges": 0, "backend": "error"}


# ── 成员 3 任务 3: 跨模态特征对齐搜索端点 ──
@router.get("/cross-search")
async def cross_modal_search(
    query: str = "",
    mode: str = "text",
    top_k: int = 5,
) -> dict[str, Any]:
    """跨模态搜索：用文字搜图片/公式，或用公式搜文字/图片。

    Args:
        query: 搜索词（文字描述或 LaTeX 公式）
        mode: 搜索模式 — "text" 用文字搜图片， "formula" 用公式搜文字
        top_k: 返回结果数量
    """
    if not query.strip():
        return {"status": "error", "detail": "查询不能为空", "results": []}

    try:
        from multimodal_alignment import get_cross_modal_aligner
        aligner = get_cross_modal_aligner()
        results = aligner.search(query, mode=mode, top_k=top_k)
        return {
            "status": "ok",
            "query": query,
            "mode": mode,
            "total": len(results),
            "results": results,
        }
    except ImportError:
        return {
            "status": "not_initialized",
            "detail": "跨模态对齐数据尚未构建。请先上传包含公式的教材文档以构建对齐索引。",
            "results": [],
        }
    except Exception as e:
        return {"status": "error", "detail": str(e), "results": []}


# === 异步文档导读生成（NotebookLM 风格）===

_DOC_GUIDE_PROMPT = """\
请仔细阅读以下文档内容，并生成一个 JSON 字典（不要包含任何额外字符或代码块标记）：

{
  "brief_summary": "一句话核心梗概",
  "highlights": ["核心看点1", "核心看点2", "核心看点3", "核心看点4", "核心看点5"],
  "faqs": [
    {"q": "常见问题1", "a": "答案1"},
    {"q": "常见问题2", "a": "答案2"},
    {"q": "常见问题3", "a": "答案3"}
  ]
}"""


class DocumentGuideFAQ(StrictModel):
    q: str = Field(min_length=1, max_length=500)
    a: str = Field(min_length=1, max_length=3000)


class DocumentGuide(StrictModel):
    brief_summary: str = Field(min_length=1, max_length=1000)
    highlights: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(
        min_length=1, max_length=10,
    )
    faqs: list[DocumentGuideFAQ] = Field(min_length=1, max_length=10)


async def _generate_doc_guide_for_document(
    doc_id: str,
    student_id: str,
    *,
    owner_public_id: str,
    text_content: str,
    llm: Any | None = None,
    database_runner=run_db_op,
) -> None:
    """后台任务：调用 LLM 生成文档导读指南并写入 DB。"""
    def document_exists(session):
        return session.query(DBKnowledgeDocument.id).filter_by(
            id=doc_id, student_id=student_id,
        ).first() is not None

    if not await database_runner(document_exists):
        return

    from llm_client import DEFAULT_ASYNC_LLM, parse_json_object
    active_llm = llm or DEFAULT_ASYNC_LLM
    system_prompt = _DOC_GUIDE_PROMPT
    user_prompt = f"文档内容：\n\n{text_content[:12000]}"
    provider = (
        "deterministic"
        if active_llm.__class__.__name__ == "AsyncDeterministicEducationLLM"
        else CONFIG.llm_provider
    )
    model = getattr(
        active_llm,
        "model",
        "deterministic" if provider == "deterministic" else CONFIG.llm_model,
    )
    lifecycle = StreamingModelCallLifecycle(
        capability="summarize",
        prompt_key="legacy_document_guide",
        prompt_version="1.0",
        provider=provider or "unknown",
        model=model or "unknown",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        owner_public_id=owner_public_id,
        trace_id=f"m5-doc-guide-{uuid.uuid4().hex}",
        input_summary={
            "operation": "document_guide",
            "document_id": doc_id,
            "source_chars": min(len(text_content), 12000),
            "document_body_included": False,
        },
        database_runner=database_runner,
    )
    await lifecycle.start()
    try:
        result = await active_llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            role="文档导读分析师",
        )
    except asyncio.CancelledError:
        await asyncio.shield(lifecycle.fail("client_disconnected"))
        raise
    except Exception:
        await lifecycle.fail("document_guide_provider_failed")
        return

    try:
        guide = DocumentGuide.model_validate(parse_json_object(result))
    except Exception:
        await lifecycle.fail("document_guide_output_invalid", result)
        return

    guide_data = guide.model_dump(mode="json")

    def update_doc_guide(session):
        changed = LegacyReadRepository(session).set_document_guide(
            doc_id, student_id, guide_data,
        )
        if changed:
            poststate = session.query(DBKnowledgeDocument).filter_by(id=doc_id, student_id=student_id).first()
            observe_legacy_shadow_read(
                session, chain_id="knowledge-source-note", legacy_result=poststate,
                canonical_loader=lambda: KnowledgeSourceNoteCanonicalReader(session).document_poststate(doc_id, student_id),
                legacy_projector=project_model_row,
                actor_public_id=owner_public_id,
                mode="canonical_write_postcheck",
            )
        return changed

    if not await database_runner(update_doc_guide):
        await lifecycle.fail("document_unavailable_after_generation")
        return
    await lifecycle.complete(result)

@router.post("/add-web-source")
async def add_web_source(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """将网页搜索结果作为 canonical 课程来源导入。"""
    import re
    from swarm_factory import build_swarm_from_headers
    payload = await request.json()
    query = str(payload.get("query", "")).strip()
    title = str(payload.get("title", "")).strip()
    url = str(payload.get("url", "")).strip()
    snippet = str(payload.get("snippet", "")).strip()
    student_id = enforce_student_access(payload.get("student_id"), current_user)
    course_id = str(payload.get("course_id", "")).strip()

    if not title or not snippet:
        raise HTTPException(status_code=400, detail="标题和摘要内容不能为空")

    owner_public_id, target_course_id = await run_db_op(
        lambda session: _resolve_upload_target(
            session,
            student_id=student_id,
            current_user=current_user,
            course_id=course_id,
        )
    )

    # 1. 采用 LLM 智能总结脱水（保留富媒体、配图与 Markdown 格式）
    dehydration_error = ""
    try:
        swarm = build_swarm_from_headers(request.headers)
        llm = swarm.llm
        system_prompt = (
            "你是一个顶级的学术与教育内容整理专家。你的任务是将给定的网页搜索标题和摘要片段进行“高保真脱水总结”，"
            "提炼整理成一篇逻辑严密、排版美观的结构化 Markdown 读书要点笔记。\n"
            "要求：\n"
            "1. 概括该网页所涉知识的核心定义与原理，剔除广告、杂音等不相干文本。\n"
            "2. 以 Markdown 格式排版，必须包含 # 标题、## 核心概念定义、## 核心推导/要点概括、## 拓展/知识拓扑。\n"
            "3. 必须保留原文中包含的所有配图链接 ![图片描述](URL)、视频直链与 LaTeX 数学公式 $...$ ，不可盲目删减图像与公式。\n"
            "4. 在文首显著标注网页来源 URL 直连卡片。\n"
            "5. 保持中立学术风格，全中文回复。"
        )
        user_prompt = (
            f"网页标题: {title}\n"
            f"网页来源URL: {url}\n"
            f"关联搜索词: {query}\n\n"
            f"网页内容摘要:\n{snippet}\n\n"
            "请开始生成富媒体脱水 Markdown 笔记："
        )
        text_content = await audited_legacy_text_call(
            llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            role="极客助教",
            operation="web_source_dehydration",
            capability="summarize",
            owner_public_id=current_user.public_id,
            input_summary={
                "query_chars": len(query),
                "title_chars": len(title),
                "snippet_chars": len(snippet),
                "source_host": urlparse(url).netloc[:253],
                "web_content_included": False,
            },
        )
    except Exception as e:
        dehydration_error = str(e)
        print(f"  [AddWebSource] LLM Dehydration failed: {e}")
        text_content = (
            f"# {title}\n\n"
            f"**来源URL**: {url}\n"
            f"**关联搜索词**: {query}\n\n"
            f"## 网页摘要\n{snippet}"
        )

    # 2. 生成友情文件名并过滤非法字符
    safe_title = re.sub(r'[\\/*?:\"<>|]', "", title)[:40]
    filename = f"[网页] {safe_title}.md"
    doc_id = hashlib.sha256(f"{student_id}:{filename}:{os.urandom(4).hex()}".encode()).hexdigest()[:16]

    raw = text_content.encode("utf-8")
    parsed = parse_document(raw, filename)

    # 3. 与本地上传使用同一结构抽取和 canonical admission 合同
    evidence_chunks = chunk_document(parsed.text, source=filename)
    try:
        structure_llm = build_swarm_from_headers(request.headers)
        resource_structure = await _extract_resource_structure(
            parsed,
            llm=structure_llm.llm,
            owner_public_id=owner_public_id,
            course_id=target_course_id,
        )
    except Exception as exc:
        resource_structure = _pending_structure(
            parsed,
            model_meta=None,
            error_code="course_resource_structure_model_unavailable",
            message=exc,
        )
    if dehydration_error:
        resource_structure = {
            **resource_structure,
            "status": "failed",
            "error": {
                "code": "web_source_dehydration_failed",
                "message": dehydration_error[:500],
                "retryable": True,
            },
        }
    
    # 4. 创建并写入数据库记录
    doc_tags = {tag for chunk in evidence_chunks for tag in chunk.tags}
    if query:
        doc_tags.add(query)
    doc_tags.discard("网页检索")

    db_doc = DBKnowledgeDocument(
        id=doc_id,
        student_id=student_id,
        filename=filename,
        file_type="md",
        file_size=len(raw),
        title=title,
        content=parsed.text,
        tags=list(doc_tags),
        chunk_count=len(evidence_chunks),
        is_multimodal=False,
        multimodal_metadata={"url": url, "query": query, "import_kind": "web_dehydrated"},
    )

    def save_doc(session):
        session.add(db_doc)
        session.flush()
        source, refs = _persist_personal_canonical_source(
            session,
            document=db_doc,
            parsed=parsed,
            owner_public_id=owner_public_id,
            uploader_public_id=current_user.public_id,
            course_id=target_course_id,
            structure=resource_structure,
            source_path=doc_file_path,
        )
        source.source_url = url
        source.parser_metadata = {
            **dict(source.parser_metadata or {}),
            "web_query": query,
            "dehydration_error": dehydration_error,
        }
        session.commit()
        return (
            source.id,
            [ref.id for ref in refs],
            source.processing_status,
            source.processing_error_code,
        )

    # 4. 与本地上传相同的原子文件落盘和来源登记
    doc_file_path = _write_upload_file(
        student_id=student_id,
        document_id=doc_id,
        ext=".md",
        raw=raw,
    )
    try:
        source_document_id, source_ref_ids, source_status, source_error = await run_db_op(save_doc)
    except Exception:
        if doc_file_path.exists():
            doc_file_path.unlink()
        raise

    indexing_warnings = _index_canonical_chunks(
        evidence_chunks,
        source_document_id=source_document_id,
        source_ref_ids=source_ref_ids,
        source_status=source_status,
        owner_id=student_id,
    )

    try:
        from learning_strategy import invalidate_graph_cache
        invalidate_graph_cache()
    except Exception:
        pass

    # 调度异步文档导读生成（NotebookLM 风格）
    if text_content.strip():
        background_tasks.add_task(
            _generate_doc_guide_for_document,
            doc_id=doc_id,
            student_id=student_id,
            owner_public_id=current_user.public_id,
            text_content=parsed.text[:12000],
        )

    return {
        "status": "success" if source_status == "ready" else "partial",
        "id": doc_id,
        "filename": filename,
        "file_type": "md",
        "chunk_count": len(evidence_chunks),
        "course_id": target_course_id,
        "source_document_id": source_document_id,
        "source_ref_count": len(source_ref_ids),
        "source_processing_status": source_status,
        "source_processing_error_code": source_error,
        "source_parser_version": parsed.parser_version,
        "source_sha256": parsed.source_sha256,
        "processed_sha256": parsed.processed_sha256,
        "knowledge_extraction": resource_structure,
        "indexing_warnings": indexing_warnings,
        "doc_guide_status": "pending",
        "content_preview": parsed.text[:300]
    }


@router.post("/download-web-file")
async def download_web_file(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """通过 URL 直链流式下载网页文档，并调用本地解析器进行深度导入。"""
    import re
    payload = await request.json()
    url = str(payload.get("url", "")).strip()
    file_type = str(payload.get("file_type", "")).strip().lower()
    title = str(payload.get("title", "")).strip()
    student_id = enforce_student_access(payload.get("student_id"), current_user)
    course_id = str(payload.get("course_id", "")).strip()

    if not url:
        raise HTTPException(status_code=400, detail="直链 URL 不能为空")
    if not file_type:
        raise HTTPException(status_code=400, detail="文件类型 (file_type) 不能为空")
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    url = _validated_public_url(url)
    # A few legacy in-process callers use a small principal object instead of
    # the authenticated DBUser. Keep their old document-only contract isolated
    # below; every real authenticated request still resolves an owner/course.
    legacy_principal = not str(getattr(current_user, "public_id", "") or "").strip()
    if legacy_principal and course_id:
        raise HTTPException(status_code=403, detail="兼容主体不能指定课程上下文")
    if legacy_principal:
        owner_public_id, target_course_id = "", ""
    else:
        owner_public_id, target_course_id = await run_db_op(
            lambda session: _resolve_upload_target(
                session,
                student_id=student_id,
                current_user=current_user,
                course_id=course_id,
            )
        )

    # 1. 过滤文件名
    safe_title = re.sub(r'[\\/*?:\"<>|]', "", title)[:40]
    ext = f".{file_type}"
    filename = f"[下载] {safe_title}{ext}"

    if ext not in SUPPORTED_EXTENSIONS:
        if ext == ".ppt":
            raise HTTPException(status_code=400, detail="不支持旧版 PPT 格式，仅支持 .pptx、.pdf 等现代格式。")
        allowed = ", ".join(SUPPORTED_EXTENSIONS.keys())
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}，支持 {allowed}")

    # 2. 流式下载网页文档。候选准入和直链导入共用同一重试、大小和错误边界。
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    raw, _final_url, _content_type = await _download_remote_bytes(url=url, headers=headers)
    file_size = len(raw)

    if legacy_principal:
        # Compatibility adapter for pre-canonical test/in-process callers. It
        # deliberately cannot create course sources or bypass authenticated
        # owner checks; production DBUser requests never enter this branch.
        try:
            text_content = parse_uploaded_file(
                type("buf", (), {"read": lambda _self: raw})(),
                filename,
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail="资料解析失败，原文件未登记为可用资料。") from exc
        evidence_chunks = chunk_document(text_content, source=filename)
        doc_id = hashlib.sha256(f"{student_id}:{filename}:{os.urandom(4).hex()}".encode()).hexdigest()[:16]
        file_category = SUPPORTED_EXTENSIONS[ext]
        is_multimodal = file_category in ("video", "presentation")
        db_doc = DBKnowledgeDocument(
            id=doc_id,
            student_id=student_id,
            filename=filename,
            file_type=ext.lstrip("."),
            file_size=file_size,
            title=safe_title,
            content=text_content,
            tags=list({tag for chunk in evidence_chunks for tag in chunk.tags}),
            chunk_count=len(evidence_chunks),
            is_multimodal=is_multimodal,
            multimodal_metadata={"url": url, "compatibility_mode": True},
        )

        def save_legacy_document(session):
            session.add(db_doc)
            session.commit()

        await run_db_op(save_legacy_document)
        doc_path = _write_upload_file(
            student_id=student_id,
            document_id=doc_id,
            ext=ext,
            raw=raw,
        )
        hybrid_rag.ingest_user_documents(evidence_chunks, owner_id=student_id)
        return {
            "status": "success",
            "id": doc_id,
            "filename": filename,
            "file_type": ext.lstrip("."),
            "file_category": file_category,
            "file_size": file_size,
            "chunk_count": len(evidence_chunks),
            "tags": list({tag for chunk in evidence_chunks for tag in chunk.tags}),
            "is_multimodal": is_multimodal,
            "multimodal_metadata": {"url": url, "compatibility_mode": True},
            "content_preview": text_content[:300],
            "course_id": "",
            "source_document_id": "",
            "source_ref_count": 0,
            "source_processing_status": "legacy_unmigrated",
            "source_processing_error_code": "",
            "original_file_path": str(doc_path),
        }

    doc_id = hashlib.sha256(f"{student_id}:{filename}:{os.urandom(4).hex()}".encode()).hexdigest()[:16]

    file_category = SUPPORTED_EXTENSIONS[ext]
    is_multimodal = file_category in ("video", "presentation")

    # 3. 提取文本内容并分块
    ocr_dir = _ocr_asset_dir(student_id=student_id, document_id=doc_id)
    try:
        parsed = parse_document(
            raw,
            filename,
            offline_ocr=ext == ".pdf",
            ocr_asset_dir=ocr_dir if ext == ".pdf" else None,
        )
    except DocumentParseError as exc:
        if ocr_dir.parent.exists():
            shutil.rmtree(ocr_dir.parent)
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": str(exc), "file_format": exc.file_format},
        ) from exc
    text_content = parsed.text
    evidence_chunks = chunk_document(text_content, source=filename)

    try:
        structure_llm = build_swarm_from_headers(request.headers)
        resource_structure = await _extract_resource_structure(
            parsed,
            llm=structure_llm.llm,
            owner_public_id=owner_public_id,
            course_id=target_course_id,
        )
    except Exception as exc:
        resource_structure = _pending_structure(
            parsed,
            model_meta=None,
            error_code="course_resource_structure_model_unavailable",
            message=exc,
        )

    # 4. PDF 视觉解析
    visual_evidence: list = []
    if ext == ".pdf" and _visual_page_externalization_allowed(parsed):
        try:
            visual_evidence = parse_pdf_visually(
                raw,
                filename,
                owner_public_id=current_user.public_id,
                model_call_context={"trace_id": f"m5-pdf-download-{uuid.uuid4().hex}"},
            )
            if visual_evidence:
                hybrid_rag.visual_index.index.upsert(tuple(visual_evidence))
        except Exception as e:
            print(f"  [download_web_file] PDF 视觉解析失败（非致命）: {e}")

    # 5. 增量图谱自生长
    graph_report = build_graph_after_upload(evidence_chunks, source=filename, previous_text="")

    extra_metadata = {"url": url}
    if ext in (".pptx", ".ppt"):
        try:
            from document_parser import parse_pptx_slides
            slides = parse_pptx_slides(raw)
            extra_metadata["slide_count"] = len(slides)
            extra_metadata["has_images"] = any(s["images"] for s in slides)
        except Exception:
            pass

    # 6. 保存至数据库记录
    db_doc = DBKnowledgeDocument(
        id=doc_id,
        student_id=student_id,
        filename=filename,
        file_type=ext.lstrip("."),
        file_size=file_size,
        title=safe_title,
        content=text_content,
        tags=list({tag for chunk in evidence_chunks for tag in chunk.tags}),
        chunk_count=len(evidence_chunks),
        is_multimodal=is_multimodal,
        multimodal_metadata=extra_metadata,
    )
    
    def save_doc(session):
        session.add(db_doc)
        session.flush()
        source, refs = _persist_personal_canonical_source(
            session,
            document=db_doc,
            parsed=parsed,
            owner_public_id=owner_public_id,
            uploader_public_id=current_user.public_id,
            course_id=target_course_id,
            structure=resource_structure,
            source_path=doc_file_path,
        )
        source.source_url = url
        session.commit()
        return (
            source.id,
            [ref.id for ref in refs],
            source.processing_status,
            source.processing_error_code,
        )
        
    # 7. 原文件先原子落盘；数据库失败时清理，避免 ready 行缺失原文件。
    doc_file_path = _write_upload_file(
        student_id=student_id, document_id=doc_id, ext=ext, raw=raw
    )
    try:
        source_document_id, source_ref_ids, source_status, source_error = await run_db_op(save_doc)
    except Exception:
        if doc_file_path.exists():
            doc_file_path.unlink()
        if ocr_dir.parent.exists():
            shutil.rmtree(ocr_dir.parent)
        raise

    # 8. 索引可重建；失败不回滚已验证的来源正文，但必须显式返回延期警告。
    indexing_warnings = _index_canonical_chunks(
        evidence_chunks,
        source_document_id=source_document_id,
        source_ref_ids=source_ref_ids,
        source_status=source_status,
        owner_id=student_id,
    )

    try:
        from learning_strategy import invalidate_graph_cache
        invalidate_graph_cache()
    except Exception:
        pass

    # 调度异步文档导读生成（NotebookLM 风格）
    if text_content.strip():
        background_tasks.add_task(
            _generate_doc_guide_for_document,
            doc_id=doc_id,
            student_id=student_id,
            owner_public_id=current_user.public_id,
            text_content=text_content[:12000],
        )

    return {
        "status": "success" if source_status == "ready" else "partial",
        "id": doc_id,
        "filename": filename,
        "file_type": ext.lstrip("."),
        "file_category": file_category,
        "file_size": file_size,
        "chunk_count": len(evidence_chunks),
        "tags": list({tag for chunk in evidence_chunks for tag in chunk.tags}),
        "is_multimodal": is_multimodal,
        "multimodal_metadata": extra_metadata,
        "content_preview": text_content[:300],
        "course_id": target_course_id,
        "source_document_id": source_document_id,
        "source_ref_count": len(source_ref_ids),
        "source_parser_version": parsed.parser_version,
        "source_sha256": parsed.source_sha256,
        "processed_sha256": parsed.processed_sha256,
        "source_processing_status": source_status,
        "source_processing_error_code": source_error,
        "source_parser_metadata": {**dict(parsed.metadata or {}), "resource_structure": resource_structure},
        "source_parse_warnings": list(parsed.warnings),
        "indexing_warnings": indexing_warnings,
        "knowledge_extraction": resource_structure,
        "visual_pages_parsed": len(visual_evidence),
        "ocr": (parsed.metadata or {}).get("ocr", {}),
        "graph_triplets_extracted": graph_report.raw_triplets if graph_report else 0,
        "graph_candidate_relations": graph_report.candidate_edges if graph_report else 0,
        "graph_edges_written": graph_report.written_edges if graph_report else 0,
    }


@router.get("/sources/{source_document_id}")
async def get_canonical_course_source(
    source_document_id: str,
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    return await run_db_op(
        lambda session: build_canonical_course_source_detail(session, current_user, source_document_id)
    )


@router.get("/{doc_id}")
async def get_document(
    doc_id: str,
    student_id: str = "default",
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    """获取单个知识库文档的完整详情（含完整文本内容）。"""
    student_id = enforce_student_access(student_id, current_user)
    def fetch_doc(session):
        result = LegacyReadRepository(session).knowledge_document_context(doc_id, student_id)
        observe_legacy_shadow_read(
            session, chain_id="knowledge-source-note", legacy_result=result,
            canonical_loader=lambda: KnowledgeSourceNoteCanonicalReader(session).knowledge_document_context(doc_id, student_id),
            legacy_projector=project_model_tree,
            actor_public_id=current_user.public_id,
        )
        if not result:
            return None
        if result[0] != "legacy":
            return result, None, []
        source = session.query(DBSourceDocument).filter_by(legacy_document_id=doc_id).first()
        refs = (
            session.query(DBSourceRef)
            .filter_by(source_document_id=source.id)
            .order_by(DBSourceRef.location_index, DBSourceRef.id)
            .all()
            if source else []
        )
        return result, source, refs
        
    fetched = await run_db_op(fetch_doc)
    if not fetched:
        raise HTTPException(status_code=404, detail="文档未找到")
    result, personal_source, personal_refs = fetched
    scope, doc, *context = result
    if scope == "course":
        course, source, source_ref, chapter = context
        return {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "title": doc.title,
            "content": doc.content or "无文本内容",
            "tags": doc.tags or [],
            "chunk_count": doc.chunk_count,
            "is_multimodal": False,
            "multimodal_metadata": {},
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
            "scope": "course",
            "deletable": False,
            "course_id": course.id,
            "course_title": course.title,
            "course_version": course.version,
            "course_description": course.description,
            "course_domain_pack": course.domain_pack,
            "course_origin": course.content_origin,
            "course_license": course.license_text,
            "chapter_order": doc.chapter_order,
            "content_hash": doc.content_hash,
            "source_path": doc.source_path,
            **_canonical_course_provenance(course, doc, source, source_ref, chapter),
        }

    return {
        "id": doc.id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "title": doc.title,
        "content": doc.content or "无文本内容",
        "tags": doc.tags or [],
        "chunk_count": doc.chunk_count,
        "is_multimodal": doc.is_multimodal,
        "multimodal_metadata": doc.multimodal_metadata or {},
        "created_at": doc.created_at.isoformat() if doc.created_at else "",
        "scope": "personal" if doc.student_id == student_id else "legacy_public",
        "deletable": doc.student_id == student_id,
        "owner_id": doc.student_id,
        **_personal_source_provenance(personal_source, personal_refs),
    }


def _authorized_personal_ocr_source(session, *, doc_id: str, student_id: str):
    document = session.query(DBKnowledgeDocument).filter_by(id=doc_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="文档未找到")
    if document.student_id != student_id:
        raise HTTPException(status_code=403, detail="无权读取该文档 OCR 证据")
    source = session.query(DBSourceDocument).filter_by(legacy_document_id=doc_id).first()
    if source is None:
        raise HTTPException(status_code=404, detail="该文档尚无 canonical OCR 来源")
    return source


def _public_ocr_report(report: Any, *, doc_id: str, student_id: str) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {
            "schema_version": "edumatrix.ocr-document.v1",
            "status": "not_available",
            "page_count": 0,
            "region_count": 0,
            "sensitive_region_count": 0,
            "pages": [],
        }
    result = dict(report)
    pages: list[dict[str, Any]] = []
    for raw_page in report.get("pages", []):
        if not isinstance(raw_page, dict):
            continue
        page = dict(raw_page)
        page_number = int(page.get("page_number") or 0)
        page["asset_url"] = (
            f"/api/knowledge/{doc_id}/ocr/pages/{page_number}?student_id={student_id}"
        )
        pages.append(page)
    result["pages"] = pages
    result["privacy_boundary"] = {
        "raw_page_api_available": False,
        "raw_sensitive_text_persisted": False,
        "served_assets": "redacted_only",
    }
    return result


@router.get("/{doc_id}/ocr")
async def get_document_ocr(
    doc_id: str,
    student_id: str = "default",
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    student_id = enforce_student_access(student_id, current_user)

    def fetch(session):
        source = _authorized_personal_ocr_source(
            session, doc_id=doc_id, student_id=student_id
        )
        return _public_ocr_report(
            (source.parser_metadata or {}).get("ocr"),
            doc_id=doc_id,
            student_id=student_id,
        )

    return await run_db_op(fetch)


@router.get("/{doc_id}/ocr/externalization-check")
async def get_document_ocr_externalization_check(
    doc_id: str,
    student_id: str = "default",
    current_user=Depends(get_current_user),
) -> dict[str, Any]:
    student_id = enforce_student_access(student_id, current_user)

    def fetch(session):
        source = _authorized_personal_ocr_source(
            session, doc_id=doc_id, student_id=student_id
        )
        report = (source.parser_metadata or {}).get("ocr") or {}
        pages = report.get("pages") if isinstance(report, dict) else []
        redacted_assets_complete = bool(pages) and all(
            isinstance(page, dict)
            and page.get("asset_name")
            and page.get("redacted_image_sha256")
            for page in pages
        )
        return {
            "schema_version": "edumatrix.ocr-externalization-check.v1",
            "document_id": doc_id,
            "ocr_status": report.get("status", "not_available"),
            "raw_page_allowed": False,
            "redacted_page_allowed": redacted_assets_complete,
            "sensitive_region_count": int(report.get("sensitive_region_count") or 0),
            "reason": (
                "redacted_assets_verified"
                if redacted_assets_complete
                else "no_verified_redacted_asset"
            ),
        }

    return await run_db_op(fetch)


@router.get("/{doc_id}/ocr/pages/{page_number}")
async def get_document_ocr_page(
    doc_id: str,
    page_number: int,
    student_id: str = "default",
    current_user=Depends(get_current_user),
):
    student_id = enforce_student_access(student_id, current_user)

    def fetch(session):
        source = _authorized_personal_ocr_source(
            session, doc_id=doc_id, student_id=student_id
        )
        report = (source.parser_metadata or {}).get("ocr") or {}
        return next(
            (
                page
                for page in report.get("pages", [])
                if int(page.get("page_number") or 0) == page_number
            ),
            None,
        )

    page = await run_db_op(fetch)
    if page is None:
        raise HTTPException(status_code=404, detail="OCR 脱敏页不存在")
    asset_name = Path(str(page.get("asset_name") or "")).name
    expected_dir = _ocr_asset_dir(student_id=student_id, document_id=doc_id).resolve()
    asset_path = (expected_dir / asset_name).resolve()
    if asset_path.parent != expected_dir or not asset_path.is_file():
        raise HTTPException(status_code=409, detail="OCR 脱敏页资产缺失")
    if hashlib.sha256(asset_path.read_bytes()).hexdigest() != page.get("redacted_image_sha256"):
        raise HTTPException(status_code=409, detail="OCR 脱敏页哈希校验失败")
    return FileResponse(
        asset_path,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    student_id: str = "default",
    current_user=Depends(get_current_user),
) -> dict[str, str]:
    student_id = enforce_student_access(student_id, current_user)
    def do_delete(session):
        result = LegacyReadRepository(session).delete_knowledge_document(doc_id, student_id)
        if isinstance(result, tuple):
            poststate = {
                "document_exists": session.query(DBKnowledgeDocument.id).filter_by(id=doc_id).first() is not None,
                "source_exists": session.query(DBSourceDocument.id).filter_by(legacy_document_id=doc_id).first() is not None,
            }
            observe_legacy_shadow_read(
                session, chain_id="knowledge-source-note", legacy_result=poststate,
                canonical_loader=lambda: KnowledgeSourceNoteCanonicalReader(session).deletion_poststate(doc_id),
                actor_public_id=current_user.public_id,
                mode="canonical_write_postcheck",
            )
        return result

    res = await run_db_op(do_delete)
    if res in {"readonly_course", "readonly_public"}:
        raise HTTPException(status_code=403, detail="公共课程和公共资料为只读内容，学生不能删除")
    if not res:
        raise HTTPException(status_code=404, detail="文档未找到")

    filename, file_type = res
    ext = "." + file_type
    doc_file = UPLOAD_DIR / student_id / f"{doc_id}{ext}"
    if doc_file.exists():
        doc_file.unlink()
    asset_root = UPLOAD_DIR / student_id / doc_id
    if asset_root.exists():
        shutil.rmtree(asset_root)

    hybrid_rag.remove_user_documents(filename, owner_id=student_id)

    try:
        from learning_strategy import invalidate_graph_cache
        invalidate_graph_cache()
    except Exception:
        pass

    return {"status": "deleted", "id": doc_id}
