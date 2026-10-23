from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import (
    Base,
    DBArtifact,
    DBArtifactVersion,
    DBCourse,
    DBLearningEvent,
    DBNote,
    DBNoteVersion,
    DBReviewPlan,
    DBStudentProfile,
    DBUser,
)
from app.migrations import _install_f8_note_workspace_schema
from app.note_workspace import (
    create_note_record,
    note_payload,
    note_versions_payload,
    prepare_source_metadata,
    restore_note_version,
    save_ai_suggestion,
    update_note_record,
)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        _install_f8_note_workspace_schema(connection)
    session = sessionmaker(bind=engine)()
    owner = DBUser(
        public_id="usr-note-owner",
        username="note-owner",
        hashed_password="test",
        role="student",
        display_name="笔记学生",
    )
    other = DBUser(
        public_id="usr-note-other",
        username="note-other",
        hashed_password="test",
        role="student",
        display_name="其他学生",
    )
    session.add_all([
        owner,
        other,
        DBStudentProfile(student_id=owner.username),
        DBStudentProfile(student_id=other.username),
    ])
    session.commit()
    return session, owner, other


def _create_manual(session, owner, *, key="manual-note-create-0001"):
    note, created = create_note_record(
        session,
        student_id=owner.username,
        source="manual",
        content="# 初始笔记\n\n用户自己的正文。",
        tags=["基础"],
        concepts=["梯度下降"],
        idempotency_key=key,
        actor=owner,
    )
    session.commit()
    return note, created


def test_note_versions_conflicts_ai_suggestion_and_restore_are_non_mastery():
    session, owner, _ = _session()
    note, created = _create_manual(session, owner)
    assert created is True
    assert note.lock_version == 1
    assert session.query(DBNoteVersion).filter_by(note_id=note.id).count() == 1
    first_event = session.query(DBLearningEvent).filter_by(object_id=note.id).one()
    assert (first_event.mastery_eligible, first_event.completion_effect) == (False, "none")

    replay, replay_created = _create_manual(session, owner)
    assert (replay.id, replay_created) == (note.id, False)
    assert session.query(DBLearningEvent).filter_by(object_id=note.id).count() == 1

    updated, changed = update_note_record(
        session,
        note_id=note.id,
        student_id=owner.username,
        content="# 初始笔记\n\n这是用户保存后的第二版。",
        tags=["基础", "重点"],
        concepts=["梯度下降"],
        expected_version=1,
        idempotency_key="manual-note-save-0001",
        actor=owner,
    )
    session.commit()
    assert changed is True
    assert updated.lock_version == 2
    assert session.query(DBNoteVersion).filter_by(note_id=note.id).count() == 2

    replayed, replay_changed = update_note_record(
        session,
        note_id=note.id,
        student_id=owner.username,
        content="# 初始笔记\n\n这是用户保存后的第二版。",
        tags=["基础", "重点"],
        concepts=["梯度下降"],
        expected_version=1,
        idempotency_key="manual-note-save-0001",
        actor=owner,
    )
    assert replay_changed is False
    assert replayed.lock_version == 2

    local_draft = "本地尚未提交，发生冲突后必须保留。"
    with pytest.raises(HTTPException) as conflict:
        update_note_record(
            session,
            note_id=note.id,
            student_id=owner.username,
            content=local_draft,
            tags=["冲突草稿"],
            concepts=["梯度下降"],
            expected_version=1,
            idempotency_key="manual-note-stale-0001",
            actor=owner,
        )
    assert conflict.value.status_code == 409
    session.refresh(note)
    assert local_draft not in note.content
    assert note.lock_version == 2

    original_body = note.content
    save_ai_suggestion(
        session,
        note_id=note.id,
        actor=owner,
        expected_version=2,
        idempotency_key="manual-note-ai-suggestion-0001",
        content="# AI 建议\n\n这是候选内容，不是用户正文。",
        tags=["AI建议"],
        concepts=["梯度下降"],
    )
    session.commit()
    session.refresh(note)
    assert note.content == original_body
    assert note.ai_suggestion.startswith("# AI 建议")
    assert note.lock_version == 2

    applied, _ = update_note_record(
        session,
        note_id=note.id,
        student_id=owner.username,
        content=note.ai_suggestion,
        tags=note.ai_suggestion_metadata["tags"],
        concepts=note.ai_suggestion_metadata["concepts"],
        expected_version=2,
        idempotency_key="manual-note-apply-ai-0001",
        actor=owner,
        change_type="ai_suggestion_applied",
    )
    session.commit()
    assert applied.lock_version == 3
    assert applied.ai_suggestion == ""

    restored, restored_now = restore_note_version(
        session,
        note_id=note.id,
        version_number=1,
        expected_version=3,
        idempotency_key="manual-note-restore-0001",
        actor=owner,
    )
    session.commit()
    assert restored_now is True
    assert restored.lock_version == 4
    assert restored.current_version_number == 1
    assert restored.content == "# 初始笔记\n\n用户自己的正文。"
    versions = note_versions_payload(session, actor=owner, note=restored)
    assert [item["version_number"] for item in versions] == [3, 2, 1]
    assert all(item["change_type"] != "restored" for item in versions)
    assert session.query(DBNoteVersion).filter_by(note_id=note.id, version_number=1).one().content == restored.content
    assert all(
        event.mastery_eligible is False and event.completion_effect == "none"
        for event in session.query(DBLearningEvent).filter_by(object_id=note.id).all()
    )


def test_resource_source_projection_survives_withdrawal_and_reads_are_side_effect_free():
    session, owner, _ = _session()
    course = DBCourse(
        id="course-note-source",
        version="1",
        title="人工智能导论",
        manifest_version="1",
        owner_public_id=owner.public_id,
    )
    artifact = DBArtifact(
        id="art-note-handout",
        owner_public_id=owner.public_id,
        course_id=course.id,
        artifact_type="handout",
        title="梯度下降个性化讲义",
        status="published",
        current_version_id="av-note-handout-1",
    )
    version = DBArtifactVersion(
        id="av-note-handout-1",
        artifact_id=artifact.id,
        version_number=1,
        content="讲义正文不复制进笔记来源。",
        content_format="markdown",
        content_hash="a" * 64,
        metadata_json={"resource_type": "handout"},
        created_by_public_id=owner.public_id,
    )
    session.add(course)
    session.commit()
    session.add(artifact)
    session.commit()
    session.add(version)
    session.commit()

    source_type, metadata = prepare_source_metadata(
        session,
        actor=owner,
        source_type="handout",
        metadata={"resource_id": artifact.id, "resource_version_id": version.id},
    )
    note, _ = create_note_record(
        session,
        student_id=owner.username,
        source=source_type,
        content="我对梯度下降的理解。",
        source_metadata=metadata,
        idempotency_key="handout-note-create-0001",
        actor=owner,
    )
    session.commit()
    events_before = session.query(DBLearningEvent).count()
    payload = note_payload(session, actor=owner, note=note)
    note_versions_payload(session, actor=owner, note=note)
    assert session.query(DBLearningEvent).count() == events_before
    assert payload["source_context"]["available"] is True
    assert payload["source_context"]["resource_version_id"] == version.id
    assert payload["source_context"]["route"].startswith(f"/workspace/resources/handouts/{artifact.id}")
    assert version.content not in json.dumps(payload["source_context"], ensure_ascii=False)

    artifact.archived_at = note.updated_at
    session.commit()
    withdrawn = note_payload(session, actor=owner, note=note)
    assert withdrawn["source_context"]["available"] is False
    assert withdrawn["content"] == "我对梯度下降的理解。"
    assert withdrawn["source_metadata"]["resource_version_id"] == version.id


def test_review_source_projection_repairs_legacy_return_route_without_side_effects():
    session, owner, _ = _session()
    plan = DBReviewPlan(student_id=owner.username, concept="梯度下降", mastery=0.4)
    session.add(plan)
    session.commit()

    source_type, metadata = prepare_source_metadata(
        session,
        actor=owner,
        source_type="review_task",
        metadata={"source_id": str(plan.id)},
    )
    assert metadata["route"] == f"/workspace/review?review_task=review-plan:{plan.id}"
    note, _ = create_note_record(
        session,
        student_id=owner.username,
        source=source_type,
        content="复习来源笔记。",
        source_metadata=metadata,
        idempotency_key="review-note-create-0001",
        actor=owner,
    )
    note.source_metadata = {**note.source_metadata, "route": f"/workspace/review?plan_id={plan.id}"}
    session.commit()

    events_before = session.query(DBLearningEvent).count()
    payload = note_payload(session, actor=owner, note=note)
    assert payload["source_context"]["route"] == f"/workspace/review?review_task=review-plan:{plan.id}"
    assert session.query(DBLearningEvent).count() == events_before


def test_cross_student_note_access_is_rejected():
    session, owner, other = _session()
    note, _ = _create_manual(session, owner)
    with pytest.raises(HTTPException) as forbidden:
        note_payload(session, actor=other, note=note)
    assert forbidden.value.status_code == 403
    with pytest.raises(HTTPException) as forbidden_update:
        update_note_record(
            session,
            note_id=note.id,
            student_id=None,
            content="越权修改",
            tags=[],
            concepts=[],
            expected_version=1,
            idempotency_key="cross-user-note-save-0001",
            actor=other,
        )
    assert forbidden_update.value.status_code == 403


def test_migration_backfills_legacy_note_without_overwriting_content():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE notes (id VARCHAR(64) PRIMARY KEY, content TEXT, tags JSON, concepts JSON, "
            "source VARCHAR(128), source_metadata JSON, created_at DATETIME)"
        ))
        connection.execute(
            text(
                "INSERT INTO notes(id, content, tags, concepts, source, source_metadata, created_at) "
                "VALUES ('legacy-note', '旧笔记正文', '[\"旧标签\"]', '[\"旧概念\"]', 'manual', '{}', CURRENT_TIMESTAMP)"
            )
        )
        _install_f8_note_workspace_schema(connection)
    columns = {column["name"] for column in inspect(engine).get_columns("notes")}
    assert {"lock_version", "current_version_number", "ai_suggestion", "ai_suggestion_metadata"} <= columns
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT content, lock_version, current_version_number, ai_suggestion FROM notes WHERE id = 'legacy-note'"
        )).mappings().one()
        version = connection.execute(text(
            "SELECT version_number, content, change_type FROM note_versions WHERE note_id = 'legacy-note'"
        )).mappings().one()
    assert dict(row) == {"content": "旧笔记正文", "lock_version": 1, "current_version_number": 1, "ai_suggestion": ""}
    assert dict(version) == {"version_number": 1, "content": "旧笔记正文", "change_type": "legacy_baseline"}
