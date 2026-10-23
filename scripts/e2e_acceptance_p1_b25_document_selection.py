"""FB-25 isolated browser journey for text selection in paginated knowledge documents."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

import e2e_f7_t02_document_reader as base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B25"


def run() -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = 8998
    runtime = base.base
    runtime.OUTPUT_DIR = OUTPUT_DIR
    runtime.clear_output()
    db_path = OUTPUT_DIR / "p1_b25.sqlite3"
    port = runtime.free_port()
    env = runtime.runtime_env(db_path, port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "p1-b25-isolated-secret"
    env["EDUMATRIX_SANDBOX_MODE"] = "disabled"
    env["EDUMATRIX_UPLOAD_DIR"] = str(OUTPUT_DIR / "uploads")
    fixture = base.seed_fixture(env)
    asset_path = OUTPUT_DIR / "uploads" / "lzz" / "f7-t02-browser-pdf" / "ocr" / "page-1-redacted.png"
    with sqlite3.connect(db_path) as db:
        row = db.execute(
            "SELECT parser_metadata FROM source_documents WHERE id=?",
            (fixture["pdf_source_id"],),
        ).fetchone()
        metadata = json.loads(row[0])
        metadata["ocr"]["pages"][0]["asset_path"] = str(asset_path)
        db.execute(
            "UPDATE source_documents SET parser_metadata=? WHERE id=?",
            (json.dumps(metadata, ensure_ascii=False), fixture["pdf_source_id"]),
        )
        db.commit()
    process = None
    report: dict[str, object] = {
        "schema_version": "acceptance-feedback.p1-b25.browser.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "status": "running",
        "screenshots": [],
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
    }
    try:
        process = runtime.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
                page = context.new_page()
                base.page_diagnostics(page, report)
                runtime.login(page, base_url)
                page.goto(
                    f"{base_url}/knowledge/documents/{fixture['pdf_source_id']}?course_id={fixture['pdf_course_id']}",
                    wait_until="networkidle",
                    timeout=60_000,
                )
                page.locator(".page-frame").wait_for(state="visible")
                regions = page.locator(".page-text-region")
                assert regions.count() > 0
                region = regions.first
                region.evaluate("""
                  element => {
                    const node = element.firstChild
                    const range = document.createRange()
                    range.setStart(node, 0)
                    range.setEnd(node, node.textContent.length)
                    const selection = window.getSelection()
                    selection.removeAllRanges()
                    selection.addRange(range)
                    element.closest('.page-frame').dispatchEvent(new MouseEvent('mouseup', { bubbles: true, view: window }))
                  }
                """)
                toolbar = page.get_by_role("toolbar", name="文本选区操作")
                toolbar.wait_for(state="visible")
                page.get_by_role("tab", name="提问", exact=True).click()
                page.get_by_label("针对选区的问题").fill("这段文字说明了什么？")
                page.get_by_role("button", name="提交问题", exact=True).click()
                page.get_by_text("基于选区的回答", exact=True).wait_for(state="visible")
                answer = page.locator(".answer-result").inner_text()
                assert "仅依据你选中的原文" in answer
                assert "卷积层通过局部感受野提取空间特征" in answer
                screenshot = f"{width}x{height}-paginated-text-selection.png"
                page.screenshot(path=OUTPUT_DIR / screenshot, full_page=True)
                report["screenshots"].append(screenshot)
                context.close()
            browser.close()
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        runtime.stop_service(process, port)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "browser-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
