"""Verify real local video/subtitle import, versioning and recovery in Chromium."""

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
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC1-003" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_fc1_video_imports_e2e.db"
IMPORT_ROOT = ROOT / "outputs" / "_fc1_video_imports_files"
PORT = 8813
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC1-video-imports-2026!"


def wait_port(open_: bool, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError("port state timeout")


def generate_media() -> tuple[Path, Path, Path]:
    # Bundled open-source Chromium reliably decodes VP8, while H.264 support
    # depends on proprietary codecs installed with a browser distribution.
    video = OUTPUT / "probe.webm"
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "lavfi", "-i",
        "color=c=0x17342b:s=640x360:d=1.2", "-vf", "fps=10,format=yuv420p",
        "-c:v", "libvpx", "-b:v", "180k", str(video),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    first = OUTPUT / "lesson-v1.vtt"
    second = OUTPUT / "lesson-v2.vtt"
    first.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nEdge intelligence version one.\n", encoding="utf-8")
    second.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nEdge intelligence version two.\n", encoding="utf-8")
    return video, first, second


def authenticate(page, token: str, username: str) -> None:
    page.goto(BASE_URL + "/login")
    page.evaluate(
        """([token, username]) => {
          localStorage.setItem('edumatrix_token', token);
          localStorage.setItem('edumatrix_role', 'student');
          localStorage.setItem('edumatrix_username', username);
          localStorage.setItem('edumatrix_student_id', username);
          localStorage.setItem('edumatrix_onboarded', 'true');
        }""",
        [token, username],
    )


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    if IMPORT_ROOT.exists():
        shutil.rmtree(IMPORT_ROOT)
    video, subtitle_v1, subtitle_v2 = generate_media()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH), "EDUMATRIX_VIDEO_IMPORT_DIR": str(IMPORT_ROOT),
        "EDUMATRIX_AUTH_SECRET_KEY": "fc1-video-import-e2e", "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic", "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0", "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_PORT": str(PORT), "PYTHONUNBUFFERED": "1", "PYTHON_DOTENV_DISABLED": "1",
    })
    report = {"schema_version": "fc1-003.video-import-browser-e2e.v1", "checks": {}, "screenshots": []}
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN", accept_downloads=True)
                page = context.new_page()
                stamp = str(int(time.time()))
                users = {}
                for role in ("owner", "outsider"):
                    username = f"fc1_import_{role}_{stamp}"
                    result = page.request.post(BASE_URL + "/api/auth/register", data={"username": username, "password": PASSWORD, "display_name": role})
                    assert result.ok
                    users[role] = {"name": username, "token": result.json()["access_token"]}
                    users[role]["headers"] = {"Authorization": "Bearer " + users[role]["token"]}
                authenticate(page, users["owner"]["token"], users["owner"]["name"])
                page.goto(BASE_URL + "/video-imports", wait_until="networkidle")
                root = page.get_by_test_id("video-import-workspace")
                root.get_by_role("heading", name="视频资产导入").wait_for()
                root.get_by_label("视频标题").fill("边缘智能技能视频")
                root.get_by_label("选择视频文件").set_input_files(str(video))
                root.get_by_label("选择字幕文件").set_input_files(str(subtitle_v1))
                root.get_by_role("button", name="导入并固化").click()
                root.get_by_text("导入成功：版本 v1", exact=True).wait_for(timeout=60_000)
                preview = root.get_by_test_id("imported-video-preview")
                preview.wait_for()
                report["checks"]["browser_media_support"] = page.evaluate(
                    """() => ({
                      webm_vp8: document.createElement('video').canPlayType('video/webm; codecs="vp8"'),
                      mp4_h264: document.createElement('video').canPlayType('video/mp4; codecs="avc1.42E01E"')
                    })"""
                )
                page.wait_for_function("el => el.readyState >= 1 && el.duration > 0", arg=preview.element_handle())
                listing = page.request.get(BASE_URL + "/api/v1/video-imports", headers=users["owner"]["headers"]).json()["items"]
                assert len(listing) == 1
                asset = listing[0]
                assert asset["current_version"]["width"] == 640 and asset["current_version"]["height"] == 360
                report["checks"]["first_version"] = {"version": 1, "sha256": asset["current_version"]["source_sha256"], "probe": asset["current_version"]["probe_status"]}
                page.screenshot(path=str(OUTPUT / "01-desktop-imported-video.png"), full_page=True)
                report["screenshots"].append("01-desktop-imported-video.png")

                root.get_by_role("button", name="导入新版本").click()
                root.get_by_label("选择视频文件").set_input_files(str(video))
                root.get_by_label("选择字幕文件").set_input_files(str(subtitle_v2))
                root.get_by_role("button", name="导入并固化").click()
                root.get_by_text("导入成功：版本 v2", exact=True).wait_for(timeout=60_000)
                expect(root.get_by_text("v2 · WEBM", exact=True)).to_be_visible()
                expect(root.get_by_text("v1 · WEBM", exact=True)).to_be_visible()
                detail = page.request.get(BASE_URL + f"/api/v1/video-imports/{asset['id']}", headers=users["owner"]["headers"]).json()
                assert detail["lock_version"] == 2 and len(detail["versions"]) == 2
                denied = page.request.get(BASE_URL + f"/api/v1/video-imports/{asset['id']}", headers=users["outsider"]["headers"])
                assert denied.status == 403
                report["checks"]["version_and_owner"] = {"versions": 2, "lock_version": 2, "outsider": 403}

                with page.expect_download() as download_info:
                    root.get_by_role("button", name="字幕", exact=True).click()
                downloaded = OUTPUT / "downloaded-v2.vtt"
                download_info.value.save_as(downloaded)
                assert "version two" in downloaded.read_text(encoding="utf-8")
                report["checks"]["subtitle_download"] = hashlib.sha256(downloaded.read_bytes()).hexdigest()

                page.reload(wait_until="networkidle")
                root = page.get_by_test_id("video-import-workspace")
                root.get_by_text("当前版本 v2", exact=True).wait_for()
                report["checks"]["refresh_recovery"] = True
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(350)
                width = page.evaluate("document.documentElement.scrollWidth")
                assert width <= 390
                report["checks"]["mobile_scroll_width"] = width
                page.screenshot(path=str(OUTPUT / "02-mobile-video-import.png"), full_page=True)
                report["screenshots"].append("02-mobile-video-import.png")
                context.close(); browser.close()
        report["result"] = "passed"
    finally:
        if backend and backend.poll() is None:
            subprocess.run(["taskkill", "/PID", str(backend.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
            backend.wait(timeout=10); wait_port(False, 20)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(OUTPUT / "video_import_evidence.db") as evidence:
                source.backup(evidence); report["checks"]["sqlite"] = evidence.execute("PRAGMA integrity_check").fetchone()[0]
        report_path = OUTPUT / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{"file": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(OUTPUT.iterdir()) if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))]
        (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version": "fc1-003.video-import-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
