from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import (
    Base,
    DBArtifact,
    DBArtifactVersion,
    DBKnowledgeDocument,
    DBLegacyObjectMigration,
    DBLearningPath,
    DBNote,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBReviewPlan,
    DBSourceDocument,
    DBStudentProfile,
    DBUser,
    DBWrongQuestion,
)
from app.main import app
import app.legacy_migration_governance as legacy_migration
from app.legacy_migration_governance import (
    LegacyMigrationError,
    legacy_object_migrations,
    migrate_legacy_object,
    rollback_legacy_object,
)
from app.migrations import apply_registered_migrations
import app.m5_api as m5_api


ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def _seed(session):
    owner = DBUser(
        public_id="owner-public",
        username="legacy-owner",
        hashed_password="hash",
        role="student",
        is_active=True,
    )
    profile = DBStudentProfile(
        student_id=owner.username,
        target_course="机器学习",
        weak_points=["梯度下降"],
        learning_goals=["完成分类实训"],
        concept_mastery={"梯度下降": 0.42},
    )
    note = DBNote(
        id="legacy-note-1",
        student_id=owner.username,
        source="conversation",
        content="梯度下降学习笔记",
        tags=["优化"],
        concepts=["梯度下降"],
    )
    resource = DBKnowledgeDocument(
        id="legacy-resource-1",
        student_id=owner.username,
        filename="gradient.md",
        file_type="md",
        title="梯度下降讲义",
        content="# 梯度下降\n旧课程内容",
        tags=["优化"],
    )
    review = DBReviewPlan(
        student_id=owner.username,
        concept="梯度下降",
        interval_days=2,
        next_review_at=datetime(2026, 8, 14, 8, 0),
        mastery=0.42,
    )
    wrong = DBWrongQuestion(
        student_id=owner.username,
        concept_name="梯度下降",
        wrong_reason_category="公式理解",
        notes="学习率方向判断错误",
    )
    session.add_all([owner, profile, note, resource, review, wrong])
    session.commit()
    return owner, profile, note, resource, review, wrong


def test_five_legacy_object_types_migrate_idempotently_and_keep_sources():
    session, _ = _session()
    owner, profile, note, resource, review, wrong = _seed(session)
    cases = [
        ("profile", profile.student_id, "profile_snapshot"),
        ("path", str(review.id), "learning_path"),
        ("resource", resource.id, "source_document"),
        ("note", note.id, "artifact"),
        ("wrong_question", str(wrong.id), "wrong_question"),
    ]

    results = []
    for old_type, old_id, target_type in cases:
        first = migrate_legacy_object(
            session,
            owner_public_id=owner.public_id,
            old_type=old_type,
            old_id=old_id,
        )
        session.commit()
        second = migrate_legacy_object(
            session,
            owner_public_id=owner.public_id,
            old_type=old_type,
            old_id=old_id,
        )
        session.commit()
        assert first["id"] == second["id"]
        assert first["targetId"] == second["targetId"]
        assert first["status"] == "verified"
        assert first["targetType"] == target_type
        results.append(first)

    assert session.get(DBStudentProfile, profile.student_id) is not None
    assert session.get(DBNote, note.id) is not None
    assert session.get(DBKnowledgeDocument, resource.id) is not None
    assert session.get(DBReviewPlan, review.id) is not None
    assert session.get(DBWrongQuestion, wrong.id) is not None
    assert session.query(DBProfileSnapshot).count() == 1
    assert session.query(DBLearningPath).count() == 1
    assert session.query(DBSourceDocument).count() == 1
    assert session.query(DBArtifact).count() == 1
    assert len(legacy_object_migrations(session, owner_public_id=owner.public_id)) == 5
    assert len({item["rollbackToken"] for item in results}) == 5

    for item in results:
        rolled_back = rollback_legacy_object(
            session,
            owner_public_id=owner.public_id,
            migration_id=item["id"],
            rollback_token=item["rollbackToken"],
        )
        assert rolled_back["status"] == "rolled_back"
    session.commit()

    assert session.get(DBStudentProfile, profile.student_id) is not None
    assert session.get(DBNote, note.id) is not None
    assert session.get(DBKnowledgeDocument, resource.id) is not None
    assert session.get(DBReviewPlan, review.id) is not None
    assert session.get(DBWrongQuestion, wrong.id) is not None
    assert session.query(DBProfileSnapshot).count() == 0
    assert session.query(DBLearningPath).count() == 0
    assert session.query(DBPathNode).count() == 0
    assert session.query(DBPlanVersion).count() == 0
    assert session.query(DBPlanDraft).count() == 0
    assert session.query(DBSourceDocument).count() == 0
    assert session.query(DBArtifactVersion).count() == 0
    assert session.query(DBArtifact).count() == 0


def test_rollback_removes_only_created_canonical_objects_and_retry_reuses_mapping():
    session, _ = _session()
    owner, _, note, _, _, _ = _seed(session)
    migrated = migrate_legacy_object(
        session,
        owner_public_id=owner.public_id,
        old_type="note",
        old_id=note.id,
    )
    session.commit()
    artifact_id = migrated["targetId"]
    assert session.get(DBArtifact, artifact_id) is not None

    with pytest.raises(LegacyMigrationError) as denied:
        rollback_legacy_object(
            session,
            owner_public_id=owner.public_id,
            migration_id=migrated["id"],
            rollback_token="wrong",
        )
    assert denied.value.code == "legacy_migration_rollback_forbidden"

    rolled_back = rollback_legacy_object(
        session,
        owner_public_id=owner.public_id,
        migration_id=migrated["id"],
        rollback_token=migrated["rollbackToken"],
    )
    session.commit()
    assert rolled_back["status"] == "rolled_back"
    assert session.get(DBArtifact, artifact_id) is None
    assert session.get(DBNote, note.id) is not None

    retried = migrate_legacy_object(
        session,
        owner_public_id=owner.public_id,
        old_type="note",
        old_id=note.id,
    )
    session.commit()
    assert retried["id"] == migrated["id"]
    assert retried["status"] == "verified"
    assert retried["targetId"] != artifact_id


def test_failed_source_keeps_mapping_and_can_retry_after_source_exists():
    session, _ = _session()
    owner, *_ = _seed(session)
    with pytest.raises(LegacyMigrationError) as missing:
        migrate_legacy_object(
            session,
            owner_public_id=owner.public_id,
            old_type="note",
            old_id="late-note",
        )
    session.commit()
    assert missing.value.code == "legacy_migration_source_unknown"
    mapping = session.query(DBLegacyObjectMigration).filter_by(old_id="late-note").one()
    assert mapping.status == "failed"

    session.add(DBNote(
        id="late-note",
        student_id=owner.username,
        content="稍后恢复的笔记",
    ))
    session.commit()
    recovered = migrate_legacy_object(
        session,
        owner_public_id=owner.public_id,
        old_type="note",
        old_id="late-note",
    )
    session.commit()
    assert recovered["id"] == mapping.id
    assert recovered["status"] == "verified"


def test_target_owner_mismatch_fails_without_deleting_foreign_target(monkeypatch):
    session, _ = _session()
    owner, profile, *_ = _seed(session)
    foreign = DBUser(
        public_id="foreign-public",
        username="foreign-owner",
        hashed_password="hash",
        role="student",
        is_active=True,
    )
    session.add(foreign)
    session.flush()
    target = DBProfileSnapshot(
        owner_public_id=foreign.public_id,
        legacy_student_id=foreign.username,
        profile_version="foreign-v1",
        snapshot={"scope": "foreign"},
        content_hash="f" * 64,
        trace_id="foreign-trace",
    )
    session.add(target)
    session.commit()
    monkeypatch.setitem(
        legacy_migration.COPY_HANDLERS,
        "profile",
        lambda current_session, row, current_owner: (target.id, []),
    )

    with pytest.raises(LegacyMigrationError) as denied:
        migrate_legacy_object(
            session,
            owner_public_id=owner.public_id,
            old_type="profile",
            old_id=profile.student_id,
        )
    session.commit()

    assert denied.value.code == "legacy_migration_target_forbidden"
    assert session.get(DBProfileSnapshot, target.id) is not None
    mapping = session.query(DBLegacyObjectMigration).filter_by(
        owner_public_id=owner.public_id,
        old_type="profile",
    ).one()
    assert mapping.status == "failed"
    assert mapping.target_id is None


def test_copy_failure_rolls_back_partial_canonical_object(monkeypatch):
    session, _ = _session()
    owner, profile, *_ = _seed(session)

    def fail_after_insert(current_session, row, current_owner):
        partial = DBProfileSnapshot(
            owner_public_id=current_owner.public_id,
            legacy_student_id=row.student_id,
            profile_version="partial-v1",
            snapshot={"partial": True},
            content_hash="p" * 64,
            trace_id="partial-trace",
        )
        current_session.add(partial)
        current_session.flush()
        raise RuntimeError("injected copy failure")

    monkeypatch.setitem(legacy_migration.COPY_HANDLERS, "profile", fail_after_insert)
    with pytest.raises(LegacyMigrationError) as failed:
        migrate_legacy_object(
            session,
            owner_public_id=owner.public_id,
            old_type="profile",
            old_id=profile.student_id,
        )
    session.commit()

    assert failed.value.code == "legacy_migration_copy_failed"
    assert session.query(DBProfileSnapshot).count() == 0
    assert session.get(DBStudentProfile, profile.student_id) is not None
    mapping = session.query(DBLegacyObjectMigration).filter_by(
        owner_public_id=owner.public_id,
        old_type="profile",
    ).one()
    assert mapping.status == "failed"
    assert mapping.target_id is None
    assert mapping.created_objects == []


def test_copied_mapping_is_verified_without_copying_again(monkeypatch):
    session, _ = _session()
    owner, profile, *_ = _seed(session)
    target = DBProfileSnapshot(
        owner_public_id=owner.public_id,
        legacy_student_id=profile.student_id,
        profile_version="copied-v1",
        snapshot={"copied": True},
        content_hash="c" * 64,
        trace_id="copied-trace",
    )
    session.add(target)
    session.flush()
    mapping = DBLegacyObjectMigration(
        owner_public_id=owner.public_id,
        legacy_student_id=profile.student_id,
        old_type="profile",
        old_id=profile.student_id,
        target_type="profile_snapshot",
        target_id=target.id,
        version="1",
        status="copied",
        rollback_token="copied-rollback-token",
        created_objects=[{"type": "profile_snapshot", "id": target.id}],
    )
    session.add(mapping)
    session.commit()
    monkeypatch.setitem(
        legacy_migration.COPY_HANDLERS,
        "profile",
        lambda *args: pytest.fail("copied mapping must not be copied again"),
    )

    verified = migrate_legacy_object(
        session,
        owner_public_id=owner.public_id,
        old_type="profile",
        old_id=profile.student_id,
    )
    session.commit()

    assert verified["status"] == "verified"
    assert verified["targetId"] == target.id
    assert session.query(DBProfileSnapshot).count() == 1


def test_migration_api_enforces_operator_roles_and_persists_failures(monkeypatch):
    session, _ = _session()
    owner, _, note, *_ = _seed(session)

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    client = TestClient(app)
    identity = {
        "user": DBUser(
            public_id="student-operator",
            username="student-operator",
            role="student",
            is_active=True,
        )
    }
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    payload = {
        "owner_public_id": owner.public_id,
        "old_type": "note",
        "old_id": note.id,
        "version": "1",
    }
    try:
        denied = client.post("/api/v1/m5/legacy-object-migrations", json=payload)
        assert denied.status_code == 403

        identity["user"] = DBUser(
            public_id="teacher-operator",
            username="teacher-operator",
            role="teacher",
            is_active=True,
        )
        created = client.post("/api/v1/m5/legacy-object-migrations", json=payload)
        assert created.status_code == 201, created.text
        migration = created.json()
        assert migration["status"] == "verified"

        listed = client.get(
            "/api/v1/m5/legacy-object-migrations",
            params={"owner_public_id": owner.public_id},
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["items"]] == [migration["id"]]

        rejected = client.post(
            f"/api/v1/m5/legacy-object-migrations/{migration['id']}/rollback",
            json={"owner_public_id": owner.public_id, "rollback_token": "wrong"},
        )
        assert rejected.status_code == 403

        rolled_back = client.post(
            f"/api/v1/m5/legacy-object-migrations/{migration['id']}/rollback",
            json={
                "owner_public_id": owner.public_id,
                "rollback_token": migration["rollbackToken"],
            },
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()["status"] == "rolled_back"

        identity["user"] = DBUser(
            public_id="admin-operator",
            username="admin-operator",
            role="admin",
            is_active=True,
        )
        admin_list = client.get(
            "/api/v1/m5/legacy-object-migrations",
            params={"owner_public_id": owner.public_id},
        )
        assert admin_list.status_code == 200

        missing_payload = {**payload, "old_id": "missing-note", "version": "2"}
        failed = client.post(
            "/api/v1/m5/legacy-object-migrations", json=missing_payload,
        )
        assert failed.status_code == 404
        failed_mapping = session.query(DBLegacyObjectMigration).filter_by(
            owner_public_id=owner.public_id,
            old_id="missing-note",
            version="2",
        ).one()
        assert failed_mapping.status == "failed"
        assert failed_mapping.error_code == "legacy_migration_source_unknown"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_registered_schema_is_repeatable_and_contains_state_constraint(tmp_path):
    database = tmp_path / "migration.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    first = apply_registered_migrations(engine)
    second = apply_registered_migrations(engine)
    assert "20260812_064" in first
    assert second == []
    table = inspect(engine).get_table_names()
    assert "legacy_object_migrations" in table
    checks = inspect(engine).get_check_constraints("legacy_object_migrations")
    assert any(item["name"] == "ck_legacy_object_migration_status" for item in checks)


def test_legacy_route_contract_preserves_query_and_protected_destinations():
    source = (ROOT / "frontend" / "src" / "router" / "index.js").read_text(encoding="utf-8")
    assert "query: { ...to.query, compat: notice }" in source
    assert "legacy('/student-analysis', 'LegacyStudentAnalysis', '/profile/learning')" in source
    assert "legacy('/learning-path', 'LegacyLearningPath', '/workspace/path')" in source
    assert "legacy('/notes', 'LegacyNotes', '/workspace/notes')" in source
    assert "legacy('/wrong-questions', 'LegacyWrongQuestions', '/workspace/review/wrong-questions')" in source
