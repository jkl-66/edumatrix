"""COURSE-DOCUMENT-INGESTION-UX-01 real-browser acceptance.

The browser performs a real course creation, local Markdown/Notebook upload,
and web-source import against an isolated EduMatrix service.  A local
OpenAI-compatible model stub supplies the structured admission response so
the journey does not depend on a public provider.  The reader itself is the
acceptance boundary: new readable documents must open in the A+B+C preview,
retain raw Markdown, use the versioned cache, and preserve search/selection.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

import e2e_course_document_reading_ux as reading


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "custom_tasks"
    / "COURSE-DOCUMENT-INGESTION-UX-01"
    / "browser"
)
USERNAME = "lzz"
PASSWORD = "404404aA"


class _ModelStubHandler(BaseHTTPRequestHandler):
    """Small local OpenAI-compatible response for the isolated acceptance."""

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            payload = {}
        if payload.get("response_format"):
            content = json.dumps(
                {
                    "chapters": [
                        {
                            "title": "导入资料核心章节",
                            "char_start": 0,
                            "char_end": 100000,
                            "heading_level": 1,
                            "knowledge_points": [
                                {
                                    "code": "INGESTION-ABC",
                                    "title": "资料阅读版与原文切换",
                                    "level": "core",
                                    "prerequisites": [],
                                }
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        else:
            content = (
                "# 网页导入：A+B+C 阅读体验\n\n"
                "来源页面说明：这份资料通过网页加入入口进入当前课程。\n\n"
                "## 核心概念\n\n"
                "网页摘要会被整理为可读正文，打开后默认使用教材式阅读版。\n\n"
                "## 关键步骤\n\n"
                "1. 先查看章节与概念。\n"
                "2. 在阅读版和原文之间切换。\n"
                "3. 搜索并划选正文，回到同一份来源。\n"
            )
        body = json.dumps(
            {
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def _start_model_stub() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelStubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _official_state() -> dict[str, str]:
    paths = [
        ROOT / "edumatrix.db",
        ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "active_manifest.json",
        ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "current_checkpoint.json",
    ]
    return {str(path): _digest(path) for path in paths if path.is_file()}


def _clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def _diagnostics(page: Page, report: dict[str, object]) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.scheme not in {"blob", "data"} and parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(response.url)
        if response.status >= 400:
            report["http_errors"].append({"status": response.status, "url": response.url})

    page.on("response", on_response)
    def on_request_failed(request) -> None:
        if request.url.startswith("blob:") and request.failure == "net::ERR_ABORTED":
            report.setdefault("expected_request_aborts", []).append({"url": request.url, "failure": request.failure})
            return
        report["failed_requests"].append({"url": request.url, "failure": request.failure})
    page.on("requestfailed", on_request_failed)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def _capture(page: Page, report: dict[str, object], name: str) -> None:
    path = OUTPUT_DIR / name
    page.screenshot(path=path, full_page=False)
    report["screenshots"].append({"file": name, "width": path.stat().st_size and page.viewport_size["width"], "height": page.viewport_size["height"]})


def _visual_contract(page: Page) -> dict[str, object]:
    return page.evaluate(
        """
        () => {
          const root = document.querySelector('.reader-page')
          const preview = root?.querySelector('.course-document-preview')
          const toolbar = root?.querySelector('[data-testid=course-document-preview] .course-document-reader__toolbar')
          return {
            root: Boolean(root),
            preview: Boolean(preview),
            toolbar: Boolean(toolbar),
            raw: Boolean(root?.querySelector('.course-document-raw')),
            lessonBlocks: preview?.querySelectorAll('.lesson-block').length || 0,
            horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
            previewText: preview?.innerText?.slice(0, 280) || '',
          }
        }
        """
    )


def _login(page: Page, base_url: str) -> str:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": USERNAME, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    session = response.json()
    state = json.dumps(session, ensure_ascii=False)
    page.add_init_script(
        f"""
        const session = {state};
        localStorage.setItem('edumatrix_token', session.access_token);
        localStorage.setItem('edumatrix_username', session.username || '{USERNAME}');
        localStorage.setItem('edumatrix_display_name', session.display_name || session.username || '{USERNAME}');
        localStorage.setItem('edumatrix_role', session.role || 'student');
        localStorage.setItem('edumatrix_student_id', session.student_id || session.username || '{USERNAME}');
        localStorage.setItem('edumatrix_onboarded', 'true');
        """
    )
    return str(session["access_token"])


def _create_course(page: Page, base_url: str, token: str) -> str:
    response = page.request.post(
        f"{base_url}/api/knowledge/courses",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "title": "A+B+C 资料导入验收课程",
            "subject": "课程文档阅读",
            "description": "验证后续上传与加入资料统一进入教材式阅读版。",
        },
    )
    if response.status != 201:
        raise AssertionError(f"course creation failed: {response.status} {response.text}")
    return str(response.json()["course"]["id"])


def _browser_reader_payload(page: Page, source_id: str, token: str) -> dict[str, object]:
    return page.evaluate(
        """
        async ({sourceId, token}) => {
          const response = await fetch(`/api/v1/document-reader/documents/${encodeURIComponent(sourceId)}`, {
            headers: { Authorization: `Bearer ${token}` },
          })
          return { status: response.status, body: await response.json() }
        }
        """,
        {"sourceId": source_id, "token": token},
    )


def _open_reader(page: Page, base_url: str, source_id: str, course_id: str) -> None:
    page.goto(
        f"{base_url}/knowledge/documents/{source_id}?course_id={course_id}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.locator(".reader-page").wait_for(state="visible", timeout=30_000)
    page.get_by_text("正在打开原文", exact=True).wait_for(state="hidden", timeout=30_000)


def _select_preview_text(page: Page) -> None:
    page.locator(".course-document-preview").evaluate(
        """
        element => {
          const candidate = element.querySelector('.lesson-block--explanation p, .lesson-block--summary p, .lesson-block--steps li')
          if (!candidate) throw new Error('preview text block not found')
          const walker = document.createTreeWalker(candidate, NodeFilter.SHOW_TEXT)
          const node = walker.nextNode()
          if (!node || !node.textContent.trim()) throw new Error('preview text node not found')
          const range = document.createRange()
          range.setStart(node, 0)
          range.setEnd(node, Math.min(node.textContent.length, 42))
          const selection = window.getSelection()
          selection.removeAllRanges()
          selection.addRange(range)
          element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, view: window }))
        }
        """
    )
    page.get_by_role("toolbar", name="文本选区操作").wait_for(state="visible", timeout=20_000)


def _exercise_reader(
    page: Page,
    report: dict[str, object],
    base_url: str,
    token: str,
    source_id: str,
    course_id: str,
    label: str,
    search_term: str,
) -> None:
    payload = _browser_reader_payload(page, source_id, token)
    assert payload["status"] == 200, payload
    body = payload["body"]
    report["reader_payloads"].append(
        {
            "label": label,
            "source_document_id": source_id,
            "file_type": body.get("file_type"),
            "reader_mode": body.get("reader_mode"),
        }
    )
    assert body.get("reader_mode") == "course_preview", body
    _open_reader(page, base_url, source_id, course_id)
    preview = page.locator(".course-document-preview")
    preview.wait_for(state="visible", timeout=30_000)
    visual = _visual_contract(page)
    report["visual"][f"{label}_preview"] = visual
    assert visual["root"] and visual["preview"] and visual["toolbar"], visual
    assert visual["lessonBlocks"] >= 1 and not visual["horizontalOverflow"], visual
    _capture(page, report, f"{label}-01-reading-preview-1440x900.png")

    page.get_by_role("button", name="原文", exact=True).click()
    raw = page.locator(".course-document-raw")
    raw.wait_for(state="visible")
    assert raw.inner_text().strip()
    _capture(page, report, f"{label}-02-raw-source-1440x900.png")

    page.get_by_role("button", name="阅读版", exact=True).click()
    preview.wait_for(state="visible")
    assert page.get_by_text("已生成本版预览", exact=True).count() + page.get_by_text("已使用本版缓存", exact=True).count() >= 1
    page.reload(wait_until="networkidle")
    page.locator(".course-document-preview").wait_for(state="visible", timeout=30_000)
    page.get_by_text("已使用本版缓存", exact=True).wait_for(state="visible", timeout=15_000)
    report["checks"][f"{label}_version_cache_hit"] = True
    _capture(page, report, f"{label}-03-cache-hit-1440x900.png")

    page.get_by_label("在当前文档中搜索").fill(search_term)
    page.wait_for_timeout(250)
    page.get_by_title("下一个搜索结果").click()
    page.locator(".course-search-hit--current").wait_for(state="visible", timeout=15_000)
    report["checks"][f"{label}_search_highlight"] = True
    _capture(page, report, f"{label}-04-search-highlight-1440x900.png")

    _select_preview_text(page)
    report["checks"][f"{label}_selection_toolbar"] = True
    _capture(page, report, f"{label}-05-selection-toolbar-1440x900.png")


def _exercise_native_branches(page: Page, report: dict[str, object], base_url: str, fixture: dict[str, object]) -> None:
    pdf = fixture["pdf"]
    _open_reader(page, base_url, pdf["source_id"], pdf["course_id"])
    page.locator(".parsed-page-preview").wait_for(state="visible", timeout=60_000)
    assert page.locator(".course-document-preview").count() == 0
    report["checks"]["pdf_native_branch"] = True
    _capture(page, report, "pdf-native-branch-1440x900.png")

    video = fixture["video"]
    _open_reader(page, base_url, video["source_id"], video["course_id"])
    page.locator(".media-reader").wait_for(state="visible", timeout=60_000)
    assert page.locator("video").count() == 1
    assert page.locator(".course-document-preview").count() == 0
    report["checks"]["video_native_branch"] = True
    _capture(page, report, "video-native-branch-1440x900.png")


def _db_state(path: Path) -> dict[str, object]:
    with sqlite3.connect(path, timeout=10) as db:
        return {
            "learning_event_count": db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def run() -> dict[str, object]:
    _clear_output()
    reading.OUTPUT_DIR = OUTPUT_DIR
    db_path = OUTPUT_DIR / "course_document_ingestion_ux.sqlite3"
    model_server, model_thread = _start_model_stub()
    port = reading.base.free_port()
    env = reading.base.runtime_env(db_path, port)
    env.update(
        {
            "EDUMATRIX_LLM_PROVIDER": "openai",
            "EDUMATRIX_LLM_MODEL": "deepseek-v4-flash",
            "EDUMATRIX_LLM_API_KEY": "isolated-browser-model",
            "EDUMATRIX_LLM_ENDPOINT": f"http://127.0.0.1:{model_server.server_port}/chat/completions",
            "EDUMATRIX_LLM_THINKING_MODE": "max",
            "EDUMATRIX_LLM_REASONING_EFFORT": "max",
            "EDUMATRIX_UPLOAD_DIR": str(OUTPUT_DIR / "uploads"),
            "EDUMATRIX_AUTH_SECRET_KEY": "course-document-ingestion-ux-isolated-secret",
        }
    )
    official_before = _official_state()
    fixture = reading.seed_fixture(env)
    process = None
    report: dict[str, object] = {
        "schema_version": "course-document-ingestion-ux-01.browser.v1",
        "task_id": "COURSE-DOCUMENT-INGESTION-UX-01",
        "status": "running",
        "screenshots": [],
        "checks": {},
        "visual": {},
        "reader_payloads": [],
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "expected_request_aborts": [],
        "fixture": fixture,
    }
    try:
        process = reading.base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            _diagnostics(page, report)
            token = _login(page, base_url)

            course_id = _create_course(page, base_url, token)
            page.goto(f"{base_url}/knowledge/courses/{course_id}", wait_until="networkidle", timeout=60_000)
            page.get_by_test_id("add-course-material").wait_for(state="visible", timeout=30_000)

            files = [
                {
                    "name": "本地A+B+C讲义.md",
                    "mimeType": "text/markdown",
                    "buffer": (
                        "# 本地导入讲义\n\n"
                        "## 向量与检索\n\n"
                        "这份 Markdown 资料用于验证上传后默认进入阅读版。\n\n"
                        "- 可搜索的检索概念\n"
                        "- 可划选的原文内容\n\n"
                        "```python\nprint('A+B+C')\n```\n"
                    ).encode("utf-8"),
                },
                {
                    "name": "本地Notebook.ipynb",
                    "mimeType": "application/json",
                    "buffer": json.dumps(
                        {
                            "cells": [
                                {"cell_type": "markdown", "metadata": {}, "source": ["# Notebook 导入\n", "\n", "向量检索实验说明。"]},
                                {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": ["print('Notebook A+B+C')"]},
                            ],
                            "metadata": {},
                            "nbformat": 4,
                            "nbformat_minor": 5,
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                },
            ]
            with page.expect_response(lambda response: "/api/knowledge/upload-batch" in response.url) as upload_response:
                page.locator("input[type=file]").set_input_files(files)
            upload_payload = upload_response.value.json()
            assert upload_payload["succeeded"] == 2, upload_payload
            page.get_by_text("2 份资料已进入课程", exact=False).wait_for(state="visible", timeout=60_000)
            report["checks"]["local_upload_batch_ready"] = True
            uploaded = [item["document"] for item in upload_payload["results"] if item["status"] == "ready"]
            assert len(uploaded) == 2

            md_doc = next(item for item in uploaded if item["file_type"] == "md")
            notebook_doc = next(item for item in uploaded if item["file_type"] == "ipynb")
            _exercise_reader(page, report, base_url, token, md_doc["source_document_id"], course_id, "local-markdown", "检索")
            _exercise_reader(page, report, base_url, token, notebook_doc["source_document_id"], course_id, "local-notebook", "向量")

            web_payload = page.evaluate(
                """
                async ({token, courseId}) => {
                  const response = await fetch('/api/knowledge/add-web-source', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                    body: JSON.stringify({
                      query: 'A+B+C 网页教材',
                      title: '网页加入的课程资料',
                      url: 'https://example.com/edumatrix-abc',
                      snippet: '网页资料包含向量检索与阅读版切换说明。',
                      student_id: 'lzz',
                      course_id: courseId,
                    }),
                  })
                  return { status: response.status, body: await response.json() }
                }
                """,
                {"token": token, "courseId": course_id},
            )
            assert web_payload["status"] == 200, web_payload
            web_doc = web_payload["body"]
            assert web_doc["filename"].endswith(".md") and web_doc["file_type"] == "md", web_doc
            assert web_doc["source_document_id"]
            report["checks"]["web_source_markdown_persisted"] = True
            _exercise_reader(page, report, base_url, token, web_doc["source_document_id"], course_id, "web-markdown", "网页")

            _exercise_native_branches(page, report, base_url, fixture)
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            _diagnostics(page, report)
            _login(page, base_url)
            _open_reader(page, base_url, md_doc["source_document_id"], course_id)
            preview = page.locator(".course-document-preview")
            preview.wait_for(state="visible", timeout=30_000)
            visual = _visual_contract(page)
            report["visual"]["local_markdown_preview_1366x768"] = visual
            assert visual["root"] and visual["preview"] and visual["toolbar"], visual
            assert visual["lessonBlocks"] >= 1 and not visual["horizontalOverflow"], visual
            _capture(page, report, "local-markdown-06-reading-preview-1366x768.png")
            context.close()
            browser.close()

        report["database"] = _db_state(db_path)
        assert report["database"]["learning_event_count"] == fixture["initial_learning_events"]
        assert report["database"]["integrity"] == "ok"
        assert report["database"]["foreign_key_violations"] == 0
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["external_requests"], report["external_requests"]
        report["status"] = "passed"
        return report
    finally:
        reading.base.stop_service(process, port)
        model_server.shutdown()
        model_server.server_close()
        model_thread.join(timeout=3)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        report["official_state_before"] = official_before
        report["official_state_after"] = _official_state()
        report["official_state_unchanged"] = report["official_state_before"] == report["official_state_after"]
        (OUTPUT_DIR / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": _digest(path)}
            for path in sorted(OUTPUT_DIR.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT_DIR / "manifest.json").write_text(
            json.dumps({"schema_version": "course-document-ingestion-ux-01.evidence-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
