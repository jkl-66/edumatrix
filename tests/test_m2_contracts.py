from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.m2_contracts import (
    GenerationContext,
    LabGuideArtifact,
    LessonArtifact,
    M2Capability,
    TieredQuizArtifact,
    validate_m2_artifact,
)


def _question(question_id: str, bloom: str) -> dict:
    return {
        "id": question_id,
        "prompt": "请选择正确处理方式",
        "knowledge_point_ids": ["kp-rag-citation"],
        "bloom_level": bloom,
        "difficulty_basis": "需要识别来源支持边界",
        "scoring_rule": "答案和理由均正确得 2 分",
        "answer_key": "检查 source_ref 后再回答",
        "explanation": "无来源时必须诚实说明",
        "source_ref_ids": ["src-ref-001"],
    }


def test_generation_context_requires_verified_sources_and_unique_targets():
    context = GenerationContext(
        owner_public_id="usr-12345678", course_id="course-rag",
        domain_version_id="domain-version-1", profile_snapshot_id="snapshot-1",
        target_knowledge_point_ids=["kp-rag-citation"], source_ref_ids=["src-ref-001"],
    )
    assert context.quality_mode == "verified"
    with pytest.raises(ValidationError):
        GenerationContext(
            owner_public_id="usr-12345678", course_id="course-rag",
            domain_version_id="domain-version-1", profile_snapshot_id="snapshot-1",
            target_knowledge_point_ids=["kp", "kp"], source_ref_ids=[],
        )


def test_lesson_contract_requires_section_level_knowledge_and_sources():
    payload = {
        "artifact_type": "lesson", "title": "引用约束生成", "objective": "掌握可追溯回答",
        "sections": [{
            "heading": "证据边界", "body_markdown": "回答必须由来源支持。",
            "knowledge_point_ids": ["kp-rag-citation"], "source_ref_ids": ["src-ref-001"],
        }],
        "summary": "先检索，后生成，再核验。",
    }
    artifact = validate_m2_artifact(M2Capability.LESSON, payload)
    assert isinstance(artifact, LessonArtifact)
    with pytest.raises((ValidationError, ValueError)):
        validate_m2_artifact(M2Capability.LAB_GUIDE, payload)


def test_lab_guide_contract_requires_ordered_steps_rollback_and_failure_branch():
    payload = {
        "artifact_type": "lab_guide", "title": "RAG 引用检查实验", "objective": "验证引用回跳",
        "environment": ["Windows 11", "Python 3.11"], "safety_boundary": "仅使用本地研究数据",
        "steps": [{
            "step_number": 1, "title": "运行检查", "instruction": "执行来源检查器",
            "command_or_action": "python verify.py", "expected_result": "所有 claim 均有裁决",
            "rollback": "删除本次临时输出", "risk_level": "low", "source_ref_ids": ["src-ref-001"],
        }],
        "acceptance_criteria": ["unsupported claim 被标记"],
        "failure_branches": [{
            "symptom": "找不到来源", "likely_cause": "索引未初始化",
            "recovery_steps": ["确认课程来源已导入", "重新构建索引"],
        }],
    }
    artifact = validate_m2_artifact(M2Capability.LAB_GUIDE, payload)
    assert isinstance(artifact, LabGuideArtifact)
    broken = {**payload, "steps": [{**payload["steps"][0], "step_number": 2}]}
    with pytest.raises(ValidationError, match="consecutive"):
        validate_m2_artifact(M2Capability.LAB_GUIDE, broken)


def test_tiered_quiz_contract_orders_three_tiers_and_hides_answers_from_learner():
    payload = {
        "artifact_type": "tiered_quiz", "title": "引用能力分阶测试", "instructions": "逐阶完成",
        "tiers": [
            {"level": "foundation", "questions": [_question("q-foundation", "understand")]},
            {"level": "application", "questions": [_question("q-application", "apply")]},
            {"level": "advanced", "questions": [_question("q-advanced", "analyze")]},
        ],
        "pass_rules": {"foundation": "2 分", "application": "2 分", "advanced": "2 分"},
    }
    artifact = validate_m2_artifact(M2Capability.TIERED_QUIZ, payload)
    assert isinstance(artifact, TieredQuizArtifact)
    learner = artifact.learner_payload()
    assert "answer_key" not in learner["tiers"][0]["questions"][0]
    assert "explanation" not in learner["tiers"][0]["questions"][0]
    wrong_order = {**payload, "tiers": list(reversed(payload["tiers"]))}
    with pytest.raises(ValidationError, match="ordered"):
        validate_m2_artifact(M2Capability.TIERED_QUIZ, wrong_order)


def test_contracts_reject_unknown_fields_instead_of_silently_dropping_them():
    with pytest.raises(ValidationError):
        LessonArtifact(
            title="讲义", objective="目标", summary="总结", unexpected="ignored",
            sections=[{
                "heading": "章节", "body_markdown": "内容",
                "knowledge_point_ids": ["kp"], "source_ref_ids": ["src"],
            }],
        )
