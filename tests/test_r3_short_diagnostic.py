from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

import app.m5_api as m5_api
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBAssessmentAbilityState,
    DBAssessmentAttempt,
    DBAssessmentGradingResult,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBAssessmentSelectionTrace,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBKnowledgePoint,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.m5_assessment_core import AttemptInput, CatSelectionInput


ROOT = Path(__file__).resolve().parents[1]
COURSE_ID = "demo-course-rag-trust-v1"
ASSESSMENT = ROOT / "frontend" / "src" / "views" / "AssessmentWorkspace.vue"
KNOWLEDGE = ROOT / "frontend" / "src" / "views" / "Knowledge.vue"


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _run(awaitable):
    return asyncio.run(awaitable)


def test_seed_exposes_five_source_bound_mirt_questions_and_repairs_legacy_contract():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        questions = (
            session.query(DBAssessmentQuestion)
            .filter_by(course_id=COURSE_ID)
            .order_by(DBAssessmentQuestion.id)
            .all()
        )
        assert len(questions) == 5
        for question in questions:
            version = session.get(DBAssessmentQuestionVersion, question.current_version_id)
            assert question.question_type == "true_false"
            assert question.status == "approved"
            assert version.options == ["是", "否"]
            assert version.answer_key.keys() == {"value"}
            assert isinstance(version.answer_key["value"], bool)
            assert version.scoring_rule["type"] == "exact"
            assert version.scoring_rule["version"] == "competition-diagnostic-v1"
            assert version.scoring_rule["diagnostic_dimension"] in {
                "theory", "application", "engineering_judgment",
            }
            assert len(version.irt_parameters["alpha_vector"]) == 3
            assert len(version.irt_parameters["beta_vector"]) == 3
            assert version.irt_parameters["gamma"] == 0.5
            assert version.expert_difficulty is not None
            assert version.primary_knowledge_point_id
            assert len(version.source_ref_ids) == 1
            source_ref = session.get(DBSourceRef, version.source_ref_ids[0])
            source_document = session.get(DBSourceDocument, source_ref.source_document_id)
            knowledge_point = session.get(DBKnowledgePoint, version.primary_knowledge_point_id)
            chapter = session.get(DBChapter, source_ref.chapter_id)
            chapter_link = session.query(DBChapterKnowledgePoint).filter_by(
                chapter_id=chapter.id,
                knowledge_point_id=knowledge_point.id,
            ).one_or_none()
            assert source_document.course_id == COURSE_ID
            assert chapter.course_id == COURSE_ID
            assert chapter_link is not None
            assert source_ref.content_hash and source_ref.quote
            assert version.content_hash

        legacy_question = questions[0]
        legacy_version = session.get(DBAssessmentQuestionVersion, legacy_question.current_version_id)
        legacy_version.answer_key = {"choice": "是"}
        legacy_version.irt_parameters = {"alpha": 1.0, "beta": 0.0, "gamma": 0.25}
        session.commit()
        legacy_version_id = legacy_version.id

        repaired = seed_competition_demo(session)
        session.refresh(legacy_question)
        corrected = session.get(DBAssessmentQuestionVersion, legacy_question.current_version_id)
        assert repaired.status == "repaired"
        assert corrected.id != legacy_version_id
        assert corrected.version_number == 2
        assert corrected.answer_key == {"value": False}
        assert len(corrected.irt_parameters["alpha_vector"]) == 3
        assert session.get(DBAssessmentQuestionVersion, legacy_version_id).answer_key == {"choice": "是"}
    finally:
        session.close()
        engine.dispose()


def test_catalog_cat_scoring_ability_recovery_idempotency_and_permissions(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        outsider = DBUser(
            public_id="usr-r3-diagnostic-outsider",
            username="r3-diagnostic-outsider",
            hashed_password="not-used",
            role="student",
        )
        session.add(outsider)
        session.commit()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)

        catalog = _run(m5_api.list_assessment_questions(course_id=COURSE_ID, current_user=learner))
        assert catalog["schema_version"] == "next.assessment-catalog.v2"
        assert len(catalog["items"]) == 5
        assert all(item["course_id"] == COURSE_ID for item in catalog["items"])
        assert len(catalog["attempts"]) == 2
        assert catalog["ability"]["response_count"] == 0
        assert catalog["ability_explanation"]["boundary"]
        for item in catalog["items"]:
            context = item["evidence_context"]
            assert context["source_status"] == "verified"
            assert context["knowledge_point"] and context["chapter"]
            assert context["sources"][0]["source_document_id"]
            assert context["sources"][0]["content_hash"]
            assert context["version_evidence"]["content_hash"] == item["content_hash"]

        completed = tuple(item["question_version_id"] for item in catalog["attempts"])
        selected = _run(m5_api.get_next_cat_question(
            CatSelectionInput(course_id=COURSE_ID, excluded_version_ids=completed),
            current_user=learner,
        ))
        assert selected["question"]["course_id"] == COURSE_ID
        assert selected["question"]["id"] not in completed
        assert selected["selection"]["algorithm_version"] == "mirt-d-optimal-v1"
        assert selected["selection"]["selected_information"] > 0
        assert selected["selection"]["trace_hash"]
        assert selected["selection"]["reason"]
        trace = session.get(DBAssessmentSelectionTrace, selected["selection"]["id"])
        assert trace and trace.course_scope == COURSE_ID
        assert trace.selected_question_version_id == selected["question"]["id"]

        version = session.get(DBAssessmentQuestionVersion, selected["question"]["id"])
        payload = AttemptInput(
            question_version_id=version.id,
            idempotency_key="r3-short-diagnostic-attempt-001",
            mode="diagnostic",
            answer={"value": version.answer_key["value"]},
        )
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        first = _run(m5_api.submit_assessment_attempt(request, payload, current_user=learner))
        assert first["created"] is True
        assert first["correct"] is True and first["score"] == 1.0
        assert first["grading"]["label"] == "服务端客观评分"
        assert first["grading"]["rubric_version"] == "competition-diagnostic-v1"
        assert first["ability_update"]["applied"] is True
        assert first["ability_update"]["before"]["response_count"] == 0
        assert first["ability_update"]["after"]["response_count"] == 1
        assert first["answer_explanation"]
        assert first["question"]["source_status"] == "verified"

        replay = _run(m5_api.submit_assessment_attempt(request, payload, current_user=learner))
        assert replay["created"] is False
        assert replay["id"] == first["id"]
        ability = session.query(DBAssessmentAbilityState).filter_by(
            owner_public_id=learner.public_id,
            course_scope=COURSE_ID,
        ).one()
        assert ability.response_count == 1
        assert session.query(DBAssessmentAttempt).filter_by(
            owner_public_id=learner.public_id,
            idempotency_key=payload.idempotency_key,
        ).count() == 1
        assert session.query(DBAssessmentGradingResult).filter_by(attempt_id=first["id"]).count() == 1

        restored = _run(m5_api.get_assessment_attempt(first["id"], current_user=learner))
        assert restored["id"] == first["id"]
        assert restored["ability_update"]["after"]["response_count"] == 1
        refreshed = _run(m5_api.list_assessment_questions(course_id=COURSE_ID, current_user=learner))
        assert any(item["id"] == first["id"] for item in refreshed["attempts"])
        assert refreshed["ability"]["response_count"] == 1

        session.get(DBCourse, COURSE_ID).visibility = "private"
        session.commit()
        with pytest.raises(HTTPException) as forbidden_question:
            _run(m5_api.get_assessment_question(version.id, current_user=outsider))
        assert forbidden_question.value.status_code == 403
        with pytest.raises(HTTPException) as forbidden_attempt:
            _run(m5_api.submit_assessment_attempt(request, payload, current_user=outsider))
        assert forbidden_attempt.value.status_code == 403
    finally:
        session.close()
        engine.dispose()


def test_invalid_source_reference_fails_closed_and_frontend_preserves_course_deep_links(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        question = session.query(DBAssessmentQuestion).filter_by(course_id=COURSE_ID).first()
        version = session.get(DBAssessmentQuestionVersion, question.current_version_id)
        version.source_ref_ids = ["missing-source-ref"]
        session.commit()

        async def isolated_run_db_op(operation, *args, **kwargs):
            return operation(session, *args, **kwargs)

        monkeypatch.setattr(m5_api, "run_db_op", isolated_run_db_op)
        payload = _run(m5_api.get_assessment_question(version.id, current_user=learner))
        assert payload["evidence_context"]["source_status"] == "unavailable"
        assert payload["evidence_context"]["sources"] == []

        assessment_source = ASSESSMENT.read_text(encoding="utf-8")
        knowledge_source = KNOWLEDGE.read_text(encoding="utf-8")
        for marker in (
            "DEFAULT_DEMO_COURSE_ID",
            "getM5NextCatQuestion",
            "completedVersionIds",
            'data-testid="cat-selection-reason"',
            'data-testid="question-evidence"',
            'data-testid="ability-change"',
            "document_id: source.source_document_id",
        ):
            assert marker in assessment_source
            for marker in (
                "KnowledgeCourseShelf",
                '@open-source="openCourseSource"',
                '@open-search-result="openCourseSearchResult"',
                "openCourseSource",
                "openCourseSearchResult",
                "source_document_id",
                "path: `/knowledge/documents/${encodeURIComponent(sourceDocumentId)}`",
            ):
                assert marker in knowledge_source
    finally:
        session.close()
        engine.dispose()
