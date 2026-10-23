"""F7-T02 large document reader desktop E2E on isolated SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

import e2e_f6_t03_code_sandbox as base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "f7_t02_document_reader"
    / "browser"
)
COURSE_ID = "course-machine-learning-foundations-v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def seed_fixture(
    env: dict[str, str],
    *,
    initialize_demo: bool = True,
) -> dict[str, object]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBChapter, DBCourse, DBCourseMembership, DBKnowledgeDocument, DBSourceDocument,
    DBSourceRef, DBStudentProfile, DBUser, SessionLocal, init_db,
)
from course_catalog import seed_default_courses

init_db()
db = SessionLocal()
try:
    if {initialize_demo!r}:
        seed_competition_demo(db)
    seed_default_courses(db)
    user = db.query(DBUser).filter_by(username="lzz").one()
    if db.get(DBStudentProfile, "lzz") is None:
        db.add(DBStudentProfile(student_id="lzz"))
        db.flush()
    source = (
        db.query(DBSourceDocument)
        .filter_by(course_id={COURSE_ID!r}, processing_status="ready")
        .order_by(DBSourceDocument.id)
        .first()
    )
    if source is None:
        raise RuntimeError("flagship source is missing")
    source_ref = (
        db.query(DBSourceRef)
        .filter_by(source_document_id=source.id)
        .order_by(DBSourceRef.location_index, DBSourceRef.id)
        .first()
    )
    document = db.get(DBKnowledgeDocument, source.legacy_document_id) if source.legacy_document_id else None
    course_document = __import__("app.database", fromlist=["DBCourseDocument"]).DBCourseDocument
    canonical = db.get(course_document, source.legacy_document_id) if source.legacy_document_id else None
    content = str((canonical.content if canonical is not None else None) or (document.content if document is not None else None) or "")
    search_term = next((term for term in ("机器学习", "学习", "模型", "数据") if term in content), content.strip()[:2])
    if not source_ref or not content or not search_term:
        raise RuntimeError("flagship source content or source ref is missing")

    pdf_course = DBCourse(
        id="f7-t02-browser-pdf-course",
        version="1",
        title="视觉教材选区演示",
        visibility="private",
        status="draft",
        owner_public_id=user.public_id,
        manifest_version="f7-t02-browser-v1",
        content_origin="isolated_e2e_fixture",
        license_text="仅用于隔离验收",
    )
    pdf_document = DBKnowledgeDocument(
        id="f7-t02-browser-pdf",
        student_id="lzz",
        filename="cnn-visual-guide.pdf",
        file_type="pdf",
        title="卷积网络视觉讲义",
        content="卷积层通过局部感受野提取空间特征。池化层压缩空间尺寸。",
    )
    content_hash = hashlib.sha256(pdf_document.content.encode("utf-8")).hexdigest()
    asset_dir = Path({env['EDUMATRIX_UPLOAD_DIR']!r}) / "lzz" / pdf_document.id / "ocr"
    asset_dir.mkdir(parents=True, exist_ok=True)
    asset_path = asset_dir / "page-1-redacted.png"
    image = Image.new("RGB", (1000, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((90, 80, 540, 330), outline=(17, 33, 45), width=5)
    draw.rectangle((155, 145, 285, 260), outline=(74, 92, 106), width=4)
    draw.line((285, 202, 440, 202), fill=(17, 33, 45), width=5)
    draw.polygon(((430, 188), (460, 202), (430, 216)), fill=(17, 33, 45))
    draw.text((110, 360), "CNN feature extraction diagram", fill=(17, 33, 45))
    draw.text((110, 405), "Drag a rectangle around the diagram to ask.", fill=(74, 92, 106))
    image.save(asset_path, format="PNG")
    asset_hash = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    pdf_source = DBSourceDocument(
        id="f7-t02-browser-pdf-source",
        course_id=pdf_course.id,
        legacy_document_id=pdf_document.id,
        title=pdf_document.title,
        filename=pdf_document.filename,
        file_format="pdf",
        content_hash=content_hash,
        source_sha256=asset_hash,
        processed_sha256=content_hash,
        source_path="isolated-browser-fixture/cnn-visual-guide.pdf",
        uploader_public_id=user.public_id,
        parser_version="f7-t02-browser-parser-v1",
        parser_metadata={{
            "ocr": {{
                "status": "ready",
                "page_count": 1,
                "region_count": 1,
                "sensitive_region_count": 0,
                "pages": [{{
                    "page_number": 1,
                    "width_px": 1000,
                    "height_px": 800,
                    "asset_name": asset_path.name,
                    "redacted_image_sha256": asset_hash,
                    "regions": [{{
                        "region_id": "cnn-diagram",
                        "bbox": {{"x": 0.09, "y": 0.1, "width": 0.46, "height": 0.32}},
                        "content": {{"text": "卷积层通过局部感受野提取空间特征"}},
                        "privacy": {{"sensitive": False}},
                    }}],
                }}],
            }}
        }},
        processing_status="ready",
        license_text="仅用于隔离验收",
    )
    db.add_all([pdf_course, pdf_document, pdf_source])
    db.flush()
    pdf_chapter = DBChapter(
        id="f7-t02-browser-pdf-chapter",
        course_id=pdf_course.id,
        source_document_id=pdf_source.id,
        stable_key="cnn-page-1",
        title="卷积层图示",
        position=1,
        char_start=0,
        char_end=len(pdf_document.content),
    )
    db.add(pdf_chapter)
    db.flush()
    pdf_ref = DBSourceRef(
        id="f7-t02-browser-pdf-ref",
        source_document_id=pdf_source.id,
        chapter_id=pdf_chapter.id,
        parser_version=pdf_source.parser_version,
        page_number=1,
        char_start=0,
        char_end=len(pdf_document.content),
        location_kind="page",
        location_index=1,
        location_label="第 1 页",
        content_hash=content_hash,
        quote=pdf_document.content,
    )
    membership = DBCourseMembership(
        course_id=pdf_course.id,
        user_public_id=user.public_id,
        role="student",
        status="active",
    )
    db.add_all([pdf_ref, membership])
    db.commit()
    payload = {{
        "course_id": {COURSE_ID!r},
        "source_id": source.id,
        "source_ref_id": source_ref.id,
        "source_title": source.title,
        "search_term": search_term,
        "pdf_course_id": pdf_course.id,
        "pdf_source_id": pdf_source.id,
        "initial_learning_event_count": db.execute(__import__("sqlalchemy").text("SELECT COUNT(*) FROM learning_events")).scalar_one(),
    }}
    Path({str(fixture_path)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=120)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def database_state(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        selection_note_event = db.execute(
            "SELECT le.event_type,le.evidence_status,le.mastery_eligible,le.completion_effect,"
            "le.source,le.object_type,le.action,le.payload FROM learning_events le "
            "JOIN notes n ON n.id=le.object_id "
            "WHERE n.source='knowledge_selection' AND le.event_type='note.created' "
            "ORDER BY le.occurred_at DESC,le.id DESC LIMIT 1"
        ).fetchone()
        return {
            "learning_event_count": db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
            "selection_count": db.execute("SELECT COUNT(*) FROM document_selections").fetchone()[0],
            "selection_note_count": db.execute(
                "SELECT COUNT(*) FROM notes WHERE source='knowledge_selection'"
            ).fetchone()[0],
            "reader_generation_count": db.execute(
                "SELECT COUNT(*) FROM generation_tasks WHERE capability='learning_resource_bundle.generate' "
                "AND idempotency_key LIKE 'f7-reader-%'"
            ).fetchone()[0],
            "selection_note_event": selection_note_event,
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def capture(page: Page, report: dict, filename: str) -> None:
    page.screenshot(path=OUTPUT_DIR / filename, full_page=True)
    report["screenshots"].append(filename)


def page_diagnostics(page: Page, report: dict) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.scheme not in {"blob", "data"} and parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(response.url)
        if response.status >= 400:
            report["http_errors"].append({"status": response.status, "url": response.url})

    page.on("response", on_response)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url,
        "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def visual_contract(page: Page) -> dict[str, object]:
    return page.evaluate("""
      () => {
        const root = document.querySelector('.reader-page')
        if (!root) return { missingRoot: true }
        const visible = element => {
          const style = getComputedStyle(element)
          const box = element.getBoundingClientRect()
          return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0
        }
        const textNodes = [...root.querySelectorAll(
          'button, h1, h2, h3, p, span, strong, label, summary, dt, dd, option'
        )].filter(element => visible(element) && element.textContent.trim())
        const smallText = textNodes
          .filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 13.9)
          .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 70), size: getComputedStyle(element).fontSize }))
        const clippedText = textNodes
          .filter(element => {
            const style = getComputedStyle(element)
            if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
            if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
            return element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1
          })
          .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 70) }))
        const decorativeBackgrounds = [...root.querySelectorAll('*')]
          .filter(visible)
          .map(element => getComputedStyle(element).backgroundImage)
          .filter(value => value && value !== 'none')
        const outline = root.querySelector('.reader-outline')?.getBoundingClientRect()
        const main = root.querySelector('.reader-main')?.getBoundingClientRect()
        const context = root.querySelector('.reader-context')?.getBoundingClientRect()
        const ordered = outline && main && context
          ? outline.right <= main.left + 1 && main.right <= context.left + 1
          : false
        const radii = [...root.querySelectorAll('button, .document-content, .page-frame, .selection-toolbar')]
          .filter(visible)
          .map(element => Number.parseFloat(getComputedStyle(element).borderRadius))
        return {
          missingRoot: false,
          pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 || root.scrollWidth > root.clientWidth + 1,
          ordered,
          centerIsLargest: Boolean(main && outline && context && main.width > outline.width && main.width > context.width),
          smallText,
          clippedText,
          decorativeBackgrounds,
          oversizedRadii: radii.filter(value => value > 8.1),
        }
      }
    """)


def assert_visual_contract(page: Page, report: dict, key: str) -> None:
    result = visual_contract(page)
    report["visual"][key] = result
    assert result["missingRoot"] is False, result
    assert result["pageOverflow"] is False, result
    assert result["ordered"] is True, result
    assert result["centerIsLargest"] is True, result
    assert result["smallText"] == [], result
    assert result["clippedText"] == [], result
    assert result["decorativeBackgrounds"] == [], result
    assert result["oversizedRadii"] == [], result


def open_reader(page: Page, base_url: str, source_id: str, course_id: str) -> None:
    page.goto(
        f"{base_url}/knowledge/documents/{source_id}?course_id={course_id}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.locator(".reader-page").wait_for(state="visible")
    page.get_by_text("正在打开原文", exact=True).wait_for(state="hidden")


def select_reader_text(page: Page) -> None:
    page.locator(".document-content").evaluate("""
      element => {
        const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT)
        let node = walker.nextNode()
        while (node && !node.textContent.trim()) node = walker.nextNode()
        if (!node) throw new Error('reader text node not found')
        const start = Math.max(0, node.textContent.search(/\S/))
        const end = Math.min(node.textContent.length, start + 72)
        const range = document.createRange()
        range.setStart(node, start)
        range.setEnd(node, end)
        const selection = window.getSelection()
        selection.removeAllRanges()
        selection.addRange(range)
        element.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, view: window }))
      }
    """)
    page.get_by_role("toolbar", name="文本选区操作").wait_for(state="visible")


def verify_text_reader(page: Page, base_url: str, fixture: dict, report: dict) -> None:
    open_reader(page, base_url, str(fixture["source_id"]), str(fixture["course_id"]))
    page.locator(".document-content").wait_for(state="visible")
    assert str(fixture["source_title"]) in page.locator(".reader-header").inner_text()
    reader_text = page.locator(".document-content").inner_text()
    assert "\\n>" not in reader_text
    assert "上游来源" in reader_text
    assert_visual_contract(page, report, "text_reader_initial_1440x900")
    capture(page, report, "01-text-reader-1440x900.png")

    page.get_by_label("在当前文档中搜索").fill(str(fixture["search_term"]))
    assert "无结果" not in page.locator(".reader-search").inner_text()
    page.get_by_title("下一个搜索结果").click()
    page.get_by_title("放大").click()
    page.wait_for_timeout(500)
    assert "110%" in page.locator(".zoom-control").inner_text()

    with page.expect_download() as download_info:
        page.get_by_role("button", name="导出解析文本", exact=True).click()
    assert "解析文本" in download_info.value.suggested_filename

    select_reader_text(page)
    capture(page, report, "02-text-selection-toolbar-1440x900.png")
    page.get_by_role("toolbar", name="文本选区操作").get_by_role("button", name="提问", exact=True).click()
    page.get_by_label("针对选区的问题").fill("这段原文的核心含义是什么？")
    page.get_by_role("button", name="提交问题", exact=True).click()
    page.get_by_text("基于选区的回答", exact=True).wait_for(state="visible")
    assert "仅依据你选中的原文" in page.locator(".answer-result").inner_text()
    assert_visual_contract(page, report, "text_answer_1440x900")
    capture(page, report, "03-source-bound-answer-1440x900.png")

    page.get_by_role("tab", name="笔记与生成", exact=True).click()
    page.get_by_label("选区笔记").fill("记录这段教材定义，并在复习时回到原文。")
    page.get_by_role("button", name="保存到笔记本", exact=True).click()
    page.get_by_text("已保存，文档位置与选区引用已归档。", exact=True).wait_for(state="visible")

    scope = page.locator(".scope-switch")
    scope.get_by_role("button", name="当前文件", exact=True).click()
    page.get_by_role("button", name="生成并归档", exact=True).click()
    page.get_by_text("任务已进入资源中心", exact=True).wait_for(state="visible")
    page.get_by_label("资源类型").select_option("mind_map")
    scope.get_by_role("button", name="当前选区", exact=True).click()
    page.get_by_role("button", name="生成并归档", exact=True).click()
    page.get_by_text("任务已进入资源中心", exact=True).wait_for(state="visible")
    capture(page, report, "04-note-and-generation-1440x900.png")

    page.reload(wait_until="networkidle")
    page.locator(".reader-page").wait_for(state="visible")
    page.get_by_text("已恢复上次位置", exact=True).wait_for(state="visible")
    assert "110%" in page.locator(".zoom-control").inner_text()
    assert page.get_by_label("针对选区的问题").input_value() == "这段原文的核心含义是什么？"
    capture(page, report, "05-refresh-restored-1440x900.png")


def verify_image_reader(page: Page, base_url: str, fixture: dict, report: dict) -> None:
    open_reader(page, base_url, str(fixture["pdf_source_id"]), str(fixture["pdf_course_id"]))
    layer = page.locator(".image-selection-layer")
    layer.wait_for(state="visible")
    assert_visual_contract(page, report, "image_reader_1440x900")
    capture(page, report, "06-image-reader-1440x900.png")

    box = layer.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + box["width"] * 0.68, box["y"] + box["height"] * 0.68)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.9, box["y"] + box["height"] * 0.9, steps=8)
    page.mouse.up()
    page.get_by_role("toolbar", name="图片选区操作").wait_for(state="visible")
    page.get_by_role("toolbar", name="图片选区操作").get_by_role("button", name="提问", exact=True).click()
    page.get_by_label("针对选区的问题").fill("这块图片区域说明了什么？")
    page.get_by_role("button", name="提交问题", exact=True).click()
    page.get_by_text("图片区域已保留", exact=True).wait_for(state="visible")
    assert page.locator(".image-selection-rect").is_visible()
    capture(page, report, "07-image-ocr-failure-preserved-1440x900.png")

    page.reload(wait_until="networkidle")
    page.locator(".image-selection-layer").wait_for(state="visible")
    page.locator(".image-selection-rect").wait_for(state="visible")
    assert page.get_by_label("针对选区的问题").input_value() == "这块图片区域说明了什么？"
    page.get_by_role("button", name="重试 OCR", exact=True).click()
    page.get_by_text("图片区域已保留", exact=True).wait_for(state="visible")
    capture(page, report, "08-image-selection-restored-1440x900.png")


def verify_secondary_viewport(page: Page, base_url: str, fixture: dict, report: dict) -> None:
    open_reader(page, base_url, str(fixture["source_id"]), str(fixture["course_id"]))
    page.locator(".document-content").wait_for(state="visible")
    assert_visual_contract(page, report, "text_reader_1366x768")
    capture(page, report, "09-text-reader-1366x768.png")
    page.get_by_role("tab", name="来源", exact=True).click()
    page.get_by_role("button", name="定位当前选区", exact=True).click()
    capture(page, report, "10-source-location-1366x768.png")


def run() -> dict:
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = 8998
    base.COURSE_ID = COURSE_ID
    base.clear_output()
    db_path = OUTPUT_DIR / "f7_t02.sqlite3"
    port = base.free_port()
    env = base.runtime_env(db_path, port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "f7-t02-isolated-secret"
    env["EDUMATRIX_SANDBOX_MODE"] = "disabled"
    env["EDUMATRIX_UPLOAD_DIR"] = str(OUTPUT_DIR / "uploads")
    fixture = seed_fixture(env)
    process: subprocess.Popen | None = None
    report = {
        "schema_version": "f7-t02.document-reader-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "visual": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "external_model_called": False,
    }
    try:
        process = base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN", accept_downloads=True)
            page = context.new_page()
            page_diagnostics(page, report)
            base.login(page, base_url)
            verify_text_reader(page, base_url, fixture, report)
            verify_image_reader(page, base_url, fixture, report)
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            base.login(page, base_url)
            verify_secondary_viewport(page, base_url, fixture, report)
            context.close()
            browser.close()

        report["database"] = database_state(db_path)
        assert report["database"]["learning_event_count"] == fixture["initial_learning_event_count"] + 1
        assert report["database"]["selection_count"] >= 2
        assert report["database"]["selection_note_count"] == 1
        assert report["database"]["reader_generation_count"] == 2
        selection_note_event = report["database"]["selection_note_event"]
        assert selection_note_event is not None
        assert selection_note_event[:7] == (
            "note.created", "none", 0, "none", "note_workspace", "note", "created",
        )
        selection_note_payload = json.loads(selection_note_event[7] or "{}")
        assert selection_note_payload.get("source_type") == "knowledge_selection"
        assert selection_note_payload.get("mastery_updated") is False
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
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT_DIR.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT_DIR / "manifest.json").write_text(
            json.dumps(
                {"schema_version": "f7-t02.evidence-manifest.v1", "files": files},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
