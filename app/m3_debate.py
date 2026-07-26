"""Claim-level Prover/Challenger/Judge review for M3 resources."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.database import (
    DBAgentRun,
    DBArtifact,
    DBArtifactVersion,
    DBClaimCheck,
    DBDebateRound,
    DBGenerationTask,
)
from app.m1_repository import create_artifact_with_version
from app.m2_contracts import StrictModel
from app.m3_agents import M3_COLLABORATION_CAPABILITY, M3AgentRole, complete_m3_agent_run


M3_DEBATE_REPORT_TYPE = "m3_debate_report"


class M3DebateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise M3DebateError(code, message)


class AtomicClaimInput(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    artifact_version_id: str
    location: str
    atomic_claim: str = Field(min_length=1)
    proposed_source_ref_ids: tuple[str, ...] = Field(min_length=1)


class ProverArgument(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    support_status: Literal["supported", "partial", "insufficient"]
    evidence_ref_ids: tuple[str, ...]
    applicable_conditions: tuple[str, ...]
    rationale: str


class ChallengerArgument(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_types: tuple[
        Literal[
            "unsupported",
            "version_conflict",
            "missing_condition",
            "dangerous_step",
            "difficulty_mismatch",
            "internal_conflict",
            "none",
        ],
        ...,
    ]
    evidence_ref_ids: tuple[str, ...]
    rationale: str


class JudgeVerdict(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: Literal["keep", "revise", "reject", "uncertain"]
    rationale: str
    evidence_ref_ids: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)


class DebateRoundOutput(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prover: ProverArgument
    challenger: ChallengerArgument
    judge: JudgeVerdict


class ClaimDebateResult(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim: AtomicClaimInput
    rounds: tuple[DebateRoundOutput, ...] = Field(min_length=1)
    final_verdict: Literal["keep", "revise", "reject", "uncertain"]
    stopping_reason: Literal["resolved", "evidence_insufficient", "round_limit"]


class M3DebateReport(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["m3.debate_report.v1"] = "m3.debate_report.v1"
    task_id: str
    trace_id: str
    reviewer_version: str
    max_rounds: int = Field(ge=1, le=4)
    results: tuple[ClaimDebateResult, ...] = Field(min_length=1)
    overall_status: Literal["passed", "revision_required", "rejected", "uncertain"]
    semantic_quality_metric_assessed: Literal[False] = False


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


def _validate_claim_scope(session: Any, task: DBGenerationTask, claim: AtomicClaimInput) -> None:
    row = (
        session.query(DBArtifactVersion, DBArtifact)
        .join(DBArtifact, DBArtifact.id == DBArtifactVersion.artifact_id)
        .filter(DBArtifactVersion.id == claim.artifact_version_id)
        .first()
    )
    if row is None:
        _fail("artifact_version_not_found", "claim artifact version does not exist")
    version, artifact = row
    if artifact.creating_task_id != task.id or artifact.artifact_type not in {"lesson", "lab_guide", "tiered_quiz"}:
        _fail("artifact_version_out_of_scope", "claim does not reference a generated M3 resource")
    allowed_sources = set((version.metadata_json or {}).get("source_ref_ids") or [])
    if not set(claim.proposed_source_ref_ids).issubset(allowed_sources):
        _fail("claim_source_out_of_scope", "claim proposes evidence outside the resource source scope")


async def conduct_m3_debate(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
    claims: list[AtomicClaimInput],
    reviewer: Any,
    reviewer_version: str,
    max_rounds: int = 2,
) -> M3DebateReport:
    if not 1 <= max_rounds <= 4:
        _fail("invalid_round_limit", "max_rounds must be between 1 and 4")
    task = _owned_task(session, task_id, owner_public_id)
    run = session.query(DBAgentRun).filter_by(task_id=task.id, role=M3AgentRole.EVIDENCE_REVIEW.value).first()
    if run is None or run.status != "running":
        _fail("evidence_review_not_running", "evidence review role must be running")
    if not claims or len({claim.claim_id for claim in claims}) != len(claims):
        _fail("invalid_claim_set", "claims must be non-empty with unique claim IDs")

    results = []
    for claim in claims:
        _validate_claim_scope(session, task, claim)
        rounds = []
        for round_number in range(1, max_rounds + 1):
            raw = await reviewer.review_claim(
                claim.model_dump(mode="json"),
                round_number=round_number,
                previous_rounds=[item.model_dump(mode="json") for item in rounds],
            )
            try:
                output = DebateRoundOutput.model_validate(raw)
            except ValueError as exc:
                raise M3DebateError("reviewer_output_invalid", str(exc)) from exc
            allowed = set(claim.proposed_source_ref_ids)
            referenced = (
                set(output.prover.evidence_ref_ids)
                | set(output.challenger.evidence_ref_ids)
                | set(output.judge.evidence_ref_ids)
            )
            if not referenced.issubset(allowed):
                _fail("review_evidence_out_of_scope", "review role cited evidence outside the claim scope")
            rounds.append(output)
            if output.judge.verdict in {"keep", "reject", "uncertain"}:
                break

        final = rounds[-1].judge.verdict
        if final == "uncertain":
            stopping = "evidence_insufficient"
        elif final == "revise" and len(rounds) == max_rounds:
            stopping = "round_limit"
        else:
            stopping = "resolved"
        results.append(
            ClaimDebateResult(
                claim=claim,
                rounds=tuple(rounds),
                final_verdict=final,
                stopping_reason=stopping,
            )
        )

    verdicts = {result.final_verdict for result in results}
    if "reject" in verdicts:
        overall = "rejected"
    elif "uncertain" in verdicts:
        overall = "uncertain"
    elif "revise" in verdicts:
        overall = "revision_required"
    else:
        overall = "passed"
    return M3DebateReport(
        task_id=task.id,
        trace_id=task.trace_id,
        reviewer_version=reviewer_version,
        max_rounds=max_rounds,
        results=tuple(results),
        overall_status=overall,
    )


def persist_m3_debate_report(
    session: Any,
    *,
    owner_public_id: str,
    report: M3DebateReport,
) -> tuple[DBArtifact, DBArtifactVersion, bool]:
    task = _owned_task(session, report.task_id, owner_public_id)
    if report.trace_id != task.trace_id:
        _fail("report_trace_mismatch", "debate report trace does not match task")
    run = session.query(DBAgentRun).filter_by(task_id=task.id, role=M3AgentRole.EVIDENCE_REVIEW.value).first()
    if run is None or run.status not in {"running", "completed"}:
        _fail("evidence_review_not_running", "evidence review role must be running")
    content = _canonical_json(report.model_dump(mode="json"))
    existing = session.query(DBArtifact).filter_by(
        creating_task_id=task.id,
        artifact_type=M3_DEBATE_REPORT_TYPE,
    ).first()
    if existing is not None:
        version = session.query(DBArtifactVersion).filter_by(id=existing.current_version_id).one()
        if version.content != content:
            _fail("debate_replay_conflict", "task already contains another debate report")
        return existing, version, False

    round_number = 0
    for result in report.results:
        final = result.rounds[-1]
        support_status = {
            "keep": "supported",
            "revise": "partial",
            "reject": "unsupported",
            "uncertain": "unverifiable",
        }[result.final_verdict]
        session.add(
            DBClaimCheck(
                artifact_version_id=result.claim.artifact_version_id,
                trace_id=task.trace_id,
                atomic_claim=result.claim.atomic_claim,
                source_ref_id=result.claim.proposed_source_ref_ids[0],
                support_status=support_status,
                verdict=result.final_verdict,
                rationale=_canonical_json(
                    {
                        "claim_id": result.claim.claim_id,
                        "location": result.claim.location,
                        "judge_rationale": final.judge.rationale,
                        "stopping_reason": result.stopping_reason,
                        "reviewer_version": report.reviewer_version,
                    }
                ),
            )
        )
        for round_output in result.rounds:
            round_number += 1
            session.add(
                DBDebateRound(
                    task_id=task.id,
                    artifact_version_id=result.claim.artifact_version_id,
                    trace_id=task.trace_id,
                    round_number=round_number,
                    max_rounds=report.max_rounds,
                    prover_claim=_canonical_json(round_output.prover.model_dump(mode="json")),
                    challenger_response=_canonical_json(round_output.challenger.model_dump(mode="json")),
                    judge_decision=round_output.judge.verdict,
                    evidence_ref_ids=list(round_output.judge.evidence_ref_ids),
                )
            )
    session.flush()
    artifact, version = create_artifact_with_version(
        session,
        owner_public_id=task.owner_public_id,
        artifact_type=M3_DEBATE_REPORT_TYPE,
        title="M3 原子事实辩论审核报告",
        content=content,
        content_format="json",
        course_id=task.course_id,
        creating_task_id=task.id,
        metadata={
            "trace_id": task.trace_id,
            "reviewer_version": report.reviewer_version,
            "overall_status": report.overall_status,
            "semantic_quality_metric_assessed": False,
            "claim_count": len(report.results),
        },
    )
    if run.status == "running":
        complete_m3_agent_run(
            session,
            task_id=task.id,
            owner_public_id=owner_public_id,
            role=M3AgentRole.EVIDENCE_REVIEW,
            output_artifact_version_id=version.id,
        )
    session.flush()
    return artifact, version, True
