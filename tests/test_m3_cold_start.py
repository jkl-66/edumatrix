from pathlib import Path
import subprocess

import pytest

from scripts import collect_ml_multimodal_data
from scripts import ingest_to_faiss


def test_faiss_ingestion_uses_repository_relative_paths():
    root = Path(__file__).resolve().parents[1]
    assert ingest_to_faiss.BASE == root
    assert ingest_to_faiss.DATA_DIR == root / "data"
    assert ingest_to_faiss.RAW_DATA_DIR == root / "data" / "raw"
    assert ingest_to_faiss.FAISS_DIR == root / "data" / "faiss_indexes"


def test_faiss_classification_is_limited_to_explicit_cold_start_source(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "lesson.md").write_text("# Verified lesson", encoding="utf-8")
    (raw / "example.py").write_text("print('verified')", encoding="utf-8")
    (raw / "ignored.png").write_bytes(b"not-indexed")

    classified = ingest_to_faiss.classify_files(raw)

    assert classified["courseware"][".md"] == [raw / "lesson.md"]
    assert classified["code"][".py"] == [raw / "example.py"]
    assert all(
        path.suffix != ".png"
        for files_by_type in classified.values()
        for paths in files_by_type.values()
        for path in paths
    )


def test_faiss_default_classification_excludes_uploads_and_generated_indexes(monkeypatch, tmp_path):
    raw = tmp_path / "raw"
    uploads = tmp_path / "uploads"
    indexes = tmp_path / "faiss_indexes"
    raw.mkdir()
    uploads.mkdir()
    indexes.mkdir()
    partial = raw / ".failed.partial"
    partial.mkdir()
    (raw / "source.md").write_text("# Approved cold-start source", encoding="utf-8")
    (partial / "leaked.md").write_text("incomplete download", encoding="utf-8")
    (uploads / "private.md").write_text("private learner upload", encoding="utf-8")
    (indexes / "generated.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ingest_to_faiss, "RAW_DATA_DIR", raw)

    classified = ingest_to_faiss.classify_files()
    indexed_paths = {
        path
        for files_by_type in classified.values()
        for paths in files_by_type.values()
        for path in paths
    }

    assert indexed_paths == {raw / "source.md"}


def test_collector_clones_to_partial_directory_before_atomic_publish(monkeypatch, tmp_path):
    monkeypatch.setattr(collect_ml_multimodal_data, "DATA", tmp_path)
    source = collect_ml_multimodal_data.SOURCES[0]
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        partial = Path(command[-1])
        partial.mkdir(parents=True)
        (partial / "lesson.md").write_text("# Downloaded", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(collect_ml_multimodal_data.subprocess, "run", fake_run)
    monkeypatch.setattr(collect_ml_multimodal_data, "append_event", lambda record: None)

    collect_ml_multimodal_data.clone_source(source, force=False)

    target = tmp_path / "raw" / "github_repos" / source.key
    assert (target / "lesson.md").is_file()
    assert not target.with_name(f".{source.key}.partial").exists()
    assert commands[0][commands[0].index("clone") + 1 : commands[0].index(source.url)] == ["--depth", "1"]


def test_collector_rejects_incomplete_existing_repository(monkeypatch, tmp_path):
    monkeypatch.setattr(collect_ml_multimodal_data, "DATA", tmp_path)
    source = collect_ml_multimodal_data.SOURCES[0]
    target = tmp_path / "raw" / "github_repos" / source.key
    target.mkdir(parents=True)

    monkeypatch.setattr(
        collect_ml_multimodal_data.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 128),
    )

    with pytest.raises(RuntimeError, match="incomplete existing repository"):
        collect_ml_multimodal_data.clone_source(source, force=False)


def test_ingestion_does_not_persist_empty_index(monkeypatch, tmp_path):
    saved_paths = []

    class EmptyIndex:
        def __init__(self, name):
            self.name = name

        def save(self, path):
            saved_paths.append(path)

        def count(self):
            return 0

    monkeypatch.setattr(ingest_to_faiss, "FAISS_DIR", tmp_path)
    monkeypatch.setattr(ingest_to_faiss, "FaissVectorIndex", EmptyIndex)
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text("{}", encoding="utf-8")

    index = ingest_to_faiss.build_category_index(
        "reference",
        "metadata",
        {".jsonl": [metadata]},
    )

    assert index.count() == 0
    assert saved_paths == []
