"""F8-T03 isolated dual-desktop source-bound notes acceptance."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import e2e_f8_t01_review_calendar as browser_base  # noqa: E402


OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f8_t03_notes"
BROWSER_DIR = OUTPUT_DIR / "browser"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "f8_t03_runtime.sqlite3"
REPORT_PATH = OUTPUT_DIR / "report.json"
USERNAME = "lzz"
PASSWORD = "404404aA"
COURSE_ID = "demo-course-rag-trust-v1"
PORT_START = int(os.getenv("EDUMATRIX_F8_T03_PORT", "9100"))


def configure_browser_base() -> None:
    browser_base.OUTPUT_DIR = OUTPUT_DIR
    browser_base.BROWSER_DIR = BROWSER_DIR
    browser_base.RUNTIME_DIR = RUNTIME_DIR
    browser_base.DB_PATH = DB_PATH
    browser_base.REPORT_PATH = REPORT_PATH
    browser_base.USERNAME = USERNAME
    browser_base.PASSWORD = PASSWORD
    browser_base.COURSE_ID = COURSE_ID
    browser_base.PORT_START = PORT_START


def runtime_env(port: int) -> dict[str, str]:
    env = browser_base.runtime_env(port)
    env.update({
        "EDUMATRIX_AUTH_SECRET_KEY": "f8-t03-isolated-secret",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_UPLOAD_DIR": str(RUNTIME_DIR / "uploads"),
    })
    return env


def seed_fixture(
    env: dict[str, str],
    *,
    base_fixture: dict[str, object] | None = None,
) -> dict[str, object]:
    fixture = dict(base_fixture) if base_fixture is not None else browser_base.seed_fixture(env)
    os.environ.update(env)

    from PIL import Image, ImageDraw

    from app.database import (
        DBArtifact,
        DBArtifactVersion,
        DBChapter,
        DBChapterKnowledgePoint,
        DBCourse,
        DBCourseMembership,
        DBKnowledgeDocument,
        DBKnowledgePoint,
        DBProfileSnapshot,
        DBReviewPlan,
        DBSourceDocument,
        DBSourceRef,
        DBUser,
        SessionLocal,
    )
    from app.note_workspace import create_note_record, prepare_source_metadata
    from app.resource_bundles import create_generation_job, execute_generation_job_demo

    db = SessionLocal()
    try:
        learner = db.query(DBUser).filter_by(username=USERNAME).one()
        profile = db.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
        source_ref = db.get(DBSourceRef, "demo-ref-07")
        point = (
            db.query(DBKnowledgePoint)
            .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.knowledge_point_id == DBKnowledgePoint.id)
            .join(DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id)
            .filter(DBChapter.course_id == COURSE_ID)
            .order_by(DBKnowledgePoint.title, DBKnowledgePoint.id)
            .first()
        )
        if profile is None or source_ref is None or point is None:
            raise RuntimeError("F8-T03 fixture requires the frozen profile, source and knowledge point")

        resources = {}
        resource_specs = {
            "handout": ("梯度下降来源讲义", "阅读来源讲义并记录个人理解。"),
            "code_sandbox": ("梯度下降代码实训", "保存代码版本并完成一次真实运行。"),
        }
        for resource_type, (title, completion_rule) in resource_specs.items():
            generation = create_generation_job(
                db,
                learner,
                course_id=COURSE_ID,
                knowledge_point_id=point.id,
                profile_snapshot_id=profile.id,
                idempotency_key=f"f8-t03-source-{resource_type}-fixture",
                scope="single",
                items=[{
                    "type": resource_type,
                    "title": title,
                    "source_ref_ids": [source_ref.id],
                    "completion_rule": completion_rule,
                }],
                learning_goal="把来源阅读、代码实训和个人笔记连接为可追溯学习记录",
            )
            db.commit()
            generated = execute_generation_job_demo(db, learner, generation["job_id"])
            db.commit()
            resources[resource_type] = generated["items"][0]["resource"]

        pdf_course = DBCourse(
            id="f8-t03-pdf-course",
            version="1",
            title="视觉选区笔记演示",
            visibility="private",
            status="draft",
            owner_public_id=learner.public_id,
            manifest_version="f8-t03-browser-v1",
            content_origin="isolated_e2e_fixture",
            license_text="仅用于隔离验收",
        )
        pdf_document = DBKnowledgeDocument(
            id="f8-t03-pdf-document",
            student_id=USERNAME,
            filename="gradient-descent-diagram.pdf",
            file_type="pdf",
            title="梯度下降视觉讲义",
            content="梯度方向指向目标函数局部上升最快方向，参数更新使用负梯度方向。",
        )
        content_hash = hashlib.sha256(pdf_document.content.encode("utf-8")).hexdigest()
        asset_dir = Path(env["EDUMATRIX_UPLOAD_DIR"]) / USERNAME / pdf_document.id / "ocr"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_path = asset_dir / "page-1-redacted.png"
        image = Image.new("RGB", (1000, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.line((170, 160, 460, 420), fill=(17, 33, 45), width=8)
        draw.polygon(((445, 390), (485, 445), (420, 430)), fill=(17, 33, 45))
        draw.rectangle((120, 100, 560, 500), outline=(74, 92, 106), width=4)
        draw.text((140, 540), "Gradient direction and parameter update", fill=(17, 33, 45))
        image.save(asset_path, format="PNG")
        asset_hash = hashlib.sha256(asset_path.read_bytes()).hexdigest()
        pdf_source = DBSourceDocument(
            id="f8-t03-pdf-source",
            course_id=pdf_course.id,
            legacy_document_id=pdf_document.id,
            title=pdf_document.title,
            filename=pdf_document.filename,
            file_format="pdf",
            content_hash=content_hash,
            source_sha256=asset_hash,
            processed_sha256=content_hash,
            source_path="isolated-browser-fixture/gradient-descent-diagram.pdf",
            uploader_public_id=learner.public_id,
            parser_version="f8-t03-browser-parser-v1",
            parser_metadata={
                "ocr": {
                    "status": "ready",
                    "page_count": 1,
                    "region_count": 1,
                    "sensitive_region_count": 0,
                    "pages": [{
                        "page_number": 1,
                        "width_px": 1000,
                        "height_px": 800,
                        "asset_name": asset_path.name,
                        "redacted_image_sha256": asset_hash,
                        "regions": [{
                            "region_id": "gradient-diagram",
                            "bbox": {"x": 0.12, "y": 0.1, "width": 0.44, "height": 0.52},
                            "content": {"text": "梯度方向与参数更新方向相反"},
                            "privacy": {"sensitive": False},
                        }],
                    }],
                },
            },
            processing_status="ready",
            license_text="仅用于隔离验收",
        )
        db.add_all([pdf_course, pdf_document, pdf_source])
        db.flush()
        pdf_chapter = DBChapter(
            id="f8-t03-pdf-chapter",
            course_id=pdf_course.id,
            source_document_id=pdf_source.id,
            stable_key="gradient-page-1",
            title="梯度方向图示",
            position=1,
            char_start=0,
            char_end=len(pdf_document.content),
        )
        db.add(pdf_chapter)
        db.flush()
        pdf_ref = DBSourceRef(
            id="f8-t03-pdf-ref",
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
            user_public_id=learner.public_id,
            role="student",
            status="active",
        )
        db.add_all([pdf_ref, membership])

        manual_note, _ = create_note_record(
            db,
            student_id=USERNAME,
            source="manual",
            content="# 梯度下降版本实验\n\n这是用户保存的初始正文。",
            tags=["版本实验"],
            concepts=["梯度下降"],
            idempotency_key="f8-t03-manual-note",
            actor=learner,
        )

        withdrawn_artifact = DBArtifact(
            id="f8-t03-withdrawn-handout",
            owner_public_id=learner.public_id,
            course_id=COURSE_ID,
            artifact_type="handout",
            title="已撤回来源讲义",
            status="published",
        )
        db.add(withdrawn_artifact)
        db.flush()
        withdrawn_version = DBArtifactVersion(
            id="f8-t03-withdrawn-handout-v1",
            artifact_id=withdrawn_artifact.id,
            version_number=1,
            content="# 已撤回来源\n\n历史内容只用于来源快照验收。",
            content_format="markdown",
            content_hash="a" * 64,
            metadata_json={"resource_type": "handout", "knowledge_point_id": point.id},
            created_by_public_id=learner.public_id,
        )
        db.add(withdrawn_version)
        db.flush()
        withdrawn_artifact.current_version_id = withdrawn_version.id
        source_type, source_metadata = prepare_source_metadata(
            db,
            actor=learner,
            source_type="handout",
            metadata={
                "resource_id": withdrawn_artifact.id,
                "resource_version_id": withdrawn_version.id,
            },
        )
        withdrawn_note, _ = create_note_record(
            db,
            student_id=USERNAME,
            source=source_type,
            content="# 已撤回来源讲义\n\n来源撤回后仍保留我的正文和历史引用。",
            tags=["来源状态"],
            concepts=[point.title],
            source_metadata=source_metadata,
            idempotency_key="f8-t03-withdrawn-note",
            actor=learner,
        )
        withdrawn_artifact.archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
        review_plan = db.query(DBReviewPlan).filter_by(student_id=USERNAME).order_by(DBReviewPlan.id).first()
        if review_plan is None:
            raise RuntimeError("F8-T03 fixture requires one review plan")
        db.commit()

        fixture.update({
            "knowledge_point_id": point.id,
            "knowledge_point_title": point.title,
            "handout_resource_id": resources["handout"]["resource_id"],
            "sandbox_resource_id": resources["code_sandbox"]["resource_id"],
            "pdf_course_id": pdf_course.id,
            "pdf_source_id": pdf_source.id,
            "pdf_source_ref_id": pdf_ref.id,
            "pdf_document_version": content_hash,
            "manual_note_id": manual_note.id,
            "withdrawn_note_id": withdrawn_note.id,
            "review_plan_id": review_plan.id,
        })
        return fixture
    finally:
        db.close()


def parse_json(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def database_state(fixture: dict[str, object]) -> dict[str, object]:
    owner = str(fixture["owner_public_id"])
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        profile_row = db.execute(
            "SELECT concept_mastery FROM student_profiles WHERE student_id=?", (USERNAME,)
        ).fetchone()
        knowledge_note = db.execute(
            "SELECT id, source_metadata, lock_version, content FROM notes "
            "WHERE student_id=? AND source='knowledge_selection' ORDER BY created_at DESC LIMIT 1",
            (USERNAME,),
        ).fetchone()
        return {
            "learning_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=?", (owner,)
            ).fetchone()[0],
            "mastery_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=? AND mastery_eligible=1",
                (owner,),
            ).fetchone()[0],
            "profile_snapshots": db.execute(
                "SELECT COUNT(*) FROM profile_snapshots WHERE owner_public_id=?", (owner,)
            ).fetchone()[0],
            "profile_mastery": parse_json(profile_row[0]) if profile_row else None,
            "path_states": db.execute(
                "SELECT id, status FROM path_nodes WHERE learning_path_id IN "
                "(SELECT id FROM learning_paths WHERE owner_public_id=?) ORDER BY id",
                (owner,),
            ).fetchall(),
            "review_states": db.execute(
                "SELECT id, review_count, next_review_at FROM review_plans "
                "WHERE student_id=? ORDER BY id", (USERNAME,),
            ).fetchall(),
            "notes": db.execute(
                "SELECT COUNT(*) FROM notes WHERE student_id=?", (USERNAME,)
            ).fetchone()[0],
            "note_versions": db.execute(
                "SELECT COUNT(*) FROM note_versions WHERE note_id IN "
                "(SELECT id FROM notes WHERE student_id=?)", (USERNAME,),
            ).fetchone()[0],
            "knowledge_note": {
                "id": knowledge_note[0],
                "source_metadata": parse_json(knowledge_note[1]),
                "lock_version": knowledge_note[2],
                "content": knowledge_note[3],
            } if knowledge_note else None,
            "manual_note": db.execute(
                "SELECT lock_version, content, ai_suggestion FROM notes WHERE id=?",
                (fixture["manual_note_id"],),
            ).fetchone(),
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


READ_ONLY_KEYS = (
    "mastery_events",
    "profile_snapshots",
    "profile_mastery",
    "path_states",
    "review_states",
)


def assert_read_only_browsing(before: dict[str, object], after: dict[str, object]) -> None:
    for key in READ_ONLY_KEYS:
        assert after[key] == before[key], (key, before[key], after[key])


def attach_diagnostics(page: Page, report: dict[str, object]) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.scheme not in {"blob", "data"} and parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(response.url)
        if response.status < 400:
            return
        item = {"status": response.status, "url": response.url}
        if response.status == 409 and "/api/notes/update/" in response.url:
            report["expected_http_errors"].append(item)
        else:
            report["http_errors"].append(item)

    page.on("response", on_response)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url,
        "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))

    def on_console(message) -> None:
        if message.type != "error":
            return
        target = "expected_console_errors" if "409" in message.text else "console_errors"
        report[target].append(message.text)

    page.on("console", on_console)


def visual_metrics(page: Page) -> dict[str, object]:
    return page.evaluate("""
      () => {
        const root = document.querySelector('[data-testid="notes-workspace"]')
        if (!root) return { missingRoot: true }
        const visible = element => {
          const style = getComputedStyle(element), box = element.getBoundingClientRect()
          const closed = element.closest('details:not([open])')
          if (closed && !closed.querySelector(':scope > summary')?.contains(element)) return false
          return style.display !== 'none' && style.visibility !== 'hidden' &&
            Number(style.opacity) > 0 && box.width > 1 && box.height > 1
        }
        const textNodes = [...root.querySelectorAll('button,a,h1,h2,h3,p,span,strong,small,label,dt,dd,li,time')]
          .filter(element => visible(element) && (element.textContent || '').trim())
        const clipped = textNodes.filter(element => {
          const style = getComputedStyle(element)
          if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
          if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
          return element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 2
        }).map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 70) })).slice(0, 30)
        const smallText = textNodes.filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 13.9)
          .map(element => ({ text: element.textContent.trim().slice(0, 60), size: getComputedStyle(element).fontSize })).slice(0, 30)
        const controls = [...root.querySelectorAll('button,a[href],input,select,textarea,summary')].filter(visible)
        const collisions = []
        for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
          const left = controls[i], right = controls[j]
          if (left.contains(right) || right.contains(left)) continue
          const a = left.getBoundingClientRect(), b = right.getBoundingClientRect()
          const overlapWidth = Math.min(a.right, b.right) - Math.max(a.left, b.left)
          const overlapHeight = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
          if (overlapWidth > 3 && overlapHeight > 3) collisions.push([
            (left.textContent || left.getAttribute('aria-label') || '').trim().slice(0, 36),
            (right.textContent || right.getAttribute('aria-label') || '').trim().slice(0, 36),
          ])
        }
        const forbidden = new Set([
          'rgb(16, 185, 129)', 'rgb(34, 197, 94)', 'rgb(59, 130, 246)',
          'rgb(14, 165, 233)', 'rgb(139, 92, 246)', 'rgb(168, 85, 247)',
          'rgb(120, 53, 15)', 'rgb(146, 64, 14)',
        ])
        const forbiddenThemeHits = [...root.querySelectorAll('*')].filter(visible).flatMap(element => {
          const style = getComputedStyle(element)
          return [style.color, style.backgroundColor, style.borderColor]
            .filter(value => forbidden.has(value))
            .map(value => ({ value, text: element.textContent.trim().slice(0, 60) }))
        })
        const gradients = [...root.querySelectorAll('*')].filter(visible)
          .map(element => getComputedStyle(element).backgroundImage)
          .filter(value => value && value !== 'none' && value.includes('gradient'))
        const explorer = root.querySelector('[data-testid="notes-explorer"]')?.getBoundingClientRect()
        const documentPane = root.querySelector('[data-testid="notes-document"]')?.getBoundingClientRect()
        const context = root.querySelector('[data-testid="notes-context"]')?.getBoundingClientRect()
        return {
          missingRoot: false,
          viewport: [innerWidth, innerHeight],
          pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
          rootOverflow: root.scrollWidth > root.clientWidth + 1,
          clipped,
          smallText,
          collisions,
          forbiddenThemeHits,
          gradients,
          primaryActions: [...root.querySelectorAll('.button.primary')].filter(visible).length,
          layout: explorer && documentPane && context ? {
            explorerWidth: explorer.width,
            documentWidth: documentPane.width,
            contextWidth: context.width,
            leftOverlap: Math.max(0, explorer.right - documentPane.left),
            rightOverlap: Math.max(0, documentPane.right - context.left),
          } : null,
        }
      }
    """)


def assert_visual(page: Page, report: dict[str, object], key: str) -> None:
    metrics = visual_metrics(page)
    report["visual"][key] = metrics
    assert metrics["missingRoot"] is False, metrics
    assert metrics["pageOverflow"] is False, metrics
    assert metrics["rootOverflow"] is False, metrics
    assert metrics["clipped"] == [], metrics
    assert metrics["smallText"] == [], metrics
    assert metrics["collisions"] == [], metrics
    assert metrics["forbiddenThemeHits"] == [], metrics
    assert metrics["gradients"] == [], metrics
    assert metrics["primaryActions"] <= 1, metrics
    assert metrics["layout"] is not None, metrics
    assert 220 <= metrics["layout"]["explorerWidth"] <= 270, metrics
    assert 270 <= metrics["layout"]["contextWidth"] <= 310, metrics
    assert metrics["layout"]["documentWidth"] > metrics["layout"]["explorerWidth"], metrics
    assert metrics["layout"]["leftOverlap"] == 0, metrics
    assert metrics["layout"]["rightOverlap"] == 0, metrics


def capture(page: Page, report: dict[str, object], name: str) -> None:
    browser_base.capture(page, report, name)


def notes_url(base_url: str, note_id: object | None = None) -> str:
    suffix = f"?note_id={note_id}" if note_id else ""
    return f"{base_url}/workspace/notes{suffix}"


def wait_for_notes(page: Page) -> None:
    page.get_by_test_id("notes-workspace").wait_for(state="visible")
    page.get_by_text("正在准备笔记", exact=True).wait_for(state="hidden")


def select_note_by_title(page: Page, title: str) -> None:
    item = page.locator(".note-list-item").filter(has_text=title)
    assert item.count() == 1, title
    previous_url = page.url
    item.click()
    page.wait_for_function("previousUrl => location.href !== previousUrl", arg=previous_url)
    page.wait_for_function(
        "() => !document.querySelector('.page-fade-enter-active, .page-fade-leave-active')"
    )
    wait_for_notes(page)
    page.get_by_test_id("notes-document").get_by_role("heading", name=title, exact=True).wait_for()


def create_selection_note(
    page: Page,
    base_url: str,
    fixture: dict[str, object],
    report: dict[str, object],
) -> None:
    page.goto(
        f"{base_url}/knowledge/documents/{fixture['pdf_source_id']}?course_id={fixture['pdf_course_id']}",
        wait_until="networkidle",
        timeout=60_000,
    )
    layer = page.locator(".image-selection-layer")
    layer.wait_for(state="visible")
    box = layer.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + box["width"] * 0.18, box["y"] + box["height"] * 0.16)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.52, box["y"] + box["height"] * 0.56, steps=10)
    page.mouse.up()
    page.get_by_role("toolbar", name="图片选区操作").wait_for(state="visible")
    page.get_by_role("tab", name="笔记与生成", exact=True).click()
    page.get_by_label("选区笔记").fill("# 梯度方向图示\n\n图片区域说明参数应沿负梯度方向更新。")
    page.get_by_role("button", name="保存到笔记本", exact=True).click()
    page.get_by_text("已保存，文档位置与选区引用已归档。", exact=True).wait_for(state="visible")
    page.get_by_role("button", name="进入笔记本", exact=True).click()
    wait_for_notes(page)
    source = page.get_by_test_id("notes-source")
    source.get_by_text("引用标识", exact=True).wait_for(state="visible", timeout=10_000)
    source_text = source.inner_text()
    report["selection_source_text"] = source_text
    for label in ("页码", "图片区域", "文档版本", "选区标识", "引用标识"):
        assert label in source_text, (label, source_text)
    assert str(fixture["pdf_source_ref_id"]) in source_text, source_text
    assert_visual(page, report, "selection_source_1440x900")
    capture(page, report, "01-selection-source-1440x900.png")
    source.get_by_role("button", name="返回来源", exact=True).click()
    page.locator(".reader-page").wait_for(state="visible")
    assert str(fixture["pdf_source_id"]) in page.url
    page.go_back(wait_until="networkidle")
    wait_for_notes(page)


def create_resource_note(
    page: Page,
    base_url: str,
    fixture: dict[str, object],
    *,
    resource_type: str,
) -> None:
    if resource_type == "handout":
        resource_id = fixture["handout_resource_id"]
        page.goto(
            f"{base_url}/workspace/resources/handouts/{resource_id}?course_id={COURSE_ID}",
            wait_until="networkidle",
            timeout=60_000,
        )
        page.get_by_test_id("handout-workspace").wait_for(state="visible")
        page.get_by_test_id("resource-toolbar").get_by_role("button", name="记笔记", exact=True).click()
        expected_source = "个性化讲义"
        expected_title = "梯度下降来源讲义"
    else:
        resource_id = fixture["sandbox_resource_id"]
        page.goto(
            f"{base_url}/workspace/code/{resource_id}?course_id={COURSE_ID}",
            wait_until="networkidle",
            timeout=60_000,
        )
        page.get_by_test_id("code-sandbox-workspace").wait_for(state="visible")
        page.get_by_role("button", name="保存当前代码版本的来源笔记", exact=True).click()
        expected_source = "代码沙盒"
        expected_title = "梯度下降代码实训"
    wait_for_notes(page)
    source = page.get_by_test_id("notes-source")
    assert page.locator(".note-list-item.is-active .source-label").inner_text() == expected_source
    assert source.get_by_text(expected_title, exact=True).count() == 1
    assert source.get_by_text("资源版本", exact=True).count() == 1


def create_review_note(page: Page, base_url: str, fixture: dict[str, object]) -> None:
    page.goto(
        f"{base_url}/workspace/review?course_id={COURSE_ID}&review_task=review-plan:{fixture['review_plan_id']}",
        wait_until="networkidle",
        timeout=60_000,
    )
    board = page.get_by_test_id("review-schedule-board")
    board.wait_for(state="visible")
    note_button = board.get_by_role("button", name="记笔记", exact=True).first
    note_button.wait_for(state="visible")
    note_button.click()
    wait_for_notes(page)
    source = page.get_by_test_id("notes-source")
    assert source.get_by_text("复习任务", exact=False).count() >= 1


def fetch_note(page: Page, note_id: str) -> dict[str, object]:
    return page.evaluate(
        """async ({ noteId, studentId }) => {
          const token = localStorage.getItem('edumatrix_token')
          const response = await fetch(`/api/notes/${encodeURIComponent(studentId)}`, {
            headers: { Authorization: `Bearer ${token}` },
          })
          if (!response.ok) throw new Error(`note fetch failed: ${response.status}`)
          const payload = await response.json()
          return (payload.notes || payload).find(note => note.id === noteId)
        }""",
        {"noteId": note_id, "studentId": USERNAME},
    )


def external_update(page: Page, note: dict[str, object]) -> dict[str, object]:
    return page.evaluate(
        """async ({ note, studentId }) => {
          const token = localStorage.getItem('edumatrix_token')
          const response = await fetch(`/api/notes/update/${note.id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({
              student_id: studentId,
              content: `${note.content}\n\n来自并发标签页的更新。`,
              tags: note.tags,
              concepts: note.concepts,
              expected_version: note.lock_version,
              idempotency_key: 'f8-t03-external-update',
              change_type: 'saved',
            }),
          })
          const body = await response.json()
          return { status: response.status, body }
        }""",
        {"note": note, "studentId": USERNAME},
    )


def exercise_note_workspace(
    page: Page,
    base_url: str,
    fixture: dict[str, object],
    report: dict[str, object],
) -> None:
    page.goto(notes_url(base_url, fixture["withdrawn_note_id"]), wait_until="networkidle", timeout=60_000)
    wait_for_notes(page)
    source = page.get_by_test_id("notes-source")
    source.get_by_text("当前不可用", exact=True).wait_for(state="visible")
    assert source.get_by_role("button", name="返回来源", exact=True).is_disabled()
    capture(page, report, "02-withdrawn-source-1440x900.png")

    before_browse = database_state(fixture)
    search = page.get_by_placeholder("搜索正文、概念或标签")
    search.fill("梯度下降")
    assert page.locator(".note-list-item").count() >= 1
    search.fill("")
    page.get_by_role("navigation", name="按来源筛选").get_by_role("button", name="文档选区", exact=False).click()
    assert page.locator(".note-list-item").count() >= 1
    page.get_by_text("清除筛选", exact=True).click()

    select_note_by_title(page, "梯度下降版本实验")
    history = page.get_by_test_id("notes-history")
    history.get_by_text("版本 1", exact=True).wait_for(state="visible")
    learning = page.get_by_test_id("notes-learning-actions")
    learning.locator("summary").click()
    learning.get_by_role("button", name="生成对话内练习", exact=True).wait_for(state="visible")
    learning.get_by_role("button", name="开始闪卡复习", exact=True).click()
    flashcard_dialog = page.locator(".flashcard-modal")
    flashcard_dialog.wait_for(state="visible")
    assert flashcard_dialog.get_attribute("role") == "dialog"
    assert flashcard_dialog.get_attribute("aria-labelledby") == "flashcard-title"
    assert flashcard_dialog.locator("#flashcard-title").inner_text().strip() == "闪卡复习"
    page.get_by_role("button", name="关闭闪卡复习", exact=True).click()

    toolbar = page.locator(".toolbar-menu")
    toolbar.locator("summary").click()
    with page.expect_download() as markdown_download:
        toolbar.get_by_role("button", name="导出 Markdown", exact=True).click()
    assert markdown_download.value.suggested_filename.endswith(".md")
    if not toolbar.get_by_role("button", name="导出 PDF", exact=True).is_visible():
        toolbar.locator("summary").click()
    with page.expect_download() as pdf_download:
        toolbar.get_by_role("button", name="导出 PDF", exact=True).click()
    assert pdf_download.value.suggested_filename.endswith(".pdf")
    after_browse = database_state(fixture)
    assert_read_only_browsing(before_browse, after_browse)
    report["database"]["read_only_before"] = before_browse
    report["database"]["read_only_after"] = after_browse

    page.get_by_role("button", name="编辑", exact=True).click()
    editor = page.get_by_role("textbox", name="笔记正文", exact=True)
    draft_text = "# 梯度下降版本实验\n\n这是刷新后必须恢复的本地草稿。"
    editor.fill(draft_text)
    page.reload(wait_until="networkidle")
    wait_for_notes(page)
    assert page.get_by_role("textbox", name="笔记正文", exact=True).input_value() == draft_text
    stale_note = fetch_note(page, str(fixture["manual_note_id"]))
    update = external_update(page, stale_note)
    assert update["status"] == 200, update
    conflict_expectation = report.get("diagnostic_expectations", {}).get("note_conflict")
    if isinstance(conflict_expectation, dict):
        conflict_expectation.update({
            "active": True,
            "operation": "save_stale_note_version",
            "status": 409,
            "url": f"{base_url}/api/notes/update/{fixture['manual_note_id']}",
            "response_seen": False,
        })
    try:
        page.get_by_role("button", name="保存新版本", exact=True).click()
        conflict = page.get_by_test_id("notes-conflict")
        conflict.wait_for(state="visible")
        assert page.get_by_role("textbox", name="笔记正文", exact=True).input_value() == draft_text
        assert_visual(page, report, "conflict_preserves_draft_1440x900")
        capture(page, report, "03-conflict-preserves-draft-1440x900.png")
    finally:
        if isinstance(conflict_expectation, dict):
            conflict_expectation["active"] = False
    conflict.get_by_role("button", name="同步最新版本", exact=True).click()
    conflict.wait_for(state="hidden")
    assert page.get_by_role("textbox", name="笔记正文", exact=True).input_value() == draft_text
    page.get_by_role("button", name="保存新版本", exact=True).click()
    page.get_by_text("已保存为版本", exact=False).wait_for(state="visible")

    ai = page.get_by_test_id("notes-ai-suggestion")
    ai.get_by_role("button", name="生成排版建议", exact=True).click()
    ai.get_by_role("button", name="应用并另存新版本", exact=True).wait_for(
        state="visible", timeout=60_000
    )
    saved_before_apply = fetch_note(page, str(fixture["manual_note_id"]))
    assert saved_before_apply["ai_suggestion"]
    assert saved_before_apply["content"] == draft_text
    capture(page, report, "04-ai-suggestion-separated-1440x900.png")
    ai.get_by_role("button", name="应用并另存新版本", exact=True).click()
    page.get_by_text("AI 建议已作为版本", exact=False).wait_for(state="visible")

    version_one = page.get_by_test_id("notes-history").locator(".version-row").filter(has_text="版本 1")
    page.once("dialog", lambda dialog: dialog.accept())
    version_one.get_by_role("button", name="将版本 1 另存为新版本", exact=True).click()
    page.get_by_text("版本 1 已另存为版本", exact=False).wait_for(state="visible")
    final_manual = fetch_note(page, str(fixture["manual_note_id"]))
    assert final_manual["lock_version"] > saved_before_apply["lock_version"]
    assert final_manual["content"].startswith("# 梯度下降版本实验")
    assert_visual(page, report, "version_restore_complete_1440x900")
    capture(page, report, "05-version-restore-complete-1440x900.png")
    report["checks"].update({
        "withdrawn_source_honest": True,
        "search_tags_concepts_reachable": True,
        "markdown_pdf_flashcard_review_reachable": True,
        "ordinary_browsing_zero_mastery_writes": True,
        "local_draft_survived_refresh": True,
        "conflict_preserved_local_draft": True,
        "ai_suggestion_separate_until_applied": True,
        "historical_restore_created_new_version": True,
    })


def run_primary(
    page: Page,
    base_url: str,
    fixture: dict[str, object],
    report: dict[str, object],
) -> None:
    create_selection_note(page, base_url, fixture, report)
    create_resource_note(page, base_url, fixture, resource_type="handout")
    capture(page, report, "06-handout-source-note-1440x900.png")
    create_resource_note(page, base_url, fixture, resource_type="code_sandbox")
    capture(page, report, "07-sandbox-source-note-1440x900.png")
    create_review_note(page, base_url, fixture)
    capture(page, report, "08-review-source-note-1440x900.png")
    exercise_note_workspace(page, base_url, fixture, report)
    state = database_state(fixture)
    metadata = state["knowledge_note"]["source_metadata"]
    assert metadata["source_ref_id"] == fixture["pdf_source_ref_id"], metadata
    assert metadata["document_version"] == fixture["pdf_document_version"], metadata
    assert metadata["page_number"] == 1, metadata
    assert metadata["selection_id"], metadata
    assert metadata["normalized_rect"], metadata
    report["checks"].update({
        "selection_note_exact_source_identity": True,
        "handout_source_note": True,
        "sandbox_version_source_note": True,
        "review_task_source_note": True,
    })


def run_secondary(
    page: Page,
    base_url: str,
    fixture: dict[str, object],
    report: dict[str, object],
) -> None:
    before = database_state(fixture)
    page.goto(notes_url(base_url, fixture["manual_note_id"]), wait_until="networkidle", timeout=60_000)
    wait_for_notes(page)
    page.get_by_test_id("notes-history").locator("summary").click()
    page.get_by_test_id("notes-ai-suggestion").locator("summary").click()
    page.get_by_test_id("notes-learning-actions").locator("summary").click()
    assert_visual(page, report, "stable_workspace_1366x768")
    capture(page, report, "09-stable-workspace-1366x768.png")
    after = database_state(fixture)
    assert_read_only_browsing(before, after)
    report["database"]["secondary_read_only_before"] = before
    report["database"]["secondary_read_only_after"] = after


def run() -> dict[str, object]:
    configure_browser_base()
    browser_base.reset_output()
    port = browser_base.free_port()
    env = runtime_env(port)
    fixture = seed_fixture(env)
    base_url = f"http://127.0.0.1:{port}"
    report: dict[str, object] = {
        "schema_version": "f8-t03.source-bound-notes-desktop.v1",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "viewports": [[1440, 900], [1366, 768]],
        "isolated_database": str(DB_PATH),
        "single_service": True,
        "single_chromium_instance": True,
        "deterministic_model_only": True,
        "external_model_called": False,
        "fixture": fixture,
        "screenshots": [],
        "checks": {},
        "visual": {},
        "database": {"initial": database_state(fixture)},
        "expected_http_errors": [],
        "expected_console_errors": [],
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
    }
    process = None
    try:
        process = browser_base.start_service(env, port)
        with sync_playwright() as playwright:
            browser: Browser = playwright.chromium.launch(headless=True)
            try:
                primary_context = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                    accept_downloads=True,
                )
                primary = primary_context.new_page()
                attach_diagnostics(primary, report)
                browser_base.login(primary, base_url)
                run_primary(primary, base_url, fixture, report)
                primary_context.close()

                secondary_context = browser.new_context(
                    viewport={"width": 1366, "height": 768},
                    locale="zh-CN",
                )
                secondary = secondary_context.new_page()
                attach_diagnostics(secondary, report)
                browser_base.login(secondary, base_url)
                run_secondary(secondary, base_url, fixture, report)
                secondary_context.close()
            finally:
                browser.close()
        final_state = database_state(fixture)
        report["database"]["final"] = final_state
        assert final_state["integrity"] == "ok", final_state
        assert final_state["foreign_key_violations"] == 0, final_state
        assert len(report["expected_http_errors"]) == 1, report["expected_http_errors"]
        assert len(report["expected_console_errors"]) <= 1, report["expected_console_errors"]
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["external_requests"], report["external_requests"]
        report["status"] = "passed"
        return report
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        browser_base.stop_service(process, port)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result["status"],
        "screenshots": len(result["screenshots"]),
        "checks": result["checks"],
        "database": result["database"],
    }, ensure_ascii=False, indent=2))
