"""Web discovery candidate boundary for F7.

Candidates remain owner-scoped records and never become canonical course sources
through this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from io import BytesIO
from typing import Any
from urllib.parse import unquote, urlparse

from fastapi import HTTPException

from app.database import DBSourceRef, DBWebSourceCandidate, DBUser
from app.m2_contracts import StrictModel
from app.m5_legacy_calls import audited_legacy_text_call, model_identity
from config import CONFIG
from llm_client import parse_json_object
from web_search_api import _perform_web_search


ALLOWED_LICENSES = {"personal_use_allowed", "open_permissive"}
EDITABLE_TRUST_LEVELS = {"unverified", "source_declared"}
_CONTENT_TYPE_FORMATS = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "text/markdown": "md",
    "text/plain": "txt",
    "application/x-ipynb+json": "ipynb",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/x-msvideo": "avi",
    "video/x-matroska": "mkv",
    "video/x-flv": "flv",
}

_FORMAT_LABELS = {
    "html": "HTML 网页",
    "pdf": "PDF",
    "ppt": "旧版 PPT",
    "pptx": "PPTX",
    "doc": "旧版 DOC",
    "docx": "DOCX",
    "md": "Markdown",
    "txt": "纯文本",
    "ipynb": "Jupyter Notebook",
    "mp4": "MP4 视频",
    "avi": "AVI 视频",
    "mov": "MOV 视频",
    "mkv": "MKV 视频",
    "webm": "WebM 视频",
    "flv": "FLV 视频",
    "unknown": "待下载确认",
}


class CandidateCreate(StrictModel):
    query: str
    title: str
    url: str
    snippet: str = ""


class CandidateAdmission(StrictModel):
    course_id: str
    author_or_organization: str = ""
    license_status: str
    license_text: str = ""
    usage_hint: str
    trust_level: str = "source_declared"


def _profile_query_model(llm: Any) -> dict[str, Any]:
    """Require the configured production model for profile-conditioned query text."""
    provider, model = model_identity(llm)
    thinking_mode = str(getattr(llm, "thinking_mode", CONFIG.llm_thinking_mode or "max") or "").lower()
    reasoning_effort = str(getattr(llm, "reasoning_effort", CONFIG.llm_reasoning_effort or "max") or "").lower()
    fallback_enabled = os.getenv("EDUMATRIX_ALLOW_LLM_FALLBACK", "0") == "1"
    is_wrapper = llm.__class__.__name__ == "FallbackAsyncLLMWrapper" or hasattr(llm, "fallback")
    if (
        model != "deepseek-v4-flash"
        or provider not in {"openai", "openai-compatible", "deepseek"}
        or thinking_mode not in {"enabled", "max"}
        or reasoning_effort != "max"
        or fallback_enabled
        or is_wrapper
    ):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "profile_query_model_policy_blocked",
                "message": "画像驱动搜索需要 deepseek-v4-flash、thinking enabled、reasoning_effort=max 且禁止 fallback。",
            },
        )
    return {
        "provider": provider,
        "model": model,
        "thinking": "enabled",
        "reasoning_effort": "max",
        "allow_fallback": False,
    }


def _query_plan_validator(raw: str) -> dict[str, Any]:
    value = parse_json_object(raw)
    query_text = " ".join(str(value.get("query") or "").split())
    focus_terms = value.get("focus_terms") or value.get("focusTerms") or []
    if not query_text or len(query_text) > 500 or not isinstance(focus_terms, list):
        raise ValueError("画像联网 query plan 缺少有效 query/focus_terms")
    normalized_terms = [" ".join(str(item).split())[:80] for item in focus_terms if str(item).strip()]
    if not normalized_terms:
        normalized_terms = [query_text[:120]]
    return {
        "query": query_text,
        "focus_terms": normalized_terms[:12],
        "rationale": " ".join(str(value.get("rationale") or value.get("reason") or "").split())[:500],
    }


async def _generate_profile_query(
    *,
    user_query: str,
    course_context: dict[str, Any],
    profile_context: dict[str, Any],
    llm: Any,
    owner_public_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model_meta = _profile_query_model(llm)
    system_prompt = (
        "你是 EduMatrix 的画像驱动联网检索 Query Planner。只根据给定的课程快照、学习画像快照和用户检索意图，"
        "生成适合公开互联网搜索的一个 query 和若干关注词；不要回答课程问题，不要编造画像事实，不要加入未提供的个人信息。"
        "只输出一个 JSON 对象，字段必须是 query（字符串）、focus_terms（字符串数组）、rationale（简短中文字符串）。"
    )
    user_prompt = json.dumps(
        {
            "user_query": user_query,
            "course": course_context,
            "profile": profile_context,
        },
        ensure_ascii=False,
    )
    raw = await audited_legacy_text_call(
        llm,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        role="画像联网检索规划 Agent",
        operation="profile_conditioned_web_query",
        capability="web_search_query_planning",
        owner_public_id=owner_public_id,
        course_id=str(course_context.get("course_id") or "") or None,
        input_summary={
            "course_id": course_context.get("course_id"),
            "profile_snapshot_id": profile_context.get("profile_snapshot_id"),
            "user_query_chars": len(user_query),
            "profile_fields": sorted(key for key, value in profile_context.items() if value and key not in {"profile_snapshot_id", "profile_version"}),
        },
        response_validator=_query_plan_validator,
    )
    plan = _query_plan_validator(raw)
    return plan, model_meta


def _rank_discovery_results(
    raw_results: list[dict[str, Any]],
    *,
    query: str,
    focus_terms: list[str],
) -> tuple[list[dict[str, Any]], int]:
    terms = [term.casefold() for term in [query, *focus_terms] if str(term).strip()]
    ranked: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    duplicate_count = 0
    for result in raw_results:
        url = _public_http_url(result.get("url"))
        if not url:
            continue
        canonical_url = url.rstrip("/").casefold()
        if canonical_url in seen_urls:
            duplicate_count += 1
            continue
        seen_urls.add(canonical_url)
        title = str(result.get("title") or "").strip()
        snippet = str(result.get("snippet") or "").strip()
        title_text = title.casefold()
        body_text = f"{title} {snippet}".casefold()
        matched_terms = [term for term in terms if term and term in body_text]
        title_matches = [term for term in terms if term and term in title_text]
        score = round(min(1.0, (len(matched_terms) * 0.12) + (len(title_matches) * 0.18)), 3)
        ranked.append({
            **result,
            "url": url,
            "relevanceScore": score,
            "matchedFocusTerms": matched_terms[:8],
            "recommendationReason": (
                f"命中画像/课程关注词：{'、'.join(matched_terms[:3])}。"
                if matched_terms
                else "保留为公开搜索候选，仍需用户核对来源和许可。"
            ),
        })
    ranked.sort(key=lambda item: (-float(item.get("relevanceScore") or 0), str(item.get("title") or ""), item["url"]))
    return ranked, duplicate_count


async def search_web_materials(
    query: str,
    max_results: int,
    *,
    course_context: dict[str, Any] | None = None,
    profile_context: dict[str, Any] | None = None,
    llm: Any | None = None,
    owner_public_id: str = "",
) -> dict[str, Any]:
    normalized_query = " ".join(str(query or "").split())
    if len(normalized_query) < 2:
        raise HTTPException(status_code=422, detail="请输入至少两个字的教材或课程主题")
    course_context = dict(course_context or {})
    profile_context = dict(profile_context or {})
    profile_available = bool(profile_context.get("profile_snapshot_id"))
    query_plan: dict[str, Any] = {
        "query": normalized_query,
        "focus_terms": [],
        "rationale": "未找到当前画像快照；保留用户搜索词并明确标记画像缺失。",
    }
    model_meta: dict[str, Any] | None = None
    if profile_available:
        if llm is None:
            raise HTTPException(status_code=503, detail={"code": "profile_query_model_unavailable", "message": "画像快照已提供，但画像联网 query 模型当前不可用，请重试。"})
        try:
            query_plan, model_meta = await _generate_profile_query(
                user_query=normalized_query,
                course_context=course_context,
                profile_context=profile_context,
                llm=llm,
                owner_public_id=owner_public_id,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "profile_query_failed",
                    "message": "画像联网 query 生成没有完成，原搜索条件已保留，请重试。",
                },
            ) from exc
    search_query = query_plan["query"]
    try:
        raw_results = await _perform_web_search(search_query, max_results=max_results * 2)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "web_discovery_unavailable",
                "message": "联网发现暂不可用，搜索词已保留，请稍后重试。",
                "query": normalized_query,
                "generatedQuery": search_query,
            },
        ) from exc
    search_status = getattr(raw_results, "status", "ready")
    ranked_results, duplicate_count = _rank_discovery_results(
        list(raw_results),
        query=search_query,
        focus_terms=query_plan.get("focus_terms") or [],
    )
    items = []
    seen_urls: set[str] = set()
    for result in ranked_results[:max_results]:
        url = _public_http_url(result.get("url"))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        domain = urlparse(url).hostname or ""
        result_title = str(result.get("title") or domain or "未命名资料").strip()
        result_snippet = str(result.get("snippet") or "").strip()[:1000]
        file_format, format_detection = _infer_format_details(
            url,
            title=result_title,
            snippet=result_snippet,
        )
        items.append({
            "title": result_title,
            "url": url,
            "snippet": result_snippet,
            "sourceDomain": domain,
            "authorOrOrganization": domain,
            "fileFormat": file_format,
            "formatLabel": _FORMAT_LABELS.get(file_format, file_format.upper()),
            "formatConfidence": format_detection["confidence"],
            "formatDetection": format_detection["method"],
            "licenseStatus": "unknown",
            "licenseText": "",
            "usageHint": "请在保存候选后核对原站许可和允许用途。",
            "parsingImpact": _parsing_impact(file_format, format_detection=format_detection),
            "trustLevel": "unverified",
            "reviewStatus": "not_saved",
            "importedVersion": None,
            "authoritative": False,
            "relevanceScore": result.get("relevanceScore", 0),
            "matchedFocusTerms": result.get("matchedFocusTerms", []),
            "recommendationReason": result.get("recommendationReason", ""),
        })
    if search_status not in {"ready", "no_results", "provider_failed"}:
        search_status = "ready" if items else "no_results"
    if search_status == "ready" and not items:
        search_status = "no_results"
    return {
        "schemaVersion": "edumatrix.web-source-discovery.v1",
        "status": search_status,
        "query": normalized_query,
        "generatedQuery": search_query,
        "queryPlan": {
            **query_plan,
            "model": model_meta,
            "source": "profile_snapshot" if profile_available else "user_query_profile_missing",
        },
        "profileBasis": {
            "status": "available" if profile_available else "missing",
            "profileSnapshotId": profile_context.get("profile_snapshot_id"),
            "profileVersion": profile_context.get("profile_version"),
            "courseId": course_context.get("course_id"),
            "courseTitle": course_context.get("title"),
            "courseGoals": profile_context.get("course_goals") or course_context.get("course_goals") or [],
            "learningGoals": profile_context.get("learning_goals") or [],
            "weakDirections": profile_context.get("weak_directions") or [],
            "preferences": profile_context.get("preferences") or [],
            "timeBudget": profile_context.get("time_budget") or "",
        },
        "ranking": {"deduplicatedCount": duplicate_count, "scoredCount": len(ranked_results)},
        "items": items,
        "filteredResultCount": max(len(raw_results) - len(items), 0),
        "message": (
            "联网搜索提供方暂时不可用，搜索词和画像条件已保留，请稍后重试。"
            if search_status == "provider_failed"
            else "未找到带真实原站地址的结果。"
            if search_status == "no_results"
            else ""
        ),
        "authorityBoundary": "搜索结果只进入候选区；无真实原站地址、许可未确认或未经准入的资料不会进入课程图谱、检索或资源生成。推荐本身不会改变 mastery/path。",
    }


def create_candidate(session: Any, current_user: DBUser, payload: CandidateCreate) -> dict[str, Any]:
    url = _public_http_url(payload.url)
    if not url:
        raise HTTPException(status_code=422, detail="候选资料必须提供真实的 HTTP(S) 原站地址")
    url_sha256 = hashlib.sha256(url.encode("utf-8")).hexdigest()
    candidate = session.query(DBWebSourceCandidate).filter_by(
        owner_public_id=current_user.public_id,
        url_sha256=url_sha256,
    ).first()
    created = candidate is None
    if candidate is None:
        file_format, format_detection = _infer_format_details(
            url,
            title=payload.title,
            snippet=payload.snippet,
        )
        candidate = DBWebSourceCandidate(
            owner_public_id=current_user.public_id,
            query=" ".join(payload.query.split())[:500],
            title=payload.title.strip()[:512] or (urlparse(url).hostname or "未命名资料"),
            url=url,
            url_sha256=url_sha256,
            source_domain=urlparse(url).hostname or "",
            author_or_organization=urlparse(url).hostname or "",
            file_format=file_format,
            snippet=payload.snippet.strip()[:4000],
            parsing_impact=_parsing_impact(file_format, format_detection=format_detection),
        )
        session.add(candidate)
        session.flush()
    session.commit()
    return {"created": created, "candidate": serialize_candidate(candidate)}


def list_candidates(session: Any, current_user: DBUser, review_status: str | None = None) -> dict[str, Any]:
    query = session.query(DBWebSourceCandidate).filter_by(owner_public_id=current_user.public_id)
    if review_status:
        query = query.filter(DBWebSourceCandidate.review_status == review_status)
    items = query.order_by(DBWebSourceCandidate.updated_at.desc(), DBWebSourceCandidate.id).all()
    return {
        "schemaVersion": "edumatrix.web-source-candidates.v1",
        "items": [serialize_candidate(item) for item in items],
    }


def prepare_candidate_admission(
    session: Any,
    current_user: DBUser,
    candidate_id: str,
    payload: CandidateAdmission,
) -> DBWebSourceCandidate:
    candidate = _owned_candidate(session, current_user, candidate_id)
    if candidate.review_status == "withdrawn":
        raise HTTPException(status_code=409, detail="已撤回候选不能重新准入，请重新保存来源")
    if candidate.review_status == "rejected":
        raise HTTPException(status_code=409, detail="已拒绝候选不能直接准入")
    if candidate.review_status == "imported":
        return candidate
    if payload.trust_level not in EDITABLE_TRUST_LEVELS:
        raise HTTPException(status_code=422, detail="候选资料不能由当前用户自行标记为已验证")
    if not payload.course_id.strip():
        raise HTTPException(status_code=422, detail="请选择要导入的学习课程")

    candidate.author_or_organization = payload.author_or_organization.strip()[:256]
    candidate.license_status = payload.license_status
    candidate.license_text = payload.license_text.strip()[:4000]
    candidate.usage_hint = payload.usage_hint.strip()[:4000]
    candidate.trust_level = payload.trust_level
    if candidate.license_status not in ALLOWED_LICENSES or not candidate.usage_hint:
        candidate.review_status = "license_required"
        _update_pipeline(
            candidate,
            admission={
                "status": "blocked",
                "code": "license_required",
                "message": "许可或允许用途尚未确认",
            },
        )
        session.commit()
        raise HTTPException(status_code=409, detail="许可或允许用途尚未确认，候选资料不能准入")

    candidate.review_status = "pending_review"
    _update_pipeline(
        candidate,
        download={"status": "pending", "code": "", "message": "等待从原站下载"},
        parse={"status": "pending", "code": "", "message": "等待下载完成"},
        citation={"status": "blocked", "code": "", "message": "等待解析完成"},
        admission={"status": "pending", "code": "", "message": "等待解析和来源核验"},
    )
    session.commit()
    return candidate


def complete_candidate_import(
    session: Any,
    current_user: DBUser,
    candidate_id: str,
    *,
    course_id: str,
    document_id: str,
    source_document_id: str,
) -> dict[str, Any]:
    candidate = _owned_candidate(session, current_user, candidate_id)
    created = candidate.review_status != "imported"
    candidate.review_status = "imported"
    candidate.imported_version = candidate.imported_version or f"{source_document_id}-v1"
    _update_pipeline(
        candidate,
        download={"status": "completed", "code": "", "message": "原站文件已下载"},
        parse={"status": "completed", "code": "", "message": "文件已完成解析"},
        citation={
            "status": "ready",
            "code": "",
            "message": "当前来源版本可引用",
            "source_document_id": source_document_id,
        },
        admission={
            "status": "admitted",
            "code": "",
            "message": "已加入目标个人课程",
            "course_id": course_id,
        },
    )
    candidate.parsing_impact = {
        **dict(candidate.parsing_impact or {}),
        "import": {
            "course_id": course_id,
            "document_id": document_id,
            "source_document_id": source_document_id,
            "status": "ready",
            "citation_status": "ready",
            "admission_status": "admitted",
        },
    }
    session.commit()
    return {"created": created, "candidate": serialize_candidate(candidate)}


def reject_candidate(session: Any, current_user: DBUser, candidate_id: str) -> dict[str, Any]:
    candidate = _owned_candidate(session, current_user, candidate_id)
    if candidate.review_status == "imported":
        raise HTTPException(status_code=409, detail="已准入候选请使用撤回操作")
    candidate.review_status = "rejected"
    _update_pipeline(
        candidate,
        admission={"status": "rejected", "code": "candidate_rejected", "message": "候选已被拒绝"},
    )
    session.commit()
    return {"candidate": serialize_candidate(candidate)}


def withdraw_candidate(session: Any, current_user: DBUser, candidate_id: str) -> dict[str, Any]:
    candidate = _owned_candidate(session, current_user, candidate_id)
    if candidate.review_status != "imported":
        raise HTTPException(status_code=409, detail="只有已准入候选可以撤回")
    candidate.review_status = "withdrawn"
    _update_pipeline(
        candidate,
        admission={"status": "withdrawn", "code": "candidate_withdrawn", "message": "候选准入记录已撤回"},
        citation={"status": "revoked", "code": "candidate_withdrawn", "message": "撤回后不再作为当前可引用候选"},
    )
    session.commit()
    return {"candidate": serialize_candidate(candidate)}


def serialize_candidate(candidate: DBWebSourceCandidate) -> dict[str, Any]:
    blockers = []
    if candidate.license_status not in ALLOWED_LICENSES:
        blockers.append("许可未确认")
    if not candidate.usage_hint.strip():
        blockers.append("用途说明缺失")
    impact = dict(candidate.parsing_impact or {})
    pipeline = _pipeline_for(candidate, impact)
    format_detection = dict(impact.get("formatDetection") or {})
    return {
        "id": candidate.id,
        "query": candidate.query,
        "title": candidate.title,
        "url": candidate.url,
        "sourceDomain": candidate.source_domain,
        "authorOrOrganization": candidate.author_or_organization or "原站未提供",
        "fileFormat": candidate.file_format,
        "formatLabel": _FORMAT_LABELS.get(candidate.file_format, str(candidate.file_format or "unknown").upper()),
        "formatConfidence": format_detection.get("confidence", "unknown"),
        "formatDetection": format_detection.get("method", "stored_candidate"),
        "snippet": candidate.snippet,
        "licenseStatus": candidate.license_status,
        "licenseText": candidate.license_text,
        "usageHint": candidate.usage_hint,
        "parsingImpact": impact,
        "processingPipeline": pipeline,
        "processingStatus": pipeline["overall_status"],
        "citationStatus": pipeline["citation"]["status"],
        "retryable": pipeline["retryable"],
        "failure": pipeline.get("failure"),
        "trustLevel": candidate.trust_level,
        "reviewStatus": candidate.review_status,
        "importedVersion": candidate.imported_version,
        "importResult": dict(impact.get("import") or {}),
        "canAdmit": candidate.review_status in {"pending_review", "license_required"} and not blockers,
        "blockers": blockers,
        "authorityScope": "personal_course_source" if candidate.review_status == "imported" else "candidate_only",
        "authoritative": False,
        "resourceGenerationEligible": candidate.review_status == "imported",
        "createdAt": candidate.created_at.isoformat() if candidate.created_at else "",
        "updatedAt": candidate.updated_at.isoformat() if candidate.updated_at else "",
    }


def canonical_source_ref_count(session: Any) -> int:
    return session.query(DBSourceRef).count()


def _owned_candidate(session: Any, current_user: DBUser, candidate_id: str) -> DBWebSourceCandidate:
    candidate = session.query(DBWebSourceCandidate).filter_by(
        id=candidate_id,
        owner_public_id=current_user.public_id,
    ).first()
    if candidate is None:
        raise HTTPException(status_code=404, detail="候选资料不存在")
    return candidate


def _public_http_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return ""
    return parsed.geturl()


def _infer_format(url: str) -> str:
    return _infer_format_details(url)[0]


def _infer_format_details(
    url: str,
    *,
    content_type: str = "",
    raw: bytes | None = None,
    title: str = "",
    snippet: str = "",
) -> tuple[str, dict[str, str]]:
    """Infer a candidate format without treating every unknown URL as HTML."""
    content = str(content_type or "").split(";", 1)[0].strip().lower()
    if content in _CONTENT_TYPE_FORMATS:
        return _CONTENT_TYPE_FORMATS[content], {"confidence": "declared", "method": "content_type"}
    if content.startswith("video/"):
        return "unknown", {"confidence": "low", "method": "unsupported_video_content_type"}

    if raw:
        if raw.startswith(b"%PDF-"):
            return "pdf", {"confidence": "signature", "method": "pdf_magic"}
        if raw.startswith(b"\x00\x01\x00\x00"):
            return "unknown", {"confidence": "low", "method": "binary_signature_requires_download"}
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                names = set(archive.namelist())
            if "word/document.xml" in names:
                return "docx", {"confidence": "signature", "method": "ooxml_word_package"}
            if "ppt/presentation.xml" in names:
                return "pptx", {"confidence": "signature", "method": "ooxml_presentation_package"}
        except (OSError, zipfile.BadZipFile):
            pass
        if b"ftyp" in raw[:64]:
            return "mp4", {"confidence": "signature", "method": "iso_media_ftyp"}

    path = unquote(urlparse(url).path).lower()
    extension_map = {
        ".pdf": "pdf",
        ".ppt": "ppt",
        ".pptx": "pptx",
        ".doc": "doc",
        ".docx": "docx",
        ".md": "md",
        ".markdown": "md",
        ".txt": "txt",
        ".ipynb": "ipynb",
        ".mp4": "mp4",
        ".avi": "avi",
        ".mov": "mov",
        ".mkv": "mkv",
        ".webm": "webm",
        ".flv": "flv",
        ".html": "html",
        ".htm": "html",
    }
    for suffix, file_format in extension_map.items():
        if path.endswith(suffix):
            return file_format, {"confidence": "high", "method": "url_extension"}

    explicit_hint = re.search(
        r"(?i)(?:^|[\s._-])(pdf|pptx?|docx?|mp4|avi|mov|mkv|webm|flv)(?:$|[\s._-])",
        f"{title} {snippet}",
    )
    if explicit_hint:
        hint = explicit_hint.group(1).lower()
        return hint, {"confidence": "medium", "method": "title_or_snippet_hint"}
    return "unknown", {"confidence": "unknown", "method": "awaiting_content_type_or_signature"}


def _parsing_impact(
    file_format: str,
    *,
    format_detection: dict[str, str] | None = None,
) -> dict[str, Any]:
    detection = dict(format_detection or {"confidence": "stored", "method": "candidate_record"})
    if file_format == "pdf":
        capabilities = {"text": True, "images": "best_effort", "tables": "best_effort", "formulas": "best_effort", "ocr": "best_effort"}
        summary = "可提取正文、页面图片和 OCR；复杂表格、公式与扫描页需要解析后复核。"
    elif file_format in {"ppt", "pptx", "doc", "docx"}:
        capabilities = {"text": True, "images": "best_effort", "tables": "best_effort", "formulas": "best_effort", "ocr": "best_effort"}
        summary = "可提取结构化文本、表格和内嵌图片；版式、复杂公式与扫描图片需要解析后复核。"
    elif file_format == "html":
        capabilities = {"text": "best_effort", "images": "metadata_and_authorized_ocr", "tables": "best_effort", "dynamic_content": "not_guaranteed"}
        summary = "可提取公开正文和图片地址/alt/位置；图片需通过公开访问与许可检查后再做 OCR，动态或受限内容不保证。"
    elif file_format == "ipynb":
        capabilities = {"text": True, "code": True, "outputs": "best_effort"}
        summary = "可提取说明、代码与已有输出，外部数据依赖需另行确认。"
    elif file_format in {"mp4", "avi", "mov", "mkv", "webm", "flv"}:
        capabilities = {"metadata": True, "transcript": "when_authorized", "subtitles": "when_available", "keyframes": "metadata_only"}
        summary = "先保留媒体元数据；公开字幕或获授权转写可进入引用，未取得字幕/转写时不伪装成完整正文。"
    elif file_format in {"md", "txt"}:
        capabilities = {"text": True, "images": "not_applicable"}
        summary = "可直接提取文本；图片或外部附件不因文件扩展名自动获得引用资格。"
    else:
        capabilities = {"text": "pending_download", "images": "pending_download", "media": "pending_download"}
        summary = "格式待下载后的 Content-Type 或文件签名确认，当前不会把未知资源归类为 HTML。"
    return {
        **capabilities,
        "formatDetection": detection,
        "pipeline": _new_pipeline(),
        "summary": summary,
    }


def _new_pipeline() -> dict[str, Any]:
    return {
        "download": {"status": "not_started", "code": "", "message": "尚未下载"},
        "parse": {"status": "not_started", "code": "", "message": "尚未解析"},
        "citation": {"status": "blocked", "code": "", "message": "等待解析和来源核验"},
        "admission": {"status": "candidate", "code": "", "message": "尚未准入"},
    }


def _pipeline_for(candidate: DBWebSourceCandidate, impact: dict[str, Any]) -> dict[str, Any]:
    pipeline = dict(impact.get("pipeline") or _new_pipeline())
    for key, default in _new_pipeline().items():
        current = pipeline.get(key)
        pipeline[key] = {**default, **(current if isinstance(current, dict) else {})}
    if candidate.review_status == "imported" and pipeline["admission"]["status"] == "candidate":
        pipeline["download"] = {**pipeline["download"], "status": "completed", "message": "原站文件已下载"}
        pipeline["parse"] = {**pipeline["parse"], "status": "completed", "message": "文件已完成解析"}
        pipeline["citation"] = {**pipeline["citation"], "status": "ready", "message": "当前来源版本可引用"}
        pipeline["admission"] = {**pipeline["admission"], "status": "admitted", "message": "已加入目标个人课程"}
    elif candidate.review_status == "rejected":
        pipeline["admission"] = {**pipeline["admission"], "status": "rejected", "message": "候选已被拒绝"}
    elif candidate.review_status == "withdrawn":
        pipeline["admission"] = {**pipeline["admission"], "status": "withdrawn", "message": "候选准入记录已撤回"}
        pipeline["citation"] = {**pipeline["citation"], "status": "revoked", "message": "撤回后不再作为当前可引用候选"}
    statuses = [pipeline[key]["status"] for key in ("download", "parse", "citation", "admission")]
    failure = next(
        (pipeline[key] for key in ("download", "parse", "citation", "admission") if str(pipeline[key].get("status", "")).endswith("failed")),
        None,
    )
    pipeline["overall_status"] = (
        "failed" if failure else "admitted" if pipeline["admission"]["status"] == "admitted" else "in_progress" if any(status in {"pending", "in_progress", "completed", "ready"} for status in statuses) else "candidate"
    )
    pipeline["retryable"] = bool(failure) or candidate.review_status in {"pending_review", "license_required"}
    pipeline["failure"] = failure
    return pipeline


def _update_pipeline(candidate: DBWebSourceCandidate, **stages: dict[str, Any]) -> None:
    impact = dict(candidate.parsing_impact or {})
    pipeline = _new_pipeline()
    existing = impact.get("pipeline")
    if isinstance(existing, dict):
        for key, value in existing.items():
            if key in pipeline and isinstance(value, dict):
                pipeline[key] = {**pipeline[key], **value}
    for key, value in stages.items():
        if key in pipeline:
            pipeline[key] = {**pipeline[key], **dict(value)}
    candidate.parsing_impact = {**impact, "pipeline": pipeline}


def mark_candidate_stage(
    session: Any,
    current_user: DBUser,
    candidate_id: str,
    *,
    stage: str,
    status: str,
    code: str = "",
    message: str = "",
    **metadata: Any,
) -> dict[str, Any]:
    """Persist one download/parse/citation stage without changing admission ownership."""
    if stage not in {"download", "parse", "citation", "admission"}:
        raise HTTPException(status_code=422, detail="未知的候选处理阶段")
    candidate = _owned_candidate(session, current_user, candidate_id)
    stage_payload = {"status": status, "code": code, "message": message, **metadata}
    _update_pipeline(candidate, **{stage: stage_payload})
    session.commit()
    return {"candidate": serialize_candidate(candidate)}
