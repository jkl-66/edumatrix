from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBArtifact, DBArtifactRelation, DBArtifactVersion
from app.agent_audit import public_agent_audit_payload
from app.m1_repository import M1Repository
from app.m3_agents import (
    M3AgentRole,
    complete_m3_agent_run,
    create_m3_collaboration_task,
    start_m3_agent_run,
    start_m3_collaboration_task,
)
from app.m3_baseline import seed_m3_profile_baselines
from app.m3_resources import (
    M3PersonalizedResourceGenerator,
    M3ResourceError,
    persist_m3_resource_bundle,
    validate_m3_resource_bundle,
)


class ProfileAwareFakeLLM:
    def __init__(self):
        self.calls = []

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        request = json.loads(user_prompt)
        self.calls.append((system_prompt, request, role))
        context = request["context"]
        personalization = request["profile"]["personalization"]
        archetype = request["profile"]["source_profile_id"]
        source_ids = context["source_ref_ids"]
        kp_ids = context["target_knowledge_point_ids"]
        if archetype.endswith("beginner"):
            lesson_body = "先解释关键词、向量和 top-k 术语，再用一个短例比较候选。"
            step_count, advanced_bloom = 4, "analyze"
        elif archetype.endswith("theory"):
            lesson_body = "压缩检索理论，重点比较 owner 过滤、参数控制和故障定位。"
            step_count, advanced_bloom = 3, "evaluate"
        else:
            lesson_body = "分析召回、排序、成本、版本隔离和迁移场景之间的工程权衡。"
            step_count, advanced_bloom = 2, "create"

        def question(qid, bloom):
            return {
                "id": qid,
                "prompt": f"{archetype} 如何调优并保持隔离？",
                "knowledge_point_ids": kp_ids,
                "bloom_level": bloom,
                "difficulty_basis": personalization["difficulty_band"],
                "scoring_rule": "参数、证据和隔离边界均正确得分",
                "answer_key": "先过滤，再检索与重排，最后用冻结 query 验收",
                "explanation": "不能用单次回答或关闭 owner 过滤换取指标",
                "source_ref_ids": source_ids,
            }

        return json.dumps(
            {
                "lesson": {
                    "artifact_type": "lesson",
                    "schema_version": "m3.lesson.v1",
                    "title": f"{archetype} 混合检索讲义",
                    "objective": "调优混合检索并保持数据隔离",
                    "prerequisites": ["Python/JSON"] if archetype.endswith("beginner") else [],
                    "sections": [{
                        "heading": "检索调优",
                        "body_markdown": lesson_body,
                        "knowledge_point_ids": kp_ids,
                        "source_ref_ids": source_ids,
                    }],
                    "retrieval_questions": ["top-k 改变会影响什么？"],
                    "summary": "参数变化必须绑定证据、版本和隔离验收。",
                    "personalization": personalization,
                },
                "lab_guide": {
                    "artifact_type": "lab_guide",
                    "schema_version": "m3.lab_guide.v1",
                    "title": f"{archetype} 检索调优实操",
                    "objective": "对冻结 query 执行参数实验",
                    "environment": ["冻结 RAG 课程", "受控模拟器"],
                    "safety_boundary": "owner/course/version 过滤不可关闭",
                    "steps": [{
                        "step_number": index,
                        "title": f"步骤 {index}",
                        "instruction": "调整一个变量并记录结果",
                        "command_or_action": f"set top_k={index + 2}",
                        "expected_result": "结果保存参数和来源",
                        "rollback": "恢复上一个参数快照",
                        "risk_level": "low",
                        "source_ref_ids": source_ids,
                    } for index in range(1, step_count + 1)],
                    "acceptance_criteria": ["指标可复现", "跨 owner 泄露为 0"],
                    "failure_branches": [{
                        "symptom": "owner 过滤后无结果",
                        "likely_cause": "查询范围或索引版本错误",
                        "recovery_steps": ["核对 owner/course/version", "恢复正确索引"],
                    }],
                    "personalization": personalization,
                },
                "tiered_quiz": {
                    "artifact_type": "tiered_quiz",
                    "schema_version": "m3.tiered_quiz.v1",
                    "title": f"{archetype} 检索调优测试",
                    "instructions": "按基础、应用、进阶完成",
                    "tiers": [
                        {"level": "foundation", "questions": [question("q-f", "understand")]},
                        {"level": "application", "questions": [question("q-a", "apply")]},
                        {"level": "advanced", "questions": [question("q-x", advanced_bloom)]},
                    ],
                    "pass_rules": {"foundation": "2 分", "application": "2 分", "advanced": "2 分"},
                    "personalization": personalization,
                },
            },
            ensure_ascii=False,
        )


class RepairingProfileAwareFakeLLM(ProfileAwareFakeLLM):
    def __init__(self):
        super().__init__()
        self.received_requests = []

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        request = json.loads(user_prompt)
        self.received_requests.append(request)
        original = request.get("original_request", request)
        result = await super().generate(
            system_prompt,
            json.dumps(original, ensure_ascii=False),
            role=role,
        )
        if len(self.calls) == 1:
            payload = json.loads(result)
            payload["tiered_quiz"]["pass_rules"] = {"foundation": "2 分"}
            return json.dumps(payload, ensure_ascii=False)
        return result


class PersonalizationRepairingFakeLLM(ProfileAwareFakeLLM):
    def __init__(self):
        super().__init__()
        self.received_requests = []

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        request = json.loads(user_prompt)
        self.received_requests.append(request)
        original = request.get("original_request", request)
        result = await super().generate(
            system_prompt,
            json.dumps(original, ensure_ascii=False),
            role=role,
        )
        if len(self.calls) == 1:
            payload = json.loads(result)
            for step in payload["lab_guide"]["steps"]:
                step["command_or_action"] = ""
            return json.dumps(payload, ensure_ascii=False)
        return result


class AlwaysInvalidProfileAwareFakeLLM(ProfileAwareFakeLLM):
    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        request = json.loads(user_prompt)
        original = request.get("original_request", request)
        result = await super().generate(
            system_prompt,
            json.dumps(original, ensure_ascii=False),
            role=role,
        )
        payload = json.loads(result)
        payload["tiered_quiz"]["pass_rules"] = {"foundation": "2 分"}
        return json.dumps(payload, ensure_ascii=False)


class SplitOnlyProfileAwareFakeLLM(ProfileAwareFakeLLM):
    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        request = json.loads(user_prompt)
        if "artifact_type" not in request:
            self.calls.append((system_prompt, request, role))
            return "not-json"
        full = await super().generate(system_prompt, user_prompt, role=role)
        return json.dumps(json.loads(full)[request["artifact_type"]], ensure_ascii=False)


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_three_profiles_generate_formal_different_resources_with_unchanged_standards():
    engine, session = _session()
    llm = ProfileAwareFakeLLM()
    try:
        fixtures = seed_m3_profile_baselines(session).fixtures
        lesson_bodies, lab_step_counts, difficulty_bands, audit_summaries = [], [], [], []
        for fixture in fixtures:
            context = fixture.generation_context
            task, _ = create_m3_collaboration_task(
                session,
                context=context,
                idempotency_key=f"m3-resources-{fixture.gold_profile.archetype}",
            )
            start_m3_collaboration_task(session, task_id=task.id, owner_public_id=context.owner_public_id)
            start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DIAGNOSIS)
            complete_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DIAGNOSIS)
            start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DOMAIN_GENERATION)

            bundle = asyncio.run(M3PersonalizedResourceGenerator(llm).generate(session, context=context))
            manifest, _manifest_version, resources, created = persist_m3_resource_bundle(
                session, task_id=task.id, context=context, bundle=bundle
            )
            assert created is True
            replay = persist_m3_resource_bundle(session, task_id=task.id, context=context, bundle=bundle)
            assert replay[0].id == manifest.id
            assert replay[3] is False
            lesson_bodies.append(bundle.lesson.sections[0].body_markdown)
            lab_step_counts.append(len(bundle.lab_guide.steps))
            difficulty_bands.append(bundle.lesson.personalization.difficulty_band)
            audit = public_agent_audit_payload(
                session,
                task_id=task.id,
                owner_public_id=context.owner_public_id,
            )
            audit_summaries.append(audit["items"][-1]["candidateSummary"])
            assert all(
                artifact.personalization.fact_standard == "unchanged"
                and artifact.personalization.safety_standard == "unchanged"
                for artifact in (bundle.lesson, bundle.lab_guide, bundle.tiered_quiz)
            )
            quiz = next(resource for resource in resources if resource.artifact_type == "tiered_quiz")
            learner_content = M1Repository(session).artifact_payload(quiz)["versions"][0]["content"]
            assert "answer_key" not in learner_content
            assert "explanation" not in learner_content

        assert len(set(lesson_bodies)) == 3
        assert lab_step_counts == [4, 3, 2]
        assert difficulty_bands == ["L0-L1", "L1-L2", "L2-L4"]
        assert len(set(audit_summaries)) == 3
        assert session.query(DBArtifact).count() == 12
        assert session.query(DBArtifactVersion).count() == 12
        assert session.query(DBArtifactRelation).count() == 9
        assert len(llm.calls) == 3
    finally:
        session.close()
        engine.dispose()


def test_resource_contract_rejects_claimed_personalization_from_another_profile():
    engine, session = _session()
    try:
        first, second = seed_m3_profile_baselines(session).fixtures[:2]
        llm = ProfileAwareFakeLLM()
        bundle = asyncio.run(M3PersonalizedResourceGenerator(llm).generate(session, context=first.generation_context))
        payload = bundle.model_dump(mode="json")
        foreign = second.gold_profile.adaptation_strategy
        payload["lesson"]["personalization"]["difficulty_band"] = foreign.difficulty_band

        with pytest.raises(M3ResourceError) as raised:
            validate_m3_resource_bundle(
                payload,
                context=first.generation_context,
                profile=first.gold_profile,
            )
        assert raised.value.code == "personalization_evidence_mismatch"
    finally:
        session.close()
        engine.dispose()


def test_resource_contract_rejects_metadata_only_beginner_scaffolding():
    engine, session = _session()
    try:
        fixture = seed_m3_profile_baselines(session).fixtures[0]
        bundle = asyncio.run(
            M3PersonalizedResourceGenerator(ProfileAwareFakeLLM()).generate(
                session, context=fixture.generation_context
            )
        )
        payload = bundle.model_dump(mode="json")
        for step in payload["lab_guide"]["steps"]:
            step["command_or_action"] = ""

        with pytest.raises(M3ResourceError) as raised:
            validate_m3_resource_bundle(
                payload,
                context=fixture.generation_context,
                profile=fixture.gold_profile,
            )
        assert raised.value.code == "personalization_structure_mismatch"
        assert "command_or_action" in str(raised.value)
    finally:
        session.close()
        engine.dispose()


def test_resource_contract_rejects_theory_lesson_without_debugging_check():
    engine, session = _session()
    try:
        fixture = seed_m3_profile_baselines(session).fixtures[1]
        bundle = asyncio.run(
            M3PersonalizedResourceGenerator(ProfileAwareFakeLLM()).generate(
                session, context=fixture.generation_context
            )
        )
        payload = bundle.model_dump(mode="json")
        payload["lesson"]["retrieval_questions"] = []

        with pytest.raises(M3ResourceError) as raised:
            validate_m3_resource_bundle(
                payload,
                context=fixture.generation_context,
                profile=fixture.gold_profile,
            )
        assert raised.value.code == "personalization_structure_mismatch"
        assert "application_debugging" in str(raised.value)
    finally:
        session.close()
        engine.dispose()


def test_generator_retries_once_with_validation_feedback_and_keeps_strict_contract():
    engine, session = _session()
    llm = RepairingProfileAwareFakeLLM()
    try:
        fixture = seed_m3_profile_baselines(session).fixtures[0]
        bundle = asyncio.run(
            M3PersonalizedResourceGenerator(llm).generate(
                session, context=fixture.generation_context
            )
        )
        assert bundle.tiered_quiz.pass_rules.keys() == {"foundation", "application", "advanced"}
        assert len(llm.calls) == 2
        assert "validation_feedback" in llm.received_requests[1]
        assert llm.received_requests[1]["validation_feedback"]["code"] == "m3_resource_schema_invalid"
    finally:
        session.close()
        engine.dispose()


def test_generator_repairs_metadata_only_personalization_before_persistence():
    engine, session = _session()
    llm = PersonalizationRepairingFakeLLM()
    try:
        fixture = seed_m3_profile_baselines(session).fixtures[0]
        bundle = asyncio.run(
            M3PersonalizedResourceGenerator(llm).generate(
                session, context=fixture.generation_context
            )
        )
        assert all(step.command_or_action for step in bundle.lab_guide.steps)
        assert len(llm.calls) == 2
        feedback = llm.received_requests[1]["validation_feedback"]
        assert feedback["code"] == "personalization_structure_mismatch"
        assert "command_or_action" in feedback["message"]
    finally:
        session.close()
        engine.dispose()


def test_generator_stops_after_bundle_and_first_split_repairs_fail():
    engine, session = _session()
    llm = AlwaysInvalidProfileAwareFakeLLM()
    try:
        fixture = seed_m3_profile_baselines(session).fixtures[0]
        with pytest.raises(M3ResourceError) as raised:
            asyncio.run(
                M3PersonalizedResourceGenerator(llm).generate(
                    session, context=fixture.generation_context
                )
            )
        assert raised.value.code == "m3_split_resource_invalid"
        assert "lesson" in str(raised.value)
        assert len(llm.calls) == 4
        assert session.query(DBArtifact).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_generator_falls_back_to_three_strict_small_objects_after_bundle_failure():
    engine, session = _session()
    llm = SplitOnlyProfileAwareFakeLLM()
    try:
        fixture = seed_m3_profile_baselines(session).fixtures[0]
        bundle = asyncio.run(
            M3PersonalizedResourceGenerator(llm).generate(
                session, context=fixture.generation_context
            )
        )
        assert bundle.lesson.artifact_type == "lesson"
        assert bundle.lab_guide.artifact_type == "lab_guide"
        assert bundle.tiered_quiz.artifact_type == "tiered_quiz"
        assert len(llm.calls) == 4
        assert [call[1].get("artifact_type") for call in llm.calls[-3:]] == [
            "lesson", "lab_guide", "tiered_quiz"
        ]
    finally:
        session.close()
        engine.dispose()
