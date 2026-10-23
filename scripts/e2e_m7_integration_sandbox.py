"""Verify the M7 learning-event integration failure and recovery journey."""

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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT = Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR", ROOT / "outputs" / "M7_泛化集成与高级体验" / "evidence" / "integration-sandbox-e2e-20260803"))
DB_PATH = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_m7_integration_e2e_runtime.db"))
EVIDENCE_DB = OUTPUT / "m7_integration_evidence.db"
BASE_URL = "http://127.0.0.1:8774"
ADMIN_USERNAME = "m7_integration_admin"
PASSWORD = "M7-integration-e2e-2026!"


def wait_port(open_: bool, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", 8774)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError("port 8774 state timeout")


def stop(process: subprocess.Popen | None) -> None:
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


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path.name


def write_manifest() -> None:
    files = [
        {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
    ]
    (OUTPUT / "manifest.json").write_text(
        json.dumps(
            {"schema_version": "m7.integration-sandbox-e2e-manifest.v1", "files": files},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def login(page: Page, username: str, password: str) -> dict[str, Any]:
    response = page.request.post(
        f"{BASE_URL}/api/auth/login", form={"username": username, "password": password}
    )
    assert response.ok, response.text()
    return response.json()


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
        "EDUMATRIX_AUTH_SECRET_KEY": "m7-integration-isolated-secret-2026",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": "8774",
        "PYTHONUNBUFFERED": "1",
    })
    os.environ.update(env)
    from app.auth import get_password_hash
    from app.database import DBUser, SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        session.add(DBUser(
            username=ADMIN_USERNAME,
            hashed_password=get_password_hash(PASSWORD),
            role="admin",
            display_name="企业集成管理员",
        ))
        session.commit()
    report: dict[str, Any] = {
        "scope": "formal teacher event to xAPI outbox, failure isolation, idempotent replay, recovery, mobile UI",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {},
        "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen(
                [sys.executable, "run.py"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000}, locale="zh-CN"
                )
                page = context.new_page()
                try:
                    admin = login(page, ADMIN_USERNAME, PASSWORD)
                    headers = {"Authorization": f"Bearer {admin['access_token']}"}
                    bootstrap = page.request.post(
                        f"{BASE_URL}/api/v1/m6/demo/bootstrap", headers=headers
                    ).json()
                    published_response = page.request.post(
                        f"{BASE_URL}/api/v1/m6/teacher/interventions",
                        headers=headers,
                        data={
                            "course_id": "course-rag-engineering-m0",
                            "learner_public_id": bootstrap["learner_public_id"],
                            "idempotency_key": "m7-integration-teacher-plan-v1",
                        },
                    )
                    assert published_response.ok, published_response.text()
                    published = published_response.json()
                    learner = login(
                        page, f"m6_demo_{ADMIN_USERNAME}"[:64], "EduMatrix-M6-Demo"
                    )
                    evidence_response = page.request.post(
                        f"{BASE_URL}/api/v1/m6/teacher/interventions/{published['path_id']}/learner-evidence",
                        headers={"Authorization": f"Bearer {learner['access_token']}"},
                        data={"active_seconds": 1200},
                    )
                    assert evidence_response.ok, evidence_response.text()
                    evidence = evidence_response.json()
                    confirm_response = page.request.post(
                        f"{BASE_URL}/api/v1/m6/teacher/interventions/{published['path_id']}/confirm",
                        headers=headers,
                        data={"learner_event_id": evidence["event_id"]},
                    )
                    assert confirm_response.ok, confirm_response.text()
                    confirmed_event_id = confirm_response.json()["event_id"]

                    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                    page.evaluate(
                        """([token,username])=>{localStorage.setItem('edumatrix_token',token);localStorage.setItem('edumatrix_role','admin');localStorage.setItem('edumatrix_username',username);localStorage.setItem('edumatrix_display_name','企业集成管理员');localStorage.setItem('edumatrix_onboarded','true')}""",
                        [admin["access_token"], ADMIN_USERNAME],
                    )
                    page.goto(f"{BASE_URL}/integration-sandbox", wait_until="networkidle")
                    event_row = page.locator(".event-row").filter(has_text=confirmed_event_id)
                    event_row.wait_for(state="visible", timeout=20_000)
                    page.get_by_text("本地集成模拟 · 冻结合成组织数据", exact=True).wait_for(state="visible")
                    page.get_by_text("本地模拟，不访问网络", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "01-formal-event-ready"))

                    event_row.get_by_role("button", name="映射并入队").click()
                    page.get_by_text("等待发送", exact=True).wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "02-xapi-pending"))
                    workspace = page.request.get(
                        f"{BASE_URL}/api/v1/m7/integrations/workspace",
                        headers=headers,
                    ).json()["selected"]
                    delivery = workspace["deliveries"][0]
                    replay_response = page.request.post(
                        f"{BASE_URL}/api/v1/m7/integrations/deliveries",
                        headers=headers,
                        data={
                            "organization_id": bootstrap["organization_id"],
                            "event_id": confirmed_event_id,
                            "destination_key": "competition-mock-lrs",
                        },
                    )
                    assert replay_response.ok and replay_response.json()["created"] is False

                    page.get_by_role("button", name="模拟 LRS 不可用").click()
                    page.get_by_text("等待重试", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("mock_lrs_unavailable · 本地事件未改变", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "03-failure-isolated"))
                    page.get_by_role("button", name="模拟恢复并送达").click()
                    page.get_by_text("已送达", exact=True).wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "04-recovered-delivered"))

                    final = page.request.get(
                        f"{BASE_URL}/api/v1/m7/integrations/workspace",
                        headers=headers,
                    ).json()["selected"]
                    truth = page.request.get(
                        f"{BASE_URL}/api/v1/m7/integrations/workspace",
                        headers=headers,
                    ).json()["truthfulness"]
                    assert truth["network_sent"] is False
                    assert truth["real_enterprise_connected"] is False
                    assert truth["real_lrs_compatibility_verified"] is False
                    report["checks"]["truthfulness"] = truth
                    final_delivery = final["deliveries"][0]
                    assert final_delivery["status"] == "delivered"
                    assert final_delivery["attempt_count"] == 2
                    assert final["transport"]["network_sent"] is False
                    report["checks"]["formal_chain"] = {
                        "organization_id": bootstrap["organization_id"],
                        "learning_event_id": confirmed_event_id,
                        "delivery_id": delivery["id"],
                        "idempotent_replay_created": False,
                        "final_status": final_delivery["status"],
                        "attempt_count": final_delivery["attempt_count"],
                        "network_sent": final["transport"]["network_sent"],
                    }
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.reload(wait_until="networkidle")
                    page.get_by_text("已送达", exact=True).wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "05-mobile-delivered"))
                    report["checks"]["mobile_viewport"] = {
                        "width": 390, "height": 844, "delivered_visible": True,
                    }
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
                report["checks"]["sqlite_integrity"] = target.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
                event = target.execute(
                    "SELECT event_type, payload FROM learning_events WHERE id = ?",
                    (report.get("checks", {}).get("formal_chain", {}).get("learning_event_id", ""),),
                ).fetchone()
                if event:
                    report["checks"]["persisted_event"] = {
                        "event_type": event[0], "payload_present": bool(event[1]),
                    }
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
