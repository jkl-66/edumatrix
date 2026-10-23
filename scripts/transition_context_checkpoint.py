#!/usr/bin/env python3
"""Advance the live context-recovery checkpoint through its guarded state machine."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from scripts.context_recovery_atomic_gate import (
        expected_entries,
        file_record as atomic_file_record,
        ledger_path,
        load_task_payload,
        requirements_fingerprint,
        validate_ledger_identity,
        validate_realization,
        validate_understanding,
    )
except ModuleNotFoundError:
    from context_recovery_atomic_gate import (
        expected_entries,
        file_record as atomic_file_record,
        ledger_path,
        load_task_payload,
        requirements_fingerprint,
        validate_ledger_identity,
        validate_realization,
        validate_understanding,
    )


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "原系统融合重构执行"
CONTEXT_ROOT = OUTPUT / "evidence" / "context_recovery"
STATES = (
    "NOT_STARTED",
    "CONTEXT_VERIFIED",
    "EDITING",
    "CODE_COMPLETE",
    "TESTED",
    "EVIDENCE_VERIFIED",
    "CLOSED",
)
EVIDENCE_FIELDS = {
    "impact_file_hashes",
    "read_evidence",
    "modified_files",
    "test_commands",
    "e2e",
    "screenshots",
    "rollback_checks",
    "known_limitations",
    "next_step",
}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(encoded(value))
    temp.replace(path)


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def record(path: Path) -> dict[str, Any]:
    exists = path.is_file()
    data = path.read_bytes() if exists else b""
    return {
        "path": relative(path),
        "exists": exists,
        "bytes": len(data) if exists else None,
        "sha256": sha_bytes(data) if exists else None,
    }


def resolve_live_checkpoint(active: dict[str, Any]) -> Path:
    item = active.get("current_checkpoint")
    if not isinstance(item, dict):
        raise RuntimeError("active_manifest has no current_checkpoint record")
    path = (ROOT / str(item.get("path", ""))).resolve()
    context_root = CONTEXT_ROOT.resolve()
    if path != context_root and context_root not in path.parents:
        raise RuntimeError("Live checkpoint path escapes context_recovery")
    if record(path) != item:
        raise RuntimeError("Live checkpoint hash does not match active_manifest")
    return path


def ordered_task_ids(version_dir: Path) -> list[str]:
    task_ids = [path.stem for path in (version_dir / "task_packets").glob("F*-T*.json")]

    def task_order(task_id: str) -> tuple[int, int]:
        match = re.fullmatch(r"F(\d+)-T(\d+)", task_id)
        if match is None:
            raise RuntimeError(f"Invalid task packet id: {task_id}")
        return int(match.group(1)), int(match.group(2))

    return sorted(task_ids, key=task_order)


def validate_atomic_gate(
    active: dict[str, Any],
    checkpoint: dict[str, Any],
    required_level: str,
    read_evidence: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    task = str(checkpoint.get("task", ""))
    goal_id = str(checkpoint.get("goal_id", ""))
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, task)
    entries = expected_entries(payload)
    fingerprint = requirements_fingerprint(entries)
    path = ledger_path(CONTEXT_ROOT, goal_id, task, fingerprint)
    if not path.is_file():
        raise RuntimeError(
            f"Atomic requirement ledger is missing for {task}; run read_context_recovery_task.py first"
        )
    ledger = load_json(path)
    failures = validate_ledger_identity(
        ledger, goal_id=goal_id, task=task, entries=entries
    )
    if required_level == "understanding":
        failures.extend(validate_understanding(ledger, entries))
    elif required_level == "realization":
        failures.extend(validate_realization(ledger, entries))
    else:
        raise ValueError(f"Unknown atomic requirement gate level: {required_level}")
    if failures:
        raise RuntimeError(
            f"Atomic requirement {required_level} gate failed for {task}: "
            + ", ".join(failures)
        )
    if required_level == "understanding":
        receipt_failures: list[str] = []
        receipt_found = False
        receipt_root = (CONTEXT_ROOT / "read_receipts").resolve()
        for item in read_evidence or []:
            candidate = (ROOT / item.split("#", 1)[0]).resolve()
            if candidate.parent != receipt_root or not candidate.is_file():
                continue
            receipt = load_json(candidate)
            if receipt.get("task") != task or receipt.get("active_version") != active.get(
                "active_version"
            ):
                continue
            receipt_found = True
            atomic_requirements = receipt.get("atomic_requirements", {})
            if receipt.get("schema_version") != "context-recovery.read-receipt.v1":
                receipt_failures.append("receipt.schema_version")
            if receipt.get("status") != "MACHINE_VALIDATED":
                receipt_failures.append("receipt.status")
            if atomic_requirements.get("fingerprint") != fingerprint:
                receipt_failures.append("receipt.atomic_requirements.fingerprint")
            if atomic_requirements.get("all_ids") != [
                item["atomic_requirement_id"] for item in entries
            ]:
                receipt_failures.append("receipt.atomic_requirements.all_ids")
            if receipt.get("atomic_requirement_ledger", {}).get("path") != relative(path):
                receipt_failures.append("receipt.atomic_requirement_ledger.path")
            checks = receipt.get("checks", [])
            if receipt.get("check_count") != len(checks) or not checks or not all(
                check.get("passed") is True for check in checks
            ):
                receipt_failures.append("receipt.checks")
            break
        if not receipt_found:
            receipt_failures.append("current_task_machine_validated_read_receipt")
        if receipt_failures:
            raise RuntimeError(
                f"Atomic requirement read receipt gate failed for {task}: "
                + ", ".join(receipt_failures)
            )
    return atomic_file_record(ROOT, path), {
        "primary": sum(item["role"] == "primary" for item in entries),
        "related": sum(item["role"] == "related" for item in entries),
        "total": len(entries),
    }


def transition(
    *,
    expected_task: str,
    to_state: str | None = None,
    advance_to_task: str | None = None,
    refresh_next_step: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if sum((bool(to_state), bool(advance_to_task), refresh_next_step)) != 1:
        raise ValueError(
            "Specify exactly one of to_state, advance_to_task or refresh_next_step"
        )
    lock_path = CONTEXT_ROOT / ".checkpoint-transition.lock"
    lock_fd: int | None = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(lock_fd, f"pid={os.getpid()} at={now()}\n".encode("ascii"))

        active_path = CONTEXT_ROOT / "active_manifest.json"
        active = load_json(active_path)
        if active.get("status") != "VERIFIED":
            raise RuntimeError("No VERIFIED context-recovery version is active")
        checkpoint_path = resolve_live_checkpoint(active)
        checkpoint = load_json(checkpoint_path)
        if checkpoint.get("protocol_version") != active.get("active_version"):
            raise RuntimeError("Checkpoint protocol does not match active version")
        if checkpoint.get("task") != expected_task:
            raise RuntimeError(
                f"Expected task {expected_task}, found {checkpoint.get('task')}"
            )
        current_state = str(checkpoint.get("state"))
        if current_state not in STATES:
            raise RuntimeError(f"Invalid current state: {current_state}")

        previous = {
            "phase": checkpoint.get("phase"),
            "task": checkpoint.get("task"),
            "state": current_state,
            "sha256": record(checkpoint_path)["sha256"],
        }
        if advance_to_task:
            if current_state != "CLOSED":
                raise RuntimeError("A task can advance only after CLOSED")
            version_dir = (ROOT / str(active.get("version_path", ""))).resolve()
            task_ids = ordered_task_ids(version_dir)
            try:
                index = task_ids.index(expected_task)
            except ValueError as exc:
                raise RuntimeError(f"Current task is absent from active packets: {expected_task}") from exc
            expected_next = task_ids[index + 1] if index + 1 < len(task_ids) else None
            if advance_to_task != expected_next:
                raise RuntimeError(
                    f"Next task must be {expected_next}, not {advance_to_task}"
                )
            checkpoint["task"] = advance_to_task
            checkpoint["phase"] = advance_to_task.split("-", 1)[0]
            checkpoint["state"] = "NOT_STARTED"
            descriptor = version_dir / "task_packets" / f"{advance_to_task}.json"
            checkpoint["task_packet_descriptor"] = record(descriptor)
            checkpoint["impact_file_hashes"] = {}
            checkpoint["read_evidence"] = []
            checkpoint["modified_files"] = []
            checkpoint["test_commands"] = []
            checkpoint["e2e"] = []
            checkpoint["screenshots"] = []
            checkpoint["rollback_checks"] = []
            checkpoint["known_limitations"] = []
            checkpoint.pop("atomic_requirement_ledger", None)
            checkpoint.pop("atomic_requirement_counts", None)
            checkpoint["next_step"] = (
                f"Load and verify {advance_to_task}, then transition to CONTEXT_VERIFIED."
            )
        elif not refresh_next_step:
            assert to_state is not None
            if to_state not in STATES:
                raise ValueError(f"Unknown checkpoint state: {to_state}")
            expected_index = STATES.index(current_state) + 1
            expected_state = STATES[expected_index] if expected_index < len(STATES) else None
            if to_state != expected_state:
                raise RuntimeError(
                    f"Illegal transition {current_state} -> {to_state}; expected {expected_state}"
                )
            if to_state == "CONTEXT_VERIFIED":
                ledger_record, atom_counts = validate_atomic_gate(
                    active,
                    checkpoint,
                    "understanding",
                    list((metadata or {}).get("read_evidence", checkpoint.get("read_evidence", []))),
                )
                checkpoint["atomic_requirement_ledger"] = ledger_record
                checkpoint["atomic_requirement_counts"] = atom_counts
            elif to_state == "EVIDENCE_VERIFIED":
                ledger_record, atom_counts = validate_atomic_gate(
                    active, checkpoint, "realization"
                )
                checkpoint["atomic_requirement_ledger"] = ledger_record
                checkpoint["atomic_requirement_counts"] = atom_counts
            checkpoint["state"] = to_state

        if refresh_next_step and STATES.index(current_state) >= STATES.index("CONTEXT_VERIFIED"):
            required_level = (
                "realization"
                if current_state in {"EVIDENCE_VERIFIED", "CLOSED"}
                else "understanding"
            )
            ledger_record, atom_counts = validate_atomic_gate(
                active,
                checkpoint,
                required_level,
                list(checkpoint.get("read_evidence", [])),
            )
            checkpoint["atomic_requirement_ledger"] = ledger_record
            checkpoint["atomic_requirement_counts"] = atom_counts

        metadata = metadata or {}
        unknown = sorted(set(metadata) - EVIDENCE_FIELDS)
        if unknown:
            raise ValueError(f"Unsupported metadata fields: {unknown}")
        if refresh_next_step and not str(metadata.get("next_step", "")).strip():
            raise ValueError("refresh_next_step requires metadata.next_step")
        applied_metadata = (
            {"next_step": metadata["next_step"]} if refresh_next_step else metadata
        )
        for key, value in applied_metadata.items():
            checkpoint[key] = value
        if not str(checkpoint.get("next_step", "")).strip():
            raise ValueError("Every checkpoint transition requires a non-empty next_step")

        checkpoint["gate"] = f"TASK_{checkpoint['state']}"
        checkpoint["updated_at"] = now()
        checkpoint["snapshot_sequence"] = int(checkpoint.get("snapshot_sequence", 0)) + 1
        checkpoint["last_transition"] = {
            "from": previous,
            "to": {
                "phase": checkpoint.get("phase"),
                "task": checkpoint.get("task"),
                "state": checkpoint.get("state"),
            },
            "at": checkpoint["updated_at"],
        }

        snapshot_path = (
            CONTEXT_ROOT
            / "checkpoint_snapshots"
            / (
                f"{checkpoint['snapshot_sequence']:04d}_{checkpoint['task']}_"
                f"{checkpoint['state']}_{stamp()}.json"
            )
        )
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with snapshot_path.open("xb") as handle:
            handle.write(encoded(checkpoint))

        atomic_write(checkpoint_path, checkpoint)
        active["current_checkpoint"] = record(checkpoint_path)
        active["checkpoint_updated_at"] = checkpoint["updated_at"]
        # active_manifest is deliberately the final write in the transaction.
        atomic_write(active_path, active)
        return {
            "status": "TRANSITIONED",
            "active_version": active.get("active_version"),
            "phase": checkpoint.get("phase"),
            "task": checkpoint.get("task"),
            "state": checkpoint.get("state"),
            "snapshot": relative(snapshot_path),
            "checkpoint": record(checkpoint_path),
        }
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        if lock_path.exists():
            lock_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-task", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--to-state", choices=STATES)
    group.add_argument("--advance-to-task")
    group.add_argument("--refresh-next-step", action="store_true")
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args()
    metadata = load_json(args.metadata) if args.metadata else {}
    result = transition(
        expected_task=args.expected_task,
        to_state=args.to_state,
        advance_to_task=args.advance_to_task,
        refresh_next_step=args.refresh_next_step,
        metadata=metadata,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
