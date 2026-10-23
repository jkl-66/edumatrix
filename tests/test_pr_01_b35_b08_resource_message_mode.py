from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.chat_api import MessageInput, _resource_context_values, create_message_pair
from app.competition_demo_seed import seed_competition_demo
from app.database import DBChatConversation, DBChatMessage, DBLearningPath, DBPathNode, DBSourceRef, DBUser
from app.resource_bundles import _public_manifest
from tests.api_test_helpers import auth_headers
from tests.test_f6_t03_code_sandbox_resource import _session


COURSE_ID = "course-machine-learning-foundations-v1"
ROOT = Path(__file__).resolve().parents[1]


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def test_resource_message_fields_are_frozen_and_idempotent() -> None:
    with TestClient(app) as client:
        headers = auth_headers(client, _key("b35-b08"))
        conversation = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": COURSE_ID, "title": "资源消息模式"},
        )
        assert conversation.status_code == 201, conversation.text
        conversation_id = conversation.json()["id"]
        payload = {
            "content": "请帮我生成当前章节的讲义和代码实验",
            "intent": "resource_generation",
            "resource_types": ["handout", "code_sandbox"],
            "context_snapshot_id": "ctx-requested-b08",
            "return_to": "/workspace/resources?course_id=course-machine-learning-foundations-v1",
            "idempotency_key": _key("resource-message"),
        }
        first = client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            headers=headers,
            json=payload,
        )
        assert first.status_code == 201, first.text
        first_body = first.json()
        assistant = first_body["assistantMessage"]
        assert assistant["intent"] == "resource_generation"
        assert assistant["resourceTypes"] == ["handout", "code_sandbox"]
        assert assistant["contextSnapshotId"] == "ctx-requested-b08"
        assert assistant["streamCheckpoint"]["returnTo"].startswith("/workspace/resources")
        assert first_body["userMessage"]["idempotencyKey"] == payload["idempotency_key"]

        retry = client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            headers=headers,
            json=payload,
        )
        assert retry.status_code == 201, retry.text
        retry_body = retry.json()
        assert retry_body["created"] is False
        assert retry_body["userMessage"]["id"] == first_body["userMessage"]["id"]
        assert retry_body["assistantMessage"]["id"] == assistant["id"]


def test_resource_entrypoints_route_to_canonical_chat_message_mode() -> None:
    resource_center = (ROOT / "frontend/src/views/ResourceCenter.vue").read_text(encoding="utf-8")
    learning_path = (ROOT / "frontend/src/views/LearningPathGraph.vue").read_text(encoding="utf-8")
    chat = (ROOT / "frontend/src/views/Chat.vue").read_text(encoding="utf-8")
    router = (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")

    assert "path: '/chat'" in resource_center
    assert "intent: 'resource_generation'" in resource_center
    assert "createM5ResourceGenerationJob" not in resource_center
    assert "executeM5ResourceGeneration" not in resource_center
    assert "path: '/chat'" in learning_path
    assert "intent: 'path_bundle'" in learning_path
    assert "task?.generation_context?.knowledge_point_title" in learning_path
    assert "所属章节" in learning_path
    assert "cleanQueryValue(route.query.knowledge_point_title)" in chat
    assert "createGenerationJob" not in learning_path
    assert "executeGenerationJob" not in learning_path
    assert "resourceMessageIdempotencyKey" in chat
    assert "sendRouteResourceMessage" in chat
    assert "resourceTypes: effectiveResourceTypes.value" in chat
    assert "path: '/chat'" in router
    assert "redirect: (to) => ({ path: '/learn', query: to.query })" in router


def test_path_bundle_schedule_exposes_persistent_node_id_for_chat_context() -> None:
    learning = (ROOT / "app/m5_learning.py").read_text(encoding="utf-8")
    path_view = (ROOT / "frontend/src/views/LearningPathGraph.vue").read_text(encoding="utf-8")

    # The schedule's node_key is a display/stable key (for example
    # textbook-demo-ch-06); path_bundle must submit the persisted DBPathNode
    # identity so resolve_context_ref can authorize the task.
    assert '"node_id": node["id"]' in learning
    assert "task.node_id || task.id" in path_view


def test_path_bundle_context_recovers_parent_path_id_from_persistent_task() -> None:
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        node = session.query(DBPathNode).filter_by(id="demo-task-lzz-read-01").one()
        path = session.get(DBLearningPath, node.learning_path_id)
        source = session.get(DBSourceRef, "demo-ref-06")
        assert path is not None and source is not None
        conversation = DBChatConversation(
            owner_public_id=learner.public_id,
            course_id="demo-course-rag-trust-v1",
            title="B29 path context",
        )
        session.add(conversation)
        session.commit()
        pair = create_message_pair(
            session,
            learner,
            conversation.id,
            MessageInput(
                content="请一键生成向量检索资源包",
                idempotency_key=_key("b29-path-context"),
                intent="path_bundle",
                resource_types=["handout", "mind_map"],
                context_refs=[{
                    "courseId": "demo-course-rag-trust-v1",
                    "knowledgePointId": "demo-kp-06",
                    "taskId": node.id,
                    "sourceRefId": source.id,
                }],
            ),
        )
        assistant = session.get(DBChatMessage, pair["assistantMessage"]["id"])
        values = _resource_context_values(session, assistant, conversation)
        assert values["task_id"] == node.id
        assert values["path_id"] == path.id
    finally:
        session.close()
        engine.dispose()


def test_public_resource_manifest_projects_frozen_path_context() -> None:
    result = _public_manifest({
        "course_id": COURSE_ID,
        "exam_gate": {
            "path_id": "path-frozen-01",
            "selected_task_id": "node-frozen-01",
        },
    })

    assert result["path_id"] == "path-frozen-01"
    assert result["task_id"] == "node-frozen-01"


def test_route_resource_idempotency_is_scoped_to_initialized_chat_conversation() -> None:
    chat = (ROOT / "frontend/src/views/Chat.vue").read_text(encoding="utf-8")
    assert "const conversationId = String(chatStore.activeConversationId || '').trim() || 'pending'" in chat
    assert "return `${requested}:${conversationId}`.slice(0, 128)" in chat
