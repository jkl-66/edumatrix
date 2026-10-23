"""R3-07 UI-only journey for learner misconception confirmation and event return."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "竞品融合重构执行" / "evidence" / "R3-07"
DB = OUTPUT / "r3_07_runtime.db"
PORT = int(os.environ.get("EDUMATRIX_R3_07_PORT", "8898"))
BASE = f"http://127.0.0.1:{PORT}"
COURSE_ID = "demo-course-rag-trust-v1"
QUESTION_VERSION_ID = "demo-assessment-lzz-rag-01-q01-v1"


def wait_port(expected: bool, timeout: int = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not become {'open' if expected else 'closed'}")


def diagnostics(page: Page, report: dict, scope: str) -> None:
    page.on("response", lambda response: report["http_errors"].append(
        {"scope": scope, "status": response.status, "url": response.url}
    ) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append(
        {"scope": scope, "url": request.url, "failure": request.failure}
    ) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append(
        {"scope": scope, "error": str(error)}
    ))
    page.on("console", lambda message: report["console_errors"].append(
        {"scope": scope, "text": message.text}
    ) if message.type == "error" else None)


def login(page: Page, account_index: int, landing: str) -> None:
    page.goto(BASE + "/login", wait_until="domcontentloaded", timeout=60_000)
    accounts = page.locator(".grid.grid-cols-2.gap-2 button")
    accounts.nth(account_index).wait_for(state="visible", timeout=30_000)
    accounts.nth(account_index).click()
    page.locator("button.w-full").first.click()
    page.wait_for_function("path => location.pathname === path", arg=landing, timeout=30_000)


def open_exercise(page: Page) -> None:
    page.goto(BASE + f"/workspace?course_id={COURSE_ID}&object_id={QUESTION_VERSION_ID}",
              wait_until="domcontentloaded", timeout=60_000)
    page.get_by_test_id("learning-object-exercise").wait_for(state="visible", timeout=30_000)


def screenshot(page: Page, report: dict, name: str) -> None:
    page.wait_for_timeout(350)
    page.screenshot(path=str(OUTPUT / name), full_page=True)
    report["screenshots"].append(name)


def clean_db() -> None:
    if DB.exists():
        for _ in range(20):
            try:
                with sqlite3.connect(DB, timeout=2) as connection:
                    connection.execute("pragma wal_checkpoint(truncate)")
                break
            except sqlite3.Error:
                time.sleep(0.25)
    for suffix in ("-wal", "-shm"):
        sidecar = DB.with_name(DB.name + suffix)
        for _ in range(20):
            try:
                sidecar.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.25)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB),
        "EDUMATRIX_AUTH_SECRET_KEY": "r3-07-isolated-auth-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_SANDBOX_MODE": "trusted_local",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    report = {
        "schema_version": "r3-07.misconception-feedback-ui-only.v1",
        "screenshots": [], "http_errors": [], "failed_requests": [],
        "console_errors": [], "page_errors": [],
    }
    process = None
    browser = None
    result_code = 1
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                admin_context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                admin = admin_context.new_page()
                diagnostics(admin, report, "admin-initialize")
                login(admin, 2, "/competition-showcase")
                admin.locator(".summary .primary").click()
                admin.get_by_text("3 / 3", exact=True).wait_for(timeout=30_000)
                admin_context.close()

                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                page.set_default_timeout(20_000)
                diagnostics(page, report, "student-desktop")
                login(page, 1, "/")
                open_exercise(page)
                exercise = page.get_by_test_id("learning-object-exercise")
                exercise.locator("input[type=radio]").first.check()
                with page.expect_response(
                    lambda response: response.url.endswith("/api/v1/m5/assessment/attempts") and response.status == 201,
                    timeout=30_000,
                ) as response_info:
                    page.get_by_test_id("workspace-exercise-submit").click()
                attempt = response_info.value.json()
                assert attempt["correct"] is False and attempt["misconception_review"]["status"] == "proposed"
                page.get_by_test_id("workspace-misconception-decision").wait_for(state="visible")
                screenshot(page, report, "01-candidate-awaiting-confirmation.png")

                with page.expect_response(
                    lambda response: "/misconceptions/" in response.url and response.status == 200,
                    timeout=30_000,
                ) as decision_info:
                    page.get_by_test_id("workspace-misconception-modify").click()
                decision = decision_info.value.json()
                assert decision["learning_event"]["evidence_strength"] == "user_declared"
                assert decision["learning_event"]["mastery_changed"] is False
                assert decision["profile_projection"]["updated"] is True
                assert decision["path_projection"]["status"] == "processed"
                assert decision["teacher_evidence"]["learning_event_id"] == decision["learning_event"]["id"]
                report["decision"] = {
                    "status": decision["status"], "category": decision["confirmed_category"],
                    "event_id": decision["learning_event"]["id"],
                    "evidence_strength": decision["learning_event"]["evidence_strength"],
                    "mastery_changed": decision["learning_event"]["mastery_changed"],
                    "path_status": decision["path_projection"]["status"],
                }
                page.get_by_text("错因决定已记录", exact=False).wait_for(timeout=30_000)
                screenshot(page, report, "02-learner-decision-returned.png")

                page.reload(wait_until="domcontentloaded", timeout=60_000)
                page.get_by_test_id("learning-object-exercise").wait_for(state="visible", timeout=30_000)
                page.get_by_test_id("workspace-exercise-feedback").wait_for(state="visible", timeout=30_000)
                assert page.get_by_text("错因决定已记录", exact=False).count() == 1
                report["refresh"] = {"decision_restored": True, "event_id_visible": True}
                context.close()

                mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, locale="zh-CN")
                mobile = mobile_context.new_page()
                diagnostics(mobile, report, "student-mobile")
                login(mobile, 1, "/")
                open_exercise(mobile)
                card = mobile.get_by_test_id("learning-object-exercise")
                bounds = card.evaluate("""element => { const rect = element.getBoundingClientRect();
                    return {left: rect.left, right: rect.right, viewport: innerWidth} }""")
                overflow = mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                assert not overflow and bounds["left"] >= 0 and bounds["right"] <= bounds["viewport"]
                report["mobile"] = {"viewport": [390, 844], "bounds": bounds, "horizontal_overflow": overflow}
                screenshot(mobile, report, "03-mobile-decision-restored.png")
                mobile_context.close()
                browser.close()
                browser = None

        with sqlite3.connect(DB) as connection:
            report["database_audit"] = {
                "integrity": connection.execute("pragma integrity_check").fetchone()[0],
                "foreign_key_violations": len(connection.execute("pragma foreign_key_check").fetchall()),
                "misconception_reviews": connection.execute("select count(*) from misconception_reviews").fetchone()[0],
                "decision_events": connection.execute("select count(*) from learning_events where event_type='misconception_decided'").fetchone()[0],
                "profile_evidence": connection.execute("select count(*) from profile_evidence_items where source_type='misconception_user_statement'").fetchone()[0],
            }
        assert report["database_audit"] == {
            "integrity": "ok", "foreign_key_violations": 0,
            "misconception_reviews": 1, "decision_events": 1, "profile_evidence": 1,
        }
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["page_errors"], report["page_errors"]
        report["result"] = "passed"
        result_code = 0
    except Exception as exc:
        report["result"] = "failed"
        report["failure"] = repr(exc)
        report["traceback"] = traceback.format_exc()
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if process is not None and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
            process.wait(timeout=5)
            wait_port(False, 15)
        cleanup = {
            "service_stopped": process is None or process.poll() is not None,
            "port_released": socket.socket().connect_ex(("127.0.0.1", PORT)) != 0,
            "wal_exists": DB.with_name(DB.name + "-wal").exists(),
            "shm_exists": DB.with_name(DB.name + "-shm").exists(),
        }
        clean_db()
        cleanup["wal_exists"] = DB.with_name(DB.name + "-wal").exists()
        cleanup["shm_exists"] = DB.with_name(DB.name + "-shm").exists()
        report["process_cleanup"] = cleanup
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": report.get("result"), "failure": report.get("failure"),
                      "decision": report.get("decision"), "database": report.get("database_audit"),
                      "cleanup": report.get("process_cleanup")}, ensure_ascii=True))
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
