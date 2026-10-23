from __future__ import annotations

import json
import os
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("EDUMATRIX_RUN_BROWSER") != "1",
    reason="B34 browser evidence is an explicit opt-in check",
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B34" / "browser"


class _SpaHandler(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        requested = Path(self.directory) / parsed.path.lstrip("/")
        if not requested.is_file():
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, _format, *_args):
        return


@contextmanager
def _server():
    dist = ROOT / "frontend" / "dist"
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


def _hierarchy():
    return [
        {"nodeId": "legacy-node-1", "parentNodeId": None, "label": "旧版优化算法导图", "depth": 0},
        {"nodeId": "legacy-node-2", "parentNodeId": "legacy-node-1", "label": "梯度下降", "depth": 1},
        {"nodeId": "legacy-node-3", "parentNodeId": "legacy-node-2", "label": "学习率", "depth": 2},
    ]


def _projection(*, invalid: bool = False):
    hierarchy = _hierarchy()
    if invalid:
        return {
            "schema_version": "f5.mindmap-projection.v1",
            "content_schema_version": None,
            "mode": "invalid_structured",
            "content_format": "json",
            "source_refs": [],
            "canonical_binding": {
                "schema_version": "edumatrix.canonical-resource-binding.v1",
                "artifact_id": "b34-invalid",
                "artifact_version_id": "b34-invalid-v1",
                "artifact_version_number": 1,
                "resource_type": "mind_map",
                "course_id": "course-b34",
                "source_ref_ids": [],
                "source_refs": [],
                "source_status": "unknown",
            },
            "linked_resource_bindings": [],
            "linked_resources": [],
            "structured": None,
            "legacy": None,
            "invalid": {"raw_content": "{bad", "hierarchy": hierarchy, "error_code": "mindmap_content_incomplete", "render_profile": "legacy-compatible-v1"},
            "source_readiness": {"recorded": False, "available": False, "publishable": False, "reason": "导图结构不完整，修复节点关系后才能使用完整画布。"},
            "warnings": ["当前思维导图的节点层级或关系不完整，已切换为安全阅读状态。"],
        }
    return {
        "schema_version": "f5.mindmap-projection.v1",
        "content_schema_version": None,
        "mode": "legacy_markdown",
        "content_format": "markdown",
        "source_refs": [],
        "canonical_binding": {
            "schema_version": "edumatrix.canonical-resource-binding.v1",
            "artifact_id": "b34-legacy",
            "artifact_version_id": "b34-legacy-v1",
            "artifact_version_number": 1,
            "resource_type": "mind_map",
            "course_id": "course-b34",
            "source_ref_ids": [],
            "source_refs": [],
            "source_status": "unknown",
        },
        "linked_resources": [],
        "structured": None,
        "legacy": {
            "title": "旧版优化算法导图",
            "markdown": "# 旧版优化算法导图\n- 梯度下降\n  - 学习率",
            "hierarchy": hierarchy,
            "render_profile": "legacy-compatible-v1",
        },
        "source_readiness": {"recorded": False, "available": False, "publishable": False, "reason": "未记录来源，当前导图只能作为未发布草稿查看。"},
        "warnings": ["这是旧版 Markdown 导图的兼容视图，系统不会补造节点关系、掌握区间或关联资源。"],
    }


def _detail(resource_id: str):
    invalid = resource_id == "b34-invalid"
    projection = _projection(invalid=invalid)
    return {
        "id": resource_id,
        "title": "待修复导图" if invalid else "旧版优化算法导图",
        "lock_version": 1,
        "catalog": {"type": "mind_map", "course": {"id": "course-b34", "title": "机器学习基础"}, "knowledge_point": {"id": "kp-b34", "title": "优化算法"}},
        "mindmap": {
            "current_version_id": projection["canonical_binding"]["artifact_version_id"],
            "current": projection,
            "versions": [{"id": projection["canonical_binding"]["artifact_version_id"], "number": 1, "content_format": projection["content_format"], "content_hash": "b" * 64, "projection": projection}],
        },
    }


def test_legacy_canvas_is_visible_and_keyboard_operable_at_two_desktop_sizes():
    from playwright.sync_api import sync_playwright

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    reports = []
    with _server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
                context.add_init_script(
                    "localStorage.setItem('edumatrix_token','b34-browser-token');"
                    "localStorage.setItem('edumatrix_role','student');"
                    "localStorage.setItem('edumatrix_student_id','b34-browser');"
                    "localStorage.setItem('edumatrix_onboarded','true');"
                )
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))

                def handle(route):
                    parsed = urlparse(route.request.url)
                    if parsed.path.endswith("/auth/me"):
                        route.fulfill(status=200, content_type="application/json", body=json.dumps({"public_id": "b34-browser", "username": "b34", "display_name": "B34", "role": "student"}))
                    elif parsed.path.endswith("/v1/m5/resources/b34-legacy"):
                        route.fulfill(status=200, content_type="application/json", body=json.dumps(_detail("b34-legacy"), ensure_ascii=False))
                    elif parsed.path.endswith("/v1/m5/resources/b34-invalid"):
                        route.fulfill(status=200, content_type="application/json", body=json.dumps(_detail("b34-invalid"), ensure_ascii=False))
                    elif parsed.path.endswith("/v1/m5/context/resolve"):
                        route.fulfill(status=200, content_type="application/json", body=json.dumps({"context": {"courseId": "course-b34"}, "course": {"id": "course-b34", "title": "机器学习基础"}}, ensure_ascii=False))
                    else:
                        route.fulfill(status=200, content_type="application/json", body="{}")

                page.route("**/api/**", handle)
                page.goto(f"{base_url}/workspace/resources/mindmaps/b34-legacy?course_id=course-b34", wait_until="networkidle")
                page.get_by_test_id("mindmap-workspace").wait_for(state="visible")
                page.get_by_text("旧版兼容画布：仅复用旧导图的布局与缩进解析", exact=False).wait_for(state="visible")
                page.get_by_test_id("mindmap-hierarchy-fallback").wait_for(state="visible")
                assert page.locator(".mindmap-node").count() >= 2

                node = page.locator(".mindmap-node").nth(1)
                node.focus()
                assert node.evaluate("element => document.activeElement === element")
                node.press("Enter")
                page.get_by_role("heading", name="梯度下降", exact=True).wait_for(state="visible")
                page.get_by_role("button", name="折叠全部分支").click()
                page.get_by_role("button", name="展开全部分支").click()
                page.screenshot(path=str(EVIDENCE / f"legacy-{width}x{height}.png"), full_page=True, animations="disabled")

                geometry = page.evaluate("""() => ({
                  viewport: [innerWidth, innerHeight],
                  documentWidth: document.documentElement.scrollWidth,
                  bodyWidth: document.body.scrollWidth,
                  canvasLeft: document.querySelector('.canvas-wrap')?.getBoundingClientRect().left,
                  canvasRight: document.querySelector('.canvas-wrap')?.getBoundingClientRect().right,
                  compatibility: Boolean(document.querySelector('.compatibility-note')),
                })""")
                assert geometry["documentWidth"] <= width + 1, geometry
                assert geometry["bodyWidth"] <= width + 1, geometry
                assert geometry["canvasLeft"] >= -1 and geometry["canvasRight"] <= width + 1, geometry
                assert geometry["compatibility"] is True
                assert not errors, errors
                reports.append(geometry)
                context.close()
        finally:
            browser.close()
    (EVIDENCE / "browser-report.json").write_text(json.dumps({"task_id": "P1-B34", "result": "passed", "viewports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
