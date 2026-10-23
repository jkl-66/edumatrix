from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.database import DBAuditLog, DBVideoAsset, DBVideoAssetVersion, DBUser
from app.identity import new_public_id


ROOT = Path(__file__).resolve().parents[1]
IMPORT_ROOT = Path(os.getenv("EDUMATRIX_VIDEO_IMPORT_DIR", str(ROOT / "data" / "imported_videos"))).resolve()
ALLOWED_VIDEO = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
ALLOWED_SUBTITLE = {".srt": "application/x-subrip", ".vtt": "text/vtt"}
SUBTITLE_MAX_BYTES = 2 * 1024 * 1024


class VideoImportError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise VideoImportError(code, message)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _filename(name: str, allowed: dict[str, str], kind: str) -> tuple[str, str, str]:
    clean = Path(name or "").name.strip()
    if not clean or clean != name or len(clean) > 256 or any(char in clean for char in "\x00\r\n"):
        _fail(f"video_import.{kind}_filename_invalid", f"{kind} 文件名无效")
    suffix = Path(clean).suffix.lower()
    if suffix not in allowed:
        _fail(f"video_import.{kind}_format_unsupported", f"不支持的 {kind} 格式：{suffix or '无扩展名'}")
    return clean, suffix, allowed[suffix]


def _validate_video_magic(raw: bytes, suffix: str) -> None:
    if suffix in {".mp4", ".mov"}:
        valid = b"ftyp" in raw[:64]
    else:
        valid = suffix == ".webm" and raw.startswith(b"\x1a\x45\xdf\xa3")
    if not valid:
        _fail("video_import.media_signature_invalid", "视频文件签名与扩展名不匹配")


def _normalize_subtitle(raw: bytes, suffix: str) -> bytes:
    if len(raw) > SUBTITLE_MAX_BYTES:
        _fail("video_import.subtitle_too_large", f"字幕文件超过 {SUBTITLE_MAX_BYTES} bytes")
    try:
        text = raw.decode("utf-8-sig").replace("\r\n", "\n").strip()
    except UnicodeDecodeError as exc:
        raise VideoImportError("video_import.subtitle_encoding_invalid", "字幕必须使用 UTF-8 编码") from exc
    if not text:
        _fail("video_import.subtitle_empty", "字幕文件不能为空")
    if suffix == ".vtt" and not text.startswith("WEBVTT"):
        _fail("video_import.subtitle_format_invalid", "VTT 字幕必须以 WEBVTT 开头")
    if "-->" not in text:
        _fail("video_import.subtitle_timeline_missing", "字幕缺少时间轴")
    return (text + "\n").encode("utf-8")


def _source_url(value: str) -> str:
    clean = value.strip()
    if not clean:
        return ""
    parsed = urlparse(clean)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        _fail("video_import.source_url_invalid", "来源 URL 必须是无凭据的 HTTPS 地址")
    return clean


def _probe(path: Path) -> dict[str, Any]:
    try:
        import imageio_ffmpeg
        import subprocess

        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stderr or result.stdout
        duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
        video = re.search(r"Video:\s*([^,\s]+).*?(\d{2,5})x(\d{2,5})", output)
        if not duration or not video:
            _fail("video_import.media_probe_failed", "无法读取视频流或时长，文件可能已损坏")
        seconds = int(duration.group(1)) * 3600 + int(duration.group(2)) * 60 + float(duration.group(3))
        return {
            "probe_status": "verified_local_ffmpeg", "duration_ms": max(1, round(seconds * 1000)),
            "video_codec": video.group(1), "width": int(video.group(2)), "height": int(video.group(3)),
            "ffmpeg_version": imageio_ffmpeg.get_ffmpeg_version(),
        }
    except VideoImportError:
        raise
    except Exception as exc:
        return {"probe_status": "unavailable", "duration_ms": 0, "video_codec": "", "width": 0, "height": 0,
                "probe_message": f"{type(exc).__name__}: {str(exc)[:160]}"}


def _owned(db: Any, asset_id: str, actor: DBUser) -> DBVideoAsset:
    row = db.get(DBVideoAsset, asset_id)
    if row is None:
        _fail("video_import.asset_unknown", "视频资产不存在")
    if row.owner_public_id != actor.public_id:
        _fail("video_import.asset_forbidden", "无权访问该视频资产")
    return row


def _version_payload(row: DBVideoAssetVersion) -> dict[str, Any]:
    return {
        "id": row.id, "version_number": row.version_number, "original_filename": row.original_filename,
        "media_format": row.media_format, "media_type": row.media_type, "file_size": row.file_size,
        "source_sha256": row.source_sha256, "duration_ms": row.duration_ms, "width": row.width,
        "height": row.height, "video_codec": row.video_codec, "probe_status": row.probe_status,
        "subtitle_filename": row.subtitle_filename, "subtitle_format": row.subtitle_format,
        "subtitle_sha256": row.subtitle_sha256, "subtitle_version": row.subtitle_version,
        "metadata": row.metadata_json, "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def asset_payload(db: Any, row: DBVideoAsset, *, idempotent: bool = False) -> dict[str, Any]:
    versions = db.query(DBVideoAssetVersion).filter_by(asset_id=row.id).order_by(DBVideoAssetVersion.version_number.desc()).all()
    current = db.get(DBVideoAssetVersion, row.current_version_id) if row.current_version_id else None
    return {
        "schema_version": "fc.video-asset.v1", "id": row.id, "owner_public_id": row.owner_public_id,
        "course_id": row.course_id, "chapter_id": row.chapter_id, "title": row.title,
        "language": row.language, "source_url": row.source_url, "source_author": row.source_author,
        "license_status": row.license_status, "license_text": row.license_text, "status": row.status,
        "lock_version": row.lock_version, "current_version": _version_payload(current) if current else None,
        "versions": [_version_payload(version) for version in versions], "idempotent": idempotent,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def list_assets(db: Any, actor: DBUser) -> dict[str, Any]:
    rows = db.query(DBVideoAsset).filter_by(owner_public_id=actor.public_id, status="active").order_by(DBVideoAsset.updated_at.desc()).all()
    return {"schema_version": "fc.video-asset-list.v1", "items": [asset_payload(db, row) for row in rows]}


def get_asset(db: Any, *, actor: DBUser, asset_id: str) -> dict[str, Any]:
    return asset_payload(db, _owned(db, asset_id, actor))


def import_asset(
    db: Any, *, actor: DBUser, video_raw: bytes, video_filename: str, subtitle_raw: bytes,
    subtitle_filename: str, title: str, language: str, course_id: str | None, chapter_id: str | None,
    source_url: str, source_author: str, license_status: str, license_text: str,
    asset_id: str | None, expected_lock_version: int | None,
) -> dict[str, Any]:
    name, suffix, media_type = _filename(video_filename, ALLOWED_VIDEO, "video")
    _validate_video_magic(video_raw, suffix)
    source_hash = _sha(video_raw)
    subtitle_name = ""
    subtitle_suffix = ""
    subtitle_hash = ""
    normalized_subtitle = b""
    if subtitle_raw or subtitle_filename:
        subtitle_name, subtitle_suffix, _ = _filename(subtitle_filename, ALLOWED_SUBTITLE, "subtitle")
        normalized_subtitle = _normalize_subtitle(subtitle_raw, subtitle_suffix)
        subtitle_hash = _sha(normalized_subtitle)
    clean_source_url = _source_url(source_url)
    metadata = {
        "title": title.strip(), "language": language.strip(), "course_id": course_id or "",
        "chapter_id": chapter_id or "", "source_url": clean_source_url,
        "source_author": source_author.strip(), "license_status": license_status.strip(),
        "license_text": license_text.strip(), "video_filename": name, "subtitle_filename": subtitle_name,
    }
    import_key = hashlib.sha256((actor.public_id + ":" + source_hash + ":" + subtitle_hash + ":" + _canonical(metadata)).encode("utf-8")).hexdigest()
    existing = db.query(DBVideoAssetVersion).filter_by(import_key=import_key).first()
    if existing:
        return asset_payload(db, _owned(db, existing.asset_id, actor), idempotent=True)

    asset = _owned(db, asset_id, actor) if asset_id else None
    if asset:
        if expected_lock_version is None or asset.lock_version != expected_lock_version:
            _fail("video_import.version_conflict", "视频资产已更新，请刷新后重试")
        if (course_id or None) != asset.course_id or (chapter_id or None) != asset.chapter_id:
            _fail("video_import.binding_conflict", "新版本必须保持原课程与章节绑定")
    else:
        asset = DBVideoAsset(
            owner_public_id=actor.public_id, course_id=course_id or None, chapter_id=chapter_id or None,
            title=title.strip(), language=language.strip(), source_url=clean_source_url,
            source_author=source_author.strip(), license_status=license_status.strip() or "owner_provided",
            license_text=license_text.strip(),
        )
        db.add(asset)
        db.flush()

    version_number = db.query(DBVideoAssetVersion).filter_by(asset_id=asset.id).count() + 1
    version_id = new_public_id("vav")
    output_dir = IMPORT_ROOT / actor.public_id / asset.id / version_id
    output_dir.mkdir(parents=True, exist_ok=False)
    media_path = output_dir / f"video{suffix}"
    fd, temp_name = tempfile.mkstemp(prefix=".video-", suffix=suffix, dir=output_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(video_raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, media_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    probe = _probe(media_path)
    subtitle_path = ""
    if normalized_subtitle:
        target = output_dir / f"subtitles{subtitle_suffix}"
        target.write_bytes(normalized_subtitle)
        subtitle_path = str(target.relative_to(ROOT)).replace("\\", "/")

    row = DBVideoAssetVersion(
        id=version_id, asset_id=asset.id, owner_public_id=actor.public_id, version_number=version_number,
        original_filename=name, media_format=suffix.lstrip("."), media_type=media_type,
        file_size=len(video_raw), source_sha256=source_hash,
        stored_path=str(media_path.relative_to(ROOT)).replace("\\", "/"),
        duration_ms=probe["duration_ms"], width=probe["width"], height=probe["height"],
        video_codec=probe["video_codec"], probe_status=probe["probe_status"],
        subtitle_filename=subtitle_name, subtitle_format=subtitle_suffix.lstrip("."),
        subtitle_sha256=subtitle_hash, subtitle_path=subtitle_path,
        subtitle_version=version_number if normalized_subtitle else 0, import_key=import_key,
        metadata_json={**metadata, "probe": probe, "truth_boundary": "本地上传且按当前 owner 隔离；来源与许可由上传者声明。"},
        created_by_public_id=actor.public_id,
    )
    db.add(row)
    db.flush()
    asset.current_version_id = row.id
    if version_number > 1:
        asset.lock_version += 1
    db.add(DBAuditLog(
        actor_public_id=actor.public_id, action="video_asset.imported", object_type="video_asset_version",
        object_id=row.id, trace_id=f"video-import-{new_public_id('trace')}", outcome="success",
        metadata_json={"asset_id": asset.id, "version_number": version_number, "source_sha256": source_hash,
                       "subtitle_sha256": subtitle_hash, "course_id": course_id, "chapter_id": chapter_id,
                       "file_content_persisted_in_audit": False},
    ))
    db.flush()
    return asset_payload(db, asset)


def asset_file(db: Any, *, actor: DBUser, asset_id: str, version_id: str, kind: str) -> tuple[Path, str]:
    asset = _owned(db, asset_id, actor)
    row = db.get(DBVideoAssetVersion, version_id)
    if row is None or row.asset_id != asset.id:
        _fail("video_import.version_unknown", "视频版本不存在")
    if kind == "video":
        relative, media_type = row.stored_path, row.media_type
    elif kind == "subtitle" and row.subtitle_path:
        relative, media_type = row.subtitle_path, ALLOWED_SUBTITLE.get("." + row.subtitle_format, "text/plain")
    else:
        _fail("video_import.file_unknown", "请求的媒体文件不存在")
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(IMPORT_ROOT.resolve())
    except ValueError as exc:
        raise VideoImportError("video_import.path_invalid", "视频存储路径无效") from exc
    if not path.is_file():
        _fail("video_import.file_missing", "视频文件已丢失")
    return path, media_type
