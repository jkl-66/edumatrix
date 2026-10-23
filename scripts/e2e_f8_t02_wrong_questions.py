"""F8-T02 isolated dual-desktop wrong-question acceptance."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, Route, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import e2e_f8_t01_review_calendar as browser_base  # noqa: E402


OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f8_t02_wrong_questions"
BROWSER_DIR = OUTPUT_DIR / "browser"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "f8_t02_runtime.sqlite3"
REPORT_PATH = OUTPUT_DIR / "report.json"
USERNAME = "lzz"
PASSWORD = "404404aA"
COURSE_ID = "demo-course-rag-trust-v1"
PORT_START = int(os.getenv("EDUMATRIX_F8_T02_PORT", "9090"))


def configure_browser_base() -> None:
    browser_base.OUTPUT_DIR = OUTPUT_DIR
    browser_base.BROWSER_DIR = BROWSER_DIR
    browser_base.RUNTIME_DIR = RUNTIME_DIR
    browser_base.DB_PATH = DB_PATH
    browser_base.REPORT_PATH = REPORT_PATH
    browser_base.USERNAME = USERNAME
    browser_base.PASSWORD = PASSWORD
    browser_base.COURSE_ID = COURSE_ID
    browser_base.PORT_START = PORT_START


def runtime_env(port: int) -> dict[str, str]:
    env = browser_base.runtime_env(port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "f8-t02-isolated-secret"
    return env


def seed_fixture(
    env: dict[str, str],
    *,
    preserve_review_plans: bool = False,
) -> dict[str, object]:
    os.environ.update(env)
    from app.competition_demo_seed import seed_competition_demo
    from app.database import (
        DBArtifact,
        DBArtifactVersion,
        DBAssessmentAttempt,
        DBAssessmentExam,
        DBAssessmentExamItem,
        DBAssessmentExamReport,
        DBAssessmentExamResponse,
        DBAssessmentExamSitting,
        DBAssessmentExamVersion,
        DBAssessmentGradingResult,
        DBAssessmentQuestion,
        DBAssessmentQuestionVersion,
        DBChapter,
        DBChapterKnowledgePoint,
        DBCourse,
        DBKnowledgePoint,
        DBMisconceptionReview,
        DBQuizRecord,
        DBReviewPlan,
        DBSourceDocument,
        DBSourceRef,
        DBUser,
        DBWrongQuestion,
        SessionLocal,
        init_db,
    )

    init_db()
    db = SessionLocal()
    try:
        seed_competition_demo(db)
        learner = db.query(DBUser).filter_by(username=USERNAME).one()
        course = db.get(DBCourse, COURSE_ID)
        if course is None:
            raise RuntimeError("F8-T02 fixture course is missing")
        points = (
            db.query(DBKnowledgePoint)
            .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.knowledge_point_id == DBKnowledgePoint.id)
            .join(DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id)
            .filter(DBChapter.course_id == COURSE_ID)
            .order_by(DBKnowledgePoint.title, DBKnowledgePoint.id)
            .all()
        )
        if len(points) < 2:
            raise RuntimeError("F8-T02 fixture requires two canonical knowledge points")
        source_ref = (
            db.query(DBSourceRef)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .filter(
                DBSourceDocument.course_id == COURSE_ID,
                DBSourceDocument.processing_status == "ready",
            )
            .order_by(DBSourceRef.id)
            .first()
        )
        if source_ref is None:
            raise RuntimeError("F8-T02 fixture requires one admitted source reference")
        source_document = db.get(DBSourceDocument, source_ref.source_document_id)

        db.query(DBWrongQuestion).filter_by(student_id=USERNAME).delete(synchronize_session=False)
        if not preserve_review_plans:
            db.query(DBReviewPlan).filter_by(student_id=USERNAME).delete(synchronize_session=False)
        db.flush()

        question_one = DBAssessmentQuestion(
            id="f8-t02-question-one",
            course_id=COURSE_ID,
            owner_public_id=learner.public_id,
            question_type="single_choice",
            origin="legacy",
            status="approved",
        )
        question_two = DBAssessmentQuestion(
            id="f8-t02-question-two",
            course_id=COURSE_ID,
            owner_public_id=learner.public_id,
            question_type="single_choice",
            origin="legacy",
            status="approved",
        )
        db.add_all([question_one, question_two])
        db.flush()
        version_one = DBAssessmentQuestionVersion(
            id="f8-t02-question-version-one",
            question_id=question_one.id,
            version_number=1,
            prompt="梯度下降更新参数时，为什么要沿负梯度方向？",
            options=["A. 让损失上升", "B. 获得局部最速下降方向"],
            answer_key={"choice": "B"},
            scoring_rule={"type": "exact"},
            explanation="负梯度方向对应目标函数在当前位置的局部最速下降方向。",
            primary_knowledge_point_id=points[0].id,
            source_ref_ids=[source_ref.id],
            content_hash="1" * 64,
            created_by_public_id=learner.public_id,
        )
        version_two = DBAssessmentQuestionVersion(
            id="f8-t02-question-version-two",
            question_id=question_two.id,
            version_number=1,
            prompt="学习率过大时，训练过程最可能出现什么现象？",
            options=["A. 在最优点附近震荡", "B. 每一步都严格收敛"],
            answer_key={"choice": "A"},
            scoring_rule={"type": "exact"},
            explanation="过大的学习率可能反复跨过损失谷底并产生震荡。",
            primary_knowledge_point_id=points[1].id,
            source_ref_ids=["f8-t02-withdrawn-source"],
            content_hash="2" * 64,
            created_by_public_id=learner.public_id,
        )
        db.add_all([version_one, version_two])
        db.flush()
        question_one.current_version_id = version_one.id
        question_two.current_version_id = version_two.id

        legacy_quiz = DBQuizRecord(
            id="f8-t02-legacy-quiz",
            student_id=USERNAME,
            question=version_one.prompt,
            student_answer="A",
            correct_answer="B",
            options=version_one.options,
            target_concept=points[0].title,
            accuracy_score=0.0,
            feedback=version_one.explanation,
        )
        db.add(legacy_quiz)
        db.flush()
        wrong_one = DBWrongQuestion(
            student_id=USERNAME,
            quiz_record_id=legacy_quiz.id,
            source_object_id=version_one.id,
            concept_name=points[0].title,
            wrong_reason_category="pending_confirmation",
            notes="先判断梯度指向，再决定参数更新方向。",
            pinned=True,
        )
        wrong_two = DBWrongQuestion(
            student_id=USERNAME,
            source_object_id=version_two.id,
            concept_name=points[1].title,
            wrong_reason_category="pending_confirmation",
            notes="",
        )
        db.add_all([wrong_one, wrong_two])
        db.flush()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        practice_attempt = DBAssessmentAttempt(
            id="f8-t02-practice-attempt",
            owner_public_id=learner.public_id,
            course_id=COURSE_ID,
            question_version_id=version_one.id,
            idempotency_key="f8-t02-practice-attempt-key",
            mode="practice",
            answer={"choice": "A"},
            score=0.0,
            correct=False,
            confidence=0.6,
            duration_seconds=28,
            grading_status="graded",
            feedback_policy="immediate",
            submitted_at=now - timedelta(days=1),
        )
        formal_attempt_one = DBAssessmentAttempt(
            id="f8-t02-formal-attempt-one",
            owner_public_id=learner.public_id,
            course_id=COURSE_ID,
            question_version_id=version_one.id,
            idempotency_key="f8-t02-formal-attempt-one-key",
            mode="formal",
            answer={"choice": "A"},
            score=0.0,
            correct=False,
            confidence=0.7,
            duration_seconds=34,
            grading_status="graded",
            feedback_policy="after_close",
            submitted_at=now - timedelta(hours=2),
        )
        formal_attempt_two = DBAssessmentAttempt(
            id="f8-t02-formal-attempt-two",
            owner_public_id=learner.public_id,
            course_id=COURSE_ID,
            question_version_id=version_two.id,
            idempotency_key="f8-t02-formal-attempt-two-key",
            mode="formal",
            answer={"choice": "B"},
            score=0.0,
            correct=False,
            confidence=0.5,
            duration_seconds=31,
            grading_status="graded",
            feedback_policy="after_close",
            submitted_at=now - timedelta(hours=1),
        )
        db.add_all([practice_attempt, formal_attempt_one, formal_attempt_two])
        db.flush()
        for index, attempt in enumerate((practice_attempt, formal_attempt_one, formal_attempt_two), start=1):
            db.add(DBAssessmentGradingResult(
                id=f"f8-t02-grading-{index}",
                attempt_id=attempt.id,
                owner_public_id=learner.public_id,
                grader_type="deterministic",
                status="completed",
                rubric_version="f8-t02-e2e-v1",
                score=0.0,
                correct=False,
                feedback="当前答案没有满足规范答案。",
                content_hash=str(index + 2) * 64,
            ))
        diagnosis = DBMisconceptionReview(
            id="f8-t02-proposed-diagnosis",
            owner_public_id=learner.public_id,
            attempt_id=formal_attempt_one.id,
            candidate_category="concept_confusion",
            candidate_rationale="把梯度方向误认为参数下降方向。",
            model_confidence=0.78,
            status="proposed",
        )
        db.add(diagnosis)

        exam = DBAssessmentExam(
            id="f8-t02-exam",
            course_id=COURSE_ID,
            owner_public_id=learner.public_id,
            generation_key="f8-t02-exam-key",
            title="F8-T02 智能组卷记录",
            status="closed",
        )
        db.add(exam)
        db.flush()
        exam_version = DBAssessmentExamVersion(
            id="f8-t02-exam-version",
            exam_id=exam.id,
            version_number=1,
            feedback_policy="after_close",
            total_points=20,
            manifest_hash="6" * 64,
        )
        db.add(exam_version)
        db.flush()
        exam.current_version_id = exam_version.id
        item_one = DBAssessmentExamItem(
            id="f8-t02-exam-item-one",
            exam_version_id=exam_version.id,
            question_version_id=version_one.id,
            position=1,
            points=10,
        )
        item_two = DBAssessmentExamItem(
            id="f8-t02-exam-item-two",
            exam_version_id=exam_version.id,
            question_version_id=version_two.id,
            position=2,
            points=10,
        )
        sitting = DBAssessmentExamSitting(
            id="f8-t02-sitting",
            exam_id=exam.id,
            exam_version_id=exam_version.id,
            owner_public_id=learner.public_id,
            status="released",
        )
        db.add_all([item_one, item_two, sitting])
        db.flush()
        db.add_all([
            DBAssessmentExamResponse(
                id="f8-t02-response-one",
                sitting_id=sitting.id,
                exam_item_id=item_one.id,
                attempt_id=formal_attempt_one.id,
            ),
            DBAssessmentExamResponse(
                id="f8-t02-response-two",
                sitting_id=sitting.id,
                exam_item_id=item_two.id,
                attempt_id=formal_attempt_two.id,
            ),
            DBAssessmentExamReport(
                id="f8-t02-report",
                sitting_id=sitting.id,
                report_version=1,
                report_data={"score": 0, "total": 20},
                input_hash="7" * 64,
                content_hash="8" * 64,
            ),
        ])

        artifact = DBArtifact(
            id="f8-t02-handout",
            owner_public_id=learner.public_id,
            course_id=COURSE_ID,
            artifact_type="handout",
            title="负梯度方向个性化讲义",
            status="published",
        )
        db.add(artifact)
        db.flush()
        artifact_version = DBArtifactVersion(
            id="f8-t02-handout-version",
            artifact_id=artifact.id,
            version_number=1,
            content="# 负梯度方向\n\n负梯度给出局部最速下降方向。",
            content_hash="9" * 64,
            metadata_json={
                "resource_type": "handout",
                "knowledge_point_id": points[0].id,
            },
            created_by_public_id=learner.public_id,
        )
        db.add(artifact_version)
        db.flush()
        artifact.current_version_id = artifact_version.id
        if not preserve_review_plans:
            db.add(DBReviewPlan(
                student_id=USERNAME,
                concept=points[0].title,
                next_review_at=now - timedelta(hours=1),
                review_count=2,
                mastery=0.42,
                priority=0.3,
            ))
        db.commit()
        return {
            "owner_public_id": learner.public_id,
            "course_id": COURSE_ID,
            "primary_concept": points[0].title,
            "secondary_concept": points[1].title,
            "primary_wrong_id": wrong_one.id,
            "secondary_wrong_id": wrong_two.id,
            "primary_question_version_id": version_one.id,
            "diagnosis_id": diagnosis.id,
            "source_ref_id": source_ref.id,
            "source_document_id": source_document.id if source_document else None,
        }
    finally:
        db.close()


def parse_json(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def database_state(fixture: dict[str, object]) -> dict[str, object]:
    owner = str(fixture["owner_public_id"])
    question_version = str(fixture["primary_question_version_id"])
    diagnosis_id = str(fixture["diagnosis_id"])
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        profile_row = db.execute(
            "SELECT concept_mastery FROM student_profiles WHERE student_id=?", (USERNAME,)
        ).fetchone()
        diagnosis_row = db.execute(
            "SELECT status, confirmed_category FROM misconception_reviews WHERE id=?", (diagnosis_id,)
        ).fetchone()
        decision_event = db.execute(
            "SELECT event_type, mastery_eligible, completion_effect FROM learning_events "
            "WHERE owner_public_id=? AND idempotency_key=?",
            (owner, f"misconception-decision:{diagnosis_id}"),
        ).fetchone()
        return {
            "learning_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=?", (owner,)
            ).fetchone()[0],
            "profile_snapshots": db.execute(
                "SELECT COUNT(*) FROM profile_snapshots WHERE owner_public_id=?", (owner,)
            ).fetchone()[0],
            "assessment_attempts": db.execute(
                "SELECT COUNT(*) FROM assessment_attempts WHERE owner_public_id=?", (owner,)
            ).fetchone()[0],
            "primary_attempts": db.execute(
                "SELECT COUNT(*) FROM assessment_attempts WHERE owner_public_id=? AND question_version_id=?",
                (owner, question_version),
            ).fetchone()[0],
            "correct_primary_attempts": db.execute(
                "SELECT COUNT(*) FROM assessment_attempts WHERE owner_public_id=? "
                "AND question_version_id=? AND correct=1",
                (owner, question_version),
            ).fetchone()[0],
            "wrong_questions": db.execute(
                "SELECT id, source_object_id, notes, pinned FROM wrong_questions "
                "WHERE student_id=? ORDER BY id", (USERNAME,),
            ).fetchall(),
            "primary_wrong_rows": db.execute(
                "SELECT COUNT(*) FROM wrong_questions WHERE student_id=? AND source_object_id=?",
                (USERNAME, question_version),
            ).fetchone()[0],
            "diagnosis": list(diagnosis_row) if diagnosis_row else None,
            "decision_event": list(decision_event) if decision_event else None,
            "retest_tasks": db.execute(
                "SELECT COUNT(*) FROM assessment_retest_tasks WHERE owner_public_id=?", (owner,)
            ).fetchone()[0],
            "profile_mastery": parse_json(profile_row[0]) if profile_row else None,
            "path_states": db.execute(
                "SELECT id, status FROM path_nodes WHERE learning_path_id IN "
                "(SELECT id FROM learning_paths WHERE owner_public_id=?) ORDER BY id", (owner,),
            ).fetchall(),
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


READ_ONLY_STATE_KEYS = (
    "learning_events",
    "profile_snapshots",
    "assessment_attempts",
    "primary_attempts",
    "correct_primary_attempts",
    "wrong_questions",
    "primary_wrong_rows",
    "diagnosis",
    "decision_event",
    "retest_tasks",
    "profile_mastery",
    "path_states",
)


def assert_read_only(before: dict[str, object], after: dict[str, object]) -> None:
    for key in READ_ONLY_STATE_KEYS:
        assert after[key] == before[key], (key, before[key], after[key])


def attach_diagnostics(page: Page, report: dict[str, object]) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.hostname and parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(response.url)
        if response.status < 400:
            return
        failure = {"status": response.status, "url": response.url}
        note_conflict = report.get("diagnostic_expectations", {}).get("note_conflict")
        expected_note_conflict = (
            isinstance(note_conflict, dict)
            and note_conflict.get("active") is True
            and response.status == note_conflict.get("status")
            and response.url == note_conflict.get("url")
        )
        if expected_note_conflict:
            note_conflict["response_seen"] = True
            report["expected_http_errors"].append(failure)
        elif response.status == 503 and "/quiz/wrong-questions/" in response.url:
            report["expected_http_errors"].append(failure)
        else:
            report["http_errors"].append(failure)

    page.on("response", on_response)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url,
        "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    def on_console(message) -> None:
        if message.type != "error":
            return
        note_conflict = report.get("diagnostic_expectations", {}).get("note_conflict")
        expected_note_conflict = (
            isinstance(note_conflict, dict)
            and note_conflict.get("active") is True
            and note_conflict.get("response_seen") is True
            and message.text == "Failed to load resource: the server responded with a status of 409 (Conflict)"
        )
        target = (
            "expected_console_errors"
            if expected_note_conflict or "503" in message.text
            else "console_errors"
        )
        report[target].append(message.text)

    page.on("console", on_console)


def visual_metrics(page: Page) -> dict[str, object]:
    return page.evaluate("""
      () => {
        const root = document.querySelector('[data-testid="wrong-question-workspace"]')
        if (!root) return { missingRoot: true }
        const visible = element => {
          const style = getComputedStyle(element), box = element.getBoundingClientRect()
          const closedDetails = element.closest('details:not([open])')
          if (closedDetails && !closedDetails.querySelector(':scope > summary')?.contains(element)) return false
          return style.display !== 'none' && style.visibility !== 'hidden' &&
            Number(style.opacity) > 0 && box.width > 1 && box.height > 1
        }
        const textNodes = [...root.querySelectorAll('button,a,h1,h2,h3,p,span,strong,small,label,dt,dd,li')]
          .filter(element => visible(element) && (element.textContent || '').trim())
        const clipped = textNodes.filter(element => {
          const style = getComputedStyle(element)
          if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
          if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
          return element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 2
        }).map(element => ({
          tag: element.tagName,
          text: element.textContent.trim().slice(0, 70),
        })).slice(0, 30)
        const smallText = textNodes.filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 13.9)
          .map(element => ({
            text: element.textContent.trim().slice(0, 60),
            size: getComputedStyle(element).fontSize,
          })).slice(0, 30)
        const controls = [...root.querySelectorAll('button,a[href],input,select,textarea')].filter(visible)
        const collisions = []
        for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
          const left = controls[i], right = controls[j]
          if (left.contains(right) || right.contains(left)) continue
          const a = left.getBoundingClientRect(), b = right.getBoundingClientRect()
          const overlapWidth = Math.min(a.right, b.right) - Math.max(a.left, b.left)
          const overlapHeight = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
          if (overlapWidth > 3 && overlapHeight > 3) collisions.push([
            (left.textContent || left.getAttribute('aria-label') || '').trim().slice(0, 36),
            (right.textContent || right.getAttribute('aria-label') || '').trim().slice(0, 36),
          ])
        }
        const forbidden = new Set([
          'rgb(16, 185, 129)', 'rgb(34, 197, 94)', 'rgb(59, 130, 246)',
          'rgb(14, 165, 233)', 'rgb(139, 92, 246)', 'rgb(168, 85, 247)',
          'rgb(120, 53, 15)', 'rgb(146, 64, 14)',
        ])
        const forbiddenThemeHits = [...root.querySelectorAll('*')].filter(visible).flatMap(element => {
          const style = getComputedStyle(element)
          return [style.color, style.backgroundColor, style.borderColor]
            .filter(value => forbidden.has(value))
            .map(value => ({ value, text: element.textContent.trim().slice(0, 60) }))
        })
        const backgrounds = [...root.querySelectorAll('*')].filter(visible)
          .map(element => getComputedStyle(element).backgroundImage)
          .filter(value => value && value !== 'none')
        const grid = root.querySelector('.wrong-grid')?.getBoundingClientRect()
        const list = root.querySelector('.question-list')?.getBoundingClientRect()
        const detail = root.querySelector('.detail-pane')?.getBoundingClientRect()
        return {
          missingRoot: false,
          viewport: [innerWidth, innerHeight],
          pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
          rootOverflow: root.scrollWidth > root.clientWidth + 1,
          clipped,
          smallText,
          collisions,
          forbiddenThemeHits,
          backgrounds,
          primaryActions: [...root.querySelectorAll('.primary-action')].filter(visible).length,
          layout: grid && list && detail ? {
            gridWidth: grid.width,
            listWidth: list.width,
            detailWidth: detail.width,
            overlap: Math.max(0, list.right - detail.left),
          } : null,
        }
      }
    """)


def assert_visual(
    page: Page,
    report: dict[str, object],
    key: str,
    *,
    primary_actions: int = 1,
) -> None:
    metrics = visual_metrics(page)
    report["visual"][key] = metrics
    assert metrics["missingRoot"] is False, metrics
    assert metrics["pageOverflow"] is False, metrics
    assert metrics["rootOverflow"] is False, metrics
    assert metrics["clipped"] == [], metrics
    assert metrics["smallText"] == [], metrics
    assert metrics["collisions"] == [], metrics
    assert metrics["forbiddenThemeHits"] == [], metrics
    assert metrics["backgrounds"] == [], metrics
    assert metrics["primaryActions"] == primary_actions, metrics
    assert metrics["layout"] is not None, metrics
    assert 300 <= metrics["layout"]["listWidth"] <= 380, metrics
    assert metrics["layout"]["overlap"] == 0, metrics


def capture(page: Page, report: dict[str, object], name: str) -> None:
    browser_base.capture(page, report, name)


def wrong_question_url(base_url: str, fixture: dict[str, object]) -> str:
    return (
        f"{base_url}/workspace/review/wrong-questions"
        f"?course_id={fixture['course_id']}&wrong_id={fixture['primary_wrong_id']}"
    )


def wait_for_loaded_questions(page: Page, count: int = 2) -> None:
    page.get_by_test_id("wrong-question-workspace").wait_for(state="visible")
    page.get_by_label("错题加载中").wait_for(state="hidden")
    page.get_by_test_id("wrong-question-list-item").first.wait_for(state="visible")
    assert page.get_by_test_id("wrong-question-list-item").count() == count


def select_question(page: Page, concept: str) -> None:
    row = page.get_by_test_id("wrong-question-list-item").filter(has_text=concept)
    assert row.count() == 1
    row.click()
    page.get_by_test_id("wrong-question-detail").get_by_role("heading", name=concept, exact=True).wait_for()


def run_primary(
    page: Page,
    base_url: str,
    fixture: dict[str, object],
    report: dict[str, object],
) -> None:
    fault = {"remaining": 1}

    def fail_first_load(route: Route) -> None:
        if fault["remaining"]:
            fault["remaining"] -= 1
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "隔离验收注入的一次性加载失败"}, ensure_ascii=False),
            )
        else:
            route.continue_()

    page.route("**/quiz/wrong-questions/**", fail_first_load)
    page.goto(wrong_question_url(base_url, fixture), wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("wrong-question-error").wait_for(state="visible")
    assert_visual(page, report, "load_failure_1440x900", primary_actions=0)
    capture(page, report, "01-load-failure-1440x900.png")
    page.get_by_test_id("wrong-question-error").get_by_role("button", name="重试", exact=True).click()
    page.get_by_test_id("wrong-question-error").wait_for(state="hidden")
    wait_for_loaded_questions(page)
    assert len(report["expected_http_errors"]) == 1

    history = page.get_by_test_id("wrong-question-attempt-history")
    assert "2 次提交" in history.locator("summary").inner_text()
    assert history.get_by_text("测验题资源", exact=True).count() == 1
    assert history.get_by_text("智能组卷", exact=True).count() == 1
    assert_visual(page, report, "merged_history_1440x900")
    capture(page, report, "02-merged-history-1440x900.png")

    before_browse = database_state(fixture)
    source_filter = page.get_by_role("combobox", name="来源", exact=True)
    source_filter.select_option("formal_exam")
    assert page.get_by_test_id("wrong-question-list-item").count() == 2
    source_filter.select_option("quiz_resource")
    assert page.get_by_test_id("wrong-question-list-item").count() == 1
    source_filter.select_option("all")
    page.get_by_placeholder("搜索知识点、题目或笔记").fill("不存在的知识点")
    page.get_by_test_id("wrong-question-filter-empty").wait_for(state="visible")
    capture(page, report, "03-filter-empty-1440x900.png")
    page.get_by_label("清除筛选").first.click()
    wait_for_loaded_questions(page)

    select_question(page, str(fixture["primary_concept"]))
    source_section = page.get_by_test_id("wrong-question-sources")
    source_section.locator("summary").click()
    source_button = source_section.locator(".source-body section").first.get_by_role("button").first
    assert source_button.is_enabled()
    source_button.click()
    page.locator(".reader-page").wait_for(state="visible")
    page.get_by_text("正在打开原文", exact=True).wait_for(state="hidden")
    assert f"source_ref_id={fixture['source_ref_id']}" in page.url
    capture(page, report, "04-source-round-trip-1440x900.png")
    page.go_back(wait_until="networkidle")
    wait_for_loaded_questions(page)
    select_question(page, str(fixture["primary_concept"]))
    after_browse = database_state(fixture)
    assert_read_only(before_browse, after_browse)
    report["database"]["read_only_before"] = before_browse
    report["database"]["read_only_after"] = after_browse

    page.get_by_test_id("wrong-question-diagnosis").get_by_role(
        "button", name="接受候选", exact=True
    ).click()
    page.get_by_text("已记录你的决定", exact=True).wait_for(state="visible")
    after_decision = database_state(fixture)
    assert after_decision["diagnosis"] == ["accepted", "concept_confusion"], after_decision
    assert after_decision["learning_events"] == after_browse["learning_events"] + 1, after_decision
    assert after_decision["retest_tasks"] == after_browse["retest_tasks"] + 1, after_decision
    assert after_decision["profile_mastery"] == after_browse["profile_mastery"], after_decision
    assert after_decision["path_states"] == after_browse["path_states"], after_decision
    assert after_decision["decision_event"] == ["misconception_decided", 0, "progress"], after_decision
    report["database"]["after_diagnosis"] = after_decision
    capture(page, report, "05-confirmed-diagnosis-1440x900.png")

    page.get_by_test_id("wrong-question-primary-action").click()
    redo = page.get_by_test_id("wrong-question-redo")
    redo.wait_for(state="visible")
    redo.locator('input[type="radio"][value="B"]').check()
    redo.get_by_role("button", name="提交并判分", exact=True).click()
    redo.get_by_text("回答正确，新的强证据已进入学习聚合。", exact=True).wait_for(
        state="visible", timeout=60_000
    )
    assert "3 次提交" in page.get_by_test_id("wrong-question-attempt-history").locator("summary").inner_text()
    assert page.get_by_test_id("wrong-question-attempt-history").locator(".attempt-list li").count() == 3
    after_redo = database_state(fixture)
    assert after_redo["assessment_attempts"] == after_decision["assessment_attempts"] + 1, after_redo
    assert after_redo["primary_attempts"] == after_decision["primary_attempts"] + 1, after_redo
    assert after_redo["correct_primary_attempts"] == after_decision["correct_primary_attempts"] + 1, after_redo
    assert len(after_redo["wrong_questions"]) == len(after_decision["wrong_questions"]), after_redo
    assert after_redo["primary_wrong_rows"] == 1, after_redo
    assert after_redo["learning_events"] > after_decision["learning_events"], after_redo
    report["database"]["after_redo"] = after_redo
    assert_visual(page, report, "redo_complete_1440x900")
    capture(page, report, "06-redo-complete-1440x900.png")

    page.reload(wait_until="networkidle")
    wait_for_loaded_questions(page)
    select_question(page, str(fixture["primary_concept"]))
    assert "3 次提交" in page.get_by_test_id("wrong-question-attempt-history").locator("summary").inner_text()
    assert page.get_by_test_id("wrong-question-attempt-history").locator(".attempt-list li").count() == 3
    assert_visual(page, report, "refresh_history_1440x900")
    capture(page, report, "07-refresh-history-1440x900.png")
    report["checks"].update({
        "load_failure_recovered": True,
        "practice_and_formal_filters": True,
        "same_question_attempts_merged": True,
        "source_round_trip": True,
        "diagnosis_confirmed_without_mastery_change": True,
        "redo_created_one_attempt": True,
        "refresh_preserved_history": True,
        "ordinary_browsing_zero_mastery_writes": True,
    })


def run_secondary(
    page: Page,
    base_url: str,
    fixture: dict[str, object],
    report: dict[str, object],
) -> None:
    before = database_state(fixture)
    page.goto(wrong_question_url(base_url, fixture), wait_until="networkidle", timeout=60_000)
    wait_for_loaded_questions(page)
    select_question(page, str(fixture["primary_concept"]))
    assert "3 次提交" in page.get_by_test_id("wrong-question-attempt-history").locator("summary").inner_text()
    page.get_by_role("combobox", name="来源", exact=True).select_option("formal_exam")
    assert page.get_by_test_id("wrong-question-list-item").count() == 2
    page.get_by_role("combobox", name="来源", exact=True).select_option("all")
    assert_visual(page, report, "stable_workspace_1366x768")
    capture(page, report, "08-stable-workspace-1366x768.png")
    after = database_state(fixture)
    assert_read_only(before, after)
    report["database"]["secondary_read_only_before"] = before
    report["database"]["secondary_read_only_after"] = after


def run() -> dict[str, object]:
    configure_browser_base()
    browser_base.reset_output()
    port = browser_base.free_port()
    env = runtime_env(port)
    fixture = seed_fixture(env)
    base_url = f"http://127.0.0.1:{port}"
    report: dict[str, object] = {
        "schema_version": "f8-t02.wrong-question-desktop.v1",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "viewports": [[1440, 900], [1366, 768]],
        "isolated_database": str(DB_PATH),
        "single_service": True,
        "single_chromium_instance": True,
        "deterministic_model_only": True,
        "external_model_called": False,
        "fixture": fixture,
        "screenshots": [],
        "checks": {},
        "visual": {},
        "database": {"initial": database_state(fixture)},
        "expected_http_errors": [],
        "expected_console_errors": [],
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
    }
    process = None
    try:
        process = browser_base.start_service(env, port)
        with sync_playwright() as playwright:
            browser: Browser = playwright.chromium.launch(headless=True)
            try:
                primary_context = browser.new_context(
                    viewport={"width": 1440, "height": 900}, locale="zh-CN"
                )
                primary = primary_context.new_page()
                attach_diagnostics(primary, report)
                browser_base.login(primary, base_url)
                run_primary(primary, base_url, fixture, report)
                primary_context.close()

                secondary_context = browser.new_context(
                    viewport={"width": 1366, "height": 768}, locale="zh-CN"
                )
                secondary = secondary_context.new_page()
                attach_diagnostics(secondary, report)
                browser_base.login(secondary, base_url)
                run_secondary(secondary, base_url, fixture, report)
                secondary_context.close()
            finally:
                browser.close()
        final_state = database_state(fixture)
        report["database"]["final"] = final_state
        assert final_state["integrity"] == "ok", final_state
        assert final_state["foreign_key_violations"] == 0, final_state
        assert len(report["expected_http_errors"]) == 1, report["expected_http_errors"]
        assert len(report["expected_console_errors"]) == 1, report["expected_console_errors"]
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
        browser_base.stop_service(process, port)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result["status"],
        "screenshots": len(result["screenshots"]),
        "checks": result["checks"],
        "database": result["database"],
    }, ensure_ascii=False, indent=2))
