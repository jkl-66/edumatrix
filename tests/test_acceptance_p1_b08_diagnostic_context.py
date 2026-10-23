from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.diagnostic_generation as diagnostic_generation
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBAssessmentQuestionVersion,
    DBCourse,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.diagnostic_report import _source_payload
from app.diagnostic_generation import (
    DiagnosticBlueprintRequest,
    DiagnosticGeneratedSet,
    DiagnosticReviewBundle,
    _question_type_quotas,
    _readable_course,
    diagnostic_blueprint_payload,
    diagnostic_course_catalog,
    diagnostic_preflight,
    generate_diagnostic_blueprint,
)


ROOT = Path(__file__).resolve().parents[1]
ENTRY_DIAGNOSTIC = ROOT / "frontend" / "src" / "views" / "EntryDiagnostic.vue"
COURSE_A = "demo-course-rag-trust-v1"
COURSE_B = "course-embedded-machine-learning-engineering-v2"


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
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    seed_competition_demo(session)
    learner = session.query(DBUser).filter_by(username="lzz").one()
    return engine, session, learner


def _generated_payload(scope: dict, count: int) -> dict:
    quotas = _question_type_quotas(count)
    kinds = ("theory", "application", "engineering_judgment")
    questions = []
    coverage = Counter()
    ordered_types = [kind for kind, total in quotas.items() for _ in range(total)]
    for index, question_type in enumerate(ordered_types):
        point = scope["knowledgePoints"][index % len(scope["knowledgePoints"])]
        source = next(item for item in scope["sources"] if point["id"] in item["knowledgePointIds"])
        item = {
            "item_id": f"B08-Q{index + 1:02d}",
            "question_type": question_type,
            "prompt": f"请说明 {point['title']} 的课程边界（第 {index + 1} 题）。",
            "primary_knowledge_point_id": point["id"],
            "source_ref_id": source["sourceRefId"],
            "diagnostic_dimension": kinds[index % 3],
            "bloom_level": "apply" if index % 3 else "understand",
            "difficulty": scope["targetDifficulty"],
            "explanation": f"依据 {source['location']} 的课程来源。",
        }
        if question_type == "true_false":
            item["answer"] = True
        elif question_type == "single_choice":
            item["options"] = ["冻结课程来源", "忽略来源", "替换课程", "跳过校验"]
            item["answer"] = "A"
        else:
            item["reference_answer"] = "回答课程范围、判断依据和来源位置。"
            item["rubric"] = [{"id": "evidence", "label": "证据可定位", "weight": 1.0}]
        questions.append(item)
        coverage[point["id"]] += 1
    return {
        "profile_adaptation_summary": "自评起点只用于调整诊断题难度先验。",
        "coverage_plan": [
            {"knowledge_point_id": point["id"], "question_count": coverage[point["id"]], "rationale": "覆盖当前课程知识点。"}
            for point in scope["knowledgePoints"]
        ],
        "questions": questions,
    }


def _approved_review(generated: DiagnosticGeneratedSet) -> DiagnosticReviewBundle:
    return DiagnosticReviewBundle.model_validate({
        "status": "approved",
        "decision_summary": "来源、答案和自评难度先验均已核对。",
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


def test_catalog_only_returns_authorized_current_courses_and_three_ratings():
    engine, session, learner = _session()
    try:
        foreign = DBUser(
            public_id="usr-b08-foreign",
            username="b08-foreign",
            hashed_password="not-used",
            role="teacher",
        )
        session.add(foreign)
        session.add(DBCourse(
            id="course-b08-private",
            version="private-1",
            title="未授权课程",
            visibility="private",
            status="published",
            owner_public_id=foreign.public_id,
            manifest_version="private-1",
        ))
        session.commit()

        catalog = diagnostic_course_catalog(session, user=learner)
        ids = {item["id"] for item in catalog["courses"]}
        assert {COURSE_A, COURSE_B}.issubset(ids)
        assert "course-b08-private" not in ids
        assert [item["value"] for item in catalog["selfRatingOptions"]] == [
            "foundation", "advanced", "mastered",
        ]
        with pytest.raises(diagnostic_generation.DiagnosticGenerationError) as denied:
            _readable_course(session, course_id="course-b08-private", user=learner)
        assert denied.value.status_code == 403
    finally:
        session.close()
        engine.dispose()


def test_two_courses_and_three_self_ratings_change_frozen_preflight_context():
    engine, session, learner = _session()
    try:
        snapshots = {}
        for course_id in (COURSE_A, COURSE_B):
            for rating in ("foundation", "advanced", "mastered"):
                value = diagnostic_preflight(
                    session,
                    user=learner,
                    course_id=course_id,
                    question_count=15,
                    self_rating=rating,
                )
                snapshots[(course_id, rating)] = value
                assert value["selfRating"] == rating
                assert value["course"]["version"]
                assert value["coverage"]["targetDifficulty"] is not None
        assert len({snapshots[(COURSE_A, rating)]["coverage"]["targetDifficulty"] for rating in ("foundation", "advanced", "mastered")}) == 3
        assert set(item["id"] for item in snapshots[(COURSE_A, "advanced")]["coverage"]["knowledgePoints"]) != set(
            item["id"] for item in snapshots[(COURSE_B, "advanced")]["coverage"]["knowledgePoints"]
        )
    finally:
        session.close()
        engine.dispose()


def test_generated_blueprint_keeps_course_version_profile_rating_and_sources_frozen(monkeypatch):
    engine, session, learner = _session()
    try:
        async def fake_generate_and_review(_session, *, course, profile, count, scope, self_rating, **_kwargs):
            generated = diagnostic_generation._validate_generated_set(
                _generated_payload(scope, count),
                count=count,
                quotas=_question_type_quotas(count),
                scope=scope,
            )
            return generated, _approved_review(generated), {
                "model": "deepseek-v4-flash",
                "generationCallId": "b08-generate",
                "reviewCallId": "b08-review",
                "profileSnapshotId": profile.id,
                "profileVersion": profile.profile_version,
            }

        monkeypatch.setattr(diagnostic_generation, "_generate_and_review", fake_generate_and_review)
        row, created = generate_diagnostic_blueprint(
            session,
            user=learner,
            request=DiagnosticBlueprintRequest(COURSE_A, "b08-frozen-context-001", 15, "advanced"),
            llm=_PolicyLLM(),
        )
        session.commit()
        original = dict(row.review_decision["contextSnapshot"])
        assert created is True
        assert original["course"]["version"] == "competition-demo-rag-1.0.0"
        assert original["profile"]["id"] == row.profile_snapshot_id
        assert original["selfRating"] == "advanced"
        assert original["sourceRefs"]
        assert original["sourceSnapshotVersion"] == "p1-b08-source.v2"

        version = session.get(DBAssessmentQuestionVersion, row.question_version_ids[0])
        frozen_before = _source_payload(session, version, frozen_refs=original["sourceRefs"])
        assert frozen_before and frozen_before[0]["quote"]
        source_ref = session.get(DBSourceRef, version.source_ref_ids[0])
        source_document = session.get(DBSourceDocument, source_ref.source_document_id)
        source_ref.quote = "数据库中的新引文，不应覆盖本次诊断来源快照。"
        source_document.title = "数据库中的新标题"
        session.commit()
        frozen_after = _source_payload(session, version, frozen_refs=original["sourceRefs"])
        assert frozen_after == frozen_before

        course = session.get(DBCourse, COURSE_A)
        course.version = "changed-after-start"
        session.commit()
        payload = diagnostic_blueprint_payload(session, row)
        assert payload["course"]["version"] == "competition-demo-rag-1.0.0"
        assert payload["contextSnapshot"] == original
        assert payload["selfRating"] == "advanced"
    finally:
        session.close()
        engine.dispose()


def test_entry_diagnostic_frontend_exposes_course_rating_workflow_and_recovery_states():
    source = ENTRY_DIAGNOSTIC.read_text(encoding="utf-8")
    for marker in (
        "getDiagnosticCourses",
        "diagnostic-selection",
        "self_rating: selfRating.value",
        "基础",
        "进阶",
        "完全掌握",
        "生成测试",
        "完成作答",
        "提交分析",
        "diagnostic-courses-loading",
        "diagnostic-courses-empty",
        "generationFailed",
        "可重试",
    ):
        assert marker in source
    assert "DEFAULT_DEMO_COURSE_ID" not in source
