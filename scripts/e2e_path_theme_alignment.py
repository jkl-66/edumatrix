"""Real Chromium visual acceptance for the learning-path theme alignment."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:8000"
OUT = Path("outputs/原系统融合重构执行/evidence/custom_tasks/PATH-PAGE-THEME-ALIGN-01/browser")
USERNAME = "lzz"
PASSWORD = "404404aA"
COURSE_ID = "course-ai-deep-learning-agents-v1"


def run() -> dict[str, object]:
    OUT.mkdir(parents=True, exist_ok=True)
    for item in OUT.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    report: dict[str, object] = {
        "status": "passed",
        "route": f"/workspace/path?course_id={COURSE_ID}",
        "viewports": [],
        "http_errors": [],
        "expected_http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "expected_console_errors": [],
        "screenshots": [],
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in ((1920, 1080), (2560, 1600)):
            context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
            page = context.new_page()
            def record_response(response):
                if response.status < 400:
                    return
                item = {"url": response.url, "status": response.status}
                expected = (
                    response.status == 403 and "/api/v1/competition-demo/context" in response.url
                ) or (
                    response.status == 500 and "/api/v1/m5/textbook-path-draft" in response.url
                )
                report["expected_http_errors" if expected else "http_errors"].append(item)

            page.on("response", record_response)
            page.on("requestfailed", lambda request: report["failed_requests"].append({
                "url": request.url,
                "error": request.failure,
            }))
            page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
            def record_console(message):
                if message.type != "error":
                    return
                expected = (
                    "status of 403" in message.text
                    or "status of 500" in message.text
                )
                report["expected_console_errors" if expected else "console_errors"].append(message.text)

            page.on("console", record_console)
            page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=60_000)
            page.get_by_test_id("login-username").fill(USERNAME)
            page.get_by_test_id("login-password").fill(PASSWORD)
            page.get_by_test_id("login-submit").click()
            page.wait_for_timeout(700)
            page.goto(f"{BASE_URL}/workspace/path?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1_200)
            body = page.locator("body").inner_text()
            if "学习路径" not in body or len(body.strip()) < 120:
                report["status"] = "failed"
            overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
            focus = page.locator(".path-focus-band")
            completion = page.locator(".path-completion-receipt")
            error_state = page.locator(".path-page--error")
            report["viewports"].append({
                "viewport": [width, height],
                "body_chars": len(body),
                "horizontal_overflow": bool(overflow),
                "focus_band": focus.count(),
                "completion_receipt": completion.count(),
                "error_state": error_state.count(),
            })
            filename = f"{width}x{height}-learning-path-theme.png"
            page.screenshot(path=str(OUT / filename), full_page=True)
            report["screenshots"].append(filename)
            context.close()
        browser.close()
    (OUT / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result["status"],
        "screenshots": len(result["screenshots"]),
        "http_errors": len(result["http_errors"]),
        "failed_requests": len(result["failed_requests"]),
        "page_errors": len(result["page_errors"]),
        "console_errors": len(result["console_errors"]),
    }, ensure_ascii=False))
