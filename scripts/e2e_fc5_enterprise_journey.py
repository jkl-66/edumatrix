"""Verify the FC5 enterprise judge journey against an isolated real server."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT = Path(os.environ.get(
    "EDUMATRIX_E2E_OUTPUT_DIR",
    ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC5-04A" / "browser-e2e",
))
DB_PATH = Path(os.environ.get(
    "EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_fc5_enterprise_journey_runtime.db"
))
EVIDENCE_DB = OUTPUT / "fc5_enterprise_journey_evidence.db"
PORT = int(os.environ.get("EDUMATRIX_E2E_PORT", "8841"))
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC5-enterprise-journey-e2e-2026!"
PARAMETERS = {"confidence_threshold": 0.65, "inspection_rate": 80, "buffer_size": 50}


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
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
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
        json.dumps({"schema_version": "fc5.enterprise-judge-journey-e2e-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def register(page: Page, key: str, role: str = "student") -> dict:
    username = f"fc5_enterprise_{key}"
    response = page.request.post(
        f"{BASE}/api/auth/register",
        data={"username": username, "password": PASSWORD, "display_name": f"企业旅程{key}"},
    )
    assert response.ok, response.text()
    public_id = response.json()["user_id"]
    if role != "student":
        with sqlite3.connect(DB_PATH) as db:
            db.execute("UPDATE users SET role=? WHERE public_id=?", (role, public_id))
            db.commit()
    login = page.request.post(
        f"{BASE}/api/auth/login", form={"username": username, "password": PASSWORD}
    )
    assert login.ok, login.text()
    return {
        "username": username,
        "public_id": public_id,
        "token": login.json()["access_token"],
        "headers": {"Authorization": "Bearer " + login.json()["access_token"]},
        "role": role,
    }


def browser_session(page: Page, user: dict) -> None:
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.evaluate(
        """([token,username,role])=>{
          localStorage.setItem('edumatrix_token',token);
          localStorage.setItem('edumatrix_role',role);
          localStorage.setItem('edumatrix_username',username);
          localStorage.setItem('edumatrix_display_name','FC5 企业旅程验收账号');
          localStorage.setItem('edumatrix_onboarded','true');
        }""",
        [user["token"], user["username"], user["role"]],
    )


def adapter_action(page: Page, user: dict, session: dict, action: str, key: str, **extra) -> dict:
    payload = {
        "action": action,
        "expected_lock_version": session["lock_version"],
        "idempotency_key": key,
        "parameters": extra.get("parameters"),
        "fault_type": extra.get("fault_type", "none"),
        "diagnosis": extra.get("diagnosis", ""),
        "recovery_action": extra.get("recovery_action", ""),
    }
    response = page.request.post(
        f"{BASE}/api/v1/local-adapters/{session['id']}/actions",
        headers=user["headers"], data=payload,
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
        "EDUMATRIX_AUTH_SECRET_KEY": "fc5-enterprise-journey-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
    })
    report = {
        "schema_version": "fc5.enterprise-judge-journey-e2e.v1",
        "scope": "Frozen synthetic job standard through formal expiry retraining, with real API evidence and browser refresh/mobile verification.",
        "fixture_boundary": "Organization, learner and job data are frozen synthetic competition data; reviewers are separate demonstration roles; no real enterprise or external expert claim.",
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
                    admin = register(page, "admin", "admin")
                    mentor = register(page, "mentor", "teacher")
                    manager = register(page, "manager", "teacher")
                    bootstrap = page.request.post(
                        f"{BASE}/api/v1/m6/demo/bootstrap", headers=admin["headers"]
                    )
                    assert bootstrap.ok, bootstrap.text()
                    identity = bootstrap.json()
                    org_id = identity["organization_id"]
                    learner_id = identity["learner_public_id"]
                    with sqlite3.connect(DB_PATH) as db:
                        db.executemany(
                            "INSERT INTO organization_memberships(id,organization_id,user_public_id,role,status,created_at) VALUES(?,?,?,?, 'active', CURRENT_TIMESTAMP)",
                            [
                                ("fc5-enterprise-mentor", org_id, mentor["public_id"], "mentor"),
                                ("fc5-enterprise-manager", org_id, manager["public_id"], "manager"),
                            ],
                        )
                        learner_username = db.execute(
                            "SELECT username FROM users WHERE public_id=?", (learner_id,)
                        ).fetchone()[0]
                        db.commit()
                    learner_login = page.request.post(
                        f"{BASE}/api/auth/login",
                        form={"username": learner_username, "password": "EduMatrix-M6-Demo"},
                    )
                    assert learner_login.ok, learner_login.text()
                    learner = {
                        "username": learner_username,
                        "public_id": learner_id,
                        "token": learner_login.json()["access_token"],
                        "headers": {"Authorization": "Bearer " + learner_login.json()["access_token"]},
                        "role": "student",
                    }

                    browser_session(page, admin)
                    page.goto(f"{BASE}/judge-journey/enterprise", wait_until="networkidle")
                    page.get_by_text("尚未开始企业培训旅程", exact=True).wait_for(timeout=20000)
                    page.get_by_label("演示组织").select_option(org_id)
                    page.get_by_label("转岗学员").select_option(learner_id)
                    report["screenshots"].append(shot(page, "01-empty-frozen-synthetic-boundary"))
                    page.get_by_role("button", name="新建培训旅程").click()
                    page.get_by_text("3 / 7", exact=True).wait_for(timeout=20000)
                    report["screenshots"].append(shot(page, "02-frozen-standard-gap-cohort-three-of-seven"))
                    workspace = page.request.get(
                        f"{BASE}/api/v1/competition-journeys/enterprise", headers=admin["headers"]
                    ).json()
                    run = workspace["runs"][0]
                    routes = []
                    for step in run["steps"]:
                        page.goto(f"{BASE}/judge-journey/enterprise", wait_until="networkidle")
                        article = page.locator(".steps article").filter(
                            has=page.locator(".body > span").get_by_text(step["key"], exact=True)
                        )
                        article.get_by_role("button").click()
                        page.wait_for_url(f"**{step['route']}**", timeout=20000)
                        routes.append(step["route"])
                    visited = page.request.get(
                        f"{BASE}/api/v1/competition-journeys/enterprise/runs/{run['id']}",
                        headers=admin["headers"],
                    ).json()
                    assert visited["progress"]["completed"] == 3 and len(visited["visits"]) == 7
                    page.goto(f"{BASE}/judge-journey/enterprise", wait_until="networkidle")
                    page.get_by_text("3 / 7", exact=True).wait_for(timeout=20000)
                    report["screenshots"].append(shot(page, "03-seven-visits-still-three"))

                    created = page.request.post(
                        f"{BASE}/api/v1/local-adapters", headers=learner["headers"],
                        data={"title": "冻结合成岗位本地实操", "adapter_id": "vision-quality-line-v1", "credential_placeholder": "DEMO-LOCAL-ONLY", "parameters": PARAMETERS},
                    )
                    assert created.ok, created.text()
                    session = created.json()
                    session = adapter_action(page, learner, session, "connect", "fc5-connect-01")
                    session = adapter_action(page, learner, session, "run", "fc5-run-01")
                    session = adapter_action(page, learner, session, "submit", "fc5-submit-01")
                    assert session["status"] == "passed" and session["hidden_acceptance"]["passed"]
                    enterprise = page.request.get(
                        f"{BASE}/api/v1/m6/enterprise/workspace",
                        headers=admin["headers"],
                        params={"organization_id": org_id, "learner_public_id": learner_id},
                    ).json()["selected"]
                    evidence_ids = []
                    for item in enterprise["competencies"]:
                        if item["status"] == "satisfied":
                            evidence_ids.extend(entry["id"] for entry in item["evidence"] if entry["result"] == "passed")
                            continue
                        evidence_type = item["required_evidence_types"][0]
                        source_id = session["id"] if evidence_type == "hidden_test" else f"fc5-enterprise-{item['skill_level']}"
                        evidence = page.request.post(
                            f"{BASE}/api/v1/m6/enterprise/evidence", headers=admin["headers"],
                            data={"organization_id": org_id, "learner_public_id": learner_id, "competency_standard_id": item["standard_id"], "evidence_type": evidence_type, "source_object_id": source_id, "result": "passed", "score": 0.93, "hidden_test_result": {"passed": 4, "total": 4} if evidence_type == "hidden_test" else {}},
                        )
                        assert evidence.ok, evidence.text()
                        evidence_ids.append(evidence.json()["id"])

                    review = page.request.post(
                        f"{BASE}/api/v1/multilevel-review/cases", headers=learner["headers"],
                        data={"organization_id": org_id, "object_type": "training_assignment", "object_id": run["enterprise_context"]["assignment_id"], "object_version": run["enterprise_context"]["standard_snapshot_hash"], "evidence_snapshot": {"data_class": "frozen_synthetic_demo", "local_adapter_session_id": session["id"]}},
                    )
                    assert review.ok, review.text()
                    case = review.json()["case"]
                    for reviewer, reason in (
                        (mentor, "一级演示导师检查本地实操证据"),
                        (manager, "二级演示经理复核岗位差距闭环"),
                        (admin, "三级演示管理员完成责任签核"),
                    ):
                        decision = page.request.post(
                            f"{BASE}/api/v1/multilevel-review/cases/{case['id']}/decisions",
                            headers=reviewer["headers"],
                            data={"action": "approve", "reason": reason, "expected_version": case["lock_version"]},
                        )
                        assert decision.ok, decision.text()
                        case = decision.json()
                    assert case["status"] == "signed"
                    page.get_by_role("button", name="刷新企业培训旅程").click()
                    page.get_by_text("5 / 7", exact=True).wait_for(timeout=20000)
                    report["screenshots"].append(shot(page, "04-practical-and-demo-signoff-five-of-seven"))

                    certification = page.request.post(
                        f"{BASE}/api/v1/m6/enterprise/certifications", headers=admin["headers"],
                        data={"organization_id": org_id, "learner_public_id": learner_id, "job_level_id": run["enterprise_context"]["job_level_id"], "evidence_ids": sorted(set(evidence_ids)), "retraining_rule": {"completion_days": 14, "cycle_days": 180}},
                    )
                    assert certification.ok, certification.text()
                    certification_id = certification.json()["id"]
                    page.get_by_role("button", name="刷新企业培训旅程").click()
                    page.get_by_text("6 / 7", exact=True).wait_for(timeout=20000)
                    with sqlite3.connect(DB_PATH) as db:
                        db.execute(
                            "UPDATE certifications SET expires_at=? WHERE id=?",
                            ((datetime.utcnow() - timedelta(seconds=2)).isoformat(sep=" "), certification_id),
                        )
                        db.commit()
                    scanned = page.request.post(
                        f"{BASE}/api/v1/certification-lifecycle/scan", headers=admin["headers"],
                        data={"organization_id": org_id, "upcoming_days": 30},
                    )
                    assert scanned.ok, scanned.text()
                    assert scanned.json()["expired"] == 1 and scanned.json()["retraining_created"] == 1
                    page.get_by_role("button", name="刷新企业培训旅程").click()
                    page.get_by_text("7 / 7", exact=True).wait_for(timeout=20000)
                    page.get_by_text("七步培训闭环完成", exact=True).wait_for()
                    report["screenshots"].append(shot(page, "05-completed-seven-of-seven"))
                    page.reload(wait_until="networkidle")
                    page.get_by_text("7 / 7", exact=True).wait_for(timeout=20000)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.reload(wait_until="networkidle")
                    page.get_by_text("七步培训闭环完成", exact=True).wait_for(timeout=20000)
                    width = page.evaluate("document.documentElement.scrollWidth")
                    assert width <= 390
                    report["screenshots"].append(shot(page, "06-mobile-refresh-recovery"))
                    final = page.request.get(
                        f"{BASE}/api/v1/competition-journeys/enterprise/runs/{run['id']}",
                        headers=admin["headers"],
                    ).json()
                    assert final["status"] == "completed" and final["progress"]["completed"] == 7
                    report["checks"] = {
                        "run_id": run["id"], "organization_id": org_id,
                        "learner_public_id": learner_id, "initial_progress": 3,
                        "progress_after_visits": visited["progress"]["completed"],
                        "visit_count": len(visited["visits"]), "visited_routes": routes,
                        "local_adapter_session_id": session["id"], "signed_review_case_id": case["id"],
                        "progress_after_practical_signoff": 5, "certification_id": certification_id,
                        "progress_after_certification": 6, "expiry_scan": scanned.json(),
                        "final_progress": 7, "final_status": final["status"],
                        "refresh_recovered": True, "mobile": {"width": 390, "document_width": width},
                    }
                    report["result"] = "passed"
                except Exception:
                    try:
                        report["screenshots"].append(shot(page, "error"))
                    except Exception:
                        pass
                    raise
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
                checks["migration_058"] = target.execute("SELECT count(*) FROM schema_migrations WHERE version='20260805_058'").fetchone()[0] == 1
                checks["enterprise_runs"] = target.execute("SELECT count(*) FROM competition_journey_runs WHERE journey_type='enterprise'").fetchone()[0]
                checks["journey_visits"] = target.execute("SELECT count(*) FROM competition_journey_visits").fetchone()[0]
                checks["passed_local_sessions"] = target.execute("SELECT count(*) FROM local_adapter_sessions WHERE status='passed'").fetchone()[0]
                checks["signed_reviews"] = target.execute("SELECT count(*) FROM multilevel_review_cases WHERE status='signed'").fetchone()[0]
                checks["expired_retraining_tasks"] = target.execute("SELECT count(*) FROM retraining_tasks WHERE trigger_type='expired'").fetchone()[0]
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
