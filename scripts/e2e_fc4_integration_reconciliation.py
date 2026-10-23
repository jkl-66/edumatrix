"""Verify FC4 cross-adapter preview, frozen reconciliation and repair decisions."""
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

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT = Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR", ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC4-06A" / "browser-e2e"))
DB_PATH = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_fc4_reconciliation_runtime.db"))
EVIDENCE_DB = OUTPUT / "fc4_reconciliation_evidence.db"
PORT = int(os.environ.get("EDUMATRIX_E2E_PORT", "8836"))
BASE = f"http://127.0.0.1:{PORT}"
USERNAME = "fc4_reconciliation_admin"
PASSWORD = "FC4-reconciliation-e2e-2026!"


def wait_port(open_: bool, timeout: int = 45) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} state timeout")


def stop(process) -> None:
    if not process or process.poll() is not None:
        return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, 15)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
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
        json.dumps({"schema_version": "fc4.integration-reconciliation-e2e-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def login(page: Page) -> dict:
    response = page.request.post(f"{BASE}/api/auth/login", form={"username": USERNAME, "password": PASSWORD})
    assert response.ok, response.text()
    return response.json()


def post(page: Page, path: str, headers: dict, payload: dict | None = None) -> dict:
    response = page.request.post(f"{BASE}{path}", headers=headers, data=payload or {})
    assert response.ok, f"{path}: {response.status} {response.text()}"
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
        "EDUMATRIX_AUTH_SECRET_KEY": "fc4-reconciliation-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
    })
    os.environ.update(env)
    from app.auth import get_password_hash
    from app.database import DBIntegrationDelivery, DBUser, SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        db.add(DBUser(username=USERNAME, hashed_password=get_password_hash(PASSWORD), role="admin", display_name="FC4 对账管理员"))
        db.commit()

    report = {
        "scope": "read-only five-adapter preview, frozen run, dead-letter requeue, immutable decision, refresh and mobile",
        "fault_injection": "one dead-letter delivery inserted only into the isolated E2E database",
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
                    admin = login(page)
                    headers = {"Authorization": f"Bearer {admin['access_token']}"}
                    bootstrap = post(page, "/api/v1/m6/demo/bootstrap", headers)
                    org_id = bootstrap["organization_id"]
                    post(page, "/api/v1/local-sso/providers", headers, {"organization_id": org_id})
                    post(page, "/api/v1/local-hr/mappings", headers, {"organization_id": org_id})
                    post(page, "/api/v1/local-lms/connections", headers, {"organization_id": org_id})
                    post(page, "/api/v1/local-webhooks/endpoints", headers, {"organization_id": org_id})
                    with SessionLocal() as db:
                        db.add(DBIntegrationDelivery(
                            id="fc4-reconciliation-dead-letter",
                            organization_id=org_id,
                            adapter_type="webhook",
                            adapter_version="v1",
                            destination_key="competition-local-webhook",
                            idempotency_key="fc4-reconciliation-fault",
                            source_object_type="webhook_event",
                            source_object_id="fault-event",
                            payload={"id": "fault-event", "mode": "isolated_e2e_fault"},
                            payload_hash=hashlib.sha256(b"isolated-e2e-fault").hexdigest(),
                            status="dead_letter",
                            attempt_count=5,
                            last_error_code="receiver_temporarily_unavailable",
                        ))
                        db.commit()

                    api_before = page.request.get(f"{BASE}/api/v1/integration-reconciliation/workspace?organization_id={org_id}", headers=headers)
                    assert api_before.ok, api_before.text()
                    initial = api_before.json()
                    assert initial["selected"]["preview"]["write_performed"] is False
                    assert len(initial["selected"]["preview"]["mapping_versions"]) == 5
                    assert not initial["selected"]["runs"]

                    page.goto(f"{BASE}/login", wait_until="networkidle")
                    page.evaluate("""([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','admin');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_display_name','FC4 对账管理员');localStorage.setItem('edumatrix_onboarded','true')}""", [admin["access_token"], USERNAME])
                    page.goto(f"{BASE}/integration-reconciliation", wait_until="networkidle")
                    page.get_by_text("只读 · 尚未写入", exact=True).wait_for(state="visible", timeout=20000)
                    adapter_grid = page.locator(".adapter-grid")
                    for label in ("SSO 身份", "HR 主数据", "LMS 交换", "xAPI / LRS", "签名 Webhook"):
                        adapter_grid.get_by_text(label, exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "01-read-only-five-adapters"))

                    page.get_by_role("button", name="冻结对账运行").click()
                    page.get_by_text("当前预览已冻结为不可变对账运行", exact=True).wait_for(state="visible", timeout=20000)
                    page.get_by_text("处理中", exact=True).wait_for(state="visible")
                    page.locator(".gap-list article").filter(has_text="fc4-reconciliation-dead-letter").wait_for(state="visible")
                    report["screenshots"].append(shot(page, "02-frozen-run-dead-letter"))

                    dead_letter = page.locator(".gap-list article").filter(has_text="fc4-reconciliation-dead-letter")
                    dead_letter.get_by_role("button", name="显式重入队").click()
                    dead_letter.get_by_text("已记录 requeue", exact=True).wait_for(state="visible", timeout=20000)
                    report["screenshots"].append(shot(page, "03-explicit-requeue-decision"))

                    undecided = page.locator(".gap-list article").filter(has=page.get_by_role("button", name="确认差异")).first
                    if undecided.count():
                        undecided.get_by_role("button", name="确认差异").click()
                        page.get_by_text("已记录 acknowledge", exact=True).wait_for(state="visible", timeout=20000)
                    report["screenshots"].append(shot(page, "04-immutable-decisions"))

                    page.reload(wait_until="networkidle")
                    page.get_by_text("已记录 requeue", exact=True).wait_for(state="visible", timeout=20000)
                    final_response = page.request.get(f"{BASE}/api/v1/integration-reconciliation/workspace?organization_id={org_id}", headers=headers)
                    assert final_response.ok, final_response.text()
                    final = final_response.json()["selected"]
                    frozen = final["runs"][0]
                    requeue = next(item for item in frozen["decisions"] if item["action"] == "requeue")
                    assert requeue["after_snapshot"]["status"] == "pending"
                    assert len(requeue["evidence_hash"]) == 64
                    assert frozen["snapshot_hash"] == initial["selected"]["preview"]["preview_hash"]

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.reload(wait_until="networkidle")
                    page.get_by_text("已记录 requeue", exact=True).wait_for(state="visible", timeout=20000)
                    document_width = page.evaluate("document.documentElement.scrollWidth")
                    assert document_width <= 390
                    report["screenshots"].append(shot(page, "05-mobile-refresh-recovery"))
                    report["checks"] = {
                        "organization_id": org_id,
                        "preview_write_performed": initial["selected"]["preview"]["write_performed"],
                        "adapter_keys": sorted(initial["selected"]["preview"]["mapping_versions"].keys()),
                        "initial_run_count": len(initial["selected"]["runs"]),
                        "frozen_snapshot_hash_matches": frozen["snapshot_hash"] == initial["selected"]["preview"]["preview_hash"],
                        "frozen_discrepancy_count": len(frozen["discrepancies"]),
                        "decision_count": len(frozen["decisions"]),
                        "requeue_status": requeue["after_snapshot"]["status"],
                        "requeue_attempt_count_preserved": requeue["after_snapshot"]["attempt_count"],
                        "refresh_recovered": True,
                        "mobile": {"width": 390, "document_width": document_width},
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
                checks = report.setdefault("checks", {})
                checks["sqlite_integrity"] = target.execute("PRAGMA integrity_check").fetchone()[0]
                checks["migration_053"] = target.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_053'").fetchone()[0] == 1
                checks["reconciliation_runs"] = target.execute("SELECT COUNT(*) FROM integration_reconciliation_runs").fetchone()[0]
                checks["repair_decisions"] = target.execute("SELECT COUNT(*) FROM integration_repair_decisions").fetchone()[0]
                checks["pending_requeued_delivery"] = target.execute("SELECT COUNT(*) FROM integration_deliveries WHERE id='fc4-reconciliation-dead-letter' AND status='pending' AND attempt_count=5").fetchone()[0] == 1
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
