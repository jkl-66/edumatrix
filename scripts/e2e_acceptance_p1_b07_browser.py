"""Automated desktop browser evidence for FB-07 diagnostic explanations."""

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
EVIDENCE_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "acceptance_feedback" / "P1-B07"
DB_PATH = EVIDENCE_DIR / "P1-B07_browser_runtime.db"
FIXTURE_PATH = EVIDENCE_DIR / "browser_fixture.json"
REPORT_PATH = EVIDENCE_DIR / "fb07_browser_evidence.json"
PORT = int(os.getenv("EDUMATRIX_P1_B07_PORT", "8917"))
BASE_URL = f"http://127.0.0.1:{PORT}"


def attach_errors(page: Page, report: dict[str, Any], scope: str) -> None:
    page.on("pageerror", lambda error: report["browserErrors"].append({
        "scope": scope, "type": "pageerror", "message": str(error),
    }))
    page.on("console", lambda message: report["browserErrors"].append({
        "scope": scope, "type": "console", "message": message.text,
    }) if message.type == "error" else None)
    page.on("requestfailed", lambda request: report["browserErrors"].append({
        "scope": scope, "type": "requestfailed", "url": request.url,
        "message": str(request.failure),
    }))
    page.on("response", lambda response: report["httpErrors"].append({
        "scope": scope, "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)


def page_metrics(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const root = document.querySelector('[data-testid="diagnostic-session"]')
          const visible = (el) => {
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0 &&
              rect.width > 1 && rect.height > 1 && rect.right > 0 && rect.bottom > 0 &&
              rect.left < innerWidth && rect.top < innerHeight
          }
          const controls = [...root.querySelectorAll('button,a[href],input,textarea,select')].filter(visible)
          const collisions = []
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i], b = controls[j]
            if (a.contains(b) || b.contains(a)) continue
            const x = a.getBoundingClientRect(), y = b.getBoundingClientRect()
            const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left)
            const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top)
            if (overlapW > 3 && overlapH > 3) collisions.push([
              (a.innerText || a.getAttribute('aria-label') || a.tagName).trim().slice(0, 32),
              (b.innerText || b.getAttribute('aria-label') || b.tagName).trim().slice(0, 32),
            ])
          }
          const clipped = [...root.querySelectorAll('h1,h2,h3,strong,button,label,p,small,dd,span')].filter((el) => {
            if (!visible(el)) return false
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            if (style.textOverflow === 'ellipsis') return false
            if (rect.right > innerWidth + 1 || rect.left < -1) return true
            return el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap'
          }).map((el) => ({tag: el.tagName, text: (el.innerText || '').trim().slice(0, 64)}))
          const smallText = [...root.querySelectorAll('*')].filter((el) =>
            visible(el) && el.children.length === 0 && (el.innerText || '').trim() &&
            Number.parseFloat(getComputedStyle(el).fontSize) < 13.5
          ).map((el) => ({tag: el.tagName, text: el.innerText.trim().slice(0, 48), size: getComputedStyle(el).fontSize})).slice(0, 30)
          const content = document.querySelector('.app-content')
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            contentWidth: content?.scrollWidth || 0,
            contentClientWidth: content?.clientWidth || 0,
            collisions, clipped, smallText,
          }
        }"""
    )


def capture(page: Page, report: dict[str, Any], name: str) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except PlaywrightTimeoutError:
        pass
    metrics = page_metrics(page)
    page.screenshot(path=str(EVIDENCE_DIR / name), full_page=True)
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    if metrics["documentWidth"] > metrics["viewport"][0] or metrics["contentWidth"] > metrics["contentClientWidth"] + 1:
        raise AssertionError(f"horizontal overflow at {name}: {metrics}")
    if metrics["collisions"] or metrics["clipped"] or metrics["smallText"]:
        raise AssertionError(f"visual contract failed at {name}: {metrics}")


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


def report_url(fixture: dict[str, str], prefix: str) -> str:
    return (
        f"{BASE_URL}/workspace/assessment?course_id={fixture['courseId']}"
        f"&blueprint_id={fixture[f'{prefix}BlueprintId']}"
        f"&question_version_id={fixture[f'{prefix}QuestionVersionId']}"
    )


def open_first_evidence(page: Page) -> None:
    page.locator(".evidence-list article > button").first.click()
    page.get_by_text("模型结论", exact=True).wait_for(state="visible", timeout=10_000)
    page.get_by_test_id("canonical-source-citation").first.wait_for(state="visible", timeout=10_000)


def run_evaluating_and_ready(browser, fixture: dict[str, str], report: dict[str, Any]) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
    page = context.new_page()
    attach_errors(page, report, "1440-evaluating-ready")
    try:
        login(page)
        pattern = "**/api/v1/diagnostics/sessions/*/report"
        page.route(pattern, lambda route: route.continue_(headers={**route.request.headers, "x-fb07-delay-ms": "1800"}), times=1)
        page.goto(report_url(fixture, "ready"), wait_until="domcontentloaded", timeout=30_000)
        page.get_by_test_id("diagnostic-report-loading").wait_for(state="visible", timeout=15_000)
        assert page.get_by_text("评估中：正在生成逐题解析", exact=True).is_visible()
        capture(page, report, "fb07-1440-01-evaluating.png")
        page.get_by_text("你的入学诊断结果", exact=True).wait_for(state="visible", timeout=30_000)
        assert page.get_by_text("逐题解析 5/5", exact=True).is_visible()
        open_first_evidence(page)
        body = page.get_by_test_id("diagnostic-session").inner_text()
        for label in ("判断依据", "系统解析", "可信度", "模型结论"):
            assert label in body
        for private in ("reasoning_content", "system_prompt", "api_key", "raw_response"):
            assert private not in body.lower()
        capture(page, report, "fb07-1440-02-ready-expanded.png")
        with page.expect_response(
            lambda response: "/api/v1/source-refs/" in response.url and response.status == 200,
            timeout=20_000,
        ):
            page.get_by_test_id("canonical-source-citation").first.get_by_role("button").click()
        page.wait_for_url(re.compile(r"/knowledge/documents/"), timeout=20_000)
        report["checks"]["canonicalSourceNavigation"] = {"passed": True, "url": page.url}
    finally:
        context.close()


def run_failure_retry(browser, fixture: dict[str, str], report: dict[str, Any]) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
    page = context.new_page()
    attach_errors(page, report, "1440-failure-retry")
    try:
        login(page)
        pattern = "**/api/v1/diagnostics/sessions/*/report"
        page.route(pattern, lambda route: route.abort("failed"), times=1)
        page.goto(report_url(fixture, "ready"), wait_until="domcontentloaded", timeout=30_000)
        page.get_by_test_id("diagnostic-report-error").wait_for(state="visible", timeout=15_000)
        assert page.get_by_text("报告生成失败，答案仍已保存", exact=True).is_visible()
        capture(page, report, "fb07-1440-03-failed.png")
        page.get_by_role("button", name="重新生成报告").click()
        page.get_by_text("你的入学诊断结果", exact=True).wait_for(state="visible", timeout=30_000)
        open_first_evidence(page)
        capture(page, report, "fb07-1440-04-retry-ready.png")
    finally:
        context.close()


def run_compact_and_legacy(browser, fixture: dict[str, str], report: dict[str, Any]) -> None:
    context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
    page = context.new_page()
    attach_errors(page, report, "1366-ready-legacy")
    try:
        login(page)
        page.goto(report_url(fixture, "ready"), wait_until="domcontentloaded", timeout=30_000)
        page.get_by_text("你的入学诊断结果", exact=True).wait_for(state="visible", timeout=30_000)
        open_first_evidence(page)
        capture(page, report, "fb07-1366-01-ready-expanded.png")
        page.goto(report_url(fixture, "legacy"), wait_until="domcontentloaded", timeout=30_000)
        page.get_by_text("历史报告 · 未重新执行模型评估", exact=True).wait_for(state="visible", timeout=30_000)
        capture(page, report, "fb07-1366-02-legacy.png")
    finally:
        context.close()


def persistence_checks(report: dict[str, Any]) -> None:
    with sqlite3.connect(DB_PATH) as db:
        report_count = db.execute("SELECT COUNT(*) FROM diagnostic_reports").fetchone()[0]
        model_calls = db.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0]
        owner_public_id = db.execute(
            "SELECT owner_public_id FROM diagnostic_reports ORDER BY rowid LIMIT 1"
        ).fetchone()[0]
        learning_events = db.execute(
            "SELECT COUNT(*) FROM learning_events WHERE owner_public_id = ?",
            (owner_public_id,),
        ).fetchone()[0]
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
    if report_count != 2 or model_calls != 1 or learning_events != 18 or integrity != "ok" or foreign_keys:
        raise AssertionError({
            "reportCount": report_count, "modelCallCount": model_calls,
            "learningEventCount": learning_events, "integrity": integrity,
            "foreignKeys": foreign_keys,
        })
    report["checks"]["persistence"] = {
        "reportCount": report_count,
        "modelCallCount": model_calls,
        "externalModelCallsDuringBrowser": 0,
        "learningEventOwner": owner_public_id,
        "learningEventCount": learning_events,
        "integrityCheck": integrity,
        "foreignKeyViolationCount": 0,
    }


def main() -> int:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "schemaVersion": "acceptance-feedback.P1-B07.browser.v1",
        "taskId": "ACCEPTANCE-FEEDBACK-P1-B07",
        "result": "running",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "checks": {},
        "browserErrors": [],
        "httpErrors": [],
        "manualAcceptance": "deferred by user until all acceptance-feedback fixes are complete",
        "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            run_evaluating_and_ready(browser, fixture, report)
            run_failure_retry(browser, fixture, report)
            run_compact_and_legacy(browser, fixture, report)
            browser.close()
        persistence_checks(report)
        expected_failures = [
            item for item in report["browserErrors"]
            if item["type"] == "requestfailed"
            and "/api/v1/diagnostics/sessions/" in item.get("url", "")
            and item.get("url", "").endswith("/report")
        ]
        expected_console = [
            item for item in report["browserErrors"]
            if item["type"] == "console" and "ERR_FAILED" in item["message"]
        ]
        expected_navigation = [
            item for item in report["browserErrors"]
            if item["type"] == "requestfailed" and "ERR_ABORTED" in item["message"]
            and item not in expected_failures
        ]
        expected = expected_failures + expected_console + expected_navigation
        unexpected = [item for item in report["browserErrors"] if item not in expected]
        if len(expected_failures) != 1 or unexpected or report["httpErrors"]:
            raise AssertionError({
                "expectedFailureCount": len(expected_failures),
                "unexpectedBrowserErrors": unexpected,
                "httpErrors": report["httpErrors"],
            })
        report["checks"]["expectedReportAbort"] = {"requestCount": len(expected_failures)}
        report["checks"]["expectedNavigationCancellations"] = {"count": len(expected_navigation)}
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{exc.__class__.__name__}: {exc}"
        raise
    finally:
        report["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
