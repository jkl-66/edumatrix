"""Narrow evaluator smoke for the Windows no-Docker competition package.

The backend must already be running in deterministic + trusted_local mode. The
script uses the frozen ``lzz`` demo learner, renders only the current public and
core student routes, and verifies both allowed and blocked code execution. It
does not replace the full F10 desktop acceptance suite.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from playwright.sync_api import Browser, Page, Playwright, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("EDUMATRIX_E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
OUTPUT_DIR = Path(
    os.getenv("EDUMATRIX_E2E_OUTPUT_DIR", str(ROOT / "outputs" / "e2e_no_docker"))
).resolve()
EXPECTED_SANDBOX_MODE = "trusted_local"
USERNAME = "lzz"
PASSWORD = "404404aA"


def launch_browser(playwright: Playwright) -> tuple[Browser, str]:
    """Prefer the bundled browser, then the Edge installation present on Windows."""
    try:
        return playwright.chromium.launch(headless=True), "playwright-chromium"
    except Exception:
        try:
            return playwright.chromium.launch(channel="msedge", headless=True), "system-edge"
        except Exception as edge_error:
            raise RuntimeError(
                "No Chromium runtime is available. Install Playwright Chromium or keep Microsoft Edge installed."
            ) from edge_error


def screenshot(page: Page, name: str) -> str:
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def wait_for_page(page: Page, route: str, required_text: str, content_text: str | None = None) -> None:
    page.goto(f"{BASE_URL}{route}", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_function("() => (document.body.innerText || '').trim().length >= 40", timeout=30_000)
    page.get_by_text(required_text, exact=False).first.wait_for(state="visible", timeout=30_000)
    if content_text:
        page.get_by_text(content_text, exact=False).first.wait_for(state="visible", timeout=30_000)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "mode": EXPECTED_SANDBOX_MODE,
        "base_url": BASE_URL,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "screenshots": [],
        "checks": {},
    }

    with sync_playwright() as playwright:
        browser, browser_source = launch_browser(playwright)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        page = context.new_page()
        page_errors: list[str] = []
        console_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )

        try:
            health_response = context.request.get(f"{BASE_URL}/api/health")
            status_response = context.request.get(f"{BASE_URL}/api/code/status")
            health = health_response.json()
            status = status_response.json()
            assert health_response.ok and health.get("status") == "ok", health
            assert status_response.ok and status.get("mode") == EXPECTED_SANDBOX_MODE, status
            assert status.get("execution_enabled") is True, status
            assert status.get("isolation") == "trusted_local_child_process", status
            report["checks"]["health"] = {"status": health.get("status")}
            report["checks"]["sandbox_status"] = {
                "mode": status.get("mode"),
                "execution_enabled": status.get("execution_enabled"),
                "isolation": status.get("isolation"),
                "security_level": status.get("security_level"),
            }
            report["checks"]["browser"] = browser_source

            wait_for_page(page, "/landing", "EduMatrix")
            report["checks"]["landing_page"] = {"loaded": True, "route": "/landing"}
            report["screenshots"].append(screenshot(page, "01-landing"))

            wait_for_page(page, "/login", "登录")
            report["checks"]["login_page"] = {"loaded": True, "route": "/login"}
            report["screenshots"].append(screenshot(page, "02-login"))

            login = context.request.post(
                f"{BASE_URL}/api/auth/login",
                form={"username": USERNAME, "password": PASSWORD},
            )
            assert login.ok, f"demo learner login failed: {login.status} {login.text()}"
            session = login.json()
            catalog_response = context.request.get(
                f"{BASE_URL}/api/knowledge/courses",
                headers={"Authorization": f"Bearer {session['access_token']}"},
            )
            assert catalog_response.ok, f"course catalog failed: {catalog_response.status} {catalog_response.text()}"
            catalog = catalog_response.json()
            courses = [
                *(catalog.get("shelf") or []),
                *(catalog.get("recommendations") or []),
            ]
            current_course = next((course for course in courses if course.get("id") and course.get("selectable", True)), None)
            assert current_course, "no selectable current course in catalog"
            course_id = str(current_course["id"])
            course_title = str(current_course.get("title") or course_id)
            state = json.dumps(
                {
                    "token": session["access_token"],
                    "username": session.get("username") or USERNAME,
                    "displayName": session.get("display_name") or session.get("username") or USERNAME,
                    "role": session.get("role") or "student",
                    "studentId": session.get("student_id") or session.get("username") or USERNAME,
                    "courseId": course_id,
                    "courseTitle": course_title,
                },
                ensure_ascii=False,
            )
            context.add_init_script(
                f"""
                const state = {state};
                localStorage.setItem('edumatrix_token', state.token);
                localStorage.setItem('edumatrix_username', state.username);
                localStorage.setItem('edumatrix_display_name', state.displayName);
                localStorage.setItem('edumatrix_role', state.role);
                localStorage.setItem('edumatrix_student_id', state.studentId);
                localStorage.setItem('edumatrix_onboarded', 'true');
                localStorage.setItem('edumatrix_course_id', state.courseId);
                localStorage.setItem('edumatrix_course_title', state.courseTitle);
                """
            )

            wait_for_page(page, f"/workspace?course_id={course_id}", "学习空间", "课程进度")
            report["checks"]["learning_workspace"] = {"loaded": True, "route": "/workspace"}
            report["screenshots"].append(screenshot(page, "03-learning-workspace"))

            wait_for_page(page, f"/knowledge?course_id={course_id}", "知识库", "我的书架")
            assert page.get_by_text(course_title, exact=False).count() > 0
            report["checks"]["knowledge_page"] = {
                "loaded": True,
                "route": "/knowledge",
                "course_id": course_id,
                "course_title": course_title,
                "prebuilt_course_visible": True,
            }
            report["screenshots"].append(screenshot(page, "04-knowledge"))

            authorization = {"Authorization": f"Bearer {session['access_token']}"}
            safe = context.request.post(
                f"{BASE_URL}/api/code/run",
                headers=authorization,
                data={"language": "python", "code": "print(6 * 7)"},
            )
            safe_payload = safe.json()
            assert safe.ok and "42" in str(safe_payload.get("output", "")), safe_payload
            report["checks"]["safe_execution"] = {
                "passed": True,
                "output_contains_42": True,
            }

            blocked = context.request.post(
                f"{BASE_URL}/api/code/run",
                headers=authorization,
                data={"language": "python", "code": "import os\nos.system('echo unsafe')"},
            )
            blocked_payload = blocked.json()
            assert blocked.ok, blocked_payload
            assert not str(blocked_payload.get("output", "")), blocked_payload
            assert str(blocked_payload.get("error", "")), blocked_payload
            report["checks"]["blocked_execution"] = {
                "passed": True,
                "output_empty": True,
                "error_present": True,
            }

            assert not page_errors, page_errors
            assert not console_errors, console_errors
            report["checks"]["browser_diagnostics"] = {
                "page_errors": 0,
                "console_errors": 0,
            }
            report["result"] = "passed"
            return 0
        except Exception as exc:
            report["result"] = "failed"
            report["error"] = f"{type(exc).__name__}: {exc}"[:500]
            try:
                report["screenshots"].append(screenshot(page, "error"))
            except Exception:
                pass
            return 1
        finally:
            report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            (OUTPUT_DIR / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            context.close()
            browser.close()
            print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
