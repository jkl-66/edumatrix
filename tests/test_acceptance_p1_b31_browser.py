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
    reason="B31 browser evidence is an explicit opt-in check",
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


def _conversation_payload(state):
    messages = list(state["messages"])
    latest_user = next((item for item in reversed(messages) if item["role"] == "user"), None)
    refs = list((latest_user or {}).get("contextRefs") or [])
    courses = []
    seen = set()
    for ref in refs:
        course = ref.get("course") or {}
        course_id = str(course.get("id") or ref.get("courseId") or "")
        if course_id and course_id not in seen:
            seen.add(course_id)
            courses.append(course)
    return {
        "id": state["conversation_id"],
        "courseId": courses[0]["id"] if courses else None,
        "courseIds": [item["id"] for item in courses],
        "courses": courses,
        "contextMode": "course" if courses else "general",
        "title": "B31 浏览器对话",
        "status": "active",
        "lockVersion": state["lock_version"],
        "createdAt": "2026-08-26T08:00:00Z",
        "updatedAt": "2026-08-26T08:00:00Z",
        "messages": messages,
        "attachments": [],
    }


def _install_api_mocks(page, *, course_mode="ready", hold_courses=False):
    courses = [
        {
            "id": "b31-browser-course-a",
            "title": "机器学习基础",
            "subject": "机器学习",
            "version": "v1",
            "manifestVersion": "manifest-a-v1",
            "status": "published",
            "visibility": "private",
        },
        {
            "id": "b31-browser-course-b",
            "title": "数据结构与算法",
            "subject": "计算机基础",
            "version": "v2",
            "manifestVersion": "manifest-b-v2",
            "status": "published",
            "visibility": "private",
        },
    ]
    state = {
        "course_calls": 0,
        "course_mode": course_mode,
        "conversation_id": "chat-b31-browser",
        "created": False,
        "lock_version": 1,
        "messages": [],
        "message_contexts": [],
        "message_counter": 0,
        "stream_by_user": {},
        "pending_course_route": None,
    }

    def respond(route, body, status=200):
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(body, ensure_ascii=False),
        )

    def course_response(route):
        state["course_calls"] += 1
        if hold_courses and state["course_calls"] == 1:
            state["pending_course_route"] = route
            return
        if state["course_mode"] == "fail_once" and state["course_calls"] == 1:
            respond(route, {"detail": "课程列表暂时不可用"}, status=503)
            return
        respond(route, {"schemaVersion": "edumatrix.chat-course-catalog.v1", "courses": [] if state["course_mode"] == "empty" else courses})

    def release_courses():
        pending = state.pop("pending_course_route", None)
        if pending is not None:
            respond(pending, {"schemaVersion": "edumatrix.chat-course-catalog.v1", "courses": courses})

    state["release_courses"] = release_courses

    def handle(route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        method = request.method.upper()
        if path.endswith("/api/auth/me"):
            respond(route, {"public_id": "b31-browser-user", "username": "b31-browser", "display_name": "B31 浏览器验收", "role": "student"})
            return
        if path.endswith("/api/health"):
            respond(route, {"status": "ok"})
            return
        if path.endswith("/api/v1/chat/courses") and method == "GET":
            course_response(route)
            return
        if path.endswith("/api/v1/chat/conversations") and method == "GET":
            items = [_conversation_payload(state)] if state["created"] else []
            respond(route, {"schemaVersion": "edumatrix.chat-conversation-list.v1", "items": items})
            return
        if path.endswith("/api/v1/chat/conversations") and method == "POST":
            payload = json.loads(request.post_data or "{}")
            state["created"] = True
            state["lock_version"] = 1
            selected = [str(item) for item in payload.get("course_ids") or []]
            if payload.get("course_id") and payload["course_id"] not in selected:
                selected.insert(0, str(payload["course_id"]))
            if selected:
                refs = [{"courseId": course_id, "course": next((item for item in courses if item["id"] == course_id), {"id": course_id, "title": course_id})} for course_id in selected]
                state["messages"] = []
                state["initial_courses"] = refs
            respond(route, _conversation_payload(state))
            return
        if "/api/v1/chat/conversations/" in path and method == "GET":
            respond(route, _conversation_payload(state))
            return
        if path.endswith("/api/v1/chat/conversations/chat-b31-browser/messages") and method == "POST":
            payload = json.loads(request.post_data or "{}")
            state["message_counter"] += 1
            index = state["message_counter"]
            user_id = f"b31-user-{index}"
            assistant_id = f"b31-assistant-{index}"
            context_refs = list(payload.get("context_refs") or [])
            hydrated_refs = []
            for ref in context_refs:
                course_id = str(ref.get("courseId") or "")
                course = next((item for item in courses if item["id"] == course_id), None)
                hydrated_refs.append({**ref, "course": course} if course else dict(ref))
            user = {
                "id": user_id,
                "conversationId": state["conversation_id"],
                "replyToMessageId": None,
                "sequence": index * 2 - 1,
                "role": "user",
                "status": "completed",
                "content": payload.get("content") or "",
                "contextRefs": hydrated_refs,
                "attachmentIds": [],
                "sourceRefs": [],
                "resourceLinks": [],
                "streamCheckpoint": {"status": "completed"},
                "createdAt": "2026-08-26T08:00:00Z",
                "updatedAt": "2026-08-26T08:00:00Z",
                "lockVersion": 1,
            }
            assistant = {
                "id": assistant_id,
                "conversationId": state["conversation_id"],
                "replyToMessageId": user_id,
                "sequence": index * 2,
                "role": "assistant",
                "status": "queued",
                "content": "",
                "contextRefs": hydrated_refs,
                "attachmentIds": [],
                "sourceRefs": [],
                "resourceLinks": [],
                "streamCheckpoint": {"status": "queued", "receivedCharacters": 0},
                "createdAt": "2026-08-26T08:00:00Z",
                "updatedAt": "2026-08-26T08:00:00Z",
                "lockVersion": 1,
            }
            state["messages"].extend([user, assistant])
            state["message_contexts"].append(context_refs)
            state["stream_by_user"][user_id] = assistant
            state["lock_version"] += 1
            respond(route, {"created": True, "userMessage": user, "assistantMessage": assistant})
            return
        if path.endswith("/api/stream/chat") and method == "POST":
            payload = json.loads(request.post_data or "{}")
            user_id = payload.get("user_message_id")
            assistant = state["stream_by_user"].get(user_id)
            if assistant is None:
                respond(route, {"detail": "unknown stream"}, status=404)
                return
            assistant["status"] = "completed"
            assistant["content"] = "已结合所选课程上下文完成回答。"
            assistant["streamCheckpoint"] = {"status": "completed", "receivedCharacters": len(assistant["content"])}
            sse = "".join([
                f"event: progress\ndata: {json.dumps({'message_id': assistant['id'], 'progress': 40, 'message': '正在读取课程上下文'}, ensure_ascii=False)}\n\n",
                f"event: chat_chunk\ndata: {json.dumps({'message_id': assistant['id'], 'content': assistant['content']}, ensure_ascii=False)}\n\n",
                f"event: complete\ndata: {json.dumps({'message_id': assistant['id'], 'message': assistant}, ensure_ascii=False)}\n\n",
            ])
            route.fulfill(status=200, headers={"Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache"}, body=sse)
            return
        respond(route, {})

    page.route("**/api/**", handle)
    return state


def _layout(page, width, screenshot_path):
    page.screenshot(path=str(screenshot_path), full_page=True)
    result = page.evaluate(
        """() => {
          const root = document.querySelector('[data-testid=focused-chat-workspace]');
          const important = ['[data-testid=chat-current-course-label]', '[data-testid=chat-course-picker] .course-picker__trigger', '[data-testid=chat-composer-context]'];
          const trigger = document.querySelector('[data-testid=chat-course-picker] .course-picker__trigger')?.getBoundingClientRect();
          const status = document.querySelector('.answer-status')?.getBoundingClientRect();
          return {
            viewportWidth: window.innerWidth,
            viewportHeight: window.innerHeight,
            documentWidth: document.documentElement.scrollWidth,
            bodyWidth: document.body.scrollWidth,
            rootRight: root ? root.getBoundingClientRect().right : 0,
            pickerStatusOverlap: trigger && status
              ? !(trigger.right <= status.left || status.right <= trigger.left || trigger.bottom <= status.top || status.bottom <= trigger.top)
              : false,
            importantFontSizes: important.map((selector) => {
              const node = document.querySelector(selector);
              return node ? Number.parseFloat(getComputedStyle(node).fontSize) : null;
            }),
          };
        }"""
    )
    assert result["documentWidth"] <= width + 1, result
    assert result["bodyWidth"] <= width + 1, result
    assert result["rootRight"] <= width + 1, result
    assert not result["pickerStatusOverlap"], result
    assert all(size is None or size >= 14 for size in result["importantFontSizes"]), result
    return result


def test_multicourse_chat_path_two_desktop_viewports(tmp_path):
    from playwright.sync_api import sync_playwright

    evidence = Path(__file__).resolve().parents[1] / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B31"
    evidence.mkdir(parents=True, exist_ok=True)
    reports = []
    with _frontend_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_init_script(
                    "localStorage.setItem('edumatrix_token', 'b31-browser-token');"
                    "localStorage.setItem('edumatrix_role', 'student');"
                    "localStorage.setItem('edumatrix_onboarded', 'true');"
                )
                page = context.new_page()
                page_errors = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                state = _install_api_mocks(page)
                page.goto(f"{base_url}/learn", wait_until="networkidle")
                page.get_by_test_id("chat-course-picker").wait_for()
                page.get_by_test_id("chat-course-picker").locator("button").click()
                page.locator(".course-picker__option input").nth(0).check()
                page.locator(".course-picker__option input").nth(1).check()
                assert "已选择 2 门课程" in page.get_by_test_id("chat-current-course-label").inner_text()
                page.get_by_role("button", name="完成").click()

                page.get_by_label("输入问题").fill("比较两门课程的核心概念")
                page.get_by_role("button", name="发送").click()
                page.get_by_text("已结合所选课程上下文完成回答。", exact=True).wait_for()
                assert [item.get("courseId") for item in state["message_contexts"][0]] == [
                    "b31-browser-course-a",
                    "b31-browser-course-b",
                ]

                page.get_by_test_id("chat-course-picker").locator("button").click()
                page.get_by_role("button", name="使用通用对话").click()
                assert page.get_by_test_id("chat-current-course-label").inner_text() == "未绑定课程（通用对话）"
                assert page.locator(".conversation-course").first.inner_text() == "通用对话 · 未绑定课程"
                page.get_by_label("输入问题").fill("再给一个不绑定课程的通用解释")
                page.get_by_role("button", name="发送").click()
                page.get_by_text("已结合所选课程上下文完成回答。", exact=True).last.wait_for()
                assert state["message_contexts"][1] == []

                page.locator(".message-row").nth(0).click()
                context_panel = page.get_by_test_id("chat-context-refs")
                context_panel.get_by_text("机器学习基础", exact=True).wait_for()
                context_panel.get_by_text("数据结构与算法", exact=True).wait_for()

                page.reload(wait_until="networkidle")
                page.locator(".message-row").nth(0).click()
                page.get_by_test_id("chat-context-refs").get_by_text("机器学习基础", exact=True).wait_for()
                page.get_by_test_id("chat-context-refs").get_by_text("数据结构与算法", exact=True).wait_for()
                assert not page_errors, page_errors
                reports.append({"viewport": {"width": width, "height": height}, "layout": _layout(page, width, evidence / f"chat-{width}x{height}.png"), "message_contexts": state["message_contexts"], "page_errors": page_errors})
                context.close()
        finally:
            browser.close()
    (evidence / "browser-report.json").write_text(json.dumps({"task_id": "ACCEPTANCE-FEEDBACK-P1-B31", "status": "passed", "viewports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")


def test_chat_course_picker_failure_retry_and_empty_state():
    from playwright.sync_api import sync_playwright

    with _frontend_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for mode, expected in (("fail_once", "课程列表暂时不可用"), ("empty", "暂无可用课程，可以使用通用对话。")):
                context = browser.new_context(viewport={"width": 1440, "height": 900})
                context.add_init_script(
                    "localStorage.setItem('edumatrix_token', 'b31-browser-token');"
                    "localStorage.setItem('edumatrix_role', 'student');"
                    "localStorage.setItem('edumatrix_onboarded', 'true');"
                )
                page = context.new_page()
                page_errors = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                _install_api_mocks(page, course_mode=mode)
                page.goto(f"{base_url}/learn", wait_until="networkidle")
                page.get_by_test_id("chat-course-picker").locator("button").click()
                if mode == "fail_once":
                    page.locator(".course-picker__error").wait_for()
                    assert expected in page.locator(".course-picker__error").inner_text()
                else:
                    page.get_by_text(expected, exact=True).wait_for()
                if mode == "fail_once":
                    page.get_by_role("button", name="重试").click()
                    page.locator(".course-picker__option input").nth(0).wait_for()
                else:
                    assert page.get_by_test_id("chat-current-course-label").inner_text() == "未绑定课程（通用对话）"
                assert not page_errors, page_errors
                context.close()
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_init_script(
                "localStorage.setItem('edumatrix_token', 'b31-browser-token');"
                "localStorage.setItem('edumatrix_role', 'student');"
                "localStorage.setItem('edumatrix_onboarded', 'true');"
            )
            page = context.new_page()
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            state = _install_api_mocks(page, hold_courses=True)
            page.goto(f"{base_url}/learn", wait_until="domcontentloaded")
            page.get_by_test_id("chat-course-picker").wait_for()
            page.get_by_test_id("chat-course-picker").locator("button").click()
            page.get_by_text("正在加载可用课程", exact=True).wait_for(timeout=5000)
            state["release_courses"]()
            page.locator(".course-picker__option input").nth(0).wait_for(timeout=10000)
            checkbox = page.locator(".course-picker__option input").nth(0)
            checkbox.focus()
            checkbox.press("Space")
            assert checkbox.is_checked()
            assert not page_errors, page_errors
            context.close()
        finally:
            browser.close()
