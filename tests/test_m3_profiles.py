from __future__ import annotations

import json

import pytest

from app.m3_profiles import (
    M0_PROFILE_DATASET,
    M3ProfileContractError,
    load_m3_gold_profiles,
)


def _midpoint(interval) -> float:
    return (interval.low + interval.high) / 2


def test_loads_exactly_three_frozen_synthetic_profiles_for_one_shared_goal():
    profile_set = load_m3_gold_profiles()

    assert profile_set.source_data_class == "P2-SYNTHETIC"
    assert len(profile_set.source_sha256) == 64
    assert [item.source_profile.profile_id for item in profile_set.profiles] == [
        "profile-m0-beginner",
        "profile-m0-theory",
        "profile-m0-advanced",
    ]
    assert {item.shared_job_task_id for item in profile_set.profiles} == {"JOB-05"}
    assert {item.target_knowledge_point_codes for item in profile_set.profiles} == {
        ("KP-11", "KP-12", "KP-13")
    }


def test_ability_intervals_and_resource_strategies_have_explainable_differences():
    beginner, theory, advanced = load_m3_gold_profiles().profiles

    for dimension in (
        "theoretical_understanding",
        "tool_fluency",
        "task_execution",
        "troubleshooting",
        "standards_awareness",
        "transfer_ability",
    ):
        values = [
            _midpoint(getattr(profile.ability_vector, dimension))
            for profile in (beginner, theory, advanced)
        ]
        assert values[0] < values[1] < values[2], dimension

    assert [item.adaptation_strategy.scaffolding for item in (beginner, theory, advanced)] == [
        "high",
        "medium",
        "low",
    ]
    assert [item.adaptation_strategy.task_openness for item in (beginner, theory, advanced)] == [
        "guided",
        "bounded",
        "open",
    ]
    assert all(item.adaptation_strategy.rationale for item in (beginner, theory, advanced))
    assert all(item.adaptation_strategy.invariant_fact_standard == "unchanged" for item in (beginner, theory, advanced))
    assert all(item.adaptation_strategy.invariant_safety_standard == "unchanged" for item in (beginner, theory, advanced))


def test_profile_loader_rejects_silent_profile_set_changes(tmp_path):
    payload = json.loads(M0_PROFILE_DATASET.read_text(encoding="utf-8"))
    payload["profiles"] = payload["profiles"][:2]
    changed = tmp_path / "baseline_profiles.json"
    changed.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(M3ProfileContractError) as raised:
        load_m3_gold_profiles(changed)

    assert raised.value.code == "gold_profile_set_changed"
