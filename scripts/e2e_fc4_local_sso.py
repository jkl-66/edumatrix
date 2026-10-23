"""Verify the FC4 local SSO mapping, conflict, revocation and recovery journey."""

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
OUTPUT = Path(os.environ.get(
    "EDUMATRIX_E2E_OUTPUT_DIR",
    ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC4-01A" / "browser-e2e",
))
DB_PATH = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_fc4_local_sso_runtime.db"))
EVIDENCE_DB = OUTPUT / "fc4_local_sso_evidence.db"
PORT = int(os.environ.get("EDUMATRIX_E2E_PORT", "8831"))
BASE_URL = f"http://127.0.0.1:{PORT}"
ADMIN_USERNAME = "fc4_sso_admin"
PASSWORD = "FC4-local-sso-e2e-2026!"


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


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
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
    (OUTPUT / "manifest.json").write_text(json.dumps({
        "schema_version": "fc4.local-sso-e2e-manifest.v1", "files": files,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def login(page: Page, username: str, password: str) -> dict[str, Any]:
    response = page.request.post(f"{BASE_URL}/api/auth/login", form={"username": username, "password": password})
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
        "EDUMATRIX_AUTH_SECRET_KEY": "fc4-sso-isolated-secret-2026",
        "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_RELOAD": "0", "EDUMATRIX_HOST": "127.0.0.1", "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
    })
    os.environ.update(env)
    from app.auth import get_password_hash
    from app.database import DBUser, SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        session.add(DBUser(username=ADMIN_USERNAME, hashed_password=get_password_hash(PASSWORD), role="admin", display_name="FC4 身份管理员"))
        session.commit()
    report: dict[str, Any] = {
        "scope": "local OIDC-style provider, assertion preview, role mapping, binding, login, conflict, provider fault, emergency admin, revocation and mobile recovery",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": {}, "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    admin = login(page, ADMIN_USERNAME, PASSWORD)
                    headers = {"Authorization": f"Bearer {admin['access_token']}"}
                    bootstrap_response = page.request.post(f"{BASE_URL}/api/v1/m6/demo/bootstrap", headers=headers)
                    assert bootstrap_response.ok, bootstrap_response.text()
                    bootstrap = bootstrap_response.json()

                    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                    page.evaluate(
                        """([token,username])=>{localStorage.setItem('edumatrix_token',token);localStorage.setItem('edumatrix_role','admin');localStorage.setItem('edumatrix_username',username);localStorage.setItem('edumatrix_display_name','FC4 身份管理员');localStorage.setItem('edumatrix_onboarded','true')}""",
                        [admin["access_token"], ADMIN_USERNAME],
                    )
                    page.goto(f"{BASE_URL}/local-sso", wait_until="networkidle")
                    page.get_by_text("本地模拟 IdP · 冻结合成身份数据", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_role("button", name="创建本地 IdP").click()
                    page.get_by_text("EduMatrix 比赛本地 IdP", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("未连接", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "01-provider-and-assertion"))

                    learner_option = page.locator("select option").filter(has_text="合成学员").first
                    if learner_option.count():
                        page.locator("select").select_option(learner_option.get_attribute("value"))
                    page.get_by_label("subject").fill("synthetic:fc4-learner-001")
                    page.get_by_text("course-mentors", exact=True).click()
                    page.get_by_role("button", name="预览映射").click()
                    page.get_by_text("mentor", exact=True).first.wait_for(state="visible", timeout=20_000)
                    page.get_by_role("button", name="确认绑定并应用角色").click()
                    page.get_by_text("subject 已绑定，组织角色映射已应用", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_role("button", name="模拟登录").click()
                    page.get_by_text("本地模拟登录已接受，已生成短时演示会话", exact=True).wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "02-bound-and-session"))

                    workspace = page.request.get(f"{BASE_URL}/api/v1/local-sso/workspace", headers=headers).json()
                    selected = workspace["selected"]
                    provider = selected["providers"][0]
                    mapping = selected["mappings"][0]
                    second_user = next(item for item in selected["members"] if item["user_public_id"] != mapping["user_public_id"])
                    conflict_response = page.request.post(f"{BASE_URL}/api/v1/local-sso/assertions/bind", headers=headers, data={
                        "organization_id": bootstrap["organization_id"], "provider_id": provider["id"],
                        "assertion_id": "fc4-conflict-assertion", "subject": mapping["external_subject"],
                        "groups": ["learners"], "target_user_public_id": second_user["user_public_id"],
                    })
                    assert conflict_response.status == 409
                    assert conflict_response.json()["detail"]["code"] == "subject_bound_to_another_user"

                    page.get_by_role("button", name="模拟 IdP 故障").click()
                    page.get_by_text("已停用", exact=True).wait_for(state="visible", timeout=20_000)
                    disabled_login = page.request.post(f"{BASE_URL}/api/v1/local-sso/sessions", headers=headers, data={
                        "organization_id": bootstrap["organization_id"], "provider_id": provider["id"],
                        "assertion_id": "fc4-disabled-login", "subject": mapping["external_subject"],
                        "groups": ["course-mentors"],
                    })
                    assert disabled_login.status == 409 and disabled_login.json()["detail"]["code"] == "provider_disabled"
                    page.get_by_role("button", name="启用应急管理员").click()
                    page.get_by_text("应急管理员演示会话已建立，未签发应用访问令牌", exact=True).wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "03-provider-fault-emergency"))

                    page.get_by_role("button", name="恢复 IdP").click()
                    page.get_by_text("运行中", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_role("button", name="撤销").click()
                    page.get_by_text("映射和关联演示会话已撤销", exact=True).wait_for(state="visible", timeout=20_000)
                    revoked_login = page.request.post(f"{BASE_URL}/api/v1/local-sso/sessions", headers=headers, data={
                        "organization_id": bootstrap["organization_id"], "provider_id": provider["id"],
                        "assertion_id": "fc4-revoked-login", "subject": mapping["external_subject"],
                        "groups": ["course-mentors"],
                    })
                    assert revoked_login.status == 403 and revoked_login.json()["detail"]["code"] == "identity_revoked"
                    page.reload(wait_until="networkidle")
                    page.get_by_text("已撤销", exact=True).first.wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "04-revoked-refresh"))

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.reload(wait_until="networkidle")
                    page.get_by_text("本地模拟 IdP · 冻结合成身份数据", exact=True).wait_for(state="visible", timeout=20_000)
                    body_width = page.evaluate("document.documentElement.scrollWidth")
                    viewport_width = page.evaluate("window.innerWidth")
                    assert body_width <= viewport_width
                    report["screenshots"].append(shot(page, "05-mobile-recovery"))

                    final = page.request.get(f"{BASE_URL}/api/v1/local-sso/workspace", headers=headers).json()
                    report["checks"] = {
                        "truthfulness": final["truthfulness"],
                        "organization_id": bootstrap["organization_id"],
                        "provider_status": final["selected"]["providers"][0]["status"],
                        "mapping_status": final["selected"]["mappings"][0]["status"],
                        "session_modes": sorted({row["login_mode"] for row in final["selected"]["sessions"]}),
                        "duplicate_subject_conflict": "subject_bound_to_another_user",
                        "disabled_provider_denied": "provider_disabled",
                        "revoked_identity_denied": "identity_revoked",
                        "refresh_recovered": True,
                        "mobile_viewport": {"width": viewport_width, "document_width": body_width},
                    }
                    assert final["truthfulness"]["real_idp_connected"] is False
                    assert final["truthfulness"]["oidc_saml_conformance_verified"] is False
                    assert final["truthfulness"]["application_access_token_issued"] is False
                    assert final["selected"]["mappings"][0]["status"] == "revoked"
                    assert {"simulated_sso", "emergency_admin"} <= set(report["checks"]["session_modes"])
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
                report.setdefault("checks", {})["sqlite_integrity"] = target.execute("PRAGMA integrity_check").fetchone()[0]
                report["checks"]["schema_migration_048"] = target.execute(
                    "SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_048'"
                ).fetchone()[0] == 1
                report["checks"]["event_count"] = target.execute("SELECT COUNT(*) FROM local_sso_events").fetchone()[0]
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
