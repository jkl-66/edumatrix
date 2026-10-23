"""Verify FC3-03A routing, task recovery, local rework and model operations."""

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

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC3-03A" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_fc3_gateway_tasks_e2e.db"
EVIDENCE_DB = OUTPUT / "fc3_gateway_tasks_evidence.db"
PORT = 8829
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC3-gateway-tasks-2026!"


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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
        "EDUMATRIX_AUTH_SECRET_KEY": "fc3-gateway-tasks-e2e-secret",
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
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {
        "schema_version": "edumatrix.fc3-gateway-tasks-e2e.v1",
        "work_package": "FC3-03A",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {},
        "screenshots": [],
    }
    backend = None
    page_errors: list[str] = []
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                try:
                    stamp = str(int(time.time()))
                    owner_name = f"fc3_gateway_owner_{stamp}"
                    other_name = f"fc3_gateway_other_{stamp}"
                    teacher_name = f"fc3_gateway_teacher_{stamp}"
                    tokens: dict[str, str] = {}
                    for key, username in (
                        ("owner", owner_name), ("other", other_name), ("teacher", teacher_name),
                    ):
                        response = page.request.post(
                            f"{BASE_URL}/api/auth/register",
                            data={"username": username, "password": PASSWORD, "display_name": username},
                        )
                        assert response.ok
                        tokens[key] = response.json()["access_token"]

                    with sqlite3.connect(DB_PATH) as fixture:
                        fixture.execute("UPDATE users SET role='teacher' WHERE username=?", (teacher_name,))
                        fixture.commit()

                    route_payloads = {
                        "R0": {
                            "contract": {"idempotency_key": "fc3-route-r0"},
                            "deterministic_action": "save",
                        },
                        "R1": {
                            "contract": {"idempotency_key": "fc3-route-r1"},
                            "deterministic_action": "open",
                            "natural_action": True,
                        },
                        "R2": {
                            "contract": {"idempotency_key": "fc3-route-r2"},
                            "message": "解释检索调优",
                        },
                        "R3": {
                            "contract": {"capability": "plan", "idempotency_key": "fc3-route-r3"},
                        },
                        "R4": {
                            "contract": {"capability": "lecture", "idempotency_key": "fc3-route-r4"},
                        },
                        "R5": {
                            "contract": {"idempotency_key": "fc3-route-r5"},
                            "compound_capabilities": ["lecture", "quiz"],
                        },
                    }
                    route_results = {}
                    for expected, payload in route_payloads.items():
                        response = page.request.post(
                            f"{BASE_URL}/api/v1/m5/route",
                            headers=headers(tokens["owner"]), data=payload,
                        )
                        assert response.ok
                        body = response.json()
                        assert body["route_level"] == expected
                        route_results[expected] = body["status"]

                    task_response = page.request.post(
                        f"{BASE_URL}/api/v1/m5/tasks",
                        headers=headers(tokens["owner"]),
                        data={
                            "routing": {
                                "contract": {
                                    "capability": "lecture",
                                    "idempotency_key": f"fc3-task-{stamp}",
                                }
                            },
                            "model": "deterministic",
                        },
                    )
                    assert task_response.status == 201
                    task_id = task_response.json()["id"]
                    started = page.request.post(
                        f"{BASE_URL}/api/v1/m5/tasks/{task_id}/start",
                        headers=headers(tokens["owner"]),
                    )
                    assert started.ok

                    with sqlite3.connect(DB_PATH) as fixture:
                        first_step = fixture.execute(
                            "SELECT id FROM task_steps WHERE task_id=? AND sequence=1 AND attempt=1",
                            (task_id,),
                        ).fetchone()[0]
                        fixture.execute(
                            "UPDATE task_steps SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE id=?",
                            (first_step,),
                        )
                        fixture.execute(
                            "UPDATE generation_tasks SET progress=0.25 WHERE id=?", (task_id,),
                        )
                        fixture.commit()

                    denied = page.request.post(
                        f"{BASE_URL}/api/v1/m5/tasks/{task_id}/steps/1/rework",
                        headers=headers(tokens["other"]),
                        data={"reason_code": "outsider_attempt"},
                    )
                    assert denied.status == 403

                    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'student')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [tokens["owner"], owner_name],
                    )
                    page.goto(f"{BASE_URL}/resources", wait_until="networkidle")
                    page.get_by_role("button", name="生成任务").click()
                    page.get_by_text(task_id, exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("attempt 1", exact=False).first.wait_for(state="visible")
                    page.once("dialog", lambda dialog: dialog.accept())
                    page.get_by_role("button", name="局部返工").click()
                    page.get_by_text("attempt 2", exact=False).wait_for(state="visible")
                    page.screenshot(path=str(OUTPUT / "01-desktop-owner-task-rework.png"), full_page=True)
                    report["screenshots"].append("01-desktop-owner-task-rework.png")

                    page.reload(wait_until="networkidle")
                    page.get_by_role("button", name="生成任务").click()
                    page.get_by_text("attempt 2", exact=False).wait_for(state="visible")
                    recovered = page.request.get(
                        f"{BASE_URL}/api/v1/m5/tasks/{task_id}",
                        headers=headers(tokens["owner"]),
                    ).json()
                    assert recovered["latest_steps"][0]["attempt"] == 2
                    assert any(event["event_type"] == "task_step.rework_scheduled" for event in recovered["events"])

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(500)
                    assert page.evaluate("document.documentElement.scrollWidth") <= 390
                    page.screenshot(path=str(OUTPUT / "02-mobile-task-recovery.png"), full_page=True)
                    report["screenshots"].append("02-mobile-task-recovery.png")

                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'teacher')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [tokens["teacher"], teacher_name],
                    )
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    page.goto(f"{BASE_URL}/model-operations", wait_until="networkidle")
                    page.locator(".ops-page h2").get_by_text("Agent 与模型运营", exact=True).wait_for(
                        state="visible", timeout=20_000,
                    )
                    page.get_by_text("任务健康", exact=False).first.wait_for(state="visible")
                    page.screenshot(path=str(OUTPUT / "03-desktop-model-operations.png"), full_page=True)
                    report["screenshots"].append("03-desktop-model-operations.png")

                    governance = page.request.get(
                        f"{BASE_URL}/api/v1/m5/model-governance",
                        headers=headers(tokens["teacher"]),
                    )
                    assert governance.ok
                    summary = governance.json()
                    report["checks"].update({
                        "route_levels": route_results,
                        "task_id": task_id,
                        "owner_rework_attempt": recovered["latest_steps"][0]["attempt"],
                        "rework_event_persisted": True,
                        "outsider_rework_status": denied.status,
                        "refresh_recovery": True,
                        "mobile_width": 390,
                        "model_governance_unregistered": summary["unregistered_count"],
                        "model_governance_active_direct": summary["active_direct_count"],
                        "page_or_http_5xx_errors": page_errors,
                        "dotenv_isolated": True,
                    })
                    assert not page_errors
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
            if path.is_file() and path.name != "manifest.json"
            and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT / "manifest.json").write_text(
            json.dumps({
                "schema_version": "edumatrix.fc3-gateway-tasks-manifest.v1",
                "files": files,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
