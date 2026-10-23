from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.test_acceptance_p1_b28_browser import _frontend_server


pytestmark = pytest.mark.skipif(
    os.getenv("EDUMATRIX_RUN_BROWSER") != "1",
    reason="B29 browser evidence is an explicit opt-in check",
)


def _graph_fixture(course_id: str) -> dict:
    nodes = [
        {"id": f"course:{course_id}", "name": "数据结构课程", "nodeType": "course", "category": 0, "categoryName": "课程", "summary": "课程结构", "sourceStatus": "course_scope"},
        {"id": "chapter:a", "name": "结构基础", "nodeType": "chapter", "category": 1, "categoryName": "章节", "chapterId": "chapter:a", "sourceStatus": "ready"},
        {"id": "chapter:b", "name": "算法应用", "nodeType": "chapter", "category": 1, "categoryName": "章节", "chapterId": "chapter:b", "sourceStatus": "ready"},
    ]
    for index, (name, cluster, chapter) in enumerate((("节点与边", "cluster:1", "chapter:a"), ("树与图", "cluster:1", "chapter:a"), ("检索算法", "cluster:2", "chapter:b"))):
        nodes.append({
            "id": f"knowledge:kp-{index}", "name": name, "nodeType": "knowledge_point", "category": 2,
            "categoryName": "知识点", "knowledgePointId": f"kp-{index}", "chapterId": chapter,
            "sourceStatus": "ready", "sourceDocumentId": "source-1", "sourceRefId": f"ref-{index}",
            "masteryStatus": "unknown", "masteryScore": 0.4 if index == 0 else None,
            "masteryEvidenceCount": 0, "topicClusterIds": [cluster], "importance": 1 if index == 0 else 0.5,
            "hierarchyDepth": index + 1, "isCurrentFocus": index == 0, "isBridgeNode": index == 1,
            "needsDetailExplanation": True,
        })
    edges = [
        {"id": "contains-a", "source": f"course:{course_id}", "target": "chapter:a", "relationType": "contains", "label": "包含章节"},
        {"id": "contains-b", "source": f"course:{course_id}", "target": "chapter:b", "relationType": "contains", "label": "包含章节"},
        {"id": "teaches-a", "source": "chapter:a", "target": "knowledge:kp-0", "relationType": "teaches", "label": "讲授"},
        {"id": "teaches-b", "source": "chapter:a", "target": "knowledge:kp-1", "relationType": "teaches", "label": "讲授"},
        {"id": "teaches-c", "source": "chapter:b", "target": "knowledge:kp-2", "relationType": "teaches", "label": "讲授"},
        {"id": "prereq", "source": "knowledge:kp-0", "target": "knowledge:kp-1", "relationType": "prerequisite", "label": "先修"},
    ]
    return {
        "schemaVersion": "edumatrix.course-knowledge-graph.v2",
        "status": "ready",
        "course": {"id": course_id, "title": "数据结构课程", "description": "动态知识结构 fixture", "version": "1", "manifestVersion": "1"},
        "categories": [{"name": "课程"}, {"name": "章节"}, {"name": "知识点"}, {"name": "来源"}],
        "nodes": nodes, "edges": edges,
        "hierarchy": [{"chapterId": "chapter:a", "title": "结构基础", "position": 1, "sourceDocumentId": "source-1", "sourceRefId": "ref-0", "knowledgePoints": [{"id": "kp-0", "title": "节点与边"}, {"id": "kp-1", "title": "树与图"}]}, {"chapterId": "chapter:b", "title": "算法应用", "position": 2, "sourceDocumentId": "source-1", "sourceRefId": "ref-2", "knowledgePoints": [{"id": "kp-2", "title": "检索算法"}]}],
        "topicClusters": [{"id": "cluster:1", "title": "节点与边", "size": 2, "memberNodeIds": ["knowledge:kp-0", "knowledge:kp-1"], "centerNodeId": "knowledge:kp-0"}, {"id": "cluster:2", "title": "检索算法", "size": 1, "memberNodeIds": ["knowledge:kp-2"], "centerNodeId": "knowledge:kp-2"}],
        "layoutDecision": {"strategy": "dynamic_cluster", "reason": "当前数据形成两个主题簇，簇数由关系和章节归属决定。", "clusterCount": 2, "constraints": ["节点与标签不得重叠"], "supports": ["search", "filter", "focus", "collapse", "expand", "zoom", "pan"]},
        "statistics": {"chapterCount": 2, "knowledgePointCount": 3, "sourceCount": 1, "nodeCount": len(nodes), "edgeCount": len(edges)},
        "masterySnapshot": {"status": "not_available", "profileSnapshotId": None, "courseId": course_id},
        "authorityBoundary": "仅展示课程固定版本中的章节、知识点、先修和来源事实。",
    }


def _high_density_graph_fixture(course_id: str) -> dict:
    """Build a large, connected graph to exercise the local-focus renderer."""
    nodes = [
        {"id": f"course:{course_id}", "name": "高密度课程", "nodeType": "course", "category": 0, "categoryName": "课程", "sourceStatus": "course_scope"},
        {"id": "chapter:dense", "name": "高密度章节", "nodeType": "chapter", "category": 1, "categoryName": "章节", "chapterId": "chapter:dense", "sourceStatus": "ready"},
    ]
    for index in range(81):
        nodes.append({
            "id": f"knowledge:dense-{index}",
            "name": f"高密度知识点 {index}",
            "nodeType": "knowledge_point",
            "category": 2,
            "categoryName": "知识点",
            "knowledgePointId": f"dense-{index}",
            "chapterId": "chapter:dense",
            "sourceStatus": "ready",
            "sourceDocumentId": "source-dense",
            "sourceRefId": f"ref-dense-{index}",
            "masteryStatus": "unknown",
            "masteryScore": 0.4 if index == 0 else None,
            "masteryEvidenceCount": 0,
            "topicClusterIds": ["cluster:dense"],
            "importance": 1 if index == 0 else 0.5,
            "hierarchyDepth": index + 1,
            "isCurrentFocus": index == 0,
            "isBridgeNode": index in {0, 40},
            "needsDetailExplanation": True,
        })
    edges = [
        {"id": "contains-dense", "source": f"course:{course_id}", "target": "chapter:dense", "relationType": "contains", "label": "包含章节"},
    ]
    for index in range(81):
        edges.append({"id": f"teaches-dense-{index}", "source": "chapter:dense", "target": f"knowledge:dense-{index}", "relationType": "teaches", "label": "讲授"})
        if index:
            edges.append({"id": f"prereq-dense-{index}", "source": f"knowledge:dense-{index - 1}", "target": f"knowledge:dense-{index}", "relationType": "prerequisite", "label": "先修"})
    return {
        "schemaVersion": "edumatrix.course-knowledge-graph.v2",
        "status": "ready",
        "course": {"id": course_id, "title": "高密度课程", "description": "高密度布局 fixture", "version": "1", "manifestVersion": "1"},
        "categories": [{"name": "课程"}, {"name": "章节"}, {"name": "知识点"}],
        "nodes": nodes,
        "edges": edges,
        "hierarchy": [{"chapterId": "chapter:dense", "title": "高密度章节", "position": 1, "sourceDocumentId": "source-dense", "sourceRefId": "ref-dense-0", "knowledgePoints": [{"id": f"dense-{index}", "title": f"高密度知识点 {index}"} for index in range(81)]}],
        "topicClusters": [{"id": "cluster:dense", "title": "高密度知识点 0", "size": 81, "memberNodeIds": [f"knowledge:dense-{index}" for index in range(81)], "centerNodeId": "knowledge:dense-0", "bridgeNodeIds": ["knowledge:dense-0", "knowledge:dense-40"]}],
        "layoutDecision": {"strategy": "local_focus", "reason": "高密度局部聚焦 fixture。", "clusterCount": 1, "constraints": ["节点与标签不得重叠", "边不得穿过节点", "布局不得越界"], "supports": ["search", "filter", "focus", "collapse", "expand", "zoom", "pan"], "densityTier": "over_80", "nodeCount": len(nodes), "knowledgePointCount": 81},
        "statistics": {"chapterCount": 1, "knowledgePointCount": 81, "sourceCount": 1, "nodeCount": len(nodes), "edgeCount": len(edges)},
        "masterySnapshot": {"status": "not_available", "profileSnapshotId": None, "courseId": course_id},
        "authorityBoundary": "仅展示课程固定版本中的章节、知识点、先修和来源事实。",
        "availability": {"status": "ready", "readOnly": True, "version": "1", "manifestVersion": "1", "message": "高密度 fixture 只读。"},
    }


def _canonical_graph_payload() -> dict:
    """Read the real flagship graph projection before driving the browser UI."""
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.api_test_helpers import auth_headers

    course_id = "course-machine-learning-foundations-v1"
    with TestClient(app) as client:
        headers = auth_headers(client, "b29_canonical_browser")
        response = client.get(f"/api/knowledge/courses/{course_id}/graph", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
    assert payload["status"] == "ready"
    assert payload["course"]["id"] == course_id
    assert payload["statistics"]["chapterCount"] >= 1
    assert payload["statistics"]["knowledgePointCount"] >= 1
    assert payload["statistics"]["nodeCount"] == len(payload["nodes"])
    assert payload["statistics"]["edgeCount"] == len(payload["edges"])
    return payload


def test_dynamic_graph_decision_clusters_and_spacing_two_desktop_viewports(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    course_id = "b29-browser-course"
    payload = _graph_fixture(course_id)
    reports = []
    evidence = Path(__file__).resolve().parents[1] / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B29"
    evidence.mkdir(parents=True, exist_ok=True)
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
                browser_errors = []
                page.on("pageerror", lambda error: browser_errors.append(str(error)))

                def handle(route):
                    path = urlparse(route.request.url).path
                    if path.endswith("/api/auth/me"):
                        body = {"public_id": "b29-browser-user", "username": "b29-browser", "display_name": "B29 浏览器验收", "role": "student"}
                    elif path.endswith(f"/api/knowledge/courses/{course_id}/graph"):
                        body = payload
                    elif path.endswith("/api/v1/m5/profile-summary"):
                        body = {"knowledge_graph": {"nodes": []}}
                    elif path.endswith("/api/health"):
                        body = {"status": "ok"}
                    else:
                        body = {}
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))

                page.route("**/api/**", handle)
                page.goto(f"{base_url}/knowledge/graph/{course_id}", wait_until="networkidle")
                page.get_by_test_id("course-knowledge-graph-workspace").wait_for()
                page.get_by_test_id("graph-layout-decision").wait_for()
                assert page.get_by_test_id("graph-readonly-note").is_visible()
                assert page.get_by_text("本次布局：dynamic_cluster").is_visible()
                assert page.get_by_test_id("graph-cluster-filter").is_visible()
                cluster_button = page.locator("[data-testid=graph-layout-decision] .topic-cluster-strip button").first
                cluster_button.click()
                assert cluster_button.get_attribute("aria-expanded") == "false"
                page.locator("[data-testid=graph-layout-decision] .topic-cluster-strip button").first.click()
                assert not browser_errors, browser_errors
                page.screenshot(path=str(evidence / f"{width}x{height}.png"), full_page=True)
                layout = page.evaluate("""() => ({
                  width: document.documentElement.scrollWidth,
                  bodyWidth: document.body.scrollWidth,
                  workspaceRight: document.querySelector('[data-testid=course-knowledge-graph-workspace]')?.getBoundingClientRect().right || 0,
                  smallText: [...document.querySelectorAll('[data-testid=course-knowledge-graph-workspace] *')].filter((el) => el.children.length === 0 && el.getClientRects().length && Number.parseFloat(getComputedStyle(el).fontSize) < 14).map((el) => el.textContent.trim())
                })""")
                assert layout["width"] <= width + 1, layout
                assert layout["bodyWidth"] <= width + 1, layout
                assert layout["workspaceRight"] <= width + 1, layout
                assert layout["smallText"] == [], layout
                reports.append({"viewport": {"width": width, "height": height}, "layout": layout, "page_errors": browser_errors})
                context.close()
        finally:
            browser.close()
    (evidence / "browser-report.json").write_text(json.dumps({"task_id": "ACCEPTANCE-FEEDBACK-P1-B29", "status": "passed", "viewports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")


def test_graph_state_matrix_surfaces_empty_failure_and_permission(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    course_id = "b29-state-course"
    payload = _graph_fixture(course_id)
    mode = {"value": "empty"}
    states = []
    evidence = Path(__file__).resolve().parents[1] / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B29"
    evidence.mkdir(parents=True, exist_ok=True)

    with _frontend_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_init_script(
                "localStorage.setItem('edumatrix_token', 'browser-token');"
                "localStorage.setItem('edumatrix_role', 'student');"
                "localStorage.setItem('edumatrix_onboarded', 'true');"
            )
            page = context.new_page()
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))

            def handle(route):
                path = urlparse(route.request.url).path
                if path.endswith("/api/auth/me"):
                    body = {"public_id": "b29-state-user", "username": "b29-state", "display_name": "B29 状态矩阵", "role": "student"}
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))
                    return
                if path.endswith(f"/api/knowledge/courses/{course_id}/graph"):
                    if mode["value"] == "failed":
                        route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "图谱服务暂时不可用"}, ensure_ascii=False))
                        return
                    if mode["value"] == "forbidden":
                        route.fulfill(status=403, content_type="application/json", body=json.dumps({"detail": "无权查看课程图谱"}, ensure_ascii=False))
                        return
                    if mode["value"] == "empty":
                        body = {
                            **payload,
                            "status": "empty",
                            "nodes": [],
                            "edges": [],
                            "hierarchy": [],
                            "topicClusters": [],
                            "layoutDecision": None,
                            "statistics": {"chapterCount": 0, "knowledgePointCount": 0, "sourceCount": 0, "nodeCount": 0, "edgeCount": 0},
                        }
                    else:
                        body = payload
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))
                    return
                if path.endswith("/api/v1/m5/profile-summary"):
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({"knowledge_graph": {"nodes": []}}, ensure_ascii=False))
                    return
                if path.endswith("/api/health"):
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({"status": "ok"}, ensure_ascii=False))
                    return
                route.fulfill(status=200, content_type="application/json", body="{}")

            page.route("**/api/**", handle)
            for state, expected in (
                ("empty", "当前课程还没有可展示的图谱"),
                ("failed", "课程知识图谱暂时无法打开"),
                ("forbidden", "当前账号没有查看这门课程图谱的权限。"),
            ):
                mode["value"] = state
                page.goto(f"{base_url}/knowledge/graph/{course_id}", wait_until="networkidle")
                assert page.get_by_text(expected).is_visible()
                states.append(state)

            mode["value"] = "ready"
            page.goto(f"{base_url}/knowledge/graph/{course_id}", wait_until="networkidle")
            page.get_by_test_id("graph-readonly-note").wait_for()
            assert page.get_by_text("本次布局：dynamic_cluster").is_visible()
            states.append("ready")
            assert not page_errors, page_errors
            context.close()
        finally:
            browser.close()

    (evidence / "state-matrix.json").write_text(
        json.dumps({"task_id": "ACCEPTANCE-FEEDBACK-P1-B29", "states": states, "page_errors": page_errors}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_canonical_graph_payload_drives_desktop_views_and_readonly_interactions():
    """Use canonical API data in the browser instead of a hand-built graph fixture."""
    from playwright.sync_api import sync_playwright

    course_id = "course-machine-learning-foundations-v1"
    payload = _canonical_graph_payload()
    source_node = next((node for node in payload["nodes"] if node.get("nodeType") == "source" and node.get("sourceDocumentId")), None)
    knowledge_node = next(node for node in payload["nodes"] if node.get("nodeType") == "knowledge_point")
    evidence = Path(__file__).resolve().parents[1] / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B29"
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
                browser_errors = []
                page.on("pageerror", lambda error: browser_errors.append(str(error)))

                def handle(route):
                    path = urlparse(route.request.url).path
                    if path.endswith("/api/auth/me"):
                        body = {"public_id": "b29-canonical-browser", "username": "b29_canonical_browser", "display_name": "B29 Canonical", "role": "student"}
                    elif path.endswith(f"/api/knowledge/courses/{course_id}/graph"):
                        body = payload
                    elif path.endswith("/api/v1/m5/profile-summary"):
                        body = {"knowledge_graph": {"nodes": []}}
                    elif path.endswith("/api/health"):
                        body = {"status": "ok"}
                    elif "/api/v1/document-reader/" in path:
                        body = {
                            "schema_version": "edumatrix.document-reader.v1",
                            "course": payload["course"],
                            "document": {"id": source_node["sourceDocumentId"], "title": source_node["name"], "file_type": "pdf", "content": "canonical source preview"},
                            "source_refs": [{"id": source_node.get("sourceRefId"), "location_label": source_node.get("locationLabel", "")}],
                        }
                    else:
                        body = {}
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))

                page.route("**/api/**", handle)
                page.goto(f"{base_url}/knowledge/graph/{course_id}", wait_until="networkidle")
                page.get_by_test_id("course-knowledge-graph-workspace").wait_for()
                page.get_by_test_id("graph-layout-decision").wait_for()
                assert page.get_by_test_id("graph-readonly-note").is_visible()
                assert page.get_by_test_id("graph-chapter-filter").is_visible()
                assert page.get_by_test_id("graph-relation-filter").is_visible()
                assert page.get_by_test_id("graph-cluster-filter").is_visible()

                search = page.get_by_role("searchbox", name="检索知识点")
                search.fill(knowledge_node["name"])
                assert page.get_by_test_id("course-graph-overview").get_by_role("heading", name=knowledge_node["name"]).is_visible()
                state_screenshots = {}
                selected_path = evidence / f"canonical-state-selected-{width}x{height}.png"
                page.screenshot(path=str(selected_path), full_page=True)
                state_screenshots["search_selected"] = selected_path.name
                source_navigation_available = False
                if source_node:
                    source_button = page.get_by_role("button", name="打开来源正文")
                    assert source_button.is_enabled()
                    source_navigation_available = True

                page.get_by_role("button", name="关系投影").click()
                assert page.get_by_role("button", name="关系投影").get_attribute("aria-pressed") == "true"
                projection_path = evidence / f"canonical-state-projection-{width}x{height}.png"
                page.screenshot(path=str(projection_path), full_page=True)
                state_screenshots["relationship_projection"] = projection_path.name
                page.get_by_role("button", name="层级列表").click()
                page.get_by_test_id("graph-hierarchy-fallback").wait_for()
                hierarchy_path = evidence / f"canonical-state-hierarchy-{width}x{height}.png"
                page.screenshot(path=str(hierarchy_path), full_page=True)
                state_screenshots["hierarchy_list"] = hierarchy_path.name
                page.get_by_role("button", name="关系图").click()
                page.get_by_test_id("knowledge-graph-explorer").wait_for()

                cluster_button = page.locator("[data-testid=graph-layout-decision] .topic-cluster-strip button").first
                cluster_button.click()
                assert cluster_button.get_attribute("aria-expanded") == "false"
                page.locator("[data-testid=graph-layout-decision] .topic-cluster-strip button").first.click()
                assert cluster_button.get_attribute("aria-expanded") == "true"

                page.get_by_role("button", name="重置视图").click()
                assert not page.get_by_role("heading", name=knowledge_node["name"]).is_visible()
                page.get_by_test_id("graph-chapter-filter").focus()
                page.keyboard.press("ArrowDown")
                layout = page.evaluate("""() => ({
                    width: document.documentElement.scrollWidth,
                    bodyWidth: document.body.scrollWidth,
                    workspaceRight: document.querySelector('[data-testid=course-knowledge-graph-workspace]')?.getBoundingClientRect().right || 0,
                    smallText: [...document.querySelectorAll('[data-testid=course-knowledge-graph-workspace] *')]
                      .filter((el) => el.children.length === 0 && el.getClientRects().length && Number.parseFloat(getComputedStyle(el).fontSize) < 14)
                      .map((el) => el.textContent.trim()),
                })""")
                assert layout["width"] <= width + 1, layout
                assert layout["bodyWidth"] <= width + 1, layout
                assert layout["workspaceRight"] <= width + 1, layout
                assert layout["smallText"] == [], layout
                assert not browser_errors, browser_errors
                reset_path = evidence / f"canonical-state-reset-{width}x{height}.png"
                page.screenshot(path=str(reset_path), full_page=True)
                state_screenshots["reset"] = reset_path.name
                page.screenshot(path=str(evidence / f"canonical-{width}x{height}.png"), full_page=True)
                reports.append({"viewport": {"width": width, "height": height}, "layout": layout, "node_count": len(payload["nodes"]), "edge_count": len(payload["edges"]), "cluster_count": len(payload.get("topicClusters") or []), "source_navigation_available": source_navigation_available, "state_screenshots": state_screenshots, "page_errors": browser_errors})
                context.close()
        finally:
            browser.close()
    (evidence / "canonical-browser-report.json").write_text(
        json.dumps({"task_id": "ACCEPTANCE-FEEDBACK-P1-B29", "course_id": course_id, "status": "passed", "source": "GET /api/knowledge/courses/{course_id}/graph", "reports": reports}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_high_density_local_focus_keeps_chart_nodes_separated_and_in_bounds():
    """Verify the rendered ECharts option, not just the backend density label."""
    from playwright.sync_api import sync_playwright

    course_id = "b29-high-density-course"
    payload = _high_density_graph_fixture(course_id)
    evidence = Path(__file__).resolve().parents[1] / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B29"
    evidence.mkdir(parents=True, exist_ok=True)
    with _frontend_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_init_script(
                "localStorage.setItem('edumatrix_token', 'browser-token');"
                "localStorage.setItem('edumatrix_role', 'student');"
                "localStorage.setItem('edumatrix_onboarded', 'true');"
            )
            page = context.new_page()
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))

            def handle(route):
                path = urlparse(route.request.url).path
                if path.endswith("/api/auth/me"):
                    body = {"public_id": "b29-density-user", "username": "b29-density", "display_name": "B29 密度验收", "role": "student"}
                elif path.endswith(f"/api/knowledge/courses/{course_id}/graph"):
                    body = payload
                elif path.endswith("/api/v1/m5/profile-summary"):
                    body = {"knowledge_graph": {"nodes": []}}
                elif path.endswith("/api/health"):
                    body = {"status": "ok"}
                else:
                    body = {}
                route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))

            page.route("**/api/**", handle)
            page.goto(f"{base_url}/knowledge/graph/{course_id}", wait_until="networkidle")
            page.get_by_test_id("knowledge-graph-explorer").wait_for()
            assert page.get_by_text("本次布局：local_focus").is_visible()
            chart = page.evaluate("""() => {
              const root = document.querySelector('[data-testid="knowledge-graph-explorer"]');
              const chartDom = [root, ...(root ? root.querySelectorAll('*') : [])]
                .find((element) => element?.__edumatrixChartInstance);
              const instance = chartDom?.__edumatrixChartInstance;
              if (!instance) return null;
              const option = instance.getOption();
              return { width: instance.getWidth(), height: instance.getHeight(), series: option.series || [] };
            }""")
            assert chart is not None and "series" in chart, chart
            series = chart["series"][0]
            data = series["data"]
            assert len(data) == len(payload["nodes"]), {"data_count": len(data), "node_count": len(payload["nodes"])}
            points = [(str(item.get("id")), float(item["x"]), float(item["y"]), float(item.get("symbolSize") or 0)) for item in data]
            assert all(-500 <= x <= 500 and -240 <= y <= 240 for _, x, y, _ in points), points[:3]
            min_clearance = min(
                ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5 - max(size1, size2) / 2
                for index, (_, x1, y1, size1) in enumerate(points)
                for _, x2, y2, size2 in points[index + 1:]
            )
            closest_pair = None
            for index, left in enumerate(points):
                for right in points[index + 1:]:
                    _, x1, y1, size1 = left
                    _, x2, y2, size2 = right
                    clearance = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5 - max(size1, size2) / 2
                    candidate = (clearance, left[0], right[0])
                    if closest_pair is None or candidate[0] < closest_pair[0]:
                        closest_pair = candidate
            assert min_clearance >= 8, {"min_clearance": min_clearance, "closest_pair": closest_pair, "points": points[:5]}
            assert not page_errors, page_errors
            page.screenshot(path=str(evidence / "canonical-high-density-local-focus-1440x900.png"), full_page=True)
            (evidence / "high-density-layout-report.json").write_text(
                json.dumps({"task_id": "ACCEPTANCE-FEEDBACK-P1-B29", "strategy": "local_focus", "node_count": len(data), "min_clearance": min_clearance, "chart": {"width": chart["width"], "height": chart["height"]}, "page_errors": page_errors}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            context.close()
        finally:
            browser.close()
