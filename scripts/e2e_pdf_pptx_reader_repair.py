"""PDF/PPTX native reader repair acceptance on isolated SQLite and Chromium."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

import e2e_f6_t03_code_sandbox as base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "PDF-PPTX-READER-REPAIR-01" / "browser"
COURSE_ID = "course-embedded-machine-learning-engineering-v2"
USERNAME = "lzz"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def seed_fixture(env: dict[str, str]) -> dict[str, object]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import json
from pathlib import Path
from app.competition_demo_seed import seed_competition_demo
from app.database import DBSourceDocument, DBUser, SessionLocal, init_db
from course_catalog import seed_default_courses

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    seed_default_courses(db)
    db.query(DBUser).filter_by(username={USERNAME!r}).one()
    sources = db.query(DBSourceDocument).filter_by(course_id={COURSE_ID!r}, processing_status="ready").all()
    pdf = next((row for row in sources if row.file_format == "pdf"), None)
    pptx = next((row for row in sources if row.file_format == "pptx" and row.filename.startswith("3.3.5.")), None)
    blank = next((row for row in sources if row.file_format == "pptx" and row.filename.startswith("2.2.1.")), None)
    if pdf is None or pptx is None or blank is None:
        raise RuntimeError("required built-in PDF/PPTX fixtures are missing")
    result = {{
        "pdf": {{"source_id": pdf.id, "course_id": pdf.course_id, "title": pdf.title}},
        "pptx": {{"source_id": pptx.id, "course_id": pptx.course_id, "title": pptx.title}},
        "blank_pptx": {{"source_id": blank.id, "course_id": blank.course_id, "title": blank.title}},
        "initial_learning_events": db.execute(__import__("sqlalchemy").text("SELECT COUNT(*) FROM learning_events")).scalar_one(),
    }}
    Path({str(fixture_path)!r}).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=240)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def snapshot_official_state() -> dict[str, str]:
    paths = [
        ROOT / "edumatrix.db",
        ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "active_manifest.json",
        ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "current_checkpoint.json",
    ]
    return {str(path): digest(path) for path in paths if path.is_file()}


def page_diagnostics(page: Page, report: dict[str, object]) -> None:
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


def capture(page: Page, report: dict[str, object], filename: str) -> None:
    page.screenshot(path=OUTPUT_DIR / filename, full_page=True)
    report["screenshots"].append(filename)


def open_reader(page: Page, base_url: str, item: dict[str, object]) -> None:
    page.goto(f"{base_url}/knowledge/documents/{item['source_id']}?course_id={item['course_id']}", wait_until="networkidle", timeout=60_000)
    page.locator(".reader-page").wait_for(state="visible")
    page.get_by_text("正在打开原文", exact=True).wait_for(state="hidden", timeout=60_000)


def visual_contract(page: Page) -> dict[str, object]:
    return page.evaluate("""
      () => {
        const root = document.querySelector('.reader-page')
        const visible = element => {
          if (!element) return false
          const style = getComputedStyle(element)
          const box = element.getBoundingClientRect()
          return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0
        }
        const textNodes = [...(root?.querySelectorAll('button, h1, h2, h3, h4, p, strong, span, label, summary') || [])]
          .filter(element => visible(element) && element.textContent.trim())
        const clippedText = textNodes.filter(element => {
          const style = getComputedStyle(element)
          if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
          return element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 4
        }).map(element => element.textContent.trim().slice(0, 80))
        return {
          pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          readerVisible: visible(root),
          clippedText,
          pptxReader: visible(root?.querySelector('.pptx-reader')),
          slideCanvas: visible(root?.querySelector('.pptx-slide-canvas')),
          thumbnails: root?.querySelectorAll('.pptx-thumbnail').length || 0,
          emptyThumbnails: root?.querySelectorAll('.pptx-thumbnail__empty').length || 0,
          textOnlyThumbnails: root?.querySelectorAll('.pptx-thumbnail__text-only').length || 0,
          pdfOriginal: visible(root?.querySelector('.original-pdf-preview')),
          pdfIframe: visible(root?.querySelector('.original-pdf-preview__frame')),
          parsedPreview: root?.querySelectorAll('.course-document-preview').length || 0,
          emptySlide: visible(root?.querySelector('.pptx-slide-canvas__empty')),
        }
      }
    """)


def exercise_pdf(page: Page, base_url: str, fixture: dict[str, object], report: dict[str, object]) -> None:
    open_reader(page, base_url, fixture["pdf"])
    page.locator(".original-pdf-preview").wait_for(state="visible", timeout=60_000)
    page.locator(".original-pdf-preview__frame").wait_for(state="visible", timeout=60_000)
    page.locator(".parsed-page-preview").wait_for(state="visible", timeout=60_000)
    result = page.evaluate("""
      () => ({
        iframeVisible: Boolean(document.querySelector('.original-pdf-preview__frame')),
        originalError: Boolean(document.querySelector('.original-pdf-preview [data-testid=task-state-error]')),
        parsedPages: document.querySelectorAll('.parsed-page-preview .page-frame').length,
      })
    """)
    report["checks"]["pdf_native_iframe"] = result
    assert result["iframeVisible"] is True
    assert result["originalError"] is False
    assert result["parsedPages"] >= 1
    page.get_by_label("在当前文档中搜索").fill("量化")
    page.wait_for_timeout(300)
    assert "无结果" not in page.locator(".reader-search").inner_text()
    report["visual"]["pdf_1440x900"] = visual_contract(page)
    capture(page, report, "01-pdf-native-preview-1440x900.png")


def probe_pdf_export(page: Page, base_url: str, item: dict[str, object], report: dict[str, object]) -> None:
    response = page.request.get(f"{base_url}/api/v1/document-reader/documents/{item['source_id']}/export")
    body = response.body()
    content_type = str(response.headers.get("content-type") or "").lower()
    result = {
        "status": response.status,
        "content_type": content_type,
        "prefix": body[:5].decode("latin1"),
        "bytes": len(body),
    }
    report["checks"]["pdf_export"] = result
    assert response.status == 200
    assert "application/pdf" in content_type
    assert body[:5] == b"%PDF-"
    assert len(body) > 100


def exercise_pptx(page: Page, base_url: str, item: dict[str, object], report: dict[str, object], prefix: str) -> None:
    open_reader(page, base_url, item)
    page.locator(".pptx-reader").wait_for(state="visible", timeout=60_000)
    page.locator(".pptx-slide-canvas").wait_for(state="visible", timeout=60_000)
    thumbnails = page.locator(".pptx-thumbnail")
    is_multi = prefix in {"pptx", "pptx-1366"}
    viewport_suffix = "1366x768" if prefix.endswith("-1366") else "1440x900"
    assert thumbnails.count() >= 2 if is_multi else thumbnails.count() == 1
    if is_multi:
        assert page.locator('.pptx-thumbnail__empty').count() == 0
        assert page.locator('.pptx-thumbnail__text-only').count() >= 1
    else:
        assert page.locator('.pptx-thumbnail__empty').count() == 1
    first_text = page.locator(".pptx-slide-canvas").inner_text()
    report["visual"][f"{prefix}_initial_{viewport_suffix}"] = visual_contract(page)
    capture(page, report, f"02-{prefix}-initial-{viewport_suffix}.png")
    if is_multi:
        page.get_by_label("下一张幻灯片").click()
        page.wait_for_timeout(250)
        second_text = page.locator(".pptx-slide-canvas").inner_text()
        assert second_text != first_text
        assert "第 2 /" in page.locator(".pptx-reader__controls").inner_text()
        report["checks"]["pptx_next_slide"] = {"first_text": first_text[:100], "second_text": second_text[:100]}
        capture(page, report, f"03-{prefix}-next-slide-{viewport_suffix}.png")
    else:
        page.locator(".pptx-slide-canvas__empty").wait_for(state="visible")
        report["checks"]["blank_pptx_empty_state"] = True
        capture(page, report, f"04-{prefix}-blank-slide-{viewport_suffix}.png")


def database_state(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path) as db:
        return {
            "learning_event_count": db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def run() -> dict[str, object]:
    clear_output()
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = int(os.getenv("EDUMATRIX_PDF_PPTX_REPAIR_PORT", "8998"))
    db_path = OUTPUT_DIR / "pdf_pptx_reader_repair.sqlite3"
    port = base.free_port()
    env = base.runtime_env(db_path, port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "pdf-pptx-reader-repair-secret"
    env["EDUMATRIX_UPLOAD_DIR"] = str(OUTPUT_DIR / "uploads")
    official_before = snapshot_official_state()
    fixture = seed_fixture(env)
    process = None
    report: dict[str, object] = {
        "schema_version": "pdf-pptx-reader-repair-01.browser.v1",
        "task_id": "PDF-PPTX-READER-REPAIR-01",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [], "checks": {}, "visual": {},
        "http_errors": [], "failed_requests": [], "page_errors": [],
        "console_errors": [], "external_requests": [], "expected_request_aborts": [], "external_model_called": False,
        "fixture": fixture,
    }
    try:
        process = base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page(); page_diagnostics(page, report); base.login(page, base_url)
            probe_pdf_export(page, base_url, fixture["pdf"], report)
            exercise_pdf(page, base_url, fixture, report)
            exercise_pptx(page, base_url, fixture["pptx"], report, "pptx")
            exercise_pptx(page, base_url, fixture["blank_pptx"], report, "blank-pptx")
            context.close()
            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page(); page_diagnostics(page, report); base.login(page, base_url)
            exercise_pptx(page, base_url, fixture["pptx"], report, "pptx-1366")
            capture(page, report, "05-pptx-1366x768.png")
            context.close(); browser.close()
        report["database"] = database_state(db_path)
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
        base.stop_service(process, port)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        report["official_state_before"] = official_before
        report["official_state_after"] = snapshot_official_state()
        report["official_state_unchanged"] = report["official_state_before"] == report["official_state_after"]
        (OUTPUT_DIR / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)} for path in sorted(OUTPUT_DIR.iterdir()) if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))]
        (OUTPUT_DIR / "manifest.json").write_text(json.dumps({"schema_version": "pdf-pptx-reader-repair-01.evidence-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
