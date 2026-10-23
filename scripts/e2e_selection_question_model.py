"""Isolated Chromium acceptance for model-backed document selection answers."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import e2e_f7_t02_document_reader as base
from config import CONFIG


OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "SELECTION-QUESTION-MODEL-01" / "browser"
COURSE_ID = "course-machine-learning-foundations-v1"


def run() -> dict[str, object]:
    base.OUTPUT_DIR = OUTPUT_DIR
    base.base.OUTPUT_DIR = OUTPUT_DIR
    base.COURSE_ID = COURSE_ID
    base.PORT_START = 8998
    base.base.clear_output()
    db_path = OUTPUT_DIR / "selection_question.sqlite3"
    port = base.base.free_port()
    env = base.base.runtime_env(db_path, port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "selection-question-isolated-secret"
    env["EDUMATRIX_UPLOAD_DIR"] = str(OUTPUT_DIR / "uploads")
    # Use the repository's configured provider for this acceptance.  The
    # shared fixture defaults to deterministic mode for fast regression tests;
    # this task specifically verifies the production model boundary.
    configured = {
        "EDUMATRIX_LLM_PROVIDER": CONFIG.llm_provider,
        "EDUMATRIX_LLM_MODEL": CONFIG.llm_model,
        "EDUMATRIX_LLM_API_KEY": CONFIG.llm_api_key,
        "EDUMATRIX_LLM_ENDPOINT": CONFIG.llm_endpoint,
        "EDUMATRIX_LLM_TEMPERATURE": str(CONFIG.llm_temperature),
        "EDUMATRIX_LLM_MAX_TOKENS": str(CONFIG.llm_max_tokens),
        "EDUMATRIX_LLM_TIMEOUT": str(CONFIG.llm_timeout),
        "EDUMATRIX_LLM_THINKING_MODE": CONFIG.llm_thinking_mode,
        "EDUMATRIX_LLM_REASONING_EFFORT": CONFIG.llm_reasoning_effort,
    }
    for key, value in configured.items():
        if value:
            env[key] = value
    env["EDUMATRIX_DEMO_MODE"] = "0"
    fixture = base.seed_fixture(env)
    process = None
    report: dict[str, object] = {
        "schema_version": "selection-question-model.browser.v1",
        "status": "running",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "model_calls": [],
    }
    try:
        process = base.base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
                page = context.new_page()
                base.page_diagnostics(page, report)
                base.base.login(page, base_url)
                base.open_reader(page, base_url, str(fixture["source_id"]), str(fixture["course_id"]))
                # Markdown courses use the controlled preview component; the
                # legacy helper targets the old <pre> reader only.
                content = page.locator(".document-content, .course-document-preview").first
                content.wait_for(state="visible")
                content.evaluate("""
                  element => {
                    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
                    let node = walker.nextNode()
                    while (node && !node.textContent.trim()) node = walker.nextNode()
                    if (!node) throw new Error('reader text node not found')
                    const range = document.createRange()
                    range.setStart(node, 0)
                    range.setEnd(node, Math.min(node.textContent.length, 72))
                    const selection = window.getSelection()
                    selection.removeAllRanges()
                    selection.addRange(range)
                    element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, view: window }))
                  }
                """)
                page.get_by_role("toolbar", name="文本选区操作").wait_for(state="visible")
                page.get_by_role("toolbar", name="文本选区操作").get_by_role("button", name="提问", exact=True).click()
                page.get_by_label("针对选区的问题").fill("请用一个具体例子解释这段内容，并说明学习时最容易误解的地方。")
                page.get_by_role("button", name="提交问题", exact=True).click()
                page.get_by_text("基于选区的回答", exact=True).wait_for(state="visible", timeout=60_000)
                answer = page.locator(".answer-result").inner_text()
                quote = page.locator(".selection-summary").inner_text()
                assert answer.strip(), "selection answer is empty"
                assert answer.strip() != quote.strip(), "selection answer still echoes the selected text"
                assert "当前选区直接给出的依据" not in answer, "legacy concatenation response remains"
                assert len(answer.strip()) >= 120, "model answer is too short for a useful selection explanation"
                assert page.locator(".answer-result .incremental-md-renderer").is_visible()
                screenshot = OUTPUT_DIR / f"{width}x{height}-model-selection-answer.png"
                page.screenshot(path=screenshot, full_page=True)
                report["screenshots"].append(str(screenshot))
                context.close()
            browser.close()

        with sqlite3.connect(db_path) as db:
            rows = db.execute(
                "SELECT provider, model, status, capability, input_summary FROM model_calls "
                "WHERE capability='answer' ORDER BY created_at"
            ).fetchall()
            report["model_calls"] = [
                {"provider": row[0], "model": row[1], "status": row[2], "capability": row[3], "input_summary": json.loads(row[4] or "{}")}
                for row in rows
            ]
            assert rows and all(row[2] == "completed" for row in rows)
            assert all(json.loads(row[4] or "{}").get("operation") == "document_selection_answer" for row in rows)
            report["database"] = {
                "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
                "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
                "selection_count": db.execute("SELECT COUNT(*) FROM document_selections").fetchone()[0],
            }
            assert report["database"]["integrity"] == "ok"
            assert report["database"]["foreign_key_violations"] == 0

        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        base.base.stop_service(process, port)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
