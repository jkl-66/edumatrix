from __future__ import annotations

import json
from pathlib import Path

from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBArtifact,
    DBAssessmentAttempt,
    DBAssessmentQuestionVersion,
    DBLearningEvent,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.m5_assessment_core import AttemptInput, record_attempt
from app.m5_resources import resource_detail
from app.resource_bundles import create_generation_job, execute_generation_job_demo
from tests.test_f6_t03_code_sandbox_resource import _session


COURSE_ID = "demo-course-rag-trust-v1"


def _quiz_job(session, learner: DBUser, profile_id: str, source_id: str, key: str) -> dict:
    return create_generation_job(
        session,
        learner,
        course_id=COURSE_ID,
        knowledge_point_id="demo-kp-07",
        profile_snapshot_id=profile_id,
        idempotency_key=key,
        scope="single",
        items=[{
            "type": "quiz",
            "title": "对话单题语义练习",
            "source_ref_ids": [source_id],
            "completion_rule": "提交至少一道题并获得服务端判分",
        }],
        learning_goal="从当前课程来源完成一次可追溯练习",
    )


def _profile_copy(session, source: DBProfileSnapshot, profile_id: str, snapshot: dict) -> DBProfileSnapshot:
    row = DBProfileSnapshot(
        id=profile_id,
        owner_public_id=source.owner_public_id,
        legacy_student_id=source.legacy_student_id,
        profile_version=f"pr02-{profile_id}",
        snapshot=snapshot,
        content_hash=f"hash-{profile_id}",
        trace_id=f"trace-{profile_id}",
    )
    session.add(row)
    session.flush()
    return row


def test_dynamic_quiz_semantics_follow_profile_and_source_context() -> None:
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        original = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
        sources = (
            session.query(DBSourceRef)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .filter(DBSourceDocument.course_id == COURSE_ID)
            .order_by(DBSourceRef.id)
            .all()
        )
        assert original is not None and sources
        basic = _profile_copy(
            session,
            original,
            "pr02-profile-basic",
            {"preference": "分步练习", "current_level": "基础", "weak_points": ["检索质量"], "concept_mastery": {"demo-kp-07": 0.35}},
        )
        advanced = _profile_copy(
            session,
            original,
            "pr02-profile-advanced",
            {"preference": "迁移比较", "current_level": "熟练", "weak_points": [], "concept_mastery": {"demo-kp-07": 0.88}},
        )
        session.commit()

        first = _quiz_job(session, learner, basic.id, sources[0].id, "pr02-dynamic-basic")
        second = _quiz_job(session, learner, advanced.id, sources[-1].id, "pr02-dynamic-advanced")
        first_result = execute_generation_job_demo(session, learner, first["job_id"])
        second_result = execute_generation_job_demo(session, learner, second["job_id"])
        first_artifact = session.get(DBArtifact, first_result["items"][0]["resource"]["resource_id"])
        second_artifact = session.get(DBArtifact, second_result["items"][0]["resource"]["resource_id"])
        first_content = resource_detail(session, first_artifact)["quiz"]["current"]["structured"]
        second_content = resource_detail(session, second_artifact)["quiz"]["current"]["structured"]

        assert first_content["semanticContext"]["generation_mode"] == "deterministic_fallback"
        assert second_content["semanticContext"]["generation_mode"] == "deterministic_fallback"
        assert first_content["semanticContext"]["semantic_input_fingerprint"] != second_content["semanticContext"]["semantic_input_fingerprint"]
        first_questions = first_content["questions"]
        second_ids = second_content["questions"]
        first_versions = [session.get(DBAssessmentQuestionVersion, item["questionVersionId"]) for item in first_questions]
        second_versions = [session.get(DBAssessmentQuestionVersion, item["questionVersionId"]) for item in second_ids]
        # Question bodies live in immutable QuestionVersions; the resource keeps only references.
        assert first_content["sourceRefIds"] != second_content["sourceRefIds"] or first_content["adaptation"] != second_content["adaptation"]
        assert first_content["knowledgePoint"]["id"] == second_content["knowledgePoint"]["id"]
        assert first_questions
        assert second_ids
        assert all(first_versions) and all(second_versions)
        assert [row.prompt for row in first_versions] != [row.prompt for row in second_versions]
    finally:
        session.close()
        engine.dispose()


def test_canonical_attempt_is_idempotent_and_revision_preserves_history() -> None:
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
        source = (
            session.query(DBSourceRef)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .filter(DBSourceDocument.course_id == COURSE_ID)
            .first()
        )
        assert profile is not None and source is not None
        before_events = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()
        job = _quiz_job(session, learner, profile.id, source.id, "pr02-attempt-history")
        result = execute_generation_job_demo(session, learner, job["job_id"])
        artifact = session.get(DBArtifact, result["items"][0]["resource"]["resource_id"])
        question = resource_detail(session, artifact)["quiz"]["current"]["questions"][0]
        from app.database import DBAssessmentQuestionVersion
        question_version = session.get(DBAssessmentQuestionVersion, question["id"])
        assert question_version is not None
        answer = {"choice": question_version.answer_key["choice"]}
        first, created = record_attempt(
            session,
            owner_public_id=learner.public_id,
            attempt=AttemptInput(
                question_version_id=question_version.id,
                idempotency_key="pr02-attempt-stable-001",
                mode="practice",
                answer=answer,
            ),
        )
        replay, replay_created = record_attempt(
            session,
            owner_public_id=learner.public_id,
            attempt=AttemptInput(
                question_version_id=question_version.id,
                idempotency_key="pr02-attempt-stable-001",
                mode="practice",
                answer=answer,
            ),
        )
        changed, changed_created = record_attempt(
            session,
            owner_public_id=learner.public_id,
            attempt=AttemptInput(
                question_version_id=question_version.id,
                idempotency_key="pr02-attempt-stable-002",
                mode="practice",
                answer={"choice": "Z"},
            ),
        )
        session.commit()
        assert created is True
        assert replay_created is False
        assert replay.id == first.id
        assert changed_created is True
        assert changed.id != first.id
        assert session.query(DBAssessmentAttempt).filter_by(
            owner_public_id=learner.public_id,
            question_version_id=question_version.id,
            mode="practice",
        ).count() == 2
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() >= before_events
    finally:
        session.close()
        engine.dispose()


def test_chat_uses_inline_quiz_card_and_persists_follow_up_context() -> None:
    chat = Path("frontend/src/views/Chat.vue").read_text(encoding="utf-8")
    card = Path("frontend/src/components/InlineQuizCard.vue").read_text(encoding="utf-8")
    assert "import InlineQuizCard" in chat
    assert "@follow-up=\"handleQuizFollowUp\"" in chat
    assert "@submitted=\"handleQuizSubmitted\"" in chat
    assert "submitM5AssessmentAttempt" in card
    assert "attemptId" in chat
    assert "resourceId" in chat
    assert "question_version_id" in card
