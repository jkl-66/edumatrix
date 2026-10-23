"""Verify R3-06 practice grading and feedback through visible UI actions."""

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
OUTPUT = ROOT / "outputs" / "竞品融合重构执行" / "evidence" / "R3-06"
DB = OUTPUT / "r3_06_runtime.db"
PORT = int(os.environ.get("EDUMATRIX_R3_06_PORT", "8897"))
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
    page.on("response", lambda response: report["http_errors"].append({
        "scope": scope, "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "scope": scope, "url": request.url, "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append({
        "scope": scope, "error": str(error),
    }))
    page.on("console", lambda message: report["console_errors"].append({
        "scope": scope, "text": message.text,
    }) if message.type == "error" else None)


def visible_demo_login(page: Page, account_index: int, landing: str) -> None:
    page.goto(BASE + "/login", wait_until="domcontentloaded", timeout=60_000)
    accounts = page.locator(".grid.grid-cols-2.gap-2 button")
    accounts.nth(account_index).wait_for(state="visible", timeout=30_000)
    accounts.nth(account_index).click()
    page.locator("button.w-full").first.click()
    page.wait_for_function("path => location.pathname === path", arg=landing, timeout=30_000)


def open_exercise(page: Page) -> None:
    page.goto(
        BASE + f"/workspace?course_id={COURSE_ID}&object_id={QUESTION_VERSION_ID}",
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    page.get_by_test_id("learning-object-exercise").wait_for(state="visible", timeout=30_000)


def screenshot(page: Page, report: dict, name: str) -> None:
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUTPUT / name), full_page=True)
    report["screenshots"].append(name)


def checkpoint_database() -> None:
    if DB.exists():
        with sqlite3.connect(DB) as connection:
            connection.execute("pragma wal_checkpoint(truncate)").fetchone()
    for suffix in ("-wal", "-shm"):
        sidecar = DB.with_name(DB.name + suffix)
        for attempt in range(20):
            try:
                sidecar.unlink(missing_ok=True)
                break
            except PermissionError:
                if attempt == 19:
                    break
                time.sleep(0.25)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    preserved_logs = {
        "focused-junit.xml", "focused-pytest.log",
        "expanded-junit.xml", "expanded-pytest.log", "vue-build.log",
    }
    for path in OUTPUT.iterdir():
        if path.is_file() and path.name not in preserved_logs:
            path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB),
        "EDUMATRIX_AUTH_SECRET_KEY": "r3-06-isolated-auth-secret",
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
        "schema_version": "r3-06.practice-feedback-ui-only.v1",
        "screenshots": [], "http_errors": [], "failed_requests": [],
        "console_errors": [], "page_errors": [],
    }
    process = None
    browser = None
    result_code = 1
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)

                admin_context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                admin = admin_context.new_page()
                diagnostics(admin, report, "admin-initialize")
                visible_demo_login(admin, 2, "/competition-showcase")
                admin.locator(".summary .primary").click()
                admin.get_by_text("3 / 3", exact=True).wait_for(timeout=30_000)
                admin_context.close()

                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                page.set_default_timeout(20_000)
                diagnostics(page, report, "student-desktop")
                visible_demo_login(page, 1, "/")
                open_exercise(page)
                exercise = page.get_by_test_id("learning-object-exercise")
                assert exercise.locator("input[type=radio]").count() == 2
                assert page.get_by_test_id("workspace-evidence-panel").count() == 1
                screenshot(page, report, "01-exercise-ready.png")

                exercise.locator("input[type=radio]").first.check()
                with page.expect_response(
                    lambda response: response.url.endswith("/api/v1/m5/assessment/attempts") and response.status == 201,
                    timeout=30_000,
                ) as response_info:
                    page.get_by_test_id("workspace-exercise-submit").click()
                attempt_payload = response_info.value.json()
                feedback = page.get_by_test_id("workspace-exercise-feedback")
                feedback.wait_for(state="visible", timeout=30_000)
                assert attempt_payload["correct"] is False
                assert attempt_payload["score"] == 0
                assert feedback.locator("p").inner_text().strip()
                assert feedback.locator("small").inner_text().strip()
                report["attempt"] = {
                    "id": attempt_payload["id"], "correct": attempt_payload["correct"],
                    "score": attempt_payload["score"], "grader_type": attempt_payload["grading"]["grader_type"],
                }
                screenshot(page, report, "02-immediate-feedback.png")

                evidence = page.get_by_test_id("workspace-evidence-panel")
                evidence.locator("summary").click()
                assert evidence.locator(".evidence-source-list article").count() >= 1
                report["source_count"] = evidence.locator(".evidence-source-list article").count()
                screenshot(page, report, "03-canonical-source.png")

                page.reload(wait_until="domcontentloaded", timeout=60_000)
                page.get_by_test_id("learning-object-exercise").wait_for(state="visible", timeout=30_000)
                assert page.get_by_test_id("workspace-exercise-feedback").count() == 0
                assert page.locator("input[type=radio]:checked").count() == 0
                report["refresh"] = {"exercise_restored": True, "stale_feedback_cleared": True}
                context.close()

                relogin_context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                relogin = relogin_context.new_page()
                diagnostics(relogin, report, "student-relogin")
                visible_demo_login(relogin, 1, "/")
                open_exercise(relogin)
                assert relogin.get_by_test_id("workspace-exercise-feedback").count() == 0
                report["relogin"] = {"exercise_restored": True}
                relogin_context.close()

                mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, locale="zh-CN")
                mobile = mobile_context.new_page()
                diagnostics(mobile, report, "student-mobile")
                visible_demo_login(mobile, 1, "/")
                open_exercise(mobile)
                card = mobile.get_by_test_id("learning-object-exercise")
                bounds = card.evaluate("""element => { const rect = element.getBoundingClientRect();
                    return {left: rect.left, right: rect.right, viewport: innerWidth} }""")
                overflow = mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                assert not overflow and bounds["left"] >= 0 and bounds["right"] <= bounds["viewport"]
                report["mobile"] = {"viewport": [390, 844], "bounds": bounds, "horizontal_overflow": overflow}
                screenshot(mobile, report, "04-mobile-exercise.png")
                mobile_context.close()
                browser.close()
                browser = None

        with sqlite3.connect(DB) as connection:
            attempt_id = report["attempt"]["id"]
            report["database_audit"] = {
                "integrity": connection.execute("pragma integrity_check").fetchone()[0],
                "foreign_key_violations": len(connection.execute("pragma foreign_key_check").fetchall()),
                "attempt_count": connection.execute(
                    "select count(*) from assessment_attempts where id=?", (attempt_id,),
                ).fetchone()[0],
                "review_case_count": connection.execute(
                    "select count(*) from assessment_review_cases where attempt_id=?", (attempt_id,),
                ).fetchone()[0],
                "cohort_students": connection.execute(
                    "select count(*) from teaching_class_members where class_id='demo-class-rag-2026-a' and role='student' and status='active'"
                ).fetchone()[0],
            }
        assert report["database_audit"] == {
            "integrity": "ok", "foreign_key_violations": 0,
            "attempt_count": 1, "review_case_count": 0, "cohort_students": 15,
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
            except Exception as exc:
                report.setdefault("cleanup_warnings", []).append(str(exc))
        if process is not None and process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, text=True, timeout=20,
            )
            process.wait(timeout=5)
            wait_port(False, 15)
        checkpoint_database()
        report["process_cleanup"] = {
            "service_stopped": process is None or process.poll() is not None,
            "port_released": socket.socket().connect_ex(("127.0.0.1", PORT)) != 0,
            "wal_exists": DB.with_name(DB.name + "-wal").exists(),
            "shm_exists": DB.with_name(DB.name + "-shm").exists(),
        }
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    print(json.dumps({
        "result": report.get("result"), "failure": report.get("failure"),
        "attempt": report.get("attempt"), "refresh": report.get("refresh"),
        "mobile": report.get("mobile"), "database": report.get("database_audit"),
        "cleanup": report.get("process_cleanup"),
    }, ensure_ascii=True))
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
