"""F7-T03 course graph and web-candidate admission desktop E2E."""

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
    / "f7_t03_graph_admission"
    / "browser"
)
COURSE_ID = "course-machine-learning-foundations-v1"
SEARCH_URL = "https://open.example.org/ml/guide.pdf"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def seed_fixture(env: dict[str, str]) -> dict[str, object]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import json
from pathlib import Path
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBChapter, DBChapterKnowledgePoint, DBCourse, DBKnowledgePoint, DBSourceDocument, DBSourceRef,
    DBStudentProfile, DBUser, SessionLocal, init_db,
)
from course_catalog import seed_default_courses

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    seed_default_courses(db)
    user = db.query(DBUser).filter_by(username="lzz").one()
    if db.get(DBStudentProfile, "lzz") is None:
        db.add(DBStudentProfile(student_id="lzz"))
        db.commit()
    course = db.get(DBCourse, {COURSE_ID!r})
    chapter = db.query(DBChapter).filter_by(course_id={COURSE_ID!r}).order_by(DBChapter.position).first()
    source = db.get(DBSourceDocument, chapter.source_document_id) if chapter is not None else None
    relation = db.query(DBChapterKnowledgePoint).filter_by(chapter_id=chapter.id).order_by(DBChapterKnowledgePoint.knowledge_point_id).first() if chapter is not None else None
    point = db.get(DBKnowledgePoint, relation.knowledge_point_id) if relation is not None else None
    if course is None or chapter is None or source is None or point is None:
        raise RuntimeError("canonical F7-T03 course graph fixture is incomplete")
    payload = {{
        "course_id": course.id,
        "course_title": course.title,
        "chapter_id": chapter.id,
        "chapter_title": chapter.title,
        "source_id": source.id,
        "source_title": source.title,
        "knowledge_point_title": point.title,
        "owner_public_id": user.public_id,
        "initial_counts": {{
            "learning_events": db.execute(__import__("sqlalchemy").text("SELECT COUNT(*) FROM learning_events")).scalar_one(),
            "profile_snapshots": db.execute(__import__("sqlalchemy").text("SELECT COUNT(*) FROM profile_snapshots")).scalar_one(),
            "path_nodes": db.execute(__import__("sqlalchemy").text("SELECT COUNT(*) FROM path_nodes")).scalar_one(),
            "source_refs": db.query(DBSourceRef).count(),
        }},
    }}
    Path({str(fixture_path)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=120)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def database_state(db_path: Path, owner_public_id: str) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        counts = {
            "learning_events": db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
            "profile_snapshots": db.execute("SELECT COUNT(*) FROM profile_snapshots").fetchone()[0],
            "path_nodes": db.execute("SELECT COUNT(*) FROM path_nodes").fetchone()[0],
            "source_refs": db.execute("SELECT COUNT(*) FROM source_refs").fetchone()[0],
        }
        candidates = db.execute(
            "SELECT review_status, imported_version, license_status, trust_level "
            "FROM web_source_candidates WHERE owner_public_id=? ORDER BY created_at",
            (owner_public_id,),
        ).fetchall()
        return {
            "protected_counts": counts,
            "candidates": [
                {
                    "review_status": row[0],
                    "imported_version": row[1],
                    "license_status": row[2],
                    "trust_level": row[3],
                }
                for row in candidates
            ],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def capture(page: Page, report: dict[str, object], filename: str) -> None:
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=OUTPUT_DIR / filename, full_page=True)
    report["screenshots"].append(filename)


def page_diagnostics(page: Page, report: dict[str, object]) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(response.url)
        if response.status < 400:
            return
        if response.status == 503 and "/api/knowledge/discovery/search" in response.url:
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


def visual_contract(page: Page, root_selector: str, kind: str) -> dict[str, object]:
    return page.evaluate(
        """
        ({ rootSelector, kind }) => {
          const root = document.querySelector(rootSelector)
          if (!root) return { missingRoot: true }
          const visible = element => {
            const style = getComputedStyle(element)
            const box = element.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0
          }
          const textNodes = [...root.querySelectorAll('button, a, h1, h2, h3, p, span, strong, small, label, dt, dd, li')]
            .filter(element => visible(element) && element.textContent.trim())
          const smallText = textNodes
            .filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 13.9)
            .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 80), size: getComputedStyle(element).fontSize }))
          const clippedText = textNodes
            .filter(element => {
              if (element.closest('.sr-only')) return false
              const style = getComputedStyle(element)
              if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
              if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
              return element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1
            })
            .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 80) }))
          const decorativeBackgrounds = [...root.querySelectorAll('*')]
            .filter(visible)
            .map(element => getComputedStyle(element).backgroundImage)
            .filter(value => value && value !== 'none')
          const forbiddenThemeValues = new Set([
            'rgb(16, 185, 129)', 'rgb(14, 165, 233)', 'rgb(139, 92, 246)',
            'rgb(59, 130, 246)', 'rgb(168, 85, 247)'
          ])
          const forbiddenThemeHits = [...root.querySelectorAll('*')]
            .filter(visible)
            .flatMap(element => {
              const style = getComputedStyle(element)
              return [style.color, style.backgroundColor, style.borderColor]
                .filter(value => forbiddenThemeValues.has(value))
                .map(value => ({ tag: element.tagName, value, text: element.textContent.trim().slice(0, 50) }))
            })
          const left = root.querySelector(kind === 'graph' ? '.graph-stage' : '.source-results')?.getBoundingClientRect()
          const right = root.querySelector(kind === 'graph' ? '.graph-overview' : '.source-preview')?.getBoundingClientRect()
          const overlap = left && right
            ? !(left.right <= right.left + 1 || right.right <= left.left + 1 || left.bottom <= right.top + 1 || right.bottom <= left.top + 1)
            : true
          return {
            missingRoot: false,
            pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 || root.scrollWidth > root.clientWidth + 1,
            rootBackground: getComputedStyle(root).backgroundColor,
            overlap,
            columnRatio: left && right ? left.width / right.width : 0,
            smallText,
            clippedText,
            decorativeBackgrounds,
            forbiddenThemeHits,
          }
        }
        """,
        {"rootSelector": root_selector, "kind": kind},
    )


def assert_visual_contract(
    page: Page,
    report: dict[str, object],
    key: str,
    root_selector: str,
    kind: str,
) -> None:
    result = visual_contract(page, root_selector, kind)
    report["visual"][key] = result
    assert result["missingRoot"] is False, result
    assert result["pageOverflow"] is False, result
    assert result["rootBackground"] == "rgb(245, 247, 247)", result
    assert result["overlap"] is False, result
    if kind == "graph":
        assert 2.0 <= result["columnRatio"] <= 3.4, result
    else:
        assert 1.25 <= result["columnRatio"] <= 2.0, result
    assert result["smallText"] == [], result
    assert result["clippedText"] == [], result
    assert result["decorativeBackgrounds"] == [], result
    assert result["forbiddenThemeHits"] == [], result


def install_discovery_route(page: Page, report: dict[str, object]) -> None:
    state = {"requests": 0}

    def handler(route: Route) -> None:
        state["requests"] += 1
        if state["requests"] == 1:
            payload = {
                "query": "机器学习公开教材",
                "items": [{
                    "id": SEARCH_URL,
                    "title": "开放机器学习课程讲义",
                    "url": SEARCH_URL,
                    "snippet": "包含课程正文、公式、图表和实验说明。",
                    "sourceDomain": "open.example.org",
                    "authorOrOrganization": "开放课程组织",
                    "fileFormat": "pdf",
                    "licenseStatus": "unknown",
                    "licenseText": "",
                    "usageHint": "尚未核验允许用途",
                    "parsingImpact": {
                        "summary": "可解析正文和基础图片；复杂公式与表格需要复核。",
                        "text": True,
                        "images": "review_required",
                        "formulas": "review_required",
                        "tables": "review_required",
                    },
                    "trustLevel": "unverified",
                    "reviewStatus": "search_result",
                    "blockers": ["许可未确认", "允许用途未确认"],
                    "canAdmit": False,
                    "authorityScope": "web_search_result",
                    "authoritative": False,
                    "resourceGenerationEligible": False,
                }],
                "filteredResultCount": 1,
                "authorityBoundary": "联网搜索结果只进入候选区；未经许可核验不得进入权威课程、RAG 或资源生成。",
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))
            return
        route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({"detail": {"message": "联网发现暂时不可用，搜索词和已有候选已保留。", "query": "神经网络公开教材"}}, ensure_ascii=False),
        )

    page.route("**/api/knowledge/discovery/search**", handler)
    report["checks"]["injected_discovery_requests"] = state


def open_graph(page: Page, base_url: str, fixture: dict[str, object]) -> None:
    page.goto(f"{base_url}/knowledge/graph/{fixture['course_id']}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("course-knowledge-graph-workspace").wait_for(state="visible")
    page.get_by_text("正在读取课程事实", exact=True).wait_for(state="hidden")
    page.locator(".graph-stage canvas").wait_for(state="visible", timeout=30_000)


def verify_graph(page: Page, base_url: str, fixture: dict[str, object], report: dict[str, object], suffix: str) -> None:
    open_graph(page, base_url, fixture)
    assert page.locator(".course-statistics").get_by_text("12", exact=True).count() >= 1
    assert "联网候选不会进入本图谱" in page.locator(".authority-note").inner_text()
    assert_visual_contract(page, report, f"graph_initial_{suffix}", ".graph-workspace", "graph")
    capture(page, report, f"01-graph-{suffix}.png")

    page.get_by_test_id("graph-chapter-filter").select_option(str(fixture["chapter_id"]))
    page.get_by_test_id("graph-relation-filter").select_option("teaches")
    page.locator(".graph-stage canvas").wait_for(state="visible")
    page.get_by_role("button", name="关系投影", exact=True).click()
    assert page.get_by_role("button", name="关系投影", exact=True).get_attribute("aria-pressed") == "true"
    search = page.get_by_placeholder("检索知识点")
    search.fill(str(fixture["knowledge_point_title"]))
    page.locator(".graph-overview h2").get_by_text(str(fixture["knowledge_point_title"]), exact=True).wait_for(state="visible")
    capture(page, report, f"02-projection-source-{suffix}.png")

    page.get_by_role("button", name="层级列表", exact=True).click()
    page.get_by_test_id("graph-hierarchy-fallback").wait_for(state="visible")
    assert str(fixture["chapter_title"]) in page.get_by_test_id("graph-hierarchy-fallback").inner_text()
    capture(page, report, f"03-hierarchy-{suffix}.png")
    page.get_by_test_id("graph-hierarchy-fallback").locator("ol > li > button").first.click()
    page.get_by_test_id("graph-relation-filter").select_option("all")
    page.get_by_placeholder("检索知识点").fill(str(fixture["source_title"]))
    source_button = page.get_by_role("button", name="打开来源正文", exact=True)
    assert source_button.is_enabled()
    source_button.click()
    page.wait_for_url(lambda url: "/knowledge/documents/" in url, timeout=30_000)
    page.locator(".reader-page").wait_for(state="visible", timeout=30_000)
    assert str(fixture["course_title"]) in page.locator(".reader-header").inner_text()
    report["checks"][f"source_deep_link_{suffix}"] = page.url


def verify_discovery(
    page: Page,
    base_url: str,
    report: dict[str, object],
    suffix: str,
    *,
    full_flow: bool,
) -> None:
    install_discovery_route(page, report)
    page.goto(f"{base_url}/knowledge/discover", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("knowledge-discovery-workspace").wait_for(state="visible")
    query = page.get_by_test_id("discovery-search-input")
    query.fill("机器学习公开教材")
    page.get_by_test_id("discovery-search-submit").click()
    page.get_by_text("开放机器学习课程讲义", exact=True).first.wait_for(state="visible")
    page.wait_for_timeout(500)
    assert page.get_by_role("link", name="打开原站").get_attribute("href") == SEARCH_URL
    preview = page.get_by_test_id("discovery-source-preview")
    for text in ("开放课程组织", "PDF", "未核验", "复杂公式与表格需要复核"):
        assert text in preview.inner_text()
    assert_visual_contract(page, report, f"discovery_result_{suffix}", ".discovery-workspace", "discovery")
    capture(page, report, f"04-discovery-result-{suffix}.png")

    if not full_flow:
        page.get_by_role("tab", name="我的候选 1", exact=True).click()
        candidate_row = page.locator(".source-row").filter(has_text="开放机器学习课程讲义")
        candidate_row.get_by_role("button").first.click()
        assert "已撤回" in preview.inner_text()
        assert "不进入课程图谱、RAG 或资源生成" in preview.inner_text()
        query.fill("神经网络公开教材")
        page.get_by_test_id("discovery-search-submit").click()
        page.get_by_text("联网搜索没有完成", exact=True).wait_for(state="visible")
        assert query.input_value() == "神经网络公开教材"
        assert page.get_by_role("tab", name="我的候选 1", exact=True).get_attribute("aria-selected") == "true"
        assert "已撤回" in preview.inner_text()
        assert_visual_contract(page, report, f"discovery_failure_{suffix}", ".discovery-workspace", "discovery")
        capture(page, report, f"06-discovery-failure-retained-{suffix}.png")
        return

    result_row = page.locator(".source-row").filter(has_text="开放机器学习课程讲义")
    save_button = result_row.get_by_role("button", name="保存为候选", exact=True)
    save_button.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    save_button.click()
    page.wait_for_timeout(1_000)
    admit = page.get_by_test_id("candidate-admit")
    if admit.count() == 0:
        report["checks"][f"after_save_debug_{suffix}"] = {
            "tabs": page.get_by_role("tab").all_inner_texts(),
            "selected_tabs": page.locator('[role="tab"][aria-selected="true"]').all_inner_texts(),
            "results_text": page.locator(".source-results").inner_text(),
            "preview_text": preview.inner_text(),
        }
        capture(page, report, f"05-after-save-debug-{suffix}.png")
        raise AssertionError(report["checks"][f"after_save_debug_{suffix}"])
    admit.wait_for(state="visible")
    assert page.get_by_role("tab", name="我的候选 1", exact=True).get_attribute("aria-selected") == "true"
    assert "开放机器学习课程讲义" in preview.inner_text()
    report["checks"][f"save_notice_visible_{suffix}"] = page.get_by_text(
        "已保存到候选区。请核对许可与用途后再决定是否准入。", exact=True
    ).count() > 0
    assert admit.is_disabled()
    assert "许可未确认" in preview.inner_text()
    page.get_by_label("作者或机构").fill("开放课程组织")
    page.get_by_test_id("candidate-license-select").select_option("open_permissive")
    page.get_by_label("许可原文或名称").fill("CC BY 4.0")
    page.get_by_label("允许用途").fill("允许个人学习引用并保留署名")
    page.get_by_label("可信等级").select_option("source_declared")
    assert admit.is_enabled()
    admit.click()
    page.get_by_text("已准入为个人候选参考。它仍不属于权威课程，也不会被资源生成引用。", exact=True).wait_for(state="visible")
    page.get_by_text("个人参考版本", exact=False).wait_for(state="visible")
    assert "不进入课程图谱、RAG 或资源生成" in preview.inner_text()
    capture(page, report, f"05-personal-admission-{suffix}.png")

    page.get_by_role("button", name="撤回个人参考", exact=True).click()
    page.get_by_text("个人参考已撤回。历史审核记录保留，但不会继续作为可用来源。", exact=True).wait_for(state="visible")
    assert "已撤回" in preview.inner_text()

    query.fill("神经网络公开教材")
    page.get_by_test_id("discovery-search-submit").click()
    page.get_by_text("联网搜索没有完成", exact=True).wait_for(state="visible")
    assert query.input_value() == "神经网络公开教材"
    assert page.get_by_role("tab", name="我的候选 1", exact=True).get_attribute("aria-selected") == "true"
    assert page.get_by_text("开放机器学习课程讲义", exact=True).first.is_visible()
    assert "已撤回" in page.get_by_test_id("discovery-source-preview").inner_text()
    assert_visual_contract(page, report, f"discovery_failure_{suffix}", ".discovery-workspace", "discovery")
    capture(page, report, f"06-discovery-failure-retained-{suffix}.png")


def verify_profile_compatibility(page: Page, base_url: str, report: dict[str, object], suffix: str) -> None:
    page.goto(f"{base_url}/profile/learning", wait_until="networkidle", timeout=60_000)
    graph = page.get_by_test_id("profile-knowledge-map")
    graph.wait_for(state="visible", timeout=30_000)
    graph.locator("canvas").wait_for(state="visible", timeout=30_000)
    assert page.get_by_role("button", name="重置视图", exact=True).is_visible()
    assert page.get_by_role("button", name="关系投影", exact=True).count() == 0
    assert page.get_by_text("双曲圆盘", exact=True).count() == 0
    capture(page, report, f"07-profile-protected-{suffix}.png")


def run_viewport(
    browser,
    viewport: tuple[int, int],
    base_url: str,
    fixture: dict[str, object],
    report: dict[str, object],
) -> None:
    suffix = f"{viewport[0]}x{viewport[1]}"
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    page = context.new_page()
    page_diagnostics(page, report)
    base.login(page, base_url)
    verify_graph(page, base_url, fixture, report, suffix)
    verify_discovery(page, base_url, report, suffix, full_flow=viewport == (1440, 900))
    verify_profile_compatibility(page, base_url, report, suffix)
    context.close()


def run() -> dict[str, object]:
    output_resolved = OUTPUT_DIR.resolve()
    if not output_resolved.is_relative_to(ROOT.resolve()):
        raise RuntimeError(f"refusing to clear evidence outside workspace: {output_resolved}")
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = 9012
    base.COURSE_ID = COURSE_ID
    base.clear_output()
    db_path = OUTPUT_DIR / "f7_t03.sqlite3"
    port = base.free_port()
    env = base.runtime_env(db_path, port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "f7-t03-isolated-secret"
    env["EDUMATRIX_SANDBOX_MODE"] = "disabled"
    fixture = seed_fixture(env)
    process: subprocess.Popen | None = None
    report: dict[str, object] = {
        "schema_version": "f7-t03.graph-admission-desktop.v1",
        "status": "running",
        "viewports": [[1440, 900], [1366, 768]],
        "isolated_database": str(db_path),
        "screenshots": [],
        "visual": {},
        "checks": {},
        "expected_injected_failures": [],
        "expected_injected_console": [],
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "external_model_called": False,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        process = base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for viewport in ((1440, 900), (1366, 768)):
                run_viewport(browser, viewport, base_url, fixture, report)
            browser.close()

        state = database_state(db_path, str(fixture["owner_public_id"]))
        report["database"] = state
        assert state["protected_counts"] == fixture["initial_counts"], {
            "browsing_or_admission_mutated_protected_state": {
                "before": fixture["initial_counts"],
                "after": state["protected_counts"],
            }
        }
        assert len(state["candidates"]) == 1, state
        candidate = state["candidates"][0]
        assert candidate["review_status"] == "withdrawn", candidate
        assert candidate["imported_version"].endswith("-v1"), candidate
        assert candidate["license_status"] == "open_permissive", candidate
        assert candidate["trust_level"] == "source_declared", candidate
        assert state["integrity"] == "ok", state
        assert state["foreign_key_violations"] == 0, state
        assert len(report["expected_injected_failures"]) == 2, report["expected_injected_failures"]
        assert len(report["expected_injected_console"]) <= 2, report["expected_injected_console"]
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
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
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
                {"schema_version": "f7-t03.evidence-manifest.v1", "files": files},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
