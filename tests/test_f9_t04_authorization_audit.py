from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.audit_log import AuditPayloadError, audit_log_payload, record_backend_audit
from app.auth import enforce_student_access, get_current_teacher
from app.authorization import ObjectAccess, can_access_object
from app.competition_demo_seed import seed_competition_demo
from app.content_review import _can_review, _can_submit
from app.database import Base, DBAuditLog, DBLearningPath, DBPlanDraft, DBUser
import app.m6_teacher as teacher_service


def user(role: str, *, public_id: str = "user-1", username: str = "user-1"):
    return SimpleNamespace(role=role, public_id=public_id, username=username)


def session_fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_only_formal_teacher_roles_receive_teacher_authority() -> None:
    for role in ("teacher", "admin"):
        assert asyncio.run(get_current_teacher(user(role))).role == role

    for role in ("student", "assistant", "visitor"):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_current_teacher(user(role)))
        assert exc_info.value.status_code == 403


def test_legacy_account_roles_receive_neither_student_nor_private_object_access() -> None:
    private = ObjectAccess(
        object_type="artifact",
        object_id="artifact-1",
        owner_public_id="user-1",
    )
    public = ObjectAccess(
        object_type="artifact",
        object_id="artifact-public",
        visibility="public",
    )

    for role in ("assistant", "visitor"):
        actor = user(role)
        with pytest.raises(HTTPException) as exc_info:
            enforce_student_access(None, actor)
        assert exc_info.value.status_code == 403
        assert can_access_object(actor, private, action="read", course_role="assistant") is False
        assert can_access_object(actor, public, action="read") is False


def test_student_and_teacher_student_scope_rules_remain_explicit() -> None:
    student = user("student", username="student-a")
    teacher = user("teacher")

    assert enforce_student_access(None, student) == "student-a"
    with pytest.raises(HTTPException) as cross_student:
        enforce_student_access("student-b", student)
    assert cross_student.value.status_code == 403

    assert enforce_student_access("student-b", teacher) == "student-b"
    with pytest.raises(HTTPException) as missing_scope:
        enforce_student_access(None, teacher)
    assert missing_scope.value.status_code == 400


def test_content_review_does_not_treat_assistant_membership_as_teacher_authority() -> None:
    assistant = user("assistant")
    artifact = SimpleNamespace(owner_public_id=assistant.public_id, course_id="course-1")
    assert _can_submit(None, artifact, assistant) is False
    assert _can_review(None, artifact, assistant) is False


def test_summary_audit_rejects_nested_case_variant_secrets() -> None:
    engine, session = session_fixture()
    try:
        unsafe_summaries = (
            {"nested": [{"API-Key": "private-value"}]},
            {"result": {"System_Prompt": "private instructions"}},
            {"credential": "Bearer private-token-value"},
            {"safe": {"raw-log": "private provider output"}},
        )
        for summary in unsafe_summaries:
            with pytest.raises(AuditPayloadError):
                record_backend_audit(
                    session,
                    actor_public_id=None,
                    action="test.unsafe",
                    object_type="test_object",
                    object_id="test-1",
                    before_summary=summary,
                )
        assert session.query(DBAuditLog).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_public_audit_projection_never_exposes_legacy_metadata() -> None:
    engine, session = session_fixture()
    try:
        row = DBAuditLog(
            actor_public_id=None,
            action="legacy.operation",
            object_type="legacy_object",
            object_id="legacy-1",
            trace_id="private-trace-value",
            outcome="success",
            metadata_json={"nested": {"api_key": "must-not-be-returned"}},
        )
        session.add(row)
        session.commit()
        payload = audit_log_payload(row)
        assert payload["detailsAvailable"] is False
        assert payload["beforeSummary"] == {}
        assert payload["afterSummary"] == {}
        assert "must-not-be-returned" not in str(payload)
        assert "private-trace-value" not in str(payload)
    finally:
        session.close()
        engine.dispose()


def test_teacher_intervention_rolls_back_when_required_audit_fails(monkeypatch) -> None:
    engine, session = session_fixture()
    try:
        seed_competition_demo(session)
        teacher = session.query(DBUser).filter_by(username="teacher").one()
        learner = session.query(DBUser).filter_by(username="lzz").one()
        before = {
            "plans": session.query(DBPlanDraft).count(),
            "paths": session.query(DBLearningPath).count(),
            "audits": session.query(DBAuditLog).count(),
        }

        def fail_audit(*args, **kwargs):
            raise RuntimeError("audit storage unavailable")

        monkeypatch.setattr(teacher_service, "record_backend_audit", fail_audit)
        with pytest.raises(RuntimeError, match="audit storage unavailable"):
            teacher_service.publish_teacher_intervention(
                session,
                actor=teacher,
                course_id="demo-course-rag-trust-v1",
                learner_public_id=learner.public_id,
                idempotency_key="f9-t04-audit-rollback",
            )

        assert session.query(DBPlanDraft).count() == before["plans"]
        assert session.query(DBLearningPath).count() == before["paths"]
        assert session.query(DBAuditLog).count() == before["audits"]
    finally:
        session.close()
        engine.dispose()
