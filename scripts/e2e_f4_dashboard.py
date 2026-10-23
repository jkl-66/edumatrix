"""Isolated desktop browser acceptance for F4-T01 student dashboard."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PORT = int(os.getenv("EDUMATRIX_F4_T01_PORT", "8897"))
BASE_URL = f"http://127.0.0.1:{PORT}"
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f4_t01_dashboard"
DB_PATH = OUTPUT_DIR / "f4_t01_runtime.db"
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


def prepare_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def seed_fixture() -> None:
    os.environ.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "f4-t01-isolated-secret",
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
    from app.competition_demo_seed import seed_competition_demo
    from app.database import SessionLocal, init_db

    init_db()
    session = SessionLocal()
    try:
        seed_competition_demo(session)
    finally:
        session.close()


def table_counts() -> dict[str, int]:
    with sqlite3.connect(DB_PATH) as db:
        return {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("learning_events", "profile_snapshots", "learning_paths", "review_plans")
        }


def login(page: Page) -> dict:
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        form={"username": "lzz", "password": "404404aA"},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    return response.json()


def install_session(page: Page, payload: dict) -> None:
    state = json.dumps(payload, ensure_ascii=False)
    page.add_init_script(
        f"""
        const session = {state}
        localStorage.setItem('edumatrix_token', session.access_token)
        localStorage.setItem('edumatrix_username', session.username || 'lzz')
        localStorage.setItem('edumatrix_display_name', session.display_name || session.username || 'lzz')
        localStorage.setItem('edumatrix_role', session.role || 'student')
        localStorage.setItem('edumatrix_student_id', session.student_id || session.username || 'lzz')
        localStorage.setItem('edumatrix_onboarded', 'true')
        localStorage.setItem('edumatrix_course_id', '{COURSE_ID}')
        localStorage.setItem('edumatrix_course_title', '人工智能与机器学习工程')
        """
    )


def page_metrics(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const visible = (el) => {
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1 &&
              rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight
          }
          const controls = [...document.querySelectorAll('button,a[href],input,select,textarea')].filter(visible)
          const collisions = []
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i], b = controls[j]
            if (a.contains(b) || b.contains(a)) continue
            const x = a.getBoundingClientRect(), y = b.getBoundingClientRect()
            const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left)
            const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top)
            if (overlapW > 3 && overlapH > 3) collisions.push([
              (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 32),
              (b.innerText || b.getAttribute('aria-label') || '').trim().slice(0, 32),
            ])
          }
          const clipped = [...document.querySelectorAll('button,a[href],h1,h2,h3,strong,p,span')].filter((el) => {
            if (!visible(el)) return false
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            if (style.textOverflow === 'ellipsis') return false
            if (rect.right > innerWidth + 1 || rect.left < -1) return true
            return el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap'
          }).map((el) => ({ tag: el.tagName, text: (el.innerText || '').trim().slice(0, 64) })).slice(0, 20)
          const textNodes = [...document.querySelectorAll('body *')].filter(
            (el) => visible(el) && el.children.length === 0 && (el.innerText || '').trim()
          )
          const smallText = textNodes.filter(
            (el) => Number.parseFloat(getComputedStyle(el).fontSize) < 13.5
          ).map((el) => ({ text: el.innerText.trim().slice(0, 40), size: getComputedStyle(el).fontSize })).slice(0, 20)
          const first = document.querySelector('[data-testid="dashboard-primary-task"]')?.getBoundingClientRect()
          const side = document.querySelector('.dashboard-side-summary')?.getBoundingClientRect()
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            documentHeight: document.documentElement.scrollHeight,
            bodyTextLength: (document.body.innerText || '').trim().length,
            collisions,
            clipped,
            smallText,
            firstViewport: first ? { left: first.left, right: first.right, top: first.top, bottom: first.bottom } : null,
            sideSummary: side ? { left: side.left, right: side.right, top: side.top, bottom: side.bottom } : null,
          }
        }"""
    )


def capture_and_validate(page: Page, name: str, report: dict) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(500)
    metrics = page_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=False)
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    if metrics["documentWidth"] > metrics["viewport"][0]:
        raise AssertionError({"horizontal_overflow": metrics})
    if metrics["bodyTextLength"] < 100:
        raise AssertionError({"blank_page": metrics})
    if metrics["collisions"] or metrics["clipped"] or metrics["smallText"]:
        raise AssertionError({"visual_defects": metrics})
    if not metrics["firstViewport"] or not metrics["sideSummary"]:
        raise AssertionError({"missing_decision_layout": metrics})
    if metrics["firstViewport"]["right"] > metrics["sideSummary"]["left"] + 1:
        raise AssertionError({"decision_columns_overlap": metrics})


def run_viewport(browser, viewport: tuple[int, int], session_payload: dict, report: dict) -> None:
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    page = context.new_page()
    install_session(page, session_payload)
    errors: list[dict] = []
    responses: list[dict] = []
    page.on("pageerror", lambda exc: errors.append({"type": "pageerror", "message": str(exc)}))
    page.on("console", lambda msg: errors.append({"type": "console", "message": msg.text}) if msg.type == "error" else None)
    page.on("requestfailed", lambda req: errors.append({"type": "requestfailed", "url": req.url, "message": str(req.failure)}))
    page.on("response", lambda response: responses.append({"url": response.url, "status": response.status}) if response.status >= 400 else None)
    suffix = f"{viewport[0]}x{viewport[1]}"
    try:
        with page.expect_response(
            lambda response: response.url.startswith(f"{BASE_URL}/api/v1/m5/dashboard") and response.status == 200,
            timeout=30_000,
        ) as dashboard_response:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        payload = dashboard_response.value.json()
        page.get_by_test_id("dashboard-today-tasks").wait_for(state="visible", timeout=30_000)
        primary = page.get_by_test_id("dashboard-primary-action")
        if primary.count() != 1 or not primary.is_visible():
            raise AssertionError("dashboard must expose exactly one visible primary action")
        if page.get_by_test_id("dashboard-primary-task").count() != 1:
            raise AssertionError("dashboard primary task missing")
        if not payload.get("focus", {}).get("strategy") or not payload.get("primary_task", {}).get("source_refs"):
            raise AssertionError({"untraceable_dashboard_payload": payload})
        if payload["primary_action"]["route"] != payload["primary_task"]["continue_route"]:
            raise AssertionError({"action_route_mismatch": payload["primary_action"]})
        if "较上周稳步提升" in page.locator("body").inner_text():
            raise AssertionError("fabricated trend copy is visible")
        capture_and_validate(page, f"{suffix}-dashboard.png", report)

        source = page.locator(".dashboard-source-disclosure")
        source.locator("summary").click()
        page.wait_for_timeout(200)
        if source.locator("div span").count() < 1:
            raise AssertionError("traceability disclosure is empty")
        report["checks"][f"{suffix}-traceability"] = {
            "sourceCount": source.locator("div span").count(),
            "sourceEventIds": payload.get("sourceEventIds", []),
        }

        expected_route = payload["primary_action"]["route"]
        primary.click()
        page.wait_for_url(
            lambda url: url.removeprefix(BASE_URL) == expected_route,
            timeout=30_000,
        )
        report["checks"][f"{suffix}-primary-action"] = {
            "expectedRoute": expected_route,
            "actualUrl": page.url,
        }
        if errors or responses:
            raise AssertionError({"browser_errors": errors, "http_errors": responses})
    finally:
        report["browser_errors"].extend(errors)
        report["http_errors"].extend(responses)
        context.close()


def main() -> int:
    prepare_output()
    seed_fixture()
    before = table_counts()
    report = {
        "schema_version": "f4-t01.dashboard-browser-e2e.v1",
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
    try:
        env = os.environ.copy()
        with (OUTPUT_DIR / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                setup = browser.new_page()
                session_payload = login(setup)
                setup.close()
                for viewport in ((1440, 900), (1366, 768)):
                    run_viewport(browser, viewport, session_payload, report)
                browser.close()
        after = table_counts()
        if before != after:
            raise AssertionError({"dashboard_read_mutated_learning_state": {"before": before, "after": after}})
        report["checks"]["read-only-database"] = {"before": before, "after": after}
        with sqlite3.connect(DB_PATH) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise AssertionError({"integrity_check": integrity})
        report["checks"]["database-integrity"] = integrity
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, text=True, timeout=20,
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
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
