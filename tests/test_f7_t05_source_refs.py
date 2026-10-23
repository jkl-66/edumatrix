from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import (
    Base,
    DBChapter,
    DBChatConversation,
    DBChatMessage,
    DBCourse,
    DBCourseMembership,
    DBDocumentSelection,
    DBLearningEvent,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.chat_api import _context_source_refs, _stream_source_materials, message_payload
from app.document_selection import _selection_payload
from app.m1_api import SourceRefDetail
from app.resource_bundles import _source_snapshots
from app.source_refs import chat_source_ref, project_selection, project_source_ref


@pytest.fixture()
def source_context(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'f7-t05-source-refs.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    owner = DBUser(public_id="usr-f7t05-owner", username="f7t05_owner", hashed_password="x", role="student")
    member = DBUser(public_id="usr-f7t05-member", username="f7t05_member", hashed_password="x", role="student")
    outsider = DBUser(public_id="usr-f7t05-outsider", username="f7t05_outsider", hashed_password="x", role="student")
    course = DBCourse(
        id="course-f7t05-private",
        version="1",
        title="来源引用课程",
        visibility="private",
        status="published",
        owner_public_id=owner.public_id,
        manifest_version="f7-t05-v1",
    )
    session.add_all([owner, member, outsider, course])
    session.flush()
    session.add(DBCourseMembership(
        course_id=course.id,
        user_public_id=member.public_id,
        role="student",
        status="active",
    ))
    content = "梯度下降沿损失函数的负梯度方向更新参数。"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    source = DBSourceDocument(
        id="src-f7t05",
        course_id=course.id,
        title="梯度下降讲义",
        filename="gradient.md",
        file_format="markdown",
        content_hash=digest,
        source_sha256=digest,
        processed_sha256=digest,
        parser_version="parser-v1",
        processing_status="ready",
    )
    session.add(source)
    session.flush()
    chapter = DBChapter(
        id="ch-f7t05",
        course_id=course.id,
        source_document_id=source.id,
        stable_key="gradient",
        title="梯度下降",
        position=1,
        char_start=0,
        char_end=len(content),
    )
    session.add(chapter)
    session.flush()
    source_ref = DBSourceRef(
        id="ref-f7t05",
        source_document_id=source.id,
        chapter_id=chapter.id,
        parser_version="parser-v1",
        page_number=3,
        char_start=0,
        char_end=len(content),
        image_region={"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2},
        location_kind="page",
        location_index=3,
        location_label="第 3 页",
        content_hash=digest,
        quote=content,
    )
    session.add(source_ref)
    session.flush()
    selection = DBDocumentSelection(
        id="sel-f7t05",
        owner_public_id=member.public_id,
        source_document_id=source.id,
        source_ref_id=source_ref.id,
        document_version=digest,
        selection_type="image",
        section_id=chapter.id,
        page_number=3,
        quote="负梯度方向更新参数",
        page_width=1200,
        page_height=800,
        normalized_rect={"x": 0.2, "y": 0.25, "width": 0.4, "height": 0.2},
        ocr_status="ready",
        ocr_text="负梯度方向更新参数",
        idempotency_key="f7-t05-selection-key",
    )
    session.add(selection)
    session.commit()
    try:
        yield session, owner, member, outsider, course, source, source_ref, selection
    finally:
        session.close()
        engine.dispose()


def test_source_projection_authorizes_and_builds_exact_reader_route(source_context) -> None:
    session, _, member, outsider, course, _, source_ref, _ = source_context
    projection = project_source_ref(session, source_ref.id, actor=member, expected_course_id=course.id)
    assert projection["available"] is True
    assert projection["chapter_title"] == "梯度下降"
    assert projection["page_number"] == 3
    assert projection["char_start"] == 0
    assert projection["route"] == (
        "/knowledge/documents/src-f7t05?course_id=course-f7t05-private"
        "&source_ref_id=ref-f7t05&page=3&chapter_id=ch-f7t05&char_start=0"
    )
    with pytest.raises(HTTPException) as denied:
        project_source_ref(session, source_ref.id, actor=outsider)
    assert denied.value.status_code == 403
    unavailable = project_source_ref(
        session,
        source_ref.id,
        actor=outsider,
        permission_as_unavailable=True,
    )
    assert unavailable["available"] is False
    assert unavailable["reason_code"] == "permission_changed"


def test_frozen_source_history_survives_withdrawal_drift_and_removal(source_context) -> None:
    session, _, member, _, course, source, source_ref, _ = source_context
    frozen = chat_source_ref(project_source_ref(session, source_ref.id, actor=member))
    source.processing_status = "failed"
    source.processing_error_code = "source_withdrawn"
    session.commit()
    withdrawn = project_source_ref(
        session,
        source_ref.id,
        actor=member,
        expected_course_id=course.id,
        frozen=frozen,
    )
    assert withdrawn["available"] is False
    assert withdrawn["reason_code"] == "source_unavailable"
    assert withdrawn["quote"] == frozen["quote"]
    assert withdrawn["route"] == frozen["route"]

    source.processing_status = "ready"
    source_ref.parser_version = "parser-v2"
    source_ref.content_hash = "b" * 64
    session.commit()
    drifted = project_source_ref(session, source_ref.id, actor=member, frozen=frozen)
    assert drifted["available"] is False
    assert drifted["reason_code"] == "source_ref_version_changed"
    assert drifted["parser_version"] == "parser-v1"
    assert drifted["content_hash"] == frozen["contentHash"]

    session.delete(source_ref)
    session.commit()
    removed = project_source_ref(session, "ref-f7t05", actor=member, frozen=frozen)
    assert removed["available"] is False
    assert removed["reason_code"] == "source_ref_missing"
    assert removed["title"] == "梯度下降讲义"
    assert removed["quote"] == frozen["quote"]


def test_selection_projection_keeps_exact_image_region_and_detects_stale_source(source_context) -> None:
    session, _, member, _, _, source, _, selection = source_context
    projection = project_selection(session, member, selection)
    assert projection["available"] is True
    assert projection["selection_id"] == selection.id
    assert projection["selection_type"] == "image"
    assert projection["image_region"] == selection.normalized_rect
    assert projection["quote"] == selection.quote

    source.processed_sha256 = "c" * 64
    session.commit()
    stale = project_selection(session, member, selection)
    assert stale["available"] is False
    assert stale["reason_code"] == "document_version_changed"


def test_m1_reader_chat_and_resource_boundaries_share_one_read_only_projection(source_context) -> None:
    session, _, member, _, course, _, source_ref, selection = source_context
    events_before = session.query(DBLearningEvent).count()
    projection = project_source_ref(session, source_ref.id, actor=member)
    m1_payload = {"id": projection["source_ref_id"], **{
        key: value for key, value in projection.items() if key != "source_ref_id"
    }}
    assert SourceRefDetail.model_validate(m1_payload).route == projection["route"]

    selection_payload = _selection_payload(session, member, selection)
    assert selection_payload["source"]["route"] == projection["route"]
    assert selection_payload["agent_audit"] is None
    selection.answer_status = "ready"
    selection.answer_text = "仅依据当前选区整理。"
    selection.answer_source_ref_id = source_ref.id
    session.flush()
    answered_selection = _selection_payload(session, member, selection)
    assert answered_selection["answer_source"]["route"] == projection["route"]
    assert answered_selection["agent_audit"]["status"] == "completed"
    snapshots = _source_snapshots(
        session,
        course_id=course.id,
        source_ref_ids=[source_ref.id],
        require_available=True,
    )
    assert snapshots == [projection]

    conversation = DBChatConversation(
        id="chat-f7t05",
        owner_public_id=member.public_id,
        course_id=course.id,
        title="来源引用对话",
    )
    frozen_refs = _context_source_refs(
        session,
        member,
        conversation,
        [{"sourceRef": {"id": source_ref.id}}],
    )
    materials = _stream_source_materials(session, member, conversation, frozen_refs)
    assert materials[0]["route"] == projection["route"]
    assert materials[0]["quote"] == projection["quote"]

    message = DBChatMessage(
        id="chatmsg-f7t05",
        conversation_id=conversation.id,
        owner_public_id=member.public_id,
        sequence=1,
        role="assistant",
        status="completed",
        content="回答",
        content_sha256="d" * 64,
        idempotency_key="f7-t05-message-key",
        source_refs=frozen_refs,
    )
    payload = message_payload(message, db=session, actor=member, course_id=course.id)
    assert payload["sourceRefs"][0]["route"] == projection["route"]
    assert session.query(DBLearningEvent).count() == events_before
