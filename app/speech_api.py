from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import Field

from app.auth import get_current_user
from app.database import DBAuditLog, DBGenerationTask, DBSpeechSegment, DBSpeechSession, DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.offline_speech import SpeechRuntimeError, runtime_status, transcribe_wav, validate_wav


router = APIRouter(prefix="/api/v1/speech", tags=["offline-speech"])
SPEECH_DIR = Path(os.getenv("EDUMATRIX_SPEECH_DIR", "data/speech"))
SPEECH_DIR.mkdir(parents=True, exist_ok=True)


class TranscribeInput(StrictModel):
    language: str = Field(default="auto", pattern="^(auto|zh|en)$")


def _session_payload(row: DBSpeechSession, segments: list[DBSpeechSegment]) -> dict[str, Any]:
    return {
        "id": row.id, "title": row.title, "status": row.status, "language": row.language,
        "duration_ms": row.duration_ms, "source_bytes": row.source_bytes,
        "source_sha256": row.source_sha256, "transcript": row.transcript or "",
        "transcript_sha256": row.transcript_sha256 or "", "truth_state": row.truth_state,
        "failure_code": row.failure_code or "", "runtime_version": row.runtime_version or "",
        "model_name": row.model_name or "", "model_sha256": row.model_sha256 or "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "completed_at": row.completed_at.isoformat() if row.completed_at else "",
        "segments": [{"index": item.segment_index, "start_ms": item.start_ms, "end_ms": item.end_ms, "text": item.text, "text_sha256": item.text_sha256} for item in segments],
    }


def _owned(session: Any, session_id: str, user: DBUser) -> DBSpeechSession:
    row = session.get(DBSpeechSession, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="语音会话不存在")
    if row.owner_public_id != user.public_id:
        raise HTTPException(status_code=403, detail="无权访问该语音会话")
    return row


def _audit(db: Any, *, user: DBUser, action: str, row: DBSpeechSession, outcome: str = "success") -> None:
    db.add(DBAuditLog(
        actor_public_id=user.public_id,
        action=action,
        object_type="speech_session",
        object_id=row.id,
        trace_id=f"speech-audit-{uuid.uuid4().hex}",
        outcome=outcome,
        metadata_json={
            "status": row.status,
            "truth_state": row.truth_state,
            "source_sha256": row.source_sha256,
            "source_bytes": row.source_bytes,
            "duration_ms": row.duration_ms,
            "raw_audio_persisted_in_audit": False,
            "transcript_persisted_in_audit": False,
        },
    ))


@router.get("/runtime")
async def get_speech_runtime(current_user: DBUser = Depends(get_current_user)):
    status = runtime_status()
    return {**status, "text_fallback_available": True, "external_model_used": False}


@router.post("/sessions")
async def create_speech_session(file: UploadFile = File(...), language: str = "auto", current_user: DBUser = Depends(get_current_user)):
    if language not in {"auto", "zh", "en"}:
        raise HTTPException(status_code=422, detail="不支持的语音语言")
    raw = await file.read(25 * 1024 * 1024 + 1)
    session_id = f"speech-{uuid.uuid4().hex[:24]}"
    owner_dir = SPEECH_DIR / current_user.public_id / session_id
    owner_dir.mkdir(parents=True, exist_ok=False)
    path = owner_dir / "source.wav"
    temporary = owner_dir / ".source.wav.tmp"
    try:
        temporary.write_bytes(raw)
        os.replace(temporary, path)
        info = validate_wav(path)
    except SpeechRuntimeError as exc:
        shutil.rmtree(owner_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc
    source_hash = hashlib.sha256(raw).hexdigest()
    def save(db):
        task = DBGenerationTask(owner_public_id=current_user.public_id, trace_id=f"speech-{uuid.uuid4().hex}", status="queued", progress=0.0, capability="offline_speech_transcription", model="whisper.cpp/base-q5_1", idempotency_key=f"speech:{session_id}")
        db.add(task); db.flush()
        row = DBSpeechSession(id=session_id, owner_public_id=current_user.public_id, task_id=task.id, title=(Path(file.filename or "录音").stem[:240] or "语音训练记录"), status="uploaded", language=language, source_sha256=source_hash, source_bytes=info["bytes"], duration_ms=info["duration_ms"], sample_rate=info["sample_rate"], channel_count=info["channels"], truth_state="pending")
        db.add(row); db.flush(); _audit(db,user=current_user,action="speech_session_created",row=row); db.commit()
        return _session_payload(row, [])
    try:
        return await run_db_op(save)
    except Exception:
        shutil.rmtree(owner_dir, ignore_errors=True)
        raise


@router.get("/sessions")
async def list_speech_sessions(current_user: DBUser = Depends(get_current_user)):
    def fetch(db):
        rows = db.query(DBSpeechSession).filter_by(owner_public_id=current_user.public_id).order_by(DBSpeechSession.created_at.desc()).limit(50).all()
        return [_session_payload(row, db.query(DBSpeechSegment).filter_by(session_id=row.id).order_by(DBSpeechSegment.segment_index).all()) for row in rows]
    return await run_db_op(fetch)


@router.get("/sessions/{session_id}")
async def get_speech_session(session_id: str, current_user: DBUser = Depends(get_current_user)):
    def fetch(db):
        row = _owned(db, session_id, current_user)
        return _session_payload(row, db.query(DBSpeechSegment).filter_by(session_id=row.id).order_by(DBSpeechSegment.segment_index).all())
    return await run_db_op(fetch)


@router.post("/sessions/{session_id}/transcribe")
async def transcribe_speech_session(session_id: str, payload: TranscribeInput, current_user: DBUser = Depends(get_current_user)):
    def begin(db):
        row = _owned(db, session_id, current_user)
        if row.status == "completed": return "completed", _session_payload(row, db.query(DBSpeechSegment).filter_by(session_id=row.id).order_by(DBSpeechSegment.segment_index).all())
        if row.status == "cancelled": raise HTTPException(status_code=409, detail="语音会话已取消")
        if row.status == "processing": raise HTTPException(status_code=409, detail="语音会话正在转写")
        if row.status in {"failed", "unavailable"}: raise HTTPException(status_code=409, detail="语音会话已进入失败终态")
        status = runtime_status()
        if not status.get("available"):
            row.status="unavailable"; row.truth_state="unavailable"; row.failure_code=status.get("failure_code", "speech_runtime_unavailable"); row.completed_at=datetime.now(timezone.utc).replace(tzinfo=None)
            task=db.get(DBGenerationTask,row.task_id)
            if task: task.status="failed"; task.failure_code=row.failure_code; task.completed_at=row.completed_at
            _audit(db,user=current_user,action="speech_transcription_finished",row=row,outcome="unavailable"); db.commit()
            return "unavailable", _session_payload(row, [])
        row.status="processing"; row.started_at=datetime.now(timezone.utc).replace(tzinfo=None); row.language=payload.language
        task=db.get(DBGenerationTask,row.task_id); task.status="running"; task.started_at=row.started_at; task.progress=0.1
        db.commit(); return "run", None
    action, existing = await run_db_op(begin)
    if action != "run": return existing
    path = SPEECH_DIR / current_user.public_id / session_id / "source.wav"
    try:
        result = await asyncio.to_thread(
            transcribe_wav,
            path,
            language=payload.language,
            cancelled=lambda: _cancelled(session_id, current_user.public_id),
        )
    except SpeechRuntimeError as exc:
        def fail(db):
            row=_owned(db,session_id,current_user); row.status="cancelled" if exc.code=="speech_cancelled" else "failed"; row.truth_state="cancelled" if exc.code=="speech_cancelled" else "failed"; row.failure_code=exc.code; row.completed_at=datetime.now(timezone.utc).replace(tzinfo=None)
            task=db.get(DBGenerationTask,row.task_id); task.status=row.status; task.failure_code=exc.code; task.completed_at=row.completed_at; _audit(db,user=current_user,action="speech_transcription_finished",row=row,outcome=row.status); db.commit(); return _session_payload(row,[])
        return await run_db_op(fail)
    def complete(db):
        row=_owned(db,session_id,current_user)
        if row.status=="cancelled": return _session_payload(row,[])
        for segment in result["segments"]:
            text=segment["text"]; db.add(DBSpeechSegment(session_id=row.id,segment_index=segment["index"],start_ms=segment["start_ms"],end_ms=segment["end_ms"],text=text,text_sha256=hashlib.sha256(text.encode()).hexdigest()))
        row.status="completed"; row.truth_state="real_offline"; row.transcript=result["transcript"]; row.transcript_sha256=hashlib.sha256(row.transcript.encode()).hexdigest(); row.completed_at=datetime.now(timezone.utc).replace(tzinfo=None); row.runtime_version=result["runtime"]["version"]; row.binary_sha256=result["runtime"]["binary_sha256"]; row.model_name=result["runtime"]["model_name"]; row.model_sha256=result["runtime"]["model_sha256"]
        task=db.get(DBGenerationTask,row.task_id); task.status="completed"; task.progress=1.0; task.completed_at=row.completed_at; _audit(db,user=current_user,action="speech_transcription_finished",row=row); db.commit()
        return _session_payload(row,db.query(DBSpeechSegment).filter_by(session_id=row.id).order_by(DBSpeechSegment.segment_index).all())
    return await run_db_op(complete)


def _cancelled(session_id: str, owner_id: str) -> bool:
    from app.database import SessionLocal
    with SessionLocal() as db:
        row=db.get(DBSpeechSession,session_id)
        return row is None or row.owner_public_id != owner_id or row.status == "cancelled"


def recover_interrupted_speech_sessions(db: Any) -> int:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = db.query(DBSpeechSession).filter_by(status="processing").all()
    for row in rows:
        row.status = "failed"
        row.truth_state = "failed"
        row.failure_code = "speech_process_interrupted"
        row.completed_at = now
        task = db.get(DBGenerationTask, row.task_id)
        if task and task.status == "running":
            task.status = "failed"
            task.failure_code = row.failure_code
            task.completed_at = now
    if rows:
        db.commit()
    return len(rows)


@router.post("/sessions/{session_id}/cancel")
async def cancel_speech_session(session_id: str, current_user: DBUser = Depends(get_current_user)):
    def cancel(db):
        row=_owned(db,session_id,current_user)
        if row.status=="completed": raise HTTPException(status_code=409,detail="已完成的语音会话不能取消")
        row.status="cancelled"; row.truth_state="cancelled"; row.failure_code="speech_cancelled"; row.completed_at=datetime.now(timezone.utc).replace(tzinfo=None)
        task=db.get(DBGenerationTask,row.task_id)
        if task: task.status="cancelled"; task.failure_code="speech_cancelled"; task.completed_at=row.completed_at
        _audit(db,user=current_user,action="speech_session_cancelled",row=row,outcome="cancelled")
        db.commit(); return _session_payload(row,[])
    return await run_db_op(cancel)


def _vtt_timestamp(milliseconds: int) -> str:
    milliseconds = max(0, int(milliseconds))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


@router.get("/sessions/{session_id}/subtitles.vtt", response_class=PlainTextResponse)
async def export_speech_subtitles(session_id: str, current_user: DBUser = Depends(get_current_user)):
    def fetch(db):
        row = _owned(db, session_id, current_user)
        if row.status != "completed":
            raise HTTPException(status_code=409, detail="语音转写尚未完成")
        return db.query(DBSpeechSegment).filter_by(session_id=row.id).order_by(DBSpeechSegment.segment_index).all()
    segments = await run_db_op(fetch)
    lines = ["WEBVTT", ""]
    for item in segments:
        lines.extend([
            str(item.segment_index + 1),
            f"{_vtt_timestamp(item.start_ms)} --> {_vtt_timestamp(item.end_ms)}",
            item.text.replace("\r", " ").replace("\n", " "),
            "",
        ])
    return PlainTextResponse(
        "\n".join(lines),
        media_type="text/vtt; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{session_id}.vtt"', "Cache-Control": "private, no-store"},
    )
