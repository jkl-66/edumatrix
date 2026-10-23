from __future__ import annotations

import hashlib
import math
import struct
import wave
from io import BytesIO

from fastapi.testclient import TestClient

import app.speech_api as speech_api
from app.database import DBAuditLog, DBGenerationTask, DBSpeechSegment, DBSpeechSession, SessionLocal
from app.main import app
from app.offline_speech import SpeechRuntimeError, runtime_status, validate_wav
from tests.api_test_helpers import auth_headers


def _wav_bytes(seconds: float = 0.3) -> bytes:
    sample_rate = 16000
    frames = int(sample_rate * seconds)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"".join(
            struct.pack("<h", int(5000 * math.sin(2 * math.pi * 440 * index / sample_rate)))
            for index in range(frames)
        ))
    return buffer.getvalue()


def test_bundled_whisper_runtime_manifest_and_hashes_are_valid():
    status = runtime_status()
    assert status["available"] is True
    assert status["version"] == "v1.9.1"
    assert status["model_name"] == "ggml-base-q5_1.bin"
    assert status["checks"] == {"binary": True, "model": True, "license": True}
    assert status["offline_cpu"] is True


def test_wav_contract_fails_closed(tmp_path):
    invalid = tmp_path / "stereo.wav"
    with wave.open(str(invalid), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(44100)
        output.writeframes(b"\0" * 4410)
    try:
        validate_wav(invalid)
    except SpeechRuntimeError as exc:
        assert exc.code == "speech_wav_contract_invalid"
    else:
        raise AssertionError("invalid WAV contract was accepted")


def test_owner_speech_lifecycle_transcript_vtt_and_privacy(tmp_path, monkeypatch):
    monkeypatch.setattr(speech_api, "SPEECH_DIR", tmp_path / "speech")
    runtime = runtime_status()

    def fake_transcribe(path, *, language, cancelled):
        assert path.is_file() and language == "zh" and not cancelled()
        return {
            "transcript": "知识图谱训练完成",
            "segments": [
                {"index": 0, "start_ms": 0, "end_ms": 1200, "text": "知识图谱"},
                {"index": 1, "start_ms": 1200, "end_ms": 2400, "text": "训练完成"},
            ],
            "detected_language": "zh",
            "audio": {"duration_ms": 300},
            "runtime": runtime,
        }

    monkeypatch.setattr(speech_api, "transcribe_wav", fake_transcribe)
    with TestClient(app) as client:
        owner_headers = auth_headers(client, "nc_media_02_owner")
        other_headers = auth_headers(client, "nc_media_02_other")
        created = client.post(
            "/api/v1/speech/sessions?language=zh",
            headers=owner_headers,
            files={"file": ("training.wav", _wav_bytes(), "audio/wav")},
        )
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["status"] == "uploaded"
        assert payload["truth_state"] == "pending"
        session_id = payload["id"]

        completed = client.post(
            f"/api/v1/speech/sessions/{session_id}/transcribe",
            headers=owner_headers,
            json={"language": "zh"},
        )
        assert completed.status_code == 200, completed.text
        body = completed.json()
        assert body["status"] == "completed"
        assert body["truth_state"] == "real_offline"
        assert body["transcript"] == "知识图谱训练完成"
        assert len(body["segments"]) == 2
        assert body["model_sha256"] == runtime["model_sha256"]

        vtt = client.get(
            f"/api/v1/speech/sessions/{session_id}/subtitles.vtt", headers=owner_headers
        )
        assert vtt.status_code == 200
        assert "WEBVTT" in vtt.text
        assert "00:00:01.200 --> 00:00:02.400" in vtt.text
        assert "训练完成" in vtt.text
        assert vtt.headers["cache-control"] == "private, no-store"

        denied = client.get(f"/api/v1/speech/sessions/{session_id}", headers=other_headers)
        denied_vtt = client.get(
            f"/api/v1/speech/sessions/{session_id}/subtitles.vtt", headers=other_headers
        )
        assert denied.status_code == denied_vtt.status_code == 403

        with SessionLocal() as db:
            row = db.get(DBSpeechSession, session_id)
            assert row is not None and row.transcript_sha256 == hashlib.sha256(body["transcript"].encode()).hexdigest()
            assert db.query(DBSpeechSegment).filter_by(session_id=session_id).count() == 2
            audits = db.query(DBAuditLog).filter_by(object_type="speech_session", object_id=session_id).all()
            assert len(audits) >= 2
            assert all("知识图谱" not in str(item.metadata_json) for item in audits)
            assert all(item.metadata_json["raw_audio_persisted_in_audit"] is False for item in audits)


def test_cancel_and_missing_runtime_are_truthful(tmp_path, monkeypatch):
    monkeypatch.setattr(speech_api, "SPEECH_DIR", tmp_path / "speech")
    with TestClient(app) as client:
        headers = auth_headers(client, "nc_media_02_fallback")
        cancelled = client.post(
            "/api/v1/speech/sessions",
            headers=headers,
            files={"file": ("cancel.wav", _wav_bytes(), "audio/wav")},
        )
        session_id = cancelled.json()["id"]
        response = client.post(f"/api/v1/speech/sessions/{session_id}/cancel", headers=headers)
        assert response.status_code == 200
        assert response.json()["truth_state"] == "cancelled"
        conflict = client.post(
            f"/api/v1/speech/sessions/{session_id}/transcribe",
            headers=headers,
            json={"language": "auto"},
        )
        assert conflict.status_code == 409

        unavailable = client.post(
            "/api/v1/speech/sessions",
            headers=headers,
            files={"file": ("unavailable.wav", _wav_bytes(), "audio/wav")},
        )
        unavailable_id = unavailable.json()["id"]
        monkeypatch.setattr(
            speech_api,
            "runtime_status",
            lambda: {"available": False, "failure_code": "speech_runtime_integrity_failed"},
        )
        result = client.post(
            f"/api/v1/speech/sessions/{unavailable_id}/transcribe",
            headers=headers,
            json={"language": "auto"},
        )
        assert result.status_code == 200
        assert result.json()["status"] == "unavailable"
        assert result.json()["truth_state"] == "unavailable"
        assert result.json()["failure_code"] == "speech_runtime_integrity_failed"
        with SessionLocal() as db:
            row = db.get(DBSpeechSession, unavailable_id)
            task = db.get(DBGenerationTask, row.task_id)
            assert row.completed_at is not None
            assert task.status == "failed"
            assert task.failure_code == "speech_runtime_integrity_failed"


def test_processing_session_rejects_duplicate_transcription(tmp_path, monkeypatch):
    monkeypatch.setattr(speech_api, "SPEECH_DIR", tmp_path / "speech")
    with TestClient(app) as client:
        headers = auth_headers(client, "nc_media_02_duplicate")
        created = client.post(
            "/api/v1/speech/sessions",
            headers=headers,
            files={"file": ("duplicate.wav", _wav_bytes(), "audio/wav")},
        )
        session_id = created.json()["id"]
        with SessionLocal() as db:
            row = db.get(DBSpeechSession, session_id)
            row.status = "processing"
            db.commit()
        response = client.post(
            f"/api/v1/speech/sessions/{session_id}/transcribe",
            headers=headers,
            json={"language": "auto"},
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "语音会话正在转写"


def test_interrupted_processing_session_recovers_to_truthful_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(speech_api, "SPEECH_DIR", tmp_path / "speech")
    with TestClient(app) as client:
        headers = auth_headers(client, "nc_media_02_recovery")
        created = client.post(
            "/api/v1/speech/sessions",
            headers=headers,
            files={"file": ("recovery.wav", _wav_bytes(), "audio/wav")},
        )
        session_id = created.json()["id"]
        with SessionLocal() as db:
            row = db.get(DBSpeechSession, session_id)
            task = db.get(DBGenerationTask, row.task_id)
            row.status = "processing"
            row.truth_state = "pending"
            task.status = "running"
            db.commit()
            assert speech_api.recover_interrupted_speech_sessions(db) == 1
            db.refresh(row)
            db.refresh(task)
            assert row.status == row.truth_state == "failed"
            assert row.failure_code == "speech_process_interrupted"
            assert task.status == "failed"
            assert task.failure_code == "speech_process_interrupted"
