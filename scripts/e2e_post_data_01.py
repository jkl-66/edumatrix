"""POST-DATA-01 complete-course and lzz browser evidence on isolated SQLite."""

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
    / "post_data_fixes"
    / "browser"
)
COURSE_ID = "course-embedded-machine-learning-engineering-v2"
COURSE_TITLE = "嵌入式机器学习与边缘智能工程实践"
CONVERSATION_ID = "postdata-chat-lzz-eml-deployment"
EXAM_ID = "postdata-exam-lzz-eml-v1"
PERSONAL_COURSE_TITLE = "边缘智能现场调试个人课程"
PERSONAL_UPLOAD_FILE = (
    ROOT
    / "data"
    / "curated"
    / "embedded_machine_learning_engineering_v2"
    / "materials"
    / "module-07"
    / "7.1.5.digging-deeper-into-object-detection.2.docx"
)

RESOURCE_ROUTES = {
    "handout": ("/workspace/resources/handouts/{id}", "[data-testid='handout-workspace']"),
    "mind_map": ("/workspace/resources/mindmaps/{id}", "[data-testid='mindmap-workspace']"),
    "quiz": ("/workspace/resources/quizzes/{id}", "[data-testid='quiz-resource-workspace']"),
    "training_task": ("/workspace/resources/training-tasks/{id}", "[data-testid='training-task-workspace']"),
    "code_sandbox": ("/workspace/code/{id}", "[data-testid='code-sandbox-workspace']"),
    "video": ("/workspace/resources/videos/{id}", "[data-testid='video-recommendation-workspace']"),
    "deck": ("/workspace/resources/decks/{id}", "[data-testid='web-deck-workspace']"),
    "interactive_model": ("/workspace/resources/models/{id}", "[data-testid='interactive-lab-workspace']"),
    "feynman": ("/workspace/feynman/{id}", ".feynman-page"),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def seed_fixture(env: dict[str, str]) -> dict[str, object]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import json
from pathlib import Path
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBArtifact, DBChapter, DBChatConversation, DBCourse, DBCourseMembership,
    DBLearningEvent, DBLearningPath, DBNote, DBPathNode, DBProfileSnapshot,
    DBReviewPlan, DBSourceDocument, DBStudentProfile, DBUser, DBWrongQuestion,
    DBAssessmentExam, SessionLocal, init_db,
)
from app.post_data_demo_seed import COURSE_ID, PATH_ID

init_db()
db = SessionLocal()
try:
    seed_result = seed_competition_demo(db)
    owner = db.query(DBUser).filter_by(username="lzz").one()
    course = db.get(DBCourse, COURSE_ID)
    if course is None:
        raise RuntimeError("POST-DATA complete course is missing")
    membership = db.query(DBCourseMembership).filter_by(
        course_id=COURSE_ID, user_public_id=owner.public_id, status="active"
    ).one()
    sources = db.query(DBSourceDocument).filter_by(course_id=COURSE_ID, processing_status="ready").all()
    pdf = next(row for row in sources if row.file_format.lower() == "pdf")
    video = next(row for row in sources if row.file_format.lower() == "mp4")
    first_page = pdf.parser_metadata["ocr"]["pages"][0]
    first_region = first_page["regions"][0]
    resources = {{
        row.artifact_type: {{"id": row.id, "title": row.title, "status": row.status}}
        for row in db.query(DBArtifact).filter_by(owner_public_id=owner.public_id, course_id=COURSE_ID).all()
        if row.id.startswith("postdata-resource-eml-")
    }}
    path = db.get(DBLearningPath, PATH_ID)
    focus_task = db.get(DBPathNode, "postdata-path-node-eml-03")
    payload = {{
        "seed_result": seed_result,
        "owner_public_id": owner.public_id,
        "course_id": course.id,
        "course_title": course.title,
        "membership_id": membership.id,
        "top_level_chapter_count": db.query(DBChapter).filter_by(course_id=COURSE_ID, parent_id=None).count(),
        "chapter_count": db.query(DBChapter).filter_by(course_id=COURSE_ID).count(),
        "source_count": len(sources),
        "source_formats": sorted({{row.file_format.lower() for row in sources}}),
        "pdf_source_id": pdf.id,
        "pdf_title": pdf.title,
        "pdf_page_count": len(pdf.parser_metadata["ocr"]["pages"]),
        "pdf_region": first_region["bbox"],
        "video_source_id": video.id,
        "video_title": video.title,
        "resources": resources,
        "profile_snapshot_id": db.query(DBProfileSnapshot).filter_by(owner_public_id=owner.public_id).order_by(DBProfileSnapshot.created_at.desc()).first().id,
        "path_id": path.id if path else None,
        "path_node_count": db.query(DBPathNode).filter_by(learning_path_id=PATH_ID).count(),
        "focus_task_id": focus_task.id if focus_task else None,
        "focus_task_title": focus_task.title if focus_task else None,
        "note_id": db.get(DBNote, "postdata-note-lzz-eml-deployment").id,
        "conversation_id": db.get(DBChatConversation, {CONVERSATION_ID!r}).id,
        "exam_id": db.get(DBAssessmentExam, {EXAM_ID!r}).id,
        "review_count": db.query(DBReviewPlan).filter_by(student_id="lzz").count(),
        "wrong_question_count": db.query(DBWrongQuestion).filter_by(student_id="lzz").count(),
        "learning_event_count": db.query(DBLearningEvent).filter_by(owner_public_id=owner.public_id).count(),
        "mastery_event_count": db.query(DBLearningEvent).filter_by(owner_public_id=owner.public_id, mastery_eligible=True).count(),
        "legacy_target_course": db.get(DBStudentProfile, "lzz").target_course,
    }}
    Path({str(fixture_path)!r}).write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=180)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def parse_json(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def database_state(db_path: Path, owner_public_id: str) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=20) as db:
        profile = db.execute(
            "SELECT target_course, concept_mastery, weak_points, learning_goals FROM student_profiles WHERE student_id='lzz'"
        ).fetchone()
        return {
            "learning_event_count": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "mastery_event_count": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=? AND mastery_eligible=1",
                (owner_public_id,),
            ).fetchone()[0],
            "profile_snapshots": db.execute(
                "SELECT id, profile_version, content_hash FROM profile_snapshots WHERE owner_public_id=? ORDER BY id",
                (owner_public_id,),
            ).fetchall(),
            "profile": {
                "target_course": profile[0],
                "concept_mastery": parse_json(profile[1]),
                "weak_points": parse_json(profile[2]),
                "learning_goals": parse_json(profile[3]),
            } if profile else None,
            "path_states": db.execute(
                "SELECT id, status, lock_version FROM learning_paths WHERE owner_public_id=? ORDER BY id",
                (owner_public_id,),
            ).fetchall(),
            "path_node_states": db.execute(
                "SELECT id, status, resource_status FROM path_nodes WHERE learning_path_id IN "
                "(SELECT id FROM learning_paths WHERE owner_public_id=?) ORDER BY id",
                (owner_public_id,),
            ).fetchall(),
            "review_states": db.execute(
                "SELECT id, review_count, mastery, next_review_at FROM review_plans WHERE student_id='lzz' ORDER BY id"
            ).fetchall(),
            "selection_count": db.execute(
                "SELECT COUNT(*) FROM document_selections WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "reading_position_count": db.execute(
                "SELECT COUNT(*) FROM document_reading_positions WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "owned_course_count": db.execute(
                "SELECT COUNT(*) FROM courses WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "owned_source_count": db.execute(
                "SELECT COUNT(*) FROM source_documents WHERE course_id IN "
                "(SELECT id FROM courses WHERE owner_public_id=?)", (owner_public_id,)
            ).fetchone()[0],
            "owned_chapter_count": db.execute(
                "SELECT COUNT(*) FROM chapters WHERE course_id IN "
                "(SELECT id FROM courses WHERE owner_public_id=?)", (owner_public_id,)
            ).fetchone()[0],
            "owned_source_ref_count": db.execute(
                "SELECT COUNT(*) FROM source_refs WHERE source_document_id IN "
                "(SELECT id FROM source_documents WHERE course_id IN "
                "(SELECT id FROM courses WHERE owner_public_id=?))", (owner_public_id,)
            ).fetchone()[0],
            "knowledge_document_count": db.execute(
                "SELECT COUNT(*) FROM knowledge_documents WHERE student_id='lzz'"
            ).fetchone()[0],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def attach_diagnostics(page: Page, report: dict[str, object]) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.scheme not in {"blob", "data"} and parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(response.url)
        if response.status >= 400:
            report["http_errors"].append({"status": response.status, "url": response.url})

    def on_console(message) -> None:
        if message.type == "error":
            report["console_errors"].append(message.text)

    page.on("response", on_response)
    def on_request_failed(request) -> None:
        item = {"url": request.url, "failure": request.failure}
        if request.url.startswith("blob:"):
            report["expected_media_cleanup"].append(item)
        else:
            report["failed_requests"].append(item)

    page.on("requestfailed", on_request_failed)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", on_console)


def capture(page: Page, report: dict[str, object], filename: str) -> None:
    page.wait_for_timeout(250)
    page.screenshot(path=OUTPUT_DIR / filename, full_page=True, animations="disabled")
    report["screenshots"].append(filename)


def install_session(page: Page, base_url: str) -> None:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": "lzz", "password": "404404aA"},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    state = json.dumps(response.json(), ensure_ascii=False)
    page.add_init_script(f"""
      const session = {state};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username || 'lzz');
      localStorage.setItem('edumatrix_display_name', session.display_name || session.username || 'lzz');
      localStorage.setItem('edumatrix_role', session.role || 'student');
      localStorage.setItem('edumatrix_student_id', session.student_id || session.username || 'lzz');
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', '{COURSE_ID}');
      localStorage.setItem('edumatrix_course_title', '{COURSE_TITLE}');
    """)


def open_route(page: Page, base_url: str, route: str, selector: str) -> None:
    page.goto(f"{base_url}{route}", wait_until="domcontentloaded", timeout=60_000)
    page.locator(selector).wait_for(state="visible", timeout=60_000)
    page.wait_for_load_state("networkidle", timeout=60_000)


def browser_api_snapshot(page: Page) -> dict[str, object]:
    return page.evaluate(
        """
        async ({ courseId, conversationId }) => {
          const token = localStorage.getItem('edumatrix_token')
          const get = async (path) => {
            const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` } })
            const body = await response.json().catch(() => ({}))
            if (!response.ok) throw new Error(`${path}: ${response.status} ${JSON.stringify(body)}`)
            return body
          }
          const [workspace, profile, resources, exams, conversations, conversation, review] = await Promise.all([
            get('/api/v1/m5/workspace'),
            get(`/api/v1/m5/profile-summary?course_id=${encodeURIComponent(courseId)}`),
            get(`/api/v1/m5/resources?course_id=${encodeURIComponent(courseId)}&limit=25`),
            get('/api/v1/m5/assessment/exams'),
            get('/api/v1/chat/conversations'),
            get(`/api/v1/chat/conversations/${conversationId}`),
            get(`/api/v1/review-schedule?month=2026-08&course_id=${encodeURIComponent(courseId)}`),
          ])
          return {
            workspace: {
              course_id: workspace.course?.id,
              path_id: workspace.current_path?.id,
              task_count: workspace.today_tasks?.length || workspace.tasks?.length || 0,
              today_tasks: (workspace.today_tasks || []).map(item => ({
                node_id: item.node_id,
                title: item.title,
                status: item.status,
                course_id: item.course_id,
              })),
            },
            profile: {
              course_id: profile.course?.id,
              knowledge_node_count: profile.knowledge_graph?.nodes?.length || 0,
            },
            resources: {
              total: resources.total,
              types: [...new Set((resources.items || []).map(item => item.artifact_type))].sort(),
            },
            exams: (exams.items || []).map(item => item.id),
            conversations: (conversations.items || []).map(item => item.id),
            conversation_message_count: conversation.messages?.length || 0,
            review: {
              selected_course_id: review.selected_course_id,
              task_count: review.tasks?.length || 0,
            },
          }
        }
        """,
        {"courseId": COURSE_ID, "conversationId": CONVERSATION_ID},
    )


def verify_course_and_readers(page: Page, base_url: str, fixture: dict[str, object], report: dict[str, object]) -> None:
    open_route(page, base_url, "/knowledge", "[data-testid='knowledge-course-shelf']")
    course_card = page.get_by_test_id(f"shelf-course-{COURSE_ID}")
    course_card.wait_for(state="visible")
    assert COURSE_TITLE in course_card.inner_text()
    assert page.get_by_test_id("create-personal-course").is_visible()
    capture(page, report, "01-knowledge-shelf-1440x900.png")

    page.get_by_test_id(f"open-course-{COURSE_ID}").click()
    page.wait_for_url(f"**/knowledge/courses/{COURSE_ID}", timeout=30_000)
    page.get_by_test_id("course-workspace").wait_for(state="visible")
    assert page.locator(".chapter-button").count() == fixture["top_level_chapter_count"] == 9
    assert COURSE_TITLE in page.locator("body").inner_text()
    capture(page, report, "02-complete-course-1440x900.png")

    open_route(
        page,
        base_url,
        f"/knowledge/documents/{fixture['pdf_source_id']}?course_id={COURSE_ID}",
        ".reader-page",
    )
    page.locator(".page-frame img").wait_for(state="visible", timeout=60_000)
    assert page.get_by_text("第 1 / 28 页", exact=True).is_visible()
    assert fixture["pdf_title"] in page.locator(".reader-header").inner_text()
    page.get_by_title("下一页").click()
    page.get_by_text("第 2 / 28 页", exact=True).wait_for(state="visible")
    page.get_by_title("上一页").click()
    page.get_by_text("第 1 / 28 页", exact=True).wait_for(state="visible")
    page.get_by_title("放大").click()
    page.get_by_text("110%", exact=True).wait_for(state="visible")
    capture(page, report, "03-pdf-reader-1440x900.png")

    layer = page.locator(".image-selection-layer")
    box = layer.bounding_box()
    assert box is not None
    region = fixture["pdf_region"]
    start_x = box["x"] + box["width"] * (region["x"] + 0.01)
    start_y = box["y"] + box["height"] * (region["y"] + 0.01)
    end_x = box["x"] + box["width"] * (region["x"] + region["width"] - 0.01)
    end_y = box["y"] + box["height"] * (region["y"] + region["height"] - 0.01)
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(end_x, end_y, steps=12)
    page.mouse.up()
    toolbar = page.get_by_role("toolbar", name="图片选区操作")
    toolbar.wait_for(state="visible")
    toolbar.get_by_role("button", name="提问", exact=True).click()
    page.get_by_label("针对选区的问题").fill("这一区域要求我掌握什么？")
    page.get_by_role("button", name="提交问题", exact=True).click()
    page.get_by_text("基于选区的回答", exact=True).wait_for(state="visible", timeout=30_000)
    assert "课程目标" in page.locator(".answer-result").inner_text()
    capture(page, report, "04-pdf-region-answer-1440x900.png")

    page.reload(wait_until="networkidle", timeout=60_000)
    page.locator(".image-selection-layer").wait_for(state="visible")
    page.locator(".image-selection-rect").wait_for(state="visible")
    assert page.get_by_text("110%", exact=True).is_visible()
    assert page.get_by_text("已恢复上次位置", exact=True).is_visible()
    report["checks"]["pdf_position_and_selection_restored"] = True

    open_route(
        page,
        base_url,
        f"/knowledge/documents/{fixture['video_source_id']}?course_id={COURSE_ID}",
        ".reader-page",
    )
    video = page.locator(".media-reader video")
    video.wait_for(state="visible", timeout=60_000)
    page.wait_for_function("element => element.readyState >= 1 && Number.isFinite(element.duration)", arg=video.element_handle(), timeout=60_000)
    media = video.evaluate("element => ({ src: element.currentSrc, duration: element.duration, readyState: element.readyState })")
    assert str(media["src"]).startswith("blob:")
    assert media["duration"] >= 20
    assert "本地视频为 EduMatrix 团队制作" in page.locator(".media-transcript").inner_text()
    report["media"] = media
    capture(page, report, "05-local-course-video-1440x900.png")


def verify_learning_surfaces(page: Page, base_url: str, fixture: dict[str, object], report: dict[str, object]) -> None:
    course_query = f"?course_id={COURSE_ID}"
    surfaces = [
        ("dashboard", "/", "[data-testid='dashboard-today-tasks']", "边缘异常检测"),
        ("workspace", f"/workspace{course_query}", "[data-testid='today-learning-focus']", fixture["focus_task_title"]),
        ("profile", f"/profile/learning{course_query}", "[data-testid='profile-knowledge-map']", "知识掌握图谱"),
        ("resources", f"/workspace/resources{course_query}", "[data-testid='resource-center']", "边缘异常检测与阈值治理个性化讲义"),
    ]
    for index, (name, route, selector, expected) in enumerate(surfaces, start=6):
        open_route(page, base_url, route, selector)
        assert expected in page.locator(selector).inner_text()
        if name == "workspace":
            assert COURSE_TITLE in page.locator("body").inner_text()
        if name == "profile":
            graph = page.get_by_test_id("knowledge-graph-explorer")
            graph.locator("canvas").wait_for(state="visible")
            graph.get_by_placeholder("检索知识点").fill("边缘异常检测与阈值治理")
            assert "边缘异常检测与阈值治理" in page.get_by_test_id("profile-node-evidence").inner_text()
        capture(page, report, f"{index:02d}-{name}-1440x900.png")
        report["learning_surfaces"][name] = {"route": route, "expected": expected, "status": "visible"}

    assert page.locator(".type-option[data-resource-type]:not([data-resource-type='all'])").count() == 9
    resources = fixture["resources"]
    assert set(resources) == set(RESOURCE_ROUTES)
    resource_screenshots = {
        "handout": "10-handout-1440x900.png",
        "code_sandbox": "11-code-sandbox-1440x900.png",
        "interactive_model": "12-interactive-model-1440x900.png",
        "feynman": "13-feynman-1440x900.png",
    }
    for resource_type, (route_template, selector) in RESOURCE_ROUTES.items():
        resource = resources[resource_type]
        route = f"{route_template.format(id=resource['id'])}{course_query}"
        open_route(page, base_url, route, selector)
        page_text = page.locator("body").inner_text()
        if resource_type == "feynman":
            assert "边缘异常检测与阈值治理 · 费曼复述" in page_text
            assert "请把“边缘异常检测与阈值治理”讲给一位刚接触这个主题的同学听" in page_text
        else:
            assert resource["title"] in page_text
        report["resource_pages"][resource_type] = {
            "route": route,
            "resource_id": resource["id"],
            "title": resource["title"],
            "status": "visible",
        }
        if resource_type in resource_screenshots:
            capture(page, report, resource_screenshots[resource_type])

    open_route(page, base_url, f"/learn{course_query}", "[data-testid='focused-chat-workspace']")
    conversation = page.locator(".conversation-item").filter(has_text="为什么异常阈值不能直接固定上线")
    conversation.wait_for(state="visible")
    conversation.click()
    page.get_by_text("直接调高阈值可能暂时减少误报", exact=False).wait_for(state="visible")
    assert page.get_by_test_id("chat-source-list").is_visible()
    capture(page, report, "14-source-linked-chat-1440x900.png")

    open_route(page, base_url, f"/workspace/review{course_query}", ".review-page")
    assert "边缘异常检测与阈值治理" in page.locator(".review-page").inner_text()
    capture(page, report, "15-review-1440x900.png")

    open_route(page, base_url, f"/workspace/notes{course_query}", "[data-testid='notes-workspace']")
    page.get_by_role("heading", name="量化部署与异常阈值治理复盘", exact=True).wait_for(state="visible")
    capture(page, report, "16-notes-1440x900.png")

    open_route(page, base_url, f"/workspace/review/wrong-questions{course_query}", "[data-testid='wrong-question-workspace']")
    page.get_by_test_id("wrong-question-list-item").first.wait_for(state="visible")
    assert "边缘异常检测与阈值治理" in page.get_by_test_id("wrong-question-workspace").inner_text()
    capture(page, report, "17-wrong-question-1440x900.png")

    open_route(
        page,
        base_url,
        f"/workspace/assessment/exams/{EXAM_ID}{course_query}",
        "[data-testid='formal-exam-workspace']",
    )
    page.get_by_test_id("exam-taking").wait_for(state="visible")
    assert "量化部署与异常阈值治理智能组卷" in page.get_by_test_id("formal-exam-workspace").inner_text()
    capture(page, report, "18-intelligent-exam-1440x900.png")


def verify_personal_course_upload(page: Page, base_url: str, report: dict[str, object]) -> None:
    open_route(page, base_url, "/knowledge", "[data-testid='knowledge-course-shelf']")
    page.get_by_test_id("create-personal-course").click()
    page.get_by_role("dialog", name="新建课程").wait_for(state="visible")
    page.get_by_label("课程名称").fill(PERSONAL_COURSE_TITLE)
    page.get_by_label("学习方向").fill("嵌入式机器学习")
    page.get_by_label("课程说明").fill("用于验证个人课程、真实资料上传、阅读与来源定位闭环")
    page.get_by_role("button", name="创建并进入课程", exact=True).click()
    page.wait_for_url("**/knowledge/courses/course-*", timeout=30_000)
    page.get_by_test_id("course-outline-empty").wait_for(state="visible", timeout=30_000)
    personal_course_id = page.url.split("/knowledge/courses/", 1)[1].split("?", 1)[0]
    assert PERSONAL_COURSE_TITLE in page.locator(".course-header").inner_text()
    assert page.get_by_text("课程还没有可阅读资料", exact=True).is_visible()

    page.locator("input[type='file']").set_input_files(str(PERSONAL_UPLOAD_FILE))
    page.get_by_text("1 份资料已进入课程", exact=True).wait_for(state="visible", timeout=60_000)
    page.get_by_test_id("course-workspace").wait_for(state="visible", timeout=60_000)
    capture(page, report, "21-personal-course-upload-1440x900.png")

    snapshot = page.evaluate(
        """
        async (courseId) => {
          const token = localStorage.getItem('edumatrix_token')
          const headers = { Authorization: `Bearer ${token}` }
          const [catalogResponse, outlineResponse] = await Promise.all([
            fetch('/api/knowledge/courses', { headers }),
            fetch(`/api/v1/courses/${encodeURIComponent(courseId)}/outline`, { headers }),
          ])
          const catalog = await catalogResponse.json()
          const outline = await outlineResponse.json()
          if (!catalogResponse.ok || !outlineResponse.ok) {
            throw new Error(`personal course snapshot failed: ${catalogResponse.status}/${outlineResponse.status}`)
          }
          return {
            course: (catalog.shelf || []).find(item => item.id === courseId),
            outline,
          }
        }
        """,
        personal_course_id,
    )
    assert snapshot["course"]["document_count"] == 1
    assert snapshot["course"]["source_count"] == 1
    assert snapshot["course"]["ready_source_count"] == 1
    assert snapshot["outline"]
    source_document_id = snapshot["outline"][0]["source_document_id"]

    page.get_by_test_id("open-chapter-document").click()
    page.wait_for_url("**/knowledge/documents/**", timeout=30_000)
    page.locator(".reader-page").wait_for(state="visible", timeout=60_000)
    assert PERSONAL_COURSE_TITLE in page.locator(".reader-header").inner_text()
    assert PERSONAL_UPLOAD_FILE.stem in page.locator(".reader-header").inner_text()
    with page.expect_response(
        lambda response: "/api/v1/document-reader/positions/" in response.url
        and response.request.method == "PUT",
        timeout=30_000,
    ) as saved_position:
        page.locator(".reading-viewport").evaluate(
            "element => { element.scrollTop = Math.min(120, element.scrollHeight); element.dispatchEvent(new Event('scroll')) }"
        )
    assert saved_position.value.ok
    capture(page, report, "22-personal-course-reader-1440x900.png")
    report["personal_course_upload"] = {
        "course_id": personal_course_id,
        "course_title": PERSONAL_COURSE_TITLE,
        "filename": PERSONAL_UPLOAD_FILE.name,
        "source_document_id": source_document_id,
        "document_count": snapshot["course"]["document_count"],
        "outline_count": len(snapshot["outline"]),
        "status": "ready_and_opened",
    }
    report["checks"]["personal_course_real_upload_opened"] = True


def verify_secondary_viewport(page: Page, base_url: str, fixture: dict[str, object], report: dict[str, object]) -> None:
    open_route(page, base_url, "/knowledge", "[data-testid='knowledge-course-shelf']")
    page.get_by_test_id(f"shelf-course-{COURSE_ID}").wait_for(state="visible")
    capture(page, report, "19-knowledge-shelf-1366x768.png")
    open_route(
        page,
        base_url,
        f"/knowledge/documents/{fixture['pdf_source_id']}?course_id={COURSE_ID}",
        ".reader-page",
    )
    page.locator(".page-frame img").wait_for(state="visible", timeout=60_000)
    assert "28 页" in page.locator(".page-control").inner_text()
    capture(page, report, "20-pdf-reader-1366x768.png")


def assert_read_only_learning_state(before: dict[str, object], after: dict[str, object]) -> None:
    for key in (
        "learning_event_count",
        "mastery_event_count",
        "profile_snapshots",
        "profile",
        "path_states",
        "path_node_states",
        "review_states",
    ):
        assert after[key] == before[key], (key, before[key], after[key])


def run() -> dict[str, object]:
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = 9011
    base.COURSE_ID = COURSE_ID
    base.clear_output()
    db_path = OUTPUT_DIR / "post_data_01.sqlite3"
    upload_dir = OUTPUT_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    port = base.free_port()
    env = base.runtime_env(db_path, port)
    env.update({
        "EDUMATRIX_AUTH_SECRET_KEY": "post-data-01-isolated-secret",
        "EDUMATRIX_UPLOAD_DIR": str(upload_dir),
        "EDUMATRIX_SANDBOX_MODE": "trusted_local",
    })
    fixture = seed_fixture(env)
    process: subprocess.Popen | None = None
    report: dict[str, object] = {
        "schema_version": "post-data-01.browser-evidence.v1",
        "task_id": "POST-DATA-01",
        "course_id": COURSE_ID,
        "course_title": COURSE_TITLE,
        "browser_engine": "Microsoft Edge (Chromium)",
        "viewports": [[1440, 900], [1366, 768]],
        "fixture": fixture,
        "screenshots": [],
        "learning_surfaces": {},
        "resource_pages": {},
        "checks": {},
        "http_errors": [],
        "failed_requests": [],
        "expected_media_cleanup": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "external_model_called": False,
    }
    try:
        process = base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        before = database_state(db_path, str(fixture["owner_public_id"]))
        report["database_before"] = before
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)

            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            attach_diagnostics(page, report)
            install_session(page, base_url)
            verify_course_and_readers(page, base_url, fixture, report)
            report["api_snapshot"] = browser_api_snapshot(page)
            verify_learning_surfaces(page, base_url, fixture, report)
            verify_personal_course_upload(page, base_url, report)
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            attach_diagnostics(page, report)
            install_session(page, base_url)
            verify_secondary_viewport(page, base_url, fixture, report)
            context.close()
            browser.close()

        after = database_state(db_path, str(fixture["owner_public_id"]))
        report["database_after"] = after
        assert_read_only_learning_state(before, after)
        assert after["selection_count"] == before["selection_count"] + 1
        assert after["reading_position_count"] == before["reading_position_count"] + 2
        assert after["owned_course_count"] == before["owned_course_count"] + 1
        assert after["owned_source_count"] == before["owned_source_count"] + 1
        assert after["owned_chapter_count"] > before["owned_chapter_count"]
        assert after["owned_source_ref_count"] > before["owned_source_ref_count"]
        assert after["knowledge_document_count"] == before["knowledge_document_count"] + 1
        assert after["integrity"] == "ok"
        assert after["foreign_key_violations"] == 0
        api = report["api_snapshot"]
        assert api["workspace"]["course_id"] == COURSE_ID
        assert api["workspace"]["path_id"] == fixture["path_id"]
        assert api["workspace"]["today_tasks"][0]["node_id"] == fixture["focus_task_id"]
        assert api["workspace"]["today_tasks"][0]["title"] == fixture["focus_task_title"]
        assert api["workspace"]["today_tasks"][0]["course_id"] == COURSE_ID
        assert api["profile"]["course_id"] == COURSE_ID
        assert api["profile"]["knowledge_node_count"] == 8
        assert api["resources"]["total"] == 9
        assert len(api["resources"]["types"]) == 9
        assert EXAM_ID in api["exams"]
        assert CONVERSATION_ID in api["conversations"]
        assert api["conversation_message_count"] == 2
        assert api["review"]["selected_course_id"] == COURSE_ID
        assert api["review"]["task_count"] >= 1
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["external_requests"], report["external_requests"]
        report["checks"]["ordinary_browsing_preserved_learning_state"] = True
        report["checks"]["sqlite_integrity"] = True
        report["status"] = "passed"
        return report
    finally:
        base.stop_service(process, port)
        if db_path.exists():
            with sqlite3.connect(db_path, timeout=20) as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            report["checks"]["sqlite_checkpoint_truncated"] = True
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT_DIR.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT_DIR / "manifest.json").write_text(
            json.dumps(
                {"schema_version": "post-data-01.evidence-manifest.v1", "files": files},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))
