from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.authorization import ObjectAccess, can_access_object
from app.auth import create_access_token, get_password_hash
from app.database import DBUser, SessionLocal
from app.identity import VALID_ROLES, normalize_role
from app.main import app
from app.role_landing import resolve_login_landing


ROOT = Path(__file__).parents[1]


def test_formal_role_policy_is_exactly_three_roles():
    assert VALID_ROLES == {"student", "teacher", "admin"}
    for legacy in ("assistant", "visitor", "demo-assistant", "demo-visitor"):
        if legacy in ("assistant", "visitor"):
            assert normalize_role(legacy) == legacy
        else:
            with pytest.raises(ValueError):
                normalize_role(legacy)


def test_legacy_roles_cannot_access_even_public_objects_or_teacher_landing():
    public = ObjectAccess("course", "public-course", visibility="public")
    for legacy in ("assistant", "visitor"):
        actor = SimpleNamespace(public_id=f"legacy-{legacy}", role=legacy)
        assert can_access_object(actor, public, action="read") is False
        assert resolve_login_landing(None, actor) is None


def test_formal_landing_paths_remain_available():
    assert resolve_login_landing(None, SimpleNamespace(role="teacher", public_id="t")) == "/teacher/overview"
    assert resolve_login_landing(None, SimpleNamespace(role="admin", public_id="a")) == "/admin/system"


def test_normal_startup_and_login_surfaces_have_no_legacy_demo_roles():
    main_source = (ROOT / "app/main.py").read_text(encoding="utf-8")
    login_source = (ROOT / "frontend/src/views/Login.vue").read_text(encoding="utf-8")
    router_source = (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")
    landing_source = (ROOT / "frontend/src/utils/roleLanding.js").read_text(encoding="utf-8")

    assert "demo-assistant" not in main_source
    assert "demo-visitor" not in main_source
    role_block = re.search(r"const roles = \[(.*?)\n\]", login_source, flags=re.DOTALL)
    assert role_block
    assert re.findall(r"value: '([^']+)'", role_block.group(1)) == ["student", "teacher", "admin"]
    assert "assistant" not in router_source
    assert "visitor" not in router_source
    assert "assistant" not in landing_source
    assert "visitor" not in landing_source


def test_legacy_credentials_and_tokens_are_rejected_at_auth_boundary():
    username = "pr09-legacy-visitor"
    with SessionLocal() as session:
        session.query(DBUser).filter_by(username=username).delete()
        user = DBUser(
            username=username,
            hashed_password=get_password_hash("legacy-password"),
            role="visitor",
            display_name="旧访客 fixture",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        public_id = user.public_id

    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                data={"username": username, "password": "legacy-password"},
            )
            assert login.status_code == 401

            token = create_access_token({"sub": public_id, "uid": public_id, "username": username, "role": "visitor"})
            me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert me.status_code == 401
    finally:
        with SessionLocal() as session:
            session.query(DBUser).filter_by(username=username).delete()
            session.commit()
