"""Desktop browser acceptance for F3-T03 traceable entry-diagnostic generation."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("EDUMATRIX_F3_T03_PORT", "8894"))
BASE_URL = f"http://127.0.0.1:{PORT}"
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f3_t03_diagnostic_generation"
DB_PATH = OUTPUT_DIR / "f3_t03_runtime.db"
COURSE_ID = "demo-course-rag-trust-v1"


def wait_port(expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected state: {expected}")


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    preserved = {"checkpoint_context_verified.json"}
    for item in OUTPUT_DIR.iterdir():
        if item.name in preserved:
            continue
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def seed_demo(env: dict[str, str]) -> None:
    command = (
        "from app.database import SessionLocal, init_db; "
        "from app.competition_demo_seed import seed_competition_demo; "
        "init_db(); db=SessionLocal(); "
        "result=seed_competition_demo(db); print(result); db.close()"
    )
    subprocess.run(
        [sys.executable, "-c", command],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


def attach_errors(page: Page, report: dict, scope: str) -> None:
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


def page_metrics(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const root = document.querySelector('[data-testid="entry-diagnostic"]')
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
          const clipped = [...root.querySelectorAll('h1,h2,h3,strong,button,label,p,small,dd')].filter((el) => {
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
          const visualEffects = [...root.querySelectorAll('*')].filter(visible).flatMap((el) => {
            const style = getComputedStyle(el), issues = []
            if (style.backgroundImage && style.backgroundImage !== 'none') issues.push('background-image')
            if (style.backdropFilter && style.backdropFilter !== 'none') issues.push('backdrop-filter')
            return issues.map((issue) => ({issue, tag: el.tagName, className: String(el.className).slice(0, 80)}))
          })
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
            visualEffects,
          }
        }"""
    )


def capture(page: Page, report: dict, name: str) -> dict:
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
    if metrics["visualEffects"]:
        raise AssertionError(f"forbidden decorative visual effect at {name}: {metrics['visualEffects']}")
    return metrics


def login(page: Page) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_test_id("login-username").fill("lzz")
    page.get_by_test_id("login-password").fill("404404aA")
    with page.expect_response(
        lambda response: response.url.endswith("/api/auth/login") and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(rf".*/(?:$|workspace|profile|onboarding).*"), timeout=30_000)


def run_viewport(browser, viewport: tuple[int, int], report: dict, *, exercise_failure: bool) -> None:
    suffix = f"{viewport[0]}x{viewport[1]}"
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    page = context.new_page()
    attach_errors(page, report, suffix)
    try:
        login(page)
        page.goto(
            f"{BASE_URL}/workspace/assessment/entry?course_id={COURSE_ID}",
            wait_until="domcontentloaded",
            timeout=30_000,
        )
        page.get_by_test_id("entry-diagnostic").wait_for(state="visible", timeout=30_000)
        page.get_by_test_id("diagnostic-overview").wait_for(state="visible", timeout=30_000)
        assert page.get_by_text("RAG 应用开发与负责任评测实训", exact=True).count() >= 1
        assert page.get_by_text("理论理解", exact=True).is_visible()
        assert page.get_by_text("应用判断", exact=True).is_visible()
        assert page.get_by_text("工程判断", exact=True).is_visible()
        capture(page, report, f"{suffix}-01-preflight.png")

        if exercise_failure:
            def fail_once(route):
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body=json.dumps({"detail": {"code": "diagnostic_temporarily_unavailable", "message": "诊断生成暂时不可用，请重试。"}}),
                )

            page.route("**/api/v1/diagnostics/blueprints", fail_once, times=1)
            page.get_by_test_id("generate-diagnostic").click()
            page.get_by_test_id("diagnostic-error").wait_for(state="visible", timeout=20_000)
            assert page.get_by_text("诊断生成暂时不可用，请重试。", exact=True).is_visible()
            report["checks"][f"{suffix}-retry-state"] = {"visible": True}
            page.get_by_test_id("diagnostic-error").get_by_role("button", name="重试").click()
            page.get_by_test_id("diagnostic-overview").wait_for(state="visible", timeout=20_000)

        with page.expect_response(
            lambda response: response.url.endswith("/api/v1/diagnostics/blueprints") and response.status == 201,
            timeout=30_000,
        ):
            page.get_by_test_id("generate-diagnostic").click()
        ready = page.get_by_test_id("diagnostic-ready")
        ready.wait_for(state="visible", timeout=30_000)
        assert ready.get_by_text("5 道题已准备完成", exact=True).is_visible()
        assert page.get_by_test_id("diagnostic-generation-stages").get_by_text("已完成", exact=True).count() == 3
        capture(page, report, f"{suffix}-02-ready.png")

        page.get_by_test_id("enter-diagnostic").click()
        page.wait_for_url(re.compile(r".*/workspace/assessment\?.*question_version_id=.*"), timeout=30_000)
        page.get_by_test_id("assessment-question").wait_for(state="visible", timeout=30_000)
        assert page.get_by_role("heading", name="向量检索是否总能优于关键词检索？").is_visible()
        report["checks"][f"{suffix}-entry-routing"] = {"url": page.url, "firstQuestionSelected": True}
    finally:
        context.close()


def main() -> int:
    clear_output()
    report = {
        "schema_version": "f3-t03.diagnostic-generation-browser-e2e.v1",
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "database": str(DB_PATH),
        "screenshots": [],
        "checks": {},
        "browser_errors": [],
        "http_errors": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    process = None
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "f3-t03-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
    })
    try:
        seed_demo(env)
        with (OUTPUT_DIR / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "run.py"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                run_viewport(browser, (1440, 900), report, exercise_failure=True)
                run_viewport(browser, (1366, 768), report, exercise_failure=False)
                browser.close()
        with sqlite3.connect(DB_PATH) as db:
            rows = db.execute(
                "SELECT owner_public_id, course_id, question_count, estimated_minutes FROM diagnostic_blueprints"
            ).fetchall()
        assert len(rows) == 2 and all(row[1:] == (COURSE_ID, 5, 10) for row in rows)
        report["checks"]["persistence"] = {"blueprintCount": len(rows), "rows": [list(row) for row in rows]}
        expected_http_errors = [item for item in report["http_errors"] if item["status"] >= 400]
        expected_retry_error = [
            item for item in expected_http_errors
            if item["status"] == 503 and item["url"].endswith("/api/v1/diagnostics/blueprints")
        ]
        unexpected_http_errors = [item for item in expected_http_errors if item not in expected_retry_error]
        expected_browser_errors = [
            item for item in report["browser_errors"]
            if (
                item["type"] == "requestfailed"
                and (
                    item["url"].endswith("/api/v1/competition-demo/context")
                    or "/api/v1/m5/workspace?" in item["url"]
                )
                and "ERR_ABORTED" in item["message"]
            ) or (
                item["type"] == "console"
                and "503 (Service Unavailable)" in item["message"]
            )
        ]
        unexpected_browser_errors = [item for item in report["browser_errors"] if item not in expected_browser_errors]
        report["checks"]["expected-retry-error"] = {"count": len(expected_retry_error)}
        report["checks"]["expected-navigation-cancellations"] = {
            "count": sum(1 for item in expected_browser_errors if item["type"] == "requestfailed"),
        }
        if unexpected_browser_errors or unexpected_http_errors or len(expected_retry_error) != 1:
            raise AssertionError({
                "browser_errors": unexpected_browser_errors,
                "http_errors": unexpected_http_errors,
                "expected_retry_errors": expected_retry_error,
            })
        report["result"] = "passed"
    except Exception as error:
        report["result"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            try:
                wait_port(False, 15)
            except RuntimeError:
                pass
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
