"""Run the FC5 local integration judge journey against isolated FastAPI/SQLite/Chrome."""
from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR", ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC5-06A" / "browser-e2e"))
DB = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_fc5_integration_journey_runtime.db"))
PORT = int(os.environ.get("EDUMATRIX_E2E_PORT", "8843"))
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC5-integration-journey-2026!"


def wait_port(expected: bool, timeout: int = 45) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError("integration journey port state timeout")


def auth(page, name: str, role: str) -> dict:
    response = page.request.post(BASE + "/api/auth/register", data={"username": name, "password": PASSWORD, "display_name": name})
    assert response.ok, response.text()
    with sqlite3.connect(DB) as db:
        db.execute("update users set role=? where username=?", (role, name)); db.commit()
    login = page.request.post(BASE + "/api/auth/login", form={"username": name, "password": PASSWORD})
    assert login.ok, login.text()
    return {"username": name, "public_id": response.json()["user_id"], "token": login.json()["access_token"], "headers": {"Authorization": "Bearer " + login.json()["access_token"]}, "role": role}


def post(page, path: str, headers: dict, payload: dict | None = None) -> dict:
    response = page.request.post(BASE + path, headers=headers, data=payload or {})
    assert response.ok, f"{path}: {response.status} {response.text()}"
    return response.json()


def browser_state(page, user: dict) -> None:
    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.evaluate("([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_display_name','FC5 集成旅程管理员');localStorage.setItem('edumatrix_onboarded','true')}", [user["token"], user["username"], user["role"]])


def shot(page, name: str, report: dict) -> None:
    page.screenshot(path=str(OUTPUT / name), full_page=True); report["screenshots"].append(name)


def manifest() -> None:
    files = [{"file": p.name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name != "manifest.json" and not p.name.endswith(("-wal", "-shm"))]
    (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version": "fc5.integration-judge-journey-e2e-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file(): path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(DB) + suffix)
        if path.exists(): path.unlink()
    env = os.environ.copy()
    env.update({"EDUMATRIX_DB_PATH": str(DB), "EDUMATRIX_AUTH_SECRET_KEY": "fc5-integration-isolated-secret", "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_MODEL": "deterministic", "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "", "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0", "EDUMATRIX_HOST": "127.0.0.1", "EDUMATRIX_PORT": str(PORT), "PYTHON_DOTENV_DISABLED": "1", "PYTHONUNBUFFERED": "1"})
    report = {"schema_version": "fc5.integration-judge-journey-e2e.v1", "scope": "local-sso-hr-lms-xapi-webhook-fault-retry-reconciliation", "fixture_boundary": "Frozen synthetic organization, identities and training data; local adapters only; no external network, enterprise conformance or third-party audit claim.", "checks": {}, "screenshots": [], "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    process = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT); wait_port(True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page(); stamp = str(int(time.time()))
                admin = auth(page, f"fc5_integration_admin_{stamp}", "admin")
                outsider = auth(page, f"fc5_integration_outsider_{stamp}", "admin")
                student = auth(page, f"fc5_integration_student_{stamp}", "student")
                bootstrap = post(page, "/api/v1/m6/demo/bootstrap", admin["headers"])
                org_id, learner_id, assignment_id = bootstrap["organization_id"], bootstrap["learner_public_id"], bootstrap["assignment_id"]
                with sqlite3.connect(DB) as db:
                    learner_username = db.execute("select username from users where public_id=?", (learner_id,)).fetchone()[0]

                browser_state(page, admin)
                page.goto(BASE + "/judge-journey/integration", wait_until="networkidle")
                root = page.get_by_test_id("integration-judge-journey")
                root.get_by_text("尚未开始本地集成旅程", exact=True).wait_for(timeout=20_000)
                root.get_by_label("冻结合成组织").select_option(org_id)
                root.get_by_label("冻结合成学员").select_option(learner_id)
                shot(page, "01-empty-frozen-local-boundary.png", report)
                root.get_by_role("button", name="新建集成旅程").click()
                root.get_by_text("0 / 6", exact=True).wait_for(timeout=20_000)
                workspace = page.request.get(BASE + "/api/v1/competition-journeys/integration", headers=admin["headers"]).json(); run = workspace["runs"][0]
                for step in run["steps"]:
                    response = page.request.post(BASE + f"/api/v1/competition-journeys/integration/runs/{run['id']}/visits", headers=admin["headers"], data={"step_key": step["key"], "route": step["route"]})
                    assert response.ok, response.text()
                visited = page.request.get(BASE + f"/api/v1/competition-journeys/integration/runs/{run['id']}", headers=admin["headers"]).json()
                assert visited["progress"]["completed"] == 0 and len(visited["visits"]) == 6

                provider = post(page, "/api/v1/local-sso/providers", admin["headers"], {"organization_id": org_id, "provider_key": "fc5-local-idp", "display_name": "FC5 本地 IdP", "protocol_style": "oidc"})
                assertion = {"organization_id": org_id, "provider_id": provider["id"], "assertion_id": f"fc5-assertion-{stamp}", "subject": f"synthetic:{learner_id}", "groups": ["learners"], "target_user_public_id": learner_id}
                post(page, "/api/v1/local-sso/assertions/preview", admin["headers"], assertion)
                post(page, "/api/v1/local-sso/assertions/bind", admin["headers"], assertion)
                login_payload = {key: value for key, value in assertion.items() if key != "target_user_public_id"}
                post(page, "/api/v1/local-sso/sessions", admin["headers"], login_payload)
                page.reload(wait_until="networkidle"); root = page.get_by_test_id("integration-judge-journey"); root.get_by_text("1 / 6", exact=True).wait_for(); shot(page, "02-sso-one-of-six.png", report)

                mapping = post(page, "/api/v1/local-hr/mappings", admin["headers"], {"organization_id": org_id})
                hr_record = {"employee_no": f"FC5-{stamp}", "name": "冻结合成集成学员", "account": learner_username, "department_name": "智能学习研发部", "job_code": "RAG-ENG", "job_name": "企业 RAG 工程师", "status": "active"}
                preview = post(page, "/api/v1/local-hr/previews", admin["headers"], {"organization_id": org_id, "mapping_version_id": mapping["id"], "source_snapshot_id": f"fc5-hr-{stamp}", "source_sequence": 1, "records": [hr_record]})
                post(page, f"/api/v1/local-hr/batches/{preview['id']}/apply", admin["headers"], {"organization_id": org_id, "expected_lock_version": 1})
                lms = post(page, "/api/v1/local-lms/connections", admin["headers"], {"organization_id": org_id})
                post(page, "/api/v1/local-lms/assignment-exchanges", admin["headers"], {"organization_id": org_id, "connection_id": lms["id"], "training_assignment_id": assignment_id})
                page.reload(wait_until="networkidle"); root = page.get_by_test_id("integration-judge-journey"); root.get_by_text("2 / 6", exact=True).wait_for(); shot(page, "03-hr-lms-two-of-six.png", report)

                cmi5 = post(page, "/api/v1/m7/integrations/cmi5/sessions", admin["headers"], {"organization_id": org_id, "learner_public_id": learner_id, "course_id": None, "launch_key": f"fc5-cmi5-{stamp}"})
                integration_ws = page.request.get(BASE + f"/api/v1/m7/integrations/workspace?organization_id={org_id}", headers=admin["headers"]).json()["selected"]
                xapi_delivery = next(item for item in integration_ws["deliveries"] if item["source_object_id"] == integration_ws["events"][0]["id"] and item["status"] == "pending")
                post(page, f"/api/v1/m7/integrations/deliveries/{xapi_delivery['id']}/local-lrs", admin["headers"])
                endpoint = post(page, "/api/v1/local-webhooks/endpoints", admin["headers"], {"organization_id": org_id})
                event = post(page, "/api/v1/local-webhooks/events", admin["headers"], {"organization_id": org_id, "event_type": "training.assignment.created", "source_object_id": assignment_id})
                webhook_delivery = post(page, "/api/v1/local-webhooks/deliveries", admin["headers"], {"event_id": event["id"], "endpoint_id": endpoint["id"]})
                post(page, f"/api/v1/local-webhooks/deliveries/{webhook_delivery['id']}/send", admin["headers"], {"fault": "none"})
                page.reload(wait_until="networkidle"); root = page.get_by_test_id("integration-judge-journey"); root.get_by_text("3 / 6", exact=True).wait_for(); shot(page, "04-xapi-webhook-three-of-six.png", report)

                drill = post(page, "/api/v1/integration-fault-drills/runs", admin["headers"], {"organization_id": org_id, "run_key": f"fc5-drill-{stamp}"})
                for version in range(1, 8):
                    drill = post(page, f"/api/v1/integration-fault-drills/runs/{drill['id']}/next", admin["headers"], {"expected_lock_version": version})
                assert drill["status"] == "passed" and drill["authority_preserved"] is True
                page.reload(wait_until="networkidle"); root = page.get_by_test_id("integration-judge-journey"); root.get_by_text("5 / 6", exact=True).wait_for(); shot(page, "05-fault-retry-five-of-six.png", report)

                reconciliation_ws = page.request.get(BASE + f"/api/v1/integration-reconciliation/workspace?organization_id={org_id}", headers=admin["headers"]).json()["selected"]
                recon = post(page, "/api/v1/integration-reconciliation/runs", admin["headers"], {"organization_id": org_id, "run_key": f"fc5-recon-{stamp}", "expected_preview_hash": reconciliation_ws["preview"]["preview_hash"]})
                lock = recon["lock_version"]
                for gap in reconciliation_ws["preview"]["discrepancies"]:
                    action = "dismiss" if "dismiss" in gap["repair_actions"] else gap["repair_actions"][0]
                    decision = post(page, f"/api/v1/integration-reconciliation/runs/{recon['id']}/decisions", admin["headers"], {"discrepancy_key": gap["key"], "action": action, "reason": "冻结合成本地演示差异已复核", "expected_lock_version": lock})
                    lock = decision["lock_version"]
                page.reload(wait_until="networkidle"); root = page.get_by_test_id("integration-judge-journey"); root.get_by_text("6 / 6", exact=True).wait_for(); root.get_by_text("六步集成闭环完成", exact=True).wait_for(); shot(page, "06-complete-six-of-six.png", report)
                page.reload(wait_until="networkidle"); root.get_by_text("6 / 6", exact=True).wait_for()
                outsider_workspace = page.request.get(BASE + "/api/v1/competition-journeys/integration", headers=outsider["headers"])
                assert outsider_workspace.status == 200 and outsider_workspace.json()["organizations"] == []
                outsider_run = page.request.get(BASE + f"/api/v1/competition-journeys/integration/runs/{run['id']}", headers=outsider["headers"])
                assert outsider_run.status == 403
                student_workspace = page.request.get(BASE + "/api/v1/competition-journeys/integration", headers=student["headers"])
                assert student_workspace.status == 403
                page.set_viewport_size({"width": 390, "height": 844}); page.wait_for_timeout(500); width = page.evaluate("document.documentElement.scrollWidth"); assert width <= 390; shot(page, "07-mobile-complete.png", report)
                final = page.request.get(BASE + f"/api/v1/competition-journeys/integration/runs/{run['id']}", headers=admin["headers"]).json()
                assert final["status"] == "completed" and final["progress"]["completed"] == 6
                report["checks"].update({"run_id": run["id"], "organization_id": org_id, "learner_public_id": learner_id, "initial_progress": 0, "visit_only_progress": visited["progress"]["completed"], "final_progress": final["progress"]["completed"], "visits": len(final["visits"]), "sso_session": final["steps"][0]["evidence_id"], "hr_lms_evidence": final["steps"][1]["evidence_id"], "xapi_webhook_evidence": final["steps"][2]["evidence_id"], "fault_drill_id": drill["id"], "reconciliation_id": recon["id"], "outsider_workspace_status": outsider_workspace.status, "outsider_organizations": outsider_workspace.json()["organizations"], "outsider_run_status": outsider_run.status, "student_workspace_status": student_workspace.status, "mobile_width": width, "network_sent": final["integration_context"]["network_sent"]})
                report["result"] = "passed"; context.close(); browser.close()
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=20); process.wait(timeout=5); wait_port(False, 15)
        if DB.exists():
            with sqlite3.connect(DB) as source, sqlite3.connect(OUTPUT / "fc5_integration_journey_evidence.db") as target:
                source.backup(target); report["checks"]["sqlite"] = target.execute("pragma integrity_check").fetchone()[0]; report["checks"]["foreign_key_violations"] = len(target.execute("pragma foreign_key_check").fetchall()); report["checks"]["migration_061"] = target.execute("select count(*) from schema_migrations where version='20260805_061'").fetchone()[0]; report["checks"]["integration_runs"] = target.execute("select count(*) from competition_journey_runs where journey_type='integration'").fetchone()[0]; report["checks"]["fault_steps"] = target.execute("select count(*) from integration_fault_drill_steps").fetchone()[0]; report["checks"]["reconciliation_runs"] = target.execute("select count(*) from integration_reconciliation_runs").fetchone()[0]
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z"); (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); manifest()
    print(json.dumps(report, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
