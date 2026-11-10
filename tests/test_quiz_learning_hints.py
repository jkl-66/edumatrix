import json
import pytest

from app import resource_bundles as bundles
from app.competition_demo_seed import seed_competition_demo
from app.database import DBArtifact, DBArtifactVersion, DBUser, DBAssessmentQuestionVersion, DBLearningEvent
from app.m5_assessment import record_canonical_attempt_evidence
from app.m5_assessment_core import AttemptInput, record_attempt, get_or_create_ability_state
from app.m5_resources import resource_detail
from tests.test_f6_t01_quiz_resource import _session, _quiz_resource
from tests.test_pr_01_semantic_resource_generation import _FakeLiveBackend


@pytest.mark.parametrize("resource_type", ["quiz", "handout"])
def test_generated_hints_survive_save_review_and_learner_projection(monkeypatch, resource_type):
    class Backend(_FakeLiveBackend):
        async def generate(self, system_prompt, user_prompt, *, role):
            result = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            if role == "resource_generator":
                for row in result["quizQuestions"]:
                    row["hints"] = ["先找条件。", "沿计算顺序分步推导。", "检查结果单位。"]
            if role == "resource_reviewer":
                content = json.loads(json.loads(user_prompt)["candidates"][0]["content"])
                questions = content["questions"] if resource_type == "quiz" else content["miniQuiz"]
                assert questions[0]["hints"][1] == "沿计算顺序分步推导。"
            return json.dumps(result, ensure_ascii=False)

    engine, db = _session()
    try:
        seed_competition_demo(db);actor = db.query(DBUser).filter_by(username="lzz").one()
        monkeypatch.setattr(bundles, "_real_model_backend", lambda: Backend())
        task = bundles.create_generation_job(db, actor, course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07",
            profile_snapshot_id="demo-profile-lzz-v1", idempotency_key="hint-generation-chain", scope="single",
            items=[{"type":resource_type,"title":"逐步练习","source_ref_ids":["demo-ref-07"]}], learning_goal="观察提示和保存")
        result = bundles.execute_generation_job(db, actor, task["job_id"])
        assert result["status"] == "succeeded"
        artifact = db.get(DBArtifact, result["items"][0]["resource"]["resource_id"])
        db.expire_all()
        current = resource_detail(db, artifact)[resource_type]["current"]
        question = current["questions"][0] if resource_type == "quiz" else current["structured"]["miniQuiz"][0]
        assert question["hints"] == ["先找条件。", "沿计算顺序分步推导。", "检查结果单位。"]
        if resource_type == "quiz":
            assert "answer_key" not in question and "explanation" not in question
        else:
            assert question["explanation"] and isinstance(question["correctIndex"], int)
    finally:
        db.close();engine.dispose()


def test_guided_answer_preserves_score_without_inflating_mastery_and_new_independent_answer_counts():
    from flashcard_api import _has_completed_learning_evidence
    engine, db = _session()
    try:
        seed_competition_demo(db);actor=db.query(DBUser).filter_by(username="lzz").one()
        artifact=db.get(DBArtifact,_quiz_resource(db,actor))
        questions=resource_detail(db,artifact)["quiz"]["current"]["questions"]
        state=get_or_create_ability_state(db,owner_public_id=actor.public_id,course_id=artifact.course_id)
        before=state.response_count
        first=db.get(DBAssessmentQuestionVersion,questions[0]["id"])
        attempt,created=record_attempt(db,owner_public_id=actor.public_id,attempt=AttemptInput(
            question_version_id=first.id,idempotency_key="guided-practice-1",answer={"choice":first.answer_key["choice"],"used_hints":True,"hints_viewed":2}))
        evidence=record_canonical_attempt_evidence(db,attempt=attempt,user=actor)
        event=db.get(DBLearningEvent,evidence["event_id"])
        assert created and attempt.correct is True and attempt.score==1
        assert state.response_count==before
        assert not event.mastery_eligible and event.evidence_strength==0
        assert event.payload["used_hints"] is True and not evidence["mastery_changed"]
        assert not _has_completed_learning_evidence(db, owner_public_id=actor.public_id,
            concept=first.primary_knowledge_point_id, course_id=artifact.course_id)
        assert record_canonical_attempt_evidence(db,attempt=attempt,user=actor)["created"] is False
        second=db.get(DBAssessmentQuestionVersion,questions[1]["id"])
        independent,_=record_attempt(db,owner_public_id=actor.public_id,attempt=AttemptInput(
            question_version_id=second.id,idempotency_key="independent-practice-2",answer={"choice":second.answer_key["choice"]}))
        evidence=record_canonical_attempt_evidence(db,attempt=independent,user=actor)
        assert db.get(DBLearningEvent,evidence["event_id"]).mastery_eligible
        assert state.response_count==before+1
        assert _has_completed_learning_evidence(db, owner_public_id=actor.public_id,
            concept=second.primary_knowledge_point_id, course_id=artifact.course_id)
        assert not _has_completed_learning_evidence(db, owner_public_id=actor.public_id,
            concept=second.primary_knowledge_point_id, course_id='another-course')
    finally:
        db.close();engine.dispose()


def test_correction_restores_scores_but_only_new_questions_update_independent_ability():
    from app.database import DBAssessmentGradingResult
    from app.m5_assessment_core import QuestionVersionInput, create_question_version

    engine, db = _session()
    try:
        seed_competition_demo(db)
        actor = db.query(DBUser).filter_by(username="lzz").one()
        artifact = db.get(DBArtifact, _quiz_resource(db, actor))
        questions = resource_detail(db, artifact)["quiz"]["current"]["questions"]
        first = db.get(DBAssessmentQuestionVersion, questions[0]["id"])
        state = get_or_create_ability_state(db, owner_public_id=actor.public_id, course_id=artifact.course_id)
        count = state.response_count
        wrong = next(letter for letter in "ABCD" if letter != first.answer_key["choice"])
        original_input = AttemptInput(question_version_id=first.id, idempotency_key="correction-original",
            answer={"choice": wrong, "resource_version_id": artifact.current_version_id})
        original, _ = record_attempt(db, owner_public_id=actor.public_id, attempt=original_input)
        original_event = record_canonical_attempt_evidence(db, attempt=original, user=actor)
        assert state.response_count == count + 1
        for index in range(2):
            db.expire_all()  # also covers re-opening the saved question before correcting
            correction, _ = record_attempt(db, owner_public_id=actor.public_id, attempt=AttemptInput(
                question_version_id=first.id, idempotency_key=f"correction-after-feedback-{index}",
                answer={"choice": first.answer_key["choice"], "resource_version_id": artifact.current_version_id}))
            result = record_canonical_attempt_evidence(db, attempt=correction, user=actor)
            event = db.get(DBLearningEvent, result["event_id"])
            assert correction.score == 1 and correction.correct is True
            assert state.response_count == count + 1
            assert event.payload["evidence_kind"] == "correction"
            assert not event.mastery_eligible and event.completion_effect == "progress"
            assert not result["mastery_changed"]
            assert not record_canonical_attempt_evidence(db, attempt=correction, user=actor)["created"]

        # A version/resource copy of the same task cannot reset answer exposure.
        copied = create_question_version(db, owner_public_id=actor.public_id, course_id=artifact.course_id,
            question_type="single_choice", origin="manual", version=QuestionVersionInput(
                prompt=first.prompt, options=tuple(first.options), answer_key=first.answer_key,
                scoring_rule=first.scoring_rule, explanation=first.explanation,
                primary_knowledge_point_id=first.primary_knowledge_point_id))[1]
        copied_attempt, _ = record_attempt(db, owner_public_id=actor.public_id, attempt=AttemptInput(
            question_version_id=copied.id, idempotency_key="copied-question-correction",
            answer={"choice": copied.answer_key["choice"]}))
        assert db.query(DBAssessmentGradingResult).filter_by(attempt_id=copied_attempt.id).one().evidence["practice_context"]["kind"] == "correction"
        assert state.response_count == count + 1

        # Another question on the same point is still an independent check.
        second = db.get(DBAssessmentQuestionVersion, questions[1]["id"])
        fresh, _ = record_attempt(db, owner_public_id=actor.public_id, attempt=AttemptInput(
            question_version_id=second.id, idempotency_key="correction-new-independent",
            answer={"choice": second.answer_key["choice"]}))
        fresh_result = record_canonical_attempt_evidence(db, attempt=fresh, user=actor)
        assert db.get(DBLearningEvent, fresh_result["event_id"]).mastery_eligible
        assert state.response_count == count + 2

        projected = resource_detail(db, artifact)["quiz"]["current"]
        first_saved = projected["questions"][0]
        assert first_saved["latest_attempt"]["practice_kind"] == "correction"
        assert first_saved["latest_attempt"]["correct"] is True
        assert first_saved["attempts"][-1]["correct"] is False
        same, created = record_attempt(db, owner_public_id=actor.public_id, attempt=original_input)
        assert not created and same.score == 0
        assert record_canonical_attempt_evidence(db, attempt=same, user=actor)["event_id"] == original_event["event_id"]
        assert db.get(DBLearningEvent, original_event["event_id"]).mastery_eligible
    finally:
        db.close(); engine.dispose()
