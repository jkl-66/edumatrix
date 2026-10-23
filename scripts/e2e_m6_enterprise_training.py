"""Verify the M6 enterprise transfer-training journey in an isolated runtime."""

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
OUTPUT = Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR", ROOT / "outputs" / "M6_教学治理与企业培训" / "evidence" / "enterprise-training-e2e-20260803"))
DB_PATH = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_m6_enterprise_training_e2e_runtime.db"))
EVIDENCE_DB = OUTPUT / "m6_enterprise_training_evidence.db"
BASE_URL = "http://127.0.0.1:8772"
ADMIN_USERNAME = "m6_enterprise_admin"
PASSWORD = "M6-enterprise-e2e-2026!"


def wait_port(open_: bool, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", 8772)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port 8772 did not become {'open' if open_ else 'closed'}")


def stop(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, timeout=15)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def shot(page: Page, name: str, *, full_page: bool = False) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
    return path.name


def write_manifest() -> None:
    files = [
        {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
    ]
    (OUTPUT / "manifest.json").write_text(
        json.dumps({"schema_version": "m6.enterprise-training-e2e-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def login(page: Page, username: str, password: str) -> dict[str, Any]:
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        form={"username": username, "password": password},
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
        "EDUMATRIX_AUTH_SECRET_KEY": "m6-enterprise-e2e-isolated-secret-2026",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": "8772",
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
            display_name="企业培训管理员",
        ))
        session.commit()

    report: dict[str, Any] = {
        "scope": "formal job standard, transfer assignment, competency gaps, reviewed evidence, certification, retraining, mobile UI, and learner isolation",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "isolated_database": str(EVIDENCE_DB.relative_to(ROOT)).replace("\\", "/"),
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
                    auth = login(page, ADMIN_USERNAME, PASSWORD)
                    headers = {"Authorization": f"Bearer {auth['access_token']}"}
                    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'admin')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_display_name', '企业培训管理员')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [auth["access_token"], ADMIN_USERNAME],
                    )
                    page.goto(f"{BASE_URL}/enterprise-training", wait_until="networkidle")
                    page.get_by_role("button", name="初始化比赛培训样例").wait_for(state="visible", timeout=20_000)
                    page.get_by_text("冻结合成岗位标准 · 比赛演示数据", exact=True).wait_for(state="visible")
                    page.get_by_text("签核由演示角色执行，不代表真实企业或外部专家认证", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "01-empty-formal-workspace", full_page=True))
                    page.get_by_role("button", name="初始化比赛培训样例").click()
                    page.get_by_text("RAG 应用工程师（独立交付）", exact=True).wait_for(state="visible", timeout=30_000)
                    page.get_by_text("1/3", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "02-transfer-gap-matrix", full_page=True))

                    for label in ("验收通过", "演示角色复核"):
                        page.get_by_role("button", name=label).click()
                        page.get_by_role("button", name=label).wait_for(state="detached", timeout=20_000)
                    page.get_by_text("已达到演示认证门槛", exact=True).wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "03-reviewed-evidence-ready", full_page=True))

                    workspace = page.request.get(f"{BASE_URL}/api/v1/m6/enterprise/workspace", headers=headers).json()["selected"]
                    learner_username = f"m6_demo_{ADMIN_USERNAME}"[:64]
                    learner_auth = login(page, learner_username, "EduMatrix-M6-Demo")
                    first_standard = workspace["competencies"][0]
                    denied = page.request.post(
                        f"{BASE_URL}/api/v1/m6/enterprise/evidence",
                        headers={"Authorization": f"Bearer {learner_auth['access_token']}"},
                        data={
                            "organization_id": workspace["organization_id"],
                            "learner_public_id": workspace["learner"]["public_id"],
                            "competency_standard_id": first_standard["standard_id"],
                            "evidence_type": "artifact",
                            "source_object_id": "learner-self-approval",
                            "result": "passed",
                        },
                    )
                    assert denied.status == 403
                    report["checks"]["learner_self_approval_denied"] = denied.status

                    page.get_by_role("button", name="签发本地演示认证").click()
                    page.get_by_text("本地演示认证已签发", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("Active · 180 天复训", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "04-certified-with-retraining", full_page=True))

                    final = page.request.get(f"{BASE_URL}/api/v1/m6/enterprise/workspace", headers=headers).json()["selected"]
                    report["checks"]["formal_chain"] = {
                        "organization_id": final["organization_id"],
                        "assignment_id": final["assignment"]["id"],
                        "job_standard_version": final["job"]["version"],
                        "required": final["summary"]["required"],
                        "satisfied": final["summary"]["satisfied"],
                        "certifications": len(final["certifications"]),
                        "retraining_cycle_days": final["certifications"][0]["retraining_rule"]["cycle_days"],
                    }
                    assert final["summary"]["certification_ready"] is True
                    assert len(final["certifications"]) == 1

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.reload(wait_until="networkidle")
                    page.get_by_text("本地演示认证已签发", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("冻结合成岗位标准 · 比赛演示数据", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "05-mobile-certified", full_page=True))
                    report["checks"]["mobile_viewport"] = {"width": 390, "height": 844, "certification_visible": True}
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
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as destination:
                source.backup(destination)
                report["checks"]["sqlite_integrity"] = destination.execute("PRAGMA integrity_check").fetchone()[0]
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
