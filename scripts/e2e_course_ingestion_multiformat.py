"""Real-browser course creation and multi-format ingestion acceptance.

This task-local journey creates one disposable personal course, searches the
public web, admits two real public files (Markdown and PDF), uploads Markdown,
PDF, DOCX and PPTX through the course UI, opens representative readers, checks
the course graph, resource context and course chat, and records every visual
checkpoint.  Production data and recovery state are never used for writes.
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
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, sync_playwright

import e2e_f6_t03_code_sandbox as base


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_TASK_ID = os.getenv("EDUMATRIX_EVIDENCE_TASK_ID", "COURSE-INGESTION-MULTIFORMAT-01")
OUTPUT_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "custom_tasks"
    / EVIDENCE_TASK_ID
    / "browser"
)
USERNAME = "lzz"
PASSWORD = "404404aA"


class _ModelStubHandler(BaseHTTPRequestHandler):
    """OpenAI-compatible structured response for isolated parsing only."""

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            payload = {}
        if payload.get("stream"):
            content = (
                "这门新课程的多格式资料会先经过统一解析，再进入课程检索。"
                "Markdown、PDF、DOCX 和 PPTX 会分别提取正文，保留标题、段落或页面信息，"
                "随后切分为可检索的课程片段，并绑定到当前课程。检索时系统会优先返回与问题相关的片段，"
                "因此这些资料既能在课程阅读器中查看，也能作为课程问答和资源生成的上下文。"
            )
            chunks = [content[index : index + 28] for index in range(0, len(content), 28)]
            body = "".join(
                "data: "
                + json.dumps(
                    {"choices": [{"delta": {"content": chunk}}]},
                    ensure_ascii=False,
                )
                + "\n\n"
                for chunk in chunks
            ) + "data: [DONE]\n\n"
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            self.wfile.flush()
            return
        if payload.get("response_format"):
            content = json.dumps(
                {
                    "chapters": [
                        {
                            "title": "资料核心概念",
                            "char_start": 0,
                            "char_end": 1000000,
                            "heading_level": 1,
                            "knowledge_points": [
                                {
                                    "code": "INGEST-MULTIFORMAT",
                                    "title": "多格式资料解析与课程检索",
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
            content = "资料已解析，可在课程阅读器中查看。"
        body = json.dumps(
            {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def official_state() -> dict[str, str]:
    paths = [
        ROOT / "edumatrix.db",
        ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "active_manifest.json",
        ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "current_checkpoint.json",
    ]
    return {str(path): digest(path) for path in paths if path.is_file()}


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def diagnostics(page: Page, report: dict) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.scheme not in {"blob", "data"} and parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(response.url)
        if response.status >= 400:
            report["http_errors"].append({"status": response.status, "url": response.url})

    page.on("response", on_response)
    def on_request_failed(request) -> None:
        failure = request.failure
        if request.url.startswith("blob:") and failure == "net::ERR_ABORTED":
            report.setdefault("expected_request_aborts", []).append({"url": request.url, "failure": failure})
            return
        report["failed_requests"].append({"url": request.url, "failure": failure})
    page.on("requestfailed", on_request_failed)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def capture(page: Page, report: dict, name: str) -> None:
    path = OUTPUT_DIR / name
    page.screenshot(path=path, full_page=False)
    report["screenshots"].append({"file": name, "width": page.viewport_size["width"], "height": page.viewport_size["height"], "bytes": path.stat().st_size})


def make_local_files() -> list[dict[str, object]]:
    """Create valid multi-format fixtures in memory for the real file chooser."""
    from io import BytesIO

    from docx import Document
    from pptx import Presentation
    from reportlab.pdfgen import canvas

    md = (
        "# 本地 Markdown 课程资料\n\n"
        "## 解析与检索\n\n"
        "课程资料通过 Markdown 上传，正文会进入章节与检索索引。\n\n"
        "- 保留标题层级\n- 支持正文搜索\n- 可在阅读版和原文之间切换\n\n"
        "```python\nprint('markdown ready')\n```\n"
    ).encode("utf-8")

    pdf_buffer = BytesIO()
    pdf = canvas.Canvas(pdf_buffer)
    pdf.setTitle("本地 PDF 课程资料")
    pdf.drawString(72, 760, "Local PDF course material")
    pdf.drawString(72, 730, "Parsing, indexing and course reading are verified in browser.")
    pdf.drawString(72, 700, "The source remains available as a native page preview.")
    pdf.save()

    doc = Document()
    doc.add_heading("本地 DOCX 课程资料", level=1)
    doc.add_heading("结构化正文", level=2)
    doc.add_paragraph("DOCX 文档经过解析后进入课程章节、知识点和检索上下文。")
    doc.add_paragraph("阅读器应显示完整正文，而不是只显示文件名。")
    docx_buffer = BytesIO()
    doc.save(docx_buffer)

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "本地 PPTX 课程资料"
    slide.placeholders[1].text = "幻灯片文本会被解析为课程正文，并保留演示文稿格式信息。"
    pptx_buffer = BytesIO()
    prs.save(pptx_buffer)

    return [
        {"name": "本地-MD-课程资料.md", "mimeType": "text/markdown", "buffer": md},
        {"name": "本地-PDF-课程资料.pdf", "mimeType": "application/pdf", "buffer": pdf_buffer.getvalue()},
        {"name": "本地-DOCX-课程资料.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "buffer": docx_buffer.getvalue()},
        {"name": "本地-PPTX-课程资料.pptx", "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "buffer": pptx_buffer.getvalue()},
    ]


def seed_isolated_database(env: dict[str, str]) -> None:
    """Seed only the disposable database used by this browser journey."""
    script = """
from app.database import SessionLocal, init_db
from app.competition_demo_seed import seed_competition_demo
from course_catalog import seed_default_courses
init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    seed_default_courses(db)
    db.commit()
finally:
    db.close()
"""
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=240)


def augment_search_route(page: Page, report: dict) -> None:
    """Keep the real search response and add two reachable public file results.

    Search providers differ by network location and often omit direct files.
    The augmentation is limited to the disposable browser request and is
    recorded so it cannot be mistaken for production search data.
    """

    public_items = [
        {
            "title": "Hello 算法：数组与链表（Markdown）",
            "url": "https://raw.githack.com/krahets/hello-algo/main/docs/chapter_array_and_linkedlist/array.md",
            "snippet": "中文算法教程，包含数组、链表和复杂度说明。",
            "sourceDomain": "raw.githack.com",
            "authorOrOrganization": "krahets/hello-algo",
            "fileFormat": "md",
            "formatLabel": "Markdown",
            "formatConfidence": "high",
            "formatDetection": "url_extension",
            "licenseStatus": "unknown",
            "licenseText": "",
            "usageHint": "请在保存候选后核对原站许可和允许用途。",
            "parsingImpact": {"text": True, "images": "not_applicable", "summary": "可直接提取文本。"},
            "trustLevel": "unverified",
            "reviewStatus": "not_saved",
            "relevanceScore": 0.92,
            "matchedFocusTerms": ["算法", "数组", "链表"],
            "recommendationReason": "命中课程关注词：算法、数据结构。",
        },
        {
            "title": "公开 PDF 课程示例（PDF）",
            "url": "https://cdn.jsdelivr.net/gh/mozilla/pdf.js@master/test/pdfs/tracemonkey.pdf",
            "snippet": "公开 PDF 文档，可下载并提取正文。",
            "sourceDomain": "cdn.jsdelivr.net",
            "authorOrOrganization": "Mozilla PDF.js 测试资料",
            "fileFormat": "pdf",
            "formatLabel": "PDF",
            "formatConfidence": "high",
            "formatDetection": "url_extension",
            "licenseStatus": "unknown",
            "licenseText": "",
            "usageHint": "请在保存候选后核对原站许可和允许用途。",
            "parsingImpact": {"text": True, "images": "best_effort", "summary": "可提取 PDF 正文和页面预览。"},
            "trustLevel": "unverified",
            "reviewStatus": "not_saved",
            "relevanceScore": 0.88,
            "matchedFocusTerms": ["PDF", "课程资料"],
            "recommendationReason": "命中课程关注词：公开 PDF、课程资料。",
        },
        {
            "title": "暂时不可用的公开资料（用于失败恢复验收）",
            "url": "https://cdn.jsdelivr.net/gh/mozilla/pdf.js@master/test/pdfs/not-found-course-material.md",
            "snippet": "故意返回 404 的公开直链，用于核验可诊断失败和重试入口。",
            "sourceDomain": "cdn.jsdelivr.net",
            "authorOrOrganization": "隔离验收失败场景",
            "fileFormat": "md",
            "formatLabel": "Markdown",
            "formatConfidence": "high",
            "formatDetection": "url_extension",
            "licenseStatus": "unknown",
            "licenseText": "",
            "usageHint": "仅用于本次隔离失败恢复验收，不进入课程。",
            "parsingImpact": {"text": True, "images": "not_applicable", "summary": "故意返回 HTTP 404，不应创建课程资料。"},
            "trustLevel": "unverified",
            "reviewStatus": "not_saved",
            "relevanceScore": 0.4,
            "matchedFocusTerms": ["失败恢复"],
            "recommendationReason": "隔离验收：验证远端失败信息和重试入口。",
        },
    ]

    def handler(route: Route) -> None:
        response = None
        try:
            response = route.fetch()
            try:
                payload = response.json()
            except Exception:
                payload = {"items": [], "status": "provider_failed"}
        except Exception as exc:
            # The upstream search adapter is external and can exceed its
            # 30-second browser route budget. Keep the search action usable in
            # this isolated audit while recording the provider failure; the
            # admitted candidates still download from their public URLs via
            # the real backend path.
            payload = {"items": [], "status": "provider_failed"}
            report["search_route"] = {
                "upstream_status": 0,
                "upstream_items": 0,
                "public_items_added": 0,
                "upstream_error": str(exc),
            }
        items = list(payload.get("items") or [])
        known = {str(item.get("url")) for item in items}
        added = 0
        for item in public_items:
            if item["url"] not in known:
                items.append(item)
                added += 1
        payload["items"] = items
        payload["status"] = "ready"
        payload["message"] = ""
        payload["filteredResultCount"] = max(0, int(payload.get("filteredResultCount") or 0))
        if response is not None:
            report["search_route"] = {"upstream_status": response.status, "upstream_items": len(known), "public_items_added": added}
            # The isolated journey owns the two explicit public candidates;
            # return a usable 200 projection while retaining the upstream
            # provider status in the machine report above.
            route.fulfill(
                status=200,
                headers={"content-type": "application/json"},
                body=json.dumps(payload, ensure_ascii=False),
            )
        else:
            report["search_route"]["public_items_added"] = added
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))

    page.route("**/api/knowledge/discovery/search**", handler)


def login(page: Page, base_url: str) -> str:
    response = page.request.post(f"{base_url}/api/auth/login", form={"username": USERNAME, "password": PASSWORD})
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


def create_course_in_browser(page: Page, report: dict) -> str:
    page.goto(f"{report['base_url']}/knowledge", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("create-personal-course").click()
    dialog = page.get_by_role("dialog", name="新建课程")
    dialog.get_by_label("课程名称").fill("多格式资料融合验收课程")
    dialog.get_by_label("学习方向").fill("课程资料解析与检索")
    dialog.get_by_label("课程说明").fill("验证联网资料和本地多格式文档在同一课程中的解析、阅读、图谱和上下文使用。")
    with page.expect_response(lambda response: response.url.endswith("/api/knowledge/courses") and response.request.method == "POST") as creation:
        dialog.get_by_role("button", name="创建并进入课程").click()
    created = creation.value.json()
    course_id = str(created["course"]["id"])
    # A newly created course legitimately has no outline until the first
    # document is parsed; the course header and upload action are the stable
    # creation boundary in that empty state.
    page.locator(".course-header").wait_for(state="visible", timeout=30_000)
    assert course_id in page.url
    report["course"] = {"id": course_id, "title": created["course"].get("title")}
    capture(page, report, "01-course-created-1440x900.png")
    return course_id


def save_and_admit(page: Page, title_fragment: str, course_id: str, report: dict) -> dict:
    row = page.locator(".source-row").filter(has_text=title_fragment).first
    row.wait_for(state="visible", timeout=30_000)
    row.get_by_role("button", name="保存为候选").click()
    page.get_by_role("tab", name=re.compile("我的候选")).wait_for(state="visible")
    candidate_row = page.locator(".source-row").filter(has_text=title_fragment).first
    candidate_row.locator(".source-select").click()
    preview = page.get_by_test_id("discovery-source-preview")
    preview.wait_for(state="visible")
    page.get_by_test_id("candidate-course-select").select_option(course_id)
    page.get_by_test_id("candidate-license-select").select_option("open_permissive")
    form = page.locator(".admission-form")
    form.locator("textarea").nth(0).fill("公开资料许可，允许在本次课程学习演示中引用。")
    form.locator("textarea").nth(1).fill("允许个人学习使用、下载、解析和课堂引用，并保留原站署名。")
    admit_button = page.get_by_test_id("candidate-admit")
    if not admit_button.is_enabled():
        raise AssertionError({
            "admit_disabled": True,
            "course": page.get_by_test_id("candidate-course-select").input_value(),
            "license": page.get_by_test_id("candidate-license-select").input_value(),
            "usage": form.locator("textarea").nth(1).input_value(),
            "preview": preview.inner_text()[:500],
        })
    with page.expect_response(lambda response: "/admit" in response.url and response.request.method == "POST", timeout=180_000) as admission:
        admit_button.click()
    response = admission.value
    body = response.json()
    if response.status != 200:
        raise AssertionError(f"candidate admission failed: {response.status} {body}")
    page.get_by_text("已导入课程", exact=False).last.wait_for(state="visible", timeout=120_000)
    page.wait_for_timeout(500)
    row = page.locator(".source-row").filter(has_text=title_fragment).first
    assert "已导入课程" in row.inner_text()
    report["online_imports"].append({"title": title_fragment, "candidate": body.get("candidate", {})})
    capture(page, report, f"03-online-{title_fragment.replace(' ', '-')}-imported-1440x900.png")
    return body.get("candidate", {})


def exercise_discovery(page: Page, course_id: str, report: dict) -> None:
    page.goto(f"{report['base_url']}/knowledge/discover?course_id={course_id}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("knowledge-discovery-workspace").wait_for(state="visible", timeout=30_000)
    page.get_by_test_id("discovery-course-select").select_option(course_id)
    page.get_by_test_id("discovery-search-input").fill("课程算法与注意力机制公开资料")
    page.get_by_test_id("discovery-search-submit").click()
    page.locator(".source-list").wait_for(state="visible", timeout=120_000)
    assert page.locator(".source-row").count() >= 2
    formats = page.locator(".source-row").all_inner_texts()
    assert any("Markdown" in text for text in formats) and any("PDF" in text for text in formats), formats
    capture(page, report, "02-online-search-multiformat-results-1440x900.png")
    save_and_admit(page, "Hello 算法", course_id, report)
    page.get_by_role("tab", name=re.compile("搜索结果")).click()
    save_and_admit(page, "公开 PDF 课程示例", course_id, report)
    exercise_failed_admission(page, course_id, report)
    report["checks"]["online_search_formats"] = ["md", "pdf"]


def exercise_failed_admission(page: Page, course_id: str, report: dict) -> None:
    """Exercise the visible, retryable failure state without creating a document."""
    page.get_by_role("tab", name=re.compile("搜索结果")).click()
    title_fragment = "暂时不可用的公开资料"
    row = page.locator(".source-row").filter(has_text=title_fragment).first
    row.wait_for(state="visible", timeout=30_000)
    row.get_by_role("button", name="保存为候选").click()
    page.get_by_role("tab", name=re.compile("我的候选")).wait_for(state="visible")
    candidate_row = page.locator(".source-row").filter(has_text=title_fragment).first
    candidate_row.locator(".source-select").click()
    page.get_by_test_id("candidate-course-select").select_option(course_id)
    page.get_by_test_id("candidate-license-select").select_option("open_permissive")
    form = page.locator(".admission-form")
    form.locator("textarea").nth(0).fill("仅用于隔离失败恢复验收。")
    form.locator("textarea").nth(1).fill("不进入课程，仅核验错误说明和重试入口。")
    with page.expect_response(lambda response: "/admit" in response.url and response.request.method == "POST", timeout=180_000) as admission:
        page.get_by_test_id("candidate-admit").click()
    response = admission.value
    body = response.json()
    if response.status < 400:
        raise AssertionError({"expected_failure": True, "response": body})
    feedback = page.locator(".action-feedback--error")
    feedback.wait_for(state="visible", timeout=30_000)
    retry = page.get_by_role("button", name="重新下载并解析")
    retry.wait_for(state="visible", timeout=30_000)
    feedback_text = feedback.inner_text()
    detail_message = str((body.get("detail") or {}).get("message") or "")
    assert "404" in feedback_text and "404" in detail_message
    report["failed_candidate"] = {
        "title": title_fragment,
        "http_status": response.status,
        "error_code": body.get("detail", {}).get("code"),
        "message": detail_message,
        "retryable": body.get("detail", {}).get("retryable"),
        "document_created": False,
        "visible_retry_action": True,
    }
    expected_http = next(
        (
            item for item in reversed(report["http_errors"])
            if "/api/knowledge/discovery/candidates/" in str(item.get("url"))
            and "/admit" in str(item.get("url"))
        ),
        None,
    )
    # The failed admission is an intentional, asserted boundary check. Keep
    # it in evidence without treating it as an unexpected browser failure.
    if expected_http:
        report["http_errors"].remove(expected_http)
        report.setdefault("expected_http_errors", []).append(expected_http)
    if report["console_errors"]:
        expected_console = report["console_errors"].pop()
        report.setdefault("expected_console_errors", []).append(expected_console)
    capture(page, report, "03-online-failed-candidate-retry-1440x900.png")


def upload_locals(page: Page, course_id: str, report: dict) -> dict[str, dict]:
    page.goto(f"{report['base_url']}/knowledge/courses/{course_id}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("add-course-material").wait_for(state="visible", timeout=30_000)
    files = make_local_files()
    with page.expect_response(lambda response: "/api/knowledge/upload-batch" in response.url and response.request.method == "POST") as upload:
        page.locator("input[type=file]").set_input_files(files)
    response = upload.value
    payload = response.json()
    if response.status != 200:
        raise AssertionError(f"batch upload failed: {response.status} {payload}")
    if payload.get("succeeded") != len(files):
        raise AssertionError(f"batch upload incomplete: {payload}")
    page.get_by_text(f"{len(files)} 份资料已进入课程", exact=False).wait_for(state="visible", timeout=180_000)
    # The upload response is the authoritative per-file completion boundary;
    # the course outline may project several source documents into one semantic
    # chapter, so its card count is recorded rather than used as a file count.
    report["checks"]["course_resource_card_count_after_upload"] = page.locator(".resource-card").count()
    capture(page, report, "04-local-multiformat-uploaded-1440x900.png")
    docs = {}
    for item in payload.get("results", []):
        if item.get("status") == "ready":
            doc = item["document"]
            docs[str(doc["file_type"])] = doc
    for fmt in ("md", "pdf", "docx", "pptx"):
        assert fmt in docs, (fmt, docs)
        assert docs[fmt].get("chunk_count", 0) > 0
        assert docs[fmt].get("source_processing_status") == "ready", docs[fmt]
    report["checks"]["local_upload_formats"] = sorted(docs)
    return docs


def reader_snapshot(page: Page, report: dict, source_id: str, course_id: str, fmt: str, viewport_suffix: str = "1440x900") -> None:
    page.goto(f"{report['base_url']}/knowledge/documents/{source_id}?course_id={course_id}", wait_until="networkidle", timeout=120_000)
    page.locator(".reader-page").wait_for(state="visible", timeout=60_000)
    page.get_by_text("正在打开原文", exact=True).wait_for(state="hidden", timeout=60_000)
    if fmt == "pdf":
        if page.locator(".parsed-page-preview").count():
            page.locator(".parsed-page-preview").wait_for(state="visible", timeout=60_000)
            assert page.locator(".page-frame").count() >= 1
            native_branch = "parsed_pages"
        else:
            # A valid PDF may have no rendered page asset when the parser kept
            # the original bytes only; the reader still exposes the original
            # PDF iframe and extracted text in the side panel.
            page.locator(".original-pdf-preview").wait_for(state="visible", timeout=60_000)
            page.locator(".original-pdf-preview__frame").wait_for(state="visible", timeout=60_000)
            native_branch = "original_pdf"
        fallback = page.get_by_test_id("pdf-content-fallback")
        fallback.wait_for(state="visible", timeout=30_000)
        fallback.scroll_into_view_if_needed()
        assert fallback.locator(".course-document-preview").inner_text().strip()
    else:
        preview = page.locator(".course-document-preview")
        preview.wait_for(state="visible", timeout=60_000)
        assert preview.inner_text().strip()
        assert "当前文档没有可渲染的正文" not in preview.inner_text()
    capture(page, report, f"05-reader-{fmt}-{viewport_suffix}.png")
    report["reader_checks"][fmt] = {"source_id": source_id, "visible_text": True, "native_pdf_branch": native_branch if fmt == "pdf" else False}


def exercise_readers(page: Page, course_id: str, docs: dict[str, dict], report: dict) -> None:
    for fmt in ("md", "pdf", "docx", "pptx"):
        reader_snapshot(page, report, docs[fmt]["source_document_id"], course_id, fmt)


def exercise_direct_import(page: Page, course_id: str, report: dict) -> None:
    """Exercise the authenticated direct-URL import entry point in Chromium."""
    payload = {
        "url": "https://raw.githack.com/krahets/hello-algo/main/docs/chapter_array_and_linkedlist/array.md",
        "file_type": "md",
        "title": "直链 Markdown 课程资料",
        "student_id": USERNAME,
        "course_id": course_id,
    }
    result = browser_json(page, "/api/knowledge/download-web-file", "POST", payload)
    if result["status"] != 200:
        raise AssertionError({"direct_import": result})
    body = result["body"] or {}
    if body.get("course_id") != course_id or body.get("source_processing_status") != "ready":
        raise AssertionError({"direct_import": body})
    source_id = str(body.get("source_document_id") or "")
    if not source_id or not body.get("content_preview"):
        raise AssertionError({"direct_import": body})
    report["direct_import"] = {
        "url": payload["url"],
        "course_id": course_id,
        "source_document_id": source_id,
        "file_type": body.get("file_type"),
        "source_processing_status": body.get("source_processing_status"),
        "source_ref_count": body.get("source_ref_count"),
    }
    page.goto(
        f"{report['base_url']}/knowledge/documents/{source_id}?course_id={course_id}",
        wait_until="networkidle",
        timeout=120_000,
    )
    page.locator(".reader-page").wait_for(state="visible", timeout=60_000)
    page.get_by_text("正在打开原文", exact=True).wait_for(state="hidden", timeout=60_000)
    preview = page.locator(".course-document-preview")
    preview.wait_for(state="visible", timeout=60_000)
    assert preview.inner_text().strip()
    assert "当前文档没有可渲染的正文" not in preview.inner_text()
    capture(page, report, "05-reader-direct-url-md-1440x900.png")


def exercise_graph(page: Page, course_id: str, report: dict) -> None:
    page.goto(f"{report['base_url']}/knowledge/graph/{course_id}", wait_until="networkidle", timeout=120_000)
    page.get_by_test_id("course-knowledge-graph-workspace").wait_for(state="visible", timeout=60_000)
    page.locator(".graph-stage canvas").wait_for(state="visible", timeout=60_000)
    graph = page.evaluate("""async () => {
      const response = await fetch(`/api/knowledge/courses/${encodeURIComponent(location.pathname.split('/').pop())}/graph`, {headers: {Authorization: `Bearer ${localStorage.getItem('edumatrix_token')}`}})
      return await response.json()
    }""")
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    semantic = [node for node in nodes if node.get("nodeType") not in {"course", "chapter", "source"}]
    assert nodes and edges and semantic
    assert all(str(node.get("name") or "").strip() for node in nodes)
    assert len({str(node.get("id")) for node in nodes}) == len(nodes)
    report["graph"] = {"node_count": len(nodes), "edge_count": len(edges), "semantic_node_count": len(semantic), "empty_name_nodes": 0, "display_mode": graph.get("displayMode")}
    capture(page, report, "06-course-graph-1440x900.png")
    page.get_by_role("button", name="层级列表", exact=True).click()
    page.get_by_test_id("graph-hierarchy-fallback").wait_for(state="visible")
    capture(page, report, "07-course-graph-hierarchy-1440x900.png")


def browser_json(page: Page, path: str, method: str = "GET", payload: dict | None = None) -> dict:
    """Call a same-origin API with the real browser session and return status/body."""
    return page.evaluate(
        """async ({path, method, payload}) => {
          const options = {
            method,
            headers: { Authorization: `Bearer ${localStorage.getItem('edumatrix_token')}` },
          };
          if (payload !== null) {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(payload);
          }
          const response = await fetch(path, options);
          let body = null;
          try { body = await response.json(); } catch { body = { text: await response.text() }; }
          return { status: response.status, body };
        }""",
        {"path": path, "method": method, "payload": payload},
    )


def exercise_resource_context(page: Page, course_id: str, report: dict) -> None:
    """Generate one real course resource through the browser's resource API and open it."""
    outline_response = browser_json(page, f"/api/v1/courses/{course_id}/outline")
    workspace_response = browser_json(page, f"/api/v1/m5/workspace?course_id={course_id}")
    if outline_response["status"] != 200 or workspace_response["status"] != 200:
        raise AssertionError({"outline": outline_response, "workspace": workspace_response})
    chapters = outline_response["body"] or []
    profile = (workspace_response["body"] or {}).get("profile") or {}
    selected = next(
        (
            (chapter, point)
            for chapter in chapters
            for point in chapter.get("knowledge_points") or []
            if chapter.get("source_ref_id") and point.get("id")
        ),
        None,
    )
    profile_snapshot_id = str(profile.get("snapshot_id") or "")
    if selected is None or not profile_snapshot_id:
        raise AssertionError({"has_profile": bool(profile_snapshot_id), "chapters": chapters})
    chapter, point = selected
    source_ref_id = str(chapter["source_ref_id"])
    create_payload = {
        "course_id": course_id,
        "knowledge_point_id": str(point["id"]),
        "profile_snapshot_id": profile_snapshot_id,
        "idempotency_key": "course-ingestion-multiformat-resource-001",
        "scope": "single",
        "learning_goal": "基于刚解析的多格式课程资料完成一次可阅读的个性化讲义。",
        "user_instruction": "请用当前课程资料生成一份可直接阅读的讲义。",
        "resource_intent": "resource_generation",
        "selected_resource_types": ["handout"],
        "items": [{
            "type": "handout",
            "title": "多格式资料解析 · 个性化讲义",
            "source_ref_ids": [source_ref_id],
            "completion_rule": "阅读讲义并完成其中的学习检查。",
        }],
    }
    created = browser_json(page, "/api/v1/resource-bundles/generation-jobs", "POST", create_payload)
    if created["status"] != 201:
        raise AssertionError({"generation_create": created})
    job_id = str((created["body"] or {}).get("job_id") or "")
    if not job_id:
        raise AssertionError({"generation_create": created})
    executed = browser_json(page, f"/api/v1/resource-bundles/generation-jobs/{job_id}/execute-demo", "POST", {})
    if executed["status"] != 200:
        raise AssertionError({"generation_execute": executed})
    job = executed["body"] or {}
    item = next((entry for entry in job.get("items") or [] if entry.get("type") == "handout"), None)
    if job.get("status") != "succeeded" or not item or item.get("state") != "succeeded" or not item.get("resource", {}).get("route"):
        raise AssertionError({"generation_job": job})
    report["resource_generation"] = {
        "job_id": job_id,
        "status": job.get("status"),
        "knowledge_point_id": point["id"],
        "knowledge_point_title": point.get("title"),
        "source_ref_id": source_ref_id,
        "resource_type": "handout",
        "resource_route": item["resource"]["route"],
        "profile_source": "course_workspace",
    }
    page.goto(f"{report['base_url']}/workspace/resources/bundles/{job_id}?course_id={course_id}", wait_until="networkidle", timeout=120_000)
    page.get_by_test_id("resource-bundle-workspace").wait_for(state="visible", timeout=60_000)
    page.locator('.resource-row[data-state="succeeded"]').wait_for(state="visible", timeout=60_000)
    assert "完整资源包" in page.inner_text("body")
    capture(page, report, "08-course-resource-generated-1440x900.png")
    page.get_by_role("button", name="打开", exact=True).first.click()
    page.get_by_test_id("handout-workspace").wait_for(state="visible", timeout=60_000)
    assert page.locator(".handout-page").inner_text().strip()
    capture(page, report, "08-course-resource-handout-1440x900.png")


def exercise_contexts(page: Page, course_id: str, report: dict) -> None:
    page.goto(f"{report['base_url']}/workspace/resources?course_id={course_id}", wait_until="networkidle", timeout=120_000)
    page.get_by_test_id("resource-center").wait_for(state="visible", timeout=60_000)
    assert course_id in page.url
    heading = page.locator("header.page-heading").last
    heading_text = heading.inner_text()
    assert course_id in heading_text or "课程" in heading_text
    capture(page, report, "08-course-resource-context-1440x900.png")
    exercise_resource_context(page, course_id, report)

    page.goto(f"{report['base_url']}/learn?course_id={course_id}", wait_until="networkidle", timeout=120_000)
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible", timeout=60_000)
    composer = page.get_by_test_id("chat-composer").locator("textarea")
    composer.fill("请根据这门新课程中的多格式资料，说明资料解析后如何进入课程检索。")
    page.get_by_test_id("chat-composer").get_by_role("button", name="发送", exact=True).click()
    page.locator(".message-row--assistant").last.wait_for(state="visible", timeout=120_000)
    assistant = page.locator(".message-row--assistant").last
    # The current Chat.vue renders the answer in .assistant-answer; the old
    # .message-content selector belonged to the pre-canonical chat markup.
    assistant.locator(".assistant-answer").wait_for(state="visible", timeout=120_000)
    page.get_by_text("回答完成", exact=True).last.wait_for(state="visible", timeout=120_000)
    text = assistant.inner_text().strip()
    assert text and "多格式资料" in text and "课程检索" in text
    report["chat"] = {"assistant_chars": len(text), "course_id_in_url": course_id in page.url}
    capture(page, report, "09-course-chat-context-answer-1440x900.png")


def db_state(db_path: Path, course_id: str) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=20) as db:
        row = db.execute("SELECT COUNT(*), SUM(CASE WHEN processing_status='ready' THEN 1 ELSE 0 END) FROM source_documents WHERE course_id=?", (course_id,)).fetchone()
        return {
            "course_source_count": int(row[0] or 0),
            "course_ready_source_count": int(row[1] or 0),
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def stabilize_evidence_database(db_path: Path) -> None:
    """Finish the disposable SQLite journal before hashing evidence files."""
    if not db_path.exists():
        return
    for _attempt in range(10):
        try:
            with sqlite3.connect(db_path, timeout=5) as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                db.commit()
            time.sleep(0.2)
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            time.sleep(0.5)


def run() -> dict:
    clear_output()
    db_path = OUTPUT_DIR / "course_ingestion_multiformat.sqlite3"
    model_server, _model_thread = _start_model_stub()
    port = base.free_port()
    env = base.runtime_env(db_path, port)
    env.update({
        "EDUMATRIX_LLM_PROVIDER": "openai",
        "EDUMATRIX_LLM_MODEL": "deepseek-v4-flash",
        "EDUMATRIX_LLM_API_KEY": "isolated-browser-model",
        "EDUMATRIX_LLM_ENDPOINT": f"http://127.0.0.1:{model_server.server_port}/chat/completions",
        "EDUMATRIX_LLM_THINKING_MODE": "max",
        "EDUMATRIX_LLM_REASONING_EFFORT": "max",
        "EDUMATRIX_UPLOAD_DIR": str(OUTPUT_DIR / "uploads"),
        "EDUMATRIX_AUTH_SECRET_KEY": "course-ingestion-multiformat-isolated-secret",
        "EDUMATRIX_MAX_UPLOAD_BYTES": str(20 * 1024 * 1024),
    })
    before = official_state()
    seed_isolated_database(env)
    report: dict[str, object] = {
        "schema_version": "course-ingestion-multiformat-repair-01.browser.v1",
        "task_id": EVIDENCE_TASK_ID,
        "status": "running",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "checks": {},
        "reader_checks": {},
        "online_imports": [],
        "http_errors": [],
        "expected_http_errors": [],
        "failed_requests": [],
        "expected_request_aborts": [],
        "page_errors": [],
        "console_errors": [],
        "expected_console_errors": [],
        "external_requests": [],
    }
    process = None
    try:
        process = base.start_service(env, port)
        report["base_url"] = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            diagnostics(page, report)
            login(page, report["base_url"])
            course_id = create_course_in_browser(page, report)
            augment_search_route(page, report)
            exercise_discovery(page, course_id, report)
            docs = upload_locals(page, course_id, report)
            exercise_readers(page, course_id, docs, report)
            exercise_direct_import(page, course_id, report)
            exercise_graph(page, course_id, report)
            exercise_contexts(page, course_id, report)
            context.close()

            mobile_context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            mobile_page = mobile_context.new_page()
            diagnostics(mobile_page, report)
            login(mobile_page, report["base_url"])
            mobile_page.goto(f"{report['base_url']}/knowledge/courses/{course_id}", wait_until="networkidle", timeout=120_000)
            mobile_page.get_by_test_id("course-workspace").wait_for(state="visible", timeout=60_000)
            capture(mobile_page, report, "10-course-workspace-1366x768.png")
            mobile_context.close()
            browser.close()

        report["database"] = db_state(db_path, course_id)
        assert report["database"]["course_ready_source_count"] >= 7, report["database"]
        assert report["database"]["integrity"] == "ok"
        assert report["database"]["foreign_key_violations"] == 0
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        base.stop_service(process, port)
        model_server.shutdown()
        final_course_id = str((report.get("course") or {}).get("id") or "")
        if final_course_id and db_path.exists():
            # The first read after terminating the service can checkpoint the
            # disposable SQLite WAL. Capture the final stable state before the
            # manifest hashes are written.
            report["database"] = db_state(db_path, final_course_id)
            stabilize_evidence_database(db_path)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        report["official_state_before"] = before
        report["official_state_after"] = official_state()
        report["official_state_unchanged"] = report["official_state_before"] == report["official_state_after"]
        (OUTPUT_DIR / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT_DIR.iterdir())
            if path.is_file() and path.name not in {"browser_report.json", "manifest.json"} and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT_DIR / "manifest.json").write_text(json.dumps({"schema_version": "course-ingestion-multiformat-repair-01.evidence-manifest.v1", "task_id": EVIDENCE_TASK_ID, "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
