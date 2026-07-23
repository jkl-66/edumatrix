from __future__ import annotations

import hashlib
import io
import json
from collections import Counter
from pathlib import Path

from document_parser import chunk_document, parse_uploaded_file


ROOT = Path(__file__).resolve().parents[1]
M0 = ROOT / "outputs" / "M0_阶段0基线与架构契约"


def _load_json(name: str):
    return json.loads((M0 / "datasets" / name).read_text(encoding="utf-8"))


def test_m0_course_manifest_hashes_and_markdown_ingestion():
    manifest = _load_json("course_manifest.json")
    assert manifest["course_id"] == "course-rag-engineering-m0"
    assert len(manifest["files"]) == 9

    for item in manifest["files"]:
        path = M0 / item["path"]
        raw = path.read_bytes()
        assert len(raw) == item["bytes"]
        assert hashlib.sha256(raw).hexdigest().upper() == item["sha256"]

        parsed = parse_uploaded_file(io.BytesIO(raw), path.name)
        assert parsed.startswith("# ")
        chunks = chunk_document(parsed, source=str(path))
        assert chunks
        assert all(chunk.content.strip() for chunk in chunks)


def test_m0_baseline_profiles_are_three_distinct_synthetic_cases():
    data = _load_json("baseline_profiles.json")
    profiles = data["profiles"]
    assert data["data_class"] == "P2-SYNTHETIC"
    assert len(profiles) == 3
    assert len({item["profile_id"] for item in profiles}) == 3
    assert {item["expected_resource"]["scaffolding"] for item in profiles} == {
        "high",
        "medium",
        "low",
    }


def test_m0_core_knowledge_point_denominator_is_frozen_and_unique():
    data = _load_json("core_knowledge_points.json")
    points = data["points"]
    assert data["gold_version"] == "kp-rag-0.1"
    assert data["coverage_denominator"] == 32
    assert len(points) == 32
    assert len({item["id"] for item in points}) == 32
    assert all(item["level"] == "core" for item in points)


def test_m0_evaluation_suite_has_sixty_nonduplicate_cases_and_balanced_domains():
    lines = (M0 / "datasets" / "evaluation_cases.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    cases = [json.loads(line) for line in lines if line.strip()]
    assert len(cases) == 60
    assert len({item["case_id"] for item in cases}) == 60

    groups = Counter()
    for item in cases:
        category = item["category"]
        if category in {"quality_review", "decision"}:
            category = "quality_and_decision"
        groups[category] += 1
        assert item["kp"]
        assert item["gold"]
        assert item["failure_branch"]

    assert groups == {
        "knowledge_accuracy": 10,
        "retrieval": 10,
        "generation": 10,
        "profile_adaptation": 10,
        "quality_and_decision": 10,
        "security_recovery": 10,
    }


def test_m0_competitor_matrix_maps_all_412_rows_without_unresolved_reviews():
    lines = (M0 / "datasets" / "competitor_capability_matrix.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    summary = _load_json("competitor_capability_summary.json")

    assert len(rows) == 412
    assert len({item["source_id"] for item in rows}) == 412
    assert Counter(item["product"] for item in rows) == {
        "智教星": 131,
        "学枢": 170,
        "LearnForge": 111,
    }
    assert all(item["primary_capability"] in {f"CAP-{i:02d}" for i in range(1, 21)} for item in rows)
    assert all(item["disposition"] in {"adopt", "adjust", "defer", "not_adopt"} for item in rows)
    assert not [item for item in rows if item["needs_human_review"]]
    assert summary["schema_version"] == "competitor-matrix-m0-0.2"
    assert summary["total"] == summary["unique_source_ids"] == 412
    assert summary["needs_human_review"] == 0
    assert set(summary["by_disposition"]) == {"adopt", "adjust", "defer", "not_adopt"}

    matrix_doc = (M0 / "18_竞品412条能力逐项归属与复核.md").read_text(
        encoding="utf-8"
    )
    documented_rows = sum(
        line.startswith(("| ZJ-", "| XS-", "| LF-F"))
        for line in matrix_doc.splitlines()
    )
    assert documented_rows == 412
