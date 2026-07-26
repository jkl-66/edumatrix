"""Rule-first dynamic decision candidates for the M3 comparison loop."""

from __future__ import annotations

import hashlib
import json
from statistics import mean
from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.database import (
    DBAgentRun,
    DBArtifact,
    DBArtifactVersion,
    DBDecisionRecord,
    DBGenerationTask,
    DBLearningEvent,
)
from app.m1_repository import add_artifact_version, create_artifact_with_version
from app.m2_contracts import StrictModel
from app.m3_agents import (
    M3_COLLABORATION_CAPABILITY,
    M3AgentRole,
    complete_m3_agent_run,
)
from app.m3_matching import M3MatchingReport, M3_MATCHING_REPORT_TYPE


M3_DECISION_RULE_VERSION = "m3.dynamic_decision.rules.v1"
M3_DECISION_COMPARISON_TYPE = "m3_decision_comparison"


class M3DecisionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise M3DecisionError(code, message)


class DecisionCandidate(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_type: Literal[
        "collect_more_evidence",
        "downgrade_explanation",
        "prerequisite_remediation",
        "maintain_and_consolidate",
        "advance_challenge",
    ]
    rationale: str
    evidence_ids: tuple[str, ...]
    estimated_burden_minutes: tuple[int, int]
    proposed_path_change: str
    resource_cost: Literal["none", "low", "medium", "high"]
    risk: Literal["low", "medium", "high"]
    confirmation_required: bool


class M3DecisionComparison(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["m3.decision_comparison.v1"] = "m3.decision_comparison.v1"
    task_id: str
    trace_id: str
    owner_public_id: str
    profile_snapshot_id: str
    matching_report_artifact_id: str
    matching_report_version_id: str
    rule_version: Literal["m3.dynamic_decision.rules.v1"] = M3_DECISION_RULE_VERSION
    evidence_state: Literal["insufficient", "conflicting", "observed", "delayed_confirmed"]
    candidates: tuple[DecisionCandidate, ...] = Field(min_length=5, max_length=5)
    selected_decision_type: str
    selected_rule_ids: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["proposed"] = "proposed"
    user_confirmed: Literal[False] = False
    mastery_update: Literal["none"] = "none"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _owned_task(session: Any, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if task is None:
        _fail("task_not_found", "M3 task does not exist")
    if task.owner_public_id != owner_public_id:
        _fail("task_forbidden", "M3 task belongs to another owner")
    if task.capability != M3_COLLABORATION_CAPABILITY:
        _fail("task_capability_mismatch", "task is not an M3 collaboration task")
    return task


def _event_features(events: list[DBLearningEvent]) -> dict[str, Any]:
    payloads = [event.payload or {} for event in events]
    numeric_accuracy = [float(item["accuracy"]) for item in payloads if item.get("accuracy") is not None]
    return {
        "accuracy": mean(numeric_accuracy) if numeric_accuracy else None,
        "help_requests": sum(int(item.get("help_requests") or 0) for item in payloads),
        "consecutive_failures": max((int(item.get("consecutive_failures") or 0) for item in payloads), default=0),
        "subjective_difficulty": max((int(item.get("self_reported_difficulty") or 0) for item in payloads), default=0),
        "hidden_acceptance_passed": any(item.get("hidden_acceptance_passed") is True for item in payloads),
        "delayed_retest_passed": any(item.get("delayed_retest_passed") is True for item in payloads),
    }


def _candidates(evidence_ids: tuple[str, ...]) -> tuple[DecisionCandidate, ...]:
    return (
        DecisionCandidate(
            decision_type="collect_more_evidence",
            rationale="证据不足或冲突时先追问、微测或完成一次受控任务",
            evidence_ids=evidence_ids,
            estimated_burden_minutes=(5, 15),
            proposed_path_change="不改变正式路径，追加诊断节点",
            resource_cost="low",
            risk="low",
            confirmation_required=False,
        ),
        DecisionCandidate(
            decision_type="downgrade_explanation",
            rationale="降低术语密度、拆分步骤并增加例子，不降低事实或安全标准",
            evidence_ids=evidence_ids,
            estimated_burden_minutes=(15, 30),
            proposed_path_change="替换目标资源表达版本，保留岗位验收",
            resource_cost="medium",
            risk="low",
            confirmation_required=False,
        ),
        DecisionCandidate(
            decision_type="prerequisite_remediation",
            rationale="失败与先修缺口一致时插入最小补救节点，完成后返回原目标",
            evidence_ids=evidence_ids,
            estimated_burden_minutes=(20, 45),
            proposed_path_change="在当前节点前插入最小先修补救",
            resource_cost="medium",
            risk="medium",
            confirmation_required=True,
        ),
        DecisionCandidate(
            decision_type="maintain_and_consolidate",
            rationale="当前难度可接受但证据尚不稳定，维持路径并安排变式或延迟复测",
            evidence_ids=evidence_ids,
            estimated_burden_minutes=(10, 25),
            proposed_path_change="保留当前节点，追加巩固或延迟复测",
            resource_cost="low",
            risk="low",
            confirmation_required=False,
        ),
        DecisionCandidate(
            decision_type="advance_challenge",
            rationale="稳定强证据显示任务过易时增加开放约束、排障或迁移挑战",
            evidence_ids=evidence_ids,
            estimated_burden_minutes=(25, 60),
            proposed_path_change="在当前目标后追加进阶挑战节点",
            resource_cost="high",
            risk="medium",
            confirmation_required=True,
        ),
    )


def build_m3_decision_comparison(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
) -> M3DecisionComparison:
    task = _owned_task(session, task_id, owner_public_id)
    run = session.query(DBAgentRun).filter_by(task_id=task.id, role=M3AgentRole.DECISION_ORCHESTRATION.value).first()
    if run is None or run.status not in {"running", "completed"}:
        _fail("decision_role_not_running", "decision orchestration role must be running")
    report_artifact = session.query(DBArtifact).filter_by(
        creating_task_id=task.id,
        artifact_type=M3_MATCHING_REPORT_TYPE,
    ).first()
    if report_artifact is None:
        _fail("matching_report_missing", "dynamic decision requires a formal matching report")
    report_version = session.query(DBArtifactVersion).filter_by(id=report_artifact.current_version_id).one()
    report = M3MatchingReport.model_validate_json(report_version.content)
    events = session.query(DBLearningEvent).filter_by(trace_id=task.trace_id).order_by(DBLearningEvent.occurred_at).all()
    features = _event_features(events)
    evidence_ids = tuple([report_version.id, report.debate_report_artifact_id, *[event.id for event in events]])

    accuracy = features["accuracy"]
    help_requests = features["help_requests"]
    failures = features["consecutive_failures"]
    difficulty = features["subjective_difficulty"]
    hidden_passed = features["hidden_acceptance_passed"]
    delayed_passed = features["delayed_retest_passed"]
    source_profile_id = report.source_profile_id
    if not events or accuracy is None:
        evidence_state = "insufficient"
        selected, rules, confidence = "collect_more_evidence", ("R-DATA-001",), 0.35
    elif accuracy >= 0.85 and (help_requests >= 2 or difficulty >= 4):
        evidence_state = "conflicting"
        selected, rules, confidence = "collect_more_evidence", ("R-CONFLICT-001",), 0.45
    elif hidden_passed and delayed_passed and accuracy >= 0.85 and help_requests == 0:
        evidence_state = "delayed_confirmed"
        selected, rules, confidence = "advance_challenge", ("R-ADV-001", "R-DELAY-001"), 0.90
    elif accuracy < 0.5 or failures >= 2:
        evidence_state = "observed"
        if source_profile_id == "profile-m0-beginner":
            selected, rules, confidence = "prerequisite_remediation", ("R-LOW-001", "R-PREREQ-001"), 0.75
        else:
            selected, rules, confidence = "downgrade_explanation", ("R-LOW-001", "R-SCAFFOLD-001"), 0.70
    else:
        evidence_state = "observed"
        selected, rules, confidence = "maintain_and_consolidate", ("R-MAINTAIN-001",), 0.65

    return M3DecisionComparison(
        task_id=task.id,
        trace_id=task.trace_id,
        owner_public_id=task.owner_public_id,
        profile_snapshot_id=report.profile_snapshot_id,
        matching_report_artifact_id=report_artifact.id,
        matching_report_version_id=report_version.id,
        evidence_state=evidence_state,
        candidates=_candidates(evidence_ids),
        selected_decision_type=selected,
        selected_rule_ids=rules,
        confidence=confidence,
    )


def persist_m3_decision_comparison(
    session: Any,
    *,
    comparison: M3DecisionComparison,
) -> tuple[DBDecisionRecord, DBArtifact, DBArtifactVersion, bool]:
    task = _owned_task(session, comparison.task_id, comparison.owner_public_id)
    if comparison.trace_id != task.trace_id:
        _fail("decision_trace_mismatch", "decision comparison trace does not match task")
    evidence_ids = tuple(dict.fromkeys(
        evidence_id
        for candidate in comparison.candidates
        for evidence_id in candidate.evidence_ids
    ))
    identity = hashlib.sha256(
        _canonical_json(
            {
                "task_id": task.id,
                "rule_version": comparison.rule_version,
                "selected": comparison.selected_decision_type,
                "evidence_ids": evidence_ids,
            }
        ).encode("utf-8")
    ).hexdigest()[:32]
    decision_id = f"decision-m3-{identity}"
    decision = session.query(DBDecisionRecord).filter_by(id=decision_id).first()
    candidates_payload = [candidate.model_dump(mode="json") for candidate in comparison.candidates]
    if decision is None:
        decision = DBDecisionRecord(
            id=decision_id,
            owner_public_id=task.owner_public_id,
            task_id=task.id,
            profile_snapshot_id=comparison.profile_snapshot_id,
            trace_id=task.trace_id,
            decision_type=comparison.selected_decision_type,
            candidates=candidates_payload,
            rules=list(comparison.selected_rule_ids),
            evidence_ids=list(evidence_ids),
            confidence=comparison.confidence,
            execution_impact={
                "mastery_update": "none",
                "path_update": "pending_confirmation" if next(
                    candidate.confirmation_required
                    for candidate in comparison.candidates
                    if candidate.decision_type == comparison.selected_decision_type
                ) else "not_executed",
                "resource_update": "not_executed",
                "rule_version": comparison.rule_version,
            },
            user_confirmed=False,
            before_version_id=comparison.matching_report_version_id,
            after_version_id=None,
            status="proposed",
        )
        session.add(decision)
        session.flush()
        decision_created = True
    else:
        expected = (
            decision.owner_public_id == task.owner_public_id
            and decision.task_id == task.id
            and decision.decision_type == comparison.selected_decision_type
            and decision.candidates == candidates_payload
            and decision.rules == list(comparison.selected_rule_ids)
            and decision.evidence_ids == list(evidence_ids)
            and decision.user_confirmed is False
            and decision.status == "proposed"
        )
        if not expected:
            _fail("decision_identity_conflict", "stable M3 decision ID is occupied by different content")
        decision_created = False

    content = _canonical_json(
        {
            **comparison.model_dump(mode="json"),
            "decision_record_id": decision.id,
        }
    )
    artifact = session.query(DBArtifact).filter_by(
        creating_task_id=task.id,
        artifact_type=M3_DECISION_COMPARISON_TYPE,
    ).first()
    artifact_version_created = False
    if artifact is None:
        artifact, version = create_artifact_with_version(
            session,
            owner_public_id=task.owner_public_id,
            artifact_type=M3_DECISION_COMPARISON_TYPE,
            title="M3 动态决策候选比较",
            content=content,
            content_format="json",
            course_id=task.course_id,
            creating_task_id=task.id,
            metadata={
                "trace_id": task.trace_id,
                "decision_record_id": decision.id,
                "rule_version": comparison.rule_version,
                "user_confirmed": False,
                "mastery_update": "none",
            },
        )
        artifact_version_created = True
    else:
        current = session.query(DBArtifactVersion).filter_by(id=artifact.current_version_id).one()
        if current.content == content:
            version = current
        else:
            version = add_artifact_version(
                session,
                artifact=artifact,
                content=content,
                content_format="json",
                created_by_public_id=task.owner_public_id,
                created_task_id=task.id,
                metadata={
                    "trace_id": task.trace_id,
                    "decision_record_id": decision.id,
                    "rule_version": comparison.rule_version,
                    "user_confirmed": False,
                    "mastery_update": "none",
                },
            )
            artifact_version_created = True
    run = session.query(DBAgentRun).filter_by(task_id=task.id, role=M3AgentRole.DECISION_ORCHESTRATION.value).first()
    if run is not None and run.status == "running":
        complete_m3_agent_run(
            session,
            task_id=task.id,
            owner_public_id=task.owner_public_id,
            role=M3AgentRole.DECISION_ORCHESTRATION,
            output_artifact_version_id=version.id,
        )
    session.flush()
    return decision, artifact, version, decision_created or artifact_version_created
