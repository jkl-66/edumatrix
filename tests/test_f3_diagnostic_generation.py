from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.diagnostic_api as diagnostic_api
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBDiagnosticBlueprint,
    DBProfileSnapshot,
    DBQuizRecord,
    DBSourceRef,
    DBUser,
)
from app.diagnostic_api import DiagnosticGenerateRequest
from app.diagnostic_generation import (
    DiagnosticBlueprintRequest,
    DiagnosticGenerationError,
    diagnostic_blueprint_payload,
    diagnostic_preflight,
    generate_diagnostic_blueprint,
)
from app.migrations import MIGRATIONS


COURSE_ID = "demo-course-rag-trust-v1"


class _DiagnosticLLM:
    provider = "openai"
    model = "deepseek-v4-flash"
    thinking_mode = "enabled"
    reasoning_effort = "max"

    def __init__(self):
        self.calls = []

    async def generate(self, system_prompt, user_prompt, *, role):
        self.calls.append(role)
        payload = json.loads(user_prompt)
        if role == "入学诊断审核":
            questions = payload["generated_set"]["questions"]
            return json.dumps({
                "status": "approved",
                "decision_summary": "题量、来源、答案和画像难度均已逐题核对。",
                "items": [
                    {
                        "item_id": item["item_id"],
                        "verdict": "approved",
                        "source_support": "supported",
                        "answer_consistency": "consistent",
                        "profile_fit": "fit",
                        "public_note": "来源与答案一致。",
                    }
                    for item in questions
                ],
            }, ensure_ascii=False)

        request = payload["request"]
        points = payload["target_knowledge_points"]
        sources = payload["authorized_sources"]
        question_types = [
            question_type
            for question_type, total in request["question_type_quotas"].items()
            for _ in range(total)
        ]
        questions = []
        coverage = {point["id"]: 0 for point in points}
        for index, question_type in enumerate(question_types):
            point = points[index % len(points)]
            source = next(item for item in sources if point["id"] in item["knowledge_point_ids"])
            common = {
                "item_id": f"Q{index + 1:02d}",
                "question_type": question_type,
                "prompt": f"第 {index + 1} 题：根据课程来源判断 {point['title']} 的适用边界。",
                "primary_knowledge_point_id": point["id"],
                "source_ref_id": source["source_ref_id"],
                "diagnostic_dimension": ("theory", "application", "engineering_judgment")[index % 3],
                "bloom_level": "apply" if index % 3 else "understand",
                "difficulty": 0.5,
                "explanation": f"依据 {source['location']} 的课程内容进行判断。",
            }
            if question_type == "true_false":
                common["answer"] = True
            elif question_type == "single_choice":
                common.update({"options": ["正确边界", "忽略来源", "跳过验证", "替换课程"], "answer": "A"})
            else:
                common.update({
                    "reference_answer": "说明输入、边界、验证方法和课程来源。",
                    "rubric": [
                        {"id": "scope", "label": "概念边界", "weight": 0.5},
                        {"id": "evidence", "label": "来源证据", "weight": 0.5},
                    ],
                })
            questions.append(common)
            coverage[point["id"]] += 1
        return json.dumps({
            "profile_adaptation_summary": "按当前画像的基础和目标设置中等难度并覆盖全部目标知识点。",
            "coverage_plan": [
                {"knowledge_point_id": point["id"], "question_count": coverage[point["id"]], "rationale": "覆盖当前课程起点。"}
                for point in points
            ],
            "questions": questions,
        }, ensure_ascii=False)


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _learner(session):
    seed_competition_demo(session)
    return session.query(DBUser).filter_by(username="lzz").one()


def test_preflight_uses_profile_course_sources_and_exact_mixed_question_quota():
    engine, session = _session()
    try:
        learner = _learner(session)
        payload = diagnostic_preflight(
            session,
            user=learner,
            course_id=COURSE_ID,
            question_count=15,
        )
        assert payload["canGenerate"] is True
        assert payload["course"]["id"] == COURSE_ID
        assert payload["profileBasis"]["id"]
        assert payload["expectedQuestionCount"] == 15
        assert payload["estimatedMinutes"] == 30
        assert payload["coverage"]["sourceCount"] >= 4
        assert 3 <= len(payload["coverage"]["knowledgePoints"]) <= 15
        assert payload["coverage"]["questionTypes"] == {
            "true_false": 5,
            "single_choice": 5,
            "short_answer": 5,
        }
        assert payload["modelPolicy"] == {
            "model": "deepseek-v4-flash",
            "thinking": "enabled",
            "reasoningEffort": "max",
            "allowFallback": False,
        }
    finally:
        session.close()
        engine.dispose()


def test_generation_is_idempotent_traceable_profile_adaptive_and_hides_answers():
    engine, session = _session()
    try:
        learner = _learner(session)
        profile = session.query(DBProfileSnapshot).filter_by(
            owner_public_id=learner.public_id,
        ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).first()
        legacy_quiz_count_before = session.query(DBQuizRecord).count()
        llm = _DiagnosticLLM()
        request = DiagnosticBlueprintRequest(COURSE_ID, "f3-diagnostic-idempotent-001", 15)
        first, created = generate_diagnostic_blueprint(session, user=learner, request=request, llm=llm)
        session.commit()
        replay, replay_created = generate_diagnostic_blueprint(session, user=learner, request=request, llm=llm)
        payload = diagnostic_blueprint_payload(session, first)

        assert created is True and replay_created is False
        assert replay.id == first.id
        assert session.query(DBDiagnosticBlueprint).count() == 1
        assert first.profile_snapshot_id == profile.id
        assert first.difficulty_bands["targetDifficulty"] == pytest.approx(0.511, abs=0.001)
        assert all(first.difficulty_bands["questionKinds"][kind] >= 1 for kind in (
            "theory", "application", "engineering_judgment",
        ))
        assert first.difficulty_bands["questionTypes"] == {
            "true_false": 5,
            "single_choice": 5,
            "short_answer": 5,
        }
        assert first.question_count == 15
        assert 3 <= len(first.knowledge_point_coverage) <= 15
        assert len(first.source_refs) >= 3
        assert [item["key"] for item in first.generation_stages] == ["analysis", "generation", "validation", "review"]
        assert first.review_decision["checks"]["answerKeyHidden"] == "passed"
        assert first.review_decision["model"] == "deepseek-v4-flash"
        assert llm.calls == ["入学诊断出题", "入学诊断审核"]
        serialized = json.dumps(payload, ensure_ascii=False).lower()
        assert "answer_key" not in serialized and "scoring_rule" not in serialized
        assert "reference_answer" not in serialized
        assert set(item["diagnosticKind"] for item in payload["questions"]) == {
            "theory", "application", "engineering_judgment",
        }
        assert {item["questionType"] for item in payload["questions"]} == {
            "true_false", "single_choice", "short_answer",
        }
        assert session.query(DBQuizRecord).count() == legacy_quiz_count_before
    finally:
        session.close()
        engine.dispose()


def test_missing_course_source_quotes_block_without_model_or_partial_blueprint():
    engine, session = _session()
    try:
        learner = _learner(session)
        for source in session.query(DBSourceRef).all():
            source.quote = ""
        session.commit()

        llm = _DiagnosticLLM()
        with pytest.raises(DiagnosticGenerationError) as blocked:
            generate_diagnostic_blueprint(
                session,
                user=learner,
                request=DiagnosticBlueprintRequest(COURSE_ID, "f3-diagnostic-filter-001", 15),
                llm=llm,
            )
        assert blocked.value.code == "diagnostic_sources_insufficient"
        assert llm.calls == []
        assert session.query(DBDiagnosticBlueprint).count() == 0
    finally:
        session.close()
        engine.dispose()


def test_missing_profile_or_required_dimension_blocks_generation_with_recovery_reason():
    engine, session = _session()
    try:
        _learner(session)
        newcomer = DBUser(
            public_id="usr-f3-newcomer",
            username="f3-newcomer",
            hashed_password="not-used",
            role="student",
        )
        session.add(newcomer)
        session.commit()
        preflight = diagnostic_preflight(session, user=newcomer, course_id=COURSE_ID, question_count=15)
        assert preflight["canGenerate"] is False
        assert any("画像" in blocker for blocker in preflight["blockers"])
        with pytest.raises(DiagnosticGenerationError) as missing_profile:
            generate_diagnostic_blueprint(
                session,
                user=newcomer,
                request=DiagnosticBlueprintRequest(COURSE_ID, "f3-no-profile-001", 15),
                llm=_DiagnosticLLM(),
            )
        assert missing_profile.value.code == "diagnostic_profile_required"

        learner = session.query(DBUser).filter_by(username="lzz").one()
        for source in session.query(DBSourceRef).all():
            source.quote = ""
        session.commit()
        with pytest.raises(DiagnosticGenerationError) as missing_sources:
            generate_diagnostic_blueprint(
                session,
                user=learner,
                request=DiagnosticBlueprintRequest(COURSE_ID, "f3-no-theory-001", 15),
                llm=_DiagnosticLLM(),
            )
        assert missing_sources.value.code == "diagnostic_sources_insufficient"
    finally:
        session.close()
        engine.dispose()


def test_student_only_api_and_blueprint_owner_boundary(monkeypatch):
    engine, session = _session()
    try:
        learner = _learner(session)
        outsider = DBUser(
            public_id="usr-f3-outsider",
            username="f3-outsider",
            hashed_password="not-used",
            role="student",
        )
        teacher = DBUser(
            public_id="usr-f3-teacher",
            username="f3-teacher",
            hashed_password="not-used",
            role="teacher",
        )
        session.add_all([outsider, teacher])
        session.commit()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return await asyncio.to_thread(operation, session, *args, **kwargs)

        monkeypatch.setattr(diagnostic_api, "run_db_op", isolated_run_db_op)
        monkeypatch.setattr(diagnostic_api, "build_diagnostic_llm", _DiagnosticLLM)
        response = asyncio.run(diagnostic_api.create_diagnostic_blueprint(
            DiagnosticGenerateRequest(
                course_id=COURSE_ID,
                idempotency_key="f3-api-owner-001",
                question_count=15,
            ),
            current_user=learner,
        ))
        assert response["created"] is True
        blueprint_id = response["blueprint"]["id"]

        with pytest.raises(HTTPException) as forbidden_owner:
            asyncio.run(diagnostic_api.get_diagnostic_blueprint(blueprint_id, current_user=outsider))
        assert forbidden_owner.value.status_code == 403
        with pytest.raises(HTTPException) as forbidden_role:
            asyncio.run(diagnostic_api.create_diagnostic_blueprint(
                DiagnosticGenerateRequest(
                    course_id=COURSE_ID,
                    idempotency_key="f3-api-teacher-001",
                    question_count=15,
                ),
                current_user=teacher,
            ))
        assert forbidden_role.value.status_code == 403
    finally:
        session.close()
        engine.dispose()


def test_latest_migration_installs_diagnostic_blueprint_table():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE diagnostic_blueprints")
        migration = next(item for item in MIGRATIONS if item.version == "20260812_066")
        migration.apply(connection)
    assert "diagnostic_blueprints" in inspect(engine).get_table_names()
    engine.dispose()
