"""F8-T01 isolated dual-desktop review-calendar acceptance."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import Browser, Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f8_t01_review_calendar"
BROWSER_DIR = OUTPUT_DIR / "browser"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "f8_t01_runtime.sqlite3"
REPORT_PATH = OUTPUT_DIR / "report.json"
USERNAME = "lzz"
PASSWORD = "404404aA"
COURSE_ID = "demo-course-rag-trust-v1"
LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
PORT_START = int(os.getenv("EDUMATRIX_F8_T01_PORT", "9060"))


def reset_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in (BROWSER_DIR, RUNTIME_DIR):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    if REPORT_PATH.exists():
        REPORT_PATH.unlink()


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F8-T01 E2E port")


def wait_port(port: int, expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(port) is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {port} did not reach expected state {expected}")


def runtime_env(port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "f8-t01-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(port),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def local_to_utc_naive(day, hour: int) -> datetime:
    value = datetime.combine(day, clock_time(hour=hour), tzinfo=LOCAL_ZONE)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def seed_fixture(env: dict[str, str]) -> dict[str, object]:
    os.environ.update(env)
    from app.competition_demo_seed import seed_competition_demo
    from app.database import (
        DBAssessmentAttempt,
        DBAssessmentQuestion,
        DBAssessmentQuestionVersion,
        DBAssessmentRetestTask,
        DBChapter,
        DBChapterKnowledgePoint,
        DBGenerationTask,
        DBKnowledgePoint,
        DBLearningPath,
        DBMisconceptionReview,
        DBPathNode,
        DBPlanDraft,
        DBPlanVersion,
        DBReviewPlan,
        DBTaskEvent,
        DBUser,
        SessionLocal,
        init_db,
    )

    init_db()
    db = SessionLocal()
    try:
        seed_competition_demo(db)
        learner = db.query(DBUser).filter_by(username=USERNAME).one()
        points = (
            db.query(DBKnowledgePoint)
            .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.knowledge_point_id == DBKnowledgePoint.id)
            .join(DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id)
            .filter(DBChapter.course_id == COURSE_ID)
            .order_by(DBKnowledgePoint.title, DBKnowledgePoint.id)
            .all()
        )
        if len(points) < 3:
            raise RuntimeError("F8-T01 fixture requires three canonical course knowledge points")

        today = datetime.now(LOCAL_ZONE).date()
        plans = [
            DBReviewPlan(
                student_id=learner.username,
                concept=points[0].id,
                next_review_at=local_to_utc_naive(today, 10),
                interval_days=1,
                mastery=0.46,
                priority=0.32,
            ),
            DBReviewPlan(
                student_id=learner.username,
                concept=points[1].id,
                next_review_at=local_to_utc_naive(today - timedelta(days=1), 9),
                interval_days=1,
                mastery=0.38,
                priority=0.25,
            ),
            DBReviewPlan(
                student_id=learner.username,
                concept=points[2].id,
                next_review_at=local_to_utc_naive(today + timedelta(days=3), 14),
                interval_days=3,
                mastery=0.62,
                priority=0.55,
            ),
            DBReviewPlan(
                student_id=learner.username,
                concept="未归类旧知识点",
                next_review_at=local_to_utc_naive(today, 16),
                interval_days=2,
                mastery=0.4,
                priority=0.5,
            ),
        ]
        db.add_all(plans)
        db.flush()

        question = DBAssessmentQuestion(
            id="f8-browser-question",
            course_id=COURSE_ID,
            owner_public_id=learner.public_id,
            question_type="single_choice",
            status="approved",
        )
        db.add(question)
        db.flush()
        version = DBAssessmentQuestionVersion(
            id="f8-browser-question-version",
            question_id=question.id,
            version_number=1,
            prompt="梯度下降沿哪个方向更新参数？",
            options=["A. 正梯度方向", "B. 负梯度方向"],
            answer_key={"choice": "B"},
            scoring_rule={"type": "exact"},
            explanation="梯度下降沿负梯度方向更新参数。",
            primary_knowledge_point_id=points[0].id,
            source_ref_ids=["demo-ref-07"],
            content_hash="8" * 64,
            created_by_public_id=learner.public_id,
        )
        db.add(version)
        db.flush()
        question.current_version_id = version.id
        attempt = DBAssessmentAttempt(
            id="f8-browser-source-attempt",
            owner_public_id=learner.public_id,
            course_id=COURSE_ID,
            question_version_id=version.id,
            idempotency_key="f8-browser-source-attempt-key",
            mode="practice",
            answer={"choice": "A"},
            score=0.0,
            correct=False,
        )
        db.add(attempt)
        db.flush()
        misconception = DBMisconceptionReview(
            id="f8-browser-misconception",
            owner_public_id=learner.public_id,
            attempt_id=attempt.id,
            candidate_category="knowledge_gap",
            status="accepted",
        )
        db.add(misconception)
        db.flush()
        retest = DBAssessmentRetestTask(
            id="f8-browser-retest",
            owner_public_id=learner.public_id,
            misconception_review_id=misconception.id,
            source_attempt_id=attempt.id,
            question_version_id=version.id,
            course_id=COURSE_ID,
            due_at=local_to_utc_naive(today, 0),
            status="due",
        )
        db.add(retest)

        assigned_at = datetime.utcnow() - timedelta(minutes=5)
        plan = DBPlanDraft(
            id="f8-browser-plan",
            owner_public_id=learner.public_id,
            course_id=COURSE_ID,
            title="F8 复习验收今日路径",
            status="confirmed",
            idempotency_key="f8-browser-plan-key",
        )
        db.add(plan)
        db.flush()
        path_version = DBPlanVersion(
            id="f8-browser-plan-version",
            plan_draft_id=plan.id,
            version_number=1,
            content={
                "schema_version": "m5.plan.v1",
                "goal": "完成今日复习任务",
                "nodes": [{
                    "node_key": "f8-browser-required-task",
                    "node_type": "assessment",
                    "target_object_id": "f8-browser-required-target",
                    "title": "完成今日概念测验",
                    "prerequisites": [],
                    "resource_status": "existing",
                    "estimate_min_minutes": 10,
                    "estimate_max_minutes": 15,
                }],
            },
            content_hash="f" * 64,
            created_by_public_id=learner.public_id,
        )
        db.add(path_version)
        db.flush()
        plan.current_version_id = path_version.id
        plan.confirmed_version_id = path_version.id
        path = DBLearningPath(
            id="f8-browser-path",
            owner_public_id=learner.public_id,
            course_id=COURSE_ID,
            source_plan_version_id=path_version.id,
            status="active",
            updated_at=datetime.utcnow(),
        )
        db.add(path)
        db.flush()
        required_node = DBPathNode(
            id="f8-browser-required-task",
            learning_path_id=path.id,
            node_key="f8-browser-required-task",
            sequence=1,
            node_type="assessment",
            target_object_id="f8-browser-required-target",
            title="完成今日概念测验",
            status="pending",
            prerequisites=[],
            is_extension=False,
            resource_status="existing",
            estimate_min_minutes=10,
            estimate_max_minutes=15,
        )
        db.add(required_node)
        db.flush()
        gate_snapshot = {
            "schema_version": "f4.intelligent-exam-gate.v1",
            "assignment_date": today.isoformat(),
            "assigned_at": assigned_at.isoformat() + "Z",
            "course_id": COURSE_ID,
            "path_id": path.id,
            "path_version_id": path_version.id,
            "selected_task_id": required_node.id,
            "required_tasks": [{
                "id": required_node.id,
                "node_key": required_node.node_key,
                "title": required_node.title,
                "node_type": required_node.node_type,
                "target_object_id": required_node.target_object_id,
                "completion_criteria": "服务端判分通过",
                "route": f"/workspace/path?course_id={COURSE_ID}&node_id={required_node.id}",
            }],
            "optional_task_ids": [],
        }
        generation_task = DBGenerationTask(
            id="f8-browser-gate-generation",
            owner_public_id=learner.public_id,
            course_id=COURSE_ID,
            trace_id="f8-browser-gate-trace",
            status="completed",
            progress=1,
            capability="learning_resource_bundle.generate",
            idempotency_key="f8-browser-gate-generation-key",
        )
        db.add(generation_task)
        db.flush()
        db.add(DBTaskEvent(
            id="f8-browser-gate-requested",
            task_id=generation_task.id,
            sequence=1,
            event_type="resource_generation.requested",
            payload={"manifest": {"exam_gate": gate_snapshot}},
        ))
        db.commit()
        return {
            "owner_public_id": learner.public_id,
            "course_id": COURSE_ID,
            "today": today.isoformat(),
            "month": today.strftime("%Y-%m"),
            "today_plan_task_id": f"review-plan:{plans[0].id}",
            "retest_task_id": f"retest:{retest.id}",
        }
    finally:
        db.close()


def start_service(env: dict[str, str], port: int) -> subprocess.Popen:
    log = (RUNTIME_DIR / "server.log").open("a", encoding="utf-8")
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    process._edumatrix_log = log  # type: ignore[attr-defined]
    wait_port(port, True)
    return process


def stop_service(process: subprocess.Popen | None, port: int) -> None:
    if process is None:
        return
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=20,
            )
        else:
            process.terminate()
        process.wait(timeout=10)
    log = getattr(process, "_edumatrix_log", None)
    if log is not None:
        log.close()
    wait_port(port, False, timeout=20)


def database_state(owner_public_id: str) -> dict[str, object]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        return {
            "learning_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "profile_snapshots": db.execute(
                "SELECT COUNT(*) FROM profile_snapshots WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "review_plans": db.execute(
                "SELECT COUNT(*) FROM review_plans WHERE student_id=?", (USERNAME,)
            ).fetchone()[0],
            "checkins": db.execute(
                "SELECT COUNT(*) FROM checkin_logs WHERE student_id=?", (USERNAME,)
            ).fetchone()[0],
            "assessment_attempts": db.execute(
                "SELECT COUNT(*) FROM assessment_attempts WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "generation_tasks": db.execute(
                "SELECT COUNT(*) FROM generation_tasks WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def attach_diagnostics(page: Page, report: dict[str, object]) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(response.url)
        if response.status >= 400:
            report["http_errors"].append({"status": response.status, "url": response.url})

    page.on("response", on_response)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url, "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def login(page: Page, base_url: str) -> None:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": USERNAME, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    state = json.dumps(response.json(), ensure_ascii=False)
    page.add_init_script(f"""
      const session = {state};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_display_name', session.display_name || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_role', session.role || 'student');
      localStorage.setItem('edumatrix_student_id', session.student_id || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', '{COURSE_ID}');
      localStorage.setItem('edumatrix_course_title', 'RAG 应用开发与负责任评测实训');
    """)


def visual_metrics(page: Page) -> dict[str, object]:
    return page.evaluate("""
      () => {
        const root = document.querySelector('[data-testid="review-schedule-board"]')
        if (!root) return { missingRoot: true }
        const visible = el => {
          const style = getComputedStyle(el), rect = el.getBoundingClientRect()
          return style.display !== 'none' && style.visibility !== 'hidden' &&
            Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1
        }
        const textNodes = [...root.querySelectorAll('button,a,h1,h2,h3,p,span,strong,small,label,dt,dd,li')]
          .filter(el => visible(el) && (el.textContent || '').trim())
        const clipped = textNodes.filter(el => {
          const style = getComputedStyle(el)
          if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
          if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
          return el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2
        }).map(el => ({ tag: el.tagName, text: el.textContent.trim().slice(0, 60) })).slice(0, 20)
        const smallText = textNodes.filter(el => Number.parseFloat(getComputedStyle(el).fontSize) < 13.9)
          .map(el => ({ text: el.textContent.trim().slice(0, 50), size: getComputedStyle(el).fontSize })).slice(0, 20)
        const controls = [...root.querySelectorAll('button,a[href],input,select,textarea')].filter(visible)
        const collisions = []
        for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
          const a = controls[i], b = controls[j]
          if (a.contains(b) || b.contains(a)) continue
          const x = a.getBoundingClientRect(), y = b.getBoundingClientRect()
          const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left)
          const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top)
          if (overlapW > 3 && overlapH > 3) collisions.push([
            (a.textContent || a.getAttribute('aria-label') || '').trim().slice(0, 32),
            (b.textContent || b.getAttribute('aria-label') || '').trim().slice(0, 32),
          ])
        }
        const schedule = root.querySelector('.review-schedule')?.getBoundingClientRect()
        const calendar = root.querySelector('.review-calendar')?.getBoundingClientRect()
        const agenda = root.querySelector('.review-agenda')?.getBoundingClientRect()
        const forbidden = new Set([
          'rgb(16, 185, 129)', 'rgb(34, 197, 94)', 'rgb(59, 130, 246)',
          'rgb(14, 165, 233)', 'rgb(139, 92, 246)', 'rgb(168, 85, 247)',
        ])
        const forbiddenThemeHits = [...root.querySelectorAll('*')].filter(visible).flatMap(el => {
          const style = getComputedStyle(el)
          return [style.color, style.backgroundColor, style.borderColor].filter(value => forbidden.has(value))
        })
        const backgrounds = [...root.querySelectorAll('*')].filter(visible)
          .map(el => getComputedStyle(el).backgroundImage).filter(value => value && value !== 'none')
        return {
          missingRoot: false,
          viewport: [innerWidth, innerHeight],
          pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
          rootOverflow: root.scrollWidth > root.clientWidth + 1,
          calendarCells: root.querySelectorAll('.review-day').length,
          clipped, smallText, collisions, forbiddenThemeHits, backgrounds,
          layout: schedule && calendar && agenda ? {
            scheduleWidth: schedule.width,
            calendarWidth: calendar.width,
            agendaWidth: agenda.width,
            ratio: calendar.width / (calendar.width + agenda.width),
            overlap: Math.max(0, calendar.right - agenda.left),
          } : null,
        }
      }
    """)


def assert_visual(page: Page, report: dict[str, object], key: str) -> None:
    metrics = visual_metrics(page)
    report["visual"][key] = metrics
    assert metrics["missingRoot"] is False, metrics
    assert metrics["pageOverflow"] is False, metrics
    assert metrics["rootOverflow"] is False, metrics
    assert metrics["calendarCells"] == 42, metrics
    assert metrics["clipped"] == [], metrics
    assert metrics["smallText"] == [], metrics
    assert metrics["collisions"] == [], metrics
    assert metrics["forbiddenThemeHits"] == [], metrics
    assert metrics["backgrounds"] == [], metrics
    assert metrics["layout"] and 0.56 <= metrics["layout"]["ratio"] <= 0.62, metrics
    assert metrics["layout"]["overlap"] == 0, metrics


def capture(page: Page, report: dict[str, object], name: str) -> None:
    page.wait_for_function(
        "() => !document.querySelector('.page-fade-enter-active, .page-fade-leave-active')",
        timeout=5_000,
    )
    page.screenshot(path=BROWSER_DIR / name, full_page=True)
    report["screenshots"].append(name)


def review_url(base_url: str, fixture: dict[str, object], path: str = "/workspace/review") -> str:
    query = urlencode({
        "course_id": fixture["course_id"],
        "month": fixture["month"],
        "date": fixture["today"],
    })
    return f"{base_url}{path}?{query}"


def open_review(page: Page, base_url: str, fixture: dict[str, object], path: str = "/workspace/review") -> None:
    page.goto(review_url(base_url, fixture, path), wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("review-schedule-board").wait_for(state="visible")
    page.get_by_test_id("review-calendar-loading").wait_for(state="hidden")


def run_primary(page: Page, base_url: str, fixture: dict[str, object], report: dict[str, object]) -> None:
    open_review(page, base_url, fixture)
    board = page.get_by_test_id("review-schedule-board")
    assert board.locator('.review-day').count() == 42
    assert board.locator(f'.review-day[data-date="{fixture["today"]}"]').get_attribute("aria-pressed") == "true"
    assert board.locator(f'[data-task-id="{fixture["today_plan_task_id"]}"]').count() == 1
    assert board.locator(f'[data-task-id="{fixture["retest_task_id"]}"]').count() == 1
    assert_visual(page, report, "review_1440_initial")
    capture(page, report, "01-review-calendar-1440x900.png")

    before_browse = database_state(str(fixture["owner_public_id"]))
    board.get_by_role("button", name="查看上个月").click()
    page.wait_for_timeout(250)
    board.get_by_role("button", name="查看下个月").click()
    page.wait_for_timeout(250)
    board.locator(".review-calendar__today").click()
    page.wait_for_timeout(250)
    with page.expect_response(lambda response: "/api/v1/review-schedule" in response.url and "course_id=unclassified" in response.url):
        board.locator("select[aria-label='筛选复习课程']").select_option("unclassified")
    page.get_by_test_id("review-calendar-loading").wait_for(state="hidden")
    with page.expect_response(lambda response: "/api/v1/review-schedule" in response.url and f"course_id={fixture['course_id']}" in response.url):
        board.locator("select[aria-label='筛选复习课程']").select_option(str(fixture["course_id"]))
    page.get_by_test_id("review-calendar-loading").wait_for(state="hidden")
    board.locator(f'.review-day[data-date="{fixture["today"]}"]').click()
    after_browse = database_state(str(fixture["owner_public_id"]))
    assert after_browse == before_browse, (before_browse, after_browse)
    report["database"]["browse_before"] = before_browse
    report["database"]["browse_after"] = after_browse

    task = board.locator(f'[data-task-id="{fixture["today_plan_task_id"]}"]')
    task.get_by_role("button", name="去复习").click()
    page.get_by_text("复习页不会增加或绕过任何解锁条件", exact=False).wait_for(
        state="visible",
        timeout=30_000,
    )
    board = page.get_by_test_id("review-schedule-board")
    task = board.locator(f'[data-task-id="{fixture["today_plan_task_id"]}"]')
    task.get_by_role("button", name="生成复习资源包").click()
    page.wait_for_url("**/workspace/resources/bundles/**", timeout=60_000)
    assert "/workspace/resources/bundles/" in page.url
    bundle = page.get_by_test_id("resource-bundle-workspace")
    bundle.wait_for(state="visible", timeout=30_000)
    bundle.locator(".loading-surface").wait_for(state="hidden", timeout=30_000)
    capture(page, report, "02-review-generated-resource-bundle.png")

    open_review(page, base_url, fixture)
    board = page.get_by_test_id("review-schedule-board")
    task = board.locator(f'[data-task-id="{fixture["today_plan_task_id"]}"]')
    task.get_by_role("button", name="去复习").click()
    task.get_by_text("一般", exact=True).click()
    task.locator("input[type='number']").fill("12")
    task.get_by_role("button", name="完成复习并更新安排").click()
    page.get_by_text("复习已完成", exact=False).wait_for(state="visible", timeout=30_000)
    page.get_by_test_id("review-calendar-loading").wait_for(state="hidden", timeout=30_000)
    capture(page, report, "03-review-completed.png")

    board.locator(f'.review-day[data-date="{fixture["today"]}"]').click()
    retest = board.locator(f'[data-task-id="{fixture["retest_task_id"]}"]')
    retest.get_by_role("button", name="去复习").click()
    retest.get_by_text("梯度下降沿哪个方向更新参数？", exact=True).wait_for(state="visible")
    retest.locator("input[type='radio'][value='B']").check()
    retest.get_by_role("button", name="提交复测").click()
    page.get_by_text("复测通过", exact=False).wait_for(state="visible", timeout=30_000)
    page.get_by_test_id("review-calendar-loading").wait_for(state="hidden", timeout=30_000)
    capture(page, report, "04-delayed-retest-completed.png")

    after_actions = database_state(str(fixture["owner_public_id"]))
    assert after_actions["learning_events"] >= before_browse["learning_events"] + 2, after_actions
    assert after_actions["generation_tasks"] >= before_browse["generation_tasks"] + 1, after_actions
    assert after_actions["checkins"] == before_browse["checkins"] + 1, after_actions
    assert after_actions["integrity"] == "ok" and after_actions["foreign_key_violations"] == 0
    report["database"]["after_actions"] = after_actions

    board.get_by_role("button", name="复习工具与历史").click()
    page.locator("#legacy-review-tools[open]").wait_for(state="visible")
    page.wait_for_timeout(300)
    legacy_tools = page.locator("#legacy-review-tools[open]")
    legacy_tools.scroll_into_view_if_needed()
    capture(page, report, "05-legacy-review-tools.png")


def run_secondary(page: Page, base_url: str, fixture: dict[str, object], report: dict[str, object]) -> None:
    open_review(page, base_url, fixture, "/workspace/review/calendar")
    assert_visual(page, report, "calendar_1366_initial")
    capture(page, report, "06-review-calendar-1366x768.png")
    page.get_by_test_id("review-schedule-board").get_by_role("button", name="复习工具与历史").click()
    page.locator("#calendar-legacy-tools[open]").wait_for(state="visible")
    page.wait_for_timeout(300)
    legacy_tools = page.locator("#calendar-legacy-tools[open]")
    legacy_text = legacy_tools.inner_text()
    for marker in ("连续打卡天数", "复习时长记录", "全部复习计划"):
        assert marker in legacy_text
    legacy_tools.scroll_into_view_if_needed()
    capture(page, report, "07-calendar-legacy-tools-1366x768.png")


def run() -> dict[str, object]:
    reset_output()
    port = free_port()
    env = runtime_env(port)
    fixture = seed_fixture(env)
    base_url = f"http://127.0.0.1:{port}"
    report: dict[str, object] = {
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "viewports": [[1440, 900], [1366, 768]],
        "isolated_database": str(DB_PATH),
        "single_service": True,
        "single_chromium_instance": True,
        "external_model_called": False,
        "screenshots": [],
        "visual": {},
        "database": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
    }
    process = None
    try:
        process = start_service(env, port)
        with sync_playwright() as playwright:
            browser: Browser = playwright.chromium.launch(headless=True)
            try:
                primary_context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                primary = primary_context.new_page()
                attach_diagnostics(primary, report)
                login(primary, base_url)
                run_primary(primary, base_url, fixture, report)
                primary_context.close()

                secondary_context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
                secondary = secondary_context.new_page()
                attach_diagnostics(secondary, report)
                login(secondary, base_url)
                run_secondary(secondary, base_url, fixture, report)
                secondary_context.close()
            finally:
                browser.close()
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["external_requests"], report["external_requests"]
        report["status"] = "passed"
        return report
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        stop_service(process, port)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result["status"],
        "screenshots": len(result["screenshots"]),
        "database": result["database"],
    }, ensure_ascii=False, indent=2))
