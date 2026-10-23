from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text

import app.diagnostic_report as diagnostic_report
import app.m5_exam_core as exam_core
import app.m5_api as m5_api
from app.database import (
    DBAssessmentAttempt,
    DBAssessmentGradingResult,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBProfileSnapshot,
)
from app.m5_assessment_core import (
    AIGradingOutput,
    AssessmentCoreError,
    AttemptInput,
    RubricCriterionResult,
    persist_ai_grading,
    record_attempt,
)
from app.migrations import _allow_pending_assessment_scores
from tests.test_f3_diagnostic_report import _session as diagnostic_session, _submitted_diagnostic
from tests.test_f6_t06_formal_exam import _configuration, _fixture


class GovernedLLM:
    model = "deepseek-v4-flash"
    thinking_mode = "enabled"
    reasoning_effort = "max"


def _grading_payload():
    return {
        "criteria": [{
            "criterion_id": "scope",
            "score": 0.8,
            "evidence": ["回答覆盖课程范围"],
            "justification": "核心范围判断正确",
            "improvement": "补充边界条件",
        }],
        "confidence": 0.9,
        "summary": "AI 已依据冻结量规完成评分。",
        "improvement_plan": ["补充一个课程来源例子"],
    }


def test_ai_grading_output_normalizes_observed_deepseek_rubric_aliases():
    output = AIGradingOutput.model_validate({
        "criteria": [{
            "id": "scope",
            "label": "范围覆盖",
            "score": 0.75,
            "evidence": "回答覆盖课程范围",
            "reason": "核心范围判断正确",
            "suggestion": "补充边界条件",
        }],
        "confidence": 0.9,
        "summary": "模型已完成评分。",
        "improvement_plan": "补充一个课程来源例子",
    })
    assert output.criteria[0].criterion_id == "scope"
    assert output.criteria[0].evidence == ("回答覆盖课程范围",)
    assert output.criteria[0].justification == "核心范围判断正确"
    assert output.criteria[0].improvement == "补充边界条件"
    assert output.improvement_plan == ("补充一个课程来源例子",)


def test_diagnostic_subjective_grade_enters_report_and_profile(monkeypatch):
    engine, session = diagnostic_session()
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        version_id = blueprint.question_version_ids[-1]
        version = session.get(DBAssessmentQuestionVersion, version_id)
        question = session.get(DBAssessmentQuestion, version.question_id)
        question.question_type = "short_answer"
        version.answer_key = {"reference_answer": "参考答案"}
        version.scoring_rule = {
            "version": "rubric-ml-v1", "correct_threshold": 0.6,
            "criteria": [{"id": "scope", "label": "范围覆盖", "weight": 1}],
        }
        blueprint.generation_stages = [{"key": "generated", "status": "completed"}]
        session.commit()

        async def fake_gateway(*_args, **kwargs):
            operation = kwargs["operation"]
            if operation == "diagnostic_subjective_grading":
                payload = _grading_payload()
            else:
                items = json.loads(kwargs["user_prompt"])["items"]
                payload = {
                    "status": "completed",
                    "items": [{
                        "question_version_id": item["question_version_id"],
                        "claim": "模型依据本次作答和课程来源形成结论。",
                        "judgment_basis": "逐项核对评分状态与授权来源。",
                        "explanation": "该解释由模型结合当前题目和来源生成。",
                        "source_ref_ids": [item["sources"][0]["id"]] if item["sources"] else [],
                        "confidence": 0.9,
                        "status": "supported" if item["sources"] else "insufficient_evidence",
                    } for item in items],
                }
            return SimpleNamespace(
                model="deepseek-v4-flash", fallback_used=False,
                trace_id="trace-noc-t02", call_id=f"call-{operation}",
                structured_output=payload,
            )

        monkeypatch.setattr(diagnostic_report, "execute_registered_structured_call", fake_gateway)
        report, _ = diagnostic_report.generate_diagnostic_report(
            session, user=learner, session_id=work.id,
            idempotency_key="noc-t02-diagnostic-001", llm=GovernedLLM(),
        )
        payload = diagnostic_report.diagnostic_report_payload(session, user=learner, row=report)
        evidence = next(item for item in payload["evidence"] if item["questionVersionId"] == version_id)
        assert evidence["grading"]["graderType"] == "ai"
        assert evidence["score"] == 0.8
        snapshot = session.get(DBProfileSnapshot, report.profile_snapshot_id)
        feedback = snapshot.snapshot["diagnostic_evidence"]["grading_feedback"]
        assert any(item["attempt_id"] == evidence["attemptId"] for item in feedback)
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_model_failure_keeps_attempt_pending_without_report(monkeypatch):
    engine, session = diagnostic_session()
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        version_id = blueprint.question_version_ids[-1]
        version = session.get(DBAssessmentQuestionVersion, version_id)
        question = session.get(DBAssessmentQuestion, version.question_id)
        question.question_type = "short_answer"
        version.answer_key = {"reference_answer": "参考答案"}
        version.scoring_rule = {
            "version": "rubric-ml-v1", "correct_threshold": 0.6,
            "criteria": [{"id": "scope", "label": "范围覆盖", "weight": 1}],
        }
        blueprint.generation_stages = [{"key": "generated", "status": "completed"}]
        session.commit()

        async def failing_gateway(*_args, **_kwargs):
            raise RuntimeError("provider unavailable")

        monkeypatch.setattr(diagnostic_report, "execute_registered_structured_call", failing_gateway)
        with pytest.raises(diagnostic_report.DiagnosticReportError) as error:
            diagnostic_report.generate_diagnostic_report(
                session,
                user=learner,
                session_id=work.id,
                idempotency_key="noc-t02-diagnostic-failure",
                llm=GovernedLLM(),
            )
        assert error.value.code == "diagnostic_subjective_grading_failed"
        attempt = session.query(DBAssessmentAttempt).filter_by(
            owner_public_id=learner.public_id,
            question_version_id=version_id,
        ).one()
        assert attempt.score is None
        assert attempt.correct is None
        assert attempt.grading_status == "pending"
        grading = session.query(DBAssessmentGradingResult).filter_by(attempt_id=attempt.id).one()
        assert grading.status == "failed"
        assert grading.score is None
        assert session.query(diagnostic_report.DBDiagnosticReport).filter_by(session_id=work.id).first() is None
    finally:
        session.close()
        engine.dispose()


def test_diagnostic_model_retry_creates_new_grading_version(monkeypatch):
    engine, session = diagnostic_session()
    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        version_id = blueprint.question_version_ids[-1]
        version = session.get(DBAssessmentQuestionVersion, version_id)
        question = session.get(DBAssessmentQuestion, version.question_id)
        question.question_type = "short_answer"
        version.answer_key = {"reference_answer": "参考答案"}
        version.scoring_rule = {
            "version": "rubric-ml-v1", "correct_threshold": 0.6,
            "criteria": [{"id": "scope", "label": "范围覆盖", "weight": 1}],
        }
        blueprint.generation_stages = [{"key": "generated", "status": "completed"}]
        session.commit()
        calls = {"grading": 0}

        async def retrying_gateway(*_args, **kwargs):
            operation = kwargs["operation"]
            if operation == "diagnostic_subjective_grading":
                calls["grading"] += 1
                if calls["grading"] == 1:
                    raise RuntimeError("provider unavailable")
                payload = _grading_payload()
            else:
                items = json.loads(kwargs["user_prompt"])["items"]
                payload = {
                    "status": "completed",
                    "items": [{
                        "question_version_id": item["question_version_id"],
                        "claim": "模型依据本次作答和课程来源形成结论。",
                        "judgment_basis": "逐项核对评分状态与授权来源。",
                        "explanation": "该解释由模型结合当前题目和来源生成。",
                        "source_ref_ids": [item["sources"][0]["id"]] if item["sources"] else [],
                        "confidence": 0.9,
                        "status": "supported" if item["sources"] else "insufficient_evidence",
                    } for item in items],
                }
            return SimpleNamespace(
                model="deepseek-v4-flash", fallback_used=False,
                trace_id=f"trace-retry-{calls['grading']}", call_id=f"call-{operation}",
                structured_output=payload,
            )

        monkeypatch.setattr(diagnostic_report, "execute_registered_structured_call", retrying_gateway)
        with pytest.raises(diagnostic_report.DiagnosticReportError):
            diagnostic_report.generate_diagnostic_report(
                session, user=learner, session_id=work.id,
                idempotency_key="noc-t02-diagnostic-retry-failure", llm=GovernedLLM(),
            )
        report, _ = diagnostic_report.generate_diagnostic_report(
            session, user=learner, session_id=work.id,
            idempotency_key="noc-t02-diagnostic-retry-success", llm=GovernedLLM(),
        )
        assert report is not None and calls["grading"] == 2
        rows = session.query(DBAssessmentGradingResult).filter_by(
            attempt_id=session.query(DBAssessmentAttempt).filter_by(
                question_version_id=version_id,
            ).one().id,
            grader_type="ai",
        ).order_by(DBAssessmentGradingResult.created_at, DBAssessmentGradingResult.id).all()
        assert [row.status for row in rows] == ["failed", "completed"]
        assert [row.rubric_version for row in rows] == ["rubric-ml-v1", "rubric-ml-v1:retry-1"]
    finally:
        session.close()
        engine.dispose()


def test_existing_sqlite_attempt_schema_allows_pending_score():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE assessment_attempts (id VARCHAR(64) PRIMARY KEY, score FLOAT NOT NULL)"
            ))
            _allow_pending_assessment_scores(connection)
            score_column = next(
                item for item in inspect(connection).get_columns("assessment_attempts")
                if item["name"] == "score"
            )
            assert score_column["nullable"] is True
            connection.execute(text(
                "INSERT INTO assessment_attempts (id, score) VALUES ('pending-1', NULL)"
            ))
    finally:
        engine.dispose()


def test_ai_grading_uses_immutable_grading_result_without_attempt_update():
    session, engine, learner, _completion = _fixture()
    try:
        version = session.query(DBAssessmentQuestionVersion).join(
            DBAssessmentQuestion,
            DBAssessmentQuestion.id == DBAssessmentQuestionVersion.question_id,
        ).filter(
            DBAssessmentQuestion.course_id == "course-f6",
            DBAssessmentQuestion.question_type == "short_answer",
        ).first()
        attempt, _ = record_attempt(
            session,
            owner_public_id=learner.public_id,
            attempt=AttemptInput(
                question_version_id=version.id,
                idempotency_key="noc-t02-immutable-attempt",
                mode="formal",
                answer={"text": "课程来源中的关键概念和判断依据。"},
            ),
        )
        criteria = tuple(
            RubricCriterionResult(
                criterion_id=item["id"],
                score=0.8,
                evidence=("依据课程来源完成判断。",),
                justification="回答覆盖该评分标准。",
                improvement="补充一个具体例子。",
            )
            for item in version.scoring_rule["criteria"]
        )
        result, _ = persist_ai_grading(
            session,
            attempt_id=attempt.id,
            output=AIGradingOutput(
                criteria=criteria,
                confidence=0.9,
                summary="AI 已依据冻结量规完成评分。",
                improvement_plan=("补充一个具体例子。",),
            ),
            trace_id="trace-noc-t02-immutable",
            created_by_public_id=learner.public_id,
        )
        assert result.status == "completed"
        assert attempt.score is None and attempt.correct is None and attempt.grading_status == "pending"
    finally:
        session.close()
        engine.dispose()


def test_intelligent_exam_model_errors_are_service_unavailable():
    response = m5_api._assessment_error(
        AssessmentCoreError("intelligent_exam_generation_failed", "live model unavailable")
    )
    assert response.status_code == 503
    assert response.detail["code"] == "intelligent_exam_generation_failed"


def test_intelligent_exam_generation_uses_live_model_and_source_bound_schema(monkeypatch):
    session, engine, learner, _completion = _fixture()
    try:
        config = exam_core.IntelligentExamConfigInput(**_configuration("noc-t02-exam-001"))
        context = exam_core.intelligent_exam_context(
            session, owner_public_id=learner.public_id, course_id=config.course_id,
        )
        assert context["external_model_required"] is True
        assert context["llm_generation_required"] is True

        async def fake_gateway(*_args, **kwargs):
            data = json.loads(kwargs["user_prompt"])
            counts = data["question_type_counts"]
            point = data["knowledge_points"][0]["id"]
            source = data["sources"][0]["id"]
            questions = []
            for question_type, count in counts.items():
                for _ in range(count):
                    if question_type == "single_choice":
                        questions.append({"question_type": question_type, "prompt": "依据课程来源选择正确结论。", "options": ["A", "B"], "answer_key": {"choice": "A"}, "scoring_rule": {"type": "exact"}, "primary_knowledge_point_id": point, "source_ref_ids": [source]})
                    elif question_type == "true_false":
                        questions.append({"question_type": question_type, "prompt": "判断课程来源中的结论。", "options": [], "answer_key": {"value": True}, "scoring_rule": {"type": "exact"}, "primary_knowledge_point_id": point, "source_ref_ids": [source]})
                    else:
                        questions.append({"question_type": question_type, "prompt": "请说明课程来源中的关键步骤。", "options": [], "answer_key": {"reference_answer": "依据来源说明关键步骤"}, "scoring_rule": {"version": "rubric-ml-v1", "criteria": [{"id": "scope", "label": "范围", "weight": 1}]}, "primary_knowledge_point_id": point, "source_ref_ids": [source]})
            return SimpleNamespace(model="deepseek-v4-flash", fallback_used=False, trace_id="trace-exam", call_id="call-exam", structured_output={"questions": questions})

        monkeypatch.setattr(exam_core, "execute_registered_structured_call", fake_gateway)
        payload = exam_core.build_intelligent_exam_input(session, owner_public_id=learner.public_id, config=config, llm=GovernedLLM())
        assert payload.generation_context["external_model_used"] is True
        assert payload.generation_context["generation_mode"] == "llm"
        assert all(payload_item.question_version_id for payload_item in payload.items)
        versions = [session.get(DBAssessmentQuestionVersion, item.question_version_id) for item in payload.items]
        assert all(session.get(DBAssessmentQuestion, version.question_id).origin == "ai_generated" for version in versions)
    finally:
        session.close()
        engine.dispose()
