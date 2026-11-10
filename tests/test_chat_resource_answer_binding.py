"""An answer selected in Chat remains the input through background generation."""
import json

import pytest
from fastapi import HTTPException

from app.chat_api import MessageInput, create_message_pair, execute_resource_chat_run, submit_message_request
from app.competition_demo_seed import seed_competition_demo
from app.database import DBChatConversation, DBChatMessage, DBUser
from app.resource_bundles import _real_model_prompt, _generation_manifest
from tests.test_f6_t03_code_sandbox_resource import _session


@pytest.fixture
def chat():
    engine, db = _session()
    seed_competition_demo(db)
    actor = db.query(DBUser).filter_by(username="lzz").one()
    conversation = DBChatConversation(owner_public_id=actor.public_id,
        course_id="demo-course-rag-trust-v1", title="选择历史回答")
    db.add(conversation)
    db.commit()
    yield db, actor, conversation
    db.close()
    engine.dispose()


def answer(db, actor, conversation, key, question, text, point="demo-kp-07", source="demo-ref-07"):
    pair = create_message_pair(db, actor, conversation.id, MessageInput(
        content=question, idempotency_key=key, intent="course_qa",
        context_refs=[{"courseId": conversation.course_id, "knowledgePointId": point, "sourceRefId": source}]))
    row = db.get(DBChatMessage, pair["assistantMessage"]["id"])
    row.content, row.status = text, "completed"
    db.commit()
    return row


def test_selected_older_answer_reaches_generation_and_retry_unchanged(chat):
    db, actor, conversation = chat
    original = answer(db, actor, conversation, "original-question", "原问题：计算这三行数据的MSE。",
                      "逐行数据与推导。" * 90 + "末行：[3, 2.5]，平方误差0.25。")
    answer(db, actor, conversation, "unrelated-question", "改聊嵌入模型", "这一条不能成为资源输入",
           "demo-kp-06", "demo-ref-06")
    payload = MessageInput(content="基于这条回答生成讲义和测验", idempotency_key="selected-answer-resource",
        intent="resource_generation", resource_types=["handout", "quiz"], source_message_id=original.id,
        context_refs=[{"courseId": conversation.course_id, "knowledgePointId": "demo-kp-06", "sourceRefId": "demo-ref-06"}])
    pair = submit_message_request(db, actor, conversation.id, payload)
    # POST itself dispatches; no SSE connection is opened by this test.
    assert pair["assistantMessage"]["resourceJobId"]
    retry = submit_message_request(db, actor, conversation.id, payload)
    assert retry["created"] is False
    assert retry["assistantMessage"]["id"] == pair["assistantMessage"]["id"]
    frozen = pair["assistantMessage"]["streamCheckpoint"]["conversationSource"]
    assert frozen["answer"] == original.content
    assert frozen["question"] == "原问题：计算这三行数据的MSE。"
    assert pair["assistantMessage"]["contextSnapshot"]["knowledge_scope"] == ["demo-kp-07"]
    submitted = execute_resource_chat_run(db, actor, pair["assistantMessage"]["id"])
    job = submitted["job"]
    assert job["automation"]["state"] == "queued"
    assert "准备" in submitted["message"]["content"]
    assert "已准备好" not in submitted["message"]["content"]
    assert execute_resource_chat_run(db, actor, pair["assistantMessage"]["id"])["job"]["job_id"] == job["job_id"]
    manifest = _generation_manifest(db, job["job_id"])
    assert job["knowledge_point_id"] == "demo-kp-07"
    assert all(item["source_ref_ids"] == ["demo-ref-07"] for item in manifest["items"])
    assert manifest["context"]["conversation_source"] == frozen
    assert manifest["input_snapshot"]["conversation_source"] == frozen
    # Later review requirements must not erase the original question or data.
    manifest["active_requirements"] = {"learning_goal": "修正一处数值", "shared": [], "by_resource": {}}
    _, prompt = _real_model_prompt(resource_type="handout", item=manifest["items"][0], manifest=manifest,
        source_snapshots=manifest["input_snapshot"]["source_snapshots"]["handout"])
    assert json.loads(prompt)["course"]["conversation_source"] == frozen
    assert "这一条不能成为资源输入" not in prompt
    payload.source_message_id = pair["assistantMessage"]["id"]
    with pytest.raises(HTTPException):
        create_message_pair(db, actor, conversation.id, payload)


def test_answer_binding_rejects_other_conversation_and_unfinished_answer(chat):
    db, actor, conversation = chat
    original = answer(db, actor, conversation, "ownership-question", "问题", "回答")
    other = DBChatConversation(owner_public_id=actor.public_id, course_id=conversation.course_id)
    db.add(other)
    db.commit()
    payload = MessageInput(content="生成讲义", idempotency_key="ownership-resource", intent="resource_generation",
                           resource_types=["handout"], source_message_id=original.id)
    with pytest.raises(HTTPException) as conflict:
        create_message_pair(db, actor, other.id, payload)
    assert conflict.value.detail["code"] == "chat_resource_conversation_conflict"
    original.status = "streaming"
    db.commit()
    with pytest.raises(HTTPException) as unfinished:
        create_message_pair(db, actor, conversation.id, payload)
    assert unfinished.value.detail["code"] == "chat_resource_answer_incomplete"
