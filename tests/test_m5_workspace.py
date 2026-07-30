from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import (
    Base,
    DBArtifact,
    DBChapter,
    DBCourse,
    DBSourceDocument,
    DBSourceRef,
)
from app.m5_workspace import (
    M5WorkspaceError,
    TutorContextSpec,
    TutorPromptPreflight,
    archive_tutor_context,
    create_tutor_context,
    tutor_prompt_envelope,
)


OWNER = "usr-m5-workspace"
COURSE = "course-m5-workspace"


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = SimpleNamespace(public_id=OWNER, role="student")
    session.add(DBCourse(
        id=COURSE, version="1", title="Workspace course", visibility="public",
        manifest_version="1",
    ))
    session.add(DBSourceDocument(
        id="src-workspace", course_id=COURSE, title="Textbook", filename="book.md",
        file_format="md", content_hash="a" * 64,
    ))
    session.add(DBChapter(
        id="chapter-workspace", course_id=COURSE, source_document_id="src-workspace",
        stable_key="workspace-chapter", title="Source-bound chapter",
    ))
    session.add(DBSourceRef(
        id="ref-workspace", source_document_id="src-workspace", chapter_id="chapter-workspace",
        parser_version="parser-v1", page_number=3, char_start=10, char_end=40,
        quote="Persisted source quotation", content_hash="b" * 64,
    ))
    session.add(DBArtifact(
        id="artifact-workspace", owner_public_id=OWNER, course_id=COURSE,
        artifact_type="lesson", title="Owned lesson",
    ))
    session.flush()
    return session, user


def _spec(key="context-key-001", **updates):
    data = {
        "idempotency_key": key,
        "course_id": COURSE,
        "context_mode": "current_resource",
        "primary_object_type": "chapter",
        "primary_object_id": "chapter-workspace",
        "selected_source_ref_ids": ("ref-workspace",),
    }
    data.update(updates)
    return TutorContextSpec(**data)


def test_context_is_source_bound_and_idempotent():
    session, user = _session()
    row, created = create_tutor_context(session, current_user=user, spec=_spec())
    replay, replay_created = create_tutor_context(session, current_user=user, spec=_spec())

    assert created is True and replay_created is False and replay.id == row.id
    assert row.context_snapshot["sources"][0]["quote"] == "Persisted source quotation"
    assert row.context_snapshot["retrieval_scope"]["current_resource_only"] is True
    with pytest.raises(M5WorkspaceError, match="another tutor context"):
        create_tutor_context(
            session, current_user=user,
            spec=_spec(teaching_style="case_based"),
        )


def test_context_rejects_cross_course_or_missing_sources():
    session, user = _session()
    with pytest.raises(M5WorkspaceError, match="outside the selected course"):
        create_tutor_context(
            session, current_user=user,
            spec=_spec(selected_source_ref_ids=("missing-ref",)),
        )


def test_prompt_preflight_preserves_context_without_starting_generation():
    session, user = _session()
    first, _ = create_tutor_context(session, current_user=user, spec=_spec())
    second, _ = create_tutor_context(
        session, current_user=user,
        spec=_spec(
            key="context-key-002", primary_object_type="artifact",
            primary_object_id="artifact-workspace", selected_source_ref_ids=(),
            context_mode="personal_resources",
        ),
    )
    envelope = tutor_prompt_envelope(
        session, row=first, owner_public_id=OWNER,
        request=TutorPromptPreflight(
            question="Compare the explanations", intent="compare",
            comparison_context_ids=(second.id,),
        ),
    )

    assert envelope["generation_started"] is False
    assert envelope["context"]["primary"]["object_id"] == "chapter-workspace"
    assert envelope["comparison_contexts"][0]["primary"]["object_id"] == "artifact-workspace"


def test_archived_context_rejects_questions_and_uses_optimistic_lock():
    session, user = _session()
    row, _ = create_tutor_context(session, current_user=user, spec=_spec())
    archive_tutor_context(
        session, row=row, owner_public_id=OWNER, expected_lock_version=1,
    )
    with pytest.raises(M5WorkspaceError, match="lock version changed"):
        archive_tutor_context(
            session, row=row, owner_public_id=OWNER, expected_lock_version=1,
        )
    with pytest.raises(M5WorkspaceError, match="cannot accept questions"):
        tutor_prompt_envelope(
            session, row=row, owner_public_id=OWNER,
            request=TutorPromptPreflight(question="Explain this"),
        )
