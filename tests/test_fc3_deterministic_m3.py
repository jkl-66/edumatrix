from __future__ import annotations

import json

from app.m3_debate import DebateRoundOutput
from app.m3_resources import M3PersonalizedResourceBundle
from llm_client import DeterministicEducationLLM


def _personalization() -> dict:
    return {
        "difficulty_band": "L1-L2",
        "scaffolding": "medium",
        "terminology_density": "medium",
        "step_granularity": "controlled",
        "hint_policy": "on_failure",
        "task_openness": "bounded",
        "quiz_emphasis": "application_debugging",
        "rationale_refs": ["evidence:a", "evidence:b", "evidence:c"],
        "fact_standard": "unchanged",
        "safety_standard": "unchanged",
        "profile_snapshot_id": "profile-snapshot-fc3",
    }


def test_deterministic_backend_generates_strict_m3_bundle_and_split_artifact():
    backend = DeterministicEducationLLM()
    request = {
        "context": {
            "target_knowledge_point_ids": ["kp-fc3"],
            "source_ref_ids": ["ref-fc3"],
        },
        "profile": {
            "source_profile_id": "profile-m0-theory",
            "personalization": _personalization(),
        },
    }
    full = json.loads(backend.generate("JSON Schema", json.dumps(request), role="M3领域生成"))
    validated = M3PersonalizedResourceBundle.model_validate(full)
    assert validated.lesson.personalization.profile_snapshot_id == "profile-snapshot-fc3"
    assert len(validated.lab_guide.steps) == 3

    request["artifact_type"] = "tiered_quiz"
    split = json.loads(backend.generate("JSON Schema", json.dumps(request), role="M3领域生成:tiered_quiz"))
    assert split["artifact_type"] == "tiered_quiz"
    assert [tier["level"] for tier in split["tiers"]] == ["foundation", "application", "advanced"]


def test_deterministic_backend_generates_scoped_m3_debate_review():
    backend = DeterministicEducationLLM()
    request = {
        "claim": {"proposed_source_ref_ids": ["ref-fc3"]},
        "round_number": 1,
        "previous_rounds": [],
        "required_schema": DebateRoundOutput.model_json_schema(),
    }
    raw = backend.generate("Return JSON only and satisfy JSON Schema", json.dumps(request), role="evidence_review")
    review = DebateRoundOutput.model_validate_json(raw)
    assert review.judge.verdict == "keep"
    assert review.judge.evidence_ref_ids == ("ref-fc3",)
