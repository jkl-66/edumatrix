"""Consistent, checksummed local backup and non-destructive restore helpers."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
import shutil
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.database import DB_PATH


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(
    destination: str | Path,
    *,
    database_path: str | Path = DB_PATH,
    file_roots: Iterable[str | Path] = (),
) -> Path:
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    db_source = Path(database_path).resolve()
    snapshot = destination.parent / f".{destination.name}.snapshot-{uuid.uuid4().hex}.sqlite3"
    try:
        with closing(sqlite3.connect(str(db_source))) as source, closing(sqlite3.connect(str(snapshot))) as target:
            source.backup(target)
            target.commit()

        entries: list[dict[str, object]] = []
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "database/database.sqlite3")
            entries.append({"path": "database/database.sqlite3", "sha256": _sha256(snapshot), "bytes": snapshot.stat().st_size})
            for root_value in file_roots:
                root = Path(root_value).resolve()
                if not root.exists():
                    continue
                files = [root] if root.is_file() else sorted(path for path in root.rglob("*") if path.is_file())
                for path in files:
                    root_label = root.parent.name if root.is_file() else root.name
                    relative = path.name if root.is_file() else path.relative_to(root).as_posix()
                    archive_path = f"files/{root_label}/{relative}"
                    archive.write(path, archive_path)
                    entries.append({"path": archive_path, "sha256": _sha256(path), "bytes": path.stat().st_size})
            manifest = {
                "format": "edumatrix-backup-v1",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "entries": entries,
            }
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    finally:
        if snapshot.exists():
            snapshot.unlink()
    return destination


def restore_backup(archive_path: str | Path, target_dir: str | Path) -> dict:
    archive_path = Path(archive_path).resolve()
    target_dir = Path(target_dir).resolve()
    if target_dir.exists() and any(target_dir.iterdir()):
        raise FileExistsError("restore target must be empty")
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != "edumatrix-backup-v1":
            raise ValueError("unsupported backup format")
        entries = manifest.get("entries")
        if not isinstance(entries, list) or not entries:
            raise ValueError("backup manifest has no entries")
        names = set(archive.namelist())
        seen: set[str] = set()
        staging = (target_dir.parent / f".{target_dir.name}.staging-{uuid.uuid4().hex}").resolve()
        staging.mkdir(parents=False, exist_ok=False)
        try:
            for item in entries:
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    raise ValueError("invalid backup manifest entry")
                item_path = item["path"]
                if item_path in seen or item_path not in names:
                    raise ValueError("duplicate or missing backup entry")
                seen.add(item_path)
                target = (staging / item_path).resolve()
                if staging not in target.parents:
                    raise ValueError("unsafe backup path")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item_path) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                if _sha256(target) != item.get("sha256") or target.stat().st_size != item.get("bytes"):
                    raise ValueError(f"backup checksum mismatch: {item_path}")
            database = staging / "database" / "database.sqlite3"
            if not database.is_file():
                raise ValueError("backup database entry is missing")
            with closing(sqlite3.connect(str(database))) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("restored database failed integrity check")
            target_dir.mkdir(parents=True, exist_ok=True)
            for child in staging.iterdir():
                shutil.move(str(child), str(target_dir / child.name))
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return manifest
