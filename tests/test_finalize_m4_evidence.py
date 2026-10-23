from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from scripts.finalize_m4_evidence import DEFAULT_OUTPUT, verify


@pytest.fixture
def evidence_copy(tmp_path: Path) -> Path:
    target = tmp_path / "evidence"
    shutil.copytree(DEFAULT_OUTPUT, target)
    return target


def _manifest(path: Path) -> dict:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))


def _write_manifest(path: Path, manifest: dict) -> None:
    (path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_verify_accepts_assembled_allowlisted_evidence(evidence_copy: Path):
    manifest = verify(evidence_copy)
    assert manifest["counts"]["raw_results"] == 60
    assert manifest["publication_authorized"] is False
    assert manifest["human_annotators"] == 0


def test_verify_rejects_non_allowlisted_file(evidence_copy: Path):
    (evidence_copy / "internal-debug.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-allowlisted"):
        verify(evidence_copy)


def test_verify_rejects_hash_tampering(evidence_copy: Path):
    path = evidence_copy / "raw" / "results.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="file changed"):
        verify(evidence_copy)


def test_verify_rejects_manifest_line_count_tampering(evidence_copy: Path):
    manifest = _manifest(evidence_copy)
    manifest["files"]["raw/results.jsonl"]["lines"] += 1
    _write_manifest(evidence_copy, manifest)
    with pytest.raises(ValueError, match="line count changed"):
        verify(evidence_copy)


@pytest.mark.parametrize(
    ("field", "value"),
    (("publication_authorized", True), ("human_annotators", 2)),
)
def test_verify_rejects_publication_or_human_boundary_change(
    evidence_copy: Path, field: str, value: object,
):
    manifest = _manifest(evidence_copy)
    manifest[field] = value
    _write_manifest(evidence_copy, manifest)
    with pytest.raises(ValueError, match="publication/human boundary changed"):
        verify(evidence_copy)


def test_verify_rejects_method_or_human_validation_blocker_change(evidence_copy: Path):
    manifest = _manifest(evidence_copy)
    manifest["method"] = "human_double_annotation"
    _write_manifest(evidence_copy, manifest)
    with pytest.raises(ValueError, match="review method changed"):
        verify(evidence_copy)

    manifest["method"] = "two_isolated_ai_passes_with_ai_adjudication"
    manifest["metrics_summary"]["publication_blockers"] = []
    _write_manifest(evidence_copy, manifest)
    with pytest.raises(ValueError, match="human-validation blocker changed"):
        verify(evidence_copy)
