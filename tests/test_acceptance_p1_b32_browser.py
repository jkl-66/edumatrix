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
    reason="B32 browser evidence is an explicit opt-in check",
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


def _attachment(attachment_id: str, filename: str, status: str, **extra) -> dict:
    can_send = status == "ready" or (status == "partial_failed" and extra.get("partialConfirmed", False))
    return {
        "id": attachment_id,
        "conversationId": "chat-b32-browser",
        "filename": filename,
        "fileFormat": "pdf",
        "mimeType": "application/pdf",
        "fileSize": 2048,
        "sourceSha256": f"sha-{attachment_id}",
        "parserVersion": "fixture",
        "parseVersion": 1,
        "status": status,
        "stage": "ready" if status == "ready" else status,
        "progress": 1 if status in {"ready", "failed_retryable", "partial_failed"} else 0.4,
        "summary": {"page_count": 2},
        "parsedPreview": "fixture",
        "locations": [],
        "warnings": extra.get("warnings", []),
        "failure": {"code": "fixture_failure", "message": extra.get("failureMessage", "解析失败，请重试"), "retryable": True}
        if status in {"failed_retryable", "partial_failed"}
        else None,
        "partialConfirmed": extra.get("partialConfirmed", False),
        "canSend": can_send,
        "lockVersion": 1,
        "createdAt": "2026-08-26T08:00:00Z",
        "updatedAt": "2026-08-26T08:00:00Z",
    }


def _install_api_mocks(page, requests):
    attachments = [
        _attachment("b32-ready", "ready.pdf", "ready"),
        _attachment("b32-parsing", "parsing.pdf", "parsing"),
        _attachment("b32-failed", "failed.pdf", "failed_retryable", failureMessage="解析失败，可重试"),
        _attachment("b32-partial", "partial.pdf", "partial_failed", failureMessage="部分页面解析失败"),
    ]
    conversation = {
        "id": "chat-b32-browser",
        "courseId": None,
        "courseIds": [],
        "courses": [],
        "contextMode": "general",
        "title": "B32 附件折叠",
        "status": "active",
        "lockVersion": 1,
        "createdAt": "2026-08-26T08:00:00Z",
        "updatedAt": "2026-08-26T08:00:00Z",
        "messages": [],
        "attachments": attachments,
    }

    def respond(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body, ensure_ascii=False))

    def handle(route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        method = request.method.upper()
        if path.endswith("/api/auth/me"):
            respond(route, {"public_id": "b32-browser-user", "username": "b32-browser", "display_name": "B32 浏览器验收", "role": "student"})
            return
        if path.endswith("/api/health"):
            respond(route, {"status": "ok"})
            return
        if path.endswith("/api/v1/chat/courses") and method == "GET":
            requests.append((method, path))
            respond(route, {"schemaVersion": "edumatrix.chat-course-catalog.v1", "courses": []})
            return
        if path.endswith("/api/v1/chat/conversations") and method == "GET":
            requests.append((method, path))
            respond(route, {"schemaVersion": "edumatrix.chat-conversation-list.v1", "items": [conversation]})
            return
        if path.endswith("/api/v1/chat/conversations/chat-b32-browser") and method == "GET":
            requests.append((method, path))
            respond(route, conversation)
            return
        if "/api/v1/chat/" in path:
            # Any mutation would violate the presentation-only disclosure contract.
            requests.append((method, path))
            respond(route, {"detail": "unexpected mutation"}, status=500)
            return
        respond(route, {})

    page.route("**/api/**", handle)


def test_attachment_disclosure_preserves_ids_states_selection_and_keyboard(tmp_path):
    from playwright.sync_api import sync_playwright

    evidence = Path(__file__).resolve().parents[1] / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B32"
    evidence.mkdir(parents=True, exist_ok=True)
    reports = []

    with _frontend_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_init_script(
                    "localStorage.setItem('edumatrix_token', 'b32-browser-token');"
                    "localStorage.setItem('edumatrix_role', 'student');"
                    "localStorage.setItem('edumatrix_onboarded', 'true');"
                )
                page = context.new_page()
                page_errors = []
                requests = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                _install_api_mocks(page, requests)
                page.goto(f"{base_url}/learn", wait_until="networkidle")
                queue = page.get_by_test_id("chat-attachment-queue")
                queue.wait_for()
                rows = queue.locator(".attachment-row")
                assert rows.count() == 4
                ids_before = rows.evaluate_all("nodes => nodes.map(node => node.id)")
                statuses_before = rows.evaluate_all("nodes => nodes.map(node => node.dataset.status)")
                queue.locator(".attachment-row").nth(0).locator("label.attachment-select").click()
                assert queue.locator(".attachment-row").nth(0).locator("input[type=checkbox]").is_checked()

                toggle = page.get_by_test_id("chat-attachment-toggle")
                assert toggle.get_attribute("aria-expanded") == "true"
                assert "4 个附件" in queue.locator(".attachment-queue__summary").inner_text()
                toggle.click()
                assert toggle.get_attribute("aria-expanded") == "false"
                page.locator("#chat-attachment-list").wait_for(state="hidden")
                assert "4 个附件" in queue.locator(".attachment-queue__summary").inner_text()
                assert requests == [("GET", "/api/v1/chat/courses"), ("GET", "/api/v1/chat/conversations"), ("GET", "/api/v1/chat/conversations/chat-b32-browser")]

                toggle.focus()
                toggle.press("Space")
                page.locator("#chat-attachment-list").wait_for(state="visible")
                assert toggle.get_attribute("aria-expanded") == "true"
                assert rows.evaluate_all("nodes => nodes.map(node => node.id)") == ids_before
                assert rows.evaluate_all("nodes => nodes.map(node => node.dataset.status)") == statuses_before
                assert rows.nth(0).locator("input[type=checkbox]").is_checked()
                assert rows.nth(2).get_by_role("button", name="重试解析").is_visible()
                assert rows.nth(3).get_by_role("button", name="确认可用部分").is_visible()

                toggle.press("Enter")
                page.locator("#chat-attachment-list").wait_for(state="hidden")
                toggle.press("Enter")
                page.locator("#chat-attachment-list").wait_for(state="visible")
                assert not page_errors, page_errors
                geometry = page.evaluate(
                    """() => ({
                      documentWidth: document.documentElement.scrollWidth,
                      bodyWidth: document.body.scrollWidth,
                      viewportWidth: window.innerWidth,
                      toggleRight: document.querySelector('[data-testid=chat-attachment-toggle]')?.getBoundingClientRect().right || 0,
                      summaryFont: Number.parseFloat(getComputedStyle(document.querySelector('.attachment-queue__summary > span')).fontSize),
                    })"""
                )
                assert geometry["documentWidth"] <= width + 1, geometry
                assert geometry["bodyWidth"] <= width + 1, geometry
                assert geometry["toggleRight"] <= width + 1, geometry
                assert geometry["summaryFont"] >= 14, geometry
                screenshot = evidence / f"chat-attachments-{width}x{height}.png"
                page.screenshot(path=str(screenshot), full_page=True)
                reports.append({"viewport": {"width": width, "height": height}, "geometry": geometry, "ids": ids_before, "statuses": statuses_before, "requests": requests, "page_errors": page_errors})
                context.close()
        finally:
            browser.close()

    (evidence / "browser-report.json").write_text(json.dumps({"task_id": "ACCEPTANCE-FEEDBACK-P1-B32", "status": "passed", "viewports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
