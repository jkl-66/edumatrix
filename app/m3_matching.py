"""Evidence-backed profile-to-resource matching reports for M3."""

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
    DBGenerationTask,
    DBLearningEvent,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
)
from app.m1_repository import add_artifact_version, create_artifact_with_version
from app.m2_contracts import StrictModel
from app.m3_agents import M3_COLLABORATION_CAPABILITY, M3AgentRole
from app.m3_debate import M3_DEBATE_REPORT_TYPE
from app.m3_profiles import M3GoldProfile, load_m3_gold_profiles


M3_MATCHING_REPORT_TYPE = "m3_matching_report"
M3_MATCHING_ALGORITHM_VERSION = "m3.matching.interval.v1"


class M3MatchingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise M3MatchingError(code, message)


class ResourceDifficultyVector(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prerequisite_depth: float = Field(ge=0.0, le=1.0)
    concept_complexity: float = Field(ge=0.0, le=1.0)
    operation_steps: float = Field(ge=0.0, le=1.0)
    tool_complexity: float = Field(ge=0.0, le=1.0)
    cognitive_load: float = Field(ge=0.0, le=1.0)
    openness: float = Field(ge=0.0, le=1.0)

    def aggregate(self) -> float:
        return round(mean(self.model_dump().values()), 4)


class RecommendedDifficultyInterval(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lower: float = Field(ge=0.0, le=1.0)
    upper: float = Field(ge=0.0, le=1.0)
    ability_midpoint: float = Field(ge=0.0, le=1.0)
    uncertainty_width: float = Field(ge=0.0, le=1.0)
    algorithm_version: Literal["m3.matching.interval.v1"] = M3_MATCHING_ALGORITHM_VERSION


class ResourceMatch(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str
    artifact_version_id: str
    artifact_type: Literal["lesson", "lab_guide", "tiered_quiz"]
    difficulty: ResourceDifficultyVector
    aggregate_difficulty: float = Field(ge=0.0, le=1.0)
    status: Literal["too_easy", "adapted", "acceptable_challenge", "too_hard"]
    explanation: str


class KnowledgeGap(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_point_code: str
    state: Literal[
        "not_encountered",
        "evidence_insufficient",
        "suspected_weak",
        "confirmed_weak",
        "remediated",
        "not_indicated",
    ]
    mastery_prior: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...]
    explanation: str


class MatchingPerformance(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["no_valid_events", "observed_not_mastery", "delayed_evidence_available"]
    learning_event_ids: tuple[str, ...]
    points: tuple[dict[str, Any], ...]
    explanation: str


class M3MatchingReport(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["m3.matching_report.v1"] = "m3.matching_report.v1"
    task_id: str
    trace_id: str
    owner_public_id: str
    profile_snapshot_id: str
    source_profile_id: str
    plan_version_id: str
    plan_execution_authorized: Literal[False] = False
    target_knowledge_point_codes: tuple[str, ...]
    recommended_interval: RecommendedDifficultyInterval
    resource_matches: tuple[ResourceMatch, ...] = Field(min_length=3, max_length=3)
    knowledge_gaps: tuple[KnowledgeGap, ...] = Field(min_length=1)
    performance: MatchingPerformance
    debate_report_artifact_id: str
    calculation_notes: tuple[str, ...]


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


def _gold_profile(snapshot: DBProfileSnapshot) -> M3GoldProfile:
    source_profile_id = (snapshot.snapshot or {}).get("source_profile_id")
    profile = next(
        (item for item in load_m3_gold_profiles().profiles if item.source_profile.profile_id == source_profile_id),
        None,
    )
    if profile is None:
        _fail("profile_not_m3_gold", "profile snapshot is outside the M3 gold set")
    return profile


def _ensure_benchmark_plan(
    session: Any,
    *,
    task: DBGenerationTask,
    snapshot: DBProfileSnapshot,
    profile: M3GoldProfile,
) -> DBPlanVersion:
    owner_scope = hashlib.sha256(task.owner_public_id.encode("utf-8")).hexdigest()[:16]
    plan_id = f"pd-{profile.archetype}-{owner_scope}-m3-v1"
    plan = session.query(DBPlanDraft).filter_by(id=plan_id).first()
    if plan is None:
        plan = DBPlanDraft(
            id=plan_id,
            owner_public_id=task.owner_public_id,
            course_id=task.course_id,
            title=f"M3 {profile.source_profile.label} 基准预期路径",
            status="draft",
        )
        session.add(plan)
        session.flush()
    elif plan.owner_public_id != task.owner_public_id or plan.course_id != task.course_id:
        _fail("benchmark_plan_conflict", "benchmark plan identity is occupied")
    content = {
        "schema_version": "m3.benchmark_plan.v1",
        "benchmark_expected": True,
        "execution_authorized": False,
        "source_profile_id": profile.source_profile.profile_id,
        "shared_job_task_id": profile.shared_job_task_id,
        "nodes": [
            {"sequence": index, "title": title, "status": "proposed"}
            for index, title in enumerate(profile.source_profile.expected_first_path, start=1)
        ],
    }
    digest = hashlib.sha256(_canonical_json(content).encode("utf-8")).hexdigest()
    version = session.query(DBPlanVersion).filter_by(plan_draft_id=plan.id, version_number=1).first()
    if version is None:
        version = DBPlanVersion(
            id=f"pv-{profile.archetype}-{owner_scope}-m3-v1",
            plan_draft_id=plan.id,
            version_number=1,
            profile_snapshot_id=snapshot.id,
            content=content,
            content_hash=digest,
            created_by_public_id=task.owner_public_id,
        )
        session.add(version)
        session.flush()
    elif (
        version.profile_snapshot_id != snapshot.id
        or version.content != content
        or version.content_hash != digest
    ):
        _fail("benchmark_plan_immutable", "benchmark plan version does not match the frozen profile")
    return version


def _recommended_interval(profile: M3GoldProfile) -> RecommendedDifficultyInterval:
    intervals = list(profile.ability_vector.model_dump().values())
    midpoints = [(item["low"] + item["high"]) / 2 for item in intervals]
    widths = [item["high"] - item["low"] for item in intervals]
    midpoint = mean(midpoints)
    uncertainty = mean(widths)
    return RecommendedDifficultyInterval(
        lower=round(max(0.0, midpoint - uncertainty - 0.05), 4),
        upper=round(min(1.0, midpoint + uncertainty + 0.07), 4),
        ability_midpoint=round(midpoint, 4),
        uncertainty_width=round(uncertainty, 4),
    )


def _difficulty(artifact_type: str, personalization: dict[str, Any]) -> ResourceDifficultyVector:
    center = {"L0-L1": 0.20, "L1-L2": 0.45, "L2-L4": 0.75}.get(personalization.get("difficulty_band"))
    if center is None:
        _fail("difficulty_band_unknown", "resource difficulty band is not frozen")
    openness = {"guided": 0.15, "bounded": 0.50, "open": 0.85}[personalization["task_openness"]]
    offsets = {
        "lesson": (-0.05, 0.00, -0.10, -0.10, 0.00),
        "lab_guide": (0.00, 0.00, 0.05, 0.05, 0.05),
        "tiered_quiz": (0.00, 0.05, 0.00, 0.00, 0.05),
    }[artifact_type]
    values = [min(1.0, max(0.0, center + offset)) for offset in offsets]
    return ResourceDifficultyVector(
        prerequisite_depth=values[0],
        concept_complexity=values[1],
        operation_steps=values[2],
        tool_complexity=values[3],
        cognitive_load=values[4],
        openness=openness,
    )


def _match_status(value: float, interval: RecommendedDifficultyInterval) -> str:
    if value < interval.lower:
        return "too_easy"
    if value <= interval.upper:
        return "adapted"
    if value <= min(1.0, interval.upper + 0.10):
        return "acceptable_challenge"
    return "too_hard"


def _knowledge_gaps(profile: M3GoldProfile) -> tuple[KnowledgeGap, ...]:
    mastery = profile.source_profile.initial_mastery
    evidence_ref = f"m0.baseline_profiles:{profile.source_profile.profile_id}"
    results = []
    for code in profile.target_knowledge_point_codes:
        prior = mastery.get(code)
        if prior is None:
            state, explanation = "evidence_insufficient", "冻结画像没有该知识点的直接先验"
        elif prior == 0:
            state, explanation = "not_encountered", "冻结先验为 0，仅表示尚无接触证据"
        elif prior < 0.5:
            state, explanation = "suspected_weak", "低先验形成疑似薄弱，仍需任务证据确认"
        else:
            state, explanation = "not_indicated", "当前先验未提示薄弱，但不等同于已掌握"
        results.append(
            KnowledgeGap(
                knowledge_point_code=code,
                state=state,
                mastery_prior=prior,
                evidence_refs=(evidence_ref,),
                explanation=explanation,
            )
        )
    return tuple(results)


def build_m3_matching_report(
    session: Any,
    *,
    task_id: str,
    owner_public_id: str,
) -> M3MatchingReport:
    task = _owned_task(session, task_id, owner_public_id)
    review_run = (
        session.query(DBAgentRun)
        .filter_by(task_id=task.id, role=M3AgentRole.EVIDENCE_REVIEW.value)
        .order_by(DBAgentRun.created_at.desc(), DBAgentRun.id.desc())
        .first()
    )
    if review_run is None or review_run.status != "completed":
        _fail("evidence_review_incomplete", "matching report requires completed evidence review")
    snapshot = session.query(DBProfileSnapshot).filter_by(trace_id=task.trace_id).first()
    if snapshot is None:
        # Collaboration tasks receive a fresh trace; recover the bound snapshot from the context event.
        from app.m3_agents import task_events

        context_event = next(event for event in task_events(session, task.id) if event.event_type == "m3.context.verified")
        snapshot_id = (context_event.payload or {})["context"]["profile_snapshot_id"]
        snapshot = session.query(DBProfileSnapshot).filter_by(id=snapshot_id).one()
    profile = _gold_profile(snapshot)
    plan_version = _ensure_benchmark_plan(session, task=task, snapshot=snapshot, profile=profile)
    interval = _recommended_interval(profile)

    resources = session.query(DBArtifact).filter(
        DBArtifact.creating_task_id == task.id,
        DBArtifact.artifact_type.in_({"lesson", "lab_guide", "tiered_quiz"}),
    ).order_by(DBArtifact.artifact_type).all()
    if len(resources) != 3:
        _fail("resource_set_incomplete", "matching report requires exactly three formal resources")
    matches = []
    for resource in resources:
        version = session.query(DBArtifactVersion).filter_by(id=resource.current_version_id).one()
        personalization = (version.metadata_json or {}).get("personalization") or {}
        vector = _difficulty(resource.artifact_type, personalization)
        aggregate = vector.aggregate()
        status = _match_status(aggregate, interval)
        matches.append(
            ResourceMatch(
                artifact_id=resource.id,
                artifact_version_id=version.id,
                artifact_type=resource.artifact_type,
                difficulty=vector,
                aggregate_difficulty=aggregate,
                status=status,
                explanation=f"资源聚合难度 {aggregate:.4f} 与推荐区间 [{interval.lower:.4f}, {interval.upper:.4f}] 比较",
            )
        )
    debate = session.query(DBArtifact).filter_by(
        creating_task_id=task.id,
        artifact_type=M3_DEBATE_REPORT_TYPE,
    ).first()
    if debate is None:
        _fail("debate_report_missing", "matching report requires the formal debate report")

    events = session.query(DBLearningEvent).filter_by(trace_id=task.trace_id).order_by(DBLearningEvent.occurred_at).all()
    points = tuple(
        {
            "event_id": event.id,
            "event_type": event.event_type,
            "object_type": event.object_type,
            "object_id": event.object_id,
            "payload": event.payload or {},
        }
        for event in events
    )
    delayed = any(event.event_type.endswith("delayed_retest") for event in events)
    performance = MatchingPerformance(
        status="delayed_evidence_available" if delayed else ("observed_not_mastery" if events else "no_valid_events"),
        learning_event_ids=tuple(event.id for event in events),
        points=points,
        explanation=(
            "尚无当前 trace 的有效表现事件，不绘制虚构实际表现点"
            if not events
            else "已记录操作/反馈点；除非存在延迟复测，否则不据此宣称长期掌握"
        ),
    )
    return M3MatchingReport(
        task_id=task.id,
        trace_id=task.trace_id,
        owner_public_id=task.owner_public_id,
        profile_snapshot_id=snapshot.id,
        source_profile_id=profile.source_profile.profile_id,
        plan_version_id=plan_version.id,
        target_knowledge_point_codes=profile.target_knowledge_point_codes,
        recommended_interval=interval,
        resource_matches=tuple(matches),
        knowledge_gaps=_knowledge_gaps(profile),
        performance=performance,
        debate_report_artifact_id=debate.id,
        calculation_notes=(
            "能力使用六维区间中点，不使用无依据单点模型分数",
            "推荐区间同时保留画像区间宽度作为不确定性",
            "资源难度六维分别报告，聚合值只用于区间定位",
            "缺少学习事件时实际表现保持为空",
        ),
    )


def persist_m3_matching_report(
    session: Any,
    *,
    report: M3MatchingReport,
) -> tuple[DBArtifact, DBArtifactVersion, bool]:
    task = _owned_task(session, report.task_id, report.owner_public_id)
    if report.trace_id != task.trace_id:
        _fail("report_trace_mismatch", "matching report trace does not match task")
    content = _canonical_json(report.model_dump(mode="json"))
    artifact = session.query(DBArtifact).filter_by(
        creating_task_id=task.id,
        artifact_type=M3_MATCHING_REPORT_TYPE,
    ).first()
    if artifact is None:
        artifact, version = create_artifact_with_version(
            session,
            owner_public_id=task.owner_public_id,
            artifact_type=M3_MATCHING_REPORT_TYPE,
            title="M3 个人学情与资源匹配报告",
            content=content,
            content_format="json",
            course_id=task.course_id,
            creating_task_id=task.id,
            metadata={
                "trace_id": task.trace_id,
                "profile_snapshot_id": report.profile_snapshot_id,
                "plan_version_id": report.plan_version_id,
                "algorithm_version": M3_MATCHING_ALGORITHM_VERSION,
                "learning_event_ids": list(report.performance.learning_event_ids),
            },
        )
        return artifact, version, True
    current = session.query(DBArtifactVersion).filter_by(id=artifact.current_version_id).one()
    if current.content == content:
        return artifact, current, False
    version = add_artifact_version(
        session,
        artifact=artifact,
        content=content,
        content_format="json",
        created_by_public_id=task.owner_public_id,
        created_task_id=task.id,
        metadata={
            "trace_id": task.trace_id,
            "profile_snapshot_id": report.profile_snapshot_id,
            "plan_version_id": report.plan_version_id,
            "algorithm_version": M3_MATCHING_ALGORITHM_VERSION,
            "learning_event_ids": list(report.performance.learning_event_ids),
        },
    )
    return artifact, version, True
