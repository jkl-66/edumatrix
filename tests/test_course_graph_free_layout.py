import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

from tests.test_acceptance_p1_b28_browser import _frontend_server
from tests.test_course_graph_layout_density import _dense_hierarchical_fixture


pytestmark = pytest.mark.skipif(
    os.getenv("EDUMATRIX_RUN_BROWSER") != "1",
    reason="Course graph free-layout browser evidence is an explicit opt-in check",
)


def _chart_snapshot(page) -> dict:
    return page.evaluate(
        """() => {
          const root = document.querySelector('[data-testid="knowledge-graph-explorer"]');
          const chartDom = [root, ...(root ? root.querySelectorAll('*') : [])]
            .find((element) => element?.__edumatrixChartInstance);
          const chart = chartDom?.__edumatrixChartInstance;
          if (!chart) return null;
          const series = chart.getOption().series?.[0] || {};
          const data = series.data || [];
          const rect = chartDom.getBoundingClientRect();
          const points = data.map((item) => {
            const pixel = chart.convertToPixel({seriesIndex: 0}, [item.x, item.y]);
            return {
              id: String(item.id),
              name: String(item.name || ''),
              logicalX: Number(item.x),
              logicalY: Number(item.y),
              x: rect.left + pixel[0],
              y: rect.top + pixel[1],
              size: Number(item.symbolSize || 0),
            };
          });
          const pointById = new Map(points.map((point) => [point.id, point]));
          let minClearance = Number.POSITIVE_INFINITY;
          for (let leftIndex = 0; leftIndex < points.length; leftIndex += 1) {
            for (let rightIndex = leftIndex + 1; rightIndex < points.length; rightIndex += 1) {
              const left = points[leftIndex];
              const right = points[rightIndex];
              const distance = Math.hypot(left.x - right.x, left.y - right.y);
              minClearance = Math.min(minClearance, distance - (left.size + right.size) / 2);
            }
          }
          const angleBins = new Set();
          let horizontalEdges = 0;
          const segments = [];
          (series.edges || []).forEach((edge) => {
            const source = pointById.get(String(edge.source));
            const target = pointById.get(String(edge.target));
            if (!source || !target) return;
            segments.push({sourceId: source.id, targetId: target.id, source, target});
            let angle = Math.atan2(target.y - source.y, target.x - source.x);
            if (angle < 0) angle += Math.PI;
            if (angle >= Math.PI) angle -= Math.PI;
            angleBins.add(Math.round(angle / (Math.PI / 18)));
            if (Math.abs(Math.sin(angle)) < 0.12) horizontalEdges += 1;
          });
          const orientation = (a, b, c) =>
            (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
          let crossingCount = 0;
          for (let leftIndex = 0; leftIndex < segments.length; leftIndex += 1) {
            for (let rightIndex = leftIndex + 1; rightIndex < segments.length; rightIndex += 1) {
              const left = segments[leftIndex];
              const right = segments[rightIndex];
              if ([left.sourceId, left.targetId].some((id) => id === right.sourceId || id === right.targetId)) continue;
              const first = orientation(left.source, left.target, right.source);
              const second = orientation(left.source, left.target, right.target);
              const third = orientation(right.source, right.target, left.source);
              const fourth = orientation(right.source, right.target, left.target);
              if (first * second < 0 && third * fourth < 0) crossingCount += 1;
            }
          }
          const yBuckets = new Map();
          points.forEach((point) => {
            const bucket = Math.round(point.y / 12);
            yBuckets.set(bucket, (yBuckets.get(bucket) || 0) + 1);
          });
          return {
            width: chart.getWidth(),
            height: chart.getHeight(),
            nodeCount: points.length,
            edgeCount: (series.edges || []).length,
            points,
            minClearance,
            angleBinCount: angleBins.size,
            horizontalEdgeRatio: (series.edges || []).length ? horizontalEdges / series.edges.length : 0,
            crossingCount,
            largestRowBucket: Math.max(0, ...yBuckets.values()),
            curveness: [
              series.lineStyle?.curveness ?? 0,
              ...(series.edges || []).map((edge) => edge.lineStyle?.curveness ?? 0),
            ],
          };
        }"""
    )


def _click_chart_node(page, node_id: str) -> None:
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
        node_id,
    )
    assert point is not None, node_id
    page.mouse.click(point["x"], point["y"])
    page.wait_for_timeout(90)


def test_dense_graph_uses_stable_free_layout_with_readable_straight_edges() -> None:
    from playwright.sync_api import sync_playwright

    course_id = "course-graph-free-layout"
    payload = _dense_hierarchical_fixture(course_id)
    evidence = (
        Path(__file__).resolve().parents[1]
        / "outputs"
        / "原系统融合重构执行"
        / "evidence"
        / "custom_tasks"
        / "COURSE-GRAPH-FREE-LAYOUT-01"
        / "browser"
    )
    evidence.mkdir(parents=True, exist_ok=True)
    reports = []

    with _frontend_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    reduced_motion="reduce",
                )
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
                            "public_id": "graph-free-layout-user",
                            "username": "graph-free-layout",
                            "display_name": "自由布局验收",
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
                page.get_by_text("自由关系布局", exact=False).wait_for()
                page.locator(".chart").scroll_into_view_if_needed()
                page.screenshot(path=str(evidence / f"free-collapsed-{width}x{height}.png"), full_page=True)

                _click_chart_node(page, "knowledge:kp-0")
                page.wait_for_timeout(250)

                # Search is the user-facing way to reveal a distant node and
                # its complete prerequisite chain without chasing coordinates
                # while the visible graph is being recomputed.
                search = page.get_by_role("searchbox", name="检索知识点")
                search.fill("大语言模型")
                page.wait_for_timeout(250)
                search.fill("不存在的知识点")
                page.wait_for_timeout(120)
                page.evaluate(
                    """() => {
                      const input = document.querySelector('input[aria-label="检索知识点"]');
                      if (input) input.value = '';
                    }"""
                )

                snapshot = _chart_snapshot(page)
                assert snapshot is not None
                assert snapshot["nodeCount"] == len(payload["hierarchy"][0]["knowledgePoints"]), snapshot
                assert snapshot["edgeCount"] == len(payload["hierarchy"][0]["knowledgePoints"]) - 1, snapshot
                assert all(point["name"].strip() for point in snapshot["points"]), snapshot
                assert snapshot["minClearance"] >= 8, snapshot
                assert snapshot["largestRowBucket"] <= 5, snapshot
                assert snapshot["angleBinCount"] >= 7, snapshot
                assert snapshot["horizontalEdgeRatio"] < 0.4, snapshot
                assert snapshot["crossingCount"] <= 2, snapshot
                assert all(abs(float(value)) < 1e-9 for value in snapshot["curveness"]), snapshot
                assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")

                page.screenshot(path=str(evidence / f"free-expanded-{width}x{height}.png"), full_page=True)
                page.locator('[data-testid="knowledge-graph-explorer"] .chart').screenshot(
                    path=str(evidence / f"free-canvas-expanded-{width}x{height}.png")
                )
                page.locator(".app-content").evaluate("element => { element.scrollTop = element.scrollHeight }")
                page.wait_for_timeout(100)
                page.screenshot(path=str(evidence / f"free-expanded-bottom-{width}x{height}.png"), full_page=True)
                page.locator(".app-content").evaluate("element => { element.scrollTop = 0 }")
                page.wait_for_timeout(100)
                before = {
                    point["id"]: (round(point["logicalX"], 6), round(point["logicalY"], 6))
                    for point in snapshot["points"]
                }
                page.evaluate("() => window.dispatchEvent(new Event('resize'))")
                page.wait_for_timeout(120)
                stable_snapshot = _chart_snapshot(page)
                after = {
                    point["id"]: (round(point["logicalX"], 6), round(point["logicalY"], 6))
                    for point in stable_snapshot["points"]
                }
                assert before == after

                page.get_by_role("button", name="关系投影").click()
                page.screenshot(path=str(evidence / f"free-projection-{width}x{height}.png"), full_page=True)
                page.get_by_role("button", name="关系图").click()
                search.fill("Transformer")
                page.get_by_test_id("course-graph-overview").get_by_role("heading", name="Transformer").wait_for()
                page.screenshot(path=str(evidence / f"free-selected-{width}x{height}.png"), full_page=True)

                assert not page_errors, page_errors
                assert not failed_requests, failed_requests
                assert not console_errors, console_errors
                reports.append({"viewport": {"width": width, "height": height}, "geometry": snapshot})
                context.close()
        finally:
            browser.close()

    (evidence / "browser-report.json").write_text(
        json.dumps(
            {"task_id": "COURSE-GRAPH-FREE-LAYOUT-01", "status": "passed", "reports": reports},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
