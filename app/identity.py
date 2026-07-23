"""M1 统一身份与稳定标识规则。

用户可读的 username/student_id 继续作为兼容字段；权限和内部关联使用
服务端生成的 public_id，前端不得自行构造权威身份标识。
"""

from __future__ import annotations

import uuid


ROLE_ADMIN = "admin"
ROLE_TEACHER = "teacher"
ROLE_ASSISTANT = "assistant"
ROLE_STUDENT = "student"
ROLE_VISITOR = "visitor"

VALID_ROLES = frozenset(
    {ROLE_ADMIN, ROLE_TEACHER, ROLE_ASSISTANT, ROLE_STUDENT, ROLE_VISITOR}
)


def new_public_id(kind: str) -> str:
    """Generate an opaque, server-owned ID for a domain object."""
    normalized = "".join(ch for ch in str(kind).lower() if ch.isalnum() or ch == "-")
    if not normalized:
        raise ValueError("ID kind must not be empty")
    return f"{normalized}-{uuid.uuid4().hex}"


def normalize_role(role: str | None) -> str:
    value = str(role or ROLE_STUDENT).strip().lower()
    if value not in VALID_ROLES:
        raise ValueError(f"unsupported role: {role}")
    return value

