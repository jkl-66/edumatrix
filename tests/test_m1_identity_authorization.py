from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from jose import jwt

from app.authorization import (
    ObjectAccess,
    active_course_role,
    can_access_object,
    require_course_access,
)
from app.database import DBCourseMembership, DBUser, SessionLocal
from app.identity import VALID_ROLES, new_public_id
from app.main import app
from config import CONFIG
from tests.api_test_helpers import TEST_PASSWORD, auth_headers


def test_server_generated_user_id_is_token_subject_and_stable():
    username = new_public_id("m1-user")
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        login = client.post(
            "/api/auth/login",
            data={"username": username, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200
        body = login.json()
        assert body["user_id"].startswith("usr-")
        assert body["user_id"] != username

        claims = jwt.decode(
            body["access_token"], CONFIG.auth_secret_key, algorithms=[CONFIG.auth_algorithm]
        )
        assert claims["sub"] == body["user_id"]
        assert claims["uid"] == body["user_id"]
        assert claims["username"] == username

        me = client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["user_id"] == body["user_id"]
        assert me.json()["username"] == username


def test_request_cannot_escalate_registration_role_or_choose_authority_id():
    username = new_public_id("m1-role")
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={
                "username": username,
                "password": TEST_PASSWORD,
                "role": "admin",
                "user_id": "usr-attacker-controlled",
            },
        )
        assert response.status_code == 200
        assert response.json()["role"] == "student"
        assert response.json()["user_id"] != "usr-attacker-controlled"


def test_role_vocabulary_covers_m0_roles():
    assert {"admin", "teacher", "assistant", "student", "visitor"} <= VALID_ROLES


def test_object_policy_denies_unrelated_private_owner():
    owner = SimpleNamespace(public_id="usr-owner", role="student")
    stranger = SimpleNamespace(public_id="usr-stranger", role="student")
    obj = ObjectAccess("artifact", "art-1", owner_public_id=owner.public_id)
    assert can_access_object(owner, obj, action="update")
    assert not can_access_object(stranger, obj, action="read")
    assert can_access_object(stranger, ObjectAccess("artifact", "art-2", visibility="public"))


def test_course_membership_is_persisted_and_not_caller_supplied():
    username = new_public_id("m1-member")
    with TestClient(app) as client:
        auth_headers(client, username)

    with SessionLocal() as session:
        user = session.query(DBUser).filter(DBUser.username == username).one()
        membership = DBCourseMembership(
            course_id="course-rag-engineering-m0",
            user_public_id=user.public_id,
            role="student",
        )
        session.add(membership)
        session.commit()

        assert active_course_role(
            session, course_id=membership.course_id, user_public_id=user.public_id
        ) == "student"
        assert require_course_access(
            session, user, course_id=membership.course_id, action="read"
        ) == "student"

        other = SimpleNamespace(public_id="usr-not-a-member", role="student")
        with pytest.raises(HTTPException) as raised:
            require_course_access(
                session, other, course_id=membership.course_id, action="read"
            )
        assert raised.value.status_code == 403

