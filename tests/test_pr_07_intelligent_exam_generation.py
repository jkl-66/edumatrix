from datetime import timedelta

from app.database import DBProfileSnapshot
from app.m5_exam_core import IntelligentExamConfigInput, build_intelligent_exam_input
import app.m5_exam_core as exam_core

from tests.test_f6_t06_formal_exam import _configuration, _fixture


def _config(**overrides):
    payload = _configuration(overrides.pop("idempotency_key", "pr7-generation-key"))
    payload.update(overrides)
    return IntelligentExamConfigInput(**payload)


def test_pr07_builds_auditable_blueprint_and_source_bound_questions():
    session, _engine, learner, _completion = _fixture()

    payload = build_intelligent_exam_input(
        session,
        owner_public_id=learner.public_id,
        config=_config(),
    )

    context = payload.generation_context
    assert context["schema_version"] == "f7.intelligent-exam-generation.v2"
    assert context["generation_mode"] == "deterministic_blueprint"
    assert context["external_model_used"] is False
    assert context["question_bank_fallback"]["available"] is True
    assert context["question_bank_fallback"]["used"] is False
    assert context["blueprint"]["theme"] == "Core concept verification"
    assert context["blueprint"]["source_ref_ids"] == ["source-ref-f6"]
    assert "recent_event_ids" not in context
    assert len(context["generated_question_version_ids"]) == 4
    assert len(payload.items) == 4

    generated_ids = {item.question_version_id for item in payload.items}
    generated = [
        version for version in session.query(exam_core.DBAssessmentQuestionVersion).all()
        if version.id in generated_ids
    ]
    assert len(generated) == 4
    assert all(version.source_ref_ids == ["source-ref-f6"] for version in generated)
    assert all(version.primary_knowledge_point_id in {"kp-f6-a", "kp-f6-b"} for version in generated)
    assert all(
        session.get(exam_core.DBAssessmentQuestion, version.question_id).origin == "derived"
        and session.get(exam_core.DBAssessmentQuestion, version.question_id).status == "approved"
        for version in generated
    )


def test_pr07_theme_and_profile_context_change_generated_semantics():
    session, _engine, learner, _completion = _fixture()
    base = _config(idempotency_key="pr7-profile-a", theme="主题 A", knowledge_point_ids=["kp-f6-a"])
    first = build_intelligent_exam_input(session, owner_public_id=learner.public_id, config=base)

    session.add(DBProfileSnapshot(
        id="profile-pr7-a",
        owner_public_id=learner.public_id,
        profile_version="1",
        snapshot={"concept_mastery": {"kp-f6-a": 0.2}, "learning_preferences": "先看图示"},
        content_hash="a" * 64,
        trace_id="profile-pr7-a-trace",
    ))
    session.flush()
    second = build_intelligent_exam_input(
        session,
        owner_public_id=learner.public_id,
        config=_config(idempotency_key="pr7-profile-b", theme="主题 B", knowledge_point_ids=["kp-f6-a"]),
    )

    first_prompt = session.get(exam_core.DBAssessmentQuestionVersion, first.items[0].question_version_id).prompt
    second_prompt = session.get(exam_core.DBAssessmentQuestionVersion, second.items[0].question_version_id).prompt
    assert first_prompt != second_prompt
    assert "主题 A" in first_prompt
    assert "主题 B" in second_prompt
    assert second.generation_context["profile_snapshot_id"] == "profile-pr7-a"
    assert second.generation_context["blueprint"]["mastery_average"] == 0.2


def test_pr07_records_question_bank_fallback_without_exposing_event_ids(monkeypatch):
    session, _engine, learner, _completion = _fixture()
    monkeypatch.setattr(exam_core, "_generate_dynamic_exam_items", lambda *args, **kwargs: [])

    payload = build_intelligent_exam_input(
        session,
        owner_public_id=learner.public_id,
        config=_config(idempotency_key="pr7-fallback-key"),
    )

    assert payload.generation_context["generation_mode"] == "question_bank_fallback"
    assert payload.generation_context["question_bank_fallback"]["used"] is True
    assert payload.generation_context["question_bank_fallback"]["reason"]
    assert "recent_event_ids" not in payload.generation_context
    assert len(payload.items) == 4


def test_pr07_deterministic_blueprint_uses_knowledge_specific_questions_and_public_reason():
    session, _engine, learner, _completion = _fixture()
    session.get(exam_core.DBKnowledgePoint, "kp-f6-a").title = "RAG 文档解析、切分与混合检索"
    session.get(exam_core.DBKnowledgePoint, "kp-f6-b").title = "优化算法、正则化与训练稳定性"
    session.flush()

    payload = build_intelligent_exam_input(
        session,
        owner_public_id=learner.public_id,
        config=_config(idempotency_key="pr7-semantic-blueprint"),
    )
    versions = [
        session.get(exam_core.DBAssessmentQuestionVersion, item.question_version_id)
        for item in payload.items
    ]
    prompts = "\n".join(version.prompt for version in versions)
    assert "解析缺页" in prompts
    assert "训练损失持续下降而验证损失连续上升" in prompts
    assert "主题“" not in prompts
    reason = payload.generation_context["model_status"]["reason"]
    assert "当前课程知识点" in reason
    assert "deterministic" not in reason.lower()
    assert "direct library" not in reason.lower()


def test_pr07_learner_error_reason_never_exposes_internal_identifiers():
    reason = exam_core._learner_error_reason(
        ("f7-kp-b8e6749cd9c5a27421f52374",),
        "优化算法、正则化与训练稳定性",
    )
    assert "优化算法、正则化与训练稳定性" in reason
    assert "仍需巩固" in reason
    assert "kp-" not in reason.lower()
