from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def candidate_animation_dirs() -> list[Path]:
    """Return animation dataset locations in precedence order."""
    raw_candidates: list[Path] = []
    for env_name in ("EDUMATRIX_ANIMATIONS_DIR", "ANIMATIONS_DIR"):
        env_value = os.getenv(env_name)
        if env_value:
            raw_candidates.append(Path(env_value))

    raw_candidates.extend(
        [
            ROOT / "data" / "animations",
            ROOT.parent / "animations",
            Path.cwd() / "data" / "animations",
            Path.cwd().parent / "animations",
        ]
    )

    seen: set[str] = set()
    candidates: list[Path] = []
    for path in raw_candidates:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser()
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(resolved)
    return candidates


def find_animation_dir() -> Path | None:
    for path in candidate_animation_dirs():
        if not path.exists() or not path.is_dir():
            continue
        has_metadata = (path / "animation_summary.json").exists() or (path / "animations_by_knowledge.json").exists()
        has_concept_dirs = any(child.is_dir() for child in path.iterdir())
        if has_metadata or has_concept_dirs:
            return path
    return None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _media_type_for_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    return "file"


def _local_files(folder: Path) -> list[dict[str, Any]]:
    if not folder.exists() or not folder.is_dir():
        return []
    files: list[dict[str, Any]] = []
    for path in sorted(child for child in folder.iterdir() if child.is_file()):
        media_type = _media_type_for_file(path)
        if media_type == "file":
            continue
        files.append(
            {
                "filename": path.name,
                "size": path.stat().st_size,
                "media_type": media_type,
                "path": f"{folder.name}/{path.name}",
                "url": f"/api/v1/animations/video/{folder.name}/{path.name}" if media_type == "video" else "",
            }
        )
    return files


@lru_cache(maxsize=8)
def load_animation_resource_index(base_dir: str | None = None) -> dict[str, dict[str, Any]]:
    """Load local animation metadata keyed by knowledge point.

    The index is intentionally small and serializable so it can be embedded into
    learning-path API responses without touching the large media files.
    """
    base = Path(base_dir).expanduser().resolve() if base_dir else find_animation_dir()
    if base is None or not base.exists():
        return {}

    summary = _load_json(base / "animation_summary.json") or {}
    by_knowledge = _load_json(base / "animations_by_knowledge.json") or {}
    summary_points = summary.get("knowledge_points", {}) if isinstance(summary, dict) else {}
    if not isinstance(summary_points, dict):
        summary_points = {}
    if not isinstance(by_knowledge, dict):
        by_knowledge = {}

    concepts: set[str] = set(summary_points) | set(by_knowledge)
    concepts.update(child.name for child in base.iterdir() if child.is_dir())

    index: dict[str, dict[str, Any]] = {}
    for concept in sorted(concepts):
        entries = by_knowledge.get(concept, [])
        if not isinstance(entries, list):
            entries = []
        summary_meta = summary_points.get(concept, {})
        if not isinstance(summary_meta, dict):
            summary_meta = {}

        folder = base / concept
        files = _local_files(folder)
        video_files = [item for item in files if item["media_type"] == "video"]
        image_files = [item for item in files if item["media_type"] == "image"]

        platforms = sorted(
            {
                str(entry.get("platform", "")).strip()
                for entry in entries
                if isinstance(entry, dict) and str(entry.get("platform", "")).strip()
            }
            | set(summary_meta.get("platforms") or [])
        )
        media_types = sorted(
            {
                str(entry.get("media_type", "")).strip()
                for entry in entries
                if isinstance(entry, dict) and str(entry.get("media_type", "")).strip()
            }
            | set(summary_meta.get("media_types") or [])
            | ({item["media_type"] for item in files} if files else set())
        )
        titles = [
            str(entry.get("title", "")).strip()
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("title", "")).strip()
        ]
        if not titles:
            titles = [Path(item["filename"]).stem for item in files[:5]]

        categories = sorted(
            {
                str(entry.get("category", "")).strip()
                for entry in entries
                if isinstance(entry, dict) and str(entry.get("category", "")).strip()
            }
        )
        downloaded_from_meta = int(summary_meta.get("downloaded") or 0)
        count_from_meta = int(summary_meta.get("count") or 0)

        index[concept] = {
            "concept": concept,
            "base_dir": str(base),
            "category": categories[0] if categories else "",
            "categories": categories,
            "count": max(count_from_meta, len(entries), len(files)),
            "downloaded": max(downloaded_from_meta, len(video_files)),
            "local_available_count": len(files),
            "video_count": len(video_files),
            "image_count": len(image_files),
            "platforms": platforms,
            "media_types": media_types,
            "titles": titles[:5],
            "preview_title": titles[0] if titles else "",
            "local_files": files[:8],
            "has_local_video": bool(video_files),
        }
    return index


def clear_animation_resource_cache() -> None:
    load_animation_resource_index.cache_clear()
