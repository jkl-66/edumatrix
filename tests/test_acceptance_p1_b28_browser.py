from __future__ import annotations

import json
import os
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("EDUMATRIX_RUN_BROWSER") != "1",
    reason="B28 browser evidence is an explicit opt-in check",
)


class _SpaHandler(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        requested = Path(self.directory) / parsed.path.lstrip("/")
        if parsed.path.startswith("/api/"):
            self.send_error(404)
            return
        if not requested.is_file():
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, _format, *_args):
        return


@contextmanager
def _frontend_server():
    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        pytest.fail("frontend/dist/index.html 不存在，请先运行 npm run build")

    def handler(*args, **kwargs):
        return _SpaHandler(*args, directory=str(dist), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def _install_api_mocks(page):
    course_id = "b28-browser-course"
    courses = [{
        "id": course_id,
        "title": "机器学习语义课程",
        "description": "资源货架浏览 fixture",
        "subject": "机器学习",
        "domain_pack": "machine-learning",
        "version": "1",
        "language": "中文",
        "can_manage": True,
        "source_health": "ready",
        "index_status": "ready",
        "chapter_count": 3,
        "document_count": 2,
        "knowledge_point_count": 3,
        "source_count": 2,
    }]
    outline = [
        {"id": "ch-1", "title": "第一章 语义基础", "position": 1, "parent_id": None, "source_document_id": "src-docx", "source_ref_id": "ref-1", "knowledge_points": [{"id": "kp-1", "code": "KP-1", "title": "语义检索"}]},
        {"id": "ch-2", "title": "第二章 证据约束", "position": 2, "parent_id": None, "source_document_id": "src-docx", "source_ref_id": "ref-2", "knowledge_points": [{"id": "kp-2", "code": "KP-2", "title": "证据定位"}]},
        {"id": "ch-3", "title": "演示资源", "position": 3, "parent_id": None, "source_document_id": "src-pptx", "source_ref_id": "ref-3", "knowledge_points": [{"id": "kp-3", "code": "KP-3", "title": "模型演示"}]},
    ]
    sources = {
        "src-docx": {"id": "src-docx", "title": "语义章节讲义", "file_type": "docx", "content": "这是 DOCX 资源预览正文。", "source_processing_status": "ready"},
        "src-pptx": {"id": "src-pptx", "title": "模型演示课件", "file_type": "pptx", "content": "这是 PPTX 资源预览正文。", "source_processing_status": "ready"},
    }

    def respond(route, payload, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))

    def handle(route):
        parsed = urlparse(route.request.url)
        path = parsed.path
        if path.endswith("/api/auth/me"):
            respond(route, {"public_id": "b28-browser-user", "username": "b28-browser", "display_name": "B28 浏览器验收", "role": "student"})
        elif path.endswith("/api/health"):
            respond(route, {"status": "ok"})
        elif path.endswith("/api/knowledge/courses"):
            respond(route, {"schema_version": "edumatrix.knowledge-course-shelf.v1", "shelf": courses, "recommendations": []})
        elif path.endswith(f"/api/v1/courses/{course_id}/outline"):
            respond(route, outline)
        elif "/api/knowledge/sources/" in path:
            source_id = path.rsplit("/", 1)[-1]
            respond(route, sources.get(source_id, {}), 200 if source_id in sources else 404)
        elif "cross-language-search" in path:
            respond(route, {"items": [], "status": "empty"})
        else:
            respond(route, {})

    page.route("**/api/**", handle)
    return course_id


def _assert_layout(page, width: int, height: int, screenshot_dir: Path):
    page.screenshot(path=str(screenshot_dir / f"{width}x{height}.png"), full_page=True)
    layout = page.evaluate(
        """() => {
          const root = document.querySelector('[data-testid=course-resource-shelf]')?.closest('[data-testid=course-workspace]');
          const visible = [...document.querySelectorAll('[data-testid=course-workspace] *')]
            .filter((el) => el.getClientRects().length && el.textContent.trim());
          const smallText = visible.filter((el) => {
            const style = getComputedStyle(el);
            return el.children.length === 0 && Number.parseFloat(style.fontSize) < 14;
          }).map((el) => el.textContent.trim().slice(0, 40));
          return {
            viewportWidth: window.innerWidth,
            viewportHeight: window.innerHeight,
            documentWidth: document.documentElement.scrollWidth,
            bodyWidth: document.body.scrollWidth,
            rootRight: root ? root.getBoundingClientRect().right : 0,
            smallText,
          };
        }"""
    )
    assert layout["documentWidth"] <= width + 1, layout
    assert layout["bodyWidth"] <= width + 1, layout
    assert layout["rootRight"] <= width + 1, layout
    assert layout["smallText"] == [], layout["smallText"]
    return layout


def test_course_resource_shelf_two_desktop_viewports():
    from playwright.sync_api import sync_playwright

    screenshot_dir = Path(__file__).resolve().parents[1] / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B28"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    with _frontend_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_init_script(
                    "localStorage.setItem('edumatrix_token', 'browser-token');"
                    "localStorage.setItem('edumatrix_role', 'student');"
                    "localStorage.setItem('edumatrix_onboarded', 'true');"
                )
                page = context.new_page()
                browser_errors = []
                page.on("pageerror", lambda error: browser_errors.append(str(error)))
                course_id = _install_api_mocks(page)
                page.goto(f"{base_url}/knowledge/courses/{course_id}", wait_until="networkidle")
                page.get_by_test_id("course-resource-shelf").wait_for()
                assert page.get_by_test_id("resource-filters").is_visible()
                assert page.get_by_test_id("selected-resource-detail").is_visible()
                assert page.get_by_test_id("open-course-structure").is_visible()
                page.get_by_test_id("resource-card-src-pptx").wait_for()
                page.get_by_role("button", name="演示").click()
                page.get_by_role("heading", name="模型演示课件").wait_for()
                assert page.get_by_role("heading", name="模型演示课件").is_visible()
                page.get_by_test_id("resource-card-src-pptx").click()
                page.get_by_text("PPTX 资源预览").wait_for()
                assert "PPTX 资源预览" in page.get_by_test_id("selected-resource-detail").inner_text()
                page.get_by_role("button", name="全部资源").click()
                assert page.get_by_test_id("resource-card-src-docx").is_visible()
                assert page.get_by_test_id("resource-card-src-pptx").is_visible()
                page.get_by_test_id("open-course-structure").press("Enter")
                assert not browser_errors, browser_errors
                reports.append({"viewport": {"width": width, "height": height}, "layout": _assert_layout(page, width, height, screenshot_dir), "resource_filter_verified": True, "resource_detail_verified": True, "page_errors": browser_errors})
                context.close()
        finally:
            browser.close()
    (screenshot_dir / "browser-report.json").write_text(json.dumps({"task_id": "ACCEPTANCE-FEEDBACK-P1-B28", "status": "passed", "viewports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
