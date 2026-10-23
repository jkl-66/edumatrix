"""Assemble and verify the allowlisted final M4 evidence package."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "outputs" / "M4_量化评测与可靠性交付" / "evidence" / "annotation-workflow-20260802"
RAW = ROOT / "outputs" / "M4_量化评测与可靠性交付" / "evidence" / "real-model-20260802"
REPORT = ROOT / "outputs" / "M4_量化评测与可靠性交付" / "evidence" / "annotation-evidence-final-v2-20260802"
DEFAULT_OUTPUT = ROOT / "outputs" / "M4_量化评测与可靠性交付" / "evidence" / "M4-final-evidence-v3-20260802"


ALLOWLIST = {
    "raw": (RAW, ("run.json", "results.jsonl", "failures.jsonl", "manifest.json")),
    "annotation": (
        WORKFLOW,
        (
            "README.md", "tasks-v2.jsonl", "annotations-a-v2.jsonl", "annotations-b-v2.jsonl",
            "agreement-v2-pre-adjudication.json", "adjudications-v2.jsonl",
            "approval-tasks.jsonl", "approval-a.jsonl", "approval-b.jsonl",
            "approval-agreement.json", "approval-adjudications-empty.jsonl",
        ),
    ),
    "report": (REPORT, ("agreement.json", "metrics.json", "resolved_annotations.jsonl", "manifest.json")),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def jsonl_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def text_line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def assemble(output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite final evidence: {output}")
    output.mkdir(parents=True)
    files = {}
    for group, (source_dir, names) in ALLOWLIST.items():
        target_dir = output / group
        target_dir.mkdir()
        for name in names:
            source = source_dir / name
            if not source.is_file():
                raise FileNotFoundError(source)
            target = target_dir / name
            shutil.copy2(source, target)
            files[f"{group}/{name}"] = {
                "sha256": sha256(target),
                "bytes": target.stat().st_size,
                "lines": text_line_count(target),
            }

    metrics = json.loads((output / "report" / "metrics.json").read_text(encoding="utf-8"))
    agreement = json.loads((output / "report" / "agreement.json").read_text(encoding="utf-8"))
    approval_agreement = json.loads((output / "annotation" / "approval-agreement.json").read_text(encoding="utf-8"))
    counts = {
        "raw_results": jsonl_count(output / "raw" / "results.jsonl"),
        "metric_tasks": jsonl_count(output / "annotation" / "tasks-v2.jsonl"),
        "annotations_a": jsonl_count(output / "annotation" / "annotations-a-v2.jsonl"),
        "annotations_b": jsonl_count(output / "annotation" / "annotations-b-v2.jsonl"),
        "adjudications": jsonl_count(output / "annotation" / "adjudications-v2.jsonl"),
        "approval_tasks": jsonl_count(output / "annotation" / "approval-tasks.jsonl"),
        "approval_a": jsonl_count(output / "annotation" / "approval-a.jsonl"),
        "approval_b": jsonl_count(output / "annotation" / "approval-b.jsonl"),
        "resolved_annotations": jsonl_count(output / "report" / "resolved_annotations.jsonl"),
    }
    expected = {
        "raw_results": 60, "metric_tasks": 376, "annotations_a": 376, "annotations_b": 376,
        "adjudications": agreement["disagreement_count"], "approval_tasks": 17,
        "approval_a": 17, "approval_b": 17, "resolved_annotations": 376,
    }
    if counts != expected:
        raise ValueError(f"final evidence count mismatch: actual={counts}, expected={expected}")
    if approval_agreement["disagreement_count"] != 0:
        raise ValueError("artifact approvals contain unresolved disagreements")
    if metrics.get("publication_authorized") is not False:
        raise ValueError("AI-reviewed M4 metrics must remain unpublished")
    if "independent_human_validation_missing" not in metrics.get("publication_blockers", []):
        raise ValueError("human validation limitation is missing")

    manifest = {
        "schema_version": "m4.final-evidence-manifest.v3",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "two_isolated_ai_passes_with_ai_adjudication",
        "human_annotators": 0,
        "publication_authorized": False,
        "counts": counts,
        "metrics_summary": {
            "valid_cases": metrics["case_validity"],
            "hallucination_rate": metrics["hallucination_rate"],
            "adaptation_accuracy": metrics["adaptation_accuracy"],
            "core_coverage": metrics["core_coverage"],
            "publication_blockers": metrics["publication_blockers"],
        },
        "agreement_summary": agreement["by_type"],
        "artifact_approval_agreement": approval_agreement["by_type"],
        "files": files,
        "excluded_internal_files": [
            "annotations-a.concurrent-corrupt.jsonl",
            "adjudications-v1-rejected-on-review.jsonl",
            "agreement-pre-adjudication.raw-signature.json",
            "disagreement_tasks.raw-signature.jsonl",
        ],
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify(output: Path) -> dict:
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_files = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*") if path.is_file() and path != manifest_path
    }
    if actual_files != set(manifest["files"]):
        raise ValueError("final evidence contains missing or non-allowlisted files")
    for relative, expected in manifest["files"].items():
        path = output / relative
        if sha256(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            raise ValueError(f"final evidence file changed: {relative}")
        if text_line_count(path) != expected.get("lines"):
            raise ValueError(f"final evidence line count changed: {relative}")
    if manifest["publication_authorized"] is not False or manifest["human_annotators"] != 0:
        raise ValueError("final evidence publication/human boundary changed")
    if manifest.get("method") != "two_isolated_ai_passes_with_ai_adjudication":
        raise ValueError("final evidence review method changed")
    blockers = manifest.get("metrics_summary", {}).get("publication_blockers", [])
    if "independent_human_validation_missing" not in blockers:
        raise ValueError("final evidence human-validation blocker changed")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("assemble", "verify"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = assemble(args.output.resolve()) if args.command == "assemble" else verify(args.output.resolve())
    print(json.dumps({
        "ok": True, "command": args.command, "output": str(args.output.resolve()),
        "counts": manifest["counts"], "publication_authorized": manifest["publication_authorized"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
