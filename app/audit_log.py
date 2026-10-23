"""Summary-only audit records for privileged backend operations."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.database import DBAuditLog
from app.identity import new_public_id


AUDIT_SCHEMA_VERSION = "edumatrix.audit.summary.v1"
MAX_SUMMARY_TEXT_LENGTH = 512

_PROHIBITED_KEYS = frozenset({
    "password", "passwordhash", "hashedpassword", "secret", "apikey",
    "token", "accesstoken", "refreshtoken", "authorization",
    "prompt", "systemprompt", "developerprompt", "chainofthought",
    "reasoning", "privatereasoning", "rawlog", "rawlogs", "trace",
    "traceback", "content", "rawcontent", "text", "rawtext",
    "originaltext", "sourcecontent", "userinput", "modelinput",
    "modeloutput", "request", "response", "payload", "message", "log", "logs",
})
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(r"\beyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{8,}\b"),
    re.compile(r"\bsk-[a-zA-Z0-9_-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
)


class AuditPayloadError(ValueError):
    """Raised before persistence when audit input is not a safe summary."""


def _normalized_key(value: Any) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _is_prohibited_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    return any(
        normalized == item or normalized.startswith(item) or normalized.endswith(item)
        for item in _PROHIBITED_KEYS
    )


def _safe_summary(value: Any, *, reject_sensitive: bool, path: str) -> Any:
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            if _is_prohibited_key(key):
                if reject_sensitive:
                    raise AuditPayloadError(f"audit summary contains prohibited field: {path}.{key}")
                continue
            cleaned[key] = _safe_summary(
                child,
                reject_sensitive=reject_sensitive,
                path=f"{path}.{key}",
            )
        return cleaned
    if isinstance(value, (list, tuple)):
        return [
            _safe_summary(item, reject_sensitive=reject_sensitive, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        if reject_sensitive:
            raise AuditPayloadError(f"audit summary contains a non-finite number: {path}")
        return None
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
            if reject_sensitive:
                raise AuditPayloadError(f"audit summary contains a secret-like value: {path}")
            return "[redacted]"
        if len(value) > MAX_SUMMARY_TEXT_LENGTH:
            if reject_sensitive:
                raise AuditPayloadError(f"audit summary text is too long: {path}")
            return "[omitted: non-summary text]"
        return value
    if reject_sensitive:
        raise AuditPayloadError(f"audit summary contains an unsupported value: {path}")
    return "[omitted: unsupported value]"


def record_backend_audit(
    session: Any,
    *,
    actor_public_id: str | None,
    action: str,
    object_type: str,
    object_id: str,
    outcome: str = "success",
    before_summary: Mapping[str, Any] | None = None,
    after_summary: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    trace_id: str | None = None,
    reject_sensitive: bool = True,
) -> DBAuditLog:
    """Add and flush one audit row without committing the caller's transaction."""
    metadata = {
        "schemaVersion": AUDIT_SCHEMA_VERSION,
        "beforeSummary": _safe_summary(
            before_summary or {}, reject_sensitive=reject_sensitive, path="beforeSummary",
        ),
        "afterSummary": _safe_summary(
            after_summary or {}, reject_sensitive=reject_sensitive, path="afterSummary",
        ),
    }
    safe_context = _safe_summary(
        context or {}, reject_sensitive=reject_sensitive, path="context",
    )
    if safe_context:
        metadata["context"] = safe_context

    row = DBAuditLog(
        actor_public_id=actor_public_id,
        action=str(action),
        object_type=str(object_type),
        object_id=str(object_id),
        trace_id=trace_id or new_public_id("trace"),
        outcome=str(outcome),
        metadata_json=metadata,
    )
    session.add(row)
    session.flush()
    return row


def audit_log_payload(row: DBAuditLog) -> dict[str, Any]:
    """Project only the approved fields from new audit rows; legacy details stay hidden."""
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    is_summary_record = metadata.get("schemaVersion") == AUDIT_SCHEMA_VERSION
    before = metadata.get("beforeSummary", {}) if is_summary_record else {}
    after = metadata.get("afterSummary", {}) if is_summary_record else {}
    return {
        "id": row.id,
        "actorPublicId": row.actor_public_id,
        "action": row.action,
        "objectType": row.object_type,
        "objectId": row.object_id,
        "outcome": row.outcome,
        "beforeSummary": _safe_summary(before, reject_sensitive=False, path="beforeSummary"),
        "afterSummary": _safe_summary(after, reject_sensitive=False, path="afterSummary"),
        "createdAt": row.created_at.isoformat() if isinstance(row.created_at, datetime) else None,
        "detailsAvailable": is_summary_record,
    }
