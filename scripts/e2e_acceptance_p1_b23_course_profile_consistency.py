"""Isolated desktop evidence for FB-23 course/profile alignment."""

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
PORT = 8913
BASE_URL = f"http://127.0.0.1:{PORT}"
EVIDENCE_DIR = ROOT / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B23"
DB_PATH = EVIDENCE_DIR / "P1-B23_runtime.db"
COURSE_ID = "course-p1-b23-browser"
COURSE_TITLE = "机器学习工程"
PASSWORD = "P1-B23-browser-2026!"


def _b03_helpers():
    path = ROOT / "scripts" / "e2e_acceptance_p1_b03_legacy_profile_fusion.py"
    spec = importlib.util.spec_from_file_location("p1_b03_helpers", path)
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


def _metrics(page, selector: str) -> dict:
    return page.locator(selector).evaluate(
        """(root) => {
          const visible = (el) => {
            const s = getComputedStyle(el), b = el.getBoundingClientRect()
            return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) > 0 && b.width > 1 && b.height > 1
          }
          const smallText = [...root.querySelectorAll('*')].filter((el) => visible(el) && !el.children.length && (el.innerText || '').trim() && parseFloat(getComputedStyle(el).fontSize) < 13.5)
            .map((el) => ({ text: el.innerText.trim().slice(0, 50), size: getComputedStyle(el).fontSize }))
          const box = root.getBoundingClientRect()
          return { viewport: [innerWidth, innerHeight], documentWidth: document.documentElement.scrollWidth,
            targetBounds: { left: box.left, right: box.right }, targetScrollWidth: root.scrollWidth,
            targetClientWidth: root.clientWidth, smallText }
        }"""
    )


def _capture(page, selector: str, name: str, report: dict) -> None:
    page.locator(selector).wait_for(state="visible", timeout=45_000)
    page.wait_for_timeout(500)
    metrics = _metrics(page, selector)
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
        "schema_version": "acceptance-feedback.p1-b23.course-profile-browser.v1",
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "course": {"id": COURSE_ID, "title": COURSE_TITLE, "version": "1"},
        "screenshots": [], "metrics": {}, "browser_errors": [], "http_errors": [],
    }
    helpers = _b03_helpers()
    process = None
    try:
        env = os.environ.copy()
        env.update({
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "p1-b23-browser-isolated-secret",
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
                user = helpers.register(setup, f"p1_b23_browser_{suffix}", "课程一致性验收学生")
                helpers.attach_course(user["username"])
                helpers.complete_initial_onboarding(setup, user)
                helpers.seed_legacy_profile(user["username"], "partial")
                setup.close()

                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page()
                page.on("pageerror", lambda error: report["browser_errors"].append(str(error)))
                page.on("response", lambda response: report["http_errors"].append({"status": response.status, "url": response.url}) if response.status >= 400 else None)
                helpers.login(page, user)
                page.goto(f"{BASE_URL}/?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=30_000)
                page.get_by_test_id("dashboard-course-alignment").wait_for(state="visible", timeout=60_000)
                alignment = page.get_by_test_id("dashboard-course-alignment").inner_text()
                assert COURSE_ID in alignment and "v1" in alignment
                _capture(page, ".dashboard-page", "1440x900-dashboard.png", report)
                context.close()

                context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
                page = context.new_page()
                page.on("pageerror", lambda error: report["browser_errors"].append(str(error)))
                page.on("response", lambda response: report["http_errors"].append({"status": response.status, "url": response.url}) if response.status >= 400 else None)
                helpers.login(page, user)
                page.goto(f"{BASE_URL}/profile/learning?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=30_000)
                page.get_by_test_id("profile-summary").wait_for(state="visible", timeout=60_000)
                migration = page.get_by_test_id("legacy-profile-migration")
                try:
                    migration.wait_for(state="visible", timeout=60_000)
                except Exception:
                    report["profile_debug"] = {
                        "url": page.url,
                        "text": page.locator(".profile-view").inner_text(timeout=5_000),
                        "summary_html": page.get_by_test_id("profile-summary").inner_html(timeout=5_000),
                    }
                    page.screenshot(path=str(EVIDENCE_DIR / "1366x768-student-analysis-debug.png"), full_page=False)
                    raise AssertionError("legacy-profile-migration panel is not visible")
                assert "legacy-profile-map.v1" in migration.inner_text()
                _capture(page, ".profile-view", "1366x768-student-analysis.png", report)
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
