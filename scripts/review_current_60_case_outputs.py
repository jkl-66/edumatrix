"""Review the 60-case deterministic output snapshots with a strict internal rubric."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from review_current_profile_resources import score_resource  # noqa: PLC0415


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "competition_submission_rebuild" / "test_data"
EVAL_DIR = DATA / "current_evaluation_20260905"
CASE_FILE = EVAL_DIR / "current_60_case_execution.jsonl"
PROFILE_FILE = DATA / "learner_profiles.json"
KP_FILE = DATA / "knowledge_base" / "knowledge_points.jsonl"


def main() -> None:
    profiles = {item["profile_id"]: item for item in json.loads(PROFILE_FILE.read_text(encoding="utf-8"))["profiles"]}
    cases = [json.loads(line) for line in CASE_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    all_kps = {item["knowledge_point_id"] for item in (json.loads(line) for line in KP_FILE.read_text(encoding="utf-8").splitlines() if line.strip())}
    annotations = []
    executed_case_count = 0
    for case in cases:
        if case.get("status") == "executed":
            executed_case_count += 1
        source_profile = profiles[case["profile_id"]]
        profile = {
            "logical_profile_id": case["profile_id"],
            "course_id": case["course_id"],
            "knowledge_point_id": case.get("knowledge_point_id"),
            "profile_adaptation_plan": source_profile.get("adaptation_plan") or {},
        }
        for artifact in case.get("resource_outputs") or []:
            if artifact.get("artifact_type") not in {"handout", "training_task", "quiz"}:
                continue
            row = score_resource(profile, artifact)
            row["case_id"] = case["case_id"]
            row["case_category"] = case["category"]
            annotations.append(row)

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

    covered_kps = {str(case.get("knowledge_point_id")) for case in cases if case.get("knowledge_point_id")}
    # The official 33-point codes are not all present as IDs in the execution
    # rows; retain an ID-level sample and a declared corpus denominator.
    course_counts = Counter(str(case.get("course_id")) for case in cases if case.get("knowledge_point_id"))
    missing_excerpt = sum(item["evidence"]["missing_source_excerpt_count"] > 0 for item in annotations)
    summary = {
        "schema_version": "xh-202630.current-60-case-review.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": "internal-reviewer-01",
        "review_policy": "single_person_internal_strict_review; not independent domain validation",
        "case_count": len(cases),
        "executed_case_count": executed_case_count,
        "core_resource_sample_count": len(annotations),
        "adaptation_accuracy_preliminary": {
            "status": "preliminary_internal_only",
            "numerator": passed,
            "denominator": len(annotations),
            "percent": round(passed / len(annotations) * 100, 4) if annotations else None,
            "target_percent": 85,
            "pass_rule": "six dimensions scored 0-2; total >= 10/12; difficulty and prerequisite > 0",
        },
        "by_profile": by_profile,
        "coverage_preliminary": {
            "covered_knowledge_point_ids": sorted(covered_kps),
            "covered_id_count": len(covered_kps),
            "declared_corpus_knowledge_point_count": len(all_kps),
            "percent_of_declared_corpus": round(len(covered_kps) / len(all_kps) * 100, 4) if all_kps else None,
            "course_case_counts": dict(course_counts),
            "status": "preliminary_scope_only",
        },
        "hallucination_review": {
            "status": "insufficient_for_metric",
            "atomic_claim_annotation_count": 0,
            "resources_with_missing_source_excerpt": missing_excerpt,
            "reason": "Resource snapshots have no claim-by-claim semantic adjudication; missing excerpts remain unknown until reviewed.",
        },
        "limitations": [
            "Deterministic resource-engine results are not external-model quality evidence.",
            "The 60-case runner performs current context validation and resource generation probes; it does not simulate human learning outcomes.",
            "The coverage denominator is the current rebuilt corpus, while this run intentionally targets only the knowledge points selected by each profile.",
        ],
    }
    (EVAL_DIR / "current_60_case_adaptation_annotations.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in annotations), encoding="utf-8"
    )
    (EVAL_DIR / "current_60_case_review.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (EVAL_DIR / "current_60_case_review.md").write_text(
        "# 当前 60 案例输出内部复核\n\n"
        f"案例执行记录：{len(cases)} 条；核心资源样本：{len(annotations)} 条；通过：{passed} 条。\n\n"
        f"内部预备适配准确率：`{passed}/{len(annotations)} = {summary['adaptation_accuracy_preliminary']['percent']}%`，低于目标 85%。\n\n"
        f"当前执行样例覆盖知识点：{len(covered_kps)}/{len(all_kps)} = {summary['coverage_preliminary']['percent_of_declared_corpus']}%，不代表正式核心覆盖率。\n\n"
        "幻觉率仍未计算，因为没有原子事实标注和逐 claim 来源复核。\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str((EVAL_DIR / "current_60_case_review.json").relative_to(ROOT)),
        "case_count": len(cases),
        "core_resource_sample_count": len(annotations),
        "adaptation": summary["adaptation_accuracy_preliminary"],
        "coverage": summary["coverage_preliminary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
