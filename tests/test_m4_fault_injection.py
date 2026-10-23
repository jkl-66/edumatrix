from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.m4_fault_injection import orchestrate, verify_package


def test_hard_process_crash_resumes_at_exact_committed_boundary(tmp_path: Path):
    output = tmp_path / "fault-evidence"
    report = orchestrate(output)

    assert report["crash"]["actual_exit_code"] == 73
    assert report["crash"]["committed_before_crash"] == 13
    assert report["recovery"]["before"] == 13
    assert report["recovery"]["attempted"] == 47
    assert report["recovery"]["after"] == 60
    assert report["verification"]["run_status"] == "awaiting_annotation"
    assert all(report["verification"]["checks"].values())
    assert verify_package(output)["verification"]["result_count"] == 60


def test_fault_evidence_rejects_unexpected_or_tampered_file(tmp_path: Path):
    output = tmp_path / "fault-evidence"
    orchestrate(output)
    (output / "debug.log").write_text("internal\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected"):
        verify_package(output)
    (output / "debug.log").unlink()

    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    report["network_used"] = True
    (output / "report.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        verify_package(output)
