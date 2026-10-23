"""R3-08 UI-only journey for the consolidated learner review center."""

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
OUTPUT = ROOT / "outputs" / "竞品融合重构执行" / "evidence" / "R3-08"
DB = OUTPUT / "r3_08_runtime.db"
PORT = int(os.environ.get("EDUMATRIX_R3_08_PORT", "8899"))
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
    page.on("pageerror", lambda error: report["page_errors"].append({"scope": scope, "error": str(error)}))
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


def screenshot(page: Page, report: dict, name: str) -> None:
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUTPUT / name), full_page=True)
    report["screenshots"].append(name)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB),
        "EDUMATRIX_AUTH_SECRET_KEY": "r3-08-isolated-auth-secret",
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
        "schema_version": "r3-08.review-center-ui-only.v1",
        "screenshots": [], "http_errors": [], "failed_requests": [],
        "console_errors": [], "page_errors": [],
    }
    process = None
    browser = None
    result_code = 1
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
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

                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN", accept_downloads=True)
                page = context.new_page()
                diagnostics(page, report, "student-desktop")
                login(page, 1, "/")
                page.goto(BASE + f"/workspace?course_id={COURSE_ID}&object_id={QUESTION_VERSION_ID}", wait_until="domcontentloaded", timeout=60_000)
                exercise = page.get_by_test_id("learning-object-exercise")
                exercise.wait_for(state="visible", timeout=30_000)
                exercise.locator("input[type=radio]").first.check()
                page.get_by_test_id("workspace-exercise-submit").click()
                page.get_by_test_id("workspace-misconception-decision").wait_for(state="visible", timeout=30_000)
                page.get_by_test_id("workspace-misconception-accept").click()
                page.get_by_text("错因决定已记录", exact=False).wait_for(timeout=30_000)

                page.goto(BASE + "/review", wait_until="domcontentloaded", timeout=60_000)
                page.get_by_role("heading", name="复习中心").wait_for(state="visible", timeout=30_000)
                queue = page.locator(".unified-queue")
                queue.get_by_text("已确认错因", exact=True).wait_for(timeout=30_000)
                queue.get_by_text("SM-2 间隔复习", exact=True).first.wait_for(timeout=30_000)
                report["desktop_queue_text"] = queue.inner_text()
                assert queue.locator("small").filter(has_text="学习者确认").count() >= 1
                assert page.get_by_role("button", name="导出诊疗材料").is_visible()
                report["desktop"] = {
                    "queue_items": queue.locator("article").count(),
                    "misconception_visible": True,
                    "sm2_visible": True,
                    "export_visible": True,
                }
                screenshot(page, report, "01-unified-review-center.png")

                with page.expect_download(timeout=30_000) as download_info:
                    page.get_by_role("button", name="导出诊疗材料").click()
                download = download_info.value
                export_path = OUTPUT / "EduMatrix-复习诊疗材料.md"
                download.save_as(export_path)
                export_text = export_path.read_text(encoding="utf-8")
                assert "复习诊疗材料" in export_text and "题目答案" in export_text
                assert "answer_key" not in export_text and "API Key" in export_text
                report["export"] = {"filename": export_path.name, "bytes": export_path.stat().st_size, "redaction_boundary_visible": True}

                page.goto(BASE + "/wrong-questions?student_id=lzz", wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_function("location.pathname === '/review' && new URLSearchParams(location.search).get('compat') === 'wrong-questions'", timeout=30_000)
                page.goto(BASE + "/revision-calendar", wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_function("location.pathname === '/review' && new URLSearchParams(location.search).get('compat') === 'revision-calendar'", timeout=30_000)
                report["compatibility_redirects"] = ["wrong-questions", "revision-calendar"]

                page.reload(wait_until="domcontentloaded", timeout=60_000)
                page.get_by_role("heading", name="复习中心").wait_for(state="visible", timeout=30_000)
                page.locator(".unified-queue article").first.wait_for(timeout=30_000)
                report["refresh"] = {"queue_restored": True}
                context.close()

                mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, locale="zh-CN")
                mobile = mobile_context.new_page()
                diagnostics(mobile, report, "student-mobile")
                login(mobile, 1, "/")
                mobile.goto(BASE + "/review", wait_until="domcontentloaded", timeout=60_000)
                mobile.get_by_role("heading", name="复习中心").wait_for(timeout=30_000)
                mobile.locator(".unified-queue article").first.wait_for(timeout=30_000)
                overflow = mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                bounds = mobile.locator(".unified-queue").evaluate("element => { const r=element.getBoundingClientRect(); return {left:r.left,right:r.right,viewport:innerWidth} }")
                assert not overflow and bounds["left"] >= 0 and bounds["right"] <= bounds["viewport"]
                report["mobile"] = {"viewport": [390, 844], "horizontal_overflow": overflow, "bounds": bounds}
                screenshot(mobile, report, "02-mobile-review-center.png")
                mobile_context.close()
                browser.close()
                browser = None

        with sqlite3.connect(DB) as connection:
            report["database_audit"] = {
                "integrity": connection.execute("pragma integrity_check").fetchone()[0],
                "foreign_key_violations": len(connection.execute("pragma foreign_key_check").fetchall()),
                "review_plans": connection.execute("select count(*) from review_plans").fetchone()[0],
                "confirmed_misconceptions": connection.execute("select count(*) from misconception_reviews where status in ('accepted','modified','teacher_confirmed')").fetchone()[0],
                "retest_tasks": connection.execute("select count(*) from assessment_retest_tasks").fetchone()[0],
            }
        assert report["database_audit"]["integrity"] == "ok"
        assert report["database_audit"]["foreign_key_violations"] == 0
        assert report["database_audit"]["confirmed_misconceptions"] == 1
        assert report["database_audit"]["retest_tasks"] == 1
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
        for suffix in ("-wal", "-shm"):
            sidecar = DB.with_name(DB.name + suffix)
            for _ in range(30):
                try:
                    sidecar.unlink(missing_ok=True)
                    break
                except PermissionError:
                    time.sleep(0.2)
        report["process_cleanup"] = {
            "service_stopped": process is None or process.poll() is not None,
            "port_released": socket.socket().connect_ex(("127.0.0.1", PORT)) != 0,
            "wal_exists": DB.with_name(DB.name + "-wal").exists(),
            "shm_exists": DB.with_name(DB.name + "-shm").exists(),
        }
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": report.get("result"), "failure": report.get("failure"), "database": report.get("database_audit"), "cleanup": report.get("process_cleanup")}, ensure_ascii=True))
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
