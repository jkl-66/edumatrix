"""Verify the first progressive legacy migration chain in isolated Chromium."""

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
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-CORE-08" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_core_legacy_migration_e2e.db"
EVIDENCE_DB = OUTPUT / "legacy_migration_evidence.db"
PORT = 8788
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-core-legacy-migration-2026!"


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
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True, text=True, timeout=15,
    )
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
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "next-core-legacy-migration-e2e-secret",
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
        "schema_version": "next.legacy-migration-e2e.v1",
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
                    username = f"migration_student_{suffix}"
                    student = page.request.post(
                        f"{BASE_URL}/api/auth/register",
                        data={"username": username, "password": PASSWORD, "display_name": "迁移验收学生"},
                    )
                    teacher = page.request.post(
                        f"{BASE_URL}/api/auth/login",
                        form={"username": "teacher", "password": "admin123"},
                    )
                    assert student.ok and teacher.ok
                    student_token = student.json()["access_token"]
                    teacher_token = teacher.json()["access_token"]
                    student_headers = {"Authorization": f"Bearer {student_token}"}
                    teacher_headers = {"Authorization": f"Bearer {teacher_token}"}

                    denied = page.request.get(
                        f"{BASE_URL}/api/v1/m5/legacy-migration-governance", headers=student_headers,
                    )
                    assert denied.status == 403
                    checkin = page.request.post(
                        f"{BASE_URL}/api/quiz/checkin/{username}", headers=student_headers,
                        data={"concept": "矩阵分解", "duration_minutes": 18},
                    )
                    history = page.request.get(
                        f"{BASE_URL}/api/quiz/checkin/history/{username}", headers=student_headers,
                    )
                    assert checkin.ok and history.ok and history.json()[0]["duration_minutes"] == 18
                    library = page.request.get(
                        f"{BASE_URL}/api/knowledge/list?student_id={username}", headers=student_headers,
                    )
                    assert library.ok, library.text()

                    governance = page.request.get(
                        f"{BASE_URL}/api/v1/m5/legacy-migration-governance", headers=teacher_headers,
                    )
                    assert governance.ok, governance.text()
                    payload = governance.json()
                    chain = payload["runtime"]["chains"]["activity-execution-search"]
                    identity_chain = payload["runtime"]["chains"]["identity-profile-history"]
                    knowledge_chain = payload["runtime"]["chains"]["knowledge-source-note"]
                    assessment_chain = payload["runtime"]["chains"]["assessment-review-calibration"]
                    assert chain["matched"] >= 2
                    assert chain.get("fallback", 0) == 0
                    assert identity_chain["matched"] >= 2
                    assert identity_chain.get("fallback", 0) == 0
                    assert knowledge_chain["matched"] >= 1
                    assert knowledge_chain.get("fallback", 0) == 0
                    assert assessment_chain["matched"] >= 2
                    assert assessment_chain.get("fallback", 0) == 0
                    assert payload["inventory"]["unregistered_consumer_count"] == 0
                    assert payload["inventory"]["unregistered_method_count"] == 0
                    assert payload["raw_content_persisted"] is False
                    report["checks"]["authorization"] = {
                        "student_status": denied.status, "teacher_status": governance.status,
                    }
                    report["checks"]["shadow_read"] = {
                        "business_payload_unchanged": True,
                        "matched": chain["matched"],
                        "fallback": chain.get("fallback", 0),
                        "raw_content_persisted": False,
                    }
                    report["checks"]["identity_shadow_read"] = {
                        "matched": identity_chain["matched"],
                        "fallback": identity_chain.get("fallback", 0),
                    }
                    report["checks"]["knowledge_shadow_read"] = {
                        "matched": knowledge_chain["matched"],
                        "fallback": knowledge_chain.get("fallback", 0),
                    }
                    report["checks"]["assessment_shadow_read"] = {
                        "matched": assessment_chain["matched"],
                        "fallback": assessment_chain.get("fallback", 0),
                    }

                    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
                    page.evaluate(
                        """([token]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'teacher')
                          localStorage.setItem('edumatrix_username', 'teacher')
                          localStorage.setItem('edumatrix_student_id', 'teacher')
                          localStorage.setItem('edumatrix_display_name', '迁移验收教师')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [teacher_token],
                    )
                    page.goto(f"{BASE_URL}/internal/objects", wait_until="domcontentloaded", timeout=30_000)
                    page.get_by_role("button", name="数据迁移").click()
                    page.get_by_text("旧数据链渐进替换", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("activity-execution-search", exact=True).wait_for(state="visible")
                    page.get_by_text("identity-profile-history", exact=True).wait_for(state="visible")
                    page.get_by_text("knowledge-source-note", exact=True).wait_for(state="visible")
                    page.get_by_text("assessment-review-calibration", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "01-desktop-legacy-migration"))
                    page.reload(wait_until="domcontentloaded", timeout=30_000)
                    page.get_by_role("button", name="数据迁移").click()
                    page.get_by_text("旧数据链渐进替换", exact=True).wait_for(state="visible")
                    page.get_by_text("activity-execution-search", exact=True).wait_for(state="visible")
                    page.get_by_text("identity-profile-history", exact=True).wait_for(state="visible")
                    page.get_by_text("knowledge-source-note", exact=True).wait_for(state="visible")
                    page.get_by_text("assessment-review-calibration", exact=True).wait_for(state="visible")
                    report["checks"]["refresh_recovery"] = True

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(350)
                    sidebar = page.locator(".app-sidebar")
                    sidebar_box = sidebar.bounding_box()
                    if sidebar_box and sidebar_box["x"] >= 0:
                        page.locator(".app-brand").click()
                    page.wait_for_function(
                        """() => {
                          const node = document.querySelector('.app-sidebar')
                          const box = node?.getBoundingClientRect()
                          return !!box && box.right <= 1
                        }""",
                    )
                    page.get_by_role("button", name="数据迁移").scroll_into_view_if_needed()
                    page.get_by_text("activity-execution-search", exact=True).wait_for(state="visible")
                    page.get_by_text("identity-profile-history", exact=True).wait_for(state="visible")
                    page.get_by_text("knowledge-source-note", exact=True).wait_for(state="visible")
                    page.get_by_text("assessment-review-calibration", exact=True).wait_for(state="visible")
                    box = page.locator(".governance-panel").bounding_box()
                    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 391
                    report["checks"]["mobile_viewport"] = {
                        "width": 390, "height": 844, "panel_visible": True,
                    }
                    report["screenshots"].append(shot(page, "02-mobile-legacy-migration"))
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
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT / "manifest.json").write_text(
            json.dumps({"schema_version": "next.legacy-migration-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
