from __future__ import annotations

import asyncio
import json
import pytest

from app.chat_api import MessageInput, create_message_pair, execute_resource_chat_run, message_payload
from app.competition_demo_seed import seed_competition_demo
from app.database import DBChatConversation, DBChatMessage, DBKnowledgePoint, DBProfileSnapshot, DBSourceRef, DBUser
from app.resource_bundles import GENERATION_RESOURCE_TYPES
from tests.test_f6_t03_code_sandbox_resource import _session


# Reuse the current full resource contract; these tests exercise chat orchestration.
from tests.test_pr_01_b35_b09_resource_supervisor import _SupervisorBackend, _fake_web_video_search

class _Backend(_SupervisorBackend):
    pass


@pytest.fixture(autouse=True)
def complete_projected_job(monkeypatch):
    # These tests cover terminal content/event projections with a fake model.
    # Dispatch/leases and the real queued handoff are tested separately in
    # test_generation_dispatch and test_chat_resource_answer_binding.
    from app.resource_bundles import execute_generation_job
    monkeypatch.setattr("app.generation_dispatch.submit_resource_job", execute_generation_job)


@pytest.mark.parametrize("selected", [["handout"], ["handout", "code_sandbox"]])
def test_rejected_resources_never_claim_completed_learning_materials(monkeypatch, selected):
    backend = _Backend(review_approved=False)
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        conversation = DBChatConversation(owner_public_id=learner.public_id,
                                          course_id="demo-course-rag-trust-v1", title="审核失败反馈")
        session.add(conversation)
        session.commit()
        pair = create_message_pair(session, learner, conversation.id, MessageInput(
            content="请生成学习内容", idempotency_key="review-rejected-chat",
            intent="resource_generation", resource_types=selected,
            context_refs=[{"courseId": conversation.course_id, "knowledgePointId": "demo-kp-07", "sourceRefId": "demo-ref-07"}]))
        result = execute_resource_chat_run(session, learner, pair["assistantMessage"]["id"])
        assert all('并做一次简短回顾' not in item['completion_rule'] for item in result['job']['items'])
        if 'code_sandbox' in selected:
            code_item = next(item for item in result['job']['items'] if item['type'] == 'code_sandbox')
            assert '必需检查' in code_item['completion_rule']
        assert result["job"]["status"] == ("failed" if len(selected) == 1 else "partial_success")
        assert result["message"]["status"] == "failed"
        assert "重试" in result["message"]["content"]
        assert "已按你的学习情况" not in result["message"]["content"]
        assert all(link["status"] != "completed" for link in result["resource_links"])
        assert all("/bundles/" in link["route"] for link in result["resource_links"])
        assert all("resourceType" not in event["summary"] for event in result["run_events"])

        row = session.get(DBChatMessage, pair["assistantMessage"]["id"])
        row.content = "资源生成已完成：成功 0 项，失败 1 项。\n\n本轮已按你的学习情况组织内容。"
        row.status = "completed"
        row.stream_checkpoint = {**row.stream_checkpoint, "resourceStatus": "partial_success", "runEvents": [
            {"summary": '内容仍需调整。具体审核意见：[{"resourceType": "handout", "severity":'}]}
        before = json.dumps(row.stream_checkpoint, ensure_ascii=False)
        visible = message_payload(row)
        assert visible["status"] == "failed" and visible["resourceStatus"] == "failed"
        assert "成功 0" not in visible["content"] and "已按" not in visible["content"]
        assert visible["runEvents"][0]["summary"] == "内容仍需调整。"
        assert json.dumps(row.stream_checkpoint, ensure_ascii=False) == before
        assert row.content.startswith("资源生成已完成")
    finally:
        session.close()
        engine.dispose()


def test_chat_recovers_resource_result_after_retry_from_another_page(monkeypatch):
    from app.resource_bundles import retry_generation_item, execute_generation_job
    backend = _Backend(review_approved=False)
    monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: backend)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        conversation = DBChatConversation(owner_public_id=learner.public_id,
            course_id="demo-course-rag-trust-v1", title="跨页重试")
        session.add(conversation)
        session.commit()
        pair = create_message_pair(session, learner, conversation.id, MessageInput(
            content="请生成学习讲义", idempotency_key="retry-from-resource-page", intent="resource_generation",
            resource_types=["handout"], context_refs=[{"courseId": conversation.course_id,
                "knowledgePointId": "demo-kp-07", "sourceRefId": "demo-ref-07"}]))
        failed = execute_resource_chat_run(session, learner, pair["assistantMessage"]["id"])
        row = session.get(DBChatMessage, pair["assistantMessage"]["id"])
        original_content = row.content
        original_checkpoint = json.dumps(row.stream_checkpoint, ensure_ascii=False)
        retry_generation_item(session, learner, failed["job"]["job_id"], "handout")
        backend.review_approved = True
        completed = execute_generation_job(session, learner, failed["job"]["job_id"])
        visible = message_payload(row, db=session, actor=learner, course_id=conversation.course_id)
        assert visible["status"] == "completed" and visible["resourceStatus"] == "succeeded"
        assert "已准备好" in visible["content"] and visible["failure"] is None
        assert visible["resourceLinks"][0]["resourceVersionId"] == completed["items"][0]["resource"]["version"]["id"]
        assert visible["agentAudit"]["status"] == "completed"
        assert any(event["eventType"] == "run.failed" for event in visible["runEvents"])
        assert any(event["eventType"] == "publish.completed" for event in visible["runEvents"])
        assert row.status == "failed" and row.content == original_content
        assert json.dumps(row.stream_checkpoint, ensure_ascii=False) == original_checkpoint
    finally:
        session.close()
        engine.dispose()


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
        assert result["job"]["manifest"]["user_instruction"] == "请生成完整资源包"
        assert result["job"]["context"]["learning_goal"] == "请生成完整资源包"
        point_title = session.get(DBKnowledgePoint, "demo-kp-07").title
        assert all(item["title"].endswith(point_title) for item in result["job"]["items"])
        assert all("请生成完整资源包" not in item["title"] for item in result["job"]["items"])
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
        # Worker events are restored from the job; HTTP no longer owns a
        # synchronous generation callback.
        projected = result["run_events"]
        assert any(item["eventType"] == "resource.item.started" for item in projected)
        assert any(item["eventType"] == "resource.item.completed" for item in projected)
        assert projected[-1]["eventType"] in {"publish.completed", "run.completed"}
        assert all("prompt" not in item and "reasoning_content" not in item for item in projected)
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
