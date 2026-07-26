"""Deterministic, restricted interactive skill artifact runtime for M3."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBGenerationTask,
    DBLearningEvent,
    DBProfileEvidence,
    DBProfileSnapshot,
)
from app.m1_repository import add_artifact_version, create_artifact_with_version
from app.m2_contracts import StrictModel
from app.m3_agents import M3_COLLABORATION_CAPABILITY, task_events
from app.m3_decisions import build_m3_decision_comparison, persist_m3_decision_comparison
from app.m3_matching import build_m3_matching_report, persist_m3_matching_report


M3_INTERACTIVE_MANIFEST_TYPE = "interactive_skill_artifact"
M3_INTERACTIVE_SESSION_TYPE = "interactive_skill_session"
M3_INTERACTIVE_VERSION = "skill-artifact-rag-tuning-1.0"
M3_INTERACTIVE_CHECKER_VERSION = "m3.rag_tuning.hidden.v1"

AllowedComponent = Literal[
    "parameter_controls",
    "metrics_table",
    "retrieval_log",
    "evidence_table",
    "fault_panel",
    "hint_panel",
    "acceptance_panel",
]
InteractiveStatus = Literal[
    "not_started",
    "configured",
    "running",
    "evaluated",
    "failed",
    "diagnosed",
    "submitted",
    "passed",
    "needs_retry",
]
FaultType = Literal[
    "none",
    "low_confidence",
    "owner_filter_empty",
    "index_version_mismatch",
    "reranker_unavailable",
]


class M3InteractiveError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise M3InteractiveError(code, message)


class ParameterDefinition(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["keyword_weight", "vector_weight", "top_k", "rerank_threshold"]
    kind: Literal["float", "integer"]
    minimum: float
    maximum: float
    step: float
    default: float


class HiddenAcceptanceContract(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checker_version: Literal["m3.rag_tuning.hidden.v1"] = M3_INTERACTIVE_CHECKER_VERSION
    scenario_count: int = Field(default=5, ge=1)
    scenario_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_result_fields: tuple[str, ...]
    hidden_expected_values_exposed: Literal[False] = False


class M3InteractiveManifest(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["m3.interactive_manifest.v1"] = "m3.interactive_manifest.v1"
    artifact_version: Literal["skill-artifact-rag-tuning-1.0"] = M3_INTERACTIVE_VERSION
    title: Literal["调优混合检索并保持数据隔离"] = "调优混合检索并保持数据隔离"
    job_task_id: Literal["JOB-05"] = "JOB-05"
    skill_target: str
    course_id: str
    domain_version_id: str
    target_knowledge_point_ids: tuple[str, ...]
    source_ref_ids: tuple[str, ...]
    prerequisites: tuple[str, ...]
    runtime_mode: Literal["safe_deterministic_simulation"] = "safe_deterministic_simulation"
    security_level: Literal["no_external_code_or_network"] = "no_external_code_or_network"
    allowed_components: tuple[AllowedComponent, ...]
    parameters: tuple[ParameterDefinition, ...]
    public_query_scenarios: tuple[str, ...] = Field(min_length=10, max_length=10)
    states: tuple[str, ...]
    actions: tuple[str, ...]
    fault_types: tuple[FaultType, ...]
    hidden_acceptance: HiddenAcceptanceContract
    static_fallback: str
    permission_scope: Literal["owner_only"] = "owner_only"


class TuningParameters(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    keyword_weight: float = Field(ge=0.0, le=1.0)
    vector_weight: float = Field(ge=0.0, le=1.0)
    top_k: int = Field(ge=1, le=10)
    rerank_threshold: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def weights_sum_to_one(self):
        if abs(self.keyword_weight + self.vector_weight - 1.0) > 1e-6:
            raise ValueError("keyword_weight and vector_weight must sum to 1")
        return self


class PublicMetrics(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    recall_at_k: float = Field(ge=0.0, le=1.0)
    ranking_score: float = Field(ge=0.0, le=1.0)
    isolation_leaks: int = Field(ge=0)
    version_mismatches: int = Field(ge=0)
    average_latency_ms: int = Field(ge=0)
    baseline_recall_at_k: float = 0.66
    baseline_ranking_score: float = 0.69


class HiddenAcceptanceResult(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed_count: int = Field(ge=0)
    total_count: int = Field(ge=1)
    passed: bool
    failure_categories: tuple[
        Literal["retrieval_quality", "ranking_quality", "isolation", "version_scope", "active_fault"],
        ...,
    ]
    checker_version: Literal["m3.rag_tuning.hidden.v1"] = M3_INTERACTIVE_CHECKER_VERSION
    hidden_expected_values_exposed: Literal[False] = False


class InteractiveSessionState(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["m3.interactive_session.v1"] = "m3.interactive_session.v1"
    session_artifact_id: str
    manifest_artifact_version_id: str
    task_id: str
    owner_public_id: str
    profile_snapshot_id: str
    status: InteractiveStatus = "not_started"
    attempt: int = Field(default=1, ge=1)
    parameters: TuningParameters = TuningParameters(
        keyword_weight=0.5,
        vector_weight=0.5,
        top_k=3,
        rerank_threshold=0.5,
    )
    injected_fault: FaultType = "none"
    diagnosis: str = ""
    recovery_action: str = ""
    recovery_verified: bool = False
    metrics: PublicMetrics | None = None
    hidden_acceptance: HiddenAcceptanceResult | None = None
    hint_level: int = Field(default=0, ge=0, le=3)
    hint_count: int = Field(default=0, ge=0)
    action_count: int = Field(default=0, ge=0)
    last_action: str = ""


class InteractiveAction(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str = Field(min_length=8, max_length=128)
    action: Literal[
        "configure",
        "inject_fault",
        "run",
        "evaluate",
        "diagnose",
        "rerun",
        "submit",
        "request_hint",
        "reset",
    ]
    parameters: TuningParameters | None = None
    fault_type: FaultType | None = None
    diagnosis: str = ""
    recovery_action: str = ""


class InteractiveEvidenceResult(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    learning_event_id: str
    profile_evidence_id: str
    skill_evidence_level: Literal["SE-2", "SE-4"]
    matching_report_version_id: str
    decision_record_id: str
    mastery_update: Literal["none"] = "none"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}-{digest}"


def _owned_task(session: Any, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if task is None:
        _fail("task_not_found", "M3 task does not exist")
    if task.owner_public_id != owner_public_id:
        _fail("task_forbidden", "M3 task belongs to another owner")
    if task.capability != M3_COLLABORATION_CAPABILITY:
        _fail("task_capability_mismatch", "task is not an M3 collaboration task")
    return task


def _task_context(session: Any, task_id: str) -> dict[str, Any]:
    event = next((item for item in task_events(session, task_id) if item.event_type == "m3.context.verified"), None)
    if event is None:
        _fail("task_context_missing", "M3 task has no verified context")
    return (event.payload or {}).get("context") or {}


def build_m3_interactive_manifest(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
) -> M3InteractiveManifest:
    task = _owned_task(session, task_id, owner_public_id)
    context = _task_context(session, task.id)
    hidden_descriptor = {
        "version": M3_INTERACTIVE_CHECKER_VERSION,
        "scenarios": ["retrieval", "ranking", "isolation", "version", "fault"],
    }
    return M3InteractiveManifest(
        skill_target="调整关键词/向量权重、top_k 与重排阈值，在不关闭 owner/course/version 过滤的前提下改善检索",
        course_id=task.course_id,
        domain_version_id=context["domain_version_id"],
        target_knowledge_point_ids=tuple(context["target_knowledge_point_ids"]),
        source_ref_ids=tuple(context["source_ref_ids"]),
        prerequisites=("KP-09", "KP-10", "KP-11"),
        allowed_components=(
            "parameter_controls",
            "metrics_table",
            "retrieval_log",
            "evidence_table",
            "fault_panel",
            "hint_panel",
            "acceptance_panel",
        ),
        parameters=(
            ParameterDefinition(name="keyword_weight", kind="float", minimum=0, maximum=1, step=0.05, default=0.5),
            ParameterDefinition(name="vector_weight", kind="float", minimum=0, maximum=1, step=0.05, default=0.5),
            ParameterDefinition(name="top_k", kind="integer", minimum=1, maximum=10, step=1, default=3),
            ParameterDefinition(name="rerank_threshold", kind="float", minimum=0, maximum=1, step=0.05, default=0.5),
        ),
        public_query_scenarios=(
            "exact_term", "semantic_paraphrase", "code_identifier", "metadata_filter", "course_scope",
            "version_scope", "conflicting_source", "low_confidence", "rerank_tie", "owner_isolation",
        ),
        states=("not_started", "configured", "running", "evaluated", "failed", "diagnosed", "submitted", "passed", "needs_retry"),
        actions=("configure", "inject_fault", "run", "evaluate", "diagnose", "rerun", "submit", "request_hint", "reset"),
        fault_types=("none", "low_confidence", "owner_filter_empty", "index_version_mismatch", "reranker_unavailable"),
        hidden_acceptance=HiddenAcceptanceContract(
            scenario_set_sha256=hashlib.sha256(_canonical_json(hidden_descriptor).encode("utf-8")).hexdigest(),
            public_result_fields=("passed_count", "total_count", "passed", "failure_categories", "checker_version"),
        ),
        static_fallback="提供参数说明、10 个公开场景和故障诊断检查表；静态模式不产生隐藏验收通过证据。",
    )


def persist_m3_interactive_manifest(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
    manifest: M3InteractiveManifest,
) -> tuple[DBArtifact, DBArtifactVersion, bool]:
    task = _owned_task(session, task_id, owner_public_id)
    if manifest.course_id != task.course_id:
        _fail("manifest_context_mismatch", "interactive manifest course does not match task")
    content = _canonical_json(manifest.model_dump(mode="json"))
    artifact = session.query(DBArtifact).filter_by(
        creating_task_id=task.id,
        artifact_type=M3_INTERACTIVE_MANIFEST_TYPE,
    ).first()
    if artifact is not None:
        version = session.query(DBArtifactVersion).filter_by(id=artifact.current_version_id).one()
        if version.content != content:
            _fail("manifest_replay_conflict", "task already contains another interactive manifest")
        return artifact, version, False
    artifact, version = create_artifact_with_version(
        session,
        owner_public_id=task.owner_public_id,
        artifact_type=M3_INTERACTIVE_MANIFEST_TYPE,
        title=manifest.title,
        content=content,
        content_format="json",
        course_id=task.course_id,
        creating_task_id=task.id,
        metadata={
            "trace_id": task.trace_id,
            "runtime_mode": manifest.runtime_mode,
            "security_level": manifest.security_level,
            "allowed_components": list(manifest.allowed_components),
            "hidden_checker_version": manifest.hidden_acceptance.checker_version,
        },
    )
    return artifact, version, True


def create_m3_interactive_session(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
    manifest_artifact_version_id: str,
) -> tuple[DBArtifact, DBArtifactVersion, bool]:
    task = _owned_task(session, task_id, owner_public_id)
    manifest_row = (
        session.query(DBArtifactVersion, DBArtifact)
        .join(DBArtifact, DBArtifact.id == DBArtifactVersion.artifact_id)
        .filter(DBArtifactVersion.id == manifest_artifact_version_id)
        .first()
    )
    if manifest_row is None or manifest_row[1].creating_task_id != task.id or manifest_row[1].artifact_type != M3_INTERACTIVE_MANIFEST_TYPE:
        _fail("manifest_version_out_of_scope", "manifest version does not belong to the M3 task")
    context = _task_context(session, task.id)
    artifact_id = _stable_id("ias", task.id, owner_public_id, manifest_artifact_version_id)
    existing = session.query(DBArtifact).filter_by(id=artifact_id).first()
    if existing is not None:
        version = session.query(DBArtifactVersion).filter_by(id=existing.current_version_id).one()
        return existing, version, False
    artifact = DBArtifact(
        id=artifact_id,
        owner_public_id=owner_public_id,
        course_id=task.course_id,
        artifact_type=M3_INTERACTIVE_SESSION_TYPE,
        title="M3 混合检索调优会话",
        status="draft",
        creating_task_id=task.id,
    )
    session.add(artifact)
    session.flush()
    state = InteractiveSessionState(
        session_artifact_id=artifact.id,
        manifest_artifact_version_id=manifest_artifact_version_id,
        task_id=task.id,
        owner_public_id=owner_public_id,
        profile_snapshot_id=context["profile_snapshot_id"],
    )
    version = add_artifact_version(
        session,
        artifact=artifact,
        content=_canonical_json(state.model_dump(mode="json")),
        content_format="json",
        created_by_public_id=owner_public_id,
        created_task_id=task.id,
        metadata={"trace_id": task.trace_id, "status": state.status, "manifest_artifact_version_id": manifest_artifact_version_id},
    )
    return artifact, version, True


def _metrics(parameters: TuningParameters) -> PublicMetrics:
    recall = 0.56 + min(parameters.top_k, 6) * 0.04 - abs(parameters.keyword_weight - 0.4) * 0.20
    ranking = 0.62 + parameters.rerank_threshold * 0.20 - abs(parameters.vector_weight - 0.6) * 0.30
    latency = 70 + parameters.top_k * 12 + int(parameters.rerank_threshold * 40)
    return PublicMetrics(
        recall_at_k=round(max(0.0, min(1.0, recall)), 4),
        ranking_score=round(max(0.0, min(1.0, ranking)), 4),
        isolation_leaks=0,
        version_mismatches=0,
        average_latency_ms=latency,
    )


_RECOVERY_ACTIONS = {
    "low_confidence": "refuse_and_adjust_retrieval",
    "owner_filter_empty": "verify_scope_and_refuse_if_empty",
    "index_version_mismatch": "select_matching_index_version",
    "reranker_unavailable": "use_declared_no_rerank_fallback",
}


def _hidden_acceptance(state: InteractiveSessionState) -> HiddenAcceptanceResult:
    metrics = state.metrics
    if metrics is None:
        _fail("metrics_missing", "hidden acceptance requires evaluated metrics")
    checks = {
        "retrieval_quality": metrics.recall_at_k >= 0.72 and 4 <= state.parameters.top_k <= 6,
        "ranking_quality": metrics.ranking_score >= 0.71 and 0.45 <= state.parameters.rerank_threshold <= 0.70,
        "isolation": metrics.isolation_leaks == 0,
        "version_scope": metrics.version_mismatches == 0,
        "active_fault": state.injected_fault == "none",
    }
    failures = tuple(key for key, passed in checks.items() if not passed)
    return HiddenAcceptanceResult(
        passed_count=sum(checks.values()),
        total_count=len(checks),
        passed=not failures,
        failure_categories=failures,
    )


def transition_m3_interactive_state(
    state: InteractiveSessionState,
    request: InteractiveAction,
) -> InteractiveSessionState:
    data = state.model_dump(mode="json")
    action = request.action
    if action == "configure":
        if state.status not in {"not_started", "configured", "evaluated", "needs_retry"} or request.parameters is None:
            _fail("invalid_transition", "configure requires an editable state and parameters")
        data.update(status="configured", parameters=request.parameters.model_dump(mode="json"), metrics=None, hidden_acceptance=None)
    elif action == "inject_fault":
        if state.status != "configured" or request.fault_type in {None, "none"}:
            _fail("invalid_transition", "a non-empty fault can only be injected after configuration")
        data.update(injected_fault=request.fault_type, diagnosis="", recovery_action="", recovery_verified=False)
    elif action == "run":
        if state.status != "configured":
            _fail("invalid_transition", "run requires configured state")
        data.update(status="running", metrics=None, hidden_acceptance=None)
    elif action == "evaluate":
        if state.status != "running":
            _fail("invalid_transition", "evaluate requires running state")
        data["metrics"] = _metrics(state.parameters).model_dump(mode="json")
        data["status"] = "failed" if state.injected_fault != "none" else "evaluated"
    elif action == "diagnose":
        if state.status != "failed" or not request.diagnosis or not request.recovery_action:
            _fail("invalid_transition", "diagnose requires a failed state and an explicit recovery choice")
        expected = _RECOVERY_ACTIONS[state.injected_fault]
        data.update(
            status="diagnosed",
            diagnosis=request.diagnosis,
            recovery_action=request.recovery_action,
            recovery_verified=request.recovery_action == expected,
        )
    elif action == "rerun":
        if state.status != "diagnosed" or not state.recovery_verified:
            _fail("recovery_not_verified", "rerun requires the correct recovery action")
        data.update(status="running", injected_fault="none", metrics=None, hidden_acceptance=None)
    elif action == "submit":
        if state.status != "evaluated":
            _fail("invalid_transition", "submit requires evaluated state")
        result = _hidden_acceptance(state)
        data.update(status="passed" if result.passed else "needs_retry", hidden_acceptance=result.model_dump(mode="json"))
    elif action == "request_hint":
        if state.status not in {"failed", "diagnosed", "evaluated", "needs_retry"}:
            _fail("invalid_transition", "hints are available only after an observable result")
        data.update(hint_level=min(3, state.hint_level + 1), hint_count=state.hint_count + 1)
    elif action == "reset":
        if state.status == "running":
            _fail("invalid_transition", "running evaluation must finish before reset")
        data.update(
            status="not_started",
            attempt=state.attempt + 1,
            parameters=TuningParameters(keyword_weight=0.5, vector_weight=0.5, top_k=3, rerank_threshold=0.5).model_dump(mode="json"),
            injected_fault="none",
            diagnosis="",
            recovery_action="",
            recovery_verified=False,
            metrics=None,
            hidden_acceptance=None,
            hint_level=0,
            hint_count=0,
        )
    data.update(action_count=state.action_count + 1, last_action=action)
    return InteractiveSessionState.model_validate(data)


def apply_m3_interactive_action(
    session: Any,
    *,
    session_artifact_id: str,
    owner_public_id: str,
    request: InteractiveAction,
) -> tuple[InteractiveSessionState, DBArtifactVersion, DBLearningEvent, bool]:
    artifact = session.query(DBArtifact).filter_by(id=session_artifact_id).first()
    if artifact is None or artifact.artifact_type != M3_INTERACTIVE_SESSION_TYPE:
        _fail("interactive_session_not_found", "interactive session does not exist")
    if artifact.owner_public_id != owner_public_id:
        _fail("interactive_session_forbidden", "interactive session belongs to another owner")
    task = _owned_task(session, artifact.creating_task_id, owner_public_id)
    event_id = _stable_id("le-m3", artifact.id, request.idempotency_key)
    request_payload = request.model_dump(mode="json")
    request_hash = hashlib.sha256(_canonical_json(request_payload).encode("utf-8")).hexdigest()
    existing_event = session.query(DBLearningEvent).filter_by(id=event_id).first()
    if existing_event is not None:
        payload = existing_event.payload or {}
        if payload.get("request_hash") != request_hash:
            _fail("action_idempotency_conflict", "idempotency key is bound to another interactive action")
        version = session.query(DBArtifactVersion).filter_by(id=payload["result_version_id"]).one()
        return InteractiveSessionState.model_validate_json(version.content), version, existing_event, False

    current_version = session.query(DBArtifactVersion).filter_by(id=artifact.current_version_id).one()
    current = InteractiveSessionState.model_validate_json(current_version.content)
    next_state = transition_m3_interactive_state(current, request)
    version = add_artifact_version(
        session,
        artifact=artifact,
        content=_canonical_json(next_state.model_dump(mode="json")),
        content_format="json",
        created_by_public_id=owner_public_id,
        created_task_id=task.id,
        metadata={
            "trace_id": task.trace_id,
            "status": next_state.status,
            "attempt": next_state.attempt,
            "action": request.action,
            "manifest_artifact_version_id": next_state.manifest_artifact_version_id,
        },
    )
    event_payload = {
        "request_hash": request_hash,
        "action": request.action,
        "from_status": current.status,
        "to_status": next_state.status,
        "result_version_id": version.id,
        "attempt": next_state.attempt,
        "hint_count": next_state.hint_count,
        "mastery_update": "none",
    }
    if request.action == "submit" and next_state.hidden_acceptance is not None:
        event_payload.update(
            accuracy=next_state.hidden_acceptance.passed_count / next_state.hidden_acceptance.total_count,
            help_requests=next_state.hint_count,
            hidden_acceptance_passed=next_state.hidden_acceptance.passed,
            hidden_result=next_state.hidden_acceptance.model_dump(mode="json"),
        )
    event = DBLearningEvent(
        id=event_id,
        owner_public_id=owner_public_id,
        course_id=artifact.course_id,
        event_type="m3.interactive.action_recorded",
        schema_version="1.0",
        trace_id=task.trace_id,
        object_type=M3_INTERACTIVE_SESSION_TYPE,
        object_id=artifact.id,
        payload=event_payload,
    )
    session.add(event)
    session.flush()
    return next_state, version, event, True


def record_m3_interactive_evidence(
    session: Any,
    *,
    session_artifact_id: str,
    owner_public_id: str,
) -> InteractiveEvidenceResult:
    artifact = session.query(DBArtifact).filter_by(id=session_artifact_id).first()
    if artifact is None or artifact.owner_public_id != owner_public_id:
        _fail("interactive_session_forbidden", "interactive session is unavailable to owner")
    task = _owned_task(session, artifact.creating_task_id, owner_public_id)
    version = session.query(DBArtifactVersion).filter_by(id=artifact.current_version_id).one()
    state = InteractiveSessionState.model_validate_json(version.content)
    if state.status != "passed" or state.hidden_acceptance is None or not state.hidden_acceptance.passed:
        _fail("hidden_acceptance_not_passed", "skill evidence requires a passed hidden acceptance")
    submit_event = (
        session.query(DBLearningEvent)
        .filter_by(trace_id=task.trace_id, object_id=artifact.id)
        .filter(DBLearningEvent.event_type == "m3.interactive.action_recorded")
        .order_by(DBLearningEvent.recorded_at.desc(), DBLearningEvent.id.desc())
        .all()
    )
    submit_event = next((event for event in submit_event if (event.payload or {}).get("action") == "submit"), None)
    if submit_event is None:
        _fail("submit_event_missing", "passed session has no submit event")
    level = "SE-4" if state.hint_count == 0 else "SE-2"
    evidence_id = _stable_id("pe-m3", artifact.id, version.id)
    evidence = session.query(DBProfileEvidence).filter_by(id=evidence_id).first()
    snapshot = session.query(DBProfileSnapshot).filter_by(id=state.profile_snapshot_id).one()
    legacy_student_id = (snapshot.snapshot or {}).get("source_student_id") or owner_public_id
    if evidence is None:
        evidence = DBProfileEvidence(
            id=evidence_id,
            owner_public_id=owner_public_id,
            legacy_student_id=legacy_student_id,
            legacy_key=f"interactive:{artifact.id}:{version.id}",
            source_type="interactive_hidden_acceptance",
            source_object_id=artifact.id,
            features=[
                f"skill_evidence_level:{level}",
                f"hidden_passed:{state.hidden_acceptance.passed_count}/{state.hidden_acceptance.total_count}",
                f"hint_count:{state.hint_count}",
                "mastery_update:none",
            ],
            weight=0.85 if level == "SE-4" else 0.60,
            confidence=0.85 if level == "SE-4" else 0.65,
            evidence_summary="通过确定性隐藏验收形成任务版本技能证据；不代表长期掌握或岗位胜任",
            status="active",
            evidence_version="m3.interactive.v1",
            trace_id=task.trace_id,
        )
        session.add(evidence)
        session.flush()
    report = build_m3_matching_report(session, task_id=task.id, owner_public_id=owner_public_id)
    _report_artifact, report_version, _ = persist_m3_matching_report(session, report=report)
    comparison = build_m3_decision_comparison(session, task_id=task.id, owner_public_id=owner_public_id)
    decision, _artifact, _version, _ = persist_m3_decision_comparison(session, comparison=comparison)
    return InteractiveEvidenceResult(
        learning_event_id=submit_event.id,
        profile_evidence_id=evidence.id,
        skill_evidence_level=level,
        matching_report_version_id=report_version.id,
        decision_record_id=decision.id,
    )
