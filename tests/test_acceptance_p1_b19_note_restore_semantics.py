from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBLearningEvent, DBNoteVersion, DBStudentProfile, DBUser
from app.migrations import _install_f8_note_restore_pointer_schema, _install_f8_note_workspace_schema
from app.note_workspace import (
    create_note_record,
    note_payload,
    note_versions_payload,
    restore_note_version,
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
        _install_f8_note_restore_pointer_schema(connection)
    session = sessionmaker(bind=engine)()
    owner = DBUser(
        public_id="b19-owner-public",
        username="b19-owner",
        hashed_password="test",
        role="student",
        display_name="B19 学生",
    )
    other = DBUser(
        public_id="b19-other-public",
        username="b19-other",
        hashed_password="test",
        role="student",
        display_name="B19 其他学生",
    )
    session.add_all([
        owner,
        other,
        DBStudentProfile(student_id=owner.username),
        DBStudentProfile(student_id=other.username),
    ])
    session.commit()
    return engine, session, owner, other


def _create_note(session, owner):
    note, created = create_note_record(
        session,
        student_id=owner.username,
        source="conversation",
        content="第一版正文",
        tags=["第一版"],
        concepts=["版本指针"],
        source_metadata={"source_type": "conversation", "conversation_id": "b19-conversation"},
        idempotency_key="b19-create-note-0001",
        actor=owner,
    )
    session.commit()
    assert created is True
    return note


def test_restore_repoints_without_new_history_and_next_save_uses_next_number():
    engine, session, owner, _ = _session()
    try:
        note = _create_note(session, owner)
        updated, changed = update_note_record(
            session,
            note_id=note.id,
            student_id=owner.username,
            content="第二版正文",
            tags=["第二版"],
            concepts=["版本指针"],
            expected_version=1,
            idempotency_key="b19-save-note-0001",
            actor=owner,
        )
        assert changed is True
        session.commit()
        updated, changed = update_note_record(
            session,
            note_id=note.id,
            student_id=owner.username,
            content="第三版正文",
            tags=["第三版"],
            concepts=["版本指针"],
            expected_version=2,
            idempotency_key="b19-save-note-0002",
            actor=owner,
        )
        assert changed is True
        session.commit()
        assert updated.lock_version == 3
        assert updated.current_version_number == 3
        assert session.query(DBNoteVersion).filter_by(note_id=note.id).count() == 3

        restored, changed = restore_note_version(
            session,
            note_id=note.id,
            version_number=1,
            expected_version=3,
            idempotency_key="b19-restore-note-0001",
            actor=owner,
        )
        assert changed is True
        session.commit()
        assert restored.content == "第一版正文"
        assert restored.tags == ["第一版"]
        assert restored.current_version_number == 1
        assert restored.lock_version == 4
        assert session.query(DBNoteVersion).filter_by(note_id=note.id).count() == 3
        assert [item["version_number"] for item in note_versions_payload(session, actor=owner, note=restored)] == [3, 2, 1]
        assert note_payload(session, actor=owner, note=restored)["current_version_number"] == 1

        saved, changed = update_note_record(
            session,
            note_id=note.id,
            student_id=owner.username,
            content="恢复后的第四版正文",
            tags=["第四版"],
            concepts=["版本指针"],
            expected_version=4,
            idempotency_key="b19-save-note-0003",
            actor=owner,
        )
        assert changed is True
        session.commit()
        assert saved.lock_version == 5
        assert saved.current_version_number == 4
        assert session.query(DBNoteVersion).filter_by(note_id=note.id).count() == 4
        assert session.query(DBNoteVersion).filter_by(note_id=note.id, version_number=4).one().content == "恢复后的第四版正文"
    finally:
        session.close()
        engine.dispose()


def test_restore_keeps_source_history_audit_permissions_and_idempotency():
    engine, session, owner, other = _session()
    try:
        note = _create_note(session, owner)
        with pytest.raises(HTTPException) as forbidden:
            restore_note_version(
                session,
                note_id=note.id,
                version_number=1,
                expected_version=1,
                idempotency_key="b19-restore-forbidden",
                actor=other,
            )
        assert forbidden.value.status_code == 403

        with pytest.raises(HTTPException) as conflict:
            restore_note_version(
                session,
                note_id=note.id,
                version_number=1,
                expected_version=99,
                idempotency_key="b19-restore-stale-0001",
                actor=owner,
            )
        assert conflict.value.status_code == 409
        session.rollback()

        restored, changed = restore_note_version(
            session,
            note_id=note.id,
            version_number=1,
            expected_version=1,
            idempotency_key="b19-restore-replay-0001",
            actor=owner,
        )
        assert changed is True
        session.commit()
        source_metadata = dict(restored.source_metadata or {})
        assert source_metadata["conversation_id"] == "b19-conversation"
        event_count = session.query(DBLearningEvent).filter_by(object_id=note.id).count()
        replayed, replay_changed = restore_note_version(
            session,
            note_id=note.id,
            version_number=1,
            expected_version=1,
            idempotency_key="b19-restore-replay-0001",
            actor=owner,
        )
        assert replay_changed is False
        assert replayed.current_version_number == 1
        assert session.query(DBLearningEvent).filter_by(object_id=note.id).count() == event_count
        assert all(
            event.mastery_eligible is False and event.completion_effect == "none"
            for event in session.query(DBLearningEvent).filter_by(object_id=note.id).all()
        )
    finally:
        session.close()
        engine.dispose()
