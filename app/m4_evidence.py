"""Fail-closed, privacy-reduced evidence packages for M4 evaluation runs."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from app.database import DBEvaluationCase, DBEvaluationReport, DBEvaluationResult, DBEvaluationRun
from app.m4_evaluation import FrozenBenchmark, M4EvaluationError


_SENSITIVE_KEYS = {
    "access_token", "api_key", "authorization", "cookie", "email", "password",
    "phone", "profile_id", "refresh_token", "secret", "student_id", "user_id",
}
_EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?![\w.-])")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _redact(value: Any, key: str = "") -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = _EMAIL.sub("[REDACTED_EMAIL]", value)
        value = _PHONE.sub("[REDACTED_PHONE]", value)
        return _BEARER.sub("Bearer [REDACTED]", value)
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    content = "".join(_canonical(row) + "\n" for row in rows)
    path.write_text(content, encoding="utf-8")


def export_evidence_package(
    session: Any,
    *,
    run: DBEvaluationRun,
    benchmark: FrozenBenchmark,
    output_dir: Path,
) -> dict[str, Any]:
    """Export a new immutable-by-convention evidence directory and its manifest."""
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise M4EvaluationError("evidence_output_exists", "evidence output directory already exists")
    if run.data_version != benchmark.case_version:
        raise M4EvaluationError("evidence_dataset_mismatch", "run and frozen benchmark versions differ")

    joined = (
        session.query(DBEvaluationCase, DBEvaluationResult)
        .join(DBEvaluationResult, DBEvaluationResult.evaluation_case_id == DBEvaluationCase.id)
        .filter(DBEvaluationResult.evaluation_run_id == run.id)
        .order_by(DBEvaluationCase.case_code)
        .all()
    )
    output_dir.mkdir(parents=True)
    run_payload = {
        "run_id": run.id,
        "trace_id": run.trace_id,
        "status": run.status,
        "code_version": run.code_version,
        "data_version": run.data_version,
        "model_version": run.model_version,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
    results = []
    failures = []
    for case, result in joined:
        output = _redact(dict(result.output_data or {}))
        row = {
            "case_id": case.case_code,
            "result_id": result.id,
            "output": output,
            "scores": _redact(dict(result.scores or {})),
            "passed": bool(result.passed),
            "failure_reason": _redact(result.failure_reason or ""),
        }
        results.append(row)
        status = str(output.get("status", "failed"))
        if status in {"failed", "timeout"} or result.failure_reason:
            failures.append({
                "case_id": case.case_code,
                "result_id": result.id,
                "status": status,
                "error_code": output.get("error_code", ""),
                "failure_reason": row["failure_reason"],
            })

    report = (
        session.query(DBEvaluationReport)
        .filter_by(evaluation_run_id=run.id)
        .order_by(DBEvaluationReport.report_version.desc())
        .first()
    )
    _write_json(output_dir / "run.json", run_payload)
    _write_jsonl(output_dir / "results.jsonl", results)
    _write_jsonl(output_dir / "failures.jsonl", failures)
    artifact_names = ["run.json", "results.jsonl", "failures.jsonl"]
    if report is not None:
        _write_json(output_dir / "report.json", {
            "report_id": report.id,
            "metric_version": report.metric_version,
            "report_version": report.report_version,
            "status": report.status,
            "approval_ref": report.approval_ref,
            "content_hash": report.content_hash,
            "report_data": _redact(report.report_data),
        })
        artifact_names.append("report.json")

    artifacts = []
    for name in artifact_names:
        path = output_dir / name
        artifacts.append({"path": name, "sha256": _sha256(path), "size_bytes": path.stat().st_size})
    manifest = {
        "schema_version": "m4.evidence-manifest.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run": {
            "id": run.id,
            "trace_id": run.trace_id,
            "code_version": run.code_version,
            "data_version": run.data_version,
            "model_version": run.model_version,
        },
        "benchmark": {
            "case_version": benchmark.case_version,
            "case_file_sha256": benchmark.case_file_sha256,
            "knowledge_point_version": benchmark.knowledge_point_version,
            "knowledge_point_file_sha256": benchmark.knowledge_point_file_sha256,
            "metric_version": benchmark.metric_version,
        },
        "report_id": report.id if report is not None else None,
        "result_count": len(results),
        "failure_count": len(failures),
        "artifacts": artifacts,
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def verify_evidence_package(output_dir: Path) -> dict[str, Any]:
    """Verify the manifest and every referenced artifact; missing files fail closed."""
    output_dir = output_dir.resolve()
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        raise M4EvaluationError("evidence_manifest_missing", "evidence manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M4EvaluationError("evidence_manifest_invalid", "evidence manifest is unreadable") from exc
    if manifest.get("schema_version") != "m4.evidence-manifest.v1":
        raise M4EvaluationError("evidence_manifest_invalid", "unsupported evidence manifest schema")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise M4EvaluationError("evidence_manifest_invalid", "manifest contains no artifacts")
    artifact_paths: dict[str, Path] = {}
    for item in artifacts:
        relative = Path(str(item.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise M4EvaluationError("evidence_path_invalid", "artifact path must remain inside the package")
        relative_name = relative.as_posix()
        if relative_name in artifact_paths:
            raise M4EvaluationError("evidence_manifest_invalid", "manifest contains duplicate artifact paths")
        path = output_dir / relative
        if not path.is_file():
            raise M4EvaluationError("evidence_file_missing", f"evidence artifact is missing: {relative}")
        if path.stat().st_size != item.get("size_bytes") or _sha256(path) != item.get("sha256"):
            raise M4EvaluationError("evidence_hash_mismatch", f"evidence artifact changed: {relative}")
        artifact_paths[relative_name] = path

    required = {"run.json", "results.jsonl", "failures.jsonl"}
    if not required.issubset(artifact_paths):
        raise M4EvaluationError("evidence_file_missing", "manifest is missing required run/result/failure artifacts")
    try:
        run_payload = json.loads(artifact_paths["run.json"].read_text(encoding="utf-8"))
        results = [json.loads(line) for line in artifact_paths["results.jsonl"].read_text(encoding="utf-8").splitlines() if line]
        failures = [json.loads(line) for line in artifact_paths["failures.jsonl"].read_text(encoding="utf-8").splitlines() if line]
    except (OSError, json.JSONDecodeError) as exc:
        raise M4EvaluationError("evidence_artifact_invalid", "evidence artifact is unreadable") from exc
    run_link = manifest.get("run", {})
    for key in ("id", "trace_id", "code_version", "data_version", "model_version"):
        payload_key = "run_id" if key == "id" else key
        if run_payload.get(payload_key) != run_link.get(key):
            raise M4EvaluationError("evidence_linkage_mismatch", f"run linkage differs for {key}")
    if len(results) != manifest.get("result_count") or len(failures) != manifest.get("failure_count"):
        raise M4EvaluationError("evidence_count_mismatch", "manifest row counts differ from evidence artifacts")
    report_id = manifest.get("report_id")
    if report_id is not None:
        report_path = artifact_paths.get("report.json")
        if report_path is None:
            raise M4EvaluationError("evidence_file_missing", "linked report artifact is missing")
        try:
            report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise M4EvaluationError("evidence_artifact_invalid", "report artifact is unreadable") from exc
        if report_payload.get("report_id") != report_id:
            raise M4EvaluationError("evidence_linkage_mismatch", "report linkage differs from manifest")
    return manifest
