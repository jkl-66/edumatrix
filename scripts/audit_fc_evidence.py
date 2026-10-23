"""Verify all FC evidence and build the FC6-06A immutable inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "outputs" / "FC_比赛功能完全体" / "evidence"
MATRIX_PATH = ROOT / "outputs" / "FC_比赛功能完全体" / "02_比赛功能完成度矩阵.jsonl"
DEFAULT_OUTPUT = EVIDENCE_ROOT / "FC6-06A"
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webm", ".mp4", ".pdf", ".pptx", ".vtt", ".srt", ".html"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative_file(base: Path, value: str) -> Path:
    candidate = (base / value.replace("/", str(Path("/").anchor or "/"))).resolve()
    # Path replacement above is platform-independent for JSON paths, but on
    # Windows forward slashes are already accepted. Rebuild directly there.
    candidate = (base / Path(value)).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError(f"manifest path escapes its directory: {value}") from exc
    return candidate


def manifest_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries = payload.get("files")
    if not isinstance(entries, list):
        raise ValueError("manifest files must be an array")
    return entries


def verify_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    failures: list[str] = []
    matched = 0
    for entry in manifest_entries(payload):
        relative = entry.get("file", entry.get("path"))
        expected_bytes = entry.get("bytes", entry.get("size"))
        expected_hash = entry.get("sha256")
        if not isinstance(relative, str) or not relative:
            failures.append("entry_without_path")
            continue
        try:
            target = relative_file(path.parent, relative)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        if not target.is_file():
            failures.append(f"missing:{relative}")
            continue
        if expected_bytes is not None and target.stat().st_size != int(expected_bytes):
            failures.append(f"size:{relative}")
            continue
        if not isinstance(expected_hash, str) or sha256(target) != expected_hash.lower():
            failures.append(f"sha256:{relative}")
            continue
        matched += 1
    return {
        "manifest": path.relative_to(EVIDENCE_ROOT).as_posix(),
        "declared": len(payload["files"]),
        "matched": matched,
        "failures": failures,
        "result": "passed" if not failures else "failed",
    }


def verify_database(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file": path.relative_to(EVIDENCE_ROOT).as_posix(),
        "bytes": path.stat().st_size,
    }
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        connection.close()
        result.update(
            integrity_check=integrity,
            foreign_key_violations=len(foreign_keys),
            result="passed" if integrity == "ok" and not foreign_keys else "failed",
        )
    except sqlite3.DatabaseError as exc:
        result.update(integrity_check="error", error=str(exc), result="failed")
    return result


def matrix_evidence() -> dict[str, Any]:
    rows = [json.loads(line) for line in MATRIX_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    references: list[str] = []
    missing: list[str] = []
    for row in rows:
        evidence = row.get("fc_completion_evidence", "")
        if not evidence:
            continue
        for raw in evidence.split(";"):
            value = raw.strip().split("#", 1)[0]
            if not value or not value.startswith("outputs/"):
                continue
            references.append(value)
            if not (ROOT / value).exists():
                missing.append(value)
    statuses = Counter(row.get("functional_status", "UNKNOWN") for row in rows)
    return {
        "rows": len(rows),
        "unique_route_ids": len({row.get("route_id") for row in rows}),
        "status_counts": dict(sorted(statuses.items())),
        "completion_evidence_references": len(references),
        "missing_references": sorted(set(missing)),
        "result": "passed" if len(rows) == 782 and len({row.get('route_id') for row in rows}) == 782 and not missing else "failed",
    }


def run(output: Path) -> dict[str, Any]:
    packages = sorted(path for path in EVIDENCE_ROOT.iterdir() if path.is_dir() and path.resolve() != output.resolve())
    files = sorted(path for package in packages for path in package.rglob("*") if path.is_file())
    manifests = [path for path in files if path.name == "manifest.json"]
    reports = [path for path in files if path.name == "report.json"]
    databases = [path for path in files if path.suffix.lower() == ".db"]
    media = [path for path in files if path.suffix.lower() in MEDIA_SUFFIXES]

    manifest_results = [verify_manifest(path) for path in manifests]
    database_results = [verify_database(path) for path in databases]
    invalid_json: list[str] = []
    for path in [item for item in files if item.suffix.lower() == ".json"]:
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            invalid_json.append(path.relative_to(EVIDENCE_ROOT).as_posix())
    empty_media = [path.relative_to(EVIDENCE_ROOT).as_posix() for path in media if path.stat().st_size == 0]
    packages_without_report = [package.name for package in packages if not any(path.name == "report.json" for path in package.rglob("report.json"))]
    packages_without_manifest = [package.name for package in packages if not any(path.name == "manifest.json" for path in package.rglob("manifest.json"))]
    matrix = matrix_evidence()

    inventory = [
        {
            "file": path.relative_to(EVIDENCE_ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in files
    ]
    failures = {
        "manifest_failures": [item for item in manifest_results if item["result"] != "passed"],
        "database_failures": [item for item in database_results if item["result"] != "passed"],
        "invalid_json": invalid_json,
        "empty_media": empty_media,
        "packages_without_report": packages_without_report,
        "packages_without_manifest": packages_without_manifest,
        "matrix_missing_references": matrix["missing_references"],
    }
    passed = not any(failures.values()) and matrix["result"] == "passed"
    report = {
        "schema_version": "edumatrix.fc6.evidence-audit.v1",
        "result": "passed" if passed else "failed",
        "scope": "All FC evidence packages present at runtime except the selected output package",
        "summary": {
            "packages": len(packages),
            "files": len(files),
            "bytes": sum(path.stat().st_size for path in files),
            "manifests": len(manifests),
            "manifest_entries": sum(item["declared"] for item in manifest_results),
            "manifest_entries_matched": sum(item["matched"] for item in manifest_results),
            "reports": len(reports),
            "databases": len(databases),
            "media_files": len(media),
        },
        "matrix": matrix,
        "failures": failures,
        "manifest_results": manifest_results,
        "database_results": database_results,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "evidence-inventory.json").write_text(
        json.dumps(
            {
                "schema_version": "edumatrix.fc6.evidence-inventory.v1",
                "root": "outputs/FC_比赛功能完全体/evidence",
                "source_package_count": len(packages),
                "file_count": len(inventory),
                "total_bytes": sum(item["bytes"] for item in inventory),
                "files": inventory,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run(args.output.resolve())
    print(json.dumps({"result": report["result"], **report["summary"]}, ensure_ascii=False, indent=2))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
