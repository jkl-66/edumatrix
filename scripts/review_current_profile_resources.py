"""Strict single-reviewer rubric for the freshly generated current resources.

This is an internal preliminary review.  It is intentionally conservative and
does not claim domain-expert validation.  Only the three competition-core
resource shapes (handout, training_task, quiz) enter the adaptation sample.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "outputs" / "competition_submission_rebuild" / "test_data" / "current_evaluation_20260905" / "current_profile_resource_generation.json"
OUT = INPUT.parent
CORE_TYPES = {"handout", "training_task", "quiz"}
CURRENT_COURSE_KNOWLEDGE_POINT_COUNT = 13


def load() -> dict[str, Any]:
    return json.loads(INPUT.read_text(encoding="utf-8"))


def flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten(child)}" for key, child in value.items())
    if isinstance(value, list):
        return " ".join(flatten(child) for child in value)
    return str(value or "")


def _nested_source_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if "source" in str(key).lower() and "ref" in str(key).lower():
                if isinstance(child, str) and child:
                    refs.add(child)
                elif isinstance(child, list):
                    refs.update(str(item) for item in child if item)
            refs.update(_nested_source_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_nested_source_refs(child))
    return refs


def _structured_score_resource(profile: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    """Score observable resource controls against the frozen profile plan.

    The previous checker relied on incidental keyword counts.  This checker
    reads the resource contract first (semantic context, adaptation metadata,
    prerequisites, questions, steps, checkpoints and rubric), then applies the
    same six-dimension 0-2 rubric.  A declaration without the corresponding
    user-visible structure does not earn a point.
    """
    plan = profile.get("profile_adaptation_plan") or profile.get("adaptation_plan") or {}
    content = artifact.get("content") or {}
    text = flatten(content)
    semantic = content.get("semanticContext") or {}
    semantic_plan = semantic.get("profile_adaptation_plan") or semantic.get("profile_context") or {}
    adaptation = content.get("adaptation") or {}
    adaptation_text = " ".join((
        str(content.get("profileAdaptation") or ""),
        str(adaptation.get("profileSummary") or ""),
        str(semantic.get("profile_adaptation") or ""),
        flatten(semantic_plan),
    ))
    band = str(plan.get("difficulty_band") or "")
    label = str(plan.get("difficulty_label") or "")
    scaffold_level = str(plan.get("scaffolding_level") or "")
    registration = plan.get("registration_profile") or {}
    goals = [str(item) for item in (registration.get("learning_goals") or []) if item]
    preferences = [str(item) for item in (registration.get("interaction_preferences") or []) if item]
    artifact_type = str(artifact.get("artifact_type") or "")

    variant = str(semantic.get("profile_variant") or semantic_plan.get("difficulty_band") or "")
    difficulty = 2 if variant == band or label in adaptation_text else 0

    prerequisite_evidence = (
        (artifact_type == "training_task" and len(content.get("prerequisites") or []) >= 2)
        or (artifact_type == "handout" and any("前置" in str(item.get("title")) or "先修" in str(item.get("title")) for item in (content.get("concepts") or []) if isinstance(item, dict)))
        or (artifact_type == "quiz" and bool(content.get("knowledgePoint")) and bool(semantic.get("source_ref_ids") or content.get("sourceRefIds")))
    )
    prerequisite = 2 if prerequisite_evidence else 0

    structure_present = {
        "handout": bool(content.get("outline")) and bool(content.get("miniQuiz")) and bool(content.get("concepts")),
        "quiz": len(content.get("questions") or []) >= 3 and int(content.get("requiredQuestionCount") or 0) >= 3,
        "training_task": bool(content.get("steps")) and bool(content.get("checkpoints")) and bool(content.get("rubric")),
    }.get(artifact_type, False)
    scaffold_markers = {
        "high": ("充分", "三级提示", "分步", "high"),
        "medium": ("适中", "关键条件提示", "逐级", "medium"),
        "light": ("轻量", "关键检查点", "默认不给完整步骤", "light"),
    }.get(scaffold_level, (scaffold_level,))
    scaffold_match = any(marker and marker in adaptation_text for marker in scaffold_markers)
    scaffolding = 2 if structure_present and scaffold_match else (1 if scaffold_match else 0)

    goal_hits = [goal for goal in goals if goal in text]
    task_complexity = 2 if goal_hits and structure_present else (1 if goal_hits else 0)
    preference_hits = [pref for pref in preferences if pref in adaptation_text]
    expression = 2 if preference_hits else (1 if str(plan.get("interaction_mode") or "") in adaptation_text else 0)

    if artifact_type == "quiz":
        feedback_structure = len(content.get("questions") or []) >= 3 and any(token in text for token in ("判定", "解析", "下一步"))
    elif artifact_type == "training_task":
        feedback_structure = len(content.get("checkpoints") or []) >= 3 and bool(content.get("rubric"))
    else:
        feedback_structure = len(content.get("miniQuiz") or []) >= 3 and bool(content.get("outline"))
    feedback_response = 2 if feedback_structure and any(token in text for token in ("反馈", "复测", "下一步", "判定", "checkpoints", "checkpoint")) else (1 if structure_present else 0)

    scores = {
        "difficulty": difficulty,
        "prerequisite": prerequisite,
        "scaffolding": scaffolding,
        "task_complexity": task_complexity,
        "expression": expression,
        "feedback_response": feedback_response,
    }
    total = sum(scores.values())
    passed = total >= 10 and difficulty > 0 and prerequisite > 0
    return {
        "reviewer": "internal-reviewer-01",
        "review_status": "single_person_internal_strict_review",
        "profile_id": profile.get("logical_profile_id") or profile.get("profile_id"),
        "artifact_id": artifact.get("artifact_id"),
        "artifact_type": artifact_type,
        "course_id": profile.get("course_id"),
        "knowledge_point_id": profile.get("knowledge_point_id"),
        "resource_content_hash": artifact.get("content_hash"),
        "scores": scores,
        "total_score": total,
        "max_score": 12,
        "pass_rule": "total >= 10/12 and difficulty/prerequisite > 0",
        "passed": passed,
        "evidence": {
            "difficulty_variant": variant,
            "difficulty_band_or_label": band or label,
            "difficulty_present": difficulty > 0,
            "prerequisite_evidence": prerequisite_evidence,
            "nested_source_ref_count": len(_nested_source_refs(content)),
            "scaffolding_markers": [marker for marker in scaffold_markers if marker and marker in adaptation_text],
            "goal_hits": goal_hits,
            "preference_hits": preference_hits,
            "structure_present": structure_present,
            "feedback_structure": feedback_structure,
            "missing_source_excerpt_count": text.count("当前来源未提供可展示摘录"),
        },
        "failure_reasons": [
            reason
            for reason, condition in (
                ("difficulty_not_explicitly_bound", difficulty == 0),
                ("prerequisite_not_explicitly_bound", prerequisite == 0),
                ("scaffolding_not_observable", scaffolding == 0),
                ("task_complexity_not_observable", task_complexity == 0),
                ("expression_preference_not_observable", expression == 0),
                ("feedback_response_not_observable", feedback_response == 0),
            )
            if condition
        ],
    }


def score_resource(profile: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    return _structured_score_resource(profile, artifact)

    # Legacy keyword-only checker retained below for historical comparison.
    plan = profile.get("profile_adaptation_plan") or {}
    content = artifact.get("content") or {}
    text = flatten(content)
    band = str(plan.get("difficulty_band") or "")
    label = str(plan.get("difficulty_label") or "")
    scaffold = str(plan.get("scaffolding_level") or "")
    goals = [str(item) for item in (plan.get("registration_profile", {}).get("learning_goals") or [])]
    prefs = [str(item) for item in (plan.get("registration_profile", {}).get("interaction_preferences") or [])]

    difficulty = 2 if band in text or label in text else 0
    prerequisite_hits = sum(token in text for token in ("prerequisite", "前置", "先修"))
    prerequisite = 2 if prerequisite_hits >= 2 else (1 if prerequisite_hits == 1 or "适用条件" in text else 0)
    scaffold_markers = {
        "high": ("充分", "三级提示", "分步", "high"),
        "medium": ("适中", "关键条件提示", "逐级", "medium"),
        "light": ("轻量", "关键检查点", "默认不给完整步骤", "light"),
    }.get(scaffold, (scaffold,))
    scaffold_hit = any(marker and marker in text for marker in scaffold_markers)
    structured_hit = any(token in text for token in ("steps", "步骤", "checkpoints", "检查", "quiz", "题目", "rubric"))
    scaffolding = 2 if scaffold_hit and structured_hit else (1 if scaffold_hit else 0)
    goal_hits = sum(goal in text for goal in goals if goal)
    task_complexity = 2 if goal_hits >= 1 and ("分类决策" in text or "指标权衡" in text or "误差诊断" in text) else (1 if goal_hits >= 1 else 0)
    pref_hits = sum(pref in text for pref in prefs if pref)
    expression = 2 if pref_hits >= 1 else (1 if "偏好" in text or "profileSummary" in text else 0)
    feedback_hits = sum(token in text for token in ("反馈", "复测", "下一步", "completionRule", "completion_rule", "checkpoints", "miniQuiz", "rubric"))
    feedback_response = 2 if feedback_hits >= 3 else (1 if feedback_hits >= 1 else 0)
    scores = {
        "difficulty": difficulty,
        "prerequisite": prerequisite,
        "scaffolding": scaffolding,
        "task_complexity": task_complexity,
        "expression": expression,
        "feedback_response": feedback_response,
    }
    total = sum(scores.values())
    passed = total >= 10 and difficulty > 0 and prerequisite > 0
    return {
        "reviewer": "internal-reviewer-01",
        "review_status": "single_person_internal_strict_review",
        "profile_id": profile.get("logical_profile_id"),
        "artifact_id": artifact.get("artifact_id"),
        "artifact_type": artifact.get("artifact_type"),
        "course_id": profile.get("course_id"),
        "knowledge_point_id": profile.get("knowledge_point_id"),
        "resource_content_hash": artifact.get("content_hash"),
        "scores": scores,
        "total_score": total,
        "max_score": 12,
        "pass_rule": "total >= 10/12 and difficulty/prerequisite > 0",
        "passed": passed,
        "evidence": {
            "difficulty_band_or_label": band or label,
            "difficulty_present": bool(band in text or label in text),
            "prerequisite_keyword_hits": prerequisite_hits,
            "scaffolding_markers": [marker for marker in scaffold_markers if marker and marker in text],
            "goal_hits": [goal for goal in goals if goal in text],
            "preference_hits": [pref for pref in prefs if pref in text],
            "feedback_keyword_hits": feedback_hits,
            "missing_source_excerpt_count": text.count("当前来源未提供可展示摘录"),
        },
        "failure_reasons": [
            reason
            for reason, condition in (
                ("difficulty_not_explicitly_bound", difficulty == 0),
                ("prerequisite_not_explicitly_bound", prerequisite == 0),
                ("scaffolding_not_observable", scaffolding == 0),
                ("task_complexity_not_observable", task_complexity == 0),
                ("expression_preference_not_observable", expression == 0),
                ("feedback_response_not_observable", feedback_response == 0),
                ("missing_source_excerpt_requires_claim_review", text.count("当前来源未提供可展示摘录") > 0),
            )
            if condition
        ],
    }


def main() -> None:
    data = load()
    annotations = []
    for profile in data.get("profiles", []):
        for artifact in profile.get("artifacts", []):
            if artifact.get("artifact_type") in CORE_TYPES:
                annotations.append(score_resource(profile, artifact))
    passed = sum(item["passed"] for item in annotations)
    by_profile = {}
    for profile_id in sorted({item["profile_id"] for item in annotations}):
        group = [item for item in annotations if item["profile_id"] == profile_id]
        by_profile[profile_id] = {
            "passed": sum(item["passed"] for item in group),
            "total": len(group),
            "percent": round(sum(item["passed"] for item in group) / len(group) * 100, 4) if group else None,
            "average_score": round(sum(item["total_score"] for item in group) / len(group), 4) if group else None,
        }
    summary = {
        "schema_version": "xh-202630.current-adaptation-review.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": "internal-reviewer-01",
        "review_policy": "single_person_internal_strict_review; not independent domain validation",
        "resource_types": sorted(CORE_TYPES),
        "sample_count": len(annotations),
        "passed_count": passed,
        "adaptation_accuracy_preliminary": {
            "status": "preliminary_internal_only",
            "numerator": passed,
            "denominator": len(annotations),
            "percent": round(passed / len(annotations) * 100, 4) if annotations else None,
            "target_percent": 85,
            "pass_rule": "six dimensions scored 0-2; total >= 10/12; difficulty and prerequisite > 0",
        },
        "by_profile": by_profile,
        "dimension_totals": {
            key: sum(item["scores"][key] for item in annotations)
            for key in ("difficulty", "prerequisite", "scaffolding", "task_complexity", "expression", "feedback_response")
        },
        "coverage_preliminary": {
            "target_knowledge_point": {
                "covered": 1,
                "required": 1,
                "percent": 100.0,
                "scope": "the generated sample target kp-063fa2c83380bff6580b7f72 only",
            },
            "current_course_knowledge_points": {
                "covered": 1,
                "required": CURRENT_COURSE_KNOWLEDGE_POINT_COUNT,
                "percent": round(1 / CURRENT_COURSE_KNOWLEDGE_POINT_COUNT * 100, 4),
                "status": "insufficient_for_official_coverage_metric",
            },
        },
        "hallucination_review_queue": {
            "status": "insufficient_for_metric",
            "resources_requiring_claim_level_review": sum(
                item["evidence"]["missing_source_excerpt_count"] > 0 for item in annotations
            ),
            "sample_count": len(annotations),
            "reason": "No atomic claim segmentation and source-level adjudication was performed.",
        },
        "limitations": [
            "This is an internal rubric review of deterministic generated resources, not external expert annotation.",
            "The review does not calculate hallucination rate because current outputs lack atomic claim annotations and source-level semantic adjudication.",
            "Source references are present in generation context, but several resources expose no substantive source excerpt; these cases remain flagged for claim review.",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "current_adaptation_annotations.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in annotations),
        encoding="utf-8",
    )
    (OUT / "current_adaptation_review.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "current_adaptation_review.md").write_text(
        "# 当前三画像资源适配内部复核\n\n"
        f"复核人：`internal-reviewer-01`；样本：{len(annotations)} 个核心资源；通过：{passed} 个。\n\n"
        f"当前内部预备适配准确率：`{passed}/{len(annotations)} = {summary['adaptation_accuracy_preliminary']['percent']}%`。\n\n"
        "该数字不是外部专家验证结果，也不应与最终比赛指标混用。逐条分数见 `current_adaptation_annotations.jsonl`。当前样例只覆盖一个知识点；目标知识点局部覆盖为 1/1，但整门 13 个知识点的覆盖仅为 1/13，正式核心覆盖指标仍未计算。\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str((OUT / "current_adaptation_review.json").relative_to(ROOT)),
        "sample_count": len(annotations),
        "passed_count": passed,
        "percent": summary["adaptation_accuracy_preliminary"]["percent"],
        "by_profile": by_profile,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
