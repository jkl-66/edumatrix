"""F6-T06 intelligent formal-exam desktop E2E on isolated SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

import e2e_f6_t03_code_sandbox as base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f6_t06_formal_exam"
COURSE_ID = "demo-course-rag-trust-v1"


def seed_fixture(env: dict[str, str]) -> dict[str, str]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBAssessmentQuestion, DBGenerationTask, DBLearningEvent, DBLearningPath,
    DBPathNode, DBSourceRef, DBTaskEvent, DBUser, SessionLocal, init_db,
)
from app.m5_assessment_core import QuestionVersionInput, create_question_version


def add_question(db, learner, *, question_type, prompt, point_id, source_id, answer_key, options=()):
    question, _ = create_question_version(
        db,
        owner_public_id=learner.public_id,
        course_id={COURSE_ID!r},
        question_type=question_type,
        origin="manual",
        version=QuestionVersionInput(
            prompt=prompt,
            options=options,
            answer_key=answer_key,
            scoring_rule={{"type": "exact", "version": "f6-e2e-v1", "correct_threshold": 0.6}},
            explanation=f"课程来源解析：{{prompt}}",
            misconception_tags=(f"需要巩固-{{point_id}}",),
            primary_knowledge_point_id=point_id,
            expert_difficulty=0.5,
            source_ref_ids=(source_id,),
        ),
    )
    question.status = "approved"


init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    learner = db.query(DBUser).filter_by(username="lzz").one()
    path = db.query(DBLearningPath).filter_by(
        owner_public_id=learner.public_id,
        course_id={COURSE_ID!r},
        status="active",
    ).order_by(DBLearningPath.updated_at.desc(), DBLearningPath.id.desc()).first()
    if path is None:
        raise RuntimeError("active demo learning path is missing")
    node = db.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(
        DBPathNode.sequence, DBPathNode.id,
    ).first()
    if node is None:
        raise RuntimeError("demo path node is missing")
    node.status = "completed"

    source_07 = db.get(DBSourceRef, "demo-ref-07")
    source_08 = db.get(DBSourceRef, "demo-ref-08")
    if source_07 is None or source_08 is None:
        raise RuntimeError("frozen demo sources are missing")

    add_question(
        db, learner,
        question_type="single_choice",
        prompt="混合检索的第一步应选择哪项？",
        point_id="demo-kp-07",
        source_id=source_07.id,
        options=("A. 删除全部课程来源", "B. 合并关键词与向量候选"),
        answer_key={{"choice": "B"}},
    )
    add_question(
        db, learner,
        question_type="single_choice",
        prompt="遇到无依据回答时应优先采取哪项措施？",
        point_id="demo-kp-08",
        source_id=source_08.id,
        options=("A. 检查并补充可核查来源", "B. 隐藏来源继续输出"),
        answer_key={{"choice": "A"}},
    )
    add_question(
        db, learner,
        question_type="true_false",
        prompt="正式测评的结论应当能够回查冻结来源。",
        point_id="demo-kp-08",
        source_id=source_08.id,
        answer_key={{"value": True}},
    )
    question, _ = create_question_version(
        db,
        owner_public_id=learner.public_id,
        course_id={COURSE_ID!r},
        question_type="short_answer",
        origin="manual",
        version=QuestionVersionInput(
            prompt="说明混合检索为什么需要冻结来源与重排证据。",
            options=(),
            answer_key={{"reference_answer": "混合检索合并关键词与向量候选，并使用冻结来源和重排证据保证结果可核查。"}},
            scoring_rule={{"version": "f6-e2e-rubric-v1", "correct_threshold": 0.6, "criteria": [{{"id": "coverage", "label": "关键概念覆盖", "weight": 1.0}}]}},
            explanation="答案应同时说明候选合并、冻结来源、重排与可核查性。",
            misconception_tags=("缺少来源与重排边界",),
            primary_knowledge_point_id="demo-kp-07",
            expert_difficulty=0.55,
            source_ref_ids=(source_07.id,),
        ),
    )
    question.status = "approved"

    assigned_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
    task = DBGenerationTask(
        id="f6-t06-browser-generation",
        owner_public_id=learner.public_id,
        course_id={COURSE_ID!r},
        trace_id="f6-t06-browser-generation-trace",
        status="completed",
        progress=1,
        capability="learning_resource_bundle.generate",
        idempotency_key="f6-t06-browser-generation-key",
    )
    db.add(task)
    db.flush()
    snapshot = {{
        "schema_version": "f4.intelligent-exam-gate.v1",
        "assignment_date": datetime.now().astimezone().date().isoformat(),
        "assigned_at": assigned_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        "course_id": {COURSE_ID!r},
        "path_id": path.id,
        "path_version_id": path.source_plan_version_id,
        "selected_task_id": node.id,
        "required_tasks": [{{
            "id": node.id,
            "node_key": node.node_key,
            "title": node.title,
            "node_type": node.node_type,
            "target_object_id": node.target_object_id,
            "completion_criteria": "完成并留下服务端接受的学习证据",
            "route": f"/workspace/path?course_id={COURSE_ID}&node_id={{node.id}}",
        }}],
        "optional_task_ids": [],
    }}
    db.add(DBTaskEvent(
        id="f6-t06-browser-generation-requested",
        task_id=task.id,
        sequence=1,
        event_type="resource_generation.requested",
        payload={{"manifest": {{"exam_gate": snapshot}}}},
    ))
    db.add(DBLearningEvent(
        id="f6-t06-browser-gate-completion",
        owner_public_id=learner.public_id,
        course_id={COURSE_ID!r},
        event_type="quiz_answered",
        schema_version="m5.learning-event.v1",
        idempotency_key="f6-t06-browser-gate-completion-key",
        source="backend",
        trace_id="f6-t06-browser-gate-completion-trace",
        object_type="path_target",
        object_id=node.target_object_id,
        action="assessment.answered",
        context_ref={{"userId": learner.public_id, "courseId": {COURSE_ID!r}, "taskId": node.id}},
        evidence_strength=0.8,
        evidence_status="accepted",
        evidence_reason="server graded evidence",
        mastery_eligible=True,
        completion_effect="complete",
        payload_version="1",
        payload={{"graded": True, "correct": True, "attempt_id": "f6-t06-gate-attempt"}},
        occurred_at=assigned_at + timedelta(minutes=1),
    ))
    db.commit()
    payload = {{"owner_public_id": learner.public_id, "path_id": path.id, "node_id": node.id}}
    Path({str(fixture_path)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=120)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def database_state(db_path: Path, owner_public_id: str) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        event_rows = db.execute(
            "SELECT id, trace_id FROM learning_events WHERE owner_public_id=? "
            "AND event_type='formal_exam_submitted'",
            (owner_public_id,),
        ).fetchall()
        return {
            "exam_count": db.execute(
                "SELECT COUNT(*) FROM assessment_exams WHERE owner_public_id=? AND generation_key IS NOT NULL",
                (owner_public_id,),
            ).fetchone()[0],
            "draft_count": db.execute(
                "SELECT COUNT(*) FROM assessment_exam_response_drafts WHERE owner_public_id=?",
                (owner_public_id,),
            ).fetchone()[0],
            "attempt_count": db.execute(
                "SELECT COUNT(*) FROM assessment_attempts WHERE owner_public_id=? AND mode='formal'",
                (owner_public_id,),
            ).fetchone()[0],
            "submission_event_count": len(event_rows),
            "consumption_status": db.execute(
                "SELECT status FROM learning_event_consumptions WHERE learning_event_id=?",
                (event_rows[0][0],),
            ).fetchone()[0] if event_rows else None,
            "wrong_question_count": db.execute(
                "SELECT COUNT(*) FROM wrong_questions WHERE student_id='lzz'",
            ).fetchone()[0],
            "review_plan_count": db.execute(
                "SELECT COUNT(*) FROM review_plans WHERE student_id='lzz'",
            ).fetchone()[0],
            "profile_projection_count": db.execute(
                "SELECT COUNT(*) FROM profile_snapshots WHERE trace_id=?",
                (event_rows[0][1],),
            ).fetchone()[0] if event_rows else 0,
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def force_recoverable_projection(db_path: Path, owner_public_id: str) -> None:
    with sqlite3.connect(db_path, timeout=10) as db:
        event_id = db.execute(
            "SELECT id FROM learning_events WHERE owner_public_id=? "
            "AND event_type='formal_exam_submitted'",
            (owner_public_id,),
        ).fetchone()[0]
        row = db.execute(
            "SELECT id, result FROM learning_event_consumptions WHERE learning_event_id=?",
            (event_id,),
        ).fetchone()
        result = json.loads(row[1] or "{}")
        steps = dict(result.get("steps") or {})
        completed_steps = ["profile_snapshot", "path_task"]
        error_code = "f6_e2e_recoverable"
        result["completed_steps"] = completed_steps
        result["steps"] = {step: steps.get(step, {}) for step in completed_steps}
        result["current_step"] = "wrong_review"
        result["next_step"] = "wrong_review"
        result["last_failure"] = {"step": "wrong_review", "error_code": error_code}
        result["aggregate_status"] = "partial"
        result["consistencyToken"] = None
        result.pop("completed_at", None)
        history = list(result.get("state_history") or [])
        if not history or history[-1] != "partial":
            history.append("partial")
        result["state_history"] = history
        snapshots = {}
        for view_id, source in dict(result.get("snapshots") or {}).items():
            snapshot = dict(source)
            step = snapshot.get("step")
            snapshot["status"] = (
                "completed" if step in completed_steps
                else "failed" if step == "wrong_review"
                else "pending"
            )
            if snapshot["status"] != "completed":
                snapshot["version"] = None
            snapshots[view_id] = snapshot
        result["snapshots"] = snapshots
        db.execute(
            "UPDATE learning_event_consumptions SET status='failed', error_code=?, result=? WHERE id=?",
            (error_code, json.dumps(result, ensure_ascii=False), row[0]),
        )
        db.commit()


def page_diagnostics(page: Page, report: dict) -> None:
    page.on("response", lambda response: report["http_errors"].append({
        "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url, "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def visual_contract(page: Page) -> dict[str, object]:
    return page.evaluate("""
      () => {
        const root = document.querySelector('.exam-shell');
        const visible = (element) => {
          const style = getComputedStyle(element);
          const box = element.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
        };
        const nodes = [...root.querySelectorAll('button,h1,h2,h3,h4,p,span,strong,small,label,summary,dt,dd,li')]
          .filter((element) => visible(element) && element.textContent.trim());
        const smallText = nodes.filter((element) => Number.parseFloat(getComputedStyle(element).fontSize) < 13.9)
          .map((element) => ({ text: element.textContent.trim().slice(0, 60), size: getComputedStyle(element).fontSize }));
        const clippedText = nodes.filter((element) => {
          const style = getComputedStyle(element);
          if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false;
          if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false;
          return element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 2;
        }).map((element) => element.textContent.trim().slice(0, 60));
        const gradients = [...root.querySelectorAll('*')].filter(visible)
          .map((element) => getComputedStyle(element).backgroundImage)
          .filter((value) => value && value !== 'none');
        const answerLayout = root.querySelector('.answer-layout');
        const children = answerLayout ? [...answerLayout.children].filter(visible).map((element) => element.getBoundingClientRect()) : [];
        const overlaps = children.flatMap((left, index) => children.slice(index + 1).filter((right) => !(
          left.right <= right.left + 1 || right.right <= left.left + 1 || left.bottom <= right.top + 1 || right.bottom <= left.top + 1
        )).map(() => index));
        return {
          viewport: [innerWidth, innerHeight],
          documentOverflow: document.documentElement.scrollWidth > innerWidth + 1,
          rootOverflow: root.scrollWidth > root.clientWidth + 1,
          smallText,
          clippedText,
          gradients,
          layoutOverlaps: overlaps,
        };
      }
    """)


def capture(page: Page, report: dict, filename: str) -> None:
    metrics = visual_contract(page)
    report["visual"][filename] = metrics
    assert metrics["documentOverflow"] is False, metrics
    assert metrics["rootOverflow"] is False, metrics
    assert metrics["smallText"] == [], metrics
    assert metrics["clippedText"] == [], metrics
    assert metrics["gradients"] == [], metrics
    assert metrics["layoutOverlaps"] == [], metrics
    page.screenshot(path=OUTPUT_DIR / filename, full_page=True, animations="disabled")
    report["screenshots"].append(filename)


def open_exam_builder(page: Page, base_url: str) -> None:
    page.goto(
        f"{base_url}/workspace/assessment/exams?course_id={COURSE_ID}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.get_by_test_id("exam-builder-unlocked").wait_for(state="visible")


def clear_optional_type(page: Page, label: str) -> None:
    button = page.get_by_role("button", name=f"减少{label}")
    while button.is_enabled():
        button.click()


def save_current(page: Page, last: bool = False) -> None:
    label = "保存本题" if last else "保存并下一题"
    page.get_by_role("button", name=label, exact=True).click()
    page.locator(".banner.notice").filter(has_text="题已保存").wait_for(state="visible")


def focus_report(page: Page) -> None:
    page.get_by_test_id("formal-exam-report").evaluate(
        "element => element.scrollIntoView({ block: 'start', inline: 'nearest' })"
    )
    page.evaluate("window.scrollBy(0, -64)")


def complete_journey(page: Page, base_url: str, db_path: Path, fixture: dict, report: dict) -> str:
    open_exam_builder(page, base_url)
    assert page.get_by_text("发布", exact=True).count() == 0
    assert page.get_by_text("复核队列", exact=True).count() == 0
    assert page.get_by_text("Word", exact=True).count() == 0
    assert page.get_by_text("Excel", exact=True).count() == 0
    clear_optional_type(page, "多选题")
    clear_optional_type(page, "填空题")
    page.get_by_label("检验主题").fill("混合检索与可核查来源")
    capture(page, report, "01-blueprint-1440x900.png")

    page.get_by_role("button", name="生成并冻结试卷", exact=True).click()
    page.get_by_test_id("generated-exam-preview").wait_for(state="visible")
    assert page.get_by_text("正确答案", exact=True).count() == 0
    assert page.get_by_text("试卷已经冻结", exact=True).is_visible()
    exam_id = page.url.split("/workspace/assessment/exams/", 1)[1].split("?", 1)[0]
    capture(page, report, "02-frozen-preview-1440x900.png")

    page.get_by_role("button", name="开始作答", exact=True).click()
    page.locator(".option-list button").nth(1).click()
    save_current(page)
    page.reload(wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("exam-taking").wait_for(state="visible")
    assert page.locator(".question-nav button.saved").count() == 1
    assert page.get_by_text("1/4", exact=True).count() >= 1
    report["checks"]["draft_restored_after_refresh"] = True
    capture(page, report, "03-draft-restored-1440x900.png")

    page.locator(".option-list button").nth(1).click()
    save_current(page)
    page.get_by_role("button", name="正确", exact=True).click()
    save_current(page)
    page.locator(".answer-stage textarea").fill("我还不能完整说明这个问题。")
    save_current(page, last=True)
    assert page.get_by_role("button", name="提交试卷", exact=True).is_enabled()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="提交试卷", exact=True).click()
    page.get_by_test_id("formal-exam-report").wait_for(state="visible")
    for label in ["学习画像", "学习路径", "下一日安排", "错题本", "复习中心"]:
        assert page.get_by_text(label, exact=True).count() >= 1, label
    assert page.get_by_text("正确答案", exact=True).count() == 4
    assert page.get_by_text("解析", exact=True).count() == 4
    assert page.locator(".report-sources summary").filter(has_text="本题来源").count() == 4
    focus_report(page)
    capture(page, report, "04-report-1440x900.png")

    first_state = database_state(db_path, fixture["owner_public_id"])
    assert first_state["submission_event_count"] == 1
    assert first_state["attempt_count"] == 4
    assert first_state["consumption_status"] == "processed"

    force_recoverable_projection(db_path, fixture["owner_public_id"])
    page.reload(wait_until="networkidle", timeout=60_000)
    page.get_by_role("button", name="查看报告", exact=True).click()
    page.get_by_text("反馈同步未完成", exact=True).wait_for(state="visible")
    focus_report(page)
    capture(page, report, "05-recoverable-feedback-1440x900.png")
    page.get_by_role("button", name="继续同步反馈", exact=True).click()
    page.get_by_text("学习闭环已同步", exact=True).wait_for(state="visible")
    assert database_state(db_path, fixture["owner_public_id"])["submission_event_count"] == 1
    report["checks"]["recoverable_projection_replayed_without_duplicate_event"] = True
    return exam_id


def verify_secondary_viewport(page: Page, base_url: str, exam_id: str, report: dict) -> None:
    page.goto(
        f"{base_url}/workspace/assessment/exams/{exam_id}?course_id={COURSE_ID}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.get_by_role("button", name="查看报告", exact=True).click()
    page.get_by_test_id("formal-exam-report").wait_for(state="visible")
    focus_report(page)
    capture(page, report, "06-report-1366x768.png")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def run() -> dict:
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = 8996
    base.clear_output()
    db_path = OUTPUT_DIR / "f6_t06.sqlite3"
    port = base.free_port()
    env = base.runtime_env(db_path, port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "f6-t06-isolated-secret"
    fixture = seed_fixture(env)
    process: subprocess.Popen | None = None
    report = {
        "schema_version": "f6-t06.formal-exam-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "checks": {},
        "visual": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_model_called": False,
    }
    try:
        process = base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            base.login(page, base_url)
            exam_id = complete_journey(page, base_url, db_path, fixture, report)
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            base.login(page, base_url)
            verify_secondary_viewport(page, base_url, exam_id, report)
            context.close()
            browser.close()

        report["database"] = database_state(db_path, fixture["owner_public_id"])
        assert report["database"]["exam_count"] == 1
        assert report["database"]["draft_count"] == 4
        assert report["database"]["attempt_count"] == 4
        assert report["database"]["submission_event_count"] == 1
        assert report["database"]["consumption_status"] == "processed"
        assert report["database"]["wrong_question_count"] >= 1
        assert report["database"]["review_plan_count"] >= 1
        assert report["database"]["profile_projection_count"] == 1
        assert report["database"]["integrity"] == "ok"
        assert report["database"]["foreign_key_violations"] == 0
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        base.stop_service(process, port)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT_DIR.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT_DIR / "manifest.json").write_text(
            json.dumps(
                {"schema_version": "f6-t06.evidence-manifest.v1", "files": files},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
