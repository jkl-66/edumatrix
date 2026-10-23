from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "vendor" / "whisper.cpp"
MANIFEST_PATH = RUNTIME_ROOT / "runtime-manifest.json"


class SpeechRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_status() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        return {"available": False, "failure_code": "speech_runtime_manifest_missing"}
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        binary = RUNTIME_ROOT / manifest["runtime"]["binary"]
        model = RUNTIME_ROOT / manifest["model"]["path"]
        license_path = RUNTIME_ROOT / manifest["runtime"]["license_file"]
        checks = {
            "binary": binary.is_file() and sha256_file(binary) == manifest["runtime"]["binary_sha256"],
            "model": model.is_file() and model.stat().st_size == manifest["model"]["bytes"] and sha256_file(model) == manifest["model"]["sha256"],
            "license": license_path.is_file() and sha256_file(license_path) == manifest["runtime"]["license_sha256"],
        }
        return {
            "available": all(checks.values()),
            "failure_code": "" if all(checks.values()) else "speech_runtime_integrity_failed",
            "version": manifest["runtime"]["version"],
            "model_name": manifest["model"]["name"],
            "binary_sha256": manifest["runtime"]["binary_sha256"],
            "model_sha256": manifest["model"]["sha256"],
            "checks": checks,
            "offline_cpu": True,
        }
    except Exception:
        return {"available": False, "failure_code": "speech_runtime_manifest_invalid"}


def validate_wav(path: Path, *, max_bytes: int = 25 * 1024 * 1024, max_seconds: int = 300) -> dict[str, int]:
    if not path.is_file() or path.stat().st_size <= 44 or path.stat().st_size > max_bytes:
        raise SpeechRuntimeError("speech_wav_size_invalid", "WAV 文件为空或超过限制")
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            sample_rate = audio.getframerate()
            sample_width = audio.getsampwidth()
            frame_count = audio.getnframes()
    except (wave.Error, EOFError) as exc:
        raise SpeechRuntimeError("speech_wav_invalid", "音频不是有效的 PCM WAV") from exc
    duration_ms = round(frame_count / sample_rate * 1000) if sample_rate else 0
    if channels != 1 or sample_rate != 16000 or sample_width != 2:
        raise SpeechRuntimeError("speech_wav_contract_invalid", "音频必须为 16kHz 单声道 16-bit PCM WAV")
    if duration_ms <= 0 or duration_ms > max_seconds * 1000:
        raise SpeechRuntimeError("speech_duration_invalid", "音频时长为空或超过限制")
    return {"channels": channels, "sample_rate": sample_rate, "sample_width": sample_width, "duration_ms": duration_ms, "bytes": path.stat().st_size}


def _language_arg(language: str) -> str:
    return language if language in {"auto", "zh", "en"} else "auto"


def transcribe_wav(path: Path, *, language: str = "auto", cancelled: callable | None = None) -> dict[str, Any]:
    info = validate_wav(path)
    runtime = runtime_status()
    if not runtime.get("available"):
        raise SpeechRuntimeError(runtime.get("failure_code", "speech_runtime_unavailable"), "离线语音运行时不可用")
    if cancelled and cancelled():
        raise SpeechRuntimeError("speech_cancelled", "语音任务已取消")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    binary = RUNTIME_ROOT / manifest["runtime"]["binary"]
    model = RUNTIME_ROOT / manifest["model"]["path"]
    with tempfile.TemporaryDirectory(prefix="edumatrix-speech-") as temporary:
        output = Path(temporary) / "transcript"
        command = [str(binary), "-m", str(model), "-f", str(path), "-l", _language_arg(language), "-nt", "-np", "-oj", "-of", str(output)]
        process = subprocess.Popen(command, cwd=binary.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 360
        while process.poll() is None:
            if cancelled and cancelled():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                raise SpeechRuntimeError("speech_cancelled", "语音任务已取消")
            if time.monotonic() >= deadline:
                process.kill()
                process.wait(timeout=3)
                raise SpeechRuntimeError("speech_runtime_timeout", "离线转写超过时间限制")
            time.sleep(0.1)
        json_path = output.with_suffix(".json")
        if process.returncode != 0 or not json_path.is_file():
            raise SpeechRuntimeError("speech_runtime_failed", "离线语音运行时执行失败")
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    segments = []
    for index, item in enumerate(payload.get("transcription", [])):
        offsets = item.get("offsets") or {}
        text = str(item.get("text") or "").strip()
        if text:
            segments.append({"index": index, "start_ms": int(offsets.get("from") or 0), "end_ms": int(offsets.get("to") or 0), "text": text})
    transcript = " ".join(item["text"] for item in segments).strip()
    if not transcript:
        raise SpeechRuntimeError("speech_transcript_empty", "音频中没有识别到可用语音")
    return {"transcript": transcript, "segments": segments, "detected_language": payload.get("result", {}).get("language", ""), "audio": info, "runtime": runtime}
