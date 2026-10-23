from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR", ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-GOV-07" / "browser-e2e"))
DB = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_next_job_standard_impact_e2e.db"))
EVIDENCE = OUT / "job_standard_impact_evidence.db"
PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "Job-standard-2026!"


def wait_port(opened: bool, timeout: int = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            current = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if current is opened:
            return
        time.sleep(0.2)
    raise RuntimeError("port timeout")


def stop(process) -> None:
    if process and process.poll() is None:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15)
        process.wait(timeout=5)
        wait_port(False, 15)


def session(page, token: str, username: str, role: str, name: str) -> None:
    page.goto(f"{BASE}/login")
    page.evaluate(
        "([t,u,r,n])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_student_id',u);localStorage.setItem('edumatrix_display_name',n);localStorage.setItem('edumatrix_onboarded','true')}",
        [token, username, role, name],
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in OUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(DB) + suffix)
        if path.exists():
            path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB), "EDUMATRIX_AUTH_SECRET_KEY": "nc-gov-07-e2e",
        "EDUMATRIX_DEMO_MODE": "1", "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic", "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "", "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1", "EDUMATRIX_PORT": str(PORT), "PYTHONUNBUFFERED": "1",
    })
    report = {"schema_version": "next.nc-gov-07-browser-e2e.v1", "checks": {}, "screenshots": []}
    backend = None
    try:
        with (OUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                stamp = str(int(time.time()))
                users = {}
                for key in ("admin", "learner"):
                    username = f"impact_{key}_{stamp}"
                    response = page.request.post(f"{BASE}/api/auth/register", data={"username": username, "password": PASSWORD, "display_name": key})
                    assert response.ok
                    users[key] = {"username": username, "token": response.json()["access_token"]}
                with sqlite3.connect(DB) as db:
                    db.execute("UPDATE users SET role='admin' WHERE username=?", (users["admin"]["username"],))
                    db.commit()
                admin_headers = {"Authorization": f"Bearer {users['admin']['token']}"}
                boot = page.request.post(f"{BASE}/api/v1/m6/demo/bootstrap", headers=admin_headers)
                assert boot.ok, boot.text()
                identity = boot.json()
                organization_id = identity["organization_id"]
                workspace_response = page.request.get(
                    f"{BASE}/api/v1/m6/enterprise/workspace?organization_id={organization_id}", headers=admin_headers,
                )
                source_id = workspace_response.json()["selected"]["assignment"]["standard_snapshot"]["job_level_id"]
                with sqlite3.connect(DB) as db:
                    learner_id = db.execute("SELECT public_id FROM users WHERE username=?", (users["learner"]["username"],)).fetchone()[0]
                    db.execute(
                        "INSERT INTO organization_memberships(id,organization_id,user_public_id,role,status,created_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)",
                        ("impact-e2e-learner-membership", organization_id, learner_id, "learner", "active"),
                    )
                    db.commit()
                learner_headers = {"Authorization": f"Bearer {users['learner']['token']}"}
                denied = page.request.get(
                    f"{BASE}/api/v1/job-standard-impact/workspace?organization_id={organization_id}", headers=learner_headers,
                )
                assert denied.status == 403
                report["checks"]["learner_forbidden"] = 403

                session(page, users["admin"]["token"], users["admin"]["username"], "admin", "岗位标准管理员")
                page.goto(f"{BASE}/job-standard-impact", wait_until="domcontentloaded")
                page.get_by_role("heading", name="岗位标准升级影响与复训调度").wait_for(timeout=20000)
                page.get_by_role("button", name="准备合成升级样例").click()
                target_option = page.get_by_label("目标版本").locator("option").filter(has_text="2026.2")
                target_option.wait_for(state="attached", timeout=20000)
                page.get_by_label("目标版本").select_option(target_option.get_attribute("value"))
                page.get_by_role("button", name="生成冻结影响预览").click()
                page.get_by_text("受影响人员", exact=True).wait_for(timeout=20000)
                preview_hash = page.locator(".title span").inner_text().replace("预览哈希 ", "")
                assert len(preview_hash) == 64
                page.screenshot(path=str(OUT / "01-frozen-impact-preview.png"), full_page=True)
                report["screenshots"].append("01-frozen-impact-preview.png")
                page.get_by_role("button", name="确认影响并安排复训").click()
                page.get_by_text("已完成显式确认和幂等调度", exact=True).wait_for(timeout=20000)
                page.reload(wait_until="domcontentloaded")
                page.get_by_text("已完成显式确认和幂等调度", exact=True).wait_for(timeout=20000)
                page.get_by_role("button", name="刷新岗位标准影响").wait_for(state="visible")
                page.wait_for_timeout(600)
                report["checks"]["admin_flow"] = {"preview_hash_length": 64, "status": "confirmed", "refresh_restored": True}
                page.screenshot(path=str(OUT / "02-confirmed-rescheduling.png"), full_page=True)
                report["screenshots"].append("02-confirmed-rescheduling.png")

                api_workspace = page.request.get(
                    f"{BASE}/api/v1/job-standard-impact/workspace?organization_id={organization_id}", headers=admin_headers,
                ).json()
                preview = api_workspace["previews"][0]
                repeated = page.request.post(
                    f"{BASE}/api/v1/job-standard-impact/previews/{preview['id']}/confirm", headers=admin_headers,
                    data={"preview_hash": preview["preview_hash"], "reason": "重复确认应保持幂等"},
                )
                assert repeated.ok and repeated.json()["created"] is False
                report["checks"]["repeat_confirmation_created"] = False

                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(700)
                scroll_width = page.evaluate("document.documentElement.scrollWidth")
                assert scroll_width <= 390
                page.screenshot(path=str(OUT / "03-mobile-confirmed-impact.png"), full_page=True)
                report["screenshots"].append("03-mobile-confirmed-impact.png")
                report["checks"]["mobile"] = {"scroll_width": scroll_width}
                context.close(); browser.close()
                with sqlite3.connect(DB) as db:
                    counts = {
                        "previews": db.execute("SELECT COUNT(*) FROM job_standard_impact_previews").fetchone()[0],
                        "confirmations": db.execute("SELECT COUNT(*) FROM job_standard_impact_confirmations").fetchone()[0],
                        "retraining_programs": db.execute("SELECT COUNT(*) FROM training_programs WHERE title LIKE '岗位标准升级复训%'").fetchone()[0],
                        "retraining_assignments": db.execute("SELECT COUNT(*) FROM training_assignments WHERE assignment_source='retraining'").fetchone()[0],
                    }
                    assert counts == {"previews": 1, "confirmations": 1, "retraining_programs": 1, "retraining_assignments": 1}
                    report["checks"]["idempotent_counts"] = counts
                report["result"] = "passed"
    except Exception as error:
        report["result"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        stop(backend)
        if DB.exists():
            with sqlite3.connect(DB) as source, sqlite3.connect(EVIDENCE) as destination:
                source.backup(destination)
                report["checks"]["sqlite_integrity"] = destination.execute("PRAGMA integrity_check").fetchone()[0]
        (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)} for path in sorted(OUT.iterdir()) if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))]
        (OUT / "manifest.json").write_text(json.dumps({"schema_version": "next.nc-gov-07-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
