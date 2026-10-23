"""Verify the bundled offline speech workflow through the real API and Chromium UI."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-MEDIA-02" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_media_speech_e2e.db"
SPEECH_ROOT = ROOT / "outputs" / "_next_media_speech_e2e_audio"
EVIDENCE_DB = OUTPUT / "offline_speech_evidence.db"
PROBE_WAV = OUTPUT / "offline-speech-probe.wav"
PORT = 8790
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-media-speech-2026!"
PROBE_TEXT = "Edu Matrix offline speech training works."


def wait_port(open_: bool, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} state timeout")


def stop(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, 15)


def make_windows_sapi_probe(path: Path) -> None:
    escaped_path = str(path).replace("'", "''")
    escaped_text = PROBE_TEXT.replace("'", "''")
    command = (
        "Add-Type -AssemblyName System.Speech; "
        "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        f"$synth.SetOutputToWaveFile('{escaped_path}', $format); "
        f"$synth.Speak('{escaped_text}'); $synth.Dispose()"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0 or not path.is_file():
        raise RuntimeError(f"Windows SAPI probe generation failed: {result.stderr.strip()}")
    with wave.open(str(path), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 16000
        assert audio.getsampwidth() == 2


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path.name


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    if SPEECH_ROOT.exists():
        assert SPEECH_ROOT.resolve().is_relative_to((ROOT / "outputs").resolve())
        shutil.rmtree(SPEECH_ROOT)
    make_windows_sapi_probe(PROBE_WAV)

    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_SPEECH_DIR": str(SPEECH_ROOT),
        "EDUMATRIX_AUTH_SECRET_KEY": "next-media-speech-e2e-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {
        "schema_version": "next.offline-speech-e2e.v1",
        "scope": "real bundled whisper.cpp transcription, timeline, TTS control, refresh, owner 403 and mobile geometry",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {},
        "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    suffix = str(int(time.time()))
                    owner_name = f"speech_owner_{suffix}"
                    other_name = f"speech_other_{suffix}"
                    owner = page.request.post(f"{BASE_URL}/api/auth/register", data={
                        "username": owner_name, "password": PASSWORD, "display_name": "语音验收用户",
                    })
                    other = page.request.post(f"{BASE_URL}/api/auth/register", data={
                        "username": other_name, "password": PASSWORD, "display_name": "语音隔离用户",
                    })
                    assert owner.ok and other.ok
                    owner_token = owner.json()["access_token"]
                    other_token = other.json()["access_token"]
                    owner_headers = {"Authorization": f"Bearer {owner_token}"}
                    other_headers = {"Authorization": f"Bearer {other_token}"}

                    runtime = page.request.get(f"{BASE_URL}/api/v1/speech/runtime", headers=owner_headers)
                    assert runtime.ok and runtime.json()["available"] is True
                    assert runtime.json()["external_model_used"] is False
                    report["checks"]["runtime"] = runtime.json()

                    created = page.request.post(
                        f"{BASE_URL}/api/v1/speech/sessions?language=en",
                        headers=owner_headers,
                        multipart={"file": {"name": PROBE_WAV.name, "mimeType": "audio/wav", "buffer": PROBE_WAV.read_bytes()}},
                    )
                    assert created.ok, created.text()
                    session_id = created.json()["id"]
                    completed = page.request.post(
                        f"{BASE_URL}/api/v1/speech/sessions/{session_id}/transcribe",
                        headers=owner_headers,
                        data={"language": "en"},
                        timeout=360_000,
                    )
                    assert completed.ok, completed.text()
                    transcript = completed.json()
                    assert transcript["status"] == "completed", transcript
                    assert transcript["truth_state"] == "real_offline"
                    assert transcript["segments"]
                    normalized = transcript["transcript"].lower().replace("-", " ")
                    assert "offline" in normalized and "speech" in normalized and "training" in normalized
                    report["checks"]["real_transcription"] = {
                        "session_id": session_id,
                        "transcript": transcript["transcript"],
                        "segment_count": len(transcript["segments"]),
                        "truth_state": transcript["truth_state"],
                        "source_sha256": transcript["source_sha256"],
                        "model_sha256": transcript["model_sha256"],
                    }

                    denied = page.request.get(
                        f"{BASE_URL}/api/v1/speech/sessions/{session_id}", headers=other_headers,
                    )
                    denied_vtt = page.request.get(
                        f"{BASE_URL}/api/v1/speech/sessions/{session_id}/subtitles.vtt", headers=other_headers,
                    )
                    vtt = page.request.get(
                        f"{BASE_URL}/api/v1/speech/sessions/{session_id}/subtitles.vtt", headers=owner_headers,
                    )
                    assert denied.status == denied_vtt.status == 403
                    assert vtt.ok and "WEBVTT" in vtt.text()
                    report["checks"]["authorization_and_vtt"] = {
                        "cross_owner_session": denied.status,
                        "cross_owner_vtt": denied_vtt.status,
                        "vtt_sha256": hashlib.sha256(vtt.body()).hexdigest(),
                    }

                    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'student')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_display_name', '语音验收用户')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [owner_token, owner_name],
                    )
                    page.goto(f"{BASE_URL}/speech-training", wait_until="domcontentloaded", timeout=30_000)
                    workspace = page.get_by_test_id("speech-training-workspace")
                    workspace.wait_for(state="visible", timeout=30_000)
                    page.get_by_test_id("speech-runtime-status").wait_for(state="visible")
                    panel = page.get_by_test_id("speech-transcript-panel")
                    panel.wait_for(state="visible", timeout=30_000)
                    page.get_by_test_id("local-avatar-speech").wait_for(state="visible", timeout=30_000)
                    assert "本地数字人讲解层" in page.get_by_test_id("local-avatar-speech").inner_text()
                    body = panel.inner_text().lower().replace("-", " ")
                    assert "offline" in body and "speech" in body
                    assert page.get_by_title("下载 WebVTT 字幕").count() == 1
                    assert page.get_by_role("button", name="朗读").count() == 1
                    report["checks"]["desktop_timeline_and_tts"] = True
                    report["screenshots"].append(shot(page, "01-desktop-offline-speech"))

                    page.reload(wait_until="domcontentloaded", timeout=30_000)
                    page.get_by_test_id("speech-transcript-panel").wait_for(state="visible", timeout=30_000)
                    assert "真实离线转写" in page.get_by_test_id("speech-transcript-panel").inner_text()
                    report["checks"]["refresh_recovery"] = True

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(300)
                    workspace.scroll_into_view_if_needed()
                    geometry = page.evaluate(
                        """() => ({
                          viewport: window.innerWidth,
                          documentWidth: document.documentElement.scrollWidth,
                          panel: (() => {
                            const box = document.querySelector('[data-testid="speech-training-workspace"]')?.getBoundingClientRect()
                            return box ? { x: box.x, width: box.width, right: box.right } : null
                          })()
                        })"""
                    )
                    assert geometry["documentWidth"] <= geometry["viewport"] + 1
                    assert geometry["panel"] and geometry["panel"]["x"] >= 0 and geometry["panel"]["right"] <= 391
                    report["checks"]["mobile_viewport"] = geometry
                    report["screenshots"].append(shot(page, "02-mobile-offline-speech"))
                    report["result"] = "passed"
                except Exception:
                    try:
                        report["screenshots"].append(shot(page, "error"))
                    except Exception:
                        pass
                    raise
                finally:
                    context.close()
                    browser.close()
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target)
                report["checks"]["sqlite_integrity"] = target.execute("PRAGMA integrity_check").fetchone()[0]
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT / "manifest.json").write_text(
            json.dumps({"schema_version": "next.offline-speech-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
