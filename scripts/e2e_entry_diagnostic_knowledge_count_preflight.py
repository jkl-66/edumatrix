"""Visual preflight check for AI-course coverage adjustment (no model call)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e_entry_diagnostic_quality as base

from playwright.sync_api import sync_playwright


TASK_DIR = Path("outputs/原系统融合重构执行/evidence/custom_tasks/ENTRY-DIAGNOSTIC-KNOWLEDGE-COUNT-01")
base.EVIDENCE = TASK_DIR
base.OUTPUT_DIR = TASK_DIR / "browser-preflight"
base.DB_PATH = base.OUTPUT_DIR / "entry_diagnostic_preflight.sqlite3"
base.PORT = 8942
base.BASE_URL = f"http://127.0.0.1:{base.PORT}"
base.QUESTION_COUNT = 15
base.USERNAME = "entry_knowledge_preflight_20260905"
base.PASSWORD = "EntryKnowledgePreflight-2026!"


def main() -> int:
    base.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in base.OUTPUT_DIR.iterdir():
        if item.is_file():
            item.unlink()
    report = {
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "visual_checks": {},
        "browser_errors": [],
        "http_errors": [],
    }
    process = None
    formal_db = Path("edumatrix.db")
    before_formal = formal_db.read_bytes() if formal_db.exists() else None
    try:
        env = base.runtime_env()
        base.seed_isolated_database(env)
        with (TASK_DIR / "backend-preflight.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=base.ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            base.wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page(); page.set_default_timeout(60_000)
                base.attach_errors(page, report, "1440x900")
                base.login(page)
                page.goto(f"{base.BASE_URL}/workspace/assessment/entry?course_id={base.COURSE_ID}", wait_until="domcontentloaded", timeout=60_000)
                page.get_by_test_id("diagnostic-overview").wait_for(state="visible", timeout=60_000)
                page.get_by_label("诊断题目数量").select_option("15")
                page.wait_for_function("() => { const b=document.querySelector('[data-testid=\"generate-diagnostic\"]'); return b && !b.disabled; }")
                text = page.get_by_test_id("diagnostic-overview").inner_text()
                report["preflight"] = {
                    "course_id": base.COURSE_ID,
                    "selected_question_count": 15,
                    "shows_adjustment_message": "当前课程知识点较多" in text,
                    "contains_expected_count_20": "20" in text,
                    "contains_knowledge_points_19": "19 个" in text,
                    "body_text": text,
                }
                base.capture(page, report, "1440x900-preflight-adjustment.png", "entry-diagnostic")
                compact = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
                compact_page = compact.new_page(); compact_page.set_default_timeout(60_000)
                base.attach_errors(compact_page, report, "1366x768")
                base.login(compact_page)
                compact_page.goto(f"{base.BASE_URL}/workspace/assessment/entry?course_id={base.COURSE_ID}", wait_until="domcontentloaded", timeout=60_000)
                compact_page.get_by_test_id("diagnostic-overview").wait_for(state="visible", timeout=60_000)
                compact_page.get_by_label("诊断题目数量").select_option("15")
                compact_page.wait_for_function("() => { const b=document.querySelector('[data-testid=\"generate-diagnostic\"]'); return b && !b.disabled; }")
                base.capture(compact_page, report, "1366x768-preflight-adjustment.png", "entry-diagnostic")
                compact.close(); context.close(); browser.close()
        after_formal = formal_db.read_bytes() if formal_db.exists() else None
        report["formal_database_unchanged"] = before_formal == after_formal
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=20)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        report["process_cleanup"] = process is None or process.poll() is not None
        (TASK_DIR / "browser-preflight-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "screenshots": len(report["screenshots"]), "error": report.get("error")}, ensure_ascii=False))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
