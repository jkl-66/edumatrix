"""F2-F4 continuous desktop acceptance journey on one isolated runtime."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f4_phase_acceptance"
DB_PATH = OUTPUT_DIR / "f4_phase_runtime.db"
PORT = int(os.getenv("EDUMATRIX_F4_PHASE_PORT", "8905"))
BASE_URL = f"http://127.0.0.1:{PORT}"
COURSE_ID = "demo-course-rag-trust-v1"
PASSWORD = "F4-phase-journey-2026!"
ANSWERS = (
    "我在高校学习人工智能与机器学习课程。",
    "我希望掌握可信 RAG 评测并完成一个可演示项目。",
    "我学过 Python、线性代数和概率论，但检索评测基础一般。",
    "我容易混淆召回率、准确率和来源可信度。",
    "我喜欢先看例子，再分步推导，最后用代码和测验验证。",
)


def structured_handout_fixture(source_ref_id: str = "demo-ref-01") -> dict[str, Any]:
    return {
        "schemaVersion": "f5.handout.v1",
        "title": "连续旅程个性化讲义",
        "summary": "用于验证资源包恢复会保留已经成功生成的结构化讲义。",
        "learningGoal": "理解可信 RAG 评测的核心机制，并能用来源和检查步骤验证结论。",
        "estimatedMinutes": 20,
        "outline": [
            {"id": "concept-overview", "title": "关键概念"},
            {"id": "figure-flow", "title": "机制图"},
            {"id": "example-use", "title": "例子"},
            {"id": "counterexample-use", "title": "反例与边界"},
            {"id": "code-check", "title": "代码检查"},
            {"id": "quiz-check", "title": "学习检查"},
            {"id": "source-note", "title": "课程来源"},
        ],
        "concepts": [{
            "id": "concept-overview",
            "title": "关键概念：可信评测",
            "explanation": "可信评测同时检查检索结果、回答内容和可定位来源，不能只看单一分数。",
            "sourceRefIds": [source_ref_id],
        }],
        "figures": [{
            "id": "figure-flow",
            "title": "评测机制链",
            "kind": "diagram",
            "content": "问题 -> 检索证据 -> 生成回答 -> 来源核验 -> 结果复盘",
            "caption": "每一步都保留可检查的输入、输出和来源。",
            "sourceRefIds": [source_ref_id],
        }],
        "examples": [{
            "id": "example-use",
            "title": "例子：有来源的回答",
            "body": "回答指出结论来自哪一章节，并允许返回原文核对条件和边界。",
            "sourceRefIds": [source_ref_id],
        }],
        "counterExamples": [{
            "id": "counterexample-use",
            "title": "只给分数",
            "body": "只有一个总体分数却没有来源和错误定位，无法支持后续改进。",
            "sourceRefIds": [source_ref_id],
        }],
        "codeBlocks": [{
            "id": "code-check",
            "title": "检查评测记录",
            "language": "python",
            "code": "def is_traceable(record):\n    return bool(record.get('source_ref_id'))\n",
            "explanation": "这里只展示检查思路，真实运行仍在代码沙盒完成。",
        }],
        "miniQuiz": [{
            "id": "quiz-check",
            "question": "哪项最能证明回答可以复核？",
            "options": ["回答文字更长", "能够返回准确课程来源"],
            "correctIndex": 1,
            "explanation": "可定位来源让学生能够检查结论和适用条件。",
            "required": True,
        }],
        "footnotes": [{
            "id": "source-note",
            "sourceRefId": source_ref_id,
            "label": "[1]",
            "title": "预置课程来源",
            "location": "可信 RAG 评测课程章节",
        }],
        "profileAdaptation": {
            "summary": "根据当前学习画像采用示例、反例和可执行检查逐步讲解。",
            "difficulty": "适中",
            "scaffolding": ["先理解机制链", "再核对来源", "最后完成学习检查"],
        },
    }


def wait_port(expected: bool, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected state: {expected}")


def prepare_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "f4-phase-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_ONBOARDING_V2": "1",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def seed_demo(env: dict[str, str]) -> None:
    code = (
        "from app.database import SessionLocal, init_db; "
        "from app.competition_demo_seed import seed_competition_demo; "
        "init_db(); db=SessionLocal(); seed_competition_demo(db); db.close()"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode:
        raise RuntimeError(f"demo seed failed: {result.stdout}\n{result.stderr}")


def register(page: Page, username: str) -> None:
    response = page.request.post(
        f"{BASE_URL}/api/auth/register",
        data={"username": username, "password": PASSWORD, "display_name": "F4 阶段连续旅程学生"},
    )
    if not response.ok:
        raise AssertionError(f"register failed: {response.status} {response.text()}")


def attach_course(username: str) -> None:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        owner = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()
        assert owner, username
        db.execute(
            """INSERT OR IGNORE INTO course_memberships
               (id, course_id, user_public_id, role, status, created_at, updated_at)
               VALUES (?, ?, ?, 'student', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (f"cm-f4-phase-{username}", COURSE_ID, owner[0]),
        )
        db.commit()


def login(page: Page, username: str) -> str:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_test_id("login-username").fill(username)
    page.get_by_test_id("login-password").fill(PASSWORD)
    with page.expect_response(
        lambda response: response.url.endswith("/api/auth/login") and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(rf"{re.escape(BASE_URL)}/(?:onboarding|$).*"), timeout=30_000)
    token = page.evaluate("() => localStorage.getItem('edumatrix_token')")
    assert token
    return token


def diagnostics(page: Page, report: dict[str, Any]) -> None:
    page.on("response", lambda response: report["http_errors"].append({
        "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url, "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text)
            if message.type == "error" else None)


def visible_metrics(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const visible = (el) => {
            const style = getComputedStyle(el), rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1 &&
              rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight;
          };
          const controls = [...document.querySelectorAll('button,a[href],input,select,textarea')].filter(visible);
          const collisions = [];
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i], b = controls[j];
            if (a.contains(b) || b.contains(a)) continue;
            const x = a.getBoundingClientRect(), y = b.getBoundingClientRect();
            if (Math.min(x.right, y.right) - Math.max(x.left, y.left) > 3 &&
                Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top) > 3) {
              collisions.push([(a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 48),
                               (b.innerText || b.getAttribute('aria-label') || '').trim().slice(0, 48)]);
            }
          }
          const clipped = [...document.querySelectorAll('button,a[href],h1,h2,h3,strong,p,span,label')]
            .filter(visible).filter((el) => {
              const style = getComputedStyle(el), rect = el.getBoundingClientRect();
              if (style.textOverflow === 'ellipsis') return false;
              return rect.right > innerWidth + 1 || rect.left < -1 ||
                (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap');
            }).map((el) => (el.innerText || '').trim().slice(0, 80)).filter(Boolean).slice(0, 20);
          const smallText = [...document.querySelectorAll('body *')].filter((el) =>
            visible(el) && el.children.length === 0 && (el.innerText || '').trim() &&
            Number.parseFloat(getComputedStyle(el).fontSize) < 13.5
          ).map((el) => ({text: el.innerText.trim().slice(0, 40), size: getComputedStyle(el).fontSize})).slice(0, 20);
          const forbiddenClasses = [...document.querySelectorAll('body *')].filter(visible).map((el) =>
            typeof el.className === 'string' ? el.className : ''
          ).filter((value) => /(?:text|bg|border)-(?:green|emerald|teal|sky|blue|indigo|purple)-/i.test(value)).slice(0, 20);
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            bodyTextLength: (document.body.innerText || '').trim().length,
            collisions, clipped, smallText, forbiddenClasses,
          };
        }"""
    )


def capture(page: Page, report: dict[str, Any], name: str) -> None:
    page.wait_for_timeout(500)
    metrics = visible_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True)
    report["screenshots"].append(name)
    report["layout_checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] > 160, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["forbiddenClasses"], metrics


def answer_onboarding(page: Page, answer: str) -> None:
    page.get_by_label("你的回答").fill(answer)
    with page.expect_response(
        lambda response: response.url.endswith("/api/v1/onboarding/turns") and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_role("button", name="发送回答").click()
    editor = page.get_by_test_id("onboarding-candidate-editor")
    editor.wait_for(state="visible", timeout=20_000)
    with page.expect_response(
        lambda response: "/api/v1/onboarding/turns/" in response.url
        and response.url.endswith("/confirm") and response.status == 200,
        timeout=30_000,
    ):
        editor.get_by_role("button", name=re.compile(r"确认本轮画像|再次保存到画像|更新为本次回答")).click()
    editor.wait_for(state="hidden", timeout=20_000)


def answer_question(page: Page, question: dict[str, Any]) -> None:
    question_type = question["questionType"]
    if question_type in {"single_choice", "multiple_choice"}:
        page.locator(".option-list label").first.click()
    elif question_type == "true_false":
        page.get_by_role("button", name="正确").click()
    elif question_type == "fill_blank":
        for field in page.locator(".blank-list input").all():
            field.fill("可信检索")
    elif question_type == "code":
        page.locator(".code-answer textarea").fill("def answer():\n    return True")
    else:
        page.locator("textarea.text-answer").fill("依据冻结课程来源完成本题分析与结论。")
    page.get_by_text("基本理解", exact=True).click()


def save_and_move(page: Page, target: int) -> None:
    with page.expect_response(
        lambda response: "/api/v1/diagnostics/sessions/" in response.url
        and "/responses/" in response.url and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_role("button", name="保存并进入下一题").click()
    page.get_by_text(f"第 {target} / 5 题", exact=True).wait_for(state="visible", timeout=20_000)


def api_post(page: Page, token: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    response = page.request.post(
        f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {token}"}, data=body or {},
    )
    if not response.ok:
        raise AssertionError(f"POST {path} failed: {response.status} {response.text()}")
    return response.json()


def owner_metrics(username: str) -> dict[str, Any]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        owner_id = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
        profile = db.execute(
            "SELECT concept_mastery FROM student_profiles WHERE student_id=?", (username,),
        ).fetchone()
        return {
            "learning_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=?", (owner_id,),
            ).fetchone()[0],
            "profile_snapshots": db.execute(
                "SELECT COUNT(*) FROM profile_snapshots WHERE owner_public_id=?", (owner_id,),
            ).fetchone()[0],
            "review_plans": db.execute(
                "SELECT COUNT(*) FROM review_plans WHERE student_id=?", (username,),
            ).fetchone()[0],
            "wrong_questions": db.execute(
                "SELECT COUNT(*) FROM wrong_questions WHERE student_id=?", (username,),
            ).fetchone()[0],
            "concept_mastery": json.loads(profile[0] or "{}") if profile else {},
        }


def create_trusted_completion_evidence(username: str) -> dict[str, Any]:
    from app.database import DBGenerationTask, DBPathNode, DBTaskEvent, DBUser, SessionLocal
    from app.exam_gate import exam_gate_status
    from app.m5_learning import LearningEventInput, process_path_event, record_learning_event

    db = SessionLocal()
    try:
        user = db.query(DBUser).filter_by(username=username).one()
        generation = db.query(DBGenerationTask).filter_by(
            owner_public_id=user.public_id,
            capability="learning_resource_bundle.generate",
        ).order_by(DBGenerationTask.created_at.desc()).first()
        assert generation is not None
        requested = db.query(DBTaskEvent).filter_by(
            task_id=generation.id, event_type="resource_generation.requested",
        ).order_by(DBTaskEvent.sequence).first()
        snapshot = dict((requested.payload or {}).get("manifest", {}).get("exam_gate") or {})
        assert snapshot.get("required_tasks"), snapshot
        before = exam_gate_status(db, owner_public_id=user.public_id, course_id=COURSE_ID)
        assert before["unlocked"] is False
        created_ids = []
        moment = datetime.now(timezone.utc) + timedelta(seconds=1)
        for index, task in enumerate(snapshot["required_tasks"], start=1):
            node = db.get(DBPathNode, task["id"])
            assert node is not None
            event, _ = record_learning_event(
                db,
                owner_public_id=user.public_id,
                user=user,
                trusted_source=True,
                event=LearningEventInput(
                    idempotency_key=f"f4-phase-complete-{node.id}",
                    event_type="quiz_answered",
                    course_id=COURSE_ID,
                    object_type="path_target",
                    object_id=node.target_object_id or node.id,
                    source="backend",
                    context={"userId": user.public_id, "courseId": COURSE_ID, "taskId": node.id},
                    occurred_at=moment + timedelta(seconds=index),
                    payload={
                        "graded": True,
                        "correct": True,
                        "attempt_id": f"f4-phase-attempt-{index}",
                    },
                ),
            )
            process_path_event(db, event=event)
            created_ids.append(event.id)
        db.commit()
        after = exam_gate_status(db, owner_public_id=user.public_id, course_id=COURSE_ID)
        assert after["unlocked"] is True, after
        return {"before": before, "after": after, "event_ids": created_ids}
    finally:
        db.close()


def select_today_task(page: Page) -> None:
    page.get_by_test_id("path-overview").wait_for(state="visible", timeout=45_000)
    tasks = page.get_by_test_id("today-knowledge-points").locator("button")
    tasks.first.wait_for(state="visible", timeout=30_000)
    assert tasks.count() > 0
    tasks.first.click()
    selected = page.get_by_test_id("selected-knowledge-point")
    selected.wait_for(state="visible", timeout=20_000)
    selected.locator("button.generation-panel__generate").wait_for(state="visible")


def run_journey(page: Page, report: dict[str, Any], username: str) -> None:
    register(page, username)
    attach_course(username)
    token = login(page, username)

    page.get_by_test_id("onboarding-v2").wait_for(state="visible", timeout=30_000)
    capture(page, report, "01-onboarding-start-1440x900.png")
    answer_onboarding(page, ANSWERS[0])
    page.reload(wait_until="domcontentloaded")
    page.get_by_test_id("onboarding-progress").get_by_text("1/5", exact=True).wait_for(state="visible")
    report["checks"]["onboarding_refresh_resume"] = True
    for answer in ANSWERS[1:]:
        answer_onboarding(page, answer)
    complete = page.get_by_test_id("onboarding-complete")
    complete.wait_for(state="visible", timeout=30_000)
    capture(page, report, "02-onboarding-complete-1440x900.png")
    with page.expect_response(
        lambda response: response.url.endswith("/api/v1/onboarding/finalize") and response.status == 200,
        timeout=30_000,
    ):
        complete.get_by_role("button", name="确认初始画像").click()
    complete.get_by_role("button", name="进入入学诊断").wait_for(state="visible", timeout=20_000)
    complete.get_by_role("button", name="进入入学诊断").click()
    page.wait_for_url(re.compile(r".*/workspace/assessment/entry(?:\?.*)?$"), timeout=30_000)

    page.get_by_test_id("diagnostic-overview").wait_for(state="visible", timeout=30_000)
    page.route(
        "**/api/v1/diagnostics/blueprints",
        lambda route: route.fulfill(
            status=503, content_type="application/json",
            body=json.dumps({"detail": {"code": "phase_retry", "message": "阶段验收注入：诊断生成暂时不可用。"}}, ensure_ascii=False),
        ),
        times=1,
    )
    page.get_by_test_id("generate-diagnostic").click()
    page.get_by_text("阶段验收注入：诊断生成暂时不可用。", exact=True).wait_for(state="visible")
    page.get_by_test_id("diagnostic-error").get_by_role("button", name="重试").click()
    page.get_by_test_id("diagnostic-overview").wait_for(state="visible")
    with page.expect_response(
        lambda response: response.url.endswith("/api/v1/diagnostics/blueprints") and response.status == 201,
        timeout=30_000,
    ) as blueprint_response:
        page.get_by_test_id("generate-diagnostic").click()
    blueprint = blueprint_response.value.json()["blueprint"]
    page.get_by_test_id("diagnostic-ready").wait_for(state="visible", timeout=30_000)
    capture(page, report, "03-diagnostic-ready-1440x900.png")
    page.get_by_test_id("enter-diagnostic").click()
    page.get_by_test_id("diagnostic-session").wait_for(state="visible", timeout=30_000)

    page.route("**/api/v1/diagnostics/sessions/*/responses/*", lambda route: route.abort("failed"), times=1)
    answer_question(page, blueprint["questions"][0])
    page.get_by_role("button", name="保存并进入下一题").click()
    page.get_by_test_id("diagnostic-save-error").wait_for(state="visible", timeout=15_000)
    with page.expect_response(
        lambda response: "/responses/" in response.url and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_role("button", name="重试保存").click()
    save_and_move(page, 2)
    answer_question(page, blueprint["questions"][1])
    save_and_move(page, 3)
    answer_question(page, blueprint["questions"][2])
    with page.expect_response(
        lambda response: "/responses/" in response.url and response.status == 200,
        timeout=30_000,
    ):
        page.wait_for_timeout(900)
    page.reload(wait_until="domcontentloaded")
    page.get_by_test_id("diagnostic-restored").wait_for(state="visible", timeout=30_000)
    page.get_by_text("第 3 / 5 题", exact=True).wait_for(state="visible")
    report["checks"]["diagnostic_refresh_resume"] = True
    save_and_move(page, 4)
    answer_question(page, blueprint["questions"][3])
    save_and_move(page, 5)
    answer_question(page, blueprint["questions"][4])
    with page.expect_response(
        lambda response: response.url.endswith("/submit") and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_role("button", name="提交本次诊断").click()
    page.get_by_test_id("diagnostic-submitted").wait_for(state="visible", timeout=45_000)
    page.get_by_role("heading", name="你的入学诊断结果").wait_for(state="visible", timeout=45_000)
    capture(page, report, "04-diagnostic-report-1440x900.png")

    session_id = page.evaluate(
        "() => document.querySelector('[data-testid=diagnostic-session]')?.dataset.sessionId || ''"
    )
    if not session_id:
        with sqlite3.connect(DB_PATH, timeout=20) as db:
            owner_id = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
            session_id = db.execute(
                "SELECT id FROM diagnostic_sessions WHERE owner_public_id=? AND blueprint_id=?",
                (owner_id, blueprint["id"]),
            ).fetchone()[0]
    page.route(
        f"**/api/v1/diagnostics/sessions/{session_id}/report/path",
        lambda route: route.fulfill(
            status=503, content_type="application/json",
            body=json.dumps({"detail": {"code": "phase_path_retry", "message": "阶段验收注入：路径生成失败，可单独重试。"}}, ensure_ascii=False),
        ),
        times=1,
    )
    page.get_by_role("button", name="生成初始学习路径").click()
    page.get_by_text("阶段验收注入：路径生成失败，可单独重试。", exact=True).wait_for(state="visible")
    page.get_by_role("button", name="重试生成路径").click()
    page.get_by_role("button", name="确认并进入总学习路径").wait_for(state="visible", timeout=30_000)
    page.get_by_role("button", name="确认并进入总学习路径").click()
    page.wait_for_url(re.compile(r".*/workspace/path\?.*path_id=.*"), timeout=30_000)

    before_browsing = owner_metrics(username)
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.get_by_test_id("dashboard-today-tasks").wait_for(state="visible", timeout=45_000)
    capture(page, report, "05-dashboard-1440x900.png")
    page.goto(f"{BASE_URL}/profile/learning?course_id={COURSE_ID}", wait_until="domcontentloaded")
    page.get_by_test_id("profile-knowledge-map").wait_for(state="visible", timeout=45_000)
    page.locator('[data-testid="profile-knowledge-map"] canvas').wait_for(state="visible", timeout=30_000)
    capture(page, report, "06-profile-1440x900.png")
    page.goto(f"{BASE_URL}/workspace/path?course_id={COURSE_ID}", wait_until="domcontentloaded")
    select_today_task(page)
    capture(page, report, "07-path-ready-1440x900.png")
    after_browsing = owner_metrics(username)
    assert after_browsing == before_browsing, {"before": before_browsing, "after": after_browsing}
    report["checks"]["ordinary_browsing_is_read_only"] = {"before": before_browsing, "after": after_browsing}

    before_generation = owner_metrics(username)
    execute_pattern = "**/api/v1/resource-bundles/generation-jobs/*/execute-demo"
    page.route(
        execute_pattern,
        lambda route: route.fulfill(
            status=409, content_type="application/json",
            body=json.dumps({"detail": {"code": "resource_generation.demo_disabled", "message": "阶段验收暂缓自动执行。"}}, ensure_ascii=False),
        ),
    )
    with page.expect_request(
        lambda request: request.method == "POST" and request.url.endswith("/api/v1/resource-bundles/generation-jobs"),
        timeout=30_000,
    ) as generation_request, page.expect_response(
        lambda response: response.request.method == "POST"
        and response.url.endswith("/api/v1/resource-bundles/generation-jobs") and response.status == 201,
        timeout=30_000,
    ) as generation_response:
        page.get_by_role("button", name="一键生成完整资源包").click()
    generation_payload = generation_request.value.post_data_json
    created_job = generation_response.value.json()
    job_id = created_job["job_id"]
    page.get_by_test_id("resource-generation-status").wait_for(state="visible", timeout=30_000)
    replay = page.request.post(
        f"{BASE_URL}/api/v1/resource-bundles/generation-jobs",
        headers={"Authorization": f"Bearer {token}"}, data=generation_payload,
    )
    assert replay.status == 201, replay.text()
    replay_payload = replay.json()
    assert replay_payload["job_id"] == job_id and replay_payload["created"] is False, replay_payload
    report["checks"]["resource_job_idempotency"] = {
        "job_id": job_id, "replayed_job_id": replay_payload["job_id"], "created": replay_payload["created"],
    }

    handout = api_post(page, token, f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/handout/start")
    handout = api_post(
        page, token, f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/handout/complete",
        {
            "content": json.dumps(structured_handout_fixture(), ensure_ascii=False),
            "content_format": "json",
        },
    )
    handout_id = next(item["resource"]["resource_id"] for item in handout["items"] if item["type"] == "handout")
    api_post(page, token, f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/mind_map/start")
    api_post(
        page, token, f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/mind_map/fail",
        {"error_code": "phase_injected_failure", "error_message": "阶段验收注入的单项失败"},
    )
    page.reload(wait_until="domcontentloaded")
    page.get_by_test_id("resource-bundle-workspace").wait_for(state="visible", timeout=45_000)
    page.get_by_role("button", name="重试此项").wait_for(state="visible", timeout=30_000)
    capture(page, report, "08-resource-single-failure-1440x900.png")
    page.unroute(execute_pattern)
    page.get_by_role("button", name="重试此项").click()
    bundle_workspace = page.get_by_test_id("resource-bundle-workspace")
    bundle_workspace.get_by_text("完整资源包已就绪", exact=True).wait_for(state="visible", timeout=45_000)
    bundle_workspace.get_by_text("9 / 9 已归档", exact=True).wait_for(state="visible", timeout=45_000)
    final_job = page.request.get(
        f"{BASE_URL}/api/v1/resource-bundles/generation-jobs/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert final_job["status"] == "succeeded"
    assert next(item["resource"]["resource_id"] for item in final_job["items"] if item["type"] == "handout") == handout_id
    capture(page, report, "09-resource-recovered-1440x900.png")
    after_generation = owner_metrics(username)
    for key in ("learning_events", "profile_snapshots", "review_plans", "wrong_questions", "concept_mastery"):
        assert after_generation[key] == before_generation[key], {"key": key, "before": before_generation, "after": after_generation}
    report["checks"]["resource_generation_is_not_mastery"] = {
        "before": before_generation, "after": after_generation,
    }

    page.goto(f"{BASE_URL}/workspace/assessment?course_id={COURSE_ID}", wait_until="domcontentloaded")
    center = page.get_by_test_id("assessment-center")
    center.wait_for(state="visible", timeout=30_000)
    assert center.get_by_role("button").count() == 2
    center.get_by_test_id("intelligent-exam-entry").click()
    page.get_by_test_id("exam-gate-locked").wait_for(state="visible", timeout=30_000)
    capture(page, report, "10-exam-gate-locked-1440x900.png")

    report["checks"]["trusted_completion_evidence"] = create_trusted_completion_evidence(username)
    page.reload(wait_until="domcontentloaded")
    page.get_by_test_id("exam-builder-unlocked").wait_for(state="visible", timeout=45_000)
    capture(page, report, "11-exam-gate-unlocked-1440x900.png")

    page.set_viewport_size({"width": 1366, "height": 768})
    page.goto(BASE_URL, wait_until="domcontentloaded")
    page.get_by_test_id("dashboard-today-tasks").wait_for(state="visible", timeout=45_000)
    capture(page, report, "12-dashboard-1366x768.png")
    page.goto(f"{BASE_URL}/profile/learning?course_id={COURSE_ID}", wait_until="domcontentloaded")
    page.get_by_test_id("profile-knowledge-map").wait_for(state="visible", timeout=45_000)
    capture(page, report, "13-profile-1366x768.png")
    page.goto(f"{BASE_URL}/workspace/path?course_id={COURSE_ID}", wait_until="domcontentloaded")
    page.get_by_test_id("path-overview").wait_for(state="visible", timeout=45_000)
    capture(page, report, "14-path-1366x768.png")
    page.goto(f"{BASE_URL}/workspace/assessment/exams?course_id={COURSE_ID}", wait_until="domcontentloaded")
    page.get_by_test_id("exam-builder-unlocked").wait_for(state="visible", timeout=45_000)
    capture(page, report, "15-exam-builder-1366x768.png")


def validate_errors(report: dict[str, Any]) -> None:
    unexpected_http = [item for item in report["http_errors"] if not (
        item["status"] == 503 and (
            item["url"].endswith("/api/v1/diagnostics/blueprints")
            or item["url"].endswith("/report/path")
        )
        or item["status"] == 409 and item["url"].endswith("/execute-demo")
    )]
    unexpected_failed = [item for item in report["failed_requests"] if not (
        "/api/v1/diagnostics/sessions/" in item["url"] and "/responses/" in item["url"]
        or str(item.get("failure")) in {"net::ERR_ABORTED", "net::ERR_CANCELED"}
    )]
    unexpected_console = [message for message in report["console_errors"] if not any(token in message for token in (
        "503", "409", "ERR_FAILED", "Failed to load resource",
    ))]
    assert not unexpected_http, unexpected_http
    assert not unexpected_failed, unexpected_failed
    assert not unexpected_console, unexpected_console
    assert not report["page_errors"], report["page_errors"]
    report["checks"]["expected_failure_recovery"] = {
        "http": len(report["http_errors"]),
        "failed_requests": len(report["failed_requests"]),
        "console_errors": len(report["console_errors"]),
        "unexpected": 0,
    }


def database_audit(username: str) -> dict[str, Any]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        owner_id = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "onboarding_sessions": db.execute(
                "SELECT COUNT(*) FROM onboarding_sessions WHERE owner_public_id=?", (owner_id,),
            ).fetchone()[0],
            "diagnostic_reports": db.execute(
                "SELECT COUNT(*) FROM diagnostic_reports WHERE owner_public_id=?", (owner_id,),
            ).fetchone()[0],
            "active_or_completed_paths": db.execute(
                "SELECT COUNT(*) FROM learning_paths WHERE owner_public_id=? AND status IN ('active','completed')", (owner_id,),
            ).fetchone()[0],
            "generation_jobs": db.execute(
                "SELECT COUNT(*) FROM generation_tasks WHERE owner_public_id=? AND capability='learning_resource_bundle.generate'", (owner_id,),
            ).fetchone()[0],
            "artifacts": db.execute(
                "SELECT COUNT(*) FROM artifacts WHERE owner_public_id=?", (owner_id,),
            ).fetchone()[0],
        }


def main() -> int:
    prepare_output()
    env = runtime_env()
    os.environ.update(env)
    username = f"f4_phase_{int(time.time())}"
    report: dict[str, Any] = {
        "schema_version": "f4.phase-continuous-journey.v1",
        "result": "failed",
        "database": str(DB_PATH),
        "service": BASE_URL,
        "single_browser_context": True,
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "layout_checks": {},
        "checks": {},
        "http_errors": [],
        "failed_requests": [],
        "console_errors": [],
        "page_errors": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    process = None
    try:
        seed_demo(env)
        with (OUTPUT_DIR / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page()
                page.set_default_timeout(30_000)
                diagnostics(page, report)
                run_journey(page, report, username)
                context.close()
                browser.close()
        validate_errors(report)
        report["database_audit"] = database_audit(username)
        assert report["database_audit"]["integrity"] == "ok"
        assert report["database_audit"]["foreign_key_violations"] == 0
        assert report["database_audit"]["onboarding_sessions"] == 1
        assert report["database_audit"]["diagnostic_reports"] == 1
        assert report["database_audit"]["active_or_completed_paths"] == 1
        assert report["database_audit"]["generation_jobs"] == 1
        assert report["database_audit"]["artifacts"] == 9
        report["result"] = "passed"
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        report["traceback"] = traceback.format_exc()
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, text=True, timeout=20,
            )
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            try:
                wait_port(False, 15)
            except RuntimeError:
                pass
        report["process_cleanup"] = process is None or process.poll() is not None
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    print(json.dumps({
        "result": report["result"],
        "screenshots": len(report["screenshots"]),
        "error": report.get("error"),
        "process_cleanup": report["process_cleanup"],
    }, ensure_ascii=False))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
