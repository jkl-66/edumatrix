import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.test_acceptance_p1_b28_browser import _frontend_server


pytestmark = pytest.mark.skipif(
    os.getenv("EDUMATRIX_RUN_BROWSER") != "1",
    reason="Course graph density browser evidence is an explicit opt-in check",
)


def _dense_hierarchical_fixture(course_id: str) -> dict:
    nodes = [
        {
            "id": f"course:{course_id}",
            "name": "人工智能与深度学习",
            "nodeType": "course",
            "category": 0,
            "categoryName": "课程",
            "sourceStatus": "course_scope",
        },
        {
            "id": "chapter:core",
            "name": "深度学习核心",
            "nodeType": "chapter",
            "category": 1,
            "categoryName": "章节",
            "chapterId": "chapter:core",
            "sourceStatus": "ready",
        },
    ]
    names = [
        "人工智能概览", "数据与特征", "向量与矩阵", "概率基础", "损失函数",
        "梯度下降", "自动微分", "线性回归", "逻辑回归", "多层感知机",
        "反向传播", "过拟合与正则化", "优化算法", "卷积神经网络", "池化操作",
        "循环神经网络", "序列建模", "注意力机制", "查询键值表示", "自注意力",
        "位置编码", "Transformer", "语言模型", "大语言模型",
    ]
    for index, name in enumerate(names):
        nodes.append(
            {
                "id": f"knowledge:kp-{index}",
                "name": name,
                "nodeType": "knowledge_point",
                "category": 2,
                "categoryName": "知识点",
                "knowledgePointId": f"kp-{index}",
                "chapterId": "chapter:core",
                "sourceStatus": "ready",
                "sourceDocumentId": "source:core",
                "sourceRefId": f"ref-{index}",
                "masteryStatus": "unknown",
                "masteryScore": 0.58 if index == 0 else None,
                "masteryEvidenceCount": 0,
                "topicClusterIds": ["cluster:core"],
                "importance": 1 if index in {0, 17, 21} else 0.5,
                "hierarchyDepth": index + 1,
                "isCurrentFocus": index == 0,
                "isBridgeNode": index in {10, 17, 21},
                "needsDetailExplanation": True,
            }
        )
    edges = [
        {
            "id": "contains-core",
            "source": f"course:{course_id}",
            "target": "chapter:core",
            "relationType": "contains",
            "label": "包含章节",
        }
    ]
    for index in range(len(names)):
        edges.append(
            {
                "id": f"teaches-{index}",
                "source": "chapter:core",
                "target": f"knowledge:kp-{index}",
                "relationType": "teaches",
                "label": "讲授",
            }
        )
        if index:
            edges.append(
                {
                    "id": f"prerequisite-{index}",
                    "source": f"knowledge:kp-{index - 1}",
                    "target": f"knowledge:kp-{index}",
                    "relationType": "prerequisite",
                    "label": "先修",
                }
            )
    return {
        "schemaVersion": "edumatrix.course-knowledge-graph.v2",
        "status": "ready",
        "course": {
            "id": course_id,
            "title": "人工智能与深度学习",
            "description": "密集分层图谱视觉验收",
            "version": "1",
            "manifestVersion": "1",
        },
        "categories": [{"name": "课程"}, {"name": "章节"}, {"name": "知识点"}],
        "nodes": nodes,
        "edges": edges,
        "hierarchy": [
            {
                "chapterId": "chapter:core",
                "title": "深度学习核心",
                "position": 1,
                "sourceDocumentId": "source:core",
                "sourceRefId": "ref-0",
                "knowledgePoints": [
                    {"id": f"kp-{index}", "title": name}
                    for index, name in enumerate(names)
                ],
            }
        ],
        "topicClusters": [
            {
                "id": "cluster:core",
                "title": "深度学习核心",
                "size": len(names),
                "memberNodeIds": [f"knowledge:kp-{index}" for index in range(len(names))],
                "centerNodeId": "knowledge:kp-0",
                "bridgeNodeIds": ["knowledge:kp-10", "knowledge:kp-17", "knowledge:kp-21"],
            }
        ],
        "layoutDecision": {
            "strategy": "hierarchical",
            "reason": "先修关系形成稳定的分层学习顺序。",
            "clusterCount": 1,
            "constraints": ["节点与标签不得重叠", "边不得穿过节点", "布局不得越界"],
            "supports": ["search", "filter", "focus", "collapse", "expand", "zoom", "pan"],
            "densityTier": "over_20",
            "nodeCount": len(nodes),
            "knowledgePointCount": len(names),
        },
        "statistics": {
            "chapterCount": 1,
            "knowledgePointCount": len(names),
            "sourceCount": 1,
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
        },
        "masterySnapshot": {"status": "not_available", "profileSnapshotId": None, "courseId": course_id},
        "authorityBoundary": "仅展示课程固定版本中的章节、知识点、先修和来源事实。",
        "availability": {"status": "ready", "readOnly": True, "version": "1", "manifestVersion": "1"},
    }


def _chart_handle(page):
    return page.evaluate(
        """() => {
          const root = document.querySelector('[data-testid="knowledge-graph-explorer"]');
          const chartDom = [root, ...(root ? root.querySelectorAll('*') : [])]
            .find((element) => element?.__edumatrixChartInstance);
          return Boolean(chartDom?.__edumatrixChartInstance);
        }"""
    )


def _chart_geometry(page) -> dict:
    return page.evaluate(
        """() => {
          const root = document.querySelector('[data-testid="knowledge-graph-explorer"]');
          const chartDom = [root, ...(root ? root.querySelectorAll('*') : [])]
            .find((element) => element?.__edumatrixChartInstance);
          const chart = chartDom?.__edumatrixChartInstance;
          if (!chart) return null;
          const option = chart.getOption();
          const series = option.series?.[0] || {};
          const data = series.data || [];
          const rect = chartDom.getBoundingClientRect();
          const points = data.map((item) => {
            const pixel = chart.convertToPixel({seriesIndex: 0}, [item.x, item.y]);
            return {id: String(item.id), name: String(item.name || ''), x: rect.left + pixel[0], y: rect.top + pixel[1], size: Number(item.symbolSize || 0)};
          });
          let minClearance = Number.POSITIVE_INFINITY;
          let closestPair = null;
          for (let i = 0; i < points.length; i += 1) {
            for (let j = i + 1; j < points.length; j += 1) {
              const distance = Math.hypot(points[i].x - points[j].x, points[i].y - points[j].y);
              const clearance = distance - (points[i].size + points[j].size) / 2;
              if (clearance < minClearance) {
                minClearance = clearance;
                closestPair = [points[i].id, points[j].id];
              }
            }
          }
          return {
            width: chart.getWidth(),
            height: chart.getHeight(),
            nodeCount: data.length,
            edgeCount: (series.edges || []).length,
            curveness: [series.lineStyle?.curveness ?? 0, ...(series.edges || []).map((edge) => edge.lineStyle?.curveness ?? 0)],
            labels: points.map((point) => point.name),
            minClearance,
            closestPair,
            points,
          };
        }"""
    )


def test_dense_graph_layout_is_small_straight_spaced_and_interactive(tmp_path: Path):
    from playwright.sync_api import sync_playwright

    course_id = "course-graph-layout-density"
    payload = _dense_hierarchical_fixture(course_id)
    evidence = (
        Path(__file__).resolve().parents[1]
        / "outputs"
        / "原系统融合重构执行"
        / "evidence"
        / "custom_tasks"
        / "COURSE-GRAPH-LAYOUT-DENSITY-01"
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
                page_errors = []
                failed_requests = []
                console_errors = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}"))
                page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

                def handle(route):
                    path = urlparse(route.request.url).path
                    if path.endswith("/api/auth/me"):
                        body = {
                            "public_id": "graph-density-user",
                            "username": "graph-density",
                            "display_name": "图谱密度验收",
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
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))

                page.route("**/api/**", handle)
                page.goto(f"{base_url}/knowledge/graph/{course_id}", wait_until="networkidle")
                page.get_by_test_id("knowledge-graph-explorer").wait_for()
                assert _chart_handle(page)
                page.locator(".chart").scroll_into_view_if_needed()
                page.screenshot(path=str(evidence / f"graph-collapsed-{width}x{height}.png"), full_page=True)

                # A real canvas click verifies the progressive disclosure
                # interaction. Search then expands the selected node's full
                # prerequisite chain without depending on an in-flight ECharts
                # animation moving the next click target.
                point = page.evaluate(
                    """(id) => {
                      const root = document.querySelector('[data-testid="knowledge-graph-explorer"]');
                      const chartDom = [root, ...(root ? root.querySelectorAll('*') : [])]
                        .find((element) => element?.__edumatrixChartInstance);
                      const chart = chartDom?.__edumatrixChartInstance;
                      const item = chart?.getOption().series?.[0]?.data?.find((entry) => String(entry.id) === id);
                      if (!chart || !item) return null;
                      const pixel = chart.convertToPixel({seriesIndex: 0}, [item.x, item.y]);
                      const rect = chartDom.getBoundingClientRect();
                      return {x: rect.left + pixel[0], y: rect.top + pixel[1]};
                    }""",
                    "knowledge:kp-0",
                )
                assert point is not None
                page.mouse.click(point["x"], point["y"])
                page.wait_for_timeout(700)
                page.screenshot(path=str(evidence / f"graph-expanded-first-{width}x{height}.png"), full_page=True)
                page.get_by_role("searchbox", name="检索知识点").fill("大语言模型")
                page.wait_for_timeout(700)
                blank = page.evaluate(
                    """() => {
                      const chart = document.querySelector('[data-testid="knowledge-graph-explorer"] .chart');
                      const rect = chart?.getBoundingClientRect();
                      return rect ? {x: rect.left + 24, y: rect.top + 500} : null;
                    }"""
                )
                assert blank is not None
                page.mouse.click(blank["x"], blank["y"])
                page.wait_for_timeout(250)

                geometry = _chart_geometry(page)
                assert geometry is not None
                assert geometry["nodeCount"] == len(payload["hierarchy"][0]["knowledgePoints"]), geometry
                assert all(label.strip() for label in geometry["labels"]), geometry
                assert geometry["minClearance"] >= 8, geometry
                assert all(abs(float(value)) < 1e-9 for value in geometry["curveness"]), geometry
                assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")

                page.screenshot(path=str(evidence / f"graph-expanded-{width}x{height}.png"), full_page=True)
                page.get_by_role("button", name="关系投影").click()
                page.get_by_role("button", name="关系投影").wait_for()
                page.screenshot(path=str(evidence / f"graph-projection-{width}x{height}.png"), full_page=True)
                page.get_by_role("button", name="关系图").click()
                page.get_by_role("searchbox", name="检索知识点").fill("Transformer")
                page.get_by_test_id("course-graph-overview").get_by_role("heading", name="Transformer").wait_for()
                page.screenshot(path=str(evidence / f"graph-selected-{width}x{height}.png"), full_page=True)

                assert not page_errors, page_errors
                assert not failed_requests, failed_requests
                assert not console_errors, console_errors
                reports.append({"viewport": {"width": width, "height": height}, "geometry": geometry})
                context.close()
        finally:
            browser.close()

    (evidence / "browser-report.json").write_text(
        json.dumps(
            {
                "task_id": "COURSE-GRAPH-LAYOUT-DENSITY-01",
                "status": "passed",
                "reports": reports,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
