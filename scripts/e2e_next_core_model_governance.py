"""Verify model-call governance API and operator UI in isolated Chromium."""

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
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-CORE-03" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_core_model_governance_e2e.db"
EVIDENCE_DB = OUTPUT / "model_governance_evidence.db"
PORT = 8782
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-core-model-governance-2026!"


def wait_port(open_: bool, timeout: float = 45.0) -> None:
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
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, 15)


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path.name


def digest(path: Path) -> str:
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    return value


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
        "EDUMATRIX_AUTH_SECRET_KEY": "next-core-model-governance-e2e-secret",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {
        "schema_version": "next.model-governance-e2e.v1",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {},
        "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    suffix = str(int(time.time()))
                    student = page.request.post(f"{BASE_URL}/api/auth/register", data={"username": f"gov_student_{suffix}", "password": PASSWORD, "display_name": "治理验收学生"})
                    teacher = page.request.post(
                        f"{BASE_URL}/api/auth/login",
                        form={"username": "teacher", "password": "admin123"},
                    )
                    assert student.ok and teacher.ok
                    student_token = student.json()["access_token"]
                    teacher_token = teacher.json()["access_token"]
                    denied = page.request.get(f"{BASE_URL}/api/v1/m5/model-governance", headers={"Authorization": f"Bearer {student_token}"})
                    assert denied.status == 403

                    # Generate one governed call through the authenticated intent path.
                    page.request.post(
                        f"{BASE_URL}/api/v1/m5/route",
                        headers={"Authorization": f"Bearer {teacher_token}"},
                        data={"contract": {"capability": "answer", "idempotency_key": f"route-{suffix}"}, "message": "解释模型治理"},
                    )
                    payload_response = page.request.get(f"{BASE_URL}/api/v1/m5/model-governance", headers={"Authorization": f"Bearer {teacher_token}"})
                    assert payload_response.ok, payload_response.text()
                    payload = payload_response.json()
                    assert payload["unregistered_count"] == 0
                    assert payload["active_direct_count"] == 0
                    assert payload["migration_required_count"] == 0
                    report["checks"]["authorization"] = {"student_status": denied.status, "teacher_status": payload_response.status}
                    report["checks"]["inventory"] = {key: payload[key] for key in ("total_callsites", "unregistered_count", "active_direct_count", "migration_required_count")}

                    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'teacher')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_display_name', '治理验收教师')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [teacher_token, "teacher"],
                    )
                    page.goto(f"{BASE_URL}/internal/objects", wait_until="domcontentloaded", timeout=30_000)
                    page.get_by_role("button", name="模型调用").click()
                    page.get_by_text("模型调用治理", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("活跃无治理直连", exact=True).wait_for(state="visible")
                    assert page.get_by_text("冻结兼容待迁移", exact=True).is_visible()
                    report["screenshots"].append(shot(page, "01-desktop-model-governance"))
                    page.reload(wait_until="domcontentloaded", timeout=30_000)
                    page.get_by_role("button", name="模型调用").click()
                    page.get_by_text("模型调用治理", exact=True).wait_for(state="visible")
                    report["checks"]["refresh_recovery"] = True

                    page.set_viewport_size({"width": 390, "height": 844})
                    box = page.locator(".governance-panel").bounding_box()
                    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 391
                    report["checks"]["mobile_viewport"] = {"width": 390, "height": 844, "panel_visible": True}
                    report["screenshots"].append(shot(page, "02-mobile-model-governance"))
                    report["result"] = "passed"
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
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version": "next.model-governance-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
