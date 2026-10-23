#!/usr/bin/env python3
"""Validate and materialize the active phase/task context without changing checkpoint state."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from scripts.context_recovery_atomic_gate import (
        expected_entries,
        file_record as atomic_file_record,
        ledger_path,
        new_ledger,
        requirements_fingerprint,
        validate_ledger_identity,
    )
except ModuleNotFoundError:
    from context_recovery_atomic_gate import (
        expected_entries,
        file_record as atomic_file_record,
        ledger_path,
        new_ledger,
        requirements_fingerprint,
        validate_ledger_identity,
    )


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "原系统融合重构执行"
CONTEXT_ROOT = OUTPUT / "evidence" / "context_recovery"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(
        (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
    )
    temp.replace(path)


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def verify_record(record: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    path = ROOT / str(record.get("path", ""))
    exists = path.is_file()
    data = path.read_bytes() if exists else b""
    actual = {
        "path": relative(path),
        "exists": exists,
        "bytes": len(data) if exists else None,
        "sha256": sha_bytes(data) if exists else None,
    }
    return actual == record, actual


def mapped_current_task_files(
    ledger: dict[str, Any], entries: list[dict[str, Any]]
) -> set[str]:
    """Return task files whose changes are already mapped in the active ledger."""
    allowed_atoms = {str(item["atomic_requirement_id"]) for item in entries}
    mapped: set[str] = set()
    accepted_statuses = {"IMPLEMENTED_PENDING_FINAL_VERIFICATION", "VERIFIED"}
    root = ROOT.resolve()
    for batch in ledger.get("execution_batches", []):
        if batch.get("status") not in accepted_statuses:
            continue
        atoms = batch.get("atoms")
        files = batch.get("files")
        if (
            not isinstance(atoms, list)
            or not atoms
            or not set(map(str, atoms)).issubset(allowed_atoms)
            or not isinstance(files, list)
            or not files
        ):
            raise RuntimeError("Current-task ledger contains an invalid execution batch")
        for item in files:
            path = (ROOT / str(item)).resolve()
            if path != root and root not in path.parents:
                raise RuntimeError("Current-task ledger maps a file outside the repository")
            mapped.add(relative(path))
    return mapped


def reconstruct_packet(
    descriptor_path: Path, allowed_root: Path
) -> tuple[bytes, dict[str, Any], list[dict[str, Any]]]:
    descriptor = load_json(descriptor_path)
    checks: list[dict[str, Any]] = []
    chunks: list[bytes] = []
    expected_indices = list(range(1, int(descriptor.get("chunk_count", 0)) + 1))
    actual_indices = [int(item.get("index", -1)) for item in descriptor.get("chunks", [])]
    checks.append(
        {
            "id": "chunk-indices",
            "passed": actual_indices == expected_indices,
            "actual": actual_indices,
        }
    )
    allowed = allowed_root.resolve()
    for item in descriptor.get("chunks", []):
        path = (ROOT / str(item.get("path", ""))).resolve()
        inside = path == allowed or allowed in path.parents
        exists = path.is_file()
        data = path.read_bytes() if exists and inside else b""
        passed = (
            inside
            and exists
            and len(data) == item.get("bytes")
            and sha_bytes(data) == item.get("sha256")
        )
        checks.append(
            {
                "id": f"chunk-{item.get('index')}",
                "passed": passed,
                "path": relative(path),
                "inside_version": inside,
                "bytes": len(data) if exists and inside else None,
            }
        )
        chunks.append(data)

    combined = b"".join(chunks)
    eof_record = descriptor.get("eof_record", {})
    eof_path = (ROOT / str(eof_record.get("path", ""))).resolve()
    eof_inside = eof_path == allowed or allowed in eof_path.parents
    eof_exists = eof_path.is_file()
    eof_data = eof_path.read_bytes() if eof_exists and eof_inside else b""
    eof = json.loads(eof_data.decode("utf-8")) if eof_data else {}
    eof_passed = (
        eof_inside
        and eof_exists
        and sha_bytes(eof_data) == eof_record.get("sha256")
        and eof.get("eof") is True
        and eof.get("chunk_count") == descriptor.get("chunk_count")
        and eof.get("total_bytes") == descriptor.get("total_bytes")
        and eof.get("payload_sha256") == descriptor.get("payload_sha256")
    )
    checks.append(
        {
            "id": "eof",
            "passed": eof_passed,
            "path": relative(eof_path),
        }
    )
    checks.append(
        {
            "id": "combined-payload",
            "passed": (
                len(combined) == descriptor.get("total_bytes")
                and sha_bytes(combined) == descriptor.get("payload_sha256")
                and len(descriptor.get("chunks", [])) == descriptor.get("chunk_count")
                and sum(bool(item.get("eof")) for item in descriptor.get("chunks", [])) == 1
                and bool(descriptor.get("chunks", []))
                and descriptor["chunks"][-1].get("eof") is True
            ),
            "bytes": len(combined),
            "sha256": sha_bytes(combined),
        }
    )
    if not all(item["passed"] for item in checks):
        raise RuntimeError(
            "Packet validation failed: "
            + json.dumps(
                [item for item in checks if not item["passed"]], ensure_ascii=False
            )
        )
    payload = json.loads(combined.decode("utf-8"))
    return combined, payload, checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", help="Task id; defaults to current checkpoint task")
    args = parser.parse_args()

    active_path = CONTEXT_ROOT / "active_manifest.json"
    active = load_json(active_path)
    if active.get("status") != "VERIFIED":
        raise SystemExit("No VERIFIED context-recovery version is active")
    version_dir = (ROOT / str(active.get("version_path", ""))).resolve()
    versions_root = (CONTEXT_ROOT / "versions").resolve()
    if not version_dir.is_dir() or versions_root not in version_dir.parents:
        raise SystemExit(f"Invalid active immutable version path: {version_dir}")
    if version_dir.name != active.get("active_version"):
        raise SystemExit("Active version name and version path disagree")

    checks: list[dict[str, Any]] = []
    for key in (
        "authority_manifest",
        "current_checkpoint",
        "verification_report",
        "protocol_activation",
        "phase_index",
    ):
        passed, actual = verify_record(active[key])
        checks.append({"id": f"active-record:{key}", "passed": passed, "actual": actual})

    authority = load_json(version_dir / "authority_manifest.json")
    activation = load_json(version_dir / "protocol_activation.json")
    verification = load_json(version_dir / "verification_report.json")
    checkpoint_record = active.get("current_checkpoint", {})
    checkpoint_path = (ROOT / str(checkpoint_record.get("path", ""))).resolve()
    context_root = CONTEXT_ROOT.resolve()
    if checkpoint_path != context_root and context_root not in checkpoint_path.parents:
        raise SystemExit(f"Invalid live checkpoint path: {checkpoint_path}")
    checkpoint = load_json(checkpoint_path)
    checks.extend(
        [
            {
                "id": "authority-status",
                "passed": authority.get("status") == "VERIFIED",
                "actual": authority.get("status"),
            },
            {
                "id": "activation-status",
                "passed": activation.get("status") == "VERIFIED",
                "actual": activation.get("status"),
            },
            {
                "id": "verification-status",
                "passed": verification.get("status") == "PASS"
                and verification.get("failure_count") == 0,
                "actual": {
                    "status": verification.get("status"),
                    "failure_count": verification.get("failure_count"),
                },
            },
            {
                "id": "live-checkpoint-protocol",
                "passed": checkpoint.get("protocol_version") == active.get("active_version"),
                "actual": checkpoint.get("protocol_version"),
            },
        ]
    )

    for name, record in authority.get("source_files", {}).items():
        passed, actual = verify_record(record)
        checks.append(
            {"id": f"pinned-source:{name}", "passed": passed, "actual": actual}
        )

    task_id = args.task or checkpoint.get("task")
    if task_id != checkpoint.get("task"):
        raise SystemExit(
            f"Requested task {task_id} is not current checkpoint task {checkpoint.get('task')}"
        )
    phase_id = str(checkpoint.get("phase", ""))
    phase_descriptor = version_dir / "phase_packets" / f"{phase_id}.json"
    task_descriptor = version_dir / "task_packets" / f"{task_id}.json"
    phase_bytes, phase_payload, phase_checks = reconstruct_packet(
        phase_descriptor, version_dir
    )
    task_bytes, task_payload, task_checks = reconstruct_packet(task_descriptor, version_dir)
    checks.extend(
        {**item, "id": f"phase:{item['id']}"} for item in phase_checks
    )
    checks.extend({**item, "id": f"task:{item['id']}"} for item in task_checks)
    checks.extend(
        [
            {
                "id": "phase-id",
                "passed": phase_payload.get("packet_id") == phase_id,
                "actual": phase_payload.get("packet_id"),
            },
            {
                "id": "task-id",
                "passed": task_payload.get("packet_id") == task_id,
                "actual": task_payload.get("packet_id"),
            },
            {
                "id": "protocol-version",
                "passed": phase_payload.get("protocol_version")
                == active.get("active_version")
                == task_payload.get("protocol_version"),
                "actual": {
                    "phase": phase_payload.get("protocol_version"),
                    "active": active.get("active_version"),
                    "task": task_payload.get("protocol_version"),
                },
            },
        ]
    )

    contract = task_payload.get("task_atomic_execution_contract", {})
    primary_ids = [
        item.get("atomic_requirement_id")
        for item in task_payload.get("primary_atomic_requirements", [])
    ]
    related_ids = [
        item.get("atomic_requirement_id")
        for item in task_payload.get("related_atomic_requirements", [])
    ]
    required_contract_flags = (
        "scope_is_task_local",
        "must_reload_on_entry_resume_compaction_handoff_and_task_switch",
        "previous_task_understanding_or_evidence_cannot_substitute",
        "must_read_every_primary_and_related_atom",
        "must_correlate_word_paragraphs_and_full_size_images",
        "editing_forbidden_before_context_verified",
        "context_verified_requires_per_atom_understanding",
        "ledger_must_remain_active_during_planning_editing_testing_and_review",
        "every_edit_batch_requires_atom_or_protection_mapping",
        "ledger_must_be_updated_after_each_edit_or_test_batch",
        "conflicts_require_authoritative_source_recheck",
        "evidence_verified_requires_per_atom_realization",
        "closure_requires_per_atom_reconciliation_without_group_substitution",
        "resume_must_continue_from_incomplete_ledger_entries",
        "task_close_requires_realization_gate",
        "next_task_forbidden_before_current_task_closed",
    )
    checks.extend(
        [
            {
                "id": "task-atomic-contract-identity",
                "passed": contract.get("schema_version")
                == "context-recovery.task-atomic-contract.v1"
                and contract.get("task_id") == task_id,
                "actual": {
                    "schema_version": contract.get("schema_version"),
                    "task_id": contract.get("task_id"),
                },
            },
            {
                "id": "task-atomic-contract-flags",
                "passed": all(contract.get(field) is True for field in required_contract_flags),
                "actual": {field: contract.get(field) for field in required_contract_flags},
            },
            {
                "id": "task-atomic-contract-ids",
                "passed": contract.get("primary_atomic_requirement_ids") == primary_ids
                and contract.get("related_atomic_requirement_ids") == related_ids,
                "actual": {
                    "primary": contract.get("primary_atomic_requirement_ids"),
                    "related": contract.get("related_atomic_requirement_ids"),
                },
            },
        ]
    )

    atoms = expected_entries(task_payload)
    fingerprint = requirements_fingerprint(atoms)
    atomic_ledger_path = ledger_path(
        CONTEXT_ROOT, str(checkpoint.get("goal_id", "")), task_id, fingerprint
    )
    atomic_ledger: dict[str, Any] | None = None
    mapped_files: set[str] = set()
    if atomic_ledger_path.is_file():
        atomic_ledger = load_json(atomic_ledger_path)
        identity_failures = validate_ledger_identity(
            atomic_ledger,
            goal_id=str(checkpoint.get("goal_id", "")),
            task=task_id,
            entries=atoms,
        )
        if identity_failures:
            raise RuntimeError(
                "Existing atomic requirement ledger does not match the active task packet: "
                + ", ".join(identity_failures)
            )
        if checkpoint.get("state") != "NOT_STARTED":
            mapped_files = mapped_current_task_files(atomic_ledger, atoms)

    impact_records: dict[str, dict[str, Any]] = {}
    closure = task_payload.get("code_impact_closure", {})
    for group in (
        "direct_existing_files",
        "dependency_files",
        "caller_files",
        "test_files",
        "all_closure_files",
    ):
        for record in closure.get(group, []):
            impact_records[str(record.get("path"))] = record
    for path, record in sorted(impact_records.items()):
        baseline_match, actual = verify_record(record)
        mapped_change = (
            not baseline_match and path in mapped_files and actual.get("exists") is True
        )
        checks.append(
            {
                "id": f"impact-file:{path}",
                "passed": baseline_match or mapped_change,
                "baseline_match": baseline_match,
                "mapped_current_task_change": mapped_change,
                "actual": actual,
            }
        )
    for path in sorted(mapped_files - set(impact_records)):
        actual_path = ROOT / path
        checks.append(
            {
                "id": f"mapped-task-file:{path}",
                "passed": actual_path.is_file(),
                "actual": {"path": path, "exists": actual_path.is_file()},
            }
        )

    image_records: dict[str, dict[str, Any]] = {}
    for item in task_payload.get("images", []):
        record = item.get("file_record", {}).get("copied_file", {})
        image_records[str(record.get("path"))] = record
    for path, record in sorted(image_records.items()):
        passed, actual = verify_record(record)
        checks.append(
            {"id": f"image:{path}", "passed": passed, "actual": actual}
        )

    failures = [item for item in checks if not item["passed"]]
    if failures:
        print(
            json.dumps(
                {"status": "FAIL", "task": task_id, "failures": failures},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    materialized = CONTEXT_ROOT / "loaded_context" / active["active_version"] / task_id
    materialized.mkdir(parents=True, exist_ok=True)
    phase_payload_path = materialized / f"{phase_id}.payload.json"
    task_payload_path = materialized / f"{task_id}.payload.json"
    phase_payload_path.write_bytes(phase_bytes)
    task_payload_path.write_bytes(task_bytes)
    if atomic_ledger is None:
        atomic_ledger = new_ledger(
            goal_id=str(checkpoint.get("goal_id", "")),
            task=task_id,
            entries=atoms,
            created_at=now(),
        )
        dump_json(atomic_ledger_path, atomic_ledger)
    receipt_path = CONTEXT_ROOT / "read_receipts" / f"{stamp}_{task_id}.json"
    receipt = {
        "schema_version": "context-recovery.read-receipt.v1",
        "status": "MACHINE_VALIDATED",
        "created_at": now(),
        "active_version": active["active_version"],
        "phase": phase_id,
        "task": task_id,
        "checkpoint_state": checkpoint.get("state"),
        "phase_payload": {
            "path": relative(phase_payload_path),
            "bytes": len(phase_bytes),
            "sha256": sha_bytes(phase_bytes),
        },
        "task_payload": {
            "path": relative(task_payload_path),
            "bytes": len(task_bytes),
            "sha256": sha_bytes(task_bytes),
            "chunk_count": load_json(task_descriptor).get("chunk_count"),
        },
        "pinned_sources_verified": len(authority.get("source_files", {})),
        "impact_files_verified": len(impact_records),
        "images_verified": len(image_records),
        "atomic_requirement_ledger": atomic_file_record(ROOT, atomic_ledger_path),
        "atomic_requirements": {
            "fingerprint": fingerprint,
            "primary_count": sum(item["role"] == "primary" for item in atoms),
            "related_count": sum(item["role"] == "related" for item in atoms),
            "all_ids": [item["atomic_requirement_id"] for item in atoms],
        },
        "task_atomic_execution_contract": contract,
        "check_count": len(checks),
        "checks": checks,
        "next_step": (
            "The model must treat this task's atomic contract as non-transferable, read the "
            "materialized phase/task payload plus direct 09/10/13, Word, images and code closure "
            "evidence, then complete every understanding entry in this task's ledger before "
            "checkpoint may become CONTEXT_VERIFIED."
        ),
    }
    dump_json(receipt_path, receipt)
    print(
        json.dumps(
            {
                "status": "MACHINE_VALIDATED",
                "active_version": active["active_version"],
                "phase": phase_id,
                "task": task_id,
                "checks": len(checks),
                "impact_files": len(impact_records),
                "images": len(image_records),
                "primary_atoms": sum(item["role"] == "primary" for item in atoms),
                "related_atoms": sum(item["role"] == "related" for item in atoms),
                "atomic_requirement_ledger": relative(atomic_ledger_path),
                "phase_payload": relative(phase_payload_path),
                "task_payload": relative(task_payload_path),
                "receipt": relative(receipt_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
