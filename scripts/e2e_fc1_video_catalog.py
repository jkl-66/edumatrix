"""Verify the local-first legal video catalog through the real API and Chromium UI."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC1-002" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_fc1_video_catalog_e2e.db"
PORT = 8812
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC1-video-catalog-2026!"


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


def auth(page, token: str, username: str) -> None:
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

    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "fc1-video-catalog-e2e-secret",
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
        "PYTHON_DOTENV_DISABLED": "1",
    })
    report = {"schema_version": "fc1-002.video-catalog-browser-e2e.v1", "checks": {}, "screenshots": []}
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                stamp = str(int(time.time()))
                username = f"fc1_catalog_{stamp}"
                registered = page.request.post(BASE_URL + "/api/auth/register", data={"username": username, "password": PASSWORD, "display_name": "FC1目录验收"})
                assert registered.ok, registered.text()
                token = page.request.post(BASE_URL + "/api/auth/login", form={"username": username, "password": PASSWORD}).json()["access_token"]
                auth(page, token, username)
                page.goto(BASE_URL + "/video-catalog", wait_until="networkidle")
                root = page.get_by_test_id("video-catalog")
                root.get_by_role("heading", name="合法来源视频目录").wait_for()
                assert root.get_by_test_id("video-catalog-item").count() == 6
                assert root.get_by_text("系统不会下载、镜像或分发第三方视频。", exact=False).is_visible()
                report["checks"]["initial_items"] = root.get_by_test_id("video-catalog-item").count()

                root.get_by_label("按语言筛选").select_option(label="Chinese")
                expect(root.get_by_test_id("video-catalog-item")).to_have_count(1)
                assert root.get_by_text("Bilibili 西瓜书 lecture playlist metadata").is_visible()
                report["checks"]["language_filter"] = "Chinese -> 1"

                root.get_by_label("搜索视频目录").fill("not-a-known-resource")
                page.wait_for_timeout(450)
                root.get_by_text("没有符合条件的来源").wait_for()
                report["checks"]["empty_state"] = True
                root.get_by_label("搜索视频目录").fill("")
                root.get_by_label("按语言筛选").select_option(label="English")
                expect(root.get_by_test_id("video-catalog-item")).to_have_count(5)
                link = root.get_by_role("link", name="在来源页面查看 ML Engineering course video index")
                assert link.get_attribute("target") == "_blank"
                assert link.get_attribute("rel") == "noopener noreferrer"
                report["checks"]["source_link_boundary"] = True

                page.screenshot(path=str(OUTPUT / "01-desktop-video-catalog.png"), full_page=True)
                report["screenshots"].append("01-desktop-video-catalog.png")
                page.reload(wait_until="networkidle")
                root = page.get_by_test_id("video-catalog")
                root.get_by_role("heading", name="合法来源视频目录").wait_for()
                expect(root.get_by_test_id("video-catalog-item")).to_have_count(6)
                report["checks"]["refresh_recovery"] = True

                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(300)
                width = page.evaluate("document.documentElement.scrollWidth")
                assert width <= 390
                report["checks"]["mobile_scroll_width"] = width
                page.screenshot(path=str(OUTPUT / "02-mobile-video-catalog.png"), full_page=True)
                report["screenshots"].append("02-mobile-video-catalog.png")
                context.close()
                browser.close()
        report["result"] = "passed"
    finally:
        if backend and backend.poll() is None:
            subprocess.run(["taskkill", "/PID", str(backend.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
            backend.wait(timeout=10)
            wait_port(False, 20)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(OUTPUT / "catalog_evidence.db") as evidence:
                source.backup(evidence)
                report["checks"]["sqlite"] = evidence.execute("PRAGMA integrity_check").fetchone()[0]
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = []
        for path in sorted(OUTPUT.iterdir()):
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm")):
                files.append({"file": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version": "fc1-002.video-catalog-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
