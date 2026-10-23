from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.database import DBVideoOutputVersion, DBVideoProject, DBVideoRenderTask, DBVideoScriptVersion, DBUser

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = Path(os.getenv("EDUMATRIX_VIDEO_OUTPUT_DIR", str(ROOT / "data" / "generated_videos"))).resolve()
MAX_SCENES = 12
MIN_DURATION_MS = 1500
MAX_DURATION_MS = 15000


class VideoRenderError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def runtime_status() -> dict[str, Any]:
    try:
        import imageio_ffmpeg
        binary = Path(imageio_ffmpeg.get_ffmpeg_exe())
        version = imageio_ffmpeg.get_ffmpeg_version()
        sapi = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; try { $v=$s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'zh-CN' } | Select-Object -First 1; if($v){$v.VoiceInfo.Name} } finally {$s.Dispose()}"],
            capture_output=True, text=True, timeout=15,
        )
        voice = sapi.stdout.strip() if sapi.returncode == 0 else ""
        return {
            "available": binary.is_file(), "package": "imageio-ffmpeg", "package_version": "0.6.0",
            "ffmpeg_version": version, "binary": str(binary), "binary_bytes": binary.stat().st_size,
            "binary_sha256": _hash_file(binary), "license": "BSD-2-Clause wrapper; bundled FFmpeg build",
            "offline": True, "admin_required": False, "sapi_voice": voice,
            "audio_available": bool(voice),
        }
    except Exception as exc:
        return {"available": False, "failure_code": "video.ffmpeg_unavailable", "message": str(exc)}


def _owned(db: Any, project_id: str, actor: DBUser) -> DBVideoProject:
    row = db.get(DBVideoProject, project_id)
    if not row:
        raise VideoRenderError("video.project_unknown", "视频项目不存在")
    if row.owner_public_id != actor.public_id:
        raise VideoRenderError("video.project_forbidden", "无权访问该视频项目")
    return row


def _validate_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= MAX_SCENES:
        raise VideoRenderError("video.scenes_invalid", "分镜数量必须为 1-12")
    result = []
    for index, item in enumerate(scenes, 1):
        title = str(item.get("title", "")).strip()
        narration = str(item.get("narration", "")).strip()
        bullets = [str(value).strip() for value in item.get("bullets", []) if str(value).strip()]
        duration = int(item.get("duration_ms", 4000))
        if not title or len(title) > 80 or not narration or len(narration) > 500 or len(bullets) > 5:
            raise VideoRenderError("video.scene_content_invalid", f"第 {index} 个分镜内容无效")
        if duration < MIN_DURATION_MS or duration > MAX_DURATION_MS:
            raise VideoRenderError("video.scene_duration_invalid", f"第 {index} 个分镜时长超出范围")
        result.append({"order": index, "title": title, "narration": narration, "bullets": bullets, "duration_ms": duration})
    return result


def _script_payload(row: DBVideoScriptVersion) -> dict[str, Any]:
    return {"id": row.id, "version_number": row.version_number, "scenes": row.scenes,
            "total_duration_ms": row.total_duration_ms, "content_hash": row.content_hash,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def _task_payload(db: Any, row: DBVideoRenderTask) -> dict[str, Any]:
    output = db.get(DBVideoOutputVersion, row.output_version_id) if row.output_version_id else None
    return {"id": row.id, "project_id": row.project_id, "script_version_id": row.script_version_id,
            "status": row.status, "progress": row.progress, "attempt": row.attempt,
            "audio_status": row.audio_status, "error_code": row.error_code, "error_message": row.error_message,
            "output": _output_payload(output) if output else None}


def _output_payload(row: DBVideoOutputVersion) -> dict[str, Any]:
    return {"id": row.id, "version_number": row.version_number, "duration_ms": row.duration_ms,
            "mp4_sha256": row.mp4_sha256, "manifest": row.output_manifest,
            "quality_report": row.quality_report, "created_at": row.created_at.isoformat() if row.created_at else None}


def _project_payload(db: Any, row: DBVideoProject) -> dict[str, Any]:
    script = db.get(DBVideoScriptVersion, row.current_script_version_id) if row.current_script_version_id else None
    tasks = db.query(DBVideoRenderTask).filter_by(project_id=row.id).order_by(DBVideoRenderTask.created_at.desc()).all()
    return {"id": row.id, "title": row.title, "course_id": row.course_id, "status": row.status,
            "lock_version": row.lock_version, "script": _script_payload(script) if script else None,
            "tasks": [_task_payload(db, task) for task in tasks]}


def list_projects(db: Any, actor: DBUser) -> dict[str, Any]:
    recover_interrupted(db, actor=actor)
    rows = db.query(DBVideoProject).filter_by(owner_public_id=actor.public_id, status="active").order_by(DBVideoProject.updated_at.desc()).all()
    return {"schema_version": "next.video-project-list.v1", "runtime": runtime_status(), "items": [_project_payload(db, row) for row in rows]}


def create_project(db: Any, *, actor: DBUser, title: str, course_id: str | None, scenes: list[dict[str, Any]]) -> dict[str, Any]:
    clean = _validate_scenes(scenes)
    row = DBVideoProject(owner_public_id=actor.public_id, course_id=course_id or None, title=title.strip())
    db.add(row); db.flush()
    version = DBVideoScriptVersion(project_id=row.id, version_number=1, scenes=clean,
        total_duration_ms=sum(item["duration_ms"] for item in clean), content_hash=_hash_bytes(_canonical(clean).encode()),
        created_by_public_id=actor.public_id)
    db.add(version); db.flush(); row.current_script_version_id = version.id; db.flush()
    return _project_payload(db, row)


def get_project(db: Any, *, actor: DBUser, project_id: str) -> dict[str, Any]:
    recover_interrupted(db, actor=actor)
    return _project_payload(db, _owned(db, project_id, actor))


def revise_script(db: Any, *, actor: DBUser, project_id: str, expected_version: int, scenes: list[dict[str, Any]]) -> dict[str, Any]:
    row = _owned(db, project_id, actor)
    if row.lock_version != expected_version:
        raise VideoRenderError("video.version_conflict", "视频项目已更新，请刷新后重试")
    clean = _validate_scenes(scenes)
    number = db.query(DBVideoScriptVersion).filter_by(project_id=row.id).count() + 1
    version = DBVideoScriptVersion(project_id=row.id, version_number=number, scenes=clean,
        total_duration_ms=sum(item["duration_ms"] for item in clean), content_hash=_hash_bytes(_canonical(clean).encode()),
        created_by_public_id=actor.public_id)
    db.add(version); db.flush(); row.current_script_version_id = version.id; row.lock_version += 1; db.flush()
    return _project_payload(db, row)


def _font(size: int, bold: bool = False):
    candidates = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / ("msyhbd.ttc" if bold else "msyh.ttc"),
                  Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "simhei.ttf"]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _frame(path: Path, project: DBVideoProject, scene: dict[str, Any], total: int) -> None:
    image = Image.new("RGB", (1280, 720), "#f4f7f5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1280, 92), fill="#17342b")
    draw.text((64, 28), "EduMatrix 技能微课", font=_font(28, True), fill="white")
    draw.text((64, 135), scene["title"], font=_font(48, True), fill="#15251f")
    y = 235
    for bullet in scene["bullets"]:
        draw.ellipse((68, y + 12, 82, y + 26), fill="#0f9f76")
        draw.text((100, y), bullet[:42], font=_font(28), fill="#31443d")
        y += 58
    draw.rounded_rectangle((64, 555, 1216, 650), radius=12, fill="#e3ece8")
    draw.text((88, 578), scene["narration"][:58], font=_font(23), fill="#31443d")
    draw.text((1100, 670), f"{scene['order']} / {total}", font=_font(20), fill="#667a72")
    image.save(path, "PNG")


def _timestamp(ms: int, vtt: bool = False) -> str:
    hours, remainder = divmod(ms, 3600000); minutes, remainder = divmod(remainder, 60000); seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{'.' if vtt else ','}{millis:03d}"


def _subtitles(scenes: list[dict[str, Any]], vtt: bool = False) -> str:
    lines = ["WEBVTT", ""] if vtt else []
    cursor = 0
    for index, scene in enumerate(scenes, 1):
        end = cursor + scene["duration_ms"]
        if not vtt: lines.append(str(index))
        lines.extend([f"{_timestamp(cursor, vtt)} --> {_timestamp(end, vtt)}", scene["narration"], ""])
        cursor = end
    return "\n".join(lines)


def _synthesize_audio(temp: Path, scenes: list[dict[str, Any]], runtime: dict[str, Any]) -> tuple[Path | None, str, str]:
    if not runtime.get("audio_available"):
        return None, "text_only", "video.sapi_voice_unavailable"
    script = ROOT / "scripts" / "synthesize_sapi_speech.ps1"
    wavs = []
    try:
        for index, scene in enumerate(scenes):
            raw = temp / f"voice-{index:02d}.wav"
            process = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                 "-Text", scene["narration"], "-OutputWav", str(raw)],
                capture_output=True, text=True, timeout=60,
            )
            if process.returncode != 0 or not raw.is_file():
                raise RuntimeError("sapi_scene_failed")
            aligned = temp / f"voice-aligned-{index:02d}.wav"
            duration = scene["duration_ms"] / 1000
            process = subprocess.run(
                [runtime["binary"], "-y", "-i", str(raw), "-af", f"apad,atrim=0:{duration:.3f}",
                 "-ar", "48000", "-ac", "1", str(aligned)], capture_output=True, text=True, timeout=60,
            )
            if process.returncode != 0 or not aligned.is_file():
                raise RuntimeError("audio_alignment_failed")
            wavs.append(aligned)
        concat = temp / "audio.txt"
        concat.write_text("\n".join(f"file '{path.as_posix()}'" for path in wavs) + "\n", encoding="utf-8")
        merged = temp / "narration.wav"
        process = subprocess.run(
            [runtime["binary"], "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(merged)],
            capture_output=True, text=True, timeout=60,
        )
        if process.returncode != 0 or not merged.is_file():
            raise RuntimeError("audio_concat_failed")
        return merged, "sapi_zh_cn", ""
    except Exception as exc:
        return None, "text_only", f"video.sapi_fallback:{exc}"


def render_project(db: Any, *, actor: DBUser, project_id: str, idempotency_key: str) -> dict[str, Any]:
    project = _owned(db, project_id, actor)
    existing = db.query(DBVideoRenderTask).filter_by(owner_public_id=actor.public_id, idempotency_key=idempotency_key).first()
    if existing:
        return _task_payload(db, existing)
    runtime = runtime_status()
    if not runtime.get("available"):
        raise VideoRenderError("video.ffmpeg_unavailable", "离线 FFmpeg 运行时不可用")
    script = db.get(DBVideoScriptVersion, project.current_script_version_id)
    task = DBVideoRenderTask(project_id=project.id, script_version_id=script.id, owner_public_id=actor.public_id,
                             idempotency_key=idempotency_key, status="running", progress=5, started_at=datetime.utcnow())
    db.add(task); db.flush(); db.commit()
    try:
        output_dir = OUTPUT_ROOT / actor.public_id / project.id / task.id
        output_dir.mkdir(parents=True, exist_ok=True)
        # Keep intermediate files on the output volume so the text-only
        # fallback can atomically promote the silent MP4 on Windows.
        with tempfile.TemporaryDirectory(prefix="edumatrix-video-", dir=output_dir) as temp_name:
            temp = Path(temp_name); concat_lines = []
            for index, scene in enumerate(script.scenes):
                frame = temp / f"scene-{index:02d}.png"; _frame(frame, project, scene, len(script.scenes))
                concat_lines.extend([f"file '{frame.as_posix()}'", f"duration {scene['duration_ms'] / 1000:.3f}"])
            concat_lines.append(f"file '{frame.as_posix()}'")
            concat = temp / "frames.txt"; concat.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
            silent = temp / "silent.mp4"
            command = [runtime["binary"], "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
                       "-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-movflags", "+faststart", str(silent)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if result.returncode != 0 or not silent.is_file():
                raise VideoRenderError("video.ffmpeg_failed", "FFmpeg 渲染失败")
            audio, audio_status, audio_error = _synthesize_audio(temp, script.scenes, runtime)
            mp4 = output_dir / "course-video.mp4"
            if audio:
                result = subprocess.run(
                    [runtime["binary"], "-y", "-i", str(silent), "-i", str(audio), "-c:v", "copy", "-c:a", "aac",
                     "-shortest", "-movflags", "+faststart", str(mp4)], capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0 or not mp4.is_file():
                    audio_status, audio_error = "text_only", "video.audio_mux_failed"
                    silent.replace(mp4)
            else:
                silent.replace(mp4)
        srt = output_dir / "subtitles.srt"; srt.write_text(_subtitles(script.scenes), encoding="utf-8")
        vtt = output_dir / "subtitles.vtt"; vtt.write_text(_subtitles(script.scenes, True), encoding="utf-8")
        transcript = output_dir / "transcript.json"; transcript.write_text(json.dumps({"scenes": script.scenes}, ensure_ascii=False, indent=2), encoding="utf-8")
        duration = script.total_duration_ms
        task.audio_status = audio_status
        quality = {"passed": mp4.stat().st_size > 1024, "container": "mp4", "video_codec": "h264",
                   "resolution": "1280x720", "duration_ms": duration, "subtitle_cues": len(script.scenes),
                   "audio_status": audio_status, "audio_error": audio_error,
                   "truth_boundary": "音轨状态按实际渲染结果披露；字幕与讲稿始终保留。"}
        manifest = {"schema_version": "next.video-output-manifest.v1", "runtime": runtime,
                    "files": [{"name": p.name, "bytes": p.stat().st_size, "sha256": _hash_file(p)} for p in (mp4, srt, vtt, transcript)]}
        number = db.query(DBVideoOutputVersion).filter_by(project_id=project.id).count() + 1
        output = DBVideoOutputVersion(project_id=project.id, render_task_id=task.id, owner_public_id=actor.public_id,
            version_number=number, output_manifest=manifest, output_dir=str(output_dir.relative_to(ROOT)).replace("\\", "/"),
            mp4_sha256=_hash_file(mp4), duration_ms=duration, quality_report=quality)
        db.add(output); db.flush(); task.output_version_id = output.id; task.status = "completed"; task.progress = 100; task.finished_at = datetime.utcnow(); db.commit()
        return _task_payload(db, task)
    except Exception as exc:
        db.rollback(); task = db.get(DBVideoRenderTask, task.id); task.status = "failed"; task.progress = 0
        task.error_code = exc.code if isinstance(exc, VideoRenderError) else "video.render_failed"
        task.error_message = str(exc)[:500]; task.finished_at = datetime.utcnow(); db.commit()
        raise VideoRenderError(task.error_code, task.error_message) from exc


def cancel_task(db: Any, *, actor: DBUser, task_id: str) -> dict[str, Any]:
    task = db.get(DBVideoRenderTask, task_id)
    if not task: raise VideoRenderError("video.task_unknown", "渲染任务不存在")
    if task.owner_public_id != actor.public_id: raise VideoRenderError("video.task_forbidden", "无权访问该渲染任务")
    if task.status not in {"queued", "failed"}: raise VideoRenderError("video.task_not_cancellable", "仅排队或失败任务可取消")
    task.status = "cancelled"; task.finished_at = datetime.utcnow(); db.flush(); return _task_payload(db, task)


def recover_interrupted(db: Any, *, actor: DBUser | None = None) -> int:
    query = db.query(DBVideoRenderTask).filter_by(status="running")
    if actor is not None: query = query.filter_by(owner_public_id=actor.public_id)
    rows = query.all()
    for task in rows:
        task.status = "failed"; task.progress = 0; task.error_code = "video.render_interrupted"
        task.error_message = "上次渲染进程中断，可使用新幂等键重试"; task.finished_at = datetime.utcnow()
    if rows: db.flush()
    return len(rows)


def output_file(db: Any, *, actor: DBUser, output_id: str, filename: str) -> Path:
    row = db.get(DBVideoOutputVersion, output_id)
    if not row: raise VideoRenderError("video.output_unknown", "视频输出不存在")
    if row.owner_public_id != actor.public_id: raise VideoRenderError("video.output_forbidden", "无权访问该视频输出")
    allowed = {item["name"] for item in row.output_manifest.get("files", [])}
    if filename not in allowed: raise VideoRenderError("video.output_file_unknown", "输出文件不存在")
    path = (ROOT / row.output_dir / filename).resolve()
    try: path.relative_to(OUTPUT_ROOT)
    except ValueError as exc: raise VideoRenderError("video.output_path_invalid", "输出路径无效") from exc
    if not path.is_file(): raise VideoRenderError("video.output_file_missing", "输出文件已丢失")
    return path
