from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from tests.test_acceptance_p1_b28_browser import _frontend_server


pytestmark = pytest.mark.skipif(
    os.getenv("EDUMATRIX_RUN_BROWSER") != "1",
    reason="B30 browser evidence is an explicit opt-in check",
)


EVIDENCE = Path(__file__).resolve().parents[1] / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B30"


def _courses() -> list[dict]:
    return [
        {
            "id": "b30-course-a",
            "title": "机器学习基础",
            "version": "v1",
            "sourceSummary": {"readyDocuments": 2},
            "source_health": "ready",
            "index_status": "ready",
        },
        {
            "id": "b30-course-b",
            "title": "数据结构与算法",
            "version": "v3",
            "sourceSummary": {"readyDocuments": 3},
            "source_health": "ready",
            "index_status": "ready",
        },
    ]


def _blueprint(course: dict) -> dict:
    course_id = course["id"]
    title = course["title"]
    return {
        "id": f"b30-blueprint-{course_id}",
        "course": {"id": course_id, "title": title, "version": course["version"]},
        "questionCount": 1,
        "estimatedMinutes": 4,
        "sourceRefs": [{"id": f"{course_id}-source-1", "title": f"{title}课程讲义", "locationLabel": "第 1 章 / 第 2 页"}],
        "knowledgePointCoverage": [{"id": f"{course_id}-kp-1", "title": f"{title}核心概念"}],
        "difficultyBands": {
            "difficulty": {"foundation": 1, "standard": 0, "stretch": 0},
            "questionTypes": {"single_choice": 1, "true_false": 0, "short_answer": 0},
        },
        "reviewDecision": {"decisionSummary": "已通过来源与题型校验"},
        "generationStages": [
            {"key": "analysis", "label": "分析课程、知识库与画像", "status": "completed"},
            {"key": "generation", "label": "AI 定制生成诊断题", "status": "completed"},
            {"key": "validation", "label": "校验题量、题型与来源", "status": "completed"},
            {"key": "review", "label": "独立模型逐题审核", "status": "completed"},
        ],
        "questions": [
            {
                "id": f"{course_id}-question-1",
                "questionType": "single_choice",
                "diagnosticKind": "theory",
                "expertDifficulty": 0.32,
                "prompt": f"{title}中，哪一项最能描述本课程的核心概念？",
                "options": ["A. 课程资料中的定义", "B. 与课程无关的猜测"],
                "knowledgePoint": {"id": f"{course_id}-kp-1", "title": f"{title}核心概念"},
                "sourceRefs": [{"id": f"{course_id}-source-1", "title": f"{title}课程讲义", "locationLabel": "第 1 章 / 第 2 页"}],
            }
        ],
    }


def _report(course: dict, *, with_path: bool = False) -> dict:
    course_id = course["id"]
    title = course["title"]
    report = {
        "id": f"b30-report-{course_id}",
        "course": {"id": course_id, "title": title},
        "summary": {
            "score": 0.82,
            "scoreLabel": "基础稳固",
            "scoredCount": 1,
            "questionCount": 1,
            "strongest": f"{title}核心概念",
            "weakest": "迁移应用",
            "coreAdvice": f"先巩固{title}核心概念，再进入迁移练习。",
        },
        "blindSpots": [],
        "decisionBasis": ["答案已提交并完成服务端判分", "评分证据绑定当前课程来源"],
        "weaknesses": [{"title": "迁移应用"}],
        "mastery": [{"knowledgePointId": f"{course_id}-kp-1", "title": f"{title}核心概念", "evidenceCount": 1, "score": 0.82, "label": "已确认"}],
        "evidence": [
            {
                "questionVersionId": f"{course_id}-question-1",
                "knowledgePoint": {"id": f"{course_id}-kp-1", "title": f"{title}核心概念"},
                "errorType": {"label": "正确作答", "basis": "与课程定义一致"},
                "understandingLabel": "基本理解",
                "score": 0.82,
                "prompt": f"{title}中，哪一项最能描述本课程的核心概念？",
                "answer": {"choice": "A"},
                "judgmentBasis": "答案与课程来源相符",
                "explanation": "服务端判分结果已绑定课程证据。",
                "evaluation": {"confidence": 0.94, "status": "supported", "claim": "课程资料支持该判断"},
                "sources": [{"id": f"{course_id}-source-1", "title": f"{title}课程讲义", "locationLabel": "第 1 章 / 第 2 页", "source_document_id": f"{course_id}-document-1"}],
            }
        ],
        "difficultyFit": {"target": 0.35, "basis": "按当前画像快照校准", "bands": [{"key": "foundation", "label": "基础", "score": 0.82}]},
        "boundary": "只有已提交且完成判分的答案才会进入诊断证据；普通浏览不会改变掌握度。",
        "evaluation": {"status": "completed", "completedCount": 1, "totalCount": 1},
    }
    if with_path:
        report["path"] = {
            "plan": {"id": f"subject-plan-{course_id}"},
            "nodes": [{"node_key": f"{course_id}::intro", "title": f"{title}起点任务", "reason": "由诊断证据触发", "difficulty": 0.35, "chapter": {"position": 1}}],
        }
    return report


def _session(course: dict, blueprint: dict) -> dict:
    return {
        "id": f"b30-session-{course['id']}",
        "status": "in_progress",
        "created": True,
        "lastSavedAt": None,
        "currentQuestionIndex": 0,
        "completedCount": 0,
        "responses": [],
        "canSubmit": False,
        "missingQuestionVersionIds": [blueprint["questions"][0]["id"]],
        "blueprint": blueprint,
    }


def _aggregate_result() -> dict:
    return {
        "schema_version": "p1-b30.multicourse-paths.v1",
        "status": "completed",
        "subjects": [
            {"course_id": "b30-course-a", "status": "ready", "path_id": "subject-plan-b30-course-a"},
            {"course_id": "b30-course-b", "status": "ready", "path_id": "subject-plan-b30-course-b"},
        ],
        "total_validation": {
            "status": "valid",
            "course_ids": ["b30-course-a", "b30-course-b"],
            "days": [{"day": 1, "tasks": [{"aggregate_key": "b30-course-a::intro"}, {"aggregate_key": "b30-course-b::intro"}]}],
            "issues": [],
        },
        "total_plan": {"id": "aggregate-plan-b30", "status": "draft"},
    }


def _aggregate_plan() -> dict:
    return {
        "id": "aggregate-plan-b30",
        "status": "draft",
        "current_version_id": "aggregate-version-b30",
        "versions": [
            {
                "id": "aggregate-version-b30",
                "number": 1,
                "content": {
                    "goal": "统筹两门课程的入学诊断起点",
                    "nodes": [
                        {"node_key": "b30-course-a::intro", "title": "机器学习基础起点任务", "estimate_max_minutes": 20},
                        {"node_key": "b30-course-b::intro", "title": "数据结构与算法起点任务", "estimate_max_minutes": 25},
                    ],
                    "assumptions": ["保留课程边界", "遵守先修关系和每日时间预算"],
                },
            }
        ],
    }


def _install_api_mocks(page):
    courses = _courses()
    blueprints = {course["id"]: _blueprint(course) for course in courses}
    sessions = {course["id"]: _session(course, blueprints[course["id"]]) for course in courses}
    reports = {course["id"]: _report(course) for course in courses}

    def respond(route, payload, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))

    def handle(route):
        parsed = urlparse(route.request.url)
        path = parsed.path
        method = route.request.method
        query = parse_qs(parsed.query)
        if path.endswith("/api/auth/me"):
            respond(route, {"public_id": "b30-browser-user", "username": "b30-browser", "display_name": "B30 浏览器验收", "role": "student"})
        elif path.endswith("/api/v1/m5/context/resolve"):
            respond(route, {"context": {"courseId": "b30-course-a", "version": "v1"}, "course": {"id": "b30-course-a", "title": "机器学习基础", "version": "v1"}})
        elif path.endswith("/api/health"):
            respond(route, {"status": "ok"})
        elif path.endswith("/api/v1/diagnostics/courses"):
            respond(route, {"courses": courses})
        elif path.endswith("/api/v1/diagnostics/preflight"):
            course_id = query.get("course_id", [courses[0]["id"]])[0]
            course = next(item for item in courses if item["id"] == course_id)
            respond(route, {"course": {"id": course_id, "title": course["title"], "version": course["version"]}, "canGenerate": True, "profileBasis": {"version": f"profile-{course_id}", "source": "confirmed snapshot", "goal": "完成课程学习"}, "expectedQuestionCount": 1, "estimatedMinutes": 4, "coverage": {"knowledgePoints": [{"id": f"{course_id}-kp-1", "title": f"{course['title']}核心概念"}], "questionTypes": {"single_choice": 1, "true_false": 0, "short_answer": 0}, "sourceCount": 1}})
        elif path.endswith("/api/v1/diagnostics/multi-course/blueprints") and method == "POST":
            respond(route, {"schema_version": "p1-b30.multicourse-blueprints.v1", "status": "completed", "run_key": "b30-run-browser", "ready_count": 2, "failed_count": 0, "items": [{"status": "ready", "course_id": course["id"], "course": course, "blueprint": blueprints[course["id"]]} for course in courses]})
        elif "/api/v1/diagnostics/blueprints/" in path and path.endswith("/sessions") and method == "POST":
            course_id = path.split("/blueprints/", 1)[1].split("/", 1)[0].replace("b30-blueprint-", "")
            current = sessions[course_id]
            respond(route, {"session": current})
        elif "/api/v1/diagnostics/sessions/" in path and "/responses/" in path and method == "PUT":
            course_id = next(item for item in sessions if f"b30-session-{item}" in path)
            session = sessions[course_id]
            question = blueprints[course_id]["questions"][0]
            session["responses"] = [{"questionVersionId": question["id"], "answer": {"choice": "A"}, "understandingLevel": "mostly", "complete": True, "duration": 3}]
            session.update({"completedCount": 1, "canSubmit": True, "missingQuestionVersionIds": [], "lastSavedAt": "2026-08-26T00:00:00Z"})
            respond(route, {"session": session})
        elif "/api/v1/diagnostics/sessions/" in path and path.endswith("/submit") and method == "POST":
            course_id = next(item for item in sessions if f"b30-session-{item}" in path)
            sessions[course_id]["status"] = "submitted"
            respond(route, sessions[course_id])
        elif "/api/v1/diagnostics/sessions/" in path and path.endswith("/report/path") and method == "POST":
            course_id = next(item for item in reports if f"b30-session-{item}" in path)
            reports[course_id] = _report(next(item for item in courses if item["id"] == course_id), with_path=True)
            respond(route, {"report": reports[course_id]})
        elif "/api/v1/diagnostics/sessions/" in path and path.endswith("/report") and method == "POST":
            course_id = next(item for item in reports if f"b30-session-{item}" in path)
            respond(route, {"report": reports[course_id]})
        elif path.endswith("/api/v1/diagnostics/multi-course/paths") and method == "POST":
            respond(route, _aggregate_result())
        elif path.endswith("/api/v1/m5/plans/aggregate-plan-b30"):
            respond(route, _aggregate_plan())
        elif path.endswith("/api/v1/m5/paths"):
            respond(route, {"items": []})
        elif path.endswith("/api/v1/m5/schedule"):
            respond(route, {"selected_day": 1, "total_days": 1, "days": [{"day": 1, "date": "2026-08-26", "tasks": [], "total_minutes": 0, "progress": {"completed": 0, "total": 0}}], "selected": {"day": 1, "date": "2026-08-26", "tasks": [], "total_minutes": 0, "progress": {"completed": 0, "total": 0}}})
        elif path.endswith("/api/v1/m5/today"):
            respond(route, {"items": []})
        elif path.endswith("/api/v1/m5/recommendations") or "/api/recommendations/" in path:
            respond(route, {"items": []})
        elif path.endswith("/api/v1/m5/competition/demo-context") or path.endswith("/api/profile/b30-browser/learning-path"):
            respond(route, {})
        elif "/api/v1/m5/resource-bundles/generation-jobs" in path:
            respond(route, {"items": []})
        else:
            respond(route, {})

    page.route("**/api/**", handle)
    return courses


def _assert_layout(page, root_selector: str, width: int) -> dict:
    layout = page.evaluate(
        """(rootSelector) => {
          const root = document.querySelector(rootSelector);
          const visible = root ? [...root.querySelectorAll('*')].filter((el) => el.getClientRects().length) : [];
          const smallText = visible.filter((el) => el.children.length === 0 && el.textContent.trim() && Number.parseFloat(getComputedStyle(el).fontSize) < 14).map((el) => el.textContent.trim().slice(0, 80));
          const controls = visible.filter((el) => ['BUTTON', 'SELECT', 'TEXTAREA', 'INPUT'].includes(el.tagName)).map((el) => ({tag: el.tagName, text: (el.innerText || el.getAttribute('aria-label') || '').trim(), rect: el.getBoundingClientRect().toJSON()})).filter((item) => item.rect.width > 1 && item.rect.height > 1);
          let collision = null;
          for (let i = 0; i < controls.length && !collision; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i].rect; const b = controls[j].rect;
            const overlap = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
            if (overlap > 2) { collision = {left: controls[i], right: controls[j]}; break; }
          }
          return {documentWidth: document.documentElement.scrollWidth, bodyWidth: document.body.scrollWidth, rootRight: root ? root.getBoundingClientRect().right : 0, rootLeft: root ? root.getBoundingClientRect().left : 0, smallText, collision};
        }""",
        root_selector,
    )
    assert layout["documentWidth"] <= width + 1, layout
    assert layout["bodyWidth"] <= width + 1, layout
    assert layout["rootRight"] <= width + 1, layout
    assert layout["rootLeft"] >= -1, layout
    assert layout["smallText"] == [], layout
    assert layout["collision"] is None, layout
    return layout


def test_multicourse_diagnostic_journey_two_desktop_viewports():
    from playwright.sync_api import sync_playwright

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    reports = []
    with _frontend_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(viewport={"width": width, "height": height})
                context.add_init_script(
                    "localStorage.setItem('edumatrix_token', 'browser-token');"
                    "localStorage.setItem('edumatrix_role', 'student');"
                    "localStorage.setItem('edumatrix_username', 'b30-browser');"
                    "localStorage.setItem('edumatrix_onboarded', 'true');"
                )
                page = context.new_page()
                page_errors: list[str] = []
                console_errors: list[str] = []
                failed_requests: list[str] = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
                page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))
                _install_api_mocks(page)

                page.goto(f"{base_url}/workspace/assessment/entry?course_id=b30-course-a", wait_until="networkidle")
                page.get_by_test_id("diagnostic-selection").wait_for()
                assert page.get_by_role("checkbox", name="选择课程 机器学习基础").is_checked()
                assert not page.get_by_role("checkbox", name="选择课程 数据结构与算法").is_checked()
                page.get_by_role("checkbox", name="选择课程 数据结构与算法").check()
                page.get_by_text("已选择 2 门课程：机器学习基础、数据结构与算法").wait_for()
                page.screenshot(path=str(EVIDENCE / f"entry-selected-{width}x{height}.png"), full_page=True)
                page.get_by_test_id("generate-diagnostic").click()
                page.get_by_test_id("multicourse-diagnostic-ready").wait_for()
                assert page.get_by_text("2 门课程可以开始作答").is_visible()
                assert page.get_by_text("AI 定制生成诊断题").is_visible()
                result_list = page.get_by_test_id("multicourse-result-list")
                assert result_list.get_by_text("机器学习基础", exact=True).is_visible()
                assert result_list.get_by_text("数据结构与算法", exact=True).is_visible()
                page.screenshot(path=str(EVIDENCE / f"blueprints-ready-{width}x{height}.png"), full_page=True)
                _assert_layout(page, '[data-testid="entry-diagnostic"]', width)

                page.get_by_role("button", name="开始这门课程").first.click()
                page.get_by_test_id("diagnostic-session").wait_for()
                page.locator('.option-list label').first.click()
                page.locator('.understanding-control label').filter(has_text="基本理解").click()
                page.get_by_role("button", name="提交本次诊断").click()
                page.get_by_test_id("report-next-step").wait_for()
                assert page.get_by_text("判断依据").is_visible()
                page.get_by_test_id("report-evidence-toggle").click()
                page.locator('[data-testid="report-evidence-drawer"] .evidence-list > article > button').first.click()
                citation = page.get_by_test_id("canonical-source-citation")
                assert citation.is_visible()
                assert "机器学习基础课程讲义" in citation.inner_text()
                page.get_by_role("button", name="生成初始学习路径").click()
                page.get_by_role("button", name="确认并进入总学习路径").wait_for()
                page.screenshot(path=str(EVIDENCE / f"subject-report-a-{width}x{height}.png"), full_page=True)
                _assert_layout(page, '[data-testid="diagnostic-session"]', width)

                page.get_by_role("button", name="继续下一门课程").click()
                page.get_by_test_id("diagnostic-session").get_by_text("数据结构与算法", exact=True).wait_for()
                page.locator('.option-list label').first.click()
                page.locator('.understanding-control label').filter(has_text="基本理解").click()
                page.get_by_role("button", name="提交本次诊断").click()
                page.get_by_test_id("report-next-step").wait_for()
                page.get_by_role("button", name="生成初始学习路径").click()
                page.get_by_role("button", name="生成并验证多科总路径").wait_for()
                page.get_by_role("button", name="生成并验证多科总路径").click()
                page.get_by_test_id("multicourse-total-path-result").wait_for()
                assert page.get_by_text("总路径统筹：valid").is_visible()
                assert page.get_by_text("已合并 2 门课程").is_visible()
                page.screenshot(path=str(EVIDENCE / f"aggregate-result-{width}x{height}.png"), full_page=True)
                _assert_layout(page, '[data-testid="diagnostic-session"]', width)

                page.get_by_role("button", name="查看总路径草稿").click()
                page.get_by_test_id("aggregate-plan-draft").wait_for()
                assert page.get_by_text("总路径草稿").is_visible()
                assert page.get_by_text("课程 2 门").is_visible()
                assert page.get_by_text("机器学习基础起点任务").is_visible()
                assert page.get_by_text("数据结构与算法起点任务").is_visible()
                page.screenshot(path=str(EVIDENCE / f"aggregate-deep-link-{width}x{height}.png"), full_page=True)
                layout = _assert_layout(page, '[data-testid="aggregate-plan-draft"]', width)
                assert not page_errors, page_errors
                assert not console_errors, console_errors
                assert not failed_requests, failed_requests
                reports.append({"viewport": {"width": width, "height": height}, "layout": layout, "page_errors": page_errors, "console_errors": console_errors, "failed_requests": failed_requests})
                context.close()
        finally:
            browser.close()
    (EVIDENCE / "browser-report.json").write_text(json.dumps({"task_id": "ACCEPTANCE-FEEDBACK-P1-B30", "status": "passed", "viewports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
