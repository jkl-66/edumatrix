from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBTutorContextSession, DBUser
from app.m5_workspace import (
    M5WorkspaceError,
    TutorContextSpec,
    TutorPromptPreflight,
    TutorReadingPosition,
    create_tutor_context,
    tutor_prompt_envelope,
    workspace_overview,
)
import stream_api


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    seed_competition_demo(session)
    session.commit()
    return engine, session


def _workspace_spec(payload, item, *, selected_text=""):
    return TutorContextSpec(
        idempotency_key=f"r2-context-{item['object_type']}-{item['id']}",
        course_id=payload["course"]["id"],
        context_mode="current_resource",
        primary_object_type="workspace_object",
        primary_object_id=item["id"],
        selected_source_ref_ids=tuple(item["context"]["source_ref_ids"]),
        selected_text=selected_text,
        reading_position=TutorReadingPosition(
            kind="section" if item["object_type"] == "document" else "object",
            label=(item["render"].get("section") or item["title"]),
        ),
    )


def test_workspace_context_contains_current_object_position_selection_and_minimal_profile():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        payload = workspace_overview(session, current_user=learner)
        document = next(item for item in payload["learning_objects"] if item["object_type"] == "document")
        selected = document["render"]["excerpt"][:48].strip()

        row, created = create_tutor_context(
            session, current_user=learner,
            spec=_workspace_spec(payload, document, selected_text=selected),
        )
        session.commit()
        context = row.context_snapshot

        assert created is True
        assert context["course_id"] == payload["course"]["id"]
        assert context["current_object"]["id"] == document["id"]
        assert context["current_object"]["object_type"] == "document"
        assert context["current_object"]["chapter_id"]
        assert context["reading_position"]["kind"] == "section"
        assert context["selected_text"] == selected
        assert context["sources"][0]["source_ref_id"] == document["context"]["source_ref_ids"][0]
        assert set(context["profile_summary"]) == {
            "mastery", "weak_knowledge_points", "has_misconception", "updated_at",
        }
        assert len(context["profile_summary"]["weak_knowledge_points"]) <= 3
        assert context["data_minimization"]["full_profile_included"] is False
        assert "long_term_memory" not in context
        assert "snapshot_id" not in str(context["profile_summary"])
    finally:
        session.close()
        engine.dispose()


def test_switching_workspace_objects_produces_distinct_prompt_contexts():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        payload = workspace_overview(session, current_user=learner)
        document = next(item for item in payload["learning_objects"] if item["object_type"] == "document")
        exercise = next(item for item in payload["learning_objects"] if item["object_type"] == "exercise")

        first, _ = create_tutor_context(session, current_user=learner, spec=_workspace_spec(payload, document))
        second, _ = create_tutor_context(session, current_user=learner, spec=_workspace_spec(payload, exercise))
        first_envelope = tutor_prompt_envelope(
            session, row=first, owner_public_id=learner.public_id,
            request=TutorPromptPreflight(question="解释当前内容"),
        )
        second_envelope = tutor_prompt_envelope(
            session, row=second, owner_public_id=learner.public_id,
            request=TutorPromptPreflight(question="解释当前内容"),
        )

        assert first_envelope["context"]["current_object"]["object_type"] == "document"
        assert second_envelope["context"]["current_object"]["object_type"] == "exercise"
        assert first_envelope["context"]["current_object"]["id"] != second_envelope["context"]["current_object"]["id"]
    finally:
        session.close()
        engine.dispose()


def test_stream_instruction_uses_workspace_position_selection_and_minimal_profile(monkeypatch):
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        payload = workspace_overview(session, current_user=learner)
        document = next(item for item in payload["learning_objects"] if item["object_type"] == "document")
        selected = document["render"]["excerpt"][:48].strip()
        row, _ = create_tutor_context(
            session, current_user=learner,
            spec=_workspace_spec(payload, document, selected_text=selected),
        )
        session.commit()

        async def fake_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(stream_api, "run_db_op", fake_run_db_op)
        envelope, filenames, instruction = asyncio.run(stream_api._resolve_legacy_tutor_context(
            row.id, owner_public_id=learner.public_id, question="解释当前对象",
        ))

        assert envelope["context"]["current_object"]["id"] == document["id"]
        assert selected in instruction
        assert "阅读位置" in instruction
        assert "最小画像摘要" in instruction
        assert payload["course"]["title"] in instruction
        assert filenames == [document["source"]["filename"]]
        assert "long_term_memory" not in instruction
        assert learner.public_id not in instruction
    finally:
        session.close()
        engine.dispose()


def test_workspace_context_rejects_foreign_object_and_unbound_selected_text():
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        other = session.query(DBUser).filter(DBUser.role == "student", DBUser.public_id != learner.public_id).first()
        payload = workspace_overview(session, current_user=learner)
        experiment = next(item for item in payload["learning_objects"] if item["object_type"] == "experiment")

        with pytest.raises(M5WorkspaceError) as foreign:
            create_tutor_context(
                session, current_user=other,
                spec=_workspace_spec(payload, experiment),
            )
        assert foreign.value.code in {"workspace_course_forbidden", "tutor_workspace_object_forbidden"}

        document = next(item for item in payload["learning_objects"] if item["object_type"] == "document")
        with pytest.raises(M5WorkspaceError) as selection:
            create_tutor_context(
                session, current_user=learner,
                spec=_workspace_spec(payload, document, selected_text="这是其他资源中的私有文本"),
            )
        assert selection.value.code == "tutor_selected_text_invalid"
        assert session.query(DBTutorContextSession).count() == 0
    finally:
        session.close()
        engine.dispose()
