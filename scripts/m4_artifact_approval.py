"""Build artifact approval tasks and revise M4 coverage tasks from resolved approvals."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.m4_offline_evaluation import (  # noqa: E402
    OfflineAnnotationRecord,
    OfflineAnnotationTask,
    canonical_json,
    make_task,
    resolve_annotations,
)


def read_jsonl(path: Path, model):
    return tuple(model.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def write_jsonl(path: Path, rows) -> None:
    path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8")


def prepare(args) -> int:
    metric_tasks = read_jsonl(args.metric_tasks, OfflineAnnotationTask)
    approvals = []
    seen = set()
    for task in metric_tasks:
        if task.task_type == "adaptation":
            item = task.payload
            ref = item["artifact_version_id"]
            if ref not in seen:
                approvals.append(make_task(
                    task_id=f"approval:{ref}", task_type="artifact_approval", subject_id=ref,
                    payload={
                        "artifact_ref": ref, "kind": f"m3_{item['artifact_type']}",
                        "content_sha256": item["content_sha256"], "content": item["content"],
                        "source_ref_ids": item["source_ref_ids"],
                        "upstream_status": "M3_REAL_E2E_PASSED",
                    },
                    rubric={
                        "rule": "approve only if semantics are coherent, sources/original authorship are traceable, and the exact frozen version is reviewable",
                        "labels": {
                            "semantic_quality_passed": "boolean", "source_traceability_passed": "boolean",
                            "version_integrity_passed": "boolean", "approved": "boolean conjunction",
                        },
                    },
                ))
                seen.add(ref)
        if task.task_type == "coverage":
            for item in task.payload["candidate_teaching_artifacts"]:
                ref = item["artifact_ref"]
                if ref in seen:
                    continue
                approvals.append(make_task(
                    task_id=f"approval:{ref}", task_type="artifact_approval", subject_id=ref,
                    payload={
                        "artifact_ref": ref, "kind": item["kind"], "content_sha256": item["sha256"],
                        "content": item["content"], "source_or_authorship": "EduMatrix project-original frozen M0 course",
                        "upstream_status": item["status"],
                    },
                    rubric={
                        "rule": "perform the missing independent approval; FROZEN_FOR_M0_REVIEW is not itself approval",
                        "labels": {
                            "semantic_quality_passed": "boolean", "source_traceability_passed": "boolean",
                            "version_integrity_passed": "boolean", "approved": "boolean conjunction",
                        },
                    },
                ))
                seen.add(ref)
    if len(approvals) != 17:
        raise ValueError(f"expected 17 unique approval subjects, found {len(approvals)}")
    write_jsonl(args.output, [task.model_dump(mode="json") for task in sorted(approvals, key=lambda task: task.task_id)])
    print(json.dumps({"ok": True, "approval_task_count": len(approvals), "output": str(args.output)}, ensure_ascii=False))
    return 0


def revise(args) -> int:
    metric_tasks = read_jsonl(args.metric_tasks, OfflineAnnotationTask)
    approval_tasks = read_jsonl(args.approval_tasks, OfflineAnnotationTask)
    first = read_jsonl(args.first, OfflineAnnotationRecord)
    second = read_jsonl(args.second, OfflineAnnotationRecord)
    adjudications = read_jsonl(args.adjudications, OfflineAnnotationRecord) if args.adjudications.is_file() else ()
    resolved = resolve_annotations(approval_tasks, first, second, adjudications)
    approval_map = {record.task_id.removeprefix("approval:"): record for record in resolved}
    revised = []
    for task in metric_tasks:
        if task.task_type != "coverage":
            revised.append(task)
            continue
        payload = json.loads(json.dumps(task.payload, ensure_ascii=False))
        refs = [item["artifact_ref"] for item in payload["candidate_teaching_artifacts"]]
        refs.extend(item["artifact_version_id"] for item in payload["approved_m3_resources"])
        payload["artifact_approval_evidence"] = [
            {
                "artifact_ref": ref,
                "approval_task_id": f"approval:{ref}",
                "approved": approval_map[ref].labels["approved"],
                "approval_labels": approval_map[ref].labels,
                "approval_rationale": approval_map[ref].rationale,
                "approval_task_hash": approval_map[ref].task_hash,
            }
            for ref in dict.fromkeys(refs)
        ]
        revised.append(make_task(
            task_id=task.task_id, task_type="coverage", subject_id=task.subject_id,
            payload=payload,
            rubric={
                **task.rubric,
                "artifact_approval_rule": "artifact_approved may be true only when at least one substantial artifact has approved=true in artifact_approval_evidence",
            },
        ))
    write_jsonl(args.output, [task.model_dump(mode="json") for task in revised])
    print(json.dumps({"ok": True, "metric_task_count": len(revised), "coverage_revised": 32, "output": str(args.output)}, ensure_ascii=False))
    return 0


def merge(args) -> int:
    tasks = read_jsonl(args.tasks, OfflineAnnotationTask)
    base = read_jsonl(args.base, OfflineAnnotationRecord)
    coverage = read_jsonl(args.coverage, OfflineAnnotationRecord)
    task_map = {task.task_id: task for task in tasks}
    records = [record for record in base if record.task_type != "coverage"] + list(coverage)
    if len(records) != len(tasks) or {record.task_id for record in records} != set(task_map):
        raise ValueError("merged annotations do not cover revised tasks exactly")
    revised_records = []
    for record in records:
        task = task_map[record.task_id]
        revised_records.append(record.model_copy(update={"task_hash": task.task_hash}))
    write_jsonl(args.output, [record.model_dump(mode="json") for record in revised_records])
    print(json.dumps({"ok": True, "count": len(revised_records), "output": str(args.output)}, ensure_ascii=False))
    return 0


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser("prepare")
    cmd.add_argument("--metric-tasks", type=Path, required=True)
    cmd.add_argument("--output", type=Path, required=True)
    cmd = commands.add_parser("revise")
    cmd.add_argument("--metric-tasks", type=Path, required=True)
    cmd.add_argument("--approval-tasks", type=Path, required=True)
    cmd.add_argument("--first", type=Path, required=True)
    cmd.add_argument("--second", type=Path, required=True)
    cmd.add_argument("--adjudications", type=Path, required=True)
    cmd.add_argument("--output", type=Path, required=True)
    cmd = commands.add_parser("merge")
    cmd.add_argument("--tasks", type=Path, required=True)
    cmd.add_argument("--base", type=Path, required=True)
    cmd.add_argument("--coverage", type=Path, required=True)
    cmd.add_argument("--output", type=Path, required=True)
    return root


def main():
    args = parser().parse_args()
    return {"prepare": prepare, "revise": revise, "merge": merge}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
