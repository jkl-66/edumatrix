from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.path_draft as path_draft
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBLearningEvent,
    DBModelCall,
    DBPlanDraft,
    DBProfileSnapshot,
    DBUser,
)
from app.m5_capabilities import Capability, M5CapabilityError
from app.m5_gateway import GatewayResult
from app.m5_learning import PlanSpec, confirm_plan


COURSE_ID = "demo-course-rag-trust-v1"


class _RealPathBackend:
    provider = "openai"
    model = "deepseek-v4-flash"
    thinking_mode = "enabled"
    reasoning_effort = "max"


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    seed_competition_demo(session)
    return engine, session


def _model_payload(session, profile_id: str, *, short: bool = False, node_count: int | None = None) -> dict:
    facts = path_draft._course_facts(session, course_id=COURSE_ID)
    chapters = facts["chapters"][:node_count if node_count is not None else (1 if short else 2)]
    nodes = []
    for index, chapter in enumerate(chapters):
        nodes.append({
            "node_key": f"model-{profile_id[-6:]}-{chapter.id}",
            "node_type": "chapter",
            "target_object_id": chapter.id,
            "title": chapter.title,
            "prerequisites": [],
            "resource_status": "existing",
            "estimate_min_minutes": 20,
            "estimate_max_minutes": 25,
            "difficulty": round(0.35 + index * 0.1, 3),
            "rationale": f"依据画像 {profile_id} 的初始证据，安排该课程节点。",
        })
    return {
        "plan": {
            "schema_version": "m5.plan.v1",
            "goal": f"画像 {profile_id} 的诊断后学习目标",
            "deadline": None,
            "assumptions": ["只使用当前课程和已授权来源"],
            "nodes": nodes,
        },
        "personalization_summary": f"模型根据画像 {profile_id} 调整了路径顺序和节点数量。",
    }


def _patch_model(monkeypatch, session, *, fail=False):
    calls = []

    async def fake_call(current_session, **kwargs):
        if fail:
            raise M5CapabilityError("provider_call_failed", "provider unavailable")
        context = json.loads(kwargs["user_prompt"])["context"]
        profile_id = context["profile_snapshot_id"]
        short = profile_id.endswith("-short")
        payload = _model_payload(current_session, profile_id, short=short)
        row = DBModelCall(
            trace_id="trace-p1-b11",
            owner_public_id=kwargs["owner_public_id"],
            course_id=kwargs["course_id"],
            capability=Capability.PLAN.value,
            prompt_version="p1_b11_personalized_learning_path:1.0",
            provider="openai",
            model="deepseek-v4-flash",
            status="completed",
            input_summary={"profile_snapshot_id": profile_id},
            input_tokens=10,
            output_tokens=20,
        )
        current_session.add(row)
        current_session.flush()
        calls.append(profile_id)
        return GatewayResult(
            trace_id="trace-p1-b11",
            call_id=row.id,
            capability=Capability.PLAN,
            status="completed",
            structured_output=payload,
            model="deepseek-v4-flash",
            prompt_version="p1_b11_personalized_learning_path:1.0",
            input_tokens=10,
            output_tokens=20,
            token_source="estimated",
            estimated_cost=0.0,
        )

    monkeypatch.setattr(path_draft, "execute_registered_structured_call", fake_call)
    return calls


def _profile(session, owner: DBUser, suffix: str, *, short: bool = False):
    row = DBProfileSnapshot(
        owner_public_id=owner.public_id,
        legacy_student_id=owner.username,
        profile_version=f"p1-b11:{suffix}",
        snapshot={
            "course_id": COURSE_ID,
            "learning_goal": f"goal-{suffix}",
            "learning_preferences": {"pace": suffix},
            "time_budget_minutes": 90,
            "mastery_by_knowledge_point": {},
            "weak_knowledge_point_ids": [],
            "mastered_knowledge_point_ids": [],
            "unknown_knowledge_point_ids": [],
            "diagnostic_evidence": {"source_ref_ids": ["src-1"]},
        },
        content_hash=f"hash-{suffix}",
        trace_id=f"trace-{suffix}",
    )
    session.add(row)
    session.flush()
    return row


def test_path_is_model_personalized_and_failure_keeps_confirmed_version(monkeypatch):
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        first_profile = _profile(session, learner, "long")
        short_profile = _profile(session, learner, "short")
        calls = _patch_model(monkeypatch, session)

        first, changed = path_draft.generate_textbook_path_draft(
            session,
            current_user=learner,
            course_id=COURSE_ID,
            time_budget_minutes=90,
            profile_snapshot_id=first_profile.id,
            idempotency_key="p1-b11-long-001",
            llm=_RealPathBackend(),
        )
        assert changed is True
        first_version = session.get(path_draft.DBPlanVersion, first.current_version_id)
        assert first_version.profile_snapshot_id == first_profile.id
        assert len(first_version.content["nodes"]) == 2
        assert calls == [first_profile.id]
        learning_events_before_confirm = session.query(DBLearningEvent).count()

        path = confirm_plan(
            session,
            plan=first,
            owner_public_id=learner.public_id,
            expected_lock_version=first.lock_version,
        )
        session.flush()
        assert path.status == "active"
        assert session.query(DBLearningEvent).count() == learning_events_before_confirm
        old_version_id = first.current_version_id
        session.commit()

        _patch_model(monkeypatch, session, fail=True)
        with pytest.raises(path_draft.PathDraftError) as failed:
            path_draft.generate_textbook_path_draft(
                session,
                current_user=learner,
                course_id=COURSE_ID,
                time_budget_minutes=90,
                profile_snapshot_id=short_profile.id,
                idempotency_key="p1-b11-short-001",
                llm=_RealPathBackend(),
            )
        assert failed.value.code == "path_draft_model_failed"
        session.rollback()
        session.refresh(first)
        assert first.current_version_id == old_version_id
        assert session.query(DBPlanDraft).filter_by(id=first.id).one().confirmed_version_id == old_version_id
    finally:
        session.close()
        engine.dispose()


def test_three_profiles_change_model_path_and_context_is_complete(monkeypatch):
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profiles = [_profile(session, learner, suffix) for suffix in ("short", "medium", "long")]
        profile_node_counts = {profile.id: count for profile, count in zip(profiles, (1, 2, 3))}
        captured_contexts = []

        async def fake_call(current_session, **kwargs):
            context = json.loads(kwargs["user_prompt"])["context"]
            captured_contexts.append(context)
            node_count = profile_node_counts[context["profile_snapshot_id"]]
            payload = _model_payload(
                current_session, context["profile_snapshot_id"], node_count=node_count,
            )
            row = DBModelCall(
                trace_id=f"trace-p1-b11-{node_count}",
                owner_public_id=kwargs["owner_public_id"],
                course_id=kwargs["course_id"],
                capability=Capability.PLAN.value,
                prompt_version="p1_b11_personalized_learning_path:1.0",
                provider="openai",
                model="deepseek-v4-flash",
                status="completed",
                input_summary={"profile_snapshot_id": context["profile_snapshot_id"]},
                input_tokens=10,
                output_tokens=20,
            )
            current_session.add(row)
            current_session.flush()
            return GatewayResult(
                trace_id=row.trace_id,
                call_id=row.id,
                capability=Capability.PLAN,
                status="completed",
                structured_output=payload,
                model="deepseek-v4-flash",
                prompt_version="p1_b11_personalized_learning_path:1.0",
                input_tokens=10,
                output_tokens=20,
                token_source="estimated",
                estimated_cost=0.0,
            )

        monkeypatch.setattr(path_draft, "execute_registered_structured_call", fake_call)
        node_counts = []
        for index, profile in enumerate(profiles):
            plan, _ = path_draft.generate_textbook_path_draft(
                session,
                current_user=learner,
                course_id=COURSE_ID,
                time_budget_minutes=90,
                profile_snapshot_id=profile.id,
                idempotency_key=f"p1-b11-profile-{index}",
                llm=_RealPathBackend(),
            )
            node_counts.append(len(session.get(path_draft.DBPlanVersion, plan.current_version_id).content["nodes"]))
        assert node_counts == [1, 2, 3]
        assert [item["profile_snapshot_id"] for item in captured_contexts] == [item.id for item in profiles]
        for context in captured_contexts:
            assert set(context["initial_learning_evidence"]) >= {
                "mastery_by_knowledge_point", "mastered_knowledge_point_ids",
                "weak_knowledge_point_ids", "unknown_knowledge_point_ids", "diagnostic_evidence",
            }
            assert context["learning_goal"]
            assert context["learning_preferences"]
            assert context["time_budget_minutes"] == 90
            assert context["course_graph"]["chapters"]
            assert context["course_graph"]["sources"]
    finally:
        session.close()
        engine.dispose()


def test_structured_path_output_gets_one_governed_retry(monkeypatch):
    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = _profile(session, learner, "retry")
        calls = []

        async def flaky_call(current_session, **kwargs):
            calls.append(kwargs["user_prompt"])
            if len(calls) == 1:
                raise M5CapabilityError("structured_output_invalid", "invalid path JSON")
            context = json.loads(kwargs["user_prompt"])["context"]
            payload = _model_payload(current_session, context["profile_snapshot_id"], short=True)
            row = DBModelCall(
                trace_id="trace-p1-b11-retry",
                owner_public_id=kwargs["owner_public_id"],
                course_id=kwargs["course_id"],
                capability=Capability.PLAN.value,
                prompt_version="p1_b11_personalized_learning_path:1.0",
                provider="openai",
                model="deepseek-v4-flash",
                status="completed",
                input_summary={"profile_snapshot_id": context["profile_snapshot_id"]},
                input_tokens=10,
                output_tokens=20,
            )
            current_session.add(row)
            current_session.flush()
            return GatewayResult(
                trace_id="trace-p1-b11-retry",
                call_id=row.id,
                capability=Capability.PLAN,
                status="completed",
                structured_output=payload,
                model="deepseek-v4-flash",
                prompt_version="p1_b11_personalized_learning_path:1.0",
                input_tokens=10,
                output_tokens=20,
                token_source="estimated",
                estimated_cost=0.0,
            )

        monkeypatch.setattr(path_draft, "execute_registered_structured_call", flaky_call)
        plan, changed = path_draft.generate_textbook_path_draft(
            session,
            current_user=learner,
            course_id=COURSE_ID,
            time_budget_minutes=90,
            profile_snapshot_id=profile.id,
            idempotency_key="p1-b11-retry-001",
            llm=_RealPathBackend(),
        )
        assert changed is True
        assert len(calls) == 2
        assert "上一次返回未通过结构校验" in calls[1]
        assert session.get(path_draft.DBPlanVersion, plan.current_version_id).profile_snapshot_id == profile.id
    finally:
        session.close()
        engine.dispose()


def test_path_model_policy_and_topology_fail_closed(monkeypatch):
    with pytest.raises(path_draft.PathDraftError) as policy:
        path_draft._require_path_model(type("DeterministicBackend", (), {
            "model": "deterministic",
            "thinking_mode": "enabled",
            "reasoning_effort": "max",
        })())
    assert policy.value.code == "path_draft_model_policy_invalid"

    engine, session = _session()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = _profile(session, learner, "topology")
        facts = path_draft._course_facts(session, course_id=COURSE_ID)
        first, second = facts["chapters"][:2]
        invalid = {
            "plan": {
                "schema_version": "m5.plan.v1",
                "goal": "invalid",
                "assumptions": [],
                "nodes": [
                    {
                        "node_key": "later",
                        "node_type": "chapter",
                        "target_object_id": second.id,
                        "title": second.title,
                        "prerequisites": ["missing"],
                        "resource_status": "existing",
                        "estimate_min_minutes": 10,
                        "estimate_max_minutes": 10,
                        "difficulty": 0.5,
                        "rationale": "invalid topology",
                    }
                ],
            },
            "personalization_summary": "invalid topology output",
        }
        with pytest.raises(path_draft.PathDraftError):
            path_draft._validate_model_plan_output(
                invalid, facts=facts, owner_public_id=learner.public_id,
                course_id=COURSE_ID, session=session,
            )
        assert profile.snapshot["course_id"] == COURSE_ID
    finally:
        session.close()
        engine.dispose()


def test_learning_path_ui_exposes_model_status_and_no_private_trace():
    view = (path_draft.__file__.replace("app\\path_draft.py", "frontend\\src\\views\\LearningPathGraph.vue"))
    text = open(view, encoding="utf-8").read()
    assert "textbook-path-model-status" in text
    assert "deepseek-v4-flash" in text
    assert "模型失败不会改用模板" in text
    assert "reasoning_content" not in text
    assert "api_key" not in text
