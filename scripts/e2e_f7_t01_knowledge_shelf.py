"""F7-T01 course-first knowledge-shelf desktop E2E on isolated SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, sync_playwright

import e2e_f6_t03_code_sandbox as base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "f7_t01_knowledge_shelf"
    / "browser"
)
COURSE_ID = "course-machine-learning-foundations-v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def seed_fixture(env: dict[str, str]) -> dict[str, object]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import json
from pathlib import Path
from app.competition_demo_seed import seed_competition_demo
from app.database import DBCourse, DBCourseDocument, DBChapter, DBKnowledgePoint, DBSourceDocument, DBUser, SessionLocal, init_db
from course_catalog import seed_default_courses

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    seed_default_courses(db)
    course = db.get(DBCourse, {COURSE_ID!r})
    user = db.query(DBUser).filter_by(username="lzz").one()
    if course is None:
        raise RuntimeError("flagship preloaded course is missing")
    payload = {{
        "course_id": course.id,
        "course_title": course.title,
        "owner_public_id": user.public_id,
        "chapter_count": db.query(DBChapter).filter_by(course_id=course.id).count(),
        "document_count": db.query(DBCourseDocument).filter_by(course_id=course.id, status="published").count(),
        "source_count": db.query(DBSourceDocument).filter_by(course_id=course.id).count(),
        "knowledge_point_count": db.query(DBKnowledgePoint).filter_by(domain_pack=course.domain_pack).count(),
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
        return {
            "learning_event_count": db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
            "active_membership_count": db.execute(
                "SELECT COUNT(*) FROM course_memberships WHERE status='active'"
            ).fetchone()[0],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def capture(page: Page, report: dict, filename: str) -> None:
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=OUTPUT_DIR / filename, full_page=True)
    report["screenshots"].append(filename)


def page_diagnostics(page: Page, report: dict) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(response.url)
        if response.status < 400:
            return
        if response.status == 503 and response.url.endswith("/api/knowledge/courses"):
            report["expected_injected_failures"].append({"status": response.status, "url": response.url})
            return
        report["http_errors"].append({"status": response.status, "url": response.url})

    def on_console(message) -> None:
        if message.type != "error":
            return
        if "503 (Service Unavailable)" in message.text:
            report["expected_injected_console"].append(message.text)
            return
        report["console_errors"].append(message.text)

    page.on("response", on_response)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url,
        "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", on_console)


def visual_contract(page: Page, root_selector: str = ".course-shelf") -> dict[str, object]:
    return page.evaluate("""
      (rootSelector) => {
        const root = document.querySelector(rootSelector)
        if (!root) return { missingRoot: true }
        const visible = element => {
          const style = getComputedStyle(element)
          const box = element.getBoundingClientRect()
          return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0
        }
        const textNodes = [...root.querySelectorAll(
          'button, h1, h2, h3, p, span, strong, small, label, summary, dt, dd, li'
        )].filter(element => visible(element) && element.textContent.trim())
        const smallText = textNodes
          .filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 13.9)
          .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 80), size: getComputedStyle(element).fontSize }))
        const clippedText = textNodes
          .filter(element => {
            const style = getComputedStyle(element)
            if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
            if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
            return element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1
          })
          .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 80) }))
        const decorativeBackgrounds = [...root.querySelectorAll('*')]
          .filter(element => visible(element))
          .map(element => getComputedStyle(element).backgroundImage)
          .filter(value => value && value !== 'none')
        const rail = root.querySelector('.chapter-rail')?.getBoundingClientRect()
        const main = root.querySelector('.course-main')?.getBoundingClientRect()
        const layoutOverlap = rail && main
          ? !(rail.right <= main.left + 1 || main.right <= rail.left + 1 || rail.bottom <= main.top + 1 || main.bottom <= rail.top + 1)
          : false
        const panels = [root, ...root.querySelectorAll('.course-card, .chapter-rail, .chapter-focus, .course-search, .structure-overview, .state-panel')]
          .filter(element => visible(element))
          .map(element => Number.parseFloat(getComputedStyle(element).borderRadius))
        return {
          missingRoot: false,
          pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 || root.scrollWidth > root.clientWidth + 1,
          layoutOverlap,
          smallText,
          clippedText,
          decorativeBackgrounds,
          oversizedPanelRadii: panels.filter(value => value > 8.1),
          visiblePrimaryActions: [...root.querySelectorAll('.primary-button')].filter(visible).length,
        }
      }
    """, root_selector)


def assert_visual_contract(
    page: Page,
    report: dict,
    key: str,
    *,
    primary_actions: int | None = None,
    root_selector: str = ".course-shelf",
) -> None:
    result = visual_contract(page, root_selector)
    report["visual"][key] = result
    assert result["missingRoot"] is False, result
    assert result["pageOverflow"] is False, result
    assert result["layoutOverlap"] is False, result
    assert result["smallText"] == [], result
    assert result["clippedText"] == [], result
    assert result["decorativeBackgrounds"] == [], result
    assert result["oversizedPanelRadii"] == [], result
    if primary_actions is not None:
        assert result["visiblePrimaryActions"] == primary_actions, result


def inject_one_catalog_failure(page: Page) -> None:
    state = {"used": False}

    def handler(route: Route) -> None:
        if not state["used"]:
            state["used"] = True
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "注入课程书架加载失败"}, ensure_ascii=False),
            )
            return
        route.continue_()

    page.route("**/api/knowledge/courses", handler)


def open_home(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/knowledge", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("knowledge-course-shelf").wait_for(state="visible")


def verify_primary_viewport(page: Page, base_url: str, fixture: dict, report: dict) -> None:
    inject_one_catalog_failure(page)
    open_home(page, base_url)
    page.get_by_test_id("course-shelf-error").wait_for(state="visible")
    capture(page, report, "01-catalog-failure-1440x900.png")
    page.get_by_role("button", name="重新加载", exact=True).click()

    shelf = page.get_by_test_id("my-course-shelf")
    shelf.wait_for(state="visible")
    flagship = page.get_by_test_id(f"shelf-course-{COURSE_ID}")
    flagship.wait_for(state="visible")
    assert fixture["course_title"] in flagship.inner_text()
    assert "来源与索引完整" in flagship.inner_text()
    positions = page.evaluate("""
      () => ['my-shelf-title', 'recommendation-title', 'discovery-title']
        .map(id => document.getElementById(id).getBoundingClientRect().top + window.scrollY)
    """)
    assert positions == sorted(positions), positions
    assert page.get_by_test_id("knowledge-advanced-tools").evaluate("element => element.open") is False
    assert page.get_by_text("拖拽文件到此处，或点击选择文件").is_visible() is False
    assert_visual_contract(page, report, "home_1440x900", primary_actions=1)
    capture(page, report, "02-course-shelf-1440x900.png")

    recommendation_buttons = page.locator('[data-testid^="add-course-"]')
    if recommendation_buttons.count():
        recommendation_buttons.first.click()
        page.locator(".action-message").wait_for(state="visible")
        assert "已加入书架" in page.locator(".action-message").inner_text()

    page.get_by_test_id(f"open-course-{COURSE_ID}").click()
    page.wait_for_url(f"{base_url}/knowledge/courses/{COURSE_ID}", timeout=10_000)
    page.get_by_test_id("course-workspace").wait_for(state="visible")
    assert page.locator(".chapter-button").count() == fixture["chapter_count"]
    assert_visual_contract(page, report, "course_1440x900", primary_actions=1)
    capture(page, report, "03-course-workspace-1440x900.png")

    page.locator(".chapter-button").nth(1).click()
    page.get_by_test_id("open-chapter-document").click()
    page.locator(".knowledge-modal").wait_for(state="visible")
    page.get_by_test_id("document-detail-loading").wait_for(state="hidden")
    assert page.get_by_test_id("document-detail-error").count() == 0
    page.get_by_text("文件哈希", exact=True).wait_for(state="visible")
    assert page.get_by_text("统一来源与解析版本").count() == 0
    preview_text = page.get_by_test_id("document-content-preview").inner_text()
    assert "\\n>" not in preview_text
    assert_visual_contract(page, report, "document_1440x900", root_selector=".knowledge-modal")
    capture(page, report, "04-course-document-1440x900.png")
    previous_workspace = page.get_by_test_id("course-workspace").element_handle()
    page.get_by_title("关闭 (Esc)").click()
    page.wait_for_url(f"{base_url}/knowledge/courses/{COURSE_ID}", timeout=10_000)
    if previous_workspace is not None:
        previous_workspace.wait_for_element_state("hidden", timeout=10_000)
    page.get_by_test_id("course-workspace").wait_for(state="visible")

    page.get_by_label("课程正文检索词").fill("线性回归")
    page.get_by_role("button", name="检索", exact=True).click()
    page.get_by_test_id("course-search-results").wait_for(state="visible")
    assert page.locator(".search-result").count() >= 1
    capture(page, report, "05-course-search-1440x900.png")
    page.locator(".search-result").first.get_by_role("button", name="打开来源", exact=True).click()
    page.locator(".knowledge-modal").wait_for(state="visible")
    page.get_by_test_id("document-detail-loading").wait_for(state="hidden")
    page.get_by_title("关闭 (Esc)").click()

    page.get_by_role("button", name="查看课程结构", exact=True).click()
    page.get_by_test_id("course-graph-contract").wait_for(state="visible")
    assert_visual_contract(page, report, "graph_1440x900", primary_actions=1)
    capture(page, report, "06-course-graph-contract-1440x900.png")

    page.goto(f"{base_url}/knowledge/discover", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("knowledge-discovery-boundary").wait_for(state="visible")
    assert "候选资料不会自动进入课程" in page.locator(".discovery-workflow").inner_text()
    assert_visual_contract(page, report, "discovery_1440x900", primary_actions=0)
    capture(page, report, "07-discovery-boundary-1440x900.png")

    open_home(page, base_url)
    page.get_by_test_id("my-course-shelf").wait_for(state="visible")
    page.get_by_test_id("knowledge-advanced-tools").locator("summary").click()
    page.get_by_text("拖拽文件到此处，或点击选择文件").wait_for(state="visible")
    capture(page, report, "08-advanced-tools-preserved-1440x900.png")


def verify_secondary_viewport(page: Page, base_url: str, report: dict) -> None:
    open_home(page, base_url)
    page.get_by_test_id("my-course-shelf").wait_for(state="visible")
    assert_visual_contract(page, report, "home_1366x768", primary_actions=1)
    capture(page, report, "09-course-shelf-1366x768.png")
    page.get_by_test_id(f"open-course-{COURSE_ID}").click()
    page.wait_for_url(f"{base_url}/knowledge/courses/{COURSE_ID}", timeout=10_000)
    page.get_by_test_id("course-workspace").wait_for(state="visible")
    assert_visual_contract(page, report, "course_1366x768", primary_actions=1)
    capture(page, report, "10-course-workspace-1366x768.png")
    page.locator(".chapter-button").nth(1).click()
    page.get_by_test_id("open-chapter-document").click()
    page.locator(".knowledge-modal").wait_for(state="visible")
    page.get_by_test_id("document-detail-loading").wait_for(state="hidden")
    assert page.get_by_test_id("document-detail-error").count() == 0
    assert "\\n>" not in page.get_by_test_id("document-content-preview").inner_text()
    assert_visual_contract(page, report, "document_1366x768", root_selector=".knowledge-modal")
    capture(page, report, "11-course-document-1366x768.png")
    page.get_by_title("关闭 (Esc)").click()


def run() -> dict:
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = 8997
    base.COURSE_ID = COURSE_ID
    base.clear_output()
    db_path = OUTPUT_DIR / "f7_t01.sqlite3"
    port = base.free_port()
    env = base.runtime_env(db_path, port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "f7-t01-isolated-secret"
    env["EDUMATRIX_SANDBOX_MODE"] = "disabled"
    fixture = seed_fixture(env)
    process: subprocess.Popen | None = None
    report = {
        "schema_version": "f7-t01.knowledge-shelf-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "visual": {},
        "expected_injected_failures": [],
        "expected_injected_console": [],
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
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            base.login(page, base_url)
            verify_primary_viewport(page, base_url, fixture, report)
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            base.login(page, base_url)
            verify_secondary_viewport(page, base_url, report)
            context.close()
            browser.close()

        report["database"] = database_state(db_path)
        assert report["database"]["learning_event_count"] == fixture["initial_learning_event_count"]
        assert report["database"]["integrity"] == "ok"
        assert report["database"]["foreign_key_violations"] == 0
        assert len(report["expected_injected_failures"]) == 1
        assert len(report["expected_injected_console"]) <= 1
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
                {"schema_version": "f7-t01.evidence-manifest.v1", "files": files},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
