"""Run FC5 unified showcase navigation against isolated FastAPI/SQLite/Chrome."""
from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR", ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC5-07A" / "browser-e2e"))
DB = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_fc5_showcase_runtime.db"))
PORT = int(os.environ.get("EDUMATRIX_E2E_PORT", "8844"))
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC5-showcase-2026!"


def wait_port(expected: bool, timeout: int = 45) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError("showcase port state timeout")


def auth(page, name: str, role: str) -> dict:
    response = page.request.post(BASE + "/api/auth/register", data={"username": name, "password": PASSWORD, "display_name": "FC5 统一演示管理员"})
    assert response.ok, response.text()
    with sqlite3.connect(DB) as db:
        db.execute("update users set role=? where username=?", (role, name)); db.commit()
    login = page.request.post(BASE + "/api/auth/login", form={"username": name, "password": PASSWORD})
    assert login.ok, login.text()
    return {"username": name, "token": login.json()["access_token"], "headers": {"Authorization": "Bearer " + login.json()["access_token"]}, "role": role}


def browser_state(page, user: dict) -> None:
    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.evaluate("([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_display_name','FC5 统一演示管理员');localStorage.setItem('edumatrix_onboarded','true')}", [user["token"], user["username"], user["role"]])


def shot(page, name: str, report: dict) -> None:
    page.screenshot(path=str(OUTPUT / name), full_page=True); report["screenshots"].append(name)


def manifest() -> None:
    files = [{"file": p.name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name != "manifest.json" and not p.name.endswith(("-wal", "-shm"))]
    (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version": "fc5.showcase-e2e-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file(): path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(DB) + suffix)
        if path.exists(): path.unlink()
    env = os.environ.copy()
    env.update({"EDUMATRIX_DB_PATH": str(DB), "EDUMATRIX_AUTH_SECRET_KEY": "fc5-showcase-isolated-secret", "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_MODEL": "deterministic", "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "", "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0", "EDUMATRIX_HOST": "127.0.0.1", "EDUMATRIX_PORT": str(PORT), "PYTHON_DOTENV_DISABLED": "1", "PYTHONUNBUFFERED": "1"})
    report = {"schema_version": "fc5.showcase-e2e.v1", "scope": "unified-navigation-roles-course-organization-job-bootstrap", "fixture_boundary": "Frozen synthetic roles and enterprise context; canonical packaged RAG course; local adapters only; bootstrap creates no journey completion evidence.", "checks": {}, "screenshots": [], "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    process = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT); wait_port(True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page(); stamp = str(int(time.time()))
                admin = auth(page, f"fc5_showcase_admin_{stamp}", "admin")
                student = auth(page, f"fc5_showcase_student_{stamp}", "student")
                browser_state(page, admin)
                page.goto(BASE + "/competition-showcase", wait_until="networkidle")
                root = page.get_by_test_id("competition-showcase")
                root.get_by_text("比赛演示中心", exact=True).wait_for(timeout=20_000)
                initial = page.request.get(BASE + "/api/v1/competition-showcase", headers=admin["headers"]).json()
                assert initial["ready_count"] < 6 and initial["initialized"] is False
                shot(page, "01-before-unified-bootstrap.png", report)
                root.get_by_role("button", name="一键初始化演示数据").click()
                root.get_by_text("6 / 6", exact=True).wait_for(timeout=30_000)
                root.get_by_text("统一演示上下文已创建", exact=True).wait_for(timeout=30_000)
                shot(page, "02-six-journeys-ready.png", report)
                initialized = page.request.get(BASE + "/api/v1/competition-showcase", headers=admin["headers"]).json()
                assert initialized["initialized"] is True and initialized["ready_count"] == 6
                assert all(item["ready"] for item in initialized["journeys"])
                statuses = {}
                for item in initialized["journeys"]:
                    response = page.request.get(BASE + f"/api/v1/competition-journeys/{item['key']}", headers=admin["headers"])
                    statuses[item["key"]] = response.status
                    assert response.status == 200, response.text()
                root.get_by_role("button", name="进入旅程").first.click()
                page.wait_for_url("**/judge-journey/student")
                page.get_by_role("heading", name="学生黄金旅程", exact=True).wait_for(timeout=20_000)
                page.goto(BASE + "/competition-showcase", wait_until="networkidle")
                root = page.get_by_test_id("competition-showcase"); root.get_by_text("6 / 6", exact=True).wait_for()
                with sqlite3.connect(DB) as db:
                    admin_id = db.execute("select public_id from users where username=?", (admin["username"],)).fetchone()[0]
                    run_count = db.execute("select count(*) from competition_journey_runs where owner_public_id=?", (admin_id,)).fetchone()[0]
                assert run_count == 0
                denied = page.request.get(BASE + "/api/v1/competition-showcase", headers=student["headers"])
                assert denied.status == 403
                page.set_viewport_size({"width": 390, "height": 844}); page.wait_for_timeout(500)
                width = page.evaluate("document.documentElement.scrollWidth"); assert width <= 390
                shot(page, "03-mobile-six-journeys-ready.png", report)
                report["checks"].update({"initial_ready_count": initial["ready_count"], "final_ready_count": initialized["ready_count"], "journey_workspace_statuses": statuses, "journey_runs_after_bootstrap": run_count, "student_status": denied.status, "mobile_width": width, "external_network_required": initialized["truthfulness"]["external_network_required"]})
                report["result"] = "passed"; context.close(); browser.close()
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=20); process.wait(timeout=5); wait_port(False, 15)
        if DB.exists():
            with sqlite3.connect(DB) as source, sqlite3.connect(OUTPUT / "fc5_showcase_evidence.db") as target:
                source.backup(target); report["checks"]["sqlite"] = target.execute("pragma integrity_check").fetchone()[0]; report["checks"]["foreign_key_violations"] = len(target.execute("pragma foreign_key_check").fetchall()); report["checks"]["migration_061"] = target.execute("select count(*) from schema_migrations where version='20260805_061'").fetchone()[0]
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z"); (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); manifest()
    print(json.dumps(report, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
