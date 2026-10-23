from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import build_context_recovery_packets as builder
from scripts import context_recovery_atomic_gate as atomic_gate
from scripts import read_context_recovery_task as reader
from scripts import transition_context_checkpoint as transitioner
from scripts import verify_context_recovery_packets as verifier


def test_each_task_packet_atomic_contract_is_task_local_and_non_transferable() -> None:
    primary = [{"atomic_requirement_id": "G01-R01"}]
    related = [{"atomic_requirement_id": "G02-R01"}]

    built = builder.task_atomic_execution_contract("F5-T01", primary, related)
    independently_derived = verifier.task_atomic_execution_contract(
        "F5-T01", primary, related
    )

    assert built == independently_derived
    assert built["scope_is_task_local"] is True
    assert built["must_reload_on_entry_resume_compaction_handoff_and_task_switch"] is True
    assert built["previous_task_understanding_or_evidence_cannot_substitute"] is True
    assert built["ledger_must_remain_active_during_planning_editing_testing_and_review"] is True
    assert built["every_edit_batch_requires_atom_or_protection_mapping"] is True
    assert built["ledger_must_be_updated_after_each_edit_or_test_batch"] is True
    assert built["conflicts_require_authoritative_source_recheck"] is True
    assert built["closure_requires_per_atom_reconciliation_without_group_substitution"] is True
    assert built["resume_must_continue_from_incomplete_ledger_entries"] is True
    assert built["primary_atomic_requirement_ids"] == ["G01-R01"]
    assert built["related_atomic_requirement_ids"] == ["G02-R01"]
    assert builder.task_atomic_execution_contract("F5-T02", primary, related)[
        "task_id"
    ] == "F5-T02"


def test_chunk_packet_preserves_exact_utf8_bytes_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(verifier, "ROOT", tmp_path)

    payload = {
        "packet_id": "F2-T01",
        "packet_type": "task",
        "protocol_version": "v-test",
        "text": "第一行\n第二行\n" * 40,
    }
    descriptor_path = tmp_path / "packets" / "F2-T01.json"
    descriptor = builder.write_chunked_packet(descriptor_path, payload, chunk_bytes=47)

    assert descriptor["chunk_count"] > 1
    checks = verifier.Checks()
    assert verifier.reconstruct(descriptor_path, checks) == payload
    assert checks.passed
    assert sum(item["bytes"] for item in descriptor["chunks"]) == descriptor["total_bytes"]


def test_chunk_tampering_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(verifier, "ROOT", tmp_path)
    payload = {
        "packet_id": "F2-T02",
        "packet_type": "task",
        "protocol_version": "v-test",
        "text": "evidence\n" * 30,
    }
    descriptor_path = tmp_path / "packets" / "F2-T02.json"
    builder.write_chunked_packet(descriptor_path, payload, chunk_bytes=31)
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    first_chunk = tmp_path / descriptor["chunks"][0]["path"]
    first_chunk.write_bytes(first_chunk.read_bytes() + b"tampered")

    checks = verifier.Checks()
    assert verifier.reconstruct(descriptor_path, checks) is None
    assert not checks.passed


@pytest.mark.parametrize(
    "value",
    ["../escape", "..\\escape", "/absolute", "with space", "", "a" * 97],
)
def test_protocol_version_rejects_path_escape(value: str) -> None:
    with pytest.raises(ValueError):
        builder.validate_version(value)
    with pytest.raises(ValueError):
        verifier.validate_version(value)


def test_safe_replace_tree_keeps_old_snapshot_when_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context_root = tmp_path / "context"
    source = context_root / "versions" / "v-test" / "task_packets"
    destination = context_root / "task_packets"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "new.txt").write_text("new", encoding="utf-8")
    (destination / "old.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(verifier, "CONTEXT_ROOT", context_root)

    def fail_copytree(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated copy failure")

    monkeypatch.setattr(verifier.shutil, "copytree", fail_copytree)
    with pytest.raises(OSError, match="simulated copy failure"):
        verifier.safe_replace_tree(source, destination)

    assert (destination / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (destination / "new.txt").exists()


def test_safe_replace_tree_retries_transient_windows_directory_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context_root = tmp_path / "context"
    source = context_root / "versions" / "v-test" / "phase_packets"
    destination = context_root / "phase_packets"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    (source / "new.txt").write_text("new", encoding="utf-8")
    (destination / "old.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(verifier, "CONTEXT_ROOT", context_root)
    monkeypatch.setattr(verifier.os, "name", "nt")
    monkeypatch.setattr(verifier.time, "sleep", lambda _seconds: None)

    real_replace = Path.replace
    attempts = 0

    def replace_once_locked(path: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("simulated transient directory lock")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace_once_locked)
    verifier.safe_replace_tree(source, destination)

    assert attempts >= 3
    assert (destination / "new.txt").read_text(encoding="utf-8") == "new"
    assert not (destination / "old.txt").exists()


def test_operational_files_are_not_pinned_authority() -> None:
    assert set(builder.PINNED_AUTHORITY_SOURCES).isdisjoint(builder.OPERATIONAL_SOURCES)
    assert set(verifier.PINNED_AUTHORITY_PATHS).isdisjoint(verifier.OPERATIONAL_PATHS)
    assert {"status", "recovery_index", "worklog"} == set(builder.OPERATIONAL_SOURCES)


def test_machine_fact_references_are_content_addressed_without_full_embedding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_paths = {
        "DUAL_CODE_MAP_PATH": tmp_path / "dual.json",
        "SCOPE_MATRIX_PATH": tmp_path / "scope.json",
        "CURRENT_ROUTE_PATH": tmp_path / "current.json",
        "TARGET_ROUTE_PATH": tmp_path / "target.json",
        "TARGET_GLOBAL_PATH": tmp_path / "global.json",
    }
    for name, path in source_paths.items():
        path.write_text('{"large":"document"}', encoding="utf-8")
        monkeypatch.setattr(builder, name, path)
        monkeypatch.setattr(verifier, name, path)
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(verifier, "ROOT", tmp_path)

    task = {"id": "F2-T01", "source_groups": ["G01"]}
    closure = {
        "route_references": ["/courses/:courseId"],
        "vue_routes": [{"path": "/courses/:courseId"}],
        "backend_endpoints": [
            {"method": "GET", "path": "/api/courses/{course_id}"}
        ],
        "orm_models": [{"name": "Course"}],
        "all_closure_files": ["app/models.py", "frontend/src/api/course.js"],
    }
    built = builder.build_machine_fact_references(task, closure)

    assert built == verifier.expected_machine_fact_references(task, closure)
    assert set(built["source_records"]) == {
        "dual_version_code_map",
        "fusion_scope_matrix",
        "current_route_spec",
        "target_route_spec",
        "target_global_contracts",
    }
    assert "large" not in json.dumps(built, ensure_ascii=False)
    assert built["task_projection"]["resolved_orm_models"] == ["Course"]


def test_runtime_reader_reconstructs_exact_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(reader, "ROOT", tmp_path)
    payload = {
        "packet_id": "F2-T01",
        "packet_type": "task",
        "protocol_version": "v-test",
        "text": "上下文\n" * 50,
    }
    descriptor = tmp_path / "versions" / "v-test" / "task_packets" / "F2-T01.json"
    builder.write_chunked_packet(descriptor, payload, chunk_bytes=43)

    raw, loaded, checks = reader.reconstruct_packet(
        descriptor, tmp_path / "versions" / "v-test"
    )

    assert loaded == payload
    assert json.loads(raw.decode("utf-8")) == payload
    assert all(item["passed"] for item in checks)


def test_runtime_reader_accepts_only_current_task_files_mapped_in_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reader, "ROOT", tmp_path)
    entries = _atomic_entries()
    ledger = atomic_gate.new_ledger(
        goal_id="goal",
        task="F7-T01",
        entries=entries,
        created_at="2026-08-15T00:00:00+08:00",
    )
    ledger["execution_batches"] = [
        {
            "id": "frontend",
            "status": "IMPLEMENTED_PENDING_FINAL_VERIFICATION",
            "atoms": ["G01-R01", "G02-R01"],
            "files": ["frontend/src/views/Knowledge.vue"],
        }
    ]

    assert reader.mapped_current_task_files(ledger, entries) == {
        "frontend/src/views/Knowledge.vue"
    }

    ledger["execution_batches"][0]["atoms"] = ["G99-R01"]
    with pytest.raises(RuntimeError, match="invalid execution batch"):
        reader.mapped_current_task_files(ledger, entries)


def test_rebuild_preserves_live_checkpoint_when_authority_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context_root = tmp_path / "context"
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "CONTEXT_ROOT", context_root)
    checkpoint_path = context_root / "current_checkpoint.json"
    checkpoint = {
        "goal_id": "EDUMATRIX-F0-F10-CONTEXT-SAFE-FUSION-REFACTOR",
        "protocol_version": "v-old",
        "phase": "F3",
        "task": "F3-T02",
        "state": "TESTED",
        "next_step": "resume this exact task",
        "source_hashes": {"product": "ABC"},
    }
    checkpoint_path.parent.mkdir(parents=True)
    builder.atomic_write_json(checkpoint_path, checkpoint)
    active = {
        "status": "VERIFIED",
        "active_version": "v-old",
        "current_checkpoint": builder.file_record(checkpoint_path),
    }
    builder.atomic_write_json(context_root / "active_manifest.json", active)

    loaded, unchanged = builder.load_active_checkpoint_for_rebuild(
        {"F3-T02"},
        {"product": {"sha256": "ABC"}},
        "EDUMATRIX-F0-F10-CONTEXT-SAFE-FUSION-REFACTOR",
    )

    assert unchanged is True
    assert loaded is not None
    assert loaded["task"] == "F3-T02"
    assert loaded["state"] == "TESTED"
    assert loaded["next_step"] == "resume this exact task"


def test_verified_checkpoint_preserves_only_an_unchanged_explicit_pause() -> None:
    paused = (
        "PAUSED: F5-F8 is complete. F9-T01 has not been read, planned or "
        "implemented; wait for a new user instruction."
    )
    checkpoint = {
        "phase": "F9",
        "task": "F9-T01",
        "state": "NOT_STARTED",
        "previous_checkpoint": {
            "phase": "F9",
            "task": "F9-T01",
            "state": "NOT_STARTED",
            "next_step": paused,
            "sources_unchanged": True,
        },
    }

    assert verifier.verified_checkpoint_next_step(checkpoint) == paused

    checkpoint["previous_checkpoint"]["sources_unchanged"] = False
    assert verifier.verified_checkpoint_next_step(checkpoint) == (
        "Load and verify the F9-T01 task packet, then transition to "
        "CONTEXT_VERIFIED before editing code."
    )

    checkpoint["previous_checkpoint"]["sources_unchanged"] = True
    checkpoint["previous_checkpoint"]["task"] = "F8-T05"
    assert verifier.verified_checkpoint_next_step(checkpoint).startswith(
        "Load and verify the F9-T01 task packet"
    )


def test_checkpoint_transition_updates_live_record_last_and_rejects_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context_root = tmp_path / "context"
    monkeypatch.setattr(transitioner, "ROOT", tmp_path)
    monkeypatch.setattr(transitioner, "CONTEXT_ROOT", context_root)
    version_dir = context_root / "versions" / "v-test"
    (version_dir / "task_packets").mkdir(parents=True)
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    payload = {
        "packet_id": "F2-T01",
        "packet_type": "task",
        "protocol_version": "v-test",
        "primary_atomic_requirements": [],
        "related_atomic_requirements": [],
    }
    builder.write_chunked_packet(
        version_dir / "task_packets" / "F2-T01.json", payload, chunk_bytes=200
    )
    (version_dir / "task_packets" / "F2-T02.json").write_text("{}", encoding="utf-8")
    checkpoint_path = context_root / "current_checkpoint.json"
    checkpoint = {
        "schema_version": "context-recovery.checkpoint.v1",
        "goal_id": "EDUMATRIX-F0-F10-CONTEXT-SAFE-FUSION-REFACTOR",
        "protocol_version": "v-test",
        "phase": "F2",
        "task": "F2-T01",
        "state": "NOT_STARTED",
        "snapshot_sequence": 1,
        "next_step": "read",
    }
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    transitioner.atomic_write(checkpoint_path, checkpoint)
    active_path = context_root / "active_manifest.json"
    transitioner.atomic_write(
        active_path,
        {
            "status": "VERIFIED",
            "active_version": "v-test",
            "version_path": "context/versions/v-test",
            "current_checkpoint": transitioner.record(checkpoint_path),
        },
    )
    entries = atomic_gate.expected_entries(payload)
    fingerprint = atomic_gate.requirements_fingerprint(entries)
    ledger = atomic_gate.new_ledger(
        goal_id=checkpoint["goal_id"],
        task=checkpoint["task"],
        entries=entries,
        created_at="2026-08-13T00:00:00+08:00",
    )
    transitioner.atomic_write(
        atomic_gate.ledger_path(
            context_root, checkpoint["goal_id"], checkpoint["task"], fingerprint
        ),
        ledger,
    )
    receipt_path = context_root / "read_receipts" / "current_F2-T01.json"
    transitioner.atomic_write(
        receipt_path,
        {
            "schema_version": "context-recovery.read-receipt.v1",
            "status": "MACHINE_VALIDATED",
            "active_version": "v-test",
            "task": "F2-T01",
            "atomic_requirements": {
                "fingerprint": fingerprint,
                "all_ids": [],
            },
            "atomic_requirement_ledger": atomic_gate.file_record(
                tmp_path,
                atomic_gate.ledger_path(
                    context_root, checkpoint["goal_id"], checkpoint["task"], fingerprint
                ),
            ),
            "check_count": 1,
            "checks": [{"id": "packet", "passed": True}],
        },
    )

    with pytest.raises(RuntimeError, match="Illegal transition"):
        transitioner.transition(
            expected_task="F2-T01",
            to_state="EDITING",
            metadata={"next_step": "invalid"},
        )

    result = transitioner.transition(
        expected_task="F2-T01",
        to_state="CONTEXT_VERIFIED",
        metadata={
            "next_step": "start editing",
            "read_evidence": [atomic_gate.relative(tmp_path, receipt_path)],
        },
    )

    active = transitioner.load_json(active_path)
    live = transitioner.load_json(checkpoint_path)
    assert result["state"] == "CONTEXT_VERIFIED"
    assert live["state"] == "CONTEXT_VERIFIED"
    assert live["read_evidence"] == [atomic_gate.relative(tmp_path, receipt_path)]
    assert active["current_checkpoint"] == transitioner.record(checkpoint_path)
    assert len(list((context_root / "checkpoint_snapshots").glob("*.json"))) == 1

    current_ledger_path = atomic_gate.ledger_path(
        context_root, checkpoint["goal_id"], checkpoint["task"], fingerprint
    )
    ledger["execution_batches"] = [{"batch_id": "test-refresh", "status": "VERIFIED"}]
    transitioner.atomic_write(current_ledger_path, ledger)
    assert live["atomic_requirement_ledger"] != atomic_gate.file_record(
        tmp_path, current_ledger_path
    )

    refreshed = transitioner.transition(
        expected_task="F2-T01",
        refresh_next_step=True,
        metadata={
            "next_step": "PAUSED: wait for a new user instruction.",
            "modified_files": ["must-not-be-applied"],
        },
    )
    active = transitioner.load_json(active_path)
    live = transitioner.load_json(checkpoint_path)
    assert refreshed["state"] == "CONTEXT_VERIFIED"
    assert live["phase"] == "F2"
    assert live["task"] == "F2-T01"
    assert live["state"] == "CONTEXT_VERIFIED"
    assert live["next_step"] == "PAUSED: wait for a new user instruction."
    assert live.get("modified_files") != ["must-not-be-applied"]
    assert live["atomic_requirement_ledger"] == atomic_gate.file_record(
        tmp_path, current_ledger_path
    )
    assert active["current_checkpoint"] == transitioner.record(checkpoint_path)
    assert len(list((context_root / "checkpoint_snapshots").glob("*.json"))) == 2


def test_checkpoint_task_order_is_numeric_across_f9_and_f10(tmp_path: Path) -> None:
    task_root = tmp_path / "task_packets"
    task_root.mkdir()
    for task_id in ("F10-T02", "F2-T10", "F9-T04", "F10-T01", "F2-T02"):
        (task_root / f"{task_id}.json").write_text("{}", encoding="utf-8")

    assert transitioner.ordered_task_ids(tmp_path) == [
        "F2-T02",
        "F2-T10",
        "F9-T04",
        "F10-T01",
        "F10-T02",
    ]


def _atomic_entries() -> list[dict[str, object]]:
    return atomic_gate.expected_entries(
        {
            "primary_atomic_requirements": [
                {
                    "atomic_requirement_id": "G01-R01",
                    "full_original_words": "主责原话",
                    "correct_product_interpretation": "主责解释",
                }
            ],
            "related_atomic_requirements": [
                {
                    "atomic_requirement_id": "G02-R01",
                    "full_original_words": "相关原话",
                    "correct_product_interpretation": "相关解释",
                }
            ],
        }
    )


def _complete_understanding(ledger: dict[str, object]) -> None:
    for item in ledger["entries"]:  # type: ignore[index]
        item["understanding"] = {  # type: ignore[index]
            "confirmed": True,
            "product_meaning": "用户看到并能够操作这一项具体行为。",
            "behavior_boundaries": ["普通浏览不写入掌握度。"],
            "implementation_scope": ["frontend/src/views/Target.vue"],
            "verification_plan": ["运行聚焦测试并执行桌面 E2E。"],
        }


def test_atomic_understanding_gate_rejects_missing_and_placeholder_entries() -> None:
    entries = _atomic_entries()
    ledger = atomic_gate.new_ledger(
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T01",
        entries=entries,
        created_at="2026-08-13T00:00:00+08:00",
    )

    failures = atomic_gate.validate_understanding(ledger, entries)
    assert "G01-R01:understanding.confirmed" in failures
    assert "G02-R01:understanding.product_meaning" in failures

    _complete_understanding(ledger)
    ledger["entries"][0]["understanding"]["verification_plan"] = ["TODO"]  # type: ignore[index]
    assert "G01-R01:understanding.verification_plan" in atomic_gate.validate_understanding(
        ledger, entries
    )


def test_atomic_realization_gate_requires_every_primary_and_related_atom() -> None:
    entries = _atomic_entries()
    ledger = atomic_gate.new_ledger(
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T01",
        entries=entries,
        created_at="2026-08-13T00:00:00+08:00",
    )
    _complete_understanding(ledger)

    failures = atomic_gate.validate_realization(ledger, entries)
    assert "G01-R01:realization.implementation_evidence" in failures
    assert "G02-R01:realization.compatibility_or_defer_rationale" in failures

    primary = ledger["entries"][0]["realization"]  # type: ignore[index]
    primary.update(
        {
            "status": "IMPLEMENTED_AND_VERIFIED",
            "implementation_evidence": ["frontend/src/views/Target.vue:42"],
            "verification_evidence": ["tests/test_target.py::test_behavior passed"],
            "user_visible_result": "学生可在资源中心打开该资源。",
        }
    )
    related = ledger["entries"][1]["realization"]  # type: ignore[index]
    related.update(
        {
            "status": "COMPATIBILITY_VERIFIED",
            "verification_evidence": ["tests/test_related.py::test_compatibility passed"],
            "compatibility_or_defer_rationale": "共享协议保持兼容且未越界实现。",
        }
    )
    assert atomic_gate.validate_realization(ledger, entries) == []


def test_atomic_ledger_identity_rejects_missing_duplicate_and_stale_atoms() -> None:
    entries = _atomic_entries()
    goal_id = "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
    ledger = atomic_gate.new_ledger(
        goal_id=goal_id,
        task="F5-T01",
        entries=entries,
        created_at="2026-08-13T00:00:00+08:00",
    )

    ledger["entries"] = [ledger["entries"][0], ledger["entries"][0]]
    assert "exact_atomic_requirement_order_and_ids" in atomic_gate.validate_ledger_identity(
        ledger, goal_id=goal_id, task="F5-T01", entries=entries
    )

    ledger = atomic_gate.new_ledger(
        goal_id=goal_id,
        task="F5-T01",
        entries=entries,
        created_at="2026-08-13T00:00:00+08:00",
    )
    ledger["entries"][0]["source"]["full_original_words"] = "被篡改"  # type: ignore[index]
    assert "G01-R01:source" in atomic_gate.validate_ledger_identity(
        ledger, goal_id=goal_id, task="F5-T01", entries=entries
    )
