"""Desktop browser acceptance for F3-T04 recoverable diagnostic sessions."""

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
PORT = int(os.getenv("EDUMATRIX_F3_T04_PORT", "8895"))
BASE_URL = f"http://127.0.0.1:{PORT}"
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f3_t04_diagnostic_session"
DB_PATH = OUTPUT_DIR / "f3_t04_runtime.db"
COURSE_ID = "demo-course-rag-trust-v1"


def attach_errors(page: Page, report: dict[str, Any], scope: str) -> None:
    page.on("pageerror", lambda error: report["browser_errors"].append({
        "scope": scope, "type": "pageerror", "message": str(error),
    }))
    page.on("console", lambda message: report["browser_errors"].append({
        "scope": scope, "type": "console", "message": message.text,
    }) if message.type == "error" else None)
    page.on("requestfailed", lambda request: report["browser_errors"].append({
        "scope": scope,
        "type": "requestfailed",
        "url": request.url,
        "message": str(request.failure),
    }))
    page.on("response", lambda response: report["http_errors"].append({
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
              (a.innerText || a.getAttribute('aria-label') || a.title || a.tagName).trim().slice(0, 32),
              (b.innerText || b.getAttribute('aria-label') || b.title || b.tagName).trim().slice(0, 32),
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
    page.wait_for_timeout(200)
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


def login(page: Page) -> str:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_test_id("login-username").fill("lzz")
    page.get_by_test_id("login-password").fill("404404aA")
    with page.expect_response(
        lambda response: response.url.endswith("/api/auth/login") and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(rf"{re.escape(BASE_URL)}/(?:$|workspace|profile|onboarding).*"), timeout=30_000)
    return page.evaluate("() => localStorage.getItem('edumatrix_token')")


def create_blueprint(page: Page, token: str, suffix: str) -> dict[str, Any]:
    response = page.request.post(
        f"{BASE_URL}/api/v1/diagnostics/blueprints",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "course_id": COURSE_ID,
            "idempotency_key": f"f3-t04-browser-{suffix}",
            "question_count": 5,
        },
    )
    if response.status != 201:
        raise AssertionError(f"blueprint creation failed: {response.status} {response.text()}")
    return response.json()["blueprint"]


def answer_current(page: Page, question: dict[str, Any], *, alternate: bool = False) -> dict[str, Any]:
    question_type = question["questionType"]
    if question_type == "single_choice":
        options = page.locator(".option-list label")
        index = min(1 if alternate else 0, options.count() - 1)
        options.nth(index).click()
        expected = {"choice": options.nth(index).locator("b").inner_text()}
    elif question_type == "multiple_choice":
        options = page.locator(".option-list label")
        index = min(1 if alternate else 0, options.count() - 1)
        options.nth(index).click()
        expected = {"choices": [options.nth(index).locator("b").inner_text()]}
    elif question_type == "true_false":
        value = not alternate
        page.get_by_role("button", name="正确" if value else "错误").click()
        expected = {"value": value}
    elif question_type == "fill_blank":
        value = "恢复验证答案" if not alternate else "修改后的恢复验证答案"
        for field in page.locator(".blank-list input").all():
            field.fill(value)
        expected = {"blanks": [value] * page.locator(".blank-list input").count()}
    elif question_type == "code":
        value = "def answer():\n    return True" if not alternate else "def answer():\n    return False"
        page.locator(".code-answer textarea").fill(value)
        expected = {"code": value}
    else:
        value = "基于课程来源完成的诊断作答。" if not alternate else "修改后的诊断作答仍保留在当前页面。"
        page.locator("textarea.text-answer").fill(value)
        expected = {"text": value}
    page.get_by_text("基本理解", exact=True).click()
    return expected


def assert_answer_visible(page: Page, question: dict[str, Any], expected: dict[str, Any]) -> None:
    question_type = question["questionType"]
    if question_type in {"single_choice", "multiple_choice"}:
        selected = page.locator(".option-list label.selected b").all_inner_texts()
        values = expected.get("choices", [expected.get("choice")])
        assert selected == values
    elif question_type == "true_false":
        label = "正确" if expected["value"] else "错误"
        assert page.get_by_role("button", name=label).get_attribute("class") and "selected" in page.get_by_role("button", name=label).get_attribute("class")
    elif question_type == "fill_blank":
        assert page.locator(".blank-list input").all_input_values() == expected["blanks"]
    elif question_type == "code":
        assert page.locator(".code-answer textarea").input_value() == expected["code"]
    else:
        assert page.locator("textarea.text-answer").input_value() == expected["text"]
    assert page.locator(".understanding-control label.selected").inner_text().strip() == "基本理解"


def save_and_move(page: Page, target_number: int) -> None:
    with page.expect_response(
        lambda response: "/api/v1/diagnostics/sessions/" in response.url and "/responses/" in response.url and response.status == 200,
        timeout=20_000,
    ):
        page.get_by_role("button", name="保存并进入下一题").click()
    page.get_by_text(f"第 {target_number} / 5 题", exact=True).wait_for(state="visible", timeout=10_000)


def run_full_flow(browser, report: dict[str, Any]) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
    page = context.new_page()
    attach_errors(page, report, "1440x900")
    try:
        token = login(page)
        blueprint = create_blueprint(page, token, "1440x900")
        first_id = blueprint["questions"][0]["id"]
        page.goto(
            f"{BASE_URL}/workspace/assessment?course_id={COURSE_ID}&blueprint_id={blueprint['id']}&question_version_id={first_id}",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        page.get_by_test_id("diagnostic-session").wait_for(state="visible", timeout=30_000)
        page.get_by_text("第 1 / 5 题", exact=True).wait_for(state="visible", timeout=30_000)
        capture(page, report, "1440x900-01-initial.png")

        page.route(
            "**/api/v1/diagnostics/sessions/*/responses/*",
            lambda route: route.abort("failed"),
            times=1,
        )
        first_answer = answer_current(page, blueprint["questions"][0])
        page.get_by_test_id("diagnostic-save-error").wait_for(state="visible", timeout=10_000)
        assert_answer_visible(page, blueprint["questions"][0], first_answer)
        report["checks"]["save-failure-preserves-input"] = {"passed": True}
        capture(page, report, "1440x900-02-save-failure.png")

        with page.expect_response(
            lambda response: "/responses/" in response.url and response.status == 200,
            timeout=20_000,
        ):
            page.get_by_role("button", name="重试保存").click()
        page.get_by_test_id("diagnostic-save-error").wait_for(state="hidden", timeout=10_000)
        save_and_move(page, 2)

        answer_current(page, blueprint["questions"][1])
        save_and_move(page, 3)
        third_answer = answer_current(page, blueprint["questions"][2])
        with page.expect_response(
            lambda response: "/responses/" in response.url and response.status == 200,
            timeout=20_000,
        ):
            page.wait_for_timeout(900)
        page.reload(wait_until="domcontentloaded")
        page.get_by_test_id("diagnostic-restored").wait_for(state="visible", timeout=20_000)
        page.get_by_text("第 3 / 5 题", exact=True).wait_for(state="visible", timeout=10_000)
        assert_answer_visible(page, blueprint["questions"][2], third_answer)
        report["checks"]["refresh-restoration"] = {"question": 3, "passed": True}
        capture(page, report, "1440x900-03-restored.png")

        modified_answer = answer_current(page, blueprint["questions"][2], alternate=True)
        dialogs: list[str] = []

        def dismiss_dialog(dialog) -> None:
            dialogs.append(dialog.message)
            dialog.dismiss()

        page.once("dialog", dismiss_dialog)
        page.get_by_role("button", name="返回诊断概览").click()
        page.wait_for_timeout(150)
        assert dialogs == ["当前题目尚未可靠保存，确定离开诊断吗？"]
        assert "/workspace/assessment?" in page.url
        assert_answer_visible(page, blueprint["questions"][2], modified_answer)
        report["checks"]["unsaved-navigation-warning"] = {"message": dialogs[0], "stayed": True}

        save_and_move(page, 4)
        answer_current(page, blueprint["questions"][3])
        save_and_move(page, 5)
        answer_current(page, blueprint["questions"][4])
        with page.expect_response(
            lambda response: response.url.endswith("/submit") and response.status == 200,
            timeout=30_000,
        ):
            page.get_by_role("button", name="提交本次诊断").click()
        page.get_by_test_id("diagnostic-submitted").wait_for(state="visible", timeout=20_000)
        assert page.get_by_text("本次诊断答案已提交", exact=True).is_visible()
        report["checks"]["complete-submit"] = {"completed": 5, "passed": True}
        capture(page, report, "1440x900-04-submitted.png")
    finally:
        context.close()


def run_compact_layout(browser, report: dict[str, Any]) -> None:
    context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
    page = context.new_page()
    attach_errors(page, report, "1366x768")
    try:
        token = login(page)
        blueprint = create_blueprint(page, token, "1366x768")
        first_id = blueprint["questions"][0]["id"]
        page.goto(
            f"{BASE_URL}/workspace/assessment?course_id={COURSE_ID}&blueprint_id={blueprint['id']}&question_version_id={first_id}",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        page.get_by_test_id("diagnostic-session").wait_for(state="visible", timeout=30_000)
        page.get_by_text("第 1 / 5 题", exact=True).wait_for(state="visible", timeout=30_000)
        capture(page, report, "1366x768-01-initial.png")
        answer_current(page, blueprint["questions"][0])
        with page.expect_response(
            lambda response: "/responses/" in response.url and response.status == 200,
            timeout=20_000,
        ):
            page.wait_for_timeout(900)
        capture(page, report, "1366x768-02-answered.png")
    finally:
        context.close()


def persistence_evidence(report: dict[str, Any], baseline_attempts: int) -> None:
    with sqlite3.connect(DB_PATH) as db:
        sessions = db.execute(
            "SELECT status, current_question_version_id, last_saved_at, submitted_at FROM diagnostic_sessions ORDER BY started_at"
        ).fetchall()
        drafts = db.execute(
            "SELECT session_id, COUNT(*), SUM(CASE WHEN client_saved_at IS NOT NULL THEN 1 ELSE 0 END) "
            "FROM diagnostic_response_drafts GROUP BY session_id ORDER BY session_id"
        ).fetchall()
        final_attempts = db.execute("SELECT COUNT(*) FROM assessment_attempts").fetchone()[0]
        applied = db.execute(
            "SELECT version FROM schema_migrations WHERE version IN ('20260812_067','20260812_068') ORDER BY version"
        ).fetchall()
    assert len(sessions) == 2
    assert sessions[0][0] == "submitted" and sessions[0][3] is not None
    assert any(row[1:] == (5, 5) for row in drafts)
    assert final_attempts == baseline_attempts
    assert [row[0] for row in applied] == ["20260812_067", "20260812_068"]
    report["checks"]["persistence"] = {
        "sessions": [list(row) for row in sessions],
        "drafts": [list(row) for row in drafts],
        "formalAttemptCountBefore": baseline_attempts,
        "formalAttemptCountAfter": final_attempts,
        "migrations": [row[0] for row in applied],
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        baseline_attempts = db.execute("SELECT COUNT(*) FROM assessment_attempts").fetchone()[0]
    report: dict[str, Any] = {
        "schema_version": "f3-t04.diagnostic-session-browser-e2e.v1",
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "database": str(DB_PATH),
        "screenshots": [],
        "checks": {},
        "browser_errors": [],
        "http_errors": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            run_full_flow(browser, report)
            run_compact_layout(browser, report)
            browser.close()
        persistence_evidence(report, baseline_attempts)

        expected_failures = [
            item for item in report["browser_errors"]
            if (
                item["type"] == "requestfailed"
                and "/api/v1/diagnostics/sessions/" in item["url"]
                and "/responses/" in item["url"]
            ) or (
                item["type"] == "console"
                and "Failed to load resource: net::ERR_FAILED" in item["message"]
            )
        ]
        expected_navigation_cancellations = [
            item for item in report["browser_errors"]
            if item["type"] == "requestfailed"
            and "ERR_ABORTED" in item["message"]
            and item not in expected_failures
        ]
        expected = expected_failures + expected_navigation_cancellations
        unexpected_browser = [item for item in report["browser_errors"] if item not in expected]
        save_abort_requests = [item for item in expected_failures if item["type"] == "requestfailed"]
        if len(save_abort_requests) != 1 or unexpected_browser or report["http_errors"]:
            raise AssertionError({
                "expected_save_failures": expected_failures,
                "unexpected_browser_errors": unexpected_browser,
                "http_errors": report["http_errors"],
            })
        report["checks"]["expected-save-abort"] = {
            "requestCount": len(save_abort_requests),
            "consoleCount": sum(1 for item in expected_failures if item["type"] == "console"),
        }
        report["checks"]["expected-navigation-cancellations"] = {
            "count": len(expected_navigation_cancellations),
        }
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
