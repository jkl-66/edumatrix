"""Frozen three-profile benchmark contracts for the M3 competition loop."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.m2_contracts import StrictModel


ROOT = Path(__file__).resolve().parent.parent
M0_PROFILE_DATASET = (
    ROOT
    / "outputs"
    / "M0_阶段0基线与架构契约"
    / "datasets"
    / "baseline_profiles.json"
)
M3_PROFILE_SET_VERSION = "m3.gold-profiles.v1"
M3_SHARED_JOB_TASK_ID = "JOB-05"
M3_SHARED_TARGET_KNOWLEDGE_POINT_CODES = ("KP-11", "KP-12", "KP-13")


class M3ProfileContractError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AbilityInterval(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    low: float = Field(ge=0.0, le=1.0)
    high: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_interval(self):
        if self.low > self.high:
            raise ValueError("ability interval low must not exceed high")
        return self


class DomainSkillVector(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    theoretical_understanding: AbilityInterval
    tool_fluency: AbilityInterval
    task_execution: AbilityInterval
    troubleshooting: AbilityInterval
    standards_awareness: AbilityInterval
    transfer_ability: AbilityInterval


class M0ExpectedResource(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    difficulty: str
    scaffolding: Literal["high", "medium", "low"]
    lecture: str
    lab: str
    quiz: str


class M0ProfileRecord(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: str
    student_id: str
    label: str
    background: dict[str, str]
    goal: str
    constraints: dict[str, object]
    initial_mastery: dict[str, float]
    evidence: tuple[str, ...] = Field(min_length=1)
    expected_first_path: tuple[str, ...] = Field(min_length=1)
    expected_resource: M0ExpectedResource
    expected_change_after_success: dict[str, str]


class M0ProfileDataset(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["baseline-profile-0.1"]
    data_class: Literal["P2-SYNTHETIC"]
    notice: str
    profiles: tuple[M0ProfileRecord, ...]


class AdaptationStrategy(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    difficulty_band: str
    scaffolding: Literal["high", "medium", "low"]
    terminology_density: Literal["low", "medium", "high"]
    step_granularity: Literal["short", "controlled", "open"]
    hint_policy: Literal["progressive", "on_failure", "minimal"]
    task_openness: Literal["guided", "bounded", "open"]
    quiz_emphasis: Literal["recognition_application", "application_debugging", "diagnosis_decision"]
    rationale: tuple[str, ...] = Field(min_length=3)
    invariant_fact_standard: Literal["unchanged"] = "unchanged"
    invariant_safety_standard: Literal["unchanged"] = "unchanged"


class M3GoldProfile(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    archetype: Literal["beginner", "theory_practice_gap", "advanced"]
    source_profile: M0ProfileRecord
    shared_job_task_id: Literal["JOB-05"] = M3_SHARED_JOB_TASK_ID
    target_knowledge_point_codes: tuple[str, ...] = M3_SHARED_TARGET_KNOWLEDGE_POINT_CODES
    ability_vector: DomainSkillVector
    adaptation_strategy: AdaptationStrategy


class M3GoldProfileSet(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["m3.gold-profiles.v1"] = M3_PROFILE_SET_VERSION
    source_schema_version: Literal["baseline-profile-0.1"]
    source_data_class: Literal["P2-SYNTHETIC"]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profiles: tuple[M3GoldProfile, ...]


def _interval(low: float, high: float, evidence_ref: str) -> AbilityInterval:
    return AbilityInterval(
        low=low,
        high=high,
        confidence=0.8,
        evidence_refs=(evidence_ref,),
    )


def _vector(profile_id: str) -> DomainSkillVector:
    evidence = f"m0.baseline_profiles:{profile_id}"
    vectors = {
        "profile-m0-beginner": (0.10, 0.25, 0.05, 0.20, 0.05, 0.20, 0.00, 0.15, 0.10, 0.25, 0.00, 0.15),
        "profile-m0-theory": (0.65, 0.80, 0.35, 0.55, 0.30, 0.50, 0.20, 0.40, 0.40, 0.60, 0.35, 0.55),
        "profile-m0-advanced": (0.75, 0.90, 0.75, 0.90, 0.70, 0.85, 0.55, 0.75, 0.55, 0.75, 0.60, 0.80),
    }
    values = vectors.get(profile_id)
    if values is None:
        raise M3ProfileContractError("unknown_gold_profile", f"unsupported M0 profile: {profile_id}")
    intervals = [_interval(values[index], values[index + 1], evidence) for index in range(0, 12, 2)]
    return DomainSkillVector(
        theoretical_understanding=intervals[0],
        tool_fluency=intervals[1],
        task_execution=intervals[2],
        troubleshooting=intervals[3],
        standards_awareness=intervals[4],
        transfer_ability=intervals[5],
    )


def _strategy(profile: M0ProfileRecord) -> tuple[str, AdaptationStrategy]:
    strategies = {
        "profile-m0-beginner": (
            "beginner",
            AdaptationStrategy(
                difficulty_band="L0-L1",
                scaffolding="high",
                terminology_density="low",
                step_granularity="short",
                hint_policy="progressive",
                task_openness="guided",
                quiz_emphasis="recognition_application",
                rationale=(
                    "background.rag_project=无",
                    "constraints.prefers includes 短步骤",
                    "expected_resource.scaffolding=high",
                ),
            ),
        ),
        "profile-m0-theory": (
            "theory_practice_gap",
            AdaptationStrategy(
                difficulty_band="L1-L2",
                scaffolding="medium",
                terminology_density="medium",
                step_granularity="controlled",
                hint_policy="on_failure",
                task_openness="bounded",
                quiz_emphasis="application_debugging",
                rationale=(
                    "background.ml=扎实",
                    "evidence includes 无法定位 owner 过滤失败",
                    "constraints.avoid includes 重复基础理论",
                ),
            ),
        ),
        "profile-m0-advanced": (
            "advanced",
            AdaptationStrategy(
                difficulty_band="L2-L4",
                scaffolding="low",
                terminology_density="high",
                step_granularity="open",
                hint_policy="minimal",
                task_openness="open",
                quiz_emphasis="diagnosis_decision",
                rationale=(
                    "background.rag_project=做过基础向量问答",
                    "constraints.prefers includes 隐藏测试",
                    "goal includes 故障恢复和企业岗位迁移能力",
                ),
            ),
        ),
    }
    result = strategies.get(profile.profile_id)
    if result is None:
        raise M3ProfileContractError("unknown_gold_profile", f"unsupported M0 profile: {profile.profile_id}")
    return result


def load_m3_gold_profiles(path: Path = M0_PROFILE_DATASET) -> M3GoldProfileSet:
    """Load the frozen synthetic benchmark and reject silent scope changes."""
    try:
        raw = path.read_bytes()
        dataset = M0ProfileDataset.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        raise M3ProfileContractError("gold_profile_dataset_invalid", str(exc)) from exc

    expected_ids = (
        "profile-m0-beginner",
        "profile-m0-theory",
        "profile-m0-advanced",
    )
    actual_ids = tuple(profile.profile_id for profile in dataset.profiles)
    if actual_ids != expected_ids:
        raise M3ProfileContractError(
            "gold_profile_set_changed",
            f"expected ordered profiles {expected_ids}, got {actual_ids}",
        )
    if len({profile.student_id for profile in dataset.profiles}) != 3:
        raise M3ProfileContractError("gold_profile_student_conflict", "student IDs must be unique")

    profiles = []
    for source_profile in dataset.profiles:
        archetype, strategy = _strategy(source_profile)
        if source_profile.expected_resource.difficulty != strategy.difficulty_band:
            raise M3ProfileContractError(
                "gold_profile_strategy_mismatch",
                f"difficulty mismatch for {source_profile.profile_id}",
            )
        if source_profile.expected_resource.scaffolding != strategy.scaffolding:
            raise M3ProfileContractError(
                "gold_profile_strategy_mismatch",
                f"scaffolding mismatch for {source_profile.profile_id}",
            )
        profiles.append(
            M3GoldProfile(
                archetype=archetype,
                source_profile=source_profile,
                ability_vector=_vector(source_profile.profile_id),
                adaptation_strategy=strategy,
            )
        )

    return M3GoldProfileSet(
        source_schema_version=dataset.schema_version,
        source_data_class=dataset.data_class,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        profiles=tuple(profiles),
    )
