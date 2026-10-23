#!/usr/bin/env python3
"""Build and validate per-task atomic-requirement ledgers."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


GOAL_ID_PATTERN = re.compile(r"^[A-Z0-9-]+$")
TASK_ID_PATTERN = re.compile(r"^F\d+-T\d+$")
PLACEHOLDERS = {"", "todo", "tbd", "pending", "待补", "待实现", "未填写"}


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha_value(value: Any) -> str:
    return sha_bytes(encoded(value))


def relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def file_record(root: Path, path: Path) -> dict[str, Any]:
    exists = path.is_file()
    data = path.read_bytes() if exists else b""
    return {
        "path": relative(root, path),
        "exists": exists,
        "bytes": len(data) if exists else None,
        "sha256": sha_bytes(data) if exists else None,
    }


def load_task_payload(root: Path, context_root: Path, active: dict[str, Any], task: str) -> dict[str, Any]:
    version_dir = (root / str(active.get("version_path", ""))).resolve()
    versions_root = (context_root / "versions").resolve()
    if not version_dir.is_dir() or versions_root not in version_dir.parents:
        raise RuntimeError("Invalid active immutable version path")
    descriptor_path = version_dir / "task_packets" / f"{task}.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    chunks: list[bytes] = []
    for expected_index, item in enumerate(descriptor.get("chunks", []), start=1):
        if item.get("index") != expected_index:
            raise RuntimeError(f"Atomic ledger task packet has invalid chunk order: {task}")
        path = (root / str(item.get("path", ""))).resolve()
        if version_dir not in path.parents or not path.is_file():
            raise RuntimeError(f"Atomic ledger task packet chunk is invalid: {path}")
        data = path.read_bytes()
        if len(data) != item.get("bytes") or sha_bytes(data) != item.get("sha256"):
            raise RuntimeError(f"Atomic ledger task packet chunk failed verification: {path}")
        chunks.append(data)
    combined = b"".join(chunks)
    if (
        len(combined) != descriptor.get("total_bytes")
        or sha_bytes(combined) != descriptor.get("payload_sha256")
    ):
        raise RuntimeError(f"Atomic ledger task packet payload failed verification: {task}")
    payload = json.loads(combined.decode("utf-8"))
    if payload.get("packet_id") != task:
        raise RuntimeError(f"Atomic ledger task packet ID mismatch: {task}")
    return payload


def expected_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for role, key in (
        ("primary", "primary_atomic_requirements"),
        ("related", "related_atomic_requirements"),
    ):
        for atom in payload.get(key, []):
            atom_id = str(atom.get("atomic_requirement_id", ""))
            if not atom_id:
                raise RuntimeError(f"Task packet contains an atom without ID in {key}")
            entries.append(
                {
                    "role": role,
                    "atomic_requirement_id": atom_id,
                    "requirement_sha256": sha_value(atom),
                    "source": atom,
                }
            )
    ids = [item["atomic_requirement_id"] for item in entries]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Task packet contains duplicate primary/related atomic requirement IDs")
    return entries


def requirements_fingerprint(entries: list[dict[str, Any]]) -> str:
    return sha_value(
        [
            {
                "role": item["role"],
                "atomic_requirement_id": item["atomic_requirement_id"],
                "requirement_sha256": item["requirement_sha256"],
            }
            for item in entries
        ]
    )


def ledger_path(context_root: Path, goal_id: str, task: str, fingerprint: str) -> Path:
    if not GOAL_ID_PATTERN.fullmatch(goal_id) or not TASK_ID_PATTERN.fullmatch(task):
        raise RuntimeError("Unsafe goal or task ID for atomic requirement ledger")
    return context_root / "atomic_requirement_ledgers" / goal_id / f"{task}_{fingerprint}.json"


def new_ledger(
    *, goal_id: str, task: str, entries: list[dict[str, Any]], created_at: str
) -> dict[str, Any]:
    fingerprint = requirements_fingerprint(entries)
    return {
        "schema_version": "context-recovery.atomic-ledger.v1",
        "goal_id": goal_id,
        "task": task,
        "requirements_fingerprint": fingerprint,
        "created_at": created_at,
        "instructions": {
            "before_context_verified": (
                "Review every source atom with its Word text and images, then replace every blank "
                "understanding field and set confirmed=true. No atom may be summarized away."
            ),
            "during_execution": (
                "Keep this ledger as the active checklist. Map every edit or test batch to current "
                "atom IDs or an explicit protection contract, and update the affected entries "
                "immediately after that batch. Resolve conflicts against the authoritative sources."
            ),
            "before_evidence_verified": (
                "For every primary atom record implementation and verification evidence plus the "
                "user-visible result. For every related atom record compatibility evidence and rationale. "
                "Reconcile every entry individually; group-level claims cannot substitute."
            ),
            "after_resume": (
                "Continue from incomplete or insufficient ledger entries for this task only. Do not "
                "infer scope from the task title or copy understanding or evidence from another task."
            ),
        },
        "entries": [
            {
                **item,
                "understanding": {
                    "confirmed": False,
                    "product_meaning": "",
                    "behavior_boundaries": [],
                    "implementation_scope": [],
                    "verification_plan": [],
                },
                "realization": {
                    "status": "PENDING",
                    "implementation_evidence": [],
                    "verification_evidence": [],
                    "user_visible_result": "",
                    "compatibility_or_defer_rationale": "",
                },
            }
            for item in entries
        ],
    }


def meaningful(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in PLACEHOLDERS
    if isinstance(value, list):
        return bool(value) and all(meaningful(item) for item in value)
    return False


def validate_ledger_identity(
    ledger: dict[str, Any], *, goal_id: str, task: str, entries: list[dict[str, Any]]
) -> list[str]:
    failures: list[str] = []
    if ledger.get("schema_version") != "context-recovery.atomic-ledger.v1":
        failures.append("schema_version")
    if ledger.get("goal_id") != goal_id:
        failures.append("goal_id")
    if ledger.get("task") != task:
        failures.append("task")
    fingerprint = requirements_fingerprint(entries)
    if ledger.get("requirements_fingerprint") != fingerprint:
        failures.append("requirements_fingerprint")
    actual_entries = ledger.get("entries", [])
    actual_ids = [item.get("atomic_requirement_id") for item in actual_entries]
    expected_ids = [item["atomic_requirement_id"] for item in entries]
    if actual_ids != expected_ids or len(actual_ids) != len(set(actual_ids)):
        failures.append("exact_atomic_requirement_order_and_ids")
        return failures
    for expected, actual in zip(entries, actual_entries):
        atom_id = expected["atomic_requirement_id"]
        if actual.get("role") != expected["role"]:
            failures.append(f"{atom_id}:role")
        if actual.get("requirement_sha256") != expected["requirement_sha256"]:
            failures.append(f"{atom_id}:requirement_sha256")
        if sha_value(actual.get("source")) != expected["requirement_sha256"]:
            failures.append(f"{atom_id}:source")
    return failures


def validate_understanding(ledger: dict[str, Any], entries: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for expected, actual in zip(entries, ledger.get("entries", [])):
        atom_id = expected["atomic_requirement_id"]
        understanding = actual.get("understanding", {})
        if understanding.get("confirmed") is not True:
            failures.append(f"{atom_id}:understanding.confirmed")
        for field in (
            "product_meaning",
            "behavior_boundaries",
            "implementation_scope",
            "verification_plan",
        ):
            if not meaningful(understanding.get(field)):
                failures.append(f"{atom_id}:understanding.{field}")
    return failures


def validate_realization(ledger: dict[str, Any], entries: list[dict[str, Any]]) -> list[str]:
    failures = validate_understanding(ledger, entries)
    for expected, actual in zip(entries, ledger.get("entries", [])):
        atom_id = expected["atomic_requirement_id"]
        realization = actual.get("realization", {})
        if expected["role"] == "primary":
            if realization.get("status") != "IMPLEMENTED_AND_VERIFIED":
                failures.append(f"{atom_id}:realization.status")
            for field in (
                "implementation_evidence",
                "verification_evidence",
                "user_visible_result",
            ):
                if not meaningful(realization.get(field)):
                    failures.append(f"{atom_id}:realization.{field}")
        else:
            if realization.get("status") not in {
                "COMPATIBILITY_VERIFIED",
                "COORDINATION_VERIFIED",
                "NOT_APPLICABLE_VERIFIED",
            }:
                failures.append(f"{atom_id}:realization.status")
            for field in ("verification_evidence", "compatibility_or_defer_rationale"):
                if not meaningful(realization.get(field)):
                    failures.append(f"{atom_id}:realization.{field}")
    return failures
