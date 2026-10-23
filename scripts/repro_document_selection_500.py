"""Reproduce document text-selection failures against the running EduMatrix app."""
from __future__ import annotations

import json
import time
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "DOCUMENT-SELECTION-500-REPAIR-01"
OUT.mkdir(parents=True, exist_ok=True)


def run() -> dict:
    report = {"status": "running", "base_url": "http://127.0.0.1:5173", "requests": [], "screenshots": [], "errors": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, locale="zh-CN")
        page = context.new_page()
        page.on("console", lambda msg: report["errors"].append({"type": "console", "text": msg.text}) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: report["errors"].append({"type": "page", "text": str(exc)}))
        def on_response(response):
            if "/api/v1/document-reader/selections" in response.url:
                item = {"url": response.url, "method": response.request.method, "status": response.status}
                try:
                    item["body"] = response.text()[:2000]
                except Exception:
                    item["body"] = "<unavailable>"
                report["requests"].append(item)
        page.on("response", on_response)
        login = requests.post(report["base_url"].replace(":5173", ":8000") + "/api/auth/login", data={"username": "lzz", "password": "404404aA"})
        login.raise_for_status()
        identity = login.json()
        token = identity["access_token"]
        outline = requests.get(report["base_url"].replace(":5173", ":8000") + "/api/v1/courses/course-machine-learning-foundations-v1/outline", headers={"Authorization": f"Bearer {token}"})
        outline.raise_for_status()
        item = outline.json()[0]
        await_token = token
        page.goto(report["base_url"] + "/", wait_until="domcontentloaded")
        page.evaluate("data => { localStorage.setItem('edumatrix_token', data.token); localStorage.setItem('edumatrix_username', 'lzz'); localStorage.setItem('edumatrix_display_name', 'lzz'); localStorage.setItem('edumatrix_role', 'student'); localStorage.setItem('edumatrix_student_id', 'lzz'); localStorage.setItem('edumatrix_onboarded', 'true'); }", {"token": await_token})
        page.goto(report["base_url"] + "/knowledge/documents/" + item["source_document_id"] + "?course_id=course-machine-learning-foundations-v1", wait_until="networkidle")
        content = page.locator(".document-content, .course-document-preview").first
        content.wait_for(state="visible", timeout=30000)
        content.evaluate("""
          element => {
            const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
            let node = walker.nextNode()
            while (node && !node.textContent.trim()) node = walker.nextNode()
            if (!node) throw new Error('reader text node not found')
            const range = document.createRange()
            range.setStart(node, 0)
            range.setEnd(node, Math.min(node.textContent.length, 80))
            const selection = window.getSelection()
            selection.removeAllRanges(); selection.addRange(range)
            element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, view: window }))
          }
        """)
        page.get_by_role("toolbar", name="文本选区操作").wait_for(state="visible", timeout=15000)
        report["screenshots"].append(str(OUT / "01-selection-toolbar-1920x1080.png"))
        page.screenshot(path=OUT / "01-selection-toolbar-1920x1080.png", full_page=True)
        page.get_by_role("toolbar", name="文本选区操作").get_by_role("button", name="提问", exact=True).click()
        page.get_by_label("针对选区的问题").fill("请解释选中的内容，并举一个学习中的具体例子。")
        page.get_by_role("button", name="提交问题", exact=True).click()
        page.wait_for_timeout(30000)
        report["screenshots"].append(str(OUT / "02-selection-answer-1920x1080.png"))
        page.screenshot(path=OUT / "02-selection-answer-1920x1080.png", full_page=True)
        context.close(); browser.close()
    report["status"] = "passed" if not any(item["status"] >= 500 for item in report["requests"]) else "reproduced_500"
    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    (OUT / "reproduction_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
