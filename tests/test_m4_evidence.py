from pathlib import Path
import shutil
import uuid

import pytest

from app.m4_evaluation import M4EvaluationError, load_frozen_benchmark
from app.m4_evidence import export_evidence_package, verify_evidence_package
from app.m4_runs import BlindCaseOutput, record_blind_result, start_evaluation_run, sync_frozen_cases
from tests.test_m4_runs import _session


def test_m4_evidence_manifest_verifies_hashes_and_exports_redacted_failures():
    session, version = _session()
    benchmark = load_frozen_benchmark()
    sync_frozen_cases(session, benchmark=benchmark, domain_version_id=version.id)
    run = start_evaluation_run(
        session,
        benchmark=benchmark,
        trace_id="trace-m4-evidence-001",
        code_version="test-tree",
        model_version="test-double",
    )
    record_blind_result(
        session,
        run=run,
        output=BlindCaseOutput(
            case_id="M0-K01",
            status="failed",
            response_text="student@example.com 13800138000 Bearer private-token",
            error_code="provider_failure",
        ),
    )
    output_dir = Path("outputs") / f".test_m4_evidence_{uuid.uuid4().hex}"
    try:
        manifest = export_evidence_package(
            session, run=run, benchmark=benchmark, output_dir=output_dir,
        )
        verified = verify_evidence_package(output_dir)
        failures = (output_dir / "failures.jsonl").read_text(encoding="utf-8")

        assert verified == manifest
        assert manifest["result_count"] == 1
        assert manifest["failure_count"] == 1
        assert "student@example.com" not in failures
        assert "13800138000" not in failures
        assert "private-token" not in failures

        failure_bytes = (output_dir / "failures.jsonl").read_bytes()
        (output_dir / "failures.jsonl").unlink()
        with pytest.raises(M4EvaluationError, match="missing"):
            verify_evidence_package(output_dir)
        (output_dir / "failures.jsonl").write_bytes(failure_bytes)

        with (output_dir / "run.json").open("a", encoding="utf-8") as handle:
            handle.write("tampered")
        with pytest.raises(M4EvaluationError, match="changed"):
            verify_evidence_package(output_dir)
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)
