from __future__ import annotations

import json
import os
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("EDUMATRIX_RUN_BROWSER") != "1",
    reason="B27 browser evidence is an explicit opt-in check",
)


class _SpaHandler(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib handler hook
        parsed = urlparse(self.path)
        requested = Path(self.directory) / parsed.path.lstrip("/")
        if parsed.path.startswith("/api/"):
            self.send_error(404)
            return
        if not requested.is_file():
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, _format, *_args):
        return


@contextmanager
def _frontend_server():
    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if not (dist / "index.html").is_file():
        pytest.fail("frontend/dist/index.html 不存在，请先运行 npm run build")

    def handler(*args, **kwargs):
        return _SpaHandler(*args, directory=str(dist), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def _candidate_payload():
    return {
        "id": "p1-b27-browser-candidate",
        "query": "画像驱动联网推荐",
        "title": "卷积公开讲义",
        "url": "https://example.test/conv.pdf",
        "sourceDomain": "example.test",
        "authorOrOrganization": "example.test",
        "fileFormat": "pdf",
        "formatLabel": "PDF",
        "formatConfidence": "high",
        "formatDetection": "url_extension",
        "snippet": "公开讲义",
        "licenseStatus": "unknown",
        "licenseText": "",
        "usageHint": "",
        "parsingImpact": {"summary": "可解析正文，需核对许可。"},
        "processingPipeline": {
            "download": {"status": "not_started", "message": "尚未下载"},
            "parse": {"status": "not_started", "message": "尚未解析"},
            "citation": {"status": "blocked", "message": "等待解析和来源核验"},
            "admission": {"status": "candidate", "message": "尚未准入"},
            "overall_status": "candidate",
            "retryable": True,
            "failure": None,
        },
        "processingStatus": "candidate",
        "citationStatus": "blocked",
        "retryable": True,
        "failure": None,
        "trustLevel": "unverified",
        "reviewStatus": "pending_review",
        "importedVersion": None,
        "importResult": {},
        "canAdmit": False,
        "blockers": ["许可未确认", "用途说明缺失"],
        "authorityScope": "candidate_only",
        "authoritative": False,
        "resourceGenerationEligible": False,
        "createdAt": "2026-08-26T00:00:00",
        "updatedAt": "2026-08-26T00:00:00",
    }


def _install_api_mocks(page):
    state = {"search_calls": 0, "saved": False}
    courses = [
        {"id": "browser-course-conv", "title": "机器学习基础", "can_manage": True, "visibility": "private"},
        {"id": "browser-course-reg", "title": "机器学习进阶", "can_manage": True, "visibility": "private"},
    ]

    def respond(route, payload, status=200):
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    def handle(route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        params = parse_qs(parsed.query)
        if path.endswith("/api/auth/me"):
            respond(route, {"public_id": "browser-user", "username": "browser", "display_name": "浏览器验收", "role": "student"})
            return
        if path.endswith("/api/knowledge/courses"):
            respond(route, {"schema_version": "edumatrix.knowledge-course-shelf.v1", "shelf": courses, "recommendations": []})
            return
        if path.endswith("/api/knowledge/discovery/candidates") and request.method == "GET":
            respond(route, {"schemaVersion": "edumatrix.web-source-candidates.v1", "items": [_candidate_payload()] if state["saved"] else []})
            return
        if path.endswith("/api/knowledge/discovery/candidates") and request.method == "POST":
            state["saved"] = True
            respond(route, {"created": True, "candidate": _candidate_payload()})
            return
        if path.endswith("/api/knowledge/discovery/search"):
            state["search_calls"] += 1
            if "失败重试" in params.get("q", [""])[0] and state["search_calls"] == 2:
                respond(route, {"detail": {"message": "联网搜索暂时不可用，搜索词已保留，请重试。"}}, status=503)
                return
            course_id = params.get("course_id", [courses[0]["id"]])[0]
            course = next((item for item in courses if item["id"] == course_id), courses[0])
            focus = "卷积" if course["id"] == courses[0]["id"] else "正则化"
            generated = f"{course['title']} {focus} 公开讲义"
            items = [
                {"id": f"result-{focus}", "title": f"{focus}公开讲义", "url": "https://example.test/conv.pdf", "snippet": f"{focus}课程资料", "sourceDomain": "example.test", "authorOrOrganization": "example.test", "fileFormat": "pdf", "formatLabel": "PDF", "formatConfidence": "high", "formatDetection": "url_extension", "licenseStatus": "unknown", "licenseText": "", "usageHint": "请核对许可", "parsingImpact": {"summary": "可解析正文"}, "trustLevel": "unverified", "reviewStatus": "not_saved", "importedVersion": None, "authoritative": False, "relevanceScore": 0.72, "matchedFocusTerms": [focus], "recommendationReason": f"命中画像/课程关注词：{focus}。"},
                {"id": "result-common", "title": "通用课程说明", "url": "https://example.test/common", "snippet": "课程概览", "sourceDomain": "example.test", "authorOrOrganization": "example.test", "fileFormat": "html", "formatLabel": "HTML 网页", "formatConfidence": "unknown", "formatDetection": "awaiting_content_type_or_signature", "licenseStatus": "unknown", "licenseText": "", "usageHint": "请核对许可", "parsingImpact": {"summary": "可提取正文"}, "trustLevel": "unverified", "reviewStatus": "not_saved", "importedVersion": None, "authoritative": False, "relevanceScore": 0.12, "matchedFocusTerms": [], "recommendationReason": "保留为公开搜索候选，仍需用户核对来源和许可。"},
            ]
            respond(route, {
                "schemaVersion": "edumatrix.web-source-discovery.v1",
                "status": "ready",
                "query": params.get("q", [""])[0],
                "generatedQuery": generated,
                "queryPlan": {"query": generated, "focus_terms": [focus], "rationale": "按当前课程画像检索公开来源", "model": {"provider": "openai", "model": "deepseek-v4-flash", "thinking": "enabled", "reasoning_effort": "max", "allow_fallback": False}, "source": "profile_snapshot"},
                "profileBasis": {"status": "available", "profileSnapshotId": "browser-profile", "profileVersion": "profile.continuous.v1", "courseId": course["id"], "courseTitle": course["title"], "courseGoals": ["掌握课程目标"], "learningGoals": [f"理解{focus}应用"], "weakDirections": [focus], "preferences": ["先看案例"], "timeBudget": "每周 3 小时"},
                "ranking": {"deduplicatedCount": 1, "scoredCount": 2},
                "items": items,
                "filteredResultCount": 0,
                "message": "",
                "authorityBoundary": "搜索结果只进入候选区；未经准入不会进入课程图谱、检索或资源生成。推荐本身不会改变 mastery/path。",
            })
            return
        respond(route, {})

    page.route("**/api/**", handle)
    return state


def _assert_layout(page, viewport_name: str, screenshot_dir: Path):
    page.screenshot(path=str(screenshot_dir / f"{viewport_name}.png"), full_page=True)
    layout = page.evaluate(
        """() => {
          const root = document.querySelector('[data-testid=knowledge-discovery-workspace]');
          const visible = [...document.querySelectorAll('[data-testid="knowledge-discovery-workspace"] *')]
            .filter((el) => el.getClientRects().length && el.textContent.trim());
          const smallText = visible.filter((el) => {
            const style = getComputedStyle(el);
            return el.children.length === 0 && Number.parseFloat(style.fontSize) < 14;
          }).map((el) => el.textContent.trim().slice(0, 40));
          return {
            viewportWidth: window.innerWidth,
            documentWidth: document.documentElement.scrollWidth,
            bodyWidth: document.body.scrollWidth,
            rootRight: root ? root.getBoundingClientRect().right : 0,
            smallText,
          };
        }"""
    )
    assert layout["documentWidth"] <= layout["viewportWidth"] + 1, layout
    assert layout["bodyWidth"] <= layout["viewportWidth"] + 1, layout
    assert layout["rootRight"] <= layout["viewportWidth"] + 1, layout
    assert layout["smallText"] == [], layout["smallText"]
    return layout


def test_profile_web_recommendation_two_desktop_viewports():
    from playwright.sync_api import sync_playwright

    screenshot_dir = Path(__file__).resolve().parents[1] / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B27"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    browser_report = []
    with _frontend_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height, name in ((1440, 900, "1440x900"), (1366, 768, "1366x768")):
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_init_script(
                    "localStorage.setItem('edumatrix_token', 'browser-token');"
                    "localStorage.setItem('edumatrix_role', 'student');"
                    "localStorage.setItem('edumatrix_onboarded', 'true');"
                )
                page = context.new_page()
                browser_errors = []
                page.on("pageerror", lambda error: browser_errors.append(str(error)))
                mock_state = _install_api_mocks(page)
                page.goto(f"{base_url}/knowledge/discover?course_id=browser-course-conv", wait_until="networkidle")
                page.get_by_test_id("discovery-course-select").wait_for()
                page.get_by_test_id("discovery-course-select").select_option("browser-course-conv")
                page.get_by_test_id("discovery-search-input").fill("请推荐课程资料")
                page.get_by_test_id("discovery-search-input").press("Enter")
                page.get_by_test_id("discovery-query-plan").wait_for()
                assert "deepseek-v4-flash" in page.get_by_test_id("discovery-query-plan").inner_text()
                assert "卷积" in page.get_by_test_id("discovery-query-plan").inner_text()
                with page.expect_response("**/api/knowledge/discovery/candidates") as save_response:
                    page.get_by_role("button", name="保存为候选").first.click()
                assert save_response.value.status == 200
                assert page.get_by_text("已保存到候选区").is_visible()

                page.get_by_test_id("discovery-search-input").fill("失败重试")
                page.get_by_test_id("discovery-search-input").press("Enter")
                page.get_by_text("联网搜索没有完成").wait_for()
                page.get_by_role("button", name="使用原搜索词重试").click()
                page.get_by_test_id("discovery-query-plan").wait_for()

                page.get_by_test_id("discovery-course-select").select_option("browser-course-reg")
                page.get_by_test_id("discovery-search-input").fill("专业资料")
                page.get_by_test_id("discovery-search-input").press("Enter")
                page.get_by_test_id("discovery-query-plan").wait_for()
                assert "正则化" in page.get_by_test_id("discovery-query-plan").inner_text()
                assert "机器学习进阶" in page.get_by_test_id("discovery-query-plan").inner_text()
                assert not browser_errors, browser_errors
                layout = _assert_layout(page, name, screenshot_dir)
                browser_report.append({
                    "viewport": {"name": name, "width": width, "height": height},
                    "url": page.url,
                    "saved_candidate": True,
                    "retry_completed": True,
                    "course_switch_query_verified": True,
                    "search_calls": mock_state["search_calls"],
                    "layout": layout,
                    "page_errors": browser_errors,
                })
                context.close()
        finally:
            browser.close()
    (screenshot_dir / "browser-report.json").write_text(
        json.dumps({"task_id": "ACCEPTANCE-FEEDBACK-P1-B27", "status": "passed", "viewports": browser_report}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
