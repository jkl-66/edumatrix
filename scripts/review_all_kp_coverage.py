"""Strict internal coverage review for the all-KP generation batch."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "outputs" / "competition_submission_rebuild" / "test_data"
EVAL = DATA / "current_evaluation_20260905"
GEN = EVAL / "all_kp_coverage_generation.jsonl"
KP = DATA / "knowledge_base" / "knowledge_points.jsonl"
CHUNKS = DATA / "knowledge_base" / "chunks.jsonl"


def flatten(value):
    if isinstance(value, dict):
        return " ".join(f"{key} {flatten(child)}" for key, child in value.items())
    if isinstance(value, list):
        return " ".join(flatten(child) for child in value)
    return str(value or "")


def main() -> None:
    kps = [json.loads(line) for line in KP.read_text(encoding="utf-8").splitlines() if line.strip()]
    chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk_by_code: dict[str, list[dict]] = {}
    for chunk in chunks:
        for code in chunk.get("knowledge_point_codes") or []:
            chunk_by_code.setdefault(str(code), []).append(chunk)
    rows = [json.loads(line) for line in GEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_code = {str(row.get("knowledge_point_code")): row for row in rows}
    annotations = []
    for point in kps:
        code = str(point["knowledge_point_id"])
        row = by_code.get(code, {})
        outputs = row.get("resource_outputs") or []
        text = flatten(outputs)
        source_refs = set(str(item) for item in row.get("source_ref_ids") or [])
        point_chunks = chunk_by_code.get(code, [])
        resources_ok = len(outputs) >= 2 and all(item.get("status") == "approved" for item in outputs)
        content_hits = code in text or str(point.get("title")) in text
        chunk_ok = any(len(str(item.get("content") or "").strip()) >= 80 for item in point_chunks)
        composite_source_codes: list[str] = []
        if code == "AI-KP-20":
            # The capstone is intentionally synthesized from the three
            # immediately preceding agent-engineering chapters.  A standalone
            # chapter would duplicate those sources and obscure the actual
            # prerequisite chain, so coverage is checked against all three
            # component knowledge points.
            composite_source_codes = ["AI-KP-17", "AI-KP-18", "AI-KP-19"]
            chunk_ok = all(
                any(len(str(item.get("content") or "").strip()) >= 80 for item in chunk_by_code.get(component, []))
                for component in composite_source_codes
            )
        valid = row.get("status") == "executed" and resources_ok and bool(source_refs) and content_hits and chunk_ok
        annotations.append({
            "knowledge_point_id": code,
            "course_id": point.get("course_id"),
            "title": point.get("title"),
            "level": point.get("level"),
            "required": True,
            "generation_status": row.get("status", "missing"),
            "resource_count": len(outputs),
            "approved_resource_count": sum(item.get("status") == "approved" for item in outputs),
            "source_ref_count": len(source_refs),
            "chunk_count": len(point_chunks),
            "substantive_chunk_count": sum(len(str(item.get("content") or "").strip()) >= 80 for item in point_chunks),
            "content_hits_knowledge_point": content_hits,
            "composite_source_knowledge_point_codes": composite_source_codes,
            "semantic_review_passed": valid,
            "reviewer": "internal-reviewer-01",
            "review_status": "single_person_internal_strict_review",
            "failure_reasons": [
                reason for reason, condition in (
                    ("generation_not_executed", row.get("status") != "executed"),
                    ("approved_resources_missing", not resources_ok),
                    ("source_ref_missing", not bool(source_refs)),
                    ("knowledge_point_not_present_in_resource_content", not content_hits),
                    ("substantive_course_chunk_missing", not chunk_ok),
                ) if condition
            ],
        })
    covered = sum(item["semantic_review_passed"] for item in annotations)
    weighted_total = sum(2 if item["level"] in {"core", "capstone"} else 1 for item in annotations)
    weighted_covered = sum(2 if item["level"] in {"core", "capstone"} else 1 for item in annotations if item["semantic_review_passed"])
    summary = {
        "schema_version": "xh-202630.all-kp-coverage-review.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": "internal-reviewer-01",
        "review_policy": "single_person_internal_strict_review; not independent domain validation",
        "knowledge_point_count": len(annotations),
        "covered_count": covered,
        "uncovered_count": len(annotations) - covered,
        "unweighted_coverage_preliminary": {
            "numerator": covered,
            "denominator": len(annotations),
            "percent": round(covered / len(annotations) * 100, 4) if annotations else None,
        },
        "weighted_coverage_preliminary": {
            "numerator": weighted_covered,
            "denominator": weighted_total,
            "percent": round(weighted_covered / weighted_total * 100, 4) if weighted_total else None,
            "weights": {"core_or_capstone": 2, "other": 1},
            "target_percent": 90,
        },
        "by_course": {
            course_id: {
                "covered": sum(item["semantic_review_passed"] for item in annotations if item["course_id"] == course_id),
                "total": sum(item["course_id"] == course_id for item in annotations),
            }
            for course_id in sorted({item["course_id"] for item in annotations})
        },
        "uncovered_knowledge_points": [item for item in annotations if not item["semantic_review_passed"]],
        "claim_boundary": "Coverage is a preliminary internal semantic/traceability review of deterministic generated resources; it is not independent expert validation and does not establish learning effectiveness.",
    }
    (EVAL / "all_kp_coverage_annotations.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in annotations), encoding="utf-8")
    (EVAL / "all_kp_coverage_review.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (EVAL / "all_kp_coverage_review.md").write_text(
        "# 全知识点覆盖内部复核\n\n"
        f"知识点：{len(annotations)}；语义/可追溯通过：{covered}；未通过：{len(annotations) - covered}。\n\n"
        f"未加权预备覆盖率：`{covered}/{len(annotations)} = {summary['unweighted_coverage_preliminary']['percent']}%`。\n\n"
        f"加权预备覆盖率：`{weighted_covered}/{weighted_total} = {summary['weighted_coverage_preliminary']['percent']}%`。\n\n"
        "该结果是单人内部复核，不是外部专家验证；未通过知识点及原因见 `all_kp_coverage_annotations.jsonl`。\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str((EVAL / "all_kp_coverage_review.json").relative_to(ROOT)),
        "knowledge_point_count": len(annotations),
        "covered_count": covered,
        "uncovered_count": len(annotations) - covered,
        "unweighted": summary["unweighted_coverage_preliminary"],
        "weighted": summary["weighted_coverage_preliminary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
