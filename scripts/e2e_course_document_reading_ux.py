"""COURSE-DOCUMENT-READING-UX-01 isolated browser acceptance.

The journey exercises the two built-in Markdown courses through the real
reader route, then checks the existing PDF/video branches.  It deliberately
uses a disposable SQLite database and never writes the official database or
checkpoint package.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

import e2e_f6_t03_code_sandbox as base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "custom_tasks"
    / "COURSE-DOCUMENT-READING-UX-01"
    / "browser"
)
MASTER_COURSE_ID = "course-ai-deep-learning-agents-v1"
SECONDARY_COURSE_ID = "course-data-structures-algorithms-engineering-v1"
PDF_COURSE_ID = "course-embedded-machine-learning-engineering-v2"
USERNAME = "lzz"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            import shutil

            shutil.rmtree(item)


def seed_fixture(env: dict[str, str]) -> dict[str, object]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import json
from pathlib import Path
from app.competition_demo_seed import seed_competition_demo
from app.database import DBChapter, DBCourse, DBSourceDocument, DBSourceRef, DBUser, SessionLocal, init_db
from course_catalog import seed_default_courses

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    seed_default_courses(db)
    user = db.query(DBUser).filter_by(username={USERNAME!r}).one()

    def pick(course_id, needle):
        sources = db.query(DBSourceDocument).filter_by(course_id=course_id, processing_status="ready").all()
        for source in sources:
            if source.file_format in {{"md", "markdown"}} and needle in (source.title or ""):
                return source
        for source in sources:
            if source.file_format in {{"md", "markdown"}}:
                return source
        raise RuntimeError(f"markdown source missing for {{course_id}}")

    master = pick({MASTER_COURSE_ID!r}, "注意力")
    secondary = pick({SECONDARY_COURSE_ID!r}, "查找")
    pdf = db.query(DBSourceDocument).filter_by(course_id={PDF_COURSE_ID!r}, file_format="pdf", processing_status="ready").first()
    video = db.query(DBSourceDocument).filter_by(course_id={PDF_COURSE_ID!r}, file_format="mp4", processing_status="ready").first()
    if pdf is None or video is None:
        raise RuntimeError("preloaded PDF/video compatibility fixtures are missing")

    def payload(source):
        ref = db.query(DBSourceRef).filter_by(source_document_id=source.id).order_by(DBSourceRef.location_index, DBSourceRef.id).first()
        chapter = db.get(DBChapter, ref.chapter_id) if ref and ref.chapter_id else None
        return {{
            "source_id": source.id,
            "course_id": source.course_id,
            "title": source.title,
            "version": str(source.processed_sha256 or source.content_hash or ""),
            "ref_id": ref.id if ref else "",
            "chapter_id": chapter.id if chapter else "",
            "chapter_title": chapter.title if chapter else "",
        }}

    result = {{
        "master": payload(master),
        "secondary": payload(secondary),
        "pdf": payload(pdf),
        "video": payload(video),
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
        failure = request.failure or ""
        # Navigating away from the video reader revokes its local object URL;
        # Chromium reports that expected media teardown as ERR_ABORTED.  Keep
        # it visible in the report, but do not classify it as an application
        # request failure.
        if request.url.startswith("blob:") and failure == "net::ERR_ABORTED":
            report.setdefault("expected_request_aborts", []).append({"url": request.url, "failure": failure})
            return
        report["failed_requests"].append({"url": request.url, "failure": failure})
    page.on("requestfailed", on_request_failed)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def capture(page: Page, report: dict[str, object], filename: str) -> None:
    path = OUTPUT_DIR / filename
    page.screenshot(path=path, full_page=True)
    report["screenshots"].append(filename)


def visual_contract(page: Page) -> dict[str, object]:
    return page.evaluate(
        """
        () => {
          const root = document.querySelector('.reader-page')
          if (!root) return { missingRoot: true }
          const visible = element => {
            const style = getComputedStyle(element)
            const box = element.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0
          }
          const textNodes = [...root.querySelectorAll('button, h1, h2, h3, h4, p, strong, label, summary, dt, dd, li')]
            .filter(element => visible(element) && element.textContent.trim())
          const smallText = textNodes
            .filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 13.9)
            .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 70), size: getComputedStyle(element).fontSize }))
          const clippedText = textNodes
            .filter(element => {
              const style = getComputedStyle(element)
              if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
              if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
              // Chromium rounds fractional line boxes; a few pixels of vertical
              // difference is normal and is not visible clipping.  Keep the
              // horizontal check strict and require a real vertical overflow.
              return element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 4
            })
            .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 70) }))
          const outline = root.querySelector('.reader-outline')?.getBoundingClientRect()
          const main = root.querySelector('.reader-main')?.getBoundingClientRect()
          const context = root.querySelector('.reader-context')?.getBoundingClientRect()
          return {
            missingRoot: false,
            pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 || root.scrollWidth > root.clientWidth + 1,
            ordered: Boolean(outline && main && context && outline.right <= main.left + 1 && main.right <= context.left + 1),
            centerIsLargest: Boolean(main && outline && context && main.width > outline.width && main.width > context.width),
            smallText,
            clippedText,
            previewVisible: Boolean(root.querySelector('.course-document-preview')),
            rawVisible: Boolean(root.querySelector('.course-document-raw')),
            lessonBlocks: root.querySelectorAll('.lesson-block').length,
            practiceBlocks: root.querySelectorAll('.lesson-block--practice').length,
            formulaBlocks: root.querySelectorAll('.lesson-block--formula').length,
            tableBlocks: root.querySelectorAll('.lesson-block--comparison').length,
            calloutBlocks: root.querySelectorAll('.lesson-block--callout').length,
          }
        }
        """
    )


def assert_visual(page: Page, report: dict[str, object], key: str) -> dict[str, object]:
    result = visual_contract(page)
    report["visual"][key] = result
    assert result["missingRoot"] is False, result
    assert result["pageOverflow"] is False, result
    assert result["ordered"] is True, result
    assert result["centerIsLargest"] is True, result
    assert result["smallText"] == [], result
    assert result["clippedText"] == [], result
    return result


def open_reader(page: Page, base_url: str, item: dict[str, object]) -> None:
    page.goto(
        f"{base_url}/knowledge/documents/{item['source_id']}?course_id={item['course_id']}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.locator(".reader-page").wait_for(state="visible")
    page.get_by_text("正在打开原文", exact=True).wait_for(state="hidden", timeout=60_000)


def select_preview_text(page: Page) -> None:
    page.locator(".course-document-preview").evaluate(
        """
        element => {
          const candidate = element.querySelector('.lesson-block--explanation p, .lesson-block--summary p')
          if (!candidate) throw new Error('preview explanation block not found')
          const walker = document.createTreeWalker(candidate, NodeFilter.SHOW_TEXT)
          let node = walker.nextNode()
          while (node && !node.textContent.trim()) node = walker.nextNode()
          if (!node) throw new Error('preview text node not found')
          const start = Math.max(0, node.textContent.search(/\\S/))
          const end = Math.min(node.textContent.length, start + 60)
          const range = document.createRange()
          range.setStart(node, start)
          range.setEnd(node, end)
          const selection = window.getSelection()
          selection.removeAllRanges()
          selection.addRange(range)
          element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, view: window }))
        }
        """
    )
    page.get_by_role("toolbar", name="文本选区操作").wait_for(state="visible", timeout=20_000)


def exercise_markdown(page: Page, base_url: str, item: dict[str, object], report: dict[str, object], label: str) -> None:
    open_reader(page, base_url, item)
    preview = page.locator(".course-document-preview")
    preview.wait_for(state="visible", timeout=30_000)
    assert page.locator(".reader-header").get_by_role("heading").is_visible()
    assert preview.locator(".course-heading").count() >= 1
    assert preview.locator(".lesson-block--practice").count() >= 1
    text = preview.inner_text()
    assert text.strip()
    assert "当前文档没有可渲染的正文" not in text
    first = assert_visual(page, report, f"{label}_preview_1440x900")
    capture(page, report, f"{label}-01-reading-preview-1440x900.png")

    page.get_by_role("button", name="原文", exact=True).click()
    raw = page.locator(".course-document-raw")
    raw.wait_for(state="visible")
    assert "#" in raw.inner_text()
    assert page.locator(".course-document-preview").count() == 0
    capture(page, report, f"{label}-02-raw-markdown-1440x900.png")

    page.get_by_role("button", name="阅读版", exact=True).click()
    preview.wait_for(state="visible")
    assert page.get_by_text("已生成本版预览", exact=True).count() + page.get_by_text("已使用本版缓存", exact=True).count() >= 1
    cache_keys = page.evaluate("Object.keys(localStorage).filter(key => key.includes('edumatrix.course-document.preview.'))")
    assert any(str(item["source_id"]) in key and str(item["version"]) in key for key in cache_keys), cache_keys

    page.reload(wait_until="networkidle")
    preview = page.locator(".course-document-preview")
    preview.wait_for(state="visible", timeout=30_000)
    page.get_by_text("已使用本版缓存", exact=True).wait_for(state="visible", timeout=15_000)
    report["checks"][f"{label}_cache_hit"] = True
    capture(page, report, f"{label}-03-cache-hit-1440x900.png")

    # A stale-version entry must not be consumed.  Remove only the current
    # browser cache key in the disposable context and leave an old-version
    # sentinel behind; the reader must regenerate the current version.
    current_key = next(key for key in cache_keys if str(item["source_id"]) in key and str(item["version"]) in key)
    old_key = current_key.replace(str(item["version"]), "old-version-sentinel")
    page.evaluate(
        """
        ({ currentKey, oldKey }) => {
          const value = JSON.parse(localStorage.getItem(currentKey) || '{}')
          value.html = '<p>STALE VERSION SENTINEL</p>'
          value.rendererVersion = value.rendererVersion || 'course-document-renderer-v1'
          localStorage.removeItem(currentKey)
          localStorage.setItem(oldKey, JSON.stringify(value))
        }
        """,
        {"currentKey": current_key, "oldKey": old_key},
    )
    page.reload(wait_until="networkidle")
    preview = page.locator(".course-document-preview")
    preview.wait_for(state="visible", timeout=30_000)
    page.get_by_text("已生成本版预览", exact=True).wait_for(state="visible", timeout=15_000)
    assert "STALE VERSION SENTINEL" not in preview.inner_text()
    report["checks"][f"{label}_stale_version_rejected"] = True

    query = "注意力机制与 Transformer" if label == "master" else "二分查找"
    page.get_by_label("在当前文档中搜索").fill(query)
    page.wait_for_timeout(250)
    assert "无结果" not in page.locator(".reader-search").inner_text()
    page.get_by_title("下一个搜索结果").click()
    page.locator(".course-search-hit--current").wait_for(state="visible", timeout=15_000)
    capture(page, report, f"{label}-04-search-highlight-1440x900.png")

    select_preview_text(page)
    selection_toolbar = page.get_by_role("toolbar", name="文本选区操作")
    selection_toolbar.wait_for(state="visible", timeout=15_000)
    capture(page, report, f"{label}-05-selection-toolbar-1440x900.png")
    # The reader keeps the source tab selected after creating a selection.
    # Switch through the same action a learner uses before checking the quote.
    selection_toolbar.get_by_role("button", name="提问", exact=True).click()
    summary = page.locator(".context-panel:visible .selection-summary")
    summary.wait_for(state="visible", timeout=15_000)
    assert summary.inner_text().strip() and "先在正文中划选" not in summary.inner_text()
    report["checks"][f"{label}_selection_quote_visible"] = True
    report["checks"][f"{label}_selection_summary_after_ask"] = True
    capture(page, report, f"{label}-06-selection-summary-1440x900.png")

    # Chapter navigation remains a reader concern, not a rendering concern.
    buttons = page.locator(".chapter-list > button")
    if buttons.count() > 1:
        buttons.nth(1).click()
        page.wait_for_timeout(250)
        assert page.locator(".chapter-list > button.active").count() >= 1
        report["checks"][f"{label}_chapter_navigation"] = True


def exercise_pdf_video(page: Page, base_url: str, fixture: dict[str, object], report: dict[str, object]) -> None:
    open_reader(page, base_url, fixture["pdf"])
    page.locator(".reader-page").wait_for(state="visible")
    page.locator(".parsed-page-preview").wait_for(state="visible", timeout=60_000)
    assert page.locator(".course-document-preview").count() == 0
    assert page.locator(".page-frame").count() >= 1
    report["checks"]["pdf_branch_preserved"] = True
    capture(page, report, "pdf-06-reader-branch-1440x900.png")

    open_reader(page, base_url, fixture["video"])
    page.locator(".media-reader").wait_for(state="visible", timeout=60_000)
    assert page.locator("video").count() == 1
    assert page.locator(".course-document-preview").count() == 0
    report["checks"]["video_branch_preserved"] = True
    capture(page, report, "video-07-reader-branch-1440x900.png")


def database_state(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        return {
            "learning_event_count": db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
            "selection_count": db.execute("SELECT COUNT(*) FROM document_selections").fetchone()[0],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def run() -> dict[str, object]:
    clear_output()
    db_path = OUTPUT_DIR / "course_document_reading_ux.sqlite3"
    port = base.free_port()
    env = base.runtime_env(db_path, port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "course-document-reading-ux-isolated-secret"
    env["EDUMATRIX_UPLOAD_DIR"] = str(OUTPUT_DIR / "uploads")
    official_before = snapshot_official_state()
    fixture = seed_fixture(env)
    process: subprocess.Popen | None = None
    report: dict[str, object] = {
        "schema_version": "course-document-reading-ux-01.browser.v1",
        "task_id": "COURSE-DOCUMENT-READING-UX-01",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "checks": {},
        "visual": {},
        "http_errors": [],
        "failed_requests": [],
        "expected_request_aborts": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "external_model_called": False,
        "fixture": fixture,
    }
    try:
        process = base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            base.login(page, base_url)
            exercise_markdown(page, base_url, fixture["master"], report, "master")
            exercise_markdown(page, base_url, fixture["secondary"], report, "secondary")
            exercise_pdf_video(page, base_url, fixture, report)
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            base.login(page, base_url)
            open_reader(page, base_url, fixture["master"])
            page.locator(".course-document-preview").wait_for(state="visible", timeout=30_000)
            assert_visual(page, report, "master_preview_1366x768")
            capture(page, report, "master-08-reading-preview-1366x768.png")
            context.close()
            browser.close()

        report["database"] = database_state(db_path)
        # Opening, searching, selecting and caching are read-only.  No note,
        # resource or mastery event should be created by this acceptance run.
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
        report_path = OUTPUT_DIR / "browser_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT_DIR.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT_DIR / "manifest.json").write_text(
            json.dumps({"schema_version": "course-document-reading-ux-01.evidence-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
