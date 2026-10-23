"""Automated desktop/keyboard smoke for the P1-B14 path surface.

The browser uses mocked read-only API responses so the check exercises the real
Vue route and layout without writing the formal database or calling a model.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import time

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
PORT = int(os.getenv("EDUMATRIX_B14_VITE_PORT", "5178"))
BASE_URL = f"http://127.0.0.1:{PORT}"
EVIDENCE_DIR = ROOT / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B14"


def _wait_port(timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", PORT)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError("Vite dev server did not start")


def _resources():
    return [
        {"type": "learning", "label": "学习理解", "explanation": "理解课程内容", "estimate_minutes": 12, "completion_criteria": "完成重点阅读"},
        {"type": "practice", "label": "巩固练习", "explanation": "验证理解", "estimate_minutes": 8, "completion_criteria": "提交一次练习"},
        {"type": "extension", "label": "拓展迁移", "explanation": "迁移到新场景", "estimate_minutes": 5, "completion_criteria": "完成一个拓展任务"},
    ]


def _paths():
    def path(path_id, course_id, title, node_prefix):
        nodes = [
            {"id": f"{node_prefix}-1", "node_key": f"{node_prefix}-root", "sequence": 1, "node_type": "chapter", "title": "基础概念", "status": "pending", "prerequisites": [], "estimate_minutes": [20, 30]},
            {"id": f"{node_prefix}-2", "node_key": f"{node_prefix}-branch", "sequence": 2, "node_type": "chapter", "title": "分支应用", "status": "pending", "prerequisites": [f"{node_prefix}-root"], "estimate_minutes": [15, 25]},
        ]
        return {"id": path_id, "course_id": course_id, "course": {"id": course_id, "title": title, "subject": title}, "status": "active", "lock_version": 1, "source_plan_version_id": f"{path_id}-version", "nodes": nodes}
    return [path("path-a", "course-a", "数据结构", "a"), path("path-b", "course-b", "机器学习", "b")]


def _schedule(day: int):
    paths = _paths()
    tasks = []
    for path in paths:
        node = path["nodes"][0 if day == 1 else 1]
        tasks.append({
            **node,
            "course_id": path["course_id"],
            "course_title": path["course"]["title"],
            "path_id": path["id"],
            "task_kind": "path",
            "knowledge_point_title": f"{path['course']['title']} · {node['title']}",
            "completion_criteria": "完成学习并留下可追溯证据",
            "resources": _resources(),
            "generation_context": {
                "ready": True,
                "knowledge_point_id": f"{path['course_id']}-kp",
                "knowledge_point_title": node["title"],
                "source_ref_ids": [f"{path['course_id']}-ref"],
                "profile_snapshot_id": f"{path['course_id']}-profile",
                "path_version_id": path["source_plan_version_id"],
                "schedule_day": day,
            },
            "continue_route": f"/workspace?course_id={path['course_id']}&node_id={node['id']}",
            "scheduled_day": day,
        })
    return {
        "schema_version": "m5.multi-course-schedule.v1",
        "selected_day": day,
        "total_days": 2,
        "days": [
            {"day": 1, "date": "2026-08-25", "tasks": _schedule_tasks(1), "total_minutes": 50, "progress": {"completed": 0, "total": 2}},
            {"day": 2, "date": "2026-08-26", "tasks": _schedule_tasks(2), "total_minutes": 40, "progress": {"completed": 0, "total": 2}},
        ],
        "selected": {"day": day, "date": f"2026-08-{25 + day - 1:02d}", "tasks": tasks, "total_minutes": 50 if day == 1 else 40, "progress": {"completed": 0, "total": 2}},
        "courses": [
            {"path_id": "path-a", "course_id": "course-a", "course": {"id": "course-a", "title": "数据结构", "subject": "数据结构"}, "status": "active", "lock_version": 1, "nodes": paths[0]["nodes"], "profile_snapshot_id": "course-a-profile", "time_budget_minutes": 60},
            {"path_id": "path-b", "course_id": "course-b", "course": {"id": "course-b", "title": "机器学习", "subject": "机器学习"}, "status": "active", "lock_version": 1, "nodes": paths[1]["nodes"], "profile_snapshot_id": "course-b-profile", "time_budget_minutes": 60},
        ],
        "read_only": True,
        "learning_state_written": False,
    }


def _schedule_tasks(day: int):
    result = []
    for path in _paths():
        node = path["nodes"][0 if day == 1 else 1]
        result.append({
            **node,
            "course_id": path["course_id"],
            "course_title": path["course"]["title"],
            "path_id": path["id"],
            "task_kind": "path",
            "knowledge_point_title": f"{path['course']['title']} · {node['title']}",
            "completion_criteria": "完成学习并留下可追溯证据",
            "resources": _resources(),
            "generation_context": {"ready": True, "knowledge_point_id": f"{path['course_id']}-kp", "knowledge_point_title": node["title"], "source_ref_ids": [f"{path['course_id']}-ref"], "profile_snapshot_id": f"{path['course_id']}-profile", "path_version_id": f"{path['id']}-version", "schedule_day": day},
            "continue_route": f"/workspace?course_id={path['course_id']}&node_id={node['id']}",
            "scheduled_day": day,
        })
    return result


def _json(route, body):
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body, ensure_ascii=False))


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    vite = subprocess.Popen(["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(PORT)], cwd=FRONTEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_port()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()

            def handle(route):
                request = route.request
                url = request.url
                from urllib.parse import urlparse
                if not urlparse(url).path.startswith("/api/"):
                    return route.continue_()
                if request.method == "GET" and "/auth/me" in url:
                    return _json(route, {
                        "public_id": "b14-browser",
                        "username": "b14-browser",
                        "display_name": "B14 浏览器验收",
                        "role": "student",
                        "is_active": True,
                    })
                if request.method == "GET" and "/v1/m5/paths" in url and "/schedule" not in url:
                    return _json(route, {"items": _paths()})
                if request.method == "GET" and "/v1/m5/schedule" in url:
                    from urllib.parse import parse_qs, urlparse
                    day = int(parse_qs(urlparse(url).query).get("day", ["1"])[0])
                    return _json(route, _schedule(max(1, min(2, day))))
                if request.method == "GET" and "/v1/resource-bundles/generation-jobs" in url:
                    return _json(route, {"items": []})
                if request.method == "POST" and "/paths/" in url and "/transition" in url:
                    return _json(route, _paths()[0])
                return _json(route, {})

            page.route("**/api/**", handle)
            page.add_init_script("localStorage.setItem('edumatrix_token', 'b14-test-token'); localStorage.setItem('edumatrix_role', 'student'); localStorage.setItem('edumatrix_onboarded', 'true'); localStorage.setItem('edumatrix_student_id', 'b14-browser');")
            page.goto(f"{BASE_URL}/workspace/path?course_id=course-a", wait_until="networkidle", timeout=60000)
            page.get_by_test_id("path-overview").wait_for(state="visible")
            page.get_by_test_id("path-day-1").wait_for(state="visible")
            page.screenshot(path=str(EVIDENCE_DIR / "1440x900-total.png"), full_page=True)
            assert page.locator("html").evaluate("el => el.scrollWidth <= window.innerWidth")
            page.get_by_test_id("path-day-2").click()
            page.get_by_text("D2 · 总路径", exact=True).wait_for(state="visible")
            page.get_by_test_id("path-subject-view").click()
            page.get_by_text("D2 · 科目路径", exact=True).wait_for(state="visible")
            page.get_by_test_id("subject-toggle-course-a").focus()
            assert page.evaluate("document.activeElement?.dataset?.testid === 'subject-toggle-course-a'")
            page.set_viewport_size({"width": 1366, "height": 768})
            page.screenshot(path=str(EVIDENCE_DIR / "1366x768-subject.png"), full_page=True)
            assert page.locator("html").evaluate("el => el.scrollWidth <= window.innerWidth")
            browser.close()
        (EVIDENCE_DIR / "report.json").write_text(json.dumps({"result": "passed", "viewports": [[1440, 900], [1366, 768]], "keyboard": "subject-toggle-course-a focused", "screenshots": ["1440x900-total.png", "1366x768-subject.png"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0
    finally:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(vite.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            vite.terminate()
            try:
                vite.wait(timeout=10)
            except subprocess.TimeoutExpired:
                vite.kill()


if __name__ == "__main__":
    raise SystemExit(main())
