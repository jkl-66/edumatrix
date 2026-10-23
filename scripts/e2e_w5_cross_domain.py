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

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "W5" / "browser-e2e"
DB = ROOT / "outputs" / "_w5_cross_domain_e2e.db"
PORT = 8810
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "W5-cross-domain-2026!"
ROUTES = (
    "/workspace", "/assessment", "/speech-training", "/video-studio",
    "/course-governance", "/model-operations", "/marketplace", "/plugins", "/knowledge",
)


def wait_port(expected_open: bool, timeout: float = 70) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            opened = probe.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected_open:
            return
        time.sleep(0.2)
    raise RuntimeError("w5_port_timeout")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in OUT.glob("*"):
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(DB) + suffix)
        if path.exists():
            path.unlink()

    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB), "EDUMATRIX_AUTH_SECRET_KEY": "w5-cross-domain",
        "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "", "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "", "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0", "EDUMATRIX_PORT": str(PORT), "PYTHONUNBUFFERED": "1",
        "PYTHON_DOTENV_DISABLED": "1",
    })
    report = {"schema_version": "next.w5-cross-domain-e2e.v1", "checks": {}, "screenshots": []}
    backend = None
    failures: list[str] = []
    try:
        with (OUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                page.on("pageerror", lambda error: failures.append(f"pageerror:{error}"))
                page.on("response", lambda response: failures.append(
                    f"http_{response.status}:{response.url}"
                ) if response.status >= 500 else None)
                stamp = str(int(time.time()))
                username = f"w5_admin_{stamp}"
                registered = page.request.post(
                    BASE + "/api/auth/register",
                    data={"username": username, "password": PASSWORD, "display_name": "W5 admin"},
                )
                assert registered.ok
                with sqlite3.connect(DB) as connection:
                    connection.execute(
                        "UPDATE users SET role='admin' WHERE public_id=?",
                        (registered.json()["user_id"],),
                    )
                    connection.commit()
                token = page.request.post(
                    BASE + "/api/auth/login", form={"username": username, "password": PASSWORD},
                ).json()["access_token"]
                page.goto(BASE + "/login")
                page.evaluate(
                    """([token, name]) => {
                        localStorage.setItem('edumatrix_token', token);
                        localStorage.setItem('edumatrix_role', 'admin');
                        localStorage.setItem('edumatrix_username', name);
                        localStorage.setItem('edumatrix_student_id', name);
                        localStorage.setItem('edumatrix_onboarded', 'true');
                    }""",
                    [token, username],
                )

                routes = []
                for route in ROUTES:
                    response = page.goto(BASE + route, wait_until="networkidle")
                    page.wait_for_timeout(250)
                    text = page.locator("body").inner_text().strip()
                    width = page.evaluate("document.documentElement.scrollWidth")
                    assert response and response.status < 500
                    assert page.url.startswith(BASE + route)
                    assert len(text) >= 40
                    assert width <= 1440
                    routes.append({"route": route, "body_chars": len(text), "scroll_width": width})
                page.screenshot(path=str(OUT / "01-desktop-cross-domain-knowledge.png"), full_page=False)
                report["screenshots"].append("01-desktop-cross-domain-knowledge.png")

                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(BASE + "/video-studio", wait_until="networkidle")
                page.wait_for_timeout(500)
                mobile_width = page.evaluate("document.documentElement.scrollWidth")
                assert mobile_width <= 390
                page.screenshot(path=str(OUT / "02-mobile-cross-domain-video.png"), full_page=True)
                report["screenshots"].append("02-mobile-cross-domain-video.png")
                assert not failures, failures
                report["checks"].update({
                    "routes": routes, "route_count": len(routes),
                    "mobile_scroll_width": mobile_width, "page_or_http_5xx_errors": failures,
                    "dotenv_isolated": True,
                })
                context.close()
                browser.close()
                report["result"] = "passed"
    finally:
        if backend and backend.poll() is None:
            subprocess.run(["taskkill", "/PID", str(backend.pid), "/T", "/F"], capture_output=True)
            backend.wait(timeout=10)
            wait_port(False, 20)
        if DB.exists():
            with sqlite3.connect(DB) as source, sqlite3.connect(OUT / "w5_cross_domain_evidence.db") as target:
                source.backup(target)
                report["checks"]["sqlite"] = target.execute("PRAGMA integrity_check").fetchone()[0]
        (OUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        files = []
        for path in sorted(OUT.glob("*")):
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm")):
                files.append({
                    "file": path.name, "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
        (OUT / "manifest.json").write_text(
            json.dumps({"schema_version": "next.w5-cross-domain-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
