from __future__ import annotations

import asyncio
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent_audit import (
    assert_public_audit_is_sanitized,
    build_chat_agent_audit,
    public_agent_audit_payload,
)
from app.database import Base, DBArtifact, DBArtifactVersion, DBAgentRun
from app.m3_agents import (
    M3AgentRole,
    complete_m3_agent_run,
    create_m3_collaboration_task,
    fail_m3_agent_run,
    start_m3_agent_run,
    start_m3_collaboration_task,
)
from app.m3_baseline import seed_m3_profile_baselines
from app.m3_resources import M3PersonalizedResourceGenerator, persist_m3_resource_bundle
from tests.test_m3_resources import ProfileAwareFakeLLM


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_real_resource_run_public_summary_binds_task_trace_and_version():
    engine, session = _session()
    try:
        fixture = seed_m3_profile_baselines(session).fixtures[0]
        context = fixture.generation_context
        task, _ = create_m3_collaboration_task(session, context=context, idempotency_key="pr10-binding")
        start_m3_collaboration_task(session, task_id=task.id, owner_public_id=context.owner_public_id)
        diagnosis = start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DIAGNOSIS)
        complete_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DIAGNOSIS)
        start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DOMAIN_GENERATION)
        bundle = asyncio.run(M3PersonalizedResourceGenerator(ProfileAwareFakeLLM()).generate(session, context=context, task_id=task.id))
        manifest, manifest_version, _, _ = persist_m3_resource_bundle(session, task_id=task.id, context=context, bundle=bundle)
        session.commit()

        audit = public_agent_audit_payload(session, task_id=task.id, owner_public_id=context.owner_public_id)
        diagnosis_item, generation_item = audit["items"][-2:]
        assert f"task:{task.id}" in diagnosis_item["inputRefs"]
        assert f"run:{diagnosis.id}" in diagnosis_item["inputRefs"]
        assert f"trace:{task.trace_id}" in generation_item["inputRefs"]
        assert f"version:{manifest_version.id}" in generation_item["inputRefs"]
        assert manifest.current_version_id == manifest_version.id
        assert_public_audit_is_sanitized(audit)
    finally:
        session.close()
        engine.dispose()


def test_failed_model_stage_is_explicit_and_retry_keeps_history_separate():
    engine, session = _session()
    try:
        fixture = seed_m3_profile_baselines(session).fixtures[0]
        context = fixture.generation_context
        task, _ = create_m3_collaboration_task(session, context=context, idempotency_key="pr10-fallback")
        start_m3_collaboration_task(session, task_id=task.id, owner_public_id=context.owner_public_id)
        first = start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DIAGNOSIS)
        fail_m3_agent_run(
            session,
            task_id=task.id,
            owner_public_id=context.owner_public_id,
            role=M3AgentRole.DIAGNOSIS,
            error_code="model_unavailable",
            error_message="provider unavailable; api_key=sk-private-value",
        )
        second = start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DIAGNOSIS)
        assert second.id != first.id
        assert second.parent_run_id == first.id
        complete_m3_agent_run(
            session,
            task_id=task.id,
            owner_public_id=context.owner_public_id,
            role=M3AgentRole.DIAGNOSIS,
            candidate_summary="deterministic_local retry completed with bounded evidence.",
        )
        session.commit()
        audit = public_agent_audit_payload(session, task_id=task.id, owner_public_id=context.owner_public_id)
        assert [item["status"] for item in audit["items"]][-2:] == ["failed", "completed"]
        assert "model_unavailable" in audit["items"][-2]["validation"]
        assert "sk-private-value" not in json.dumps(audit, ensure_ascii=False)
        assert_public_audit_is_sanitized(audit)
    finally:
        session.close()
        engine.dispose()


def test_chat_audit_uses_one_stable_run_and_never_claims_later_stages_before_completion():
    audit = build_chat_agent_audit(
        message_id="chatmsg-pr10",
        status="failed",
        input_refs={"source_ids": ["source:1"], "system_prompt": "private"},
        source_count=1,
        failure_message="model unavailable; raw_trace=private",
    )
    assert audit["runId"] == "chat-audit-chatmsg-pr10"
    assert [item["status"] for item in audit["items"]] == ["completed", "failed", "pending", "pending"]
    assert all("run:chat-audit-chatmsg-pr10" in item["inputRefs"] for item in audit["items"][:2])
    assert audit["items"][2]["inputRefs"] == []
    encoded = json.dumps(audit, ensure_ascii=False).lower()
    assert "system_prompt" not in encoded
    assert "raw_trace" not in encoded
    assert_public_audit_is_sanitized(audit)


def test_chat_without_sources_is_an_unreviewed_risk_draft_and_without_run_has_no_completed_stage():
    audit = build_chat_agent_audit(message_id="chatmsg-no-source", status="completed", source_count=0)
    assert all(item["status"] == "completed" for item in audit["items"][:2])
    assert "未审核草稿" in audit["items"][2]["validation"]
    assert "未审核" in audit["items"][3]["decisionSummary"]

    no_run = build_chat_agent_audit(message_id="chatmsg-no-run", status="completed", has_real_run=False)
    assert no_run["status"] == "pending"
    assert all(item["status"] == "pending" for item in no_run["items"])
    assert all(item["inputRefs"] == [] for item in no_run["items"])

    deterministic = build_chat_agent_audit(
        message_id="chatmsg-deterministic",
        status="completed",
        execution_mode="deterministic_local",
        source_count=1,
    )
    assert "deterministic_local" in deterministic["items"][1]["candidateSummary"]
