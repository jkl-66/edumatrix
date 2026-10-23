from __future__ import annotations

import json
import sqlite3
import zipfile
import shutil
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

from app.backup import create_backup, restore_backup
from app.m8_preflight import deployment_preflight


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _workspace_temp():
    # tempfile applies an owner-only ACL that the managed Windows test process
    # cannot reopen. A child of this pre-created workspace directory inherits
    # the repository ACL and remains representative of Chinese/non-system paths.
    root = ROOT / "tests" / "m8_runtime_fixture" / uuid.uuid4().hex
    root.mkdir(parents=True)
    try:
        yield str(root)
    finally:
        shutil.rmtree(root)


def _source_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('round-trip')")
        connection.commit()


def test_backup_round_trip_and_restored_database_is_readable():
    with _workspace_temp() as value:
        root = Path(value)
        database = root / "source.db"
        _source_database(database)
        files = root / "uploads"
        files.mkdir()
        (files / "教材.txt").write_text("verified content", encoding="utf-8")
        archive = create_backup(root / "backup.zip", database_path=database, file_roots=[files])
        restored = root / "restored"
        restore_backup(archive, restored)
        with closing(sqlite3.connect(restored / "database" / "database.sqlite3")) as connection:
            assert connection.execute("SELECT value FROM sample").fetchone()[0] == "round-trip"
        assert (restored / "files" / "uploads" / "教材.txt").read_text(encoding="utf-8") == "verified content"


def test_restore_rejects_checksum_change_without_partial_target():
    with _workspace_temp() as value:
        root = Path(value)
        database = root / "source.db"
        _source_database(database)
        original = create_backup(root / "backup.zip", database_path=database)
        modified = root / "modified.zip"
        with zipfile.ZipFile(original) as source, zipfile.ZipFile(modified, "w") as output:
            for name in source.namelist():
                content = source.read(name)
                if name == "database/database.sqlite3":
                    content += b"tampered"
                output.writestr(name, content)
        target = root / "restored"
        with pytest.raises(ValueError, match="checksum mismatch"):
            restore_backup(modified, target)
        assert not target.exists()


def test_restore_rejects_nonempty_target_and_unsafe_manifest_path():
    with _workspace_temp() as value:
        root = Path(value)
        database = root / "source.db"
        _source_database(database)
        archive = create_backup(root / "backup.zip", database_path=database)
        occupied = root / "occupied"
        occupied.mkdir()
        (occupied / "keep.txt").write_text("keep", encoding="utf-8")
        with pytest.raises(FileExistsError):
            restore_backup(archive, occupied)
        unsafe = root / "unsafe.zip"
        with zipfile.ZipFile(archive) as source:
            manifest = json.loads(source.read("manifest.json"))
            manifest["entries"][0]["path"] = "../escape.db"
            with zipfile.ZipFile(unsafe, "w") as output:
                output.writestr("manifest.json", json.dumps(manifest))
                output.writestr("../escape.db", b"x")
        with pytest.raises(ValueError, match="unsafe backup path"):
            restore_backup(unsafe, root / "unsafe-target")


def test_deployment_preflight_is_truthful_and_contains_no_secret_values():
    report = deployment_preflight()
    assert report["schema_version"] == "m8.deployment-preflight.v1"
    assert report["status"] in {"ready", "not_ready"}
    assert report["generation_allowed"] == (not report["blockers"])
    assert report["checks"]["data_initialization"]["published_courses"] >= 0
    assert report["checks"]["retrieval"]["backend"] in {"canonical_hash", "faiss"}
    assert report["checks"]["generation_runtime"]["mode"] in {
        "real_model", "deterministic_demo", "unavailable",
    }
    encoded = json.dumps(report)
    assert "llm_endpoint" not in encoded
    assert "api_key" not in encoded
    assert report["configuration"]["secret_values_included"] is False
