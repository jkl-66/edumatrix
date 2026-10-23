from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.chat_api import (
    ConversationInput,
    MessageInput,
    _chat_course_catalog,
    _resolve_contexts,
    conversation_payload,
    create_message_pair,
)
from app.database import (
    Base,
    DBChatConversation,
    DBCourse,
    DBCourseMembership,
    DBUser,
)
from app.schemas import ContextRef


@pytest.fixture()
def db_and_users():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()
    learner = DBUser(
        public_id="usr-b31-learner",
        username="b31-learner",
        hashed_password="test",
        role="student",
        display_name="B31 learner",
    )
    owner = DBUser(
        public_id="usr-b31-owner",
        username="b31-owner",
        hashed_password="test",
        role="student",
        display_name="B31 owner",
    )
    db.add_all([learner, owner])
    db.flush()
    courses = [
        DBCourse(
            id="b31-public",
            version="v1",
            title="公开课程",
            subject="基础",
            visibility="public",
            status="published",
            owner_public_id=owner.public_id,
            manifest_version="manifest-public-v1",
        ),
        DBCourse(
            id="b31-member",
            version="v2",
            title="成员课程",
            subject="工程",
            visibility="private",
            status="published",
            owner_public_id=owner.public_id,
            manifest_version="manifest-member-v2",
        ),
        DBCourse(
            id="b31-denied",
            version="v1",
            title="无权限课程",
            subject="私有",
            visibility="private",
            status="published",
            owner_public_id=owner.public_id,
            manifest_version="manifest-denied-v1",
        ),
        DBCourse(
            id="b31-archived",
            version="v1",
            title="归档课程",
            subject="历史",
            visibility="public",
            status="archived",
            owner_public_id=owner.public_id,
            manifest_version="manifest-archived-v1",
        ),
    ]
    db.add_all(courses)
    db.add(
        DBCourseMembership(
            course_id="b31-member",
            user_public_id=learner.public_id,
            role="student",
            status="active",
        )
    )
    db.commit()
    try:
        yield db, learner
    finally:
        db.close()
        Base.metadata.drop_all(engine)


def _conversation(db, learner, course_id="b31-public"):
    row = DBChatConversation(
        owner_public_id=learner.public_id,
        course_id=course_id,
        title="B31 对话",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _message_payload(key: str, *course_ids: str) -> MessageInput:
    return MessageInput(
        content=f"问题 {key}",
        context_refs=[ContextRef(courseId=course_id) for course_id in course_ids],
        idempotency_key=f"b31-message-{key}",
    )


def test_chat_course_catalog_only_returns_readable_usable_courses(db_and_users):
    db, learner = db_and_users
    catalog = _chat_course_catalog(db, learner)
    ids = [item["id"] for item in catalog]
    assert ids == ["b31-public", "b31-member"]
    assert "b31-denied" not in ids
    assert "b31-archived" not in ids


def test_conversation_input_accepts_single_multi_and_general_context():
    assert ConversationInput(course_id="b31-public").course_ids == ()
    assert ConversationInput(course_ids=("b31-public", "b31-member")).course_ids == (
        "b31-public",
        "b31-member",
    )
    assert ConversationInput().course_id is None


def test_multicourse_message_freezes_context_and_switch_does_not_rewrite_history(db_and_users):
    db, learner = db_and_users
    conversation = _conversation(db, learner)

    first = create_message_pair(
        db,
        learner,
        conversation.id,
        _message_payload("first", "b31-public", "b31-member"),
    )
    first_context = first["userMessage"]["contextRefs"]
    assert [item["course"]["id"] for item in first_context] == ["b31-public", "b31-member"]

    second = create_message_pair(
        db,
        learner,
        conversation.id,
        _message_payload("second", "b31-member"),
    )
    assert [item["course"]["id"] for item in second["userMessage"]["contextRefs"]] == ["b31-member"]

    recovered = conversation_payload(db, conversation, actor=learner)
    assert recovered["courseIds"] == ["b31-member"]
    messages = recovered["messages"]
    assert [item["course"]["id"] for item in messages[0]["contextRefs"]] == ["b31-public", "b31-member"]
    assert [item["course"]["id"] for item in messages[2]["contextRefs"]] == ["b31-member"]

    generic = create_message_pair(
        db,
        learner,
        conversation.id,
        MessageInput(content="通用问题", context_refs=[], idempotency_key="b31-message-generic"),
    )
    assert generic["userMessage"]["contextRefs"] == []
    recovered_generic = conversation_payload(db, conversation, actor=learner)
    assert recovered_generic["courseIds"] == []
    assert recovered_generic["contextMode"] == "general"
    assert [item["course"]["id"] for item in recovered_generic["messages"][0]["contextRefs"]] == [
        "b31-public",
        "b31-member",
    ]


def test_unauthorized_and_archived_course_contexts_are_rejected_without_message_write(db_and_users):
    db, learner = db_and_users
    conversation = _conversation(db, learner)
    before = db.query(DBChatConversation).count()

    with pytest.raises(HTTPException) as denied:
        _resolve_contexts(
            db,
            learner,
            conversation,
            [ContextRef(courseId="b31-denied")],
        )
    assert denied.value.status_code == 403

    with pytest.raises(HTTPException) as archived:
        _resolve_contexts(
            db,
            learner,
            conversation,
            [ContextRef(courseId="b31-archived")],
        )
    assert archived.value.status_code == 409
    assert db.query(DBChatConversation).count() == before


def test_frontend_multicourse_contract_and_general_route_are_explicit():
    root = Path(__file__).resolve().parents[1]
    chat = (root / "frontend/src/views/Chat.vue").read_text(encoding="utf-8")
    router = (root / "frontend/src/router/index.js").read_text(encoding="utf-8")
    app = (root / "frontend/src/App.vue").read_text(encoding="utf-8")
    for marker in (
        'data-testid="chat-course-picker"',
        'data-testid="chat-current-course-label"',
        'conversation-course',
        "course_ids",
        "通用对话（未绑定课程）",
        "课程只影响后续新消息",
        "courseContext.setChatCourseIds",
    ):
        assert marker in chat
    assert "courseScoped: false" in router
    assert "route.path !== '/learn'" in app
