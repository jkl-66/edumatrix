"""Browser closure check for the P1-B01 semantic-profile candidate card."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import e2e_f3_profile_onboarding as onboarding_e2e


PORT = int(os.getenv("EDUMATRIX_P1_B01_VISUAL_PORT", "8896"))
BASE_URL = f"http://127.0.0.1:{PORT}"
EVIDENCE_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "acceptance_feedback" / "P1-B01"
DB_PATH = EVIDENCE_DIR / "P1-B01_runtime.db"
PASSWORD = "P1-B01-visual-2026!"


def wait_port(expected: bool, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected state: {expected}")


def visual_metrics(page) -> dict:
    return page.evaluate(
        """() => {
          const clippedRect = (el) => {
            const raw = el.getBoundingClientRect()
            let left = Math.max(0, raw.left), top = Math.max(0, raw.top)
            let right = Math.min(innerWidth, raw.right), bottom = Math.min(innerHeight, raw.bottom)
            for (let parent = el.parentElement; parent; parent = parent.parentElement) {
              const style = getComputedStyle(parent), rect = parent.getBoundingClientRect()
              if (/(auto|hidden|scroll|clip)/.test(style.overflowX)) {
                left = Math.max(left, rect.left); right = Math.min(right, rect.right)
              }
              if (/(auto|hidden|scroll|clip)/.test(style.overflowY)) {
                top = Math.max(top, rect.top); bottom = Math.min(bottom, rect.bottom)
              }
            }
            return {left, top, right, bottom, width: right - left, height: bottom - top}
          }
          const visible = (el) => {
            const style = getComputedStyle(el), rect = clippedRect(el)
            return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0 &&
              rect.width > 1 && rect.height > 1
          }
          const controls = [...document.querySelectorAll('button,a[href],input,textarea,select')].filter(visible)
          const collisions = []
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i], b = controls[j]
            if (a.contains(b) || b.contains(a)) continue
            const x = clippedRect(a), y = clippedRect(b)
            const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left)
            const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top)
            if (overlapW > 3 && overlapH > 3) collisions.push([
              (a.innerText || a.getAttribute('aria-label') || a.title || a.tagName).trim().slice(0, 32),
              (b.innerText || b.getAttribute('aria-label') || b.title || b.tagName).trim().slice(0, 32),
            ])
          }
          const smallText = [...document.querySelectorAll('body *')].filter((el) =>
            visible(el) && el.children.length === 0 && (el.innerText || '').trim() &&
            Number.parseFloat(getComputedStyle(el).fontSize) < 14
          ).map((el) => ({text: el.innerText.trim().slice(0, 48), size: getComputedStyle(el).fontSize}))
          const clippedText = [...document.querySelectorAll('h1,h2,h3,strong,button,label,p,span')].filter((el) => {
            if (!visible(el)) return false
            const style = getComputedStyle(el)
            return style.whiteSpace === 'nowrap' && style.textOverflow !== 'ellipsis' &&
              el.scrollWidth > el.clientWidth + 4
          }).map((el) => (el.innerText || '').trim().slice(0, 64))
          const badge = document.querySelector('.model-badge')
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            collisions,
            smallText,
            clippedText,
            modelBadgeText: badge?.innerText || '',
            modelBadgeFontSize: badge ? getComputedStyle(badge).fontSize : '',
          }
        }"""
    )


def capture(page, report: dict, name: str) -> None:
    page.wait_for_timeout(350)
    metrics = visual_metrics(page)
    page.screenshot(path=str(EVIDENCE_DIR / name), full_page=False)
    report["screenshots"].append(name)
    report["metrics"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert not metrics["collisions"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["clippedText"], metrics
    assert metrics["modelBadgeText"] == "DeepSeek v4 Flash · max", metrics
    assert metrics["modelBadgeFontSize"] == "14px", metrics


def profile_row(username: str):
    with sqlite3.connect(DB_PATH) as db:
        return db.execute(
            """SELECT major, learning_goals, knowledge_base, weak_points, interaction_preferences
               FROM student_profiles WHERE student_id=?""",
            (username,),
        ).fetchone()


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "acceptance-feedback.p1-b01.visual-closure.v1",
        "result": "running",
        "screenshots": [],
        "metrics": {},
        "browser_errors": [],
        "http_errors": [],
    }
    process = None
    try:
        env = os.environ.copy()
        for key in (
            "EDUMATRIX_LLM_PROVIDER", "EDUMATRIX_LLM_MODEL", "EDUMATRIX_LLM_API_KEY",
            "EDUMATRIX_LLM_ENDPOINT", "PYTHON_DOTENV_DISABLED",
        ):
            env.pop(key, None)
        env.update({
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "p1-b01-visual-isolated-secret",
            "EDUMATRIX_ONBOARDING_V2": "1",
            "EDUMATRIX_RELOAD": "0",
            "EDUMATRIX_HOST": "127.0.0.1",
            "EDUMATRIX_PORT": str(PORT),
            "EDUMATRIX_SANDBOX_MODE": "disabled",
            "PYTHONUNBUFFERED": "1",
        })
        log_path = EVIDENCE_DIR / "backend-visual-closure.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            onboarding_e2e.PORT = PORT
            onboarding_e2e.BASE_URL = BASE_URL
            onboarding_e2e.DB_PATH = DB_PATH
            onboarding_e2e.PASSWORD = PASSWORD
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page()
                page.on("pageerror", lambda error: report["browser_errors"].append(str(error)))
                page.on("console", lambda message: report["browser_errors"].append(message.text) if message.type == "error" else None)
                page.on("requestfailed", lambda request: report["browser_errors"].append(f"{request.url}: {request.failure}"))
                page.on("response", lambda response: report["http_errors"].append({"status": response.status, "url": response.url}) if response.status >= 400 else None)
                username = f"p1_b01_visual_{int(time.time() * 1000)}"
                user = onboarding_e2e.register(page, username)
                onboarding_e2e.attach_course(username)
                onboarding_e2e.login_into_onboarding(page, user)
                before = profile_row(username)
                page.get_by_label("你的回答").fill("我在华中科技大学读大三，专业是计算机科学与技术，最近想系统补上机器学习基础。")
                with page.expect_response(
                    lambda response: response.url.endswith("/api/v1/onboarding/turns") and response.status == 200,
                    timeout=120_000,
                ):
                    page.get_by_role("button", name="发送回答").click()
                editor = page.get_by_test_id("onboarding-candidate-editor")
                editor.wait_for(state="visible", timeout=30_000)
                editor.get_by_text("模型理解", exact=True).wait_for(state="visible")
                editor.get_by_text("依据：", exact=False).first.wait_for(state="visible")
                editor.locator(".candidate-understanding").evaluate(
                    "element => element.scrollIntoView({block: 'center'})"
                )
                capture(page, report, "1440x900-06-visual-closure.png")
                page.set_viewport_size({"width": 1366, "height": 768})
                editor.locator(".candidate-understanding").evaluate(
                    "element => element.scrollIntoView({block: 'center'})"
                )
                capture(page, report, "1366x768-06-visual-closure.png")
                after = profile_row(username)
                assert before == after, {"before": before, "after": after}
                report["profileUnchangedBeforeConfirmation"] = True
                context.close()
                browser.close()
        if report["browser_errors"] or report["http_errors"]:
            raise AssertionError({"browser_errors": report["browser_errors"], "http_errors": report["http_errors"]})
        report["result"] = "passed"
    except (AssertionError, PlaywrightTimeoutError, RuntimeError) as error:
        report["result"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            try:
                wait_port(False, 15)
            except RuntimeError:
                pass
        (EVIDENCE_DIR / "visual-closure-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
