"""Verify the FC5 student judge journey against isolated canonical evidence."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT = Path(os.environ.get(
    "EDUMATRIX_E2E_OUTPUT_DIR",
    ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC5-01A" / "browser-e2e",
))
DB_PATH = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_fc5_student_journey_runtime.db"))
EVIDENCE_DB = OUTPUT / "fc5_student_journey_evidence.db"
PORT = int(os.environ.get("EDUMATRIX_E2E_PORT", "8838"))
BASE = f"http://127.0.0.1:{PORT}"
USERNAME = "fc5_student_journey"
PASSWORD = "FC5-student-journey-e2e-2026!"
COURSE_ID = "fc5-student-journey-course"


def wait_port(open_: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(.25)
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_:
            return
        time.sleep(.2)
    raise RuntimeError(f"port {PORT} state timeout")


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, 15)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path.name


def write_manifest() -> None:
    files = [
        {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
    ]
    (OUTPUT / "manifest.json").write_text(json.dumps({
        "schema_version": "fc5.student-judge-journey-e2e-manifest.v1",
        "files": files,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def seed_course() -> None:
    from app.database import DBCourse, SessionLocal, init_db

    init_db()
    with SessionLocal() as db:
        db.add(DBCourse(
            id=COURSE_ID,
            version="frozen-demo-v1",
            title="人工智能技能训练课程（冻结合成演示）",
            subject="人工智能",
            status="published",
            manifest_version="fc5-e2e-v1",
            manifest_data={"data_class": "synthetic_e2e_fixture"},
        ))
        db.commit()


def seed_canonical_evidence(username: str) -> dict[str, str]:
    """Prepare isolated E2E fixture facts; this is not a user-facing shortcut."""
    from app.database import (
        DBArtifact, DBArtifactVersion, DBAssessmentAttempt, DBAssessmentExam,
        DBAssessmentExamReport, DBAssessmentExamSitting, DBAssessmentExamVersion,
        DBAssessmentQuestion, DBAssessmentQuestionVersion, DBAssessmentRetestTask,
        DBLearningPath, DBMisconceptionReview, DBPathNode, DBPlanDraft, DBPlanVersion,
        DBProfileSnapshot, DBUser, SessionLocal,
    )

    with SessionLocal() as db:
        owner = db.query(DBUser).filter_by(username=username).one()
        profile = DBProfileSnapshot(
            owner_public_id=owner.public_id, profile_version="fc5-e2e-profile-v1",
            snapshot={"data_class": "synthetic_e2e_fixture", "level": "baseline"},
            content_hash="1" * 64, trace_id="fc5-e2e-profile-trace",
        )
        question = DBAssessmentQuestion(
            owner_public_id=owner.public_id, course_id=COURSE_ID,
            question_type="single_choice", origin="manual", status="approved",
        )
        db.add_all([profile, question])
        db.flush()
        question_version = DBAssessmentQuestionVersion(
            question_id=question.id, version_number=1, prompt="2 + 2 = ?", options=["4"],
            answer_key={"choice": "4"}, scoring_rule={"kind": "exact"}, explanation="4",
            misconception_tags=[], bloom_level="understand",
            irt_parameters={"difficulty": 0.1, "discrimination": 1.0, "guessing": 0.0},
            source_ref_ids=[], content_hash="2" * 64, created_by_public_id=owner.public_id,
        )
        db.add(question_version)
        db.flush()
        question.current_version_id = question_version.id
        diagnostic = DBAssessmentAttempt(
            owner_public_id=owner.public_id, course_id=COURSE_ID,
            question_version_id=question_version.id, idempotency_key="fc5-e2e-diagnostic",
            mode="diagnostic", answer={"choice": "4"}, score=1, correct=True,
            grading_status="graded",
        )
        plan = DBPlanDraft(
            owner_public_id=owner.public_id, course_id=COURSE_ID, title="FC5 个性学习路径",
            status="confirmed", idempotency_key="fc5-e2e-plan",
        )
        db.add_all([diagnostic, plan])
        db.flush()
        plan_version = DBPlanVersion(
            plan_draft_id=plan.id, version_number=1, profile_snapshot_id=profile.id,
            content={"data_class": "synthetic_e2e_fixture", "nodes": []},
            content_hash="3" * 64, created_by_public_id=owner.public_id,
        )
        db.add(plan_version)
        db.flush()
        plan.current_version_id = plan_version.id
        plan.confirmed_version_id = plan_version.id

        artifacts: dict[str, DBArtifact] = {}
        for index, kind in enumerate(("lesson", "lab_guide", "tiered_quiz"), 4):
            artifact = DBArtifact(
                owner_public_id=owner.public_id, course_id=COURSE_ID,
                artifact_type=kind, title=f"FC5 {kind}", status="approved",
            )
            db.add(artifact)
            db.flush()
            version = DBArtifactVersion(
                artifact_id=artifact.id, version_number=1,
                content=json.dumps({"data_class": "synthetic_e2e_fixture", "kind": kind}),
                content_format="json", content_hash=str(index) * 64,
                created_by_public_id=owner.public_id,
            )
            db.add(version)
            db.flush()
            artifact.current_version_id = version.id
            artifacts[kind] = artifact

        lab = DBArtifact(
            owner_public_id=owner.public_id, course_id=COURSE_ID,
            artifact_type="interactive_lab_instance", title="FC5 本地交互实验", status="approved",
        )
        db.add(lab)
        db.flush()
        lab_version = DBArtifactVersion(
            artifact_id=lab.id, version_number=1,
            content=json.dumps({
                "data_class": "synthetic_e2e_fixture", "status": "passed",
                "hidden_acceptance": {"passed": True},
            }),
            content_format="json", content_hash="7" * 64,
            created_by_public_id=owner.public_id,
        )
        db.add(lab_version)
        db.flush()
        lab.current_version_id = lab_version.id

        path = DBLearningPath(
            owner_public_id=owner.public_id, course_id=COURSE_ID,
            source_plan_version_id=plan_version.id, status="active",
        )
        db.add(path)
        db.flush()
        node = DBPathNode(
            learning_path_id=path.id, node_key="fc5-lab", sequence=1, node_type="artifact",
            target_object_id=lab.id, title="完成本地交互实验", status="pending",
            prerequisites=[], resource_status="existing", estimate_min_minutes=10,
            estimate_max_minutes=20,
        )

        exam = DBAssessmentExam(
            owner_public_id=owner.public_id, course_id=COURSE_ID,
            title="FC5 正式测评", status="published",
        )
        db.add(exam)
        db.flush()
        exam_version = DBAssessmentExamVersion(
            exam_id=exam.id, version_number=1, instructions="冻结合成验收测评",
            feedback_policy="after_close", total_points=100,
            manifest_hash="8" * 64, created_by_public_id=owner.public_id,
        )
        db.add(exam_version)
        db.flush()
        exam.current_version_id = exam_version.id
        sitting = DBAssessmentExamSitting(
            exam_id=exam.id, exam_version_id=exam_version.id,
            owner_public_id=owner.public_id, status="released",
            released_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add(sitting)
        db.flush()
        report = DBAssessmentExamReport(
            sitting_id=sitting.id, report_version=1,
            report_data={"data_class": "synthetic_e2e_fixture", "score": 100},
            input_hash="9" * 64, content_hash="a" * 64,
            created_by_public_id=owner.public_id,
        )
        retest_attempt = DBAssessmentAttempt(
            owner_public_id=owner.public_id, course_id=COURSE_ID,
            question_version_id=question_version.id, idempotency_key="fc5-e2e-retest",
            mode="retest", answer={"choice": "4"}, score=1, correct=True,
            grading_status="graded",
        )
        db.add(retest_attempt)
        db.flush()
        review = DBMisconceptionReview(
            owner_public_id=owner.public_id, attempt_id=diagnostic.id,
            candidate_category="knowledge_gap", status="accepted",
            evidence={"data_class": "synthetic_e2e_fixture"},
        )
        db.add(review)
        db.flush()
        retest = DBAssessmentRetestTask(
            owner_public_id=owner.public_id, misconception_review_id=review.id,
            source_attempt_id=diagnostic.id, question_version_id=question_version.id,
            course_id=COURSE_ID, due_at=datetime.now(timezone.utc).replace(tzinfo=None),
            status="completed", completion_attempt_id=retest_attempt.id,
            completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db.add_all([node, report, retest])
        db.commit()
        return {"owner_public_id": owner.public_id, "path_id": path.id, "node_id": node.id, "lab_id": lab.id}


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "fc5-student-journey-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
    })
    os.environ.update(env)
    seed_course()
    report = {
        "scope": "FC5 student evidence journey, visit non-completion, 7/8 to real path event to 8/8, refresh and mobile",
        "fixture_boundary": "Canonical records inserted only into an isolated E2E database; final path transition uses the production learning-event API.",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {}, "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    registration = page.request.post(f"{BASE}/api/auth/register", data={
                        "username": USERNAME, "password": PASSWORD, "display_name": "FC5 学生旅程验收账号",
                    })
                    assert registration.ok, registration.text()
                    identity = registration.json()
                    headers = {"Authorization": f"Bearer {identity['access_token']}"}
                    page.goto(f"{BASE}/login", wait_until="networkidle")
                    page.evaluate("""([token, username]) => {
                        localStorage.setItem('edumatrix_token', token);
                        localStorage.setItem('edumatrix_role', 'student');
                        localStorage.setItem('edumatrix_username', username);
                        localStorage.setItem('edumatrix_display_name', 'FC5 学生旅程验收账号');
                        localStorage.setItem('edumatrix_onboarded', 'true');
                    }""", [identity["access_token"], USERNAME])
                    page.goto(f"{BASE}/judge-journey/student", wait_until="networkidle")
                    page.get_by_text("尚未开始学生黄金旅程", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("证据驱动完成", exact=True).wait_for(state="visible")
                    page.get_by_label("目标课程").select_option(COURSE_ID)
                    report["screenshots"].append(shot(page, "01-empty-evidence-boundary"))
                    page.get_by_role("button", name="新建旅程").click()
                    page.get_by_text("0 / 8", exact=True).wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "02-started-zero-of-eight"))

                    workspace = page.request.get(f"{BASE}/api/v1/competition-journeys/student", headers=headers).json()
                    run = workspace["runs"][0]
                    visited_routes = []
                    for step in run["steps"]:
                        page.goto(f"{BASE}/judge-journey/student", wait_until="networkidle")
                        key = page.locator(".body > span").get_by_text(step["key"], exact=True)
                        article = page.locator(".steps article").filter(has=key)
                        article.get_by_role("button").click()
                        page.wait_for_url(f"**{step['route']}**", timeout=20_000)
                        visited_routes.append(step["route"])
                    after_visits = page.request.get(
                        f"{BASE}/api/v1/competition-journeys/student/runs/{run['id']}", headers=headers,
                    ).json()
                    assert after_visits["progress"]["completed"] == 0
                    assert len(after_visits["visits"]) == 8
                    page.goto(f"{BASE}/judge-journey/student", wait_until="networkidle")
                    page.get_by_text("0 / 8", exact=True).wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "03-eight-visits-still-zero"))

                    fixture = seed_canonical_evidence(USERNAME)
                    page.get_by_role("button", name="刷新学生旅程").click()
                    page.get_by_text("7 / 8", exact=True).wait_for(state="visible", timeout=20_000)
                    path_update = page.locator(".steps article").filter(
                        has=page.locator(".body > span").get_by_text("path_update", exact=True),
                    )
                    path_update.get_by_text("需要在本旅程中更新路径", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "04-canonical-evidence-seven-of-eight"))

                    event = page.request.post(f"{BASE}/api/v1/m5/learning-events", headers=headers, data={
                        "schema_version": "m5.learning-event.v1",
                        "idempotency_key": "fc5-e2e-path-update",
                        "event_type": "code_tests_passed",
                        "course_id": COURSE_ID,
                        "object_type": "artifact",
                        "object_id": fixture["lab_id"],
                        "source": "sandbox",
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                        "payload": {"passed_count": 3, "total_count": 3, "actual_minutes": 12, "data_class": "synthetic_e2e_fixture"},
                    })
                    assert event.ok, event.text()
                    consumption = event.json()["consumption"]
                    assert consumption["status"] == "processed"
                    assert consumption["result"]["old_status"] == "pending"
                    assert consumption["result"]["new_status"] == "completed"
                    page.get_by_role("button", name="刷新学生旅程").click()
                    page.get_by_text("8 / 8", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("八步证据闭环完成", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "05-completed-eight-of-eight"))

                    page.reload(wait_until="networkidle")
                    page.get_by_text("8 / 8", exact=True).wait_for(state="visible", timeout=20_000)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.reload(wait_until="networkidle")
                    page.get_by_text("八步证据闭环完成", exact=True).wait_for(state="visible", timeout=20_000)
                    document_width = page.evaluate("document.documentElement.scrollWidth")
                    assert document_width <= 390
                    report["screenshots"].append(shot(page, "06-mobile-refresh-recovery"))

                    final = page.request.get(
                        f"{BASE}/api/v1/competition-journeys/student/runs/{run['id']}", headers=headers,
                    ).json()
                    assert final["status"] == "completed" and final["progress"]["completed"] == 8
                    assert all(step["complete"] for step in final["steps"])
                    report["checks"] = {
                        "run_id": run["id"], "course_id": COURSE_ID,
                        "initial_progress": 0, "visit_count": len(after_visits["visits"]),
                        "progress_after_visits": after_visits["progress"]["completed"],
                        "visited_routes": visited_routes, "fixture_progress": 7,
                        "path_event_consumption": consumption, "final_progress": 8,
                        "final_status": final["status"], "refresh_recovered": True,
                        "mobile": {"width": 390, "document_width": document_width},
                    }
                    report["result"] = "passed"
                except Exception:
                    try:
                        report["screenshots"].append(shot(page, "error"))
                    except Exception:
                        pass
                    raise
                finally:
                    context.close()
                    browser.close()
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as destination:
                source.backup(destination)
                checks = report.setdefault("checks", {})
                checks["sqlite_integrity"] = destination.execute("PRAGMA integrity_check").fetchone()[0]
                checks["migration_055"] = destination.execute(
                    "SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_055'"
                ).fetchone()[0] == 1
                checks["journey_runs"] = destination.execute("SELECT COUNT(*) FROM competition_journey_runs").fetchone()[0]
                checks["journey_visits"] = destination.execute("SELECT COUNT(*) FROM competition_journey_visits").fetchone()[0]
                checks["completed_paths"] = destination.execute(
                    "SELECT COUNT(*) FROM learning_paths WHERE status='completed'"
                ).fetchone()[0]
                checks["processed_path_events"] = destination.execute(
                    "SELECT COUNT(*) FROM learning_event_consumptions WHERE status='processed'"
                ).fetchone()[0]
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
