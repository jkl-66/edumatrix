from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.diagnostic_generation as diagnostic_generation
from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBDiagnosticBlueprint, DBKnowledgePoint, DBLearningEvent, DBProfileSnapshot, DBUser
from app.diagnostic_api import DiagnosticGenerateRequest
from app.diagnostic_generation import (
    DiagnosticBlueprintRequest,
    DiagnosticGenerationError,
    DiagnosticReviewBundle,
    _generation_scope,
    _question_type_quotas,
    _require_model_policy,
    _validate_generated_set,
    _validate_review,
    diagnostic_blueprint_payload,
    diagnostic_preflight,
    generate_diagnostic_blueprint,
)


ROOT = Path(__file__).resolve().parents[1]
COURSE_ID = "demo-course-rag-trust-v1"
ENTRY_DIAGNOSTIC = ROOT / "frontend" / "src" / "views" / "EntryDiagnostic.vue"


class _PolicyLLM:
    provider = "openai"
    model = "deepseek-v4-flash"
    thinking_mode = "enabled"
    reasoning_effort = "max"


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    seed_competition_demo(session)
    learner = session.query(DBUser).filter_by(username="lzz").one()
    return engine, session, learner


def _generated_payload(scope, count):
    quotas = _question_type_quotas(count)
    question_types = [
        question_type
        for question_type, total in quotas.items()
        for _ in range(total)
    ]
    coverage = Counter()
    questions = []
    for index, question_type in enumerate(question_types):
        point = scope["knowledgePoints"][index % len(scope["knowledgePoints"])]
        source = next(
            item for item in scope["sources"]
            if point["id"] in item["knowledgePointIds"]
        )
        item = {
            "item_id": f"Q{index + 1:02d}",
            "question_type": question_type,
            "prompt": f"第 {index + 1} 题：说明 {point['title']} 在课程案例中的正确边界。",
            "primary_knowledge_point_id": point["id"],
            "source_ref_id": source["sourceRefId"],
            "diagnostic_dimension": ("theory", "application", "engineering_judgment")[index % 3],
            "bloom_level": "apply" if index % 3 else "understand",
            "difficulty": 0.5,
            "explanation": f"依据 {source['location']} 的课程来源。",
        }
        if question_type == "true_false":
            item["answer"] = True
        elif question_type == "single_choice":
            item.update({
                "options": ["冻结范围并验证", "忽略来源", "替换课程", "跳过指标"],
                "answer": "A",
            })
        else:
            item.update({
                "reference_answer": "说明课程范围、判断依据、验证指标和来源位置。",
                "rubric": [
                    {"id": "scope", "label": "范围正确", "weight": 0.5},
                    {"id": "evidence", "label": "证据可定位", "weight": 0.5},
                ],
            })
        questions.append(item)
        coverage[point["id"]] += 1
    return {
        "profile_adaptation_summary": "按照当前画像设置中等起点，并优先覆盖全部课程目标知识点。",
        "coverage_plan": [
            {
                "knowledge_point_id": point["id"],
                "question_count": coverage[point["id"]],
                "rationale": "入学诊断需要覆盖该课程知识点。",
            }
            for point in scope["knowledgePoints"]
        ],
        "questions": questions,
    }


def _approved_review(generated):
    return DiagnosticReviewBundle.model_validate({
        "status": "approved",
        "decision_summary": "全部题目来源、答案和画像难度一致。",
        "items": [
            {
                "item_id": item.item_id,
                "verdict": "approved",
                "source_support": "supported",
                "answer_consistency": "consistent",
                "profile_fit": "fit",
                "public_note": "已核对。",
            }
            for item in generated.questions
        ],
    })


@pytest.mark.parametrize("count", [15, 20, 25])
def test_all_three_counts_persist_exact_mixed_source_profile_blueprints(monkeypatch, count):
    engine, session, learner = _session()
    try:
        profile = session.query(DBProfileSnapshot).filter_by(
            owner_public_id=learner.public_id,
        ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).first()
        before_profile = session.query(DBProfileSnapshot).count()
        before_events = session.query(DBLearningEvent).count()

        async def generated_and_reviewed(_session, *, course, profile, count, scope, **_kwargs):
            generated = _validate_generated_set(
                _generated_payload(scope, count),
                count=count,
                quotas=_question_type_quotas(count),
                scope=scope,
            )
            return generated, _approved_review(generated), {
                "model": "deepseek-v4-flash",
                "generationCallId": f"test-generate-{count}",
                "reviewCallId": f"test-review-{count}",
                "profileSnapshotId": profile.id,
                "profileVersion": profile.profile_version,
            }

        monkeypatch.setattr(diagnostic_generation, "_generate_and_review", generated_and_reviewed)
        preflight = diagnostic_preflight(
            session,
            user=learner,
            course_id=COURSE_ID,
            question_count=count,
        )
        row, created = generate_diagnostic_blueprint(
            session,
            user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, f"p1-b05-count-{count}", count),
            llm=_PolicyLLM(),
        )
        session.commit()
        payload = diagnostic_blueprint_payload(session, row)

        assert created is True
        assert preflight["requestedQuestionCount"] == preflight["expectedQuestionCount"] == count
        assert sum(preflight["coverage"]["questionTypes"].values()) == count
        assert row.question_count == len(row.question_version_ids) == len(payload["questions"]) == count
        assert Counter(item["questionType"] for item in payload["questions"]) == Counter(
            preflight["coverage"]["questionTypes"],
        )
        assert set(item["questionType"] for item in payload["questions"]) == {
            "true_false", "single_choice", "short_answer",
        }
        assert row.profile_snapshot_id == profile.id
        assert row.review_decision["profileVersion"] == profile.profile_version
        assert row.review_decision["questionCountAdjusted"] is False
        assert session.query(DBProfileSnapshot).count() == before_profile
        assert session.query(DBLearningEvent).count() == before_events
    finally:
        session.close()
        engine.dispose()


def test_invalid_counts_model_policy_and_reused_key_with_new_count_fail_closed(monkeypatch):
    for count in (3, 5, 8, 10, 12, 16):
        with pytest.raises(ValidationError):
            DiagnosticGenerateRequest(
                course_id=COURSE_ID,
                idempotency_key=f"invalid-count-{count}",
                question_count=count,
            )

    class WrongModel(_PolicyLLM):
        model = "another-model"

    class WrongThinking(_PolicyLLM):
        thinking_mode = "max"

    class FallbackDiagnosticLLM(_PolicyLLM):
        pass

    for backend in (WrongModel(), WrongThinking(), FallbackDiagnosticLLM()):
        with pytest.raises(DiagnosticGenerationError) as policy_error:
            _require_model_policy(backend)
        assert policy_error.value.code == "diagnostic_model_policy_invalid"

    engine, session, learner = _session()
    try:
        async def generated_and_reviewed(_session, *, profile, count, scope, **_kwargs):
            generated = _validate_generated_set(
                _generated_payload(scope, count),
                count=count,
                quotas=_question_type_quotas(count),
                scope=scope,
            )
            return generated, _approved_review(generated), {
                "model": "deepseek-v4-flash",
                "generationCallId": "test-generate",
                "reviewCallId": "test-review",
                "profileSnapshotId": profile.id,
                "profileVersion": profile.profile_version,
            }

        monkeypatch.setattr(diagnostic_generation, "_generate_and_review", generated_and_reviewed)
        first, _ = generate_diagnostic_blueprint(
            session,
            user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, "p1-b05-conflict-key", 15),
            llm=_PolicyLLM(),
        )
        session.commit()
        with pytest.raises(DiagnosticGenerationError) as conflict:
            generate_diagnostic_blueprint(
                session,
                user=learner,
                request=DiagnosticBlueprintRequest(COURSE_ID, "p1-b05-conflict-key", 20),
                llm=_PolicyLLM(),
            )
        assert conflict.value.code == "diagnostic_idempotency_conflict"
        assert session.query(DBDiagnosticBlueprint).count() == 1
        assert session.get(DBDiagnosticBlueprint, first.id).question_count == 15
    finally:
        session.close()
        engine.dispose()


def test_duplicate_or_rejected_questions_do_not_pass_validation():
    engine, session, learner = _session()
    try:
        profile = session.query(DBProfileSnapshot).filter_by(
            owner_public_id=learner.public_id,
        ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).first()
        course = diagnostic_generation._readable_course(session, course_id=COURSE_ID, user=learner)
        scope = _generation_scope(session, course=course, profile=profile, question_count=15)
        duplicate = _generated_payload(scope, 15)
        duplicate["questions"][1]["prompt"] = duplicate["questions"][0]["prompt"]
        with pytest.raises(DiagnosticGenerationError) as duplicate_error:
            _validate_generated_set(
                duplicate,
                count=15,
                quotas=_question_type_quotas(15),
                scope=scope,
            )
        assert duplicate_error.value.code == "diagnostic_duplicate_question"

        generated = _validate_generated_set(
            _generated_payload(scope, 15),
            count=15,
            quotas=_question_type_quotas(15),
            scope=scope,
        )
        rejected = _approved_review(generated).model_dump(mode="json")
        rejected["status"] = "rejected"
        rejected["items"][0].update({
            "verdict": "rejected",
            "source_support": "unsupported",
            "public_note": "来源没有支持该答案。",
        })
        with pytest.raises(DiagnosticGenerationError) as review_error:
            _validate_review(rejected, generated=generated)
        assert review_error.value.code == "diagnostic_review_rejected"
    finally:
        session.close()
        engine.dispose()


def test_entry_diagnostic_frontend_exposes_only_required_counts_and_public_workflow():
    source = ENTRY_DIAGNOSTIC.read_text(encoding="utf-8")
    for marker in (
        "const questionCount = ref(15)",
        '<option :value="15">15 题</option>',
        '<option :value="20">20 题</option>',
        '<option :value="25">25 题</option>',
        "AI 定制生成诊断题",
        "校验题量、题型与来源",
        "独立模型逐题审核",
        "true_false: '判断题'",
        "single_choice: '选择题'",
        "short_answer: '简答题'",
        "count-adjustment",
    ):
        assert marker in source
    for removed in (
        '<option :value="3">3 题</option>',
        '<option :value="5">5 题</option>',
        '<option :value="8">8 题</option>',
        '<option :value="10">10 题</option>',
        "组合诊断题组",
    ):
        assert removed not in source
    assert "私有推理" in source
    assert "answer_key" not in source and "reference_answer" not in source


def test_preflight_expands_supported_question_tier_for_larger_course_scope(monkeypatch):
    engine, session, learner = _session()
    try:
        profile = session.query(DBProfileSnapshot).filter_by(
            owner_public_id=learner.public_id,
        ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).first()
        points = [
            {"id": f"ai-kp-{index:02d}", "title": f"人工智能知识点 {index:02d}", "level": "core", "sourceRefIds": [f"ai-ref-{index:02d}"], "minimumQuestionCount": 1, "crossEvidenceTarget": 1}
            for index in range(19)
        ]
        session.add_all([
            DBKnowledgePoint(
                id=point["id"],
                domain_pack="ai-test",
                code=point["id"],
                version="1",
                title=point["title"],
                level="core",
                status="active",
            )
            for point in points
        ])
        session.commit()

        def fake_scope(_session, *, question_count, **_kwargs):
            selected = points[:question_count]
            return {
                "knowledgePoints": selected,
                "coverageGap": points[question_count:],
                "crossEvidencePointIds": [],
                "sources": [{"sourceRefId": f"ai-ref-{index:02d}", "sourceDocumentId": "ai-document", "knowledgePointIds": [point["id"]], "title": "AI课程资料", "location": f"第 {index + 1} 页", "contentHash": "a" * 64, "documentContentHash": "b" * 64, "chapterId": "ai-chapter", "chapterTitle": "人工智能基础", "quote": "课程原文"} for index, point in enumerate(points)],
                "targetDifficulty": 0.5,
            }

        monkeypatch.setattr(diagnostic_generation, "_generation_scope", fake_scope)
        preflight = diagnostic_preflight(
            session,
            user=learner,
            course_id=COURSE_ID,
            question_count=15,
        )
        assert preflight["requestedQuestionCount"] == 15
        assert preflight["expectedQuestionCount"] == 20
        assert preflight["selectedQuestionCount"] == 20
        assert preflight["questionCountAdjusted"] is True
        assert preflight["canGenerate"] is True
        assert len(preflight["coverage"]["knowledgePoints"]) == 19
        assert preflight["coverage"]["coverageGap"] == []
    finally:
        session.close()
        engine.dispose()


def test_generation_persists_adjusted_count_and_full_coverage(monkeypatch):
    engine, session, learner = _session()
    try:
        points = [
            {"id": f"ai-kp-{index:02d}", "title": f"人工智能知识点 {index:02d}", "level": "core", "sourceRefIds": [f"ai-ref-{index:02d}"], "minimumQuestionCount": 1, "crossEvidenceTarget": 1}
            for index in range(19)
        ]
        session.add_all([
            DBKnowledgePoint(
                id=point["id"],
                domain_pack="ai-test-generation",
                code=point["id"],
                version="1",
                title=point["title"],
                level="core",
                status="active",
            )
            for point in points
        ])
        session.commit()

        def fake_scope(_session, *, question_count, **_kwargs):
            return {
                "knowledgePoints": points[:question_count],
                "coverageGap": points[question_count:],
                "crossEvidencePointIds": [],
                "sources": [{"sourceRefId": f"ai-ref-{index:02d}", "sourceDocumentId": "ai-document", "knowledgePointIds": [point["id"]], "title": "AI课程资料", "location": f"第 {index + 1} 页", "contentHash": "a" * 64, "documentContentHash": "b" * 64, "chapterId": "ai-chapter", "chapterTitle": "人工智能基础", "quote": "课程原文"} for index, point in enumerate(points)],
                "targetDifficulty": 0.5,
            }

        async def generated_and_reviewed(_session, *, count, scope, **_kwargs):
            generated = _validate_generated_set(
                _generated_payload(scope, count),
                count=count,
                quotas=_question_type_quotas(count),
                scope=scope,
            )
            return generated, _approved_review(generated), {
                "model": "deepseek-v4-flash",
                "generationCallId": "test-adjusted-generate",
                "reviewCallId": "test-adjusted-review",
                "profileSnapshotId": "profile-adjusted",
                "profileVersion": "test",
            }

        monkeypatch.setattr(diagnostic_generation, "_generation_scope", fake_scope)
        monkeypatch.setattr(diagnostic_generation, "_generate_and_review", generated_and_reviewed)
        row, created = generate_diagnostic_blueprint(
            session,
            user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, "p1-b05-adjusted-count", 15),
            llm=_PolicyLLM(),
        )
        session.commit()
        payload = diagnostic_blueprint_payload(session, row)
        assert created is True
        assert row.question_count == 20
        assert len(payload["questions"]) == 20
        assert len(payload["knowledgePointCoverage"]) == 19
        assert row.review_decision["requestedQuestionCount"] == 15
        assert row.review_decision["selectedQuestionCount"] == 20
        assert row.review_decision["questionCountAdjusted"] is True
    finally:
        session.close()
        engine.dispose()
