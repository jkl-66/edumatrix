from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.test_acceptance_p1_b28_browser import _frontend_server
from tests.test_acceptance_p1_b29_browser import _graph_fixture


pytestmark = pytest.mark.skipif(
    os.getenv("EDUMATRIX_RUN_BROWSER") != "1",
    reason="Course graph UI cleanup browser evidence is an explicit opt-in check",
)


def test_course_graph_cleanup_removes_redundant_panel_and_preserves_views(tmp_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    course_id = "course-graph-ui-cleanup"
    payload = _graph_fixture(course_id)
    evidence = (
        Path(__file__).resolve().parents[1]
        / "outputs"
        / "原系统融合重构执行"
        / "evidence"
        / "custom_tasks"
        / "COURSE-GRAPH-UI-CLEANUP-01"
        / "browser"
    )
    evidence.mkdir(parents=True, exist_ok=True)
    reports = []

    with _frontend_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_init_script(
                    "localStorage.setItem('edumatrix_token', 'browser-token');"
                    "localStorage.setItem('edumatrix_role', 'student');"
                    "localStorage.setItem('edumatrix_onboarded', 'true');"
                )
                page = context.new_page()
                page_errors: list[str] = []
                failed_requests: list[str] = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.on(
                    "requestfailed",
                    lambda request: failed_requests.append(f"{request.method} {request.url}"),
                )

                def handle(route):
                    path = urlparse(route.request.url).path
                    if path.endswith("/api/auth/me"):
                        body = {
                            "public_id": "course-graph-cleanup-user",
                            "username": "course-graph-cleanup",
                            "display_name": "图谱清理验收",
                            "role": "student",
                        }
                    elif path.endswith(f"/api/knowledge/courses/{course_id}/graph"):
                        body = payload
                    elif path.endswith("/api/v1/m5/profile-summary"):
                        body = {"knowledge_graph": {"nodes": []}}
                    elif path.endswith("/api/health"):
                        body = {"status": "ok"}
                    else:
                        body = {}
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps(body, ensure_ascii=False),
                    )

                page.route("**/api/**", handle)
                page.goto(f"{base_url}/knowledge/graph/{course_id}", wait_until="networkidle")
                page.get_by_test_id("course-knowledge-graph-workspace").wait_for()
                page.get_by_test_id("course-graph-75-25-layout").wait_for()

                # The removed block must not leave a placeholder or duplicate pills.
                assert page.get_by_test_id("graph-layout-decision").count() == 0
                assert page.get_by_text("本次布局：", exact=False).count() == 0
                assert page.locator(".topic-cluster-strip").count() == 0
                assert page.get_by_test_id("graph-chapter-filter").is_visible()
                assert page.get_by_test_id("graph-relation-filter").is_visible()
                assert page.get_by_test_id("graph-cluster-filter").is_visible()

                page.screenshot(path=str(evidence / f"graph-clean-{width}x{height}.png"), full_page=True)

                page.get_by_role("button", name="关系投影").click()
                assert page.get_by_role("button", name="关系投影").get_attribute("aria-pressed") == "true"
                page.screenshot(path=str(evidence / f"graph-projection-{width}x{height}.png"), full_page=True)

                page.get_by_role("button", name="层级列表").click()
                page.get_by_test_id("graph-hierarchy-fallback").wait_for()
                page.screenshot(path=str(evidence / f"graph-hierarchy-{width}x{height}.png"), full_page=True)

                page.get_by_role("button", name="关系图").click()
                page.get_by_test_id("knowledge-graph-explorer").wait_for()
                search = page.get_by_role("searchbox", name="检索知识点")
                search.fill("节点与边")
                page.get_by_test_id("course-graph-overview").get_by_role("heading", name="节点与边").wait_for()
                page.screenshot(path=str(evidence / f"graph-selected-{width}x{height}.png"), full_page=True)

                layout = page.evaluate(
                    """() => ({
                      width: document.documentElement.scrollWidth,
                      bodyWidth: document.body.scrollWidth,
                      controlsBottom: document.querySelector('.graph-controls')?.getBoundingClientRect().bottom || 0,
                      graphTop: document.querySelector('[data-testid="course-graph-75-25-layout"]')?.getBoundingClientRect().top || 0,
                      graphVisible: Boolean(document.querySelector('[data-testid="knowledge-graph-explorer"] .chart')),
                    })"""
                )
                assert layout["width"] <= width + 1, layout
                assert layout["bodyWidth"] <= width + 1, layout
                assert layout["graphVisible"] is True, layout
                assert not page_errors, page_errors
                assert not failed_requests, failed_requests
                reports.append({"viewport": {"width": width, "height": height}, "layout": layout})
                context.close()
        finally:
            browser.close()

    (evidence / "browser-report.json").write_text(
        json.dumps(
            {
                "task_id": "COURSE-GRAPH-UI-CLEANUP-01",
                "status": "passed",
                "panel_removed": True,
                "reports": reports,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
