from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent_audit import (
    assert_public_audit_is_sanitized,
    build_chat_agent_audit,
    build_selection_agent_audit,
)
from app.chat_api import (
    begin_stream_message,
    complete_stream_message,
    fail_stream_message,
    message_payload,
    persist_stream_content,
)
from app.database import (
    Base,
    DBAgentRun,
    DBChatConversation,
    DBChatMessage,
    DBGenerationTask,
    DBLearningEvent,
    DBUser,
)


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'f7-t05-agent-audit.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def _message(*, message_id: str, owner_id: str, conversation_id: str, sequence: int, status: str, content: str = ""):
    return DBChatMessage(
        id=message_id,
        conversation_id=conversation_id,
        owner_public_id=owner_id,
        sequence=sequence,
        role="assistant",
        status=status,
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        idempotency_key=f"key-{message_id}",
        source_refs=[{
            "kind": "canonical_source",
            "sourceRefId": "ref-f7t05",
            "available": True,
        }],
        attachment_ids=["attachment-f7t05"],
        stream_checkpoint={"status": status},
    )


def test_chat_audit_builder_uses_four_truthful_sanitized_stages() -> None:
    queued = build_chat_agent_audit(
        message_id="chatmsg-queued",
        status="queued",
        input_refs={
            "sources": ["source:ref-1"],
            "system_prompt": "hidden",
            "raw_trace": "hidden",
            "reasoning_content": "hidden",
        },
        source_count=1,
        attachment_count=0,
    )
    assert [item["role"] for item in queued["items"]] == ["analysis", "generation", "validation", "decision"]
    assert [item["status"] for item in queued["items"]] == ["completed", "pending", "pending", "pending"]
    assert queued["status"] == "pending"

    failed = build_chat_agent_audit(
        message_id="chatmsg-failed",
        status="failed",
        input_refs=["source:ref-1"],
        source_count=1,
        received_characters=17,
        failure_message="provider failed; api_key=sk-never-return; reasoning_content hidden",
        historical_result={
            "label": "历史已完成回答（非本次结果）",
            "messageId": "chatmsg-old",
            "preview": "旧回答",
            "route": "/learn?message_id=chatmsg-old",
            "raw_log": "must not pass",
        },
    )
    assert failed["status"] == "failed"
    assert [item["status"] for item in failed["items"]] == ["completed", "failed", "pending", "pending"]
    assert failed["historicalResult"]["label"] == "历史已完成回答（非本次结果）"
    assert set(failed["historicalResult"]) == {"label", "messageId", "preview", "route"}
    assert_public_audit_is_sanitized(failed)

    selection_ready = build_selection_agent_audit(
        selection_id="sel-ready",
        source_ref_id="ref-1",
        answer_status="ready",
        has_evidence=True,
    )
    selection_failed = build_selection_agent_audit(
        selection_id="sel-failed",
        source_ref_id="ref-1",
        answer_status="failed",
        has_evidence=False,
    )
    assert all(item["status"] == "completed" for item in selection_ready["items"])
    assert [item["status"] for item in selection_failed["items"]] == [
        "completed", "failed", "pending", "pending",
    ]
    assert_public_audit_is_sanitized(selection_ready)
    assert_public_audit_is_sanitized(selection_failed)


def test_chat_stream_persists_audit_and_keeps_failed_run_separate_from_history(tmp_path) -> None:
    engine, session = _session(tmp_path)
    try:
        actor = DBUser(
            public_id="usr-f7t05-audit",
            username="f7t05_audit",
            hashed_password="x",
            role="student",
        )
        conversation = DBChatConversation(
            id="chat-f7t05-audit",
            owner_public_id=actor.public_id,
            title="审计对话",
        )
        previous = _message(
            message_id="chatmsg-f7t05-previous",
            owner_id=actor.public_id,
            conversation_id=conversation.id,
            sequence=2,
            status="completed",
            content="这是之前已经完成的回答。",
        )
        previous.completed_at = datetime(2026, 8, 15, 12, 0, 0)
        current = _message(
            message_id="chatmsg-f7t05-current",
            owner_id=actor.public_id,
            conversation_id=conversation.id,
            sequence=4,
            status="queued",
        )
        session.add_all([actor, conversation, previous, current])
        session.commit()
        protected_before = {
            "events": session.query(DBLearningEvent).count(),
            "tasks": session.query(DBGenerationTask).count(),
            "runs": session.query(DBAgentRun).count(),
        }

        running = begin_stream_message(session, actor, current.id)
        assert running.stream_checkpoint["agentAudit"]["status"] == "running"
        assert [item["status"] for item in running.stream_checkpoint["agentAudit"]["items"]] == [
            "completed", "running", "pending", "pending",
        ]
        partial = persist_stream_content(session, actor, current.id, "本次回答只完成了一部分")
        assert "已保存 11 个字符" in partial.stream_checkpoint["agentAudit"]["items"][1]["candidateSummary"]
        failed = fail_stream_message(
            session,
            actor,
            current.id,
            "chat_stream_provider_failed",
            "模型暂时不可用；raw_trace=hidden",
        )
        audit = failed.stream_checkpoint["agentAudit"]
        assert failed.status == "failed"
        assert failed.content == "本次回答只完成了一部分"
        assert audit["status"] == "failed"
        assert audit["historicalResult"]["messageId"] == previous.id
        assert audit["historicalResult"]["label"] == "历史已完成回答（非本次结果）"
        assert previous.content not in failed.content
        assert_public_audit_is_sanitized(audit)

        completed_row = _message(
            message_id="chatmsg-f7t05-completed",
            owner_id=actor.public_id,
            conversation_id=conversation.id,
            sequence=6,
            status="queued",
        )
        session.add(completed_row)
        session.commit()
        begin_stream_message(session, actor, completed_row.id)
        completed = complete_stream_message(
            session,
            actor,
            completed_row.id,
            content="根据课程原文可得该结论。[S1]",
        )
        complete_audit = message_payload(completed)["agentAudit"]
        assert complete_audit["status"] == "completed"
        assert all(item["status"] == "completed" for item in complete_audit["items"])
        assert "显式引用标记" in complete_audit["items"][2]["validation"]
        assert {
            "events": session.query(DBLearningEvent).count(),
            "tasks": session.query(DBGenerationTask).count(),
            "runs": session.query(DBAgentRun).count(),
        } == protected_before
    finally:
        session.close()
        engine.dispose()
