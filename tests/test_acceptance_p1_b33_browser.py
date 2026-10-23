from __future__ import annotations

import json
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest


pytestmark = pytest.mark.skipif(
    __import__("os").environ.get("EDUMATRIX_RUN_BROWSER") != "1",
    reason="B33 browser evidence is an explicit opt-in check",
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B33"
COURSE_ID = "course-p1-b33-browser"
COURSE_TITLE = "机器学习导论"
SNAPSHOT_ID = "snapshot-p1-b33-browser"


class _SpaHandler(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
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


def _summary(mode: str) -> dict:
    card = {
        "id": "kp-p1-b33-browser",
        "knowledge_point_id": "kp-p1-b33-browser",
        "title": "梯度下降",
        "mastery": 0.42 if mode == "complete" else None,
        "mastery_status": "supported" if mode == "complete" else "unknown",
        "mastery_label": "有掌握证据" if mode == "complete" else "未知（暂无掌握证据）",
        "weak_reason": "最近作答中梯度方向判断不稳定" if mode == "complete" else "当前画像快照记录该知识点需要优先强化；具体原因待确认。",
        "weak_reason_status": "supported" if mode == "complete" else "unknown",
        "profile_dimensions": [{"key": "knowledge_mastery", "label": "知识基础与掌握度", "status": "需要巩固" if mode == "complete" else "待确认"}],
        "course_snapshot": {
            "course_id": COURSE_ID,
            "course_title": COURSE_TITLE,
            "course_version": "v3",
            "snapshot_id": SNAPSHOT_ID if mode == "complete" else None,
            "snapshot_version": "profile.continuous.v4" if mode == "complete" else None,
        },
        "source_refs": ([{"type": "profile_snapshot", "id": SNAPSHOT_ID, "label": "当前画像快照"}, {"type": "source_ref", "id": "source-p1-b33", "label": "诊断课程来源"}] if mode == "complete" else []),
        "event_refs": ([{"type": "learning_event", "id": "event-p1-b33", "label": "支持该知识点的学习事件"}] if mode == "complete" else []),
        "next_action": {
            "label": "开始强化" if mode == "complete" else "路径待确认",
            "route": f"/workspace/path?course_id={COURSE_ID}&knowledge_point_id=kp-p1-b33-browser&profile_snapshot_id={SNAPSHOT_ID}" if mode == "complete" else None,
            "available": mode == "complete",
        },
    }
    return {
        "schema_version": "f4.dashboard-summary.v1",
        "state": "ready",
        "course": {"id": COURSE_ID, "title": COURSE_TITLE, "version": "v3"},
        "profile_alignment": {
            "course": {"id": COURSE_ID, "title": COURSE_TITLE, "version": "v3", "source": "团队课程知识库"},
            "profile_snapshot": {"id": SNAPSHOT_ID if mode == "complete" else None, "version": "profile.continuous.v4" if mode == "complete" else None},
            "legacy_migration": {"mapping_version": "legacy-profile-map.v1", "fields": []},
        },
        "traceability": {"profile_snapshot_id": SNAPSHOT_ID if mode == "complete" else None},
        "focus": {"title": "梯度下降", "strategy": "先理解梯度方向，再完成一次练习。", "reason": "来自当前画像证据。", "completion_criteria": "完成练习并保存有效证据。", "estimated_minutes": [15, 20], "source_refs": []},
        "primary_action": {"label": "开始学习", "route": "/workspace/path"},
        "primary_task": {"task_kind": "path", "recommended_resource": "学习空间"},
        "metrics": [{"label": "需强化", "value": "1", "detail": "来自画像快照", "source_refs": []}],
        "knowledge_strategies": [],
        "review_summary": {"due_count": 0, "items": []},
        "weak_summary": [] if mode == "empty" else [card],
        "aggregation": {"status": "ready", "message": ""},
        "trend": [],
    }


def _workspace(mode: str) -> dict:
    return {
        "state": "ready",
        "course": {"id": COURSE_ID, "title": COURSE_TITLE, "version": "v3"},
        "profile": {"snapshot_id": SNAPSHOT_ID if mode == "complete" else None, "profile_version": "profile.continuous.v4" if mode == "complete" else None, "weak_knowledge_points": []},
        "current_path": {"nodes": []},
        "today_tasks": [],
        "next_action": {"label": "查看学习路径", "route": "/workspace/path"},
    }


def _install_mocks(page, mode: str, requests: list[tuple[str, str]]):
    def respond(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body, ensure_ascii=False))

    def handle(route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        method = request.method.upper()
        if method != "GET":
            requests.append((method, path))
        if path.endswith("/v1/m5/context/resolve") and method == "POST":
            respond(route, {"context": {"courseId": COURSE_ID, "version": "v3"}, "course": {"id": COURSE_ID, "title": COURSE_TITLE, "version": "v3"}})
            return
        if path.endswith("/auth/me"):
            respond(route, {"public_id": "user-p1-b33-browser", "username": "p1-b33-browser", "display_name": "B33 验收", "role": "student"})
            return
        if path.endswith("/v1/m5/workspace"):
            respond(route, _workspace(mode))
            return
        if path.endswith("/v1/m5/dashboard"):
            respond(route, _summary(mode))
            return
        if path.endswith("/v1/m5/learning/feedback/latest"):
            respond(route, {"feedback": None})
            return
        if "/profile/" in path and path.endswith("/analysis"):
            respond(route, {"dashboard_report": "当前课程画像已生成。"})
            return
        if "/profile/" in path and path.endswith("/learning-path"):
            respond(route, {"nodes": [], "active_learning_target": "梯度下降"})
            return
        if "/profile/" in path:
            respond(route, {"concept_mastery": {}, "cognitive_load": 0.2, "frustration_index": 0.1})
            return
        if "/review/" in path:
            respond(route, {"due_reviews": []})
            return
        if "/recommendations" in path:
            respond(route, [])
            return
        if "/notes/" in path:
            respond(route, {"notes": []})
            return
        if path.endswith("/health"):
            respond(route, {"status": "ok"})
            return
        if method != "GET":
            respond(route, {"detail": "unexpected mutation"}, status=500)
            return
        respond(route, {})

    page.route("**/api/**", handle)


def test_dashboard_weak_evidence_complete_unknown_empty_and_spacing():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    reports = []
    with _frontend_server() as base_url:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for mode in ("complete", "unknown", "empty"):
                    for width, height in ((1440, 900), (1366, 768)):
                        context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
                        context.add_init_script(
                            "localStorage.setItem('edumatrix_token', 'p1-b33-browser-token');"
                            "localStorage.setItem('edumatrix_role', 'student');"
                            "localStorage.setItem('edumatrix_student_id', 'p1-b33-browser');"
                            "localStorage.setItem('edumatrix_onboarded', 'true');"
                        )
                        page = context.new_page()
                        requests: list[tuple[str, str]] = []
                        errors: list[str] = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        _install_mocks(page, mode, requests)
                        page.goto(f"{base_url}/?course_id={COURSE_ID}", wait_until="networkidle")
                        page.locator(".dashboard-page").wait_for(state="visible", timeout=30_000)
                        side = page.locator(".dashboard-side-summary")
                        side.wait_for(state="visible")
                        if mode == "empty":
                            assert "当前没有可用的画像快照" in side.inner_text()
                        else:
                            item = page.get_by_test_id("dashboard-weak-item")
                            item.wait_for(state="visible")
                            assert "梯度下降" in item.inner_text()
                            if mode == "complete":
                                assert "42%" in item.inner_text()
                                evidence = item.locator(".dashboard-weak-item__evidence")
                                evidence.locator("summary").focus()
                                evidence.locator("summary").press("Enter")
                                assert "诊断课程来源" in evidence.inner_text()
                                assert "支持该知识点的学习事件" in evidence.inner_text()
                                action = item.get_by_role("button", name="开始强化：梯度下降")
                                action.focus()
                                action.press("Enter")
                                page.wait_for_timeout(100)
                                assert "/workspace/path" in page.url
                                assert "course_id=" in page.url and "knowledge_point_id=" in page.url
                            else:
                                assert "未知 / 待确认" in item.inner_text()
                                assert "具体原因待确认" in item.inner_text()
                        geometry = page.locator(".dashboard-page").evaluate(
                            """root => { const section = root.querySelector('.dashboard-side-summary > section'); const style = section ? getComputedStyle(section) : null; return {documentWidth: document.documentElement.scrollWidth, bodyWidth: document.body.scrollWidth, viewportWidth: innerWidth, left: root.getBoundingClientRect().left, right: root.getBoundingClientRect().right, sidePaddingLeft: style ? parseFloat(style.paddingLeft) : 0, sidePaddingRight: style ? parseFloat(style.paddingRight) : 0} }"""
                        )
                        assert geometry["documentWidth"] <= width + 1, geometry
                        assert geometry["bodyWidth"] <= width + 1, geometry
                        assert geometry["left"] >= -1 and geometry["right"] <= width + 1, geometry
                        assert geometry["sidePaddingLeft"] >= 18 and geometry["sidePaddingRight"] >= 18, geometry
                        assert not [entry for entry in requests if entry[0] not in {"POST"}]
                        assert not [entry for entry in requests if entry[0] == "POST" and not entry[1].endswith("/v1/m5/context/resolve")], requests
                        assert not errors, errors
                        name = f"{mode}-{width}x{height}.png"
                        page.screenshot(path=str(EVIDENCE / name), full_page=False)
                        reports.append({"mode": mode, "viewport": [width, height], "geometry": geometry, "requests": requests, "errors": errors, "screenshot": name})
                        context.close()
            finally:
                browser.close()
    (EVIDENCE / "browser-report.json").write_text(json.dumps({"task_id": "P1-B33", "status": "passed", "viewports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
