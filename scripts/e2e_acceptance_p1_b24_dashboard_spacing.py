from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PORT = 8914
BASE_URL = f"http://127.0.0.1:{PORT}"
EVIDENCE_DIR = ROOT / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B24"
DB_PATH = EVIDENCE_DIR / "P1-B24_runtime.db"
COURSE_ID = "course-p1-b24-browser"
COURSE_TITLE = "机器学习工程"
PASSWORD = "P1-B24-browser-2026!"


def _helpers():
    path = ROOT / "scripts" / "e2e_acceptance_p1_b03_legacy_profile_fusion.py"
    spec = importlib.util.spec_from_file_location("p1_b24_helpers", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.PORT = PORT
    module.BASE_URL = BASE_URL
    module.DB_PATH = DB_PATH
    module.COURSE_ID = COURSE_ID
    module.COURSE_TITLE = COURSE_TITLE
    module.PASSWORD = PASSWORD
    return module


def _metrics(page):
    return page.locator(".dashboard-page").evaluate(
        """(root) => {
          const visible = (el) => {
            const s = getComputedStyle(el), b = el.getBoundingClientRect()
            return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0 && b.width > 1 && b.height > 1
          }
          const topbar = document.querySelector('.app-topbar')?.getBoundingClientRect()
          const pageElement = document.querySelector('.app-content__page')
          const pageStyle = pageElement ? getComputedStyle(pageElement) : null
          const heading = root.querySelector('.dashboard-heading h1')?.getBoundingClientRect()
          const smallText = [...root.querySelectorAll('*')]
            .filter((el) => visible(el) && !el.children.length && (el.innerText || '').trim() && parseFloat(getComputedStyle(el).fontSize) < 13.5)
            .map((el) => ({ text: el.innerText.trim().slice(0, 50), size: getComputedStyle(el).fontSize }))
          const box = root.getBoundingClientRect()
          const gap = topbar && heading ? heading.top - topbar.bottom : null
          return {
            viewport: [innerWidth, innerHeight], documentWidth: document.documentElement.scrollWidth,
            targetBounds: { left: box.left, right: box.right }, targetScrollWidth: root.scrollWidth,
            targetClientWidth: root.clientWidth, topbarBottom: topbar?.bottom ?? null,
            headingTop: heading?.top ?? null, pageHeaderToContentGap: gap,
            pagePaddingLeft: pageStyle ? parseFloat(pageStyle.paddingLeft) : null,
            pagePaddingRight: pageStyle ? parseFloat(pageStyle.paddingRight) : null,
            smallText
          }
        }"""
    )


def _capture(page, name: str, report: dict) -> None:
    page.locator(".dashboard-page").wait_for(state="visible", timeout=45_000)
    page.wait_for_timeout(500)
    metrics = _metrics(page)
    assert metrics["pageHeaderToContentGap"] >= 20, metrics
    assert metrics["pagePaddingLeft"] >= 16 and metrics["pagePaddingRight"] >= 16, metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["targetBounds"]["left"] >= -1 and metrics["targetBounds"]["right"] <= metrics["viewport"][0] + 1, metrics
    assert metrics["targetScrollWidth"] <= metrics["targetClientWidth"] + 1, metrics
    assert not metrics["smallText"], metrics
    page.screenshot(path=str(EVIDENCE_DIR / name), full_page=False)
    report["screenshots"].append(name)
    report["metrics"][name] = metrics


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "acceptance-feedback.p1-b24.dashboard-spacing-browser.v1",
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "course": {"id": COURSE_ID, "title": COURSE_TITLE, "version": "1"},
        "screenshots": [], "metrics": {}, "browser_errors": [], "http_errors": [],
    }
    helpers = _helpers()
    process = None
    try:
        env = os.environ.copy()
        env.update({
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "p1-b24-browser-isolated-secret",
            "EDUMATRIX_ONBOARDING_V2": "1",
            "EDUMATRIX_LLM_PROVIDER": "deterministic",
            "EDUMATRIX_LLM_MODEL": "deterministic",
            "EDUMATRIX_LLM_API_KEY": "",
            "EDUMATRIX_LLM_ENDPOINT": "",
            "EDUMATRIX_RELOAD": "0",
            "EDUMATRIX_HOST": "127.0.0.1",
            "EDUMATRIX_PORT": str(PORT),
            "EDUMATRIX_SANDBOX_MODE": "disabled",
            "PYTHONUNBUFFERED": "1",
        })
        with (EVIDENCE_DIR / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            helpers.wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                setup = browser.new_page()
                suffix = str(int(time.time() * 1000))
                user = helpers.register(setup, f"p1_b24_browser_{suffix}", "首页留白验收学生")
                helpers.attach_course(user["username"])
                helpers.complete_initial_onboarding(setup, user)
                setup.close()

                for width, height, name in [
                    (1440, 900, "1440x900-dashboard-spacing.png"),
                    (1366, 768, "1366x768-dashboard-spacing.png"),
                ]:
                    context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
                    page = context.new_page()
                    page.on("pageerror", lambda error: report["browser_errors"].append(str(error)))
                    page.on("response", lambda response: report["http_errors"].append({"status": response.status, "url": response.url}) if response.status >= 400 else None)
                    helpers.login(page, user)
                    page.goto(f"{BASE_URL}/?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=30_000)
                    page.get_by_test_id("dashboard-course-alignment").wait_for(state="visible", timeout=60_000)
                    _capture(page, name, report)
                    context.close()
                browser.close()
        if report["browser_errors"] or report["http_errors"]:
            raise AssertionError({"browser_errors": report["browser_errors"], "http_errors": report["http_errors"]})
        report["result"] = "passed"
    except Exception as error:
        report["result"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=20)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (EVIDENCE_DIR / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
