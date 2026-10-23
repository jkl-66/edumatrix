"""Dual-desktop browser evidence for the FB-FE-01 layout contract."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("FB_FE_01_BASE_URL", "http://127.0.0.1:5173").rstrip("/")
OUTPUT_DIR = Path(
    os.getenv(
        "FB_FE_01_OUTPUT_DIR",
        str(ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "post_audit_fusion_v2" / "FB-FE-01_browser"),
    )
).resolve()
USERNAME = os.getenv("FB_FE_01_USERNAME", "lzz")
PASSWORD = os.getenv("FB_FE_01_PASSWORD", "404404aA")
COURSE_ID = "demo-course-rag-trust-v1"
COURSE_TITLE = "RAG 应用开发与负责任评测实训"

ROUTES = {
    "workspace": (f"/workspace?course_id={COURSE_ID}", ".workspace-page", "学习空间"),
    "resources": (f"/workspace/resources?course_id={COURSE_ID}", '[data-testid="resource-center"]', "资源中心"),
    "notes": (f"/workspace/notes?course_id={COURSE_ID}", '[data-testid="notes-workspace"]', "笔记本"),
    "wrong_questions": (f"/workspace/review/wrong-questions?course_id={COURSE_ID}", '[data-testid="wrong-question-workspace"]', "错题本"),
}
ONLY_ROUTE = os.getenv("FB_FE_01_ONLY", "").strip()


def launch_browser(playwright: Playwright) -> tuple[Browser, str]:
    try:
        return playwright.chromium.launch(headless=True), "playwright-chromium"
    except Exception:
        return playwright.chromium.launch(channel="msedge", headless=True), "system-edge"


def rect_payload(rect) -> dict[str, float]:
    return {
        "x": round(rect["x"], 2),
        "y": round(rect["y"], 2),
        "width": round(rect["width"], 2),
        "height": round(rect["height"], 2),
        "right": round(rect["right"], 2),
        "bottom": round(rect["bottom"], 2),
    }


def inspect_layout(page: Page) -> dict[str, object]:
    return page.evaluate(
        """
        () => {
          const selectors = [
            '.app-shell', '.app-sidebar', '.app-content__layout', '.workspace-subnav',
            '.workspace-grid', '.today-learning-layout', '.today-learning-main', '.today-learning-rail',
            '.resource-workspace', '.type-rail', '.catalog-panel', '.resource-preview',
            '.notes-shell', '.notes-sidebar', '.note-document', '.note-context',
            '.wrong-grid', '.question-list', '.detail-pane'
          ];
          const rect = (selector) => {
            const node = document.querySelector(selector);
            if (!node) return null;
            const box = node.getBoundingClientRect();
            return {x: box.x, y: box.y, width: box.width, height: box.height, right: box.right, bottom: box.bottom};
          };
          const firstNav = document.querySelector('.app-nav .sidebar-item');
          const navStyle = firstNav ? getComputedStyle(firstNav) : null;
          const visibleRightOverflow = [...document.querySelectorAll('body *')]
            .filter((node) => {
              const style = getComputedStyle(node);
              if (style.display === 'none' || style.visibility === 'hidden') return false;
              const box = node.getBoundingClientRect();
              return box.width > 0 && box.right > window.innerWidth + 1;
            })
            .slice(0, 12)
            .map((node) => ({tag: node.tagName, className: String(node.className || '').slice(0, 100), right: node.getBoundingClientRect().right}));
          const visibleLeftOverflow = [...document.querySelectorAll('body *')]
            .filter((node) => {
              const style = getComputedStyle(node);
              if (style.display === 'none' || style.visibility === 'hidden') return false;
              const box = node.getBoundingClientRect();
              return box.width > 0 && box.left < -1;
            })
            .slice(0, 12)
            .map((node) => ({tag: node.tagName, className: String(node.className || '').slice(0, 100), left: node.getBoundingClientRect().left}));
          return {
            viewport: {width: window.innerWidth, height: window.innerHeight},
            document: {clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth, clientHeight: document.documentElement.clientHeight, scrollHeight: document.documentElement.scrollHeight},
            rectangles: Object.fromEntries(selectors.map((selector) => [selector, rect(selector)])),
            nav: navStyle ? {flexDirection: navStyle.flexDirection, minHeight: navStyle.minHeight, fontSize: navStyle.fontSize, lineHeight: navStyle.lineHeight, display: navStyle.display} : null,
            overflow: {visibleRightOverflow, visibleLeftOverflow},
            text: (document.body.innerText || '').slice(0, 500),
          };
        }
        """
    )


def screenshot(page: Page, name: str) -> str:
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT)).replace("\\", "/")


def wait_for_route(page: Page, route: str, marker: str, text: str) -> None:
    page.goto(f"{BASE_URL}{route}", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_function("() => (document.body.innerText || '').trim().length > 30", timeout=30_000)
    page.locator(marker).wait_for(state="attached", timeout=60_000)
    page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=30_000)
    page.wait_for_timeout(900)


def create_route_context(browser: Browser, viewport: tuple[int, int], state: dict[str, str]) -> BrowserContext:
    """Keep each route/viewport run isolated from SPA and storage state left by another run."""
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    serialized = json.dumps(state, ensure_ascii=False)
    context.add_init_script(f"""
      const state = {serialized};
      localStorage.setItem('edumatrix_token', state.token);
      localStorage.setItem('edumatrix_username', state.username);
      localStorage.setItem('edumatrix_display_name', state.displayName);
      localStorage.setItem('edumatrix_role', state.role);
      localStorage.setItem('edumatrix_student_id', state.studentId);
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', state.courseId);
      localStorage.setItem('edumatrix_course_title', state.courseTitle);
      localStorage.removeItem('edumatrix_context_ref');
    """)
    return context


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "task_id": "FB-FE-01",
        "base_url": BASE_URL,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "viewports": {},
        "result": "failed",
    }
    with sync_playwright() as playwright:
        browser, browser_source = launch_browser(playwright)
        report["browser"] = browser_source
        page_errors: list[str] = []
        console_errors: list[str] = []
        failed_requests: list[str] = []
        auth_context = browser.new_context(locale="zh-CN")
        try:
            login = auth_context.request.post(f"http://127.0.0.1:8000/api/auth/login", form={"username": USERNAME, "password": PASSWORD})
            if not login.ok:
                raise RuntimeError(f"demo learner login failed: {login.status} {login.text()[:300]}")
            session = login.json()
            state = json.dumps({
                "token": session["access_token"],
                "username": session.get("username") or USERNAME,
                "displayName": session.get("display_name") or session.get("username") or USERNAME,
                "role": session.get("role") or "student",
                "studentId": session.get("student_id") or session.get("username") or USERNAME,
                "courseId": COURSE_ID,
                "courseTitle": COURSE_TITLE,
            }, ensure_ascii=False)
            state_payload = json.loads(state)

            for viewport in ((1366, 768), (1440, 900)):
                width, height = viewport
                viewport_key = f"{width}x{height}"
                report["viewports"][viewport_key] = {}
                route_items = ((key, value) for key, value in ROUTES.items() if not ONLY_ROUTE or key == ONLY_ROUTE)
                for key, (route, marker, required_text) in route_items:
                    route_context = create_route_context(browser, viewport, state_payload)
                    route_page = route_context.new_page()
                    route_events: list[str] = []
                    route_page.on("request", lambda request: route_events.append(f"request {request.method} {request.url}"))
                    route_page.on("response", lambda response: route_events.append(f"response {response.status} {response.url}"))
                    route_page.on("pageerror", lambda error: page_errors.append(str(error)))
                    route_page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
                    route_page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))
                    before_errors = (len(page_errors), len(console_errors), len(failed_requests))
                    page = route_page
                    try:
                        wait_for_route(route_page, route, marker, required_text)
                        layout = inspect_layout(route_page)
                        image_name = f"{key}-{viewport_key}"
                        relative_image = screenshot(route_page, image_name)
                        report["viewports"][viewport_key][key] = {
                            "route": route,
                            "url_after_navigation": route_page.url,
                            "required_text": required_text,
                            "layout": layout,
                            "screenshot": relative_image,
                            "diagnostics_delta": {
                                "page_errors": len(page_errors) - before_errors[0],
                                "console_errors": len(console_errors) - before_errors[1],
                                "failed_requests": len(failed_requests) - before_errors[2],
                            },
                        }
                    except Exception as route_error:
                        report["viewports"][viewport_key][key] = {
                            "route": route,
                            "url_after_navigation": route_page.url,
                            "error": f"{type(route_error).__name__}: {route_error}"[:600],
                            "body_text": (route_page.locator("body").inner_text(timeout=3) if route_page.locator("body").count() else "")[:1200],
                            "performance_resources": route_page.evaluate("() => performance.getEntriesByType('resource').map(entry => entry.name).slice(-80)"),
                            "route_events": route_events[-120:],
                            "page_errors": page_errors[before_errors[0]:],
                            "console_errors": console_errors[before_errors[1]:],
                            "failed_requests": failed_requests[before_errors[2]:],
                            "debug_screenshot": screenshot(route_page, f"{key}-{viewport_key}-debug"),
                        }
                        raise
                    finally:
                        route_page.close()
                        route_context.close()

            report["diagnostics"] = {
                "page_errors": page_errors,
                "console_errors": console_errors,
                "failed_requests": failed_requests,
            }
            report["result"] = "passed" if not page_errors and not console_errors and not failed_requests else "failed"
            return 0 if report["result"] == "passed" else 1
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"[:600]
            try:
                report["error_screenshot"] = screenshot(page, "error")
            except Exception:
                pass
            return 1
        finally:
            report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            (OUTPUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            auth_context.close()
            browser.close()
            print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
