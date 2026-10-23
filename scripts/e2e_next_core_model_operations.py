"""Verify versioned pricing, worker lifecycle and operator UI in isolated Chromium."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-CORE-04" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_core_model_operations_e2e.db"
EVIDENCE_DB = OUTPUT / "model_operations_evidence.db"
PORT = 8783
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-core-model-operations-2026!"


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
        "EDUMATRIX_AUTH_SECRET_KEY": "next-core-model-operations-e2e-secret",
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
        "schema_version": "next.model-operations-e2e.v1",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {}, "screenshots": [],
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
                    student = page.request.post(f"{BASE_URL}/api/auth/register", data={
                        "username": f"ops_student_{suffix}", "password": PASSWORD,
                        "display_name": "运营验收学生",
                    })
                    teacher = page.request.post(f"{BASE_URL}/api/auth/login", form={"username": "teacher", "password": "admin123"})
                    assert student.ok and teacher.ok
                    student_token = student.json()["access_token"]
                    teacher_token = teacher.json()["access_token"]
                    denied = page.request.get(f"{BASE_URL}/api/v1/m5/model-operations", headers={"Authorization": f"Bearer {student_token}"})
                    teacher_read = page.request.get(f"{BASE_URL}/api/v1/m5/model-operations", headers={"Authorization": f"Bearer {teacher_token}"})
                    assert denied.status == 403 and teacher_read.ok
                    report["checks"]["authorization"] = {"student_status": denied.status, "teacher_status": teacher_read.status}

                    # The application intentionally seeds no default admin. Elevate only this
                    # isolated synthetic fixture after proving teacher read access.
                    with sqlite3.connect(DB_PATH) as fixture_db:
                        fixture_db.execute("UPDATE users SET role='admin' WHERE username='teacher'")
                        fixture_db.commit()
                    admin_token = teacher_token
                    report["checks"]["synthetic_admin_fixture"] = True

                    price = page.request.post(
                        f"{BASE_URL}/api/v1/m5/model-operations/prices",
                        headers={"Authorization": f"Bearer {admin_token}"},
                        data={
                            "provider": "deterministic", "model": "deterministic",
                            "version": "demo-zero-20260803", "currency": "CNY",
                            "input_cost_per_million": 0, "output_cost_per_million": 0,
                            "source_url": "https://example.invalid/edumatrix-demo-pricing",
                            "source_label": "冻结演示价格：本地确定性模型零外部调用成本",
                            "effective_at": "2026-08-03T08:00:00Z",
                        },
                    )
                    assert price.ok and price.json()["created"] is True
                    task_id = f"task-e2e-{uuid.uuid4().hex}"
                    with sqlite3.connect(DB_PATH) as fixture_db:
                        owner_public_id = fixture_db.execute(
                            "SELECT public_id FROM users WHERE username=?", (f"ops_student_{suffix}",),
                        ).fetchone()[0]
                        fixture_db.execute(
                            """INSERT INTO generation_tasks(
                            id,owner_public_id,trace_id,status,progress,capability,model,idempotency_key,
                            estimated_cost,actual_cost,failure_code,failure_reason,created_at
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                            (
                                task_id, owner_public_id, f"trace-{uuid.uuid4().hex}", "queued", 0,
                                "m5.capability.lecture", "deterministic", f"ops-e2e-{suffix}",
                                0, 0, "", "",
                            ),
                        )
                        fixture_db.commit()
                    report["checks"]["synthetic_queued_task_fixture"] = True
                    claim = page.request.post(
                        f"{BASE_URL}/api/v1/m5/model-operations/workers/claim",
                        headers={"Authorization": f"Bearer {admin_token}"},
                        data={"worker_id": "e2e-local-worker", "lease_seconds": 60},
                    )
                    assert claim.ok and claim.json()["claim"]["task_id"] == task_id
                    payload = page.request.get(f"{BASE_URL}/api/v1/m5/model-operations", headers={"Authorization": f"Bearer {teacher_token}"}).json()
                    assert payload["task_counts"]["running"] == 1
                    assert payload["price_versions"][0]["version"] == "demo-zero-20260803"
                    assert payload["leases"][0]["worker_id"] == "e2e-local-worker"
                    assert payload["model_calls"]["actual_invoice_total"] is None
                    report["checks"]["operations"] = {
                        "task_id": task_id, "running": payload["task_counts"]["running"],
                        "price_version": payload["price_versions"][0]["version"],
                        "lease_status": payload["leases"][0]["status"],
                        "actual_invoice_total": payload["model_calls"]["actual_invoice_total"],
                    }

                    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'teacher')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_display_name', '运营验收教师')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [teacher_token, "teacher"],
                    )
                    page.goto(f"{BASE_URL}/internal/objects", wait_until="domcontentloaded", timeout=30_000)
                    page.get_by_role("button", name="成本与队列").click()
                    page.get_by_text("成本与后台队列", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("冻结演示价格：本地确定性模型零外部调用成本", exact=False).wait_for(state="visible")
                    page.get_by_text("e2e-local-worker", exact=False).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "01-desktop-model-operations"))
                    page.reload(wait_until="domcontentloaded", timeout=30_000)
                    page.get_by_role("button", name="成本与队列").click()
                    page.get_by_text("e2e-local-worker", exact=False).wait_for(state="visible")
                    report["checks"]["refresh_recovery"] = True

                    page.set_viewport_size({"width": 390, "height": 844})
                    box = page.locator(".governance-panel").bounding_box()
                    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 391
                    report["checks"]["mobile_viewport"] = {"width": 390, "height": 844, "panel_visible": True}
                    report["screenshots"].append(shot(page, "02-mobile-model-operations"))
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
        (OUTPUT / "manifest.json").write_text(json.dumps({
            "schema_version": "next.model-operations-manifest.v1", "files": files,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
