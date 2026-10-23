"""Desktop browser acceptance for F3-T05 diagnostic reports and path handoff."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("EDUMATRIX_F3_T05_PORT", "8896"))
BASE_URL = f"http://127.0.0.1:{PORT}"
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f3_t05_diagnostic_report"
DB_PATH = OUTPUT_DIR / "f3_t05_runtime.db"
FIXTURE = json.loads((OUTPUT_DIR / "fixture.json").read_text(encoding="utf-8"))


def attach_errors(page: Page, report: dict[str, Any], scope: str) -> None:
    page.on("pageerror", lambda error: report["browser_errors"].append({
        "scope": scope, "type": "pageerror", "message": str(error),
    }))
    page.on("console", lambda message: report["browser_errors"].append({
        "scope": scope, "type": "console", "message": message.text,
    }) if message.type == "error" else None)
    page.on("requestfailed", lambda request: report["browser_errors"].append({
        "scope": scope, "type": "requestfailed", "url": request.url, "message": str(request.failure),
    }))
    page.on("response", lambda response: report["http_errors"].append({
        "scope": scope, "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)


def page_metrics(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const root = document.querySelector('[data-testid="diagnostic-submitted"]')
          const rendered = (el) => {
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0 &&
              rect.width > 1 && rect.height > 1
          }
          const inViewport = (el) => {
            const rect = el.getBoundingClientRect()
            return rendered(el) && rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight
          }
          const controls = [...root.querySelectorAll('button,a[href],input,textarea,select')].filter(inViewport)
          const collisions = []
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i], b = controls[j]
            if (a.contains(b) || b.contains(a)) continue
            const x = a.getBoundingClientRect(), y = b.getBoundingClientRect()
            const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left)
            const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top)
            if (overlapW > 3 && overlapH > 3) collisions.push([
              (a.innerText || a.getAttribute('aria-label') || a.title || a.tagName).trim().slice(0, 40),
              (b.innerText || b.getAttribute('aria-label') || b.title || b.tagName).trim().slice(0, 40),
            ])
          }
          const clipped = [...root.querySelectorAll('h1,h2,h3,strong,button,label,p,small,dd,span,em')].filter((el) => {
            if (!rendered(el)) return false
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            if (style.textOverflow === 'ellipsis') return false
            if (rect.right > document.documentElement.scrollWidth + 1 || rect.left < -1) return true
            return el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap'
          }).map((el) => ({tag: el.tagName, text: (el.innerText || '').trim().slice(0, 72)}))
          const smallText = [...root.querySelectorAll('*')].filter((el) =>
            rendered(el) && el.children.length === 0 && (el.innerText || '').trim() &&
            Number.parseFloat(getComputedStyle(el).fontSize) < 13.95
          ).map((el) => ({tag: el.tagName, text: el.innerText.trim().slice(0, 56), size: getComputedStyle(el).fontSize})).slice(0, 40)
          const content = document.querySelector('.app-content')
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            contentWidth: content?.scrollWidth || 0,
            contentClientWidth: content?.clientWidth || 0,
            bodyTextLength: (root.innerText || '').trim().length,
            collisions,
            clipped,
            smallText,
          }
        }"""
    )


def capture(page: Page, report: dict[str, Any], name: str) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(250)
    metrics = page_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True)
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    if metrics["documentWidth"] > metrics["viewport"][0] or metrics["contentWidth"] > metrics["contentClientWidth"] + 1:
        raise AssertionError(f"horizontal overflow at {name}: {metrics}")
    if metrics["collisions"]:
        raise AssertionError(f"control collision at {name}: {metrics['collisions']}")
    if metrics["clipped"]:
        raise AssertionError(f"clipped text at {name}: {metrics['clipped']}")
    if metrics["smallText"]:
        raise AssertionError(f"text below 14px at {name}: {metrics['smallText']}")


def login(page: Page) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_test_id("login-username").fill("lzz")
    page.get_by_test_id("login-password").fill("404404aA")
    with page.expect_response(
        lambda response: response.url.endswith("/api/auth/login") and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(rf"{re.escape(BASE_URL)}/(?:$|workspace|profile|onboarding).*"), timeout=30_000)


def diagnostic_url() -> str:
    return (
        f"{BASE_URL}/workspace/assessment?course_id={FIXTURE['courseId']}"
        f"&blueprint_id={FIXTURE['blueprintId']}"
        f"&question_version_id={FIXTURE['questionVersionId']}"
    )


def open_report(page: Page) -> None:
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith(f"/api/v1/diagnostics/sessions/{FIXTURE['sessionId']}/report")
        and response.status == 201,
        timeout=30_000,
    ):
        page.goto(diagnostic_url(), wait_until="domcontentloaded", timeout=30_000)
    page.get_by_test_id("diagnostic-submitted").wait_for(state="visible", timeout=30_000)
    page.get_by_role("heading", name="你的入学诊断结果").wait_for(state="visible", timeout=30_000)


def run_primary_flow(browser, report: dict[str, Any]) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
    page = context.new_page()
    attach_errors(page, report, "1440x900")
    try:
        login(page)
        open_report(page)
        assert page.get_by_text("诊断证据已归档", exact=True).is_visible()
        assert page.get_by_text("高信心盲区", exact=True).is_visible()
        assert page.get_by_text("证据不足显示“未知”，不会补造分数。", exact=True).is_visible()
        capture(page, report, "1440x900-01-report.png")

        unknown = page.locator(".evidence-list article").filter(has_text="证据不足")
        assert unknown.count() == 1
        assert unknown.locator("> button > b").inner_text().strip() == "未知"
        unknown.locator("> button").click()
        unknown.locator(".evidence-detail").wait_for(state="visible", timeout=10_000)
        assert unknown.get_by_text(FIXTURE["unknownPrompt"], exact=True).is_visible()
        capture(page, report, "1440x900-02-unknown-evidence.png")

        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(f"/api/v1/diagnostics/sessions/{FIXTURE['sessionId']}/report")
            and response.status == 201,
            timeout=30_000,
        ):
            page.reload(wait_until="domcontentloaded")
        page.get_by_role("heading", name="你的入学诊断结果").wait_for(state="visible", timeout=30_000)
        report["checks"]["report-reopen"] = {"passed": True}

        page.route(
            f"**/api/v1/diagnostics/sessions/{FIXTURE['sessionId']}/report/path",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({
                    "detail": {"code": "diagnostic_path_generation_failed", "message": "模拟路径生成失败，可单独重试。"}
                }, ensure_ascii=False),
            ),
            times=1,
        )
        page.get_by_role("button", name="生成初始学习路径").click()
        page.get_by_text("模拟路径生成失败，可单独重试。", exact=True).wait_for(state="visible", timeout=15_000)
        assert page.get_by_role("heading", name="你的入学诊断结果").is_visible()
        capture(page, report, "1440x900-03-path-failure.png")

        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(f"/api/v1/diagnostics/sessions/{FIXTURE['sessionId']}/report/path")
            and response.status == 200,
            timeout=30_000,
        ):
            page.get_by_role("button", name="重试生成路径").click()
        page.get_by_role("button", name="确认并进入总学习路径").wait_for(state="visible", timeout=30_000)
        assert page.locator(".path-panel li").count() >= 1
        capture(page, report, "1440x900-04-path-ready.png")

        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(f"/api/v1/diagnostics/sessions/{FIXTURE['sessionId']}/report/path/confirm")
            and response.status == 200,
            timeout=30_000,
        ):
            page.get_by_role("button", name="确认并进入总学习路径").click()
        page.wait_for_url(re.compile(r".*/workspace/path\?.*path_id=.*"), timeout=30_000)
        report["checks"]["path-confirmation"] = {"passed": True, "route": page.url}
    finally:
        context.close()


def run_compact_reopen(browser, report: dict[str, Any]) -> None:
    context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
    page = context.new_page()
    attach_errors(page, report, "1366x768")
    try:
        login(page)
        open_report(page)
        assert page.locator(".path-panel li").count() >= 1
        capture(page, report, "1366x768-01-reopened-report.png")
    finally:
        context.close()


def persistence_evidence(report: dict[str, Any]) -> None:
    with sqlite3.connect(DB_PATH) as db:
        report_rows = db.execute(
            "SELECT id, session_id, profile_snapshot_id, content_hash FROM diagnostic_reports"
        ).fetchall()
        attempts = db.execute(
            "SELECT COUNT(*) FROM assessment_attempts WHERE idempotency_key LIKE ?",
            (f"diagnostic-session:{FIXTURE['sessionId']}:%",),
        ).fetchone()[0]
        paths = db.execute(
            "SELECT lp.id, lp.source_plan_version_id "
            "FROM learning_paths lp "
            "JOIN plan_versions pv ON pv.id=lp.source_plan_version_id "
            "WHERE pv.profile_snapshot_id=(SELECT profile_snapshot_id FROM diagnostic_reports WHERE session_id=?)",
            (FIXTURE["sessionId"],),
        ).fetchall()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    assert len(report_rows) == 1
    assert attempts == 15
    assert len(paths) == 1
    assert integrity == "ok"
    report["checks"]["persistence"] = {
        "reportRows": [list(row) for row in report_rows],
        "formalAttemptCount": attempts,
        "learningPaths": [list(row) for row in paths],
        "integrityCheck": integrity,
    }


def main() -> int:
    report: dict[str, Any] = {
        "schema_version": "f3-t05.diagnostic-report-browser-e2e.v1",
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "database": str(DB_PATH),
        "fixture": FIXTURE,
        "screenshots": [],
        "checks": {},
        "browser_errors": [],
        "http_errors": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            run_primary_flow(browser, report)
            run_compact_reopen(browser, report)
            browser.close()
        persistence_evidence(report)

        expected_http = [
            item for item in report["http_errors"]
            if item["status"] == 503 and item["url"].endswith(f"/api/v1/diagnostics/sessions/{FIXTURE['sessionId']}/report/path")
        ]
        unexpected_http = [item for item in report["http_errors"] if item not in expected_http]
        expected_browser = [
            item for item in report["browser_errors"]
            if (
                item["type"] == "console" and "503 (Service Unavailable)" in item["message"]
            ) or (
                item["type"] == "requestfailed" and "ERR_ABORTED" in item["message"]
            )
        ]
        unexpected_browser = [item for item in report["browser_errors"] if item not in expected_browser]
        if len(expected_http) != 1 or unexpected_http or unexpected_browser:
            raise AssertionError({
                "expected_http": expected_http,
                "unexpected_http": unexpected_http,
                "unexpected_browser": unexpected_browser,
            })
        report["checks"]["expected-path-failure"] = {"httpCount": len(expected_http)}
        report["result"] = "passed"
    except Exception as error:
        report["result"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
