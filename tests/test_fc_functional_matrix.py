from __future__ import annotations

import hashlib
import json

from scripts import build_fc_functional_matrix as matrix


def _rows() -> list[dict]:
    source_rows = [
        json.loads(line)
        for line in matrix.SOURCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = []
    for source in source_rows:
        status, work_package, _ = matrix.classify(source)
        initial_status = status
        evidence = ""
        if source["route_id"] in matrix.COMPLETED_FC_ROUTES:
            status = "FUNCTION_COMPLETE"
            work_package = matrix.COMPLETED_FC_ROUTES[source["route_id"]]
            evidence = matrix.completion_evidence(source["route_id"])
        rows.append(
            {
                "route_id": source["route_id"],
                "initial_status": initial_status,
                "status": status,
                "work_package": work_package,
                "evidence": evidence,
            }
        )
    return rows


def test_fc_matrix_has_782_unique_routes_and_no_unexplained_missing():
    rows = _rows()

    assert len(rows) == 782
    assert len({row["route_id"] for row in rows}) == 782
    assert not [row for row in rows if row["status"] == "FUNCTION_MISSING"]


def test_all_fourteen_initial_gaps_are_closed_by_real_fc_evidence():
    closed = [row for row in _rows() if row["initial_status"] == "FUNCTION_MISSING"]

    assert len(closed) == 14
    assert {row["route_id"] for row in closed} == set(matrix.COMPLETED_FC_ROUTES)
    assert all(row["status"] == "FUNCTION_COMPLETE" for row in closed)
    assert all(row["work_package"].startswith(("FC1-", "FC2-")) for row in closed)
    assert all(row["evidence"] for row in closed)


def test_generated_summary_matches_source_and_zero_gap_invariants():
    summary = json.loads(
        (matrix.OUT_DIR / "02_比赛功能完成度摘要.json").read_text(encoding="utf-8")
    )

    assert summary["task_count"] == 782
    assert summary["unique_route_ids"] == 782
    assert summary["functional_status_counts"].get("FUNCTION_MISSING", 0) == 0
    assert summary["unexplained_function_missing"] == []
    assert summary["unmapped_required_tasks"] == []
    assert summary["source_sha256"] == hashlib.sha256(matrix.SOURCE.read_bytes()).hexdigest()
