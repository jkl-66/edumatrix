from __future__ import annotations

import asyncio
import json

from app.chat_api import MessageInput, create_message_pair, execute_resource_chat_run
from app.competition_demo_seed import seed_competition_demo
from app.database import DBChatConversation, DBProfileSnapshot, DBSourceRef, DBUser
from app.resource_bundles import GENERATION_RESOURCE_TYPES
from tests.test_f6_t03_code_sandbox_resource import _session


class _Backend:
    model = "deepseek-v4-flash"
    provider = "openai"

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        await asyncio.sleep(0)
        if role == "resource_planner":
            return json.dumps({
                "summary": "共享资源计划",
                "plan": "依据冻结课程来源规划九类资源，并在审核后发布。",
                "resourceBriefs": [],
            }, ensure_ascii=False)
        if role == "resource_reviewer":
            return json.dumps({"approved": True, "summary": "审核通过", "findings": [], "rejectedTypes": []})
        return json.dumps({
            "summary": "资源候选",
            "learningGoal": "完成课程目标",
            "narrative": "依据冻结课程来源组织资源内容。",
            "practiceSteps": [],
            "starterCode": "print('ok')",
            "observationPrompt": "观察参数变化",
            "quizQuestions": [
                {"prompt": f"题{i}", "options": ["选项一", "选项二", "选项三", "选项四"], "answer": "A", "explanation": "解析", "bloom": "remember", "difficulty": 0.3}
                for i in range(1, 4)
            ],
        }, ensure_ascii=False)


def test_resource_chat_uses_one_job_and_projects_events(monkeypatch):
    backend = _Backend()
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        conversation = DBChatConversation(
            owner_public_id=learner.public_id,
            course_id="demo-course-rag-trust-v1",
            title="B10 resource chat",
        )
        session.add(conversation)
        session.commit()
        pair = create_message_pair(
            session,
            learner,
            conversation.id,
            MessageInput(
                content="请生成完整资源包",
                idempotency_key="b10-resource-chat-001",
                intent="resource_generation",
                resource_types=list(GENERATION_RESOURCE_TYPES),
                context_refs=[{
                    "courseId": "demo-course-rag-trust-v1",
                    "knowledgePointId": "demo-kp-07",
                    "sourceRefId": source.id,
                }],
            ),
        )
        result = execute_resource_chat_run(session, learner, pair["assistantMessage"]["id"])
        assert result["job"]["manifest"]["conversation_id"] == conversation.id
        assert result["job"]["manifest"]["message_id"] == pair["assistantMessage"]["id"]
        assert result["job"]["status"] == "succeeded"
        events = result["run_events"]
        event_types = [item["eventType"] for item in events]
        assert "resource.item.started" in event_types
        assert "resource.item.completed" in event_types
        assert "review_gate.passed" in event_types
        assert "publish.completed" in event_types
        assert all(item["runId"] == pair["assistantMessage"]["runId"] for item in events)
        assert len(result["resource_links"]) == len(GENERATION_RESOURCE_TYPES)
    finally:
        session.close()
        engine.dispose()


def test_resource_chat_accepts_multi_select_subset_and_stream_callback(monkeypatch):
    backend = _Backend()
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        source = session.get(DBSourceRef, "demo-ref-07")
        conversation = DBChatConversation(
            owner_public_id=learner.public_id,
            course_id="demo-course-rag-trust-v1",
            title="B10 subset resource chat",
        )
        session.add(conversation)
        session.commit()
        selected = ["handout", "code_sandbox", "video"]
        pair = create_message_pair(
            session,
            learner,
            conversation.id,
            MessageInput(
                content="请生成讲义、代码实验和视频推荐",
                idempotency_key="b10-resource-chat-subset-001",
                intent="resource_generation",
                resource_types=selected,
                context_refs=[{
                    "courseId": "demo-course-rag-trust-v1",
                    "knowledgePointId": "demo-kp-07",
                    "sourceRefId": source.id,
                }],
            ),
        )
        observed = []
        result = execute_resource_chat_run(
            session,
            learner,
            pair["assistantMessage"]["id"],
            event_callback=observed.append,
        )
        assert result["job"]["status"] == "succeeded"
        assert [item["type"] for item in result["job"]["items"]] == selected
        assert len(result["resource_links"]) == len(selected)
        assert observed
        assert observed[0]["event_type"] in {"stage.completed", "stage.started"}
        assert any(item["event_type"] == "resource.item.started" for item in observed)
        assert any(item["event_type"] == "resource.item.completed" for item in observed)
        assert observed[-1]["event_type"] in {"publish.completed", "run.completed"}
        assert all("prompt" not in item and "reasoning_content" not in item for item in observed)
    finally:
        session.close()
        engine.dispose()


def test_resource_chat_accepts_course_scope_without_knowledge_point(monkeypatch):
    backend = _Backend()
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        source = session.get(DBSourceRef, "demo-ref-07")
        conversation = DBChatConversation(
            owner_public_id=learner.public_id,
            course_id="demo-course-rag-trust-v1",
            title="B16 course scope resource chat",
        )
        session.add(conversation)
        session.commit()
        pair = create_message_pair(
            session,
            learner,
            conversation.id,
            MessageInput(
                content="请基于当前课程资料生成一份课程级讲义，不绑定单一知识点",
                idempotency_key="b16-course-scope-resource-001",
                intent="resource_generation",
                resource_types=["handout"],
                context_refs=[{
                    "courseId": "demo-course-rag-trust-v1",
                    "sourceRefId": source.id,
                }],
            ),
        )
        result = execute_resource_chat_run(session, learner, pair["assistantMessage"]["id"])
        assert result["job"]["knowledge_point_id"] is None
        assert result["job"]["context"]["knowledge_point_title"] == "当前课程内容"
        assert result["job"]["status"] == "succeeded"
        assert result["job"]["items"][0]["state"] == "succeeded"
    finally:
        session.close()
        engine.dispose()
