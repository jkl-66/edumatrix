"""Traceable entry-diagnostic reports and their initial path handoff."""

from __future__ import annotations

import hashlib
import asyncio
import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from typing import Any, Literal

from pydantic import Field
from app.learner_output import LEARNER_FEEDBACK_INSTRUCTION, teacher_text, teaching_text
from app.profile_adaptation import grading_learning_needs

from app.database import (
    DBAssessmentAttempt,
    DBAssessmentGradingResult,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBCourse,
    DBDiagnosticBlueprint,
    DBDiagnosticReport,
    DBDiagnosticResponseDraft,
    DBDiagnosticSession,
    DBKnowledgePoint,
    DBLearningPath,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
    new_public_id,
)
from app.m5_assessment_core import (
    AIGradingOutput,
    AttemptInput,
    ai_grading_prompt,
    persist_ai_grading,
    persist_failed_ai_grading,
    record_attempt,
    is_diagnostic_abstention,
    learner_safe_explanation,
    learner_safe_prompt,
)
from app.m5_learning import confirm_plan
from app.path_draft import (
    PathDraftError,
    generate_textbook_path_draft,
    textbook_path_draft_payload,
)
from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, M5CapabilityError, OutputConstraints
from app.m5_gateway import execute_registered_structured_call


REPORT_VERSION = "f3.diagnostic-report.v1"
OBJECTIVE_TYPES = {"single_choice", "multiple_choice", "true_false", "fill_blank"}
UNDERSTANDING_LABELS = {
    "unfamiliar": "不熟悉",
    "partial": "有些理解",
    "mostly": "基本理解",
    "clear": "理解清楚",
}


class DiagnosticExplanationItem(StrictModel):
    question_version_id: str = Field(min_length=3, max_length=64)
    claim: str = Field(min_length=4, max_length=1200)
    judgment_basis: str = Field(min_length=4, max_length=2400)
    explanation: str = Field(min_length=8, max_length=4000)
    source_ref_ids: tuple[str, ...] = Field(default=(), max_length=16)
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["supported", "partially_supported", "insufficient_evidence"]


class DiagnosticExplanationBundle(StrictModel):
    status: Literal["completed", "partial"]
    items: tuple[DiagnosticExplanationItem, ...] = Field(min_length=1, max_length=25)


class DiagnosticReportError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _iso(value: Any) -> str | None:
    return f"{value.isoformat(timespec='seconds')}Z" if value else None


def _owned_session(session: Any, *, user: DBUser, session_id: str) -> DBDiagnosticSession:
    row = session.get(DBDiagnosticSession, session_id)
    if row is None:
        raise DiagnosticReportError("diagnostic_session_unknown", "诊断会话不存在。", status_code=404)
    if row.owner_public_id != user.public_id:
        raise DiagnosticReportError("diagnostic_session_forbidden", "无权访问该诊断报告。", status_code=403)
    if row.status != "submitted":
        raise DiagnosticReportError("diagnostic_report_not_ready", "请先提交全部诊断答案。")
    return row


def _report_for_session(session: Any, *, user: DBUser, session_id: str) -> DBDiagnosticReport | None:
    row = session.query(DBDiagnosticReport).filter_by(session_id=session_id).first()
    if row is not None and row.owner_public_id != user.public_id:
        raise DiagnosticReportError("diagnostic_report_forbidden", "无权访问该诊断报告。", status_code=403)
    return row


def _is_legacy_blueprint(blueprint: DBDiagnosticBlueprint) -> bool:
    return any(str(item.get("key")) == "legacy" for item in (blueprint.generation_stages or []) if isinstance(item, dict))


def _require_explanation_model(llm: Any) -> None:
    model = str(getattr(llm, "model", "")).strip()
    thinking = str(getattr(llm, "thinking_mode", "")).strip().lower()
    reasoning = str(getattr(llm, "reasoning_effort", "")).strip().lower()
    backend_name = llm.__class__.__name__.lower()
    if (
        model != "deepseek-v4-flash"
        or thinking != "enabled"
        or reasoning != "max"
        or "deterministic" in backend_name
        or "fallback" in backend_name
    ):
        raise DiagnosticReportError(
            "diagnostic_explanation_model_policy_invalid",
            "逐题诊断解析必须使用 deepseek-v4-flash、thinking enabled、reasoning max，且不允许回退模型。",
            status_code=503,
        )


def _validate_explanation_bundle(
    payload: dict[str, Any],
    *,
    evidence: list[dict[str, Any]],
    require_complete: bool = True,
) -> DiagnosticExplanationBundle:
    bundle = DiagnosticExplanationBundle.model_validate(payload)
    expected_ids = {str(item["questionVersionId"]) for item in evidence}
    actual_ids = [item.question_version_id for item in bundle.items]
    actual_id_set = set(actual_ids)
    if len(actual_ids) != len(actual_id_set) or not actual_id_set.issubset(expected_ids):
        raise DiagnosticReportError(
            "diagnostic_explanation_item_mismatch",
            "逐题解析包含重复题目或本次诊断之外的题目。",
            status_code=502,
        )
    if require_complete and actual_id_set != expected_ids:
        raise DiagnosticReportError(
            "diagnostic_explanation_incomplete",
            "逐题解析没有覆盖本次诊断的全部题目。",
            status_code=502,
        )
    source_ids_by_question = {
        str(item["questionVersionId"]): {str(source["id"]) for source in item.get("sources", [])}
        for item in evidence
    }
    for item in bundle.items:
        allowed = source_ids_by_question[item.question_version_id]
        if any(source_id not in allowed for source_id in item.source_ref_ids):
            raise DiagnosticReportError(
                "diagnostic_explanation_source_mismatch",
                "逐题解析引用了不属于本题的课程来源。",
                status_code=502,
            )
        if item.status in {"supported", "partially_supported"} and not item.source_ref_ids:
            raise DiagnosticReportError(
                "diagnostic_explanation_source_missing",
                "有依据的逐题解析必须绑定可定位课程来源。",
                status_code=502,
            )
    return bundle


def _grade_diagnostic_subjective_answers(
    session: Any,
    *,
    llm: Any,
    user: DBUser,
    course_id: str,
    attempts: list[DBAssessmentAttempt],
    frozen_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grade diagnostic subjective attempts before report/profile projection.

    The diagnostic report is the first durable boundary after submission.  A
    short answer therefore goes through the same frozen-rubric AI grader as
    the canonical assessment API, so the resulting grading row is available to
    both the report and the profile snapshot.
    """
    _require_explanation_model(llm)
    graded: dict[str, Any] = {}
    for attempt in attempts:
        if is_diagnostic_abstention(attempt.answer):
            continue
        version = session.get(DBAssessmentQuestionVersion, attempt.question_version_id)
        question = session.get(DBAssessmentQuestion, version.question_id) if version else None
        if version is None or question is None or question.question_type not in {"short_answer", "open_task"}:
            continue
        system_prompt, user_prompt, rubric_version, rubric = ai_grading_prompt(version, attempt.answer or {})
        previous = session.query(DBAssessmentGradingResult).filter_by(
            attempt_id=attempt.id, grader_type="ai",
        ).order_by(DBAssessmentGradingResult.created_at.desc(), DBAssessmentGradingResult.id.desc()).first()
        # A report retry must not score the same immutable submission again or
        # update ability twice. Failed/unfinished grades still take the normal
        # retry path; only the matching completed rubric can be reused.
        if (previous is not None and previous.status == "completed"
                and (previous.rubric_snapshot or {}).get("criteria") == rubric["criteria"]
                and (previous.evidence or {}).get("answer_hash") == _hash(attempt.answer)):
            graded[attempt.id] = previous
            continue
        prior_count = session.query(DBAssessmentGradingResult).filter(
            DBAssessmentGradingResult.attempt_id == attempt.id,
            DBAssessmentGradingResult.grader_type == "ai",
        ).count()
        grading_rubric_version = (
            rubric_version
            if prior_count == 0
            else f"{rubric_version}:retry-{prior_count}"
        )
        user_payload = json.loads(user_prompt)
        user_payload["course_sources"] = _source_payload(session, version, frozen_refs=frozen_refs)
        user_prompt = _canonical(user_payload)
        try:
            result = _run_async(execute_registered_structured_call(
                session,
                backend=llm,
                capability=Capability.QUIZ,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                role="入学诊断简答题评分",
                operation="diagnostic_subjective_grading",
                response_model=AIGradingOutput,
                owner_public_id=user.public_id,
                course_id=course_id,
                trace_id=f"diag-grade:{attempt.id}",
                output_constraints=OutputConstraints(
                    format="json",
                    max_length=60000,
                    source_scope=tuple(version.source_ref_ids or ()),
                    safety_boundary="Only the submitted diagnostic answer and its frozen rubric may be used.",
                ),
            ))
            if result.model != "deepseek-v4-flash" or result.fallback_used:
                raise DiagnosticReportError(
                    "diagnostic_grading_model_policy_invalid",
                    "入学诊断简答题评分未使用受治理的 deepseek-v4-flash 模型。",
                    status_code=503,
                )
            output = AIGradingOutput.model_validate(result.structured_output)
            from app.learning_generation_jobs import CURRENT_JOB, assert_generation_owner
            assert_generation_owner(session)
            grading, _ = persist_ai_grading(
                session,
                attempt_id=attempt.id,
                output=output,
                trace_id=result.trace_id,
                created_by_public_id=user.public_id,
                rubric_version_override=grading_rubric_version,
            )
            graded[attempt.id] = grading
            if CURRENT_JOB.get():
                session.commit()
        except DiagnosticReportError:
            raise
        except Exception as exc:
            # Keep the submitted attempt explicitly pending when the live
            # grader is unavailable.  The surrounding report transaction may
            # still roll back publication, but a direct caller can inspect the
            # failed grading evidence and retry without a fabricated score.
            persist_failed_ai_grading(
                session,
                attempt_id=attempt.id,
                rubric_version=grading_rubric_version,
                rubric_snapshot=rubric,
                trace_id=f"diag-grade:{attempt.id}",
                error_code="ai_grading_unavailable",
            )
            raise DiagnosticReportError(
                "diagnostic_subjective_grading_failed",
                "入学诊断简答题 AI 判分失败，报告未发布，请稍后重试。",
                status_code=502,
            ) from exc
    return graded


async def _generate_explanations(
    session: Any,
    *,
    llm: Any,
    user: DBUser,
    course_id: str,
    report_id: str,
    evidence: list[dict[str, Any]],
    learning_context: dict[str, Any] | None = None,
) -> tuple[DiagnosticExplanationBundle, dict[str, Any]]:
    _require_explanation_model(llm)
    schema = _canonical(DiagnosticExplanationBundle.model_json_schema())
    system_prompt = (
        "你是 EduMatrix 入学诊断逐题评估专家。只输出符合 JSON Schema 的原始 JSON 对象，不要 Markdown。"
        "必须针对给定题目、学习者本次作答、评分状态、理解程度和授权课程来源生成判断依据与系统解析，不能使用固定模板。"
        "选择题必须按本题冻结的选项解释字母，不能根据选项位置或其他题的标签猜测作答含义。"
        "结合参考答案、原解析与逐项评分解释本次表现，保留已确定的评分事实；"
        "原题解析将直接展示，不需要重新写一遍算式或标准解答；explanation只写与本次回答有关的补强建议。"
        "已完整答对时简短确认即可；没有实际缺口就不安排重复练习，也不要求改写正确的等价表达。"
        "总分达标不代表每个评分项都掌握，具体误解仍要清楚指出。"
        "区分实际回答能支持的误解与尚无法确定的原因，不能凭错误选项臆测学习者的思考过程。"
        "部分正确要指出具体已会和未会内容，不把方向正确夸成已经理解关键机制。"
        "下一步建议遵守已确认的工具、基础与时间条件；解释统计或模型评价时保留必要适用条件，"
        "数值编码可用于分类和概率预测，不能把类别不是连续数量说成禁止数值建模。"
        "只能引用输入中提供的 source_ref_id；证据不足时使用 insufficient_evidence 并明确限制结论。"
        "answer.response_status为not_yet表示学习者主动选择暂时不会；将其作为下一步学习起点。"
        "这类题只从具体数据或概念给出简短讲解和一个可执行的入门动作；没有作答就不推断其思考过程。"
        "如果个别题暂时无法完成，只返回已完成题并把 bundle status 设为 partial；系统会仅重试缺失题。"
        "不要输出 prompt、思维链、reasoning_content、密钥或内部日志。"
        + LEARNER_FEEDBACK_INSTRUCTION + f" JSON Schema: {schema}"
    )
    from app.learning_generation_jobs import component_cache
    cache, save = component_cache(session)
    cache_key = 'diagnostic-explanations:' + _hash([system_prompt, evidence, learning_context])
    saved = cache.get(cache_key) or {}
    completed = {key: DiagnosticExplanationItem.model_validate(value) for key, value in saved.get('items', {}).items()}
    pending = [item for item in evidence if item['questionVersionId'] not in completed]
    call_ids = list(saved.get('call_ids') or [])
    model = saved.get('model', '')
    # Labels alone (for example choice=B) cannot explain a shuffled option.
    # Load the immutable question version, never a later replacement question.
    question_context = {}
    for item in evidence:
        version = session.get(DBAssessmentQuestionVersion, item["questionVersionId"])
        question_context[item["questionVersionId"]] = {
            "question_type": item.get("questionType"),
            "options": deepcopy(version.options or []) if version else [],
            "reference_answer": deepcopy(version.answer_key or {}) if version else {},
            "reference_explanation": version.explanation if version else "",
            "grading": deepcopy(item.get("grading")),
        }
    for pass_index in range(2):
        if not pending:
            break
        public_items = [
            {
                "question_version_id": item["questionVersionId"],
                "attempt_id": item["attemptId"],
                "question": item["prompt"],
                **question_context[item["questionVersionId"]],
                "answer": item["answer"],
                "score": item["score"],
                "correct": item["correct"],
                "grading_status": item["gradingStatus"],
                "understanding_level": item["understandingLevel"],
                "knowledge_point": item["knowledgePoint"],
                "sources": [
                    {"id": source["id"], "title": source["title"], "location": source["location"], "quote": source["quote"]}
                    for source in item["sources"]
                ],
            }
            for item in pending
        ]
        user_prompt = _canonical({
            "task": "diagnostic_item_explanations" if pass_index == 0 else "diagnostic_item_explanations_retry",
            "report_id": report_id,
            "course_id": course_id,
            "learning_context": learning_context or {},
            "items": public_items,
        })
        try:
            result = await execute_registered_structured_call(
                session,
                backend=llm,
                capability=Capability.REPORT,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                role="入学诊断逐题评估",
                operation="p1_b07_diagnostic_explanations",
                response_model=DiagnosticExplanationBundle,
                response_validator=lambda value, current=pending: _validate_explanation_bundle(
                    value, evidence=current, require_complete=False,
                ),
                owner_public_id=user.public_id,
                course_id=course_id,
                trace_id=f"diag-eval:{report_id}:{pass_index + 1}",
                output_constraints=OutputConstraints(
                    format="json",
                    max_length=120000,
                    source_scope=tuple(sorted({source["id"] for item in pending for source in item["sources"]})),
                    safety_boundary="Only the submitted diagnostic answers and authorized course sources may be used.",
                ),
            )
        except DiagnosticReportError:
            raise
        except M5CapabilityError as exc:
            raise DiagnosticReportError(
                "diagnostic_explanation_generation_failed",
                "真实模型未能完成逐题诊断解析，请稍后重试。",
                status_code=502,
            ) from exc
        except Exception as exc:
            raise DiagnosticReportError(
                "diagnostic_explanation_generation_failed",
                "逐题诊断解析暂时失败，请稍后重试。",
                status_code=502,
            ) from exc
        bundle = _validate_explanation_bundle(result.structured_output, evidence=pending, require_complete=False)
        completed.update({item.question_version_id: item for item in bundle.items})
        call_ids.append(result.call_id)
        model = result.model
        save(cache_key, {'items': {key: value.model_dump(mode='json') for key, value in completed.items()},
                         'call_ids': call_ids, 'model': model})
        pending = [item for item in pending if item["questionVersionId"] not in completed]
        if not pending:
            break

    final_bundle = _validate_explanation_bundle(
        {
            "status": "completed" if not pending else "partial",
            "items": [completed[item["questionVersionId"]].model_dump(mode="json") for item in evidence if item["questionVersionId"] in completed],
        },
        evidence=evidence,
    )
    return final_bundle, {"model": model, "callId": call_ids[-1], "callIds": call_ids}


def _attach_explanations(
    report_data: dict[str, Any],
    *,
    bundle: DiagnosticExplanationBundle,
    call_meta: dict[str, str],
) -> dict[str, Any]:
    by_question = {item.question_version_id: item for item in bundle.items}
    completed = 0
    for item in report_data["evidence"]:
        evaluation = by_question[item["questionVersionId"]]
        item["judgmentBasis"] = evaluation.judgment_basis
        # Keep the reviewed solution; personalized commentary must not replace
        # its calculations with an independently paraphrased second solution.
        item["learningFeedback"] = evaluation.explanation
        item["errorType"] = {**item["errorType"], "basis": evaluation.judgment_basis}
        item["evaluation"] = {
            "status": evaluation.status,
            "claim": evaluation.claim,
            "confidence": evaluation.confidence,
            "sourceRefIds": list(evaluation.source_ref_ids),
        }
        completed += 1
    report_data["evaluation"] = {
        "status": bundle.status,
        "completedCount": completed,
        "totalCount": len(report_data["evidence"]),
        "model": call_meta["model"],
    }
    return report_data


def _source_payload(
    session: Any,
    version: DBAssessmentQuestionVersion,
    *,
    frozen_refs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    items = []
    frozen_by_id = {
        str(item.get("sourceRefId")): item
        for item in (frozen_refs or [])
        if isinstance(item, dict) and item.get("sourceRefId")
    }
    for ref_id in version.source_ref_ids or []:
        if frozen_refs is not None:
            frozen = frozen_by_id.get(str(ref_id))
            if frozen is None:
                continue
            location = frozen.get("location") or frozen.get("locationLabel") or "课程章节"
            items.append({
                "id": str(ref_id),
                "documentId": frozen.get("sourceDocumentId") or frozen.get("documentId") or "",
                "title": frozen.get("title") or "课程来源",
                "location": location,
                "locationLabel": location,
                "quote": (frozen.get("knowledgePointQuotes") or {}).get(version.primary_knowledge_point_id) or frozen.get("quote") or "",
                "contentHash": frozen.get("contentHash") or "",
                "documentContentHash": frozen.get("documentContentHash") or "",
            })
            continue
        ref = session.get(DBSourceRef, ref_id)
        if ref is None:
            continue
        document = session.get(DBSourceDocument, ref.source_document_id)
        items.append({
            "id": ref.id,
            "documentId": ref.source_document_id,
            "title": document.title if document else "课程来源",
            "location": ref.location_label or (f"第 {ref.page_number} 页" if ref.page_number else "课程章节"),
            "locationLabel": ref.location_label or (f"第 {ref.page_number} 页" if ref.page_number else "课程章节"),
            "quote": ref.quote or "",
            "contentHash": ref.content_hash,
        })
    return items


def _error_type(correct: bool | None, understanding_level: str | None) -> dict[str, str]:
    if correct is None:
        return {"code": "insufficient_evidence", "label": "证据不足", "basis": "该题尚无可靠评分结果。"}
    if correct:
        return {"code": "evidence_consistent", "label": "作答与自评一致", "basis": "评分证据支持本题理解。"}
    if understanding_level in {"mostly", "clear"}:
        return {
            "code": "confident_misunderstanding",
            "label": "高信心误判",
            "basis": "自评理解较高，但服务端评分未通过，需优先核对概念或策略。",
        }
    return {
        "code": "knowledge_gap_candidate",
        "label": "知识缺口候选",
        "basis": "自评与评分均显示当前证据不足，需回到来源补齐基础。",
    }


def _mastery_label(score: float | None) -> str:
    if score is None:
        return "未知"
    if score >= 0.8:
        return "表现稳定"
    if score >= 0.6:
        return "基本掌握"
    if score >= 0.4:
        return "仍需巩固"
    return "优先补齐"


def _difficulty_band(value: float | None) -> str:
    difficulty = float(value or 0.5)
    return "foundation" if difficulty < 0.35 else "standard" if difficulty < 0.65 else "stretch"


def _apply_learning_focus(report: dict[str, Any]) -> dict[str, Any]:
    """Derive learning priorities from scored parts without changing scores."""
    needs_by_point: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unassessed_points = set()
    for item in report.get("evidence", []):
        point_id = (item.get("knowledgePoint") or {}).get("id")
        if is_diagnostic_abstention(item.get("answer")):
            unassessed_points.add(point_id)
            continue
        needs = grading_learning_needs(item.get("grading"), explanation=str(item.get("explanation") or "")) if item.get("masteryEligible") else []
        item["learningNeeds"] = needs
        if not needs:
            continue
        needs_by_point[point_id].extend(needs)
        if item.get("correct"):
            confident_gap = needs[0]["score"] < 0.6 and item.get("understandingLevel") in {"mostly", "clear"}
            item["errorType"] = {
                "code": "confident_misunderstanding" if confident_gap else "partial_understanding",
                "label": "仍有关键误解" if confident_gap else "部分理解",
                "basis": needs[0]["basis"],
            }
    if not needs_by_point and not unassessed_points:
        return report
    for point in report.get("mastery", []):
        point_id = point.get("knowledgePointId")
        point["learningNeeds"] = needs_by_point.get(point_id, [])
        if point["learningNeeds"]:
            point["label"] = "仍有待补齐环节"
        elif point_id in unassessed_points and point.get("score") is not None:
            point["label"] = "部分已测"
    report["strengths"] = [point for point in report.get("mastery", [])
        if point.get("score") is not None and point["score"] >= 0.7
        and not point.get("learningNeeds") and point.get("knowledgePointId") not in unassessed_points]
    report["weaknesses"] = sorted([point for point in report.get("mastery", [])
        if point.get("score") is not None and (point["score"] < 0.6 or point.get("learningNeeds"))],
        key=lambda point: (point["score"], min([point["score"], *[need["score"] for need in point.get("learningNeeds", [])]])))
    report["blindSpots"] = [item for item in report.get("evidence", [])
        if (item.get("errorType") or {}).get("code") == "confident_misunderstanding"]
    summary = report.get("summary", {})
    summary["strongest"] = report["strengths"][0]["title"] if report["strengths"] else "继续通过练习确认"
    if report["weaknesses"]:
        priority = report["weaknesses"][0]
        summary["weakest"] = priority["title"]
        # A binary answer check records a wrong choice but does not diagnose
        # its cause. Prefer the actual rubric gap when both address this point.
        steps = sorted((need for need in priority.get("learningNeeds", []) if need.get("next_step", "").strip()),
                       key=lambda need: (need.get("criterion_id") == "answer_correctness", need["score"]))
        action = steps[0]["next_step"] if steps else "结合原题解析，完成一个新的独立练习。"
        summary["coreAdvice"] = f"先补齐“{priority['title']}”：{action}"
        if (summary.get("score") or 0) >= 0.8:
            summary["scoreLabel"] = "基础较稳，仍需补齐"
    return report


def _build_report_data(
    session: Any,
    *,
    work: DBDiagnosticSession,
    blueprint: DBDiagnosticBlueprint,
    attempts: list[DBAssessmentAttempt],
) -> dict[str, Any]:
    response_by_question = {
        item.question_version_id: item
        for item in session.query(DBDiagnosticResponseDraft).filter_by(session_id=work.id).all()
    }
    context_snapshot = (blueprint.review_decision or {}).get("contextSnapshot") or {}
    coverage_contract = context_snapshot.get("coverageContract") or {}
    attempt_by_question = {item.question_version_id: item for item in attempts}
    evidence = []
    mastery_inputs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    difficulty = {
        key: {"key": key, "label": label, "scored": 0, "correct": 0, "score": None}
        for key, label in (("foundation", "基础"), ("standard", "标准"), ("stretch", "进阶"))
    }
    for question_version_id in blueprint.question_version_ids or []:
        version = session.get(DBAssessmentQuestionVersion, question_version_id)
        question = session.get(DBAssessmentQuestion, version.question_id) if version else None
        response = response_by_question.get(question_version_id)
        attempt = attempt_by_question.get(question_version_id)
        grading = (
            session.query(DBAssessmentGradingResult)
            .filter_by(attempt_id=attempt.id)
            .order_by(DBAssessmentGradingResult.created_at.desc(), DBAssessmentGradingResult.id.desc())
            .first()
            if attempt else None
        )
        if version is None or question is None or response is None or attempt is None:
            continue
        knowledge = session.get(DBKnowledgePoint, version.primary_knowledge_point_id) if version.primary_knowledge_point_id else None
        score = grading.score if grading and grading.status == "completed" else (
            attempt.score if attempt.grading_status == "graded" else None
        )
        correct = grading.correct if grading and grading.status == "completed" else (
            attempt.correct if attempt.grading_status == "graded" else None
        )
        grading_payload = {
            "id": grading.id,
            "status": grading.status,
            "graderType": grading.grader_type,
            "rubricVersion": grading.rubric_version,
            "score": grading.score,
            "correct": grading.correct,
            "confidence": grading.confidence,
            "criterionResults": list(grading.criterion_results or []),
            "feedback": grading.feedback or "",
            "improvementAdvice": list(grading.improvement_advice or []),
        } if grading is not None else None
        grading_status = (
            "graded" if grading is not None and grading.status == "completed" else
            grading.status if grading is not None else
            "graded" if attempt.grading_status == "graded" else
            attempt.grading_status
        )
        # Keep the historical report contract's unknown label for an attempt
        # that has no grading row yet; a real AI failure has an explicit
        # ``failed`` grading row and remains visible as such.
        if grading is None and grading_status == "pending":
            grading_status = "unknown"
        context_snapshot = (blueprint.review_decision or {}).get("contextSnapshot") or {}
        frozen_refs = (
            list(context_snapshot.get("sourceRefs") or [])
            if context_snapshot.get("sourceSnapshotVersion") == "p1-b08-source.v2"
            else None
        )
        sources = _source_payload(session, version, frozen_refs=frozen_refs)
        # A score without a course source is still a grading observation, but
        # it is not accepted diagnostic evidence and must not feed mastery.
        evidence_eligible = score is not None and bool(sources)
        error_type = _error_type(correct if evidence_eligible else None, response.understanding_level)
        abstained = is_diagnostic_abstention(response.answer)
        if abstained:
            grading_status = "unassessed"
            error_type = {"code": "not_yet_learned", "label": "暂时不会", "basis": "你选择了暂时不会，可从这里开始学习；掌握程度待后续任务确认。"}
        item = {
            "questionVersionId": version.id,
            "attemptId": attempt.id,
            "gradingResultId": grading.id if grading else None,
            "questionType": question.question_type,
            "prompt": learner_safe_prompt(version.prompt, knowledge_point=knowledge.title if knowledge else ""),
            "answer": dict(response.answer or {}),
            "score": score,
            "correct": correct,
            "gradingStatus": grading_status if grading_status in {"completed", "failed", "needs_review", "pending", "graded", "unassessed"} else "unknown",
            "evidenceStatus": "self_reported_not_yet" if abstained else "accepted" if evidence_eligible else "insufficient_evidence",
            "masteryEligible": evidence_eligible,
            "understandingLevel": response.understanding_level,
            "understandingLabel": UNDERSTANDING_LABELS.get(response.understanding_level, "未标记"),
            "duration": response.duration_seconds,
            "difficulty": version.expert_difficulty,
            "knowledgePoint": {
                "id": knowledge.id if knowledge else version.primary_knowledge_point_id,
                "title": knowledge.title if knowledge else "未映射知识点",
            },
            "errorType": error_type,
            "judgmentBasis": error_type["basis"],
            "sources": sources,
            "explanation": learner_safe_explanation(
                version.explanation,
                prompt=version.prompt,
                options=version.options,
                answer_key=version.answer_key,
                question_type=question.question_type if question else "single_choice",
            ),
            "grading": grading_payload,
        }
        evidence.append(item)
        if knowledge and evidence_eligible:
            mastery_inputs[knowledge.id].append(item)
        if evidence_eligible:
            band = difficulty[_difficulty_band(version.expert_difficulty)]
            band["scored"] += 1
            band["correct"] += int(bool(correct))

    mastery = []
    for knowledge_point_id in dict.fromkeys(
        [str(item.get("id")) for item in blueprint.knowledge_point_coverage or [] if item.get("id")]
        + list(mastery_inputs)
    ):
        knowledge = session.get(DBKnowledgePoint, knowledge_point_id)
        items = mastery_inputs.get(knowledge_point_id, [])
        scored = [item for item in items if item["score"] is not None]
        score = round(sum(float(item["score"]) for item in scored) / len(scored), 4) if scored else None
        mastery.append({
            "knowledgePointId": knowledge_point_id,
            "title": knowledge.title if knowledge else "未映射知识点",
            "score": score,
            "label": _mastery_label(score),
            "evidenceCount": len(scored),
            "evidenceItemCount": len(items),
            "attemptIds": [item["attemptId"] for item in items],
            "questionVersionIds": [item["questionVersionId"] for item in items],
            "sourceRefIds": sorted({source["id"] for item in items for source in item["sources"]}),
            "status": "known" if score is not None else "unknown",
            "coverageStatus": "verified" if items else "unknown",
            "crossEvidence": len(items) >= 2,
        })
    for band in difficulty.values():
        band["score"] = round(band["correct"] / band["scored"], 4) if band["scored"] else None

    scored_evidence = [item for item in evidence if item["masteryEligible"]]
    overall_score = (
        round(sum(float(item["score"]) for item in scored_evidence) / len(scored_evidence), 4)
        if scored_evidence else None
    )
    strengths = [item for item in mastery if item["score"] is not None and item["score"] >= 0.7]
    weaknesses = [item for item in mastery if item["score"] is not None and item["score"] < 0.6]
    blind_spots = [
        item for item in evidence if item["errorType"]["code"] == "confident_misunderstanding"
    ]
    target_difficulty = float((blueprint.difficulty_bands or {}).get("targetDifficulty") or 0.48)
    strongest = strengths[0]["title"] if strengths else "暂未形成可确认强项"
    weakest = weaknesses[0]["title"] if weaknesses else "暂无明确薄弱点"
    advice = (
        f"先回到课程来源补齐“{weakest}”，完成短练习后再进入相邻章节。"
        if weaknesses else "沿当前教材顺序继续学习，并通过后续任务积累更充分证据。"
    )
    learning_starts = [item for item in evidence if is_diagnostic_abstention(item["answer"])]
    if not weaknesses and learning_starts:
        weakest = learning_starts[0]["knowledgePoint"]["title"]
        advice = f"从“{weakest}”的入门任务开始，再逐步学习你标记为暂时不会的内容。"
    return {
        "schemaVersion": REPORT_VERSION,
        "sessionId": work.id,
        "courseId": blueprint.course_id,
        "selfRating": (blueprint.review_decision or {}).get("selfRating"),
        "contextSnapshot": (blueprint.review_decision or {}).get("contextSnapshot"),
        "summary": {
            "score": overall_score,
            "scoredCount": len(scored_evidence),
            "questionCount": len(evidence),
            "notYetCount": len(learning_starts),
            "scoreLabel": _mastery_label(overall_score),
            "strongest": strongest,
            "weakest": weakest,
            "coreAdvice": advice,
        },
        "gradingSummary": {
            "model": "deepseek-v4-flash" if any(
                (item.get("grading") or {}).get("graderType") == "ai" for item in evidence
            ) else None,
            "completedCount": sum(
                1 for item in evidence if (item.get("grading") or {}).get("status") == "completed"
            ),
            "subjectiveCount": sum(
                1 for item in evidence if item.get("questionType") in {"short_answer", "open_task"}
            ),
        },
        "strengths": strengths,
        "learningStarts": [{"knowledgePointId": item["knowledgePoint"]["id"], "title": item["knowledgePoint"]["title"],
                            "questionVersionId": item["questionVersionId"]} for item in learning_starts],
        "weaknesses": weaknesses,
        "blindSpots": blind_spots,
        "mastery": mastery,
        "coverageContract": {
            **coverage_contract,
            "observedKnowledgePointCount": sum(item["score"] is not None for item in mastery),
            "observedCrossEvidencePointIds": [
                item["knowledgePointId"] for item in mastery if item["crossEvidence"]
            ],
        },
        "difficultyFit": {
            "target": round(target_difficulty, 3),
            "bands": list(difficulty.values()),
            "basis": "按冻结题目难度和已有可靠评分计算；无评分的题目不进入比例。",
        },
        "decisionBasis": [
            f"{len(scored_evidence)} 道题已有服务端评分证据",
            f"{sum(len(item['sources']) for item in evidence)} 条课程来源引用可下钻",
            f"{sum(1 for item in evidence if item['understandingLevel'])} 道题记录了理解程度",
        ],
        "evidence": evidence,
        "boundary": "这是基于本次诊断证据的初始快照，不是永久掌握结论；证据不足处显示未知。",
    }


def _create_profile_snapshot(
    session: Any,
    *,
    user: DBUser,
    blueprint: DBDiagnosticBlueprint,
    report_id: str,
    report_data: dict[str, Any],
) -> DBProfileSnapshot:
    profile_version = f"diagnostic-report:{report_id}:v1"
    existing = session.query(DBProfileSnapshot).filter_by(
        owner_public_id=user.public_id, profile_version=profile_version,
    ).first()
    if existing is not None:
        return existing
    previous = session.get(DBProfileSnapshot, blueprint.profile_snapshot_id) if blueprint.profile_snapshot_id else None
    snapshot = dict(previous.snapshot or {}) if previous else {}
    mastery = report_data["mastery"]
    # A stage report only replaces observations made in that stage. Untested
    # concepts retain real earlier evidence; never turn later chapters into 0.
    old_course_id = snapshot.get("course_id") or (snapshot.get("course_context") or {}).get("courseId")
    combined = dict(snapshot.get("mastery_by_knowledge_point") or {}) if old_course_id == blueprint.course_id else {}
    assessment_scope = (report_data.get("contextSnapshot") or {}).get("assessmentScope") or {}
    for point in assessment_scope.get("courseKnowledgePoints", []):
        combined.setdefault(point['id'], {'title': point['title'], 'score': None, 'status': 'unknown',
            'attempt_ids': [], 'source_ref_ids': [], 'question_version_ids': [],
            'evidence_item_count': 0, 'cross_evidence': False, 'coverage_status': 'not_assessed'})
    for item in mastery:
        earlier = combined.get(item['knowledgePointId']) or {}
        if item['score'] is None and earlier.get('score') is not None:
            continue
        combined[item['knowledgePointId']] = {
            'title': item['title'], 'score': item['score'], 'status': item['status'],
            'attempt_ids': item['attemptIds'], 'source_ref_ids': item['sourceRefIds'],
            'question_version_ids': item['questionVersionIds'], 'evidence_item_count': item['evidenceItemCount'],
            'cross_evidence': item['crossEvidence'], 'coverage_status': item['coverageStatus'],
            'learning_needs': deepcopy(item.get('learningNeeds') or []),
        }
    snapshot.update({
        "kind": "diagnostic_evidence_snapshot",
        "course_id": blueprint.course_id,
        "source_diagnostic_report_id": report_id,
        "source_diagnostic_session_id": report_data["sessionId"],
        "mastery_status": "initial_evidence_snapshot",
        "mastery_by_knowledge_point": combined,
        "diagnostic_stage": assessment_scope.get('selected'),
        "mastered_knowledge_point_ids": [
            key for key, item in combined.items() if item.get("score") is not None and item["score"] >= 0.7
            and not item.get("learning_needs")
        ],
        "weak_knowledge_point_ids": [
            key for key, item in combined.items() if item.get("score") is not None
            and (item["score"] < 0.6 or item.get("learning_needs"))
        ],
        "unknown_knowledge_point_ids": [
            key for key, item in combined.items() if item.get("score") is None
        ],
        "self_reported_learning_start_points": report_data.get("learningStarts", []),
        "difficulty_target": report_data["difficultyFit"]["target"],
        "diagnostic_evidence": {
            "attempt_ids": [item["attemptId"] for item in report_data["evidence"]],
            "source_ref_ids": sorted({
                source["id"] for item in report_data["evidence"] for source in item["sources"]
            }),
            "created_from_submitted_answers": True,
            "grading_model": report_data.get("gradingSummary", {}).get("model"),
            "grading_feedback": [
                {
                    "attempt_id": item["attemptId"],
                    "question_version_id": item["questionVersionId"],
                    "knowledge_point_id": (item.get("knowledgePoint") or {}).get("id"),
                    "explanation": item.get("explanation") or "",
                    "grading": item["grading"],
                }
                for item in report_data["evidence"]
                if item.get("grading") is not None
            ],
        },
    })
    row = DBProfileSnapshot(
        owner_public_id=user.public_id,
        legacy_student_id=user.username,
        profile_version=profile_version,
        snapshot=snapshot,
        content_hash=_hash(snapshot),
        trace_id=f"diagnostic-report:{report_id}",
    )
    session.add(row)
    session.flush()
    return row


def generate_diagnostic_report(
    session: Any,
    *,
    user: DBUser,
    session_id: str,
    idempotency_key: str,
    llm: Any | None = None,
) -> tuple[DBDiagnosticReport, bool]:
    work = _owned_session(session, user=user, session_id=session_id)
    existing = _report_for_session(session, user=user, session_id=session_id)
    if existing is not None:
        return existing, False
    blueprint = session.get(DBDiagnosticBlueprint, work.blueprint_id)
    if blueprint is None:
        raise DiagnosticReportError("diagnostic_blueprint_missing", "诊断题组不存在。")
    from app.learning_generation_jobs import component_cache, assert_generation_owner
    cache, save = component_cache(session)
    report_key = f'diagnostic-report:{work.id}'
    report_id = cache.get(report_key, {}).get('id') or new_public_id('diagreport')
    if report_key not in cache:
        save(report_key, {'id': report_id})
    responses = {
        item.question_version_id: item
        for item in session.query(DBDiagnosticResponseDraft).filter_by(session_id=work.id).all()
    }
    attempts = []
    for question_version_id in blueprint.question_version_ids or []:
        response = responses.get(question_version_id)
        if response is None:
            raise DiagnosticReportError("diagnostic_response_missing", "诊断答案不完整，无法生成报告。")
        attempt, _ = record_attempt(
            session,
            owner_public_id=user.public_id,
            attempt=AttemptInput(
                question_version_id=question_version_id,
                idempotency_key=f"diagnostic-session:{work.id}:{question_version_id}",
                mode="diagnostic",
                answer=dict(response.answer or {}),
                confidence=response.confidence,
                duration_seconds=response.duration_seconds,
            ),
        )
        attempts.append(attempt)
    # Subjective diagnostic attempts must be graded before the report is
    # projected; otherwise the report/profile would permanently see them as
    # pending and no reliable mastery evidence could be produced.
    if not _is_legacy_blueprint(blueprint):
        if llm is None:
            raise DiagnosticReportError(
                "diagnostic_grading_model_required",
                "生成新诊断报告前必须提供受治理的真实模型。",
                status_code=503,
            )
        context_snapshot = (blueprint.review_decision or {}).get("contextSnapshot") or {}
        _grade_diagnostic_subjective_answers(
            session,
            llm=llm,
            user=user,
            course_id=blueprint.course_id,
            attempts=attempts,
            frozen_refs=(
                list(context_snapshot.get("sourceRefs") or [])
                if context_snapshot.get("sourceSnapshotVersion") == "p1-b08-source.v2"
                else None
            ),
        )
    report_data = _build_report_data(session, work=work, blueprint=blueprint, attempts=attempts)
    if _is_legacy_blueprint(blueprint):
        report_data["evaluation"] = {
            "status": "legacy_compatibility",
            "completedCount": 0,
            "totalCount": len(report_data["evidence"]),
            "model": None,
        }
    else:
        bundle, call_meta = _run_async(_generate_explanations(
            session,
            llm=llm,
            user=user,
            course_id=blueprint.course_id,
            report_id=report_id,
            evidence=report_data["evidence"],
            learning_context=((blueprint.review_decision or {}).get("contextSnapshot") or {}).get("profile", {}).get("learningContext", {}),
        ))
        report_data = _attach_explanations(report_data, bundle=bundle, call_meta=call_meta)
    report_data = _apply_learning_focus(report_data)
    assert_generation_owner(session)
    profile = _create_profile_snapshot(
        session, user=user, blueprint=blueprint, report_id=report_id, report_data=report_data,
    )
    row = DBDiagnosticReport(
        id=report_id,
        session_id=work.id,
        owner_public_id=user.public_id,
        course_id=blueprint.course_id,
        idempotency_key=idempotency_key,
        report_version=REPORT_VERSION,
        attempt_ids=[item.id for item in attempts],
        profile_snapshot_id=profile.id,
        report_data=report_data,
        content_hash=_hash(report_data),
    )
    session.add(row)
    session.flush()
    return row, True


def generate_report_path(
    session: Any, *, user: DBUser, report: DBDiagnosticReport, time_budget_minutes: int | None,
    idempotency_key: str, llm: Any | None = None,
) -> dict[str, Any]:
    if report.owner_public_id != user.public_id:
        raise DiagnosticReportError("diagnostic_report_forbidden", "无权生成该诊断的路径。", status_code=403)
    generate_textbook_path_draft(
        session,
        current_user=user,
        course_id=report.course_id,
        time_budget_minutes=time_budget_minutes,
        profile_snapshot_id=report.profile_snapshot_id,
        idempotency_key=idempotency_key,
        full_coverage=True,
        llm=llm,
    )
    return textbook_path_draft_payload(
        session,
        current_user=user,
        course_id=report.course_id,
        profile_snapshot_id=report.profile_snapshot_id,
    )


def confirm_report_path(session: Any, *, user: DBUser, report: DBDiagnosticReport) -> dict[str, Any]:
    if report.owner_public_id != user.public_id:
        raise DiagnosticReportError("diagnostic_report_forbidden", "无权确认该诊断的路径。", status_code=403)
    path_payload = textbook_path_draft_payload(
        session,
        current_user=user,
        course_id=report.course_id,
        profile_snapshot_id=report.profile_snapshot_id,
    )
    plan_data = path_payload.get("plan")
    if not plan_data:
        raise DiagnosticReportError("diagnostic_path_missing", "请先生成初始学习路径。")
    plan = session.get(DBPlanDraft, plan_data["id"])
    if plan is None:
        raise DiagnosticReportError("diagnostic_path_missing", "初始学习路径不存在。")
    current = session.get(DBPlanVersion, plan.current_version_id)
    if current is None or current.profile_snapshot_id != report.profile_snapshot_id:
        raise DiagnosticReportError("diagnostic_path_stale", "路径依据已变化，请重新生成。")
    if plan.status == "confirmed" and plan.confirmed_version_id == current.id:
        path = session.query(DBLearningPath).filter_by(
            owner_public_id=user.public_id,
            source_plan_version_id=current.id,
        ).order_by(DBLearningPath.created_at.desc()).first()
    else:
        path = confirm_plan(
            session,
            plan=plan,
            owner_public_id=user.public_id,
            expected_lock_version=plan.lock_version,
        )
    if path is None:
        raise DiagnosticReportError("diagnostic_path_publish_failed", "路径确认失败，请重试。")
    return {
        "planId": plan.id,
        "pathId": path.id,
        "route": f"/workspace/path?course_id={report.course_id}&path_id={path.id}",
    }


def diagnostic_report_payload(session: Any, *, user: DBUser, row: DBDiagnosticReport) -> dict[str, Any]:
    if row.owner_public_id != user.public_id:
        raise DiagnosticReportError("diagnostic_report_forbidden", "无权访问该诊断报告。", status_code=403)
    course = session.get(DBCourse, row.course_id)
    frozen_course = ((row.report_data or {}).get("contextSnapshot") or {}).get("course", {})
    try:
        path = textbook_path_draft_payload(
            session,
            current_user=user,
            course_id=row.course_id,
            profile_snapshot_id=row.profile_snapshot_id,
        )
    except PathDraftError:
        path = {"state": "not_generated", "plan": None, "nodes": []}
    visible = _learner_report_data(row.report_data or {})
    for item in visible.get("evidence", []):
        version = session.get(DBAssessmentQuestionVersion, item.get("questionVersionId"))
        if version is not None:
            item["options"] = deepcopy(version.options or [])
            item.setdefault("learningFeedback", item.get("explanation", ""))
            if version.explanation:
                item["explanation"] = learner_safe_explanation(
                    version.explanation, prompt=version.prompt, options=version.options,
                    answer_key=version.answer_key, question_type=item.get("questionType") or "single_choice")
    visible = _apply_learning_focus(visible)
    return {
        **visible,
        "id": row.id,
        "createdAt": _iso(row.created_at),
        "course": {
            "id": row.course_id,
            "title": frozen_course.get("title") or (course.title if course else "当前课程"),
            "version": frozen_course.get("version") or (course.version if course else ""),
            "manifestVersion": frozen_course.get("manifestVersion") or (course.manifest_version if course else ""),
        },
        "profileSnapshotId": row.profile_snapshot_id,
        "attemptIds": list(row.attempt_ids or []),
        "path": path,
        "contentHash": row.content_hash,
    }


def _learner_report_data(stored: dict[str, Any]) -> dict[str, Any]:
    """Present historical feedback without altering the saved report or its hash."""
    result = deepcopy(stored)
    names: dict[str, str] = {}
    for item in result.get("evidence", []):
        knowledge = item.get("knowledgePoint") or {}
        if knowledge.get("id") and knowledge.get("title"):
            names[knowledge["id"]] = knowledge["title"]
        for source in item.get("sources", []):
            if source.get("id") and source.get("title"):
                names[source["id"]] = source["title"]
    for item in result.get("evidence", []):
        if "judgmentBasis" in item:
            item["judgmentBasis"] = teacher_text(item["judgmentBasis"], names=names)
        if "explanation" in item:
            item["explanation"] = teaching_text(item["explanation"], names=names)
        if "learningFeedback" in item:
            item["learningFeedback"] = teaching_text(item["learningFeedback"], names=names)
        for group, keys in (("evaluation", ("claim",)), ("errorType", ("basis", "label")), ("grading", ("feedback",))):
            values = item.get(group) or {}
            for key in keys:
                if key in values:
                    values[key] = teacher_text(values[key], names=names)
        grading = item.get("grading") or {}
        for criterion in grading.get("criterionResults", []):
            for key in ("justification", "feedback", "improvement"):
                if key in criterion:
                    criterion[key] = teacher_text(criterion[key], names=names)
        if "improvementAdvice" in grading:
            grading["improvementAdvice"] = [teacher_text(text, names=names) for text in grading["improvementAdvice"]]
    for group, keys in (("summary", ("coreAdvice", "strongest", "weakest")), ("difficultyFit", ("basis",))):
        values = result.get(group) or {}
        for key in keys:
            if key in values:
                values[key] = teacher_text(values[key], names=names)
    return result
