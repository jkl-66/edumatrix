from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBArtifact, DBArtifactVersion
from app.m1_repository import M1Repository
from app.m2_artifacts import (
    M2ArtifactGenerationError,
    M2StructuredArtifactGenerator,
    persist_generated_artifact,
)
from app.m2_baseline import seed_m2_baseline
from app.m2_contracts import M2Capability
from app.m2_tasks import create_golden_task, start_golden_task, start_task_step
from llm_client import AsyncDeterministicEducationLLM


def _question(question_id: str, bloom: str, context) -> dict:
    return {
        "id": question_id,
        "prompt": "如何保证回答有可追溯来源？",
        "knowledge_point_ids": context.target_knowledge_point_ids,
        "bloom_level": bloom,
        "difficulty_basis": "需要识别原子事实与来源的支持关系",
        "scoring_rule": "结论和来源边界均正确得 2 分",
        "answer_key": "先定位 source_ref，再核验每个原子事实",
        "explanation": "没有来源支持的事实不得作为确定结论",
        "source_ref_ids": context.source_ref_ids,
    }


def _payloads(context):
    return {
        "理论教授": {
            "artifact_type": "lesson",
            "title": "原子事实与来源引用",
            "objective": "掌握可追溯回答",
            "sections": [{
                "heading": "证据边界",
                "body_markdown": "将回答拆成原子事实并逐项绑定来源。",
                "knowledge_point_ids": context.target_knowledge_point_ids,
                "source_ref_ids": context.source_ref_ids,
            }],
            "retrieval_questions": ["哪些事实缺少来源支持？"],
            "summary": "先检索、再生成、后核验。",
        },
        "极客助教": {
            "artifact_type": "lab_guide",
            "title": "引用核验实操",
            "objective": "运行来源核验流程",
            "environment": ["Python 3.11+", "本地冻结课程数据"],
            "safety_boundary": "只读取课程数据，不执行外部下载或破坏性命令",
            "steps": [{
                "step_number": 1,
                "title": "执行核验",
                "instruction": "对回答中的原子事实逐项检查来源",
                "command_or_action": "python verify_claims.py --dry-run",
                "expected_result": "每个事实得到 supported 或 unsupported 裁决",
                "rollback": "删除本次临时报告，不修改冻结来源",
                "risk_level": "low",
                "source_ref_ids": context.source_ref_ids,
            }],
            "acceptance_criteria": ["unsupported 事实均被标记"],
            "failure_branches": [{
                "symptom": "来源无法定位",
                "likely_cause": "source_ref 不属于当前课程",
                "recovery_steps": ["核对课程 ID", "重新装配 verified 上下文"],
            }],
        },
        "考官智能体": {
            "artifact_type": "tiered_quiz",
            "title": "引用能力分阶测试",
            "instructions": "按基础、应用、进阶顺序完成",
            "tiers": [
                {"level": "foundation", "questions": [_question("q-f", "understand", context)]},
                {"level": "application", "questions": [_question("q-a", "apply", context)]},
                {"level": "advanced", "questions": [_question("q-x", "analyze", context)]},
            ],
            "pass_rules": {"foundation": "2 分", "application": "2 分", "advanced": "2 分"},
        },
    }


class FakeStructuredLLM:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        self.calls.append((system_prompt, json.loads(user_prompt), role))
        return json.dumps(self.payloads[role], ensure_ascii=False)


def _seeded_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    baseline = seed_m2_baseline(session)
    task, _ = create_golden_task(
        session, context=baseline.generation_context, idempotency_key="m2-artifacts"
    )
    start_golden_task(
        session, task_id=task.id, owner_public_id=baseline.generation_context.owner_public_id
    )
    return engine, session, baseline, task


def test_three_structured_generations_persist_formal_versions_and_hide_quiz_answers():
    engine, session, baseline, task = _seeded_session()
    context = baseline.generation_context
    llm = FakeStructuredLLM(_payloads(context))
    generator = M2StructuredArtifactGenerator(llm)
    try:
        for sequence, capability in enumerate(M2Capability, start=1):
            start_task_step(
                session,
                task_id=task.id,
                owner_public_id=context.owner_public_id,
                sequence=sequence,
            )
            artifact = asyncio.run(
                generator.generate(session, capability=capability, context=context)
            )
            persisted, version, created = persist_generated_artifact(
                session,
                task_id=task.id,
                context=context,
                capability=capability,
                artifact=artifact,
            )
            assert created is True
            assert version.content_format == "json"
            assert version.metadata_json["source_ref_ids"] == context.source_ref_ids
            assert persisted.current_version_id == version.id
        session.commit()

        assert session.query(DBArtifact).filter_by(creating_task_id=task.id).count() == 3
        assert session.query(DBArtifactVersion).count() == 3
        assert len(llm.calls) == 3
        assert all("JSON Schema" in call[0] for call in llm.calls)

        quiz = session.query(DBArtifact).filter_by(
            creating_task_id=task.id, artifact_type="tiered_quiz"
        ).one()
        raw_server_version = session.query(DBArtifactVersion).filter_by(id=quiz.current_version_id).one()
        assert "answer_key" in raw_server_version.content
        learner_payload = M1Repository(session).artifact_payload(quiz)
        learner_content = learner_payload["versions"][0]["content"]
        assert "answer_key" not in learner_content
        assert "explanation" not in learner_content
    finally:
        session.close()
        engine.dispose()


def test_offline_deterministic_backend_honors_all_m2_structured_contracts():
    engine, session, baseline, _task = _seeded_session()
    generator = M2StructuredArtifactGenerator(AsyncDeterministicEducationLLM())
    try:
        artifacts = [
            asyncio.run(generator.generate(session, capability=capability, context=baseline.generation_context))
            for capability in M2Capability
        ]
        assert [artifact.artifact_type for artifact in artifacts] == ["lesson", "lab_guide", "tiered_quiz"]
        lesson_refs = {ref for section in artifacts[0].sections for ref in section.source_ref_ids}
        lab_refs = {ref for step in artifacts[1].steps for ref in step.source_ref_ids}
        quiz_refs = {
            ref
            for tier in artifacts[2].tiers
            for question in tier.questions
            for ref in question.source_ref_ids
        }
        expected_refs = set(baseline.generation_context.source_ref_ids)
        assert lesson_refs == lab_refs == quiz_refs == expected_refs
    finally:
        session.close()
        engine.dispose()


def test_invalid_generator_json_and_out_of_scope_source_fail_without_artifact():
    engine, session, baseline, task = _seeded_session()
    context = baseline.generation_context
    try:
        bad_json = FakeStructuredLLM(_payloads(context))
        bad_json.payloads["理论教授"] = "not-an-object"
        with pytest.raises(M2ArtifactGenerationError) as raised:
            asyncio.run(
                M2StructuredArtifactGenerator(bad_json).generate(
                    session, capability=M2Capability.LESSON, context=context
                )
            )
        assert raised.value.code == "invalid_generator_json"

        class MarkdownLLM:
            async def generate(self, system_prompt, user_prompt, *, role):
                return "```json\n{}\n```"

        with pytest.raises(M2ArtifactGenerationError) as raised:
            asyncio.run(
                M2StructuredArtifactGenerator(MarkdownLLM()).generate(
                    session, capability=M2Capability.LESSON, context=context
                )
            )
        assert raised.value.code == "artifact_schema_invalid"

        payloads = _payloads(context)
        payloads["理论教授"]["sections"][0]["source_ref_ids"] = ["ref-outside-context"]
        with pytest.raises(M2ArtifactGenerationError) as raised:
            asyncio.run(
                M2StructuredArtifactGenerator(FakeStructuredLLM(payloads)).generate(
                    session, capability=M2Capability.LESSON, context=context
                )
            )
        assert raised.value.code == "artifact_source_out_of_scope"
        assert session.query(DBArtifact).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_identical_artifact_replay_does_not_create_a_duplicate_version():
    engine, session, baseline, task = _seeded_session()
    context = baseline.generation_context
    generator = M2StructuredArtifactGenerator(FakeStructuredLLM(_payloads(context)))
    try:
        start_task_step(
            session, task_id=task.id, owner_public_id=context.owner_public_id, sequence=1
        )
        artifact = asyncio.run(
            generator.generate(session, capability=M2Capability.LESSON, context=context)
        )
        first_artifact, first_version, first_created = persist_generated_artifact(
            session,
            task_id=task.id,
            context=context,
            capability=M2Capability.LESSON,
            artifact=artifact,
        )
        replay_artifact, replay_version, replay_created = persist_generated_artifact(
            session,
            task_id=task.id,
            context=context,
            capability=M2Capability.LESSON,
            artifact=artifact,
        )
        assert first_created is True
        assert replay_created is False
        assert replay_artifact.id == first_artifact.id
        assert replay_version.id == first_version.id
        assert session.query(DBArtifactVersion).count() == 1
    finally:
        session.close()
        engine.dispose()
