"""Verify the NC-CORE-07 formal exam, review and report workflow in Chromium."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-CORE-07" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_core_formal_exam_e2e.db"
EVIDENCE_DB = OUTPUT / "formal_exam_evidence.db"
PORT = 8786
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-core-formal-exam-2026!"


def wait_port(open_: bool, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} state timeout")


def stop(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, 15)


def login(page: Page, registration: dict[str, Any], role: str, display_name: str) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="commit", timeout=30_000)
    page.evaluate(
        """([token, username, role, name]) => {
          localStorage.setItem('edumatrix_token', token)
          localStorage.setItem('edumatrix_role', role)
          localStorage.setItem('edumatrix_username', username)
          localStorage.setItem('edumatrix_student_id', username)
          localStorage.setItem('edumatrix_display_name', name)
          localStorage.setItem('edumatrix_onboarded', 'true')
        }""",
        [registration["access_token"], registration["username"], role, display_name],
    )


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path.name


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        "EDUMATRIX_DB_PATH": str(DB_PATH), "EDUMATRIX_AUTH_SECRET_KEY": "next-formal-exam-e2e-secret",
        "EDUMATRIX_DEMO_MODE": "0", "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic", "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "", "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0", "EDUMATRIX_HOST": "127.0.0.1", "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {"schema_version": "next.formal-exam-e2e.v1", "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": {}, "screenshots": []}
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                suffix = str(int(time.time()))
                registrations = {}
                for role in ("teacher", "learner", "other"):
                    username = f"formal_{role}_{suffix}"
                    response = page.request.post(f"{BASE_URL}/api/auth/register", data={"username": username, "password": PASSWORD, "display_name": f"正式考试验收{role}"})
                    assert response.ok, response.text()
                    registrations[role] = {**response.json(), "username": username}
                with sqlite3.connect(DB_PATH) as db:
                    db.execute("UPDATE users SET role='teacher' WHERE public_id=?", (registrations["teacher"]["user_id"],))
                    db.execute("""INSERT INTO courses(id,version,title,subject,description,domain_pack,language,content_origin,license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""", (
                        "formal-e2e-course", "1.0.0", "机器学习正式考试", "人工智能", "冻结合成考试课程", "formal-e2e", "zh-CN", "synthetic-e2e",
                        "Synthetic fixture", "private", "published", registrations["teacher"]["user_id"], "1.0.0", "{}",
                    ))
                    for role, course_role in (("teacher", "teacher"), ("learner", "student")):
                        db.execute("INSERT INTO course_memberships(id,course_id,user_public_id,role,status,created_at) VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)",
                                   (f"membership-{role}", "formal-e2e-course", registrations[role]["user_id"], course_role, "active"))
                    db.commit()

                teacher_headers = {"Authorization": f"Bearer {registrations['teacher']['access_token']}"}
                learner_headers = {"Authorization": f"Bearer {registrations['learner']['access_token']}"}
                question_response = page.request.post(f"{BASE_URL}/api/v1/m5/assessment/questions", headers=teacher_headers, data={
                    "course_id": "formal-e2e-course", "question_type": "single_choice", "origin": "manual",
                    "version": {"prompt": "Sigmoid 函数的主要作用是什么？", "options": ["A. 删除异常值", "B. 将线性输出映射到 0 到 1", "C. 生成标签"],
                                "answer_key": {"choice": "B"}, "scoring_rule": {"type": "exact", "version": "objective-v1"}},
                })
                assert question_response.ok, question_response.text()
                question = question_response.json()["question_version"]
                approval = page.request.post(f"{BASE_URL}/api/v1/m5/assessment/questions/{question['question_id']}/status", headers=teacher_headers,
                                             data={"expected_current_version_id": question["id"], "status": "approved"})
                assert approval.ok, approval.text()
                exam_response = page.request.post(f"{BASE_URL}/api/v1/m5/assessment/exams", headers=teacher_headers, data={
                    "course_id": "formal-e2e-course", "title": "机器学习能力认证模拟考试", "duration_minutes": 30,
                    "feedback_policy": "after_close", "items": [{"question_version_id": question["id"], "points": 100, "required": True}],
                })
                assert exam_response.ok, exam_response.text()
                exam = exam_response.json()
                for target in ("published",):
                    response = page.request.post(f"{BASE_URL}/api/v1/m5/assessment/exams/{exam['id']}/transition", headers=teacher_headers,
                                                 data={"expected_lock_version": exam["lock_version"], "target_status": target})
                    assert response.ok, response.text(); exam = response.json()
                assigned = page.request.post(f"{BASE_URL}/api/v1/m5/assessment/exams/{exam['id']}/assignments", headers=teacher_headers,
                                             data={"learner_public_id": registrations["learner"]["user_id"]})
                assert assigned.ok, assigned.text()
                opened = page.request.post(f"{BASE_URL}/api/v1/m5/assessment/exams/{exam['id']}/transition", headers=teacher_headers,
                                           data={"expected_lock_version": exam["lock_version"], "target_status": "open"})
                assert opened.ok, opened.text(); exam = opened.json()

                login(page, registrations["learner"], "student", "正式考试验收学习者")
                page.goto(f"{BASE_URL}/formal-exams", wait_until="commit", timeout=30_000)
                page.get_by_test_id("formal-exam-workspace").wait_for(state="visible", timeout=20_000)
                page.get_by_role("button", name="开始", exact=True).click()
                page.get_by_role("option", name="B. 将线性输出映射到 0 到 1").wait_for(state="attached")
                page.locator(".item-list select").select_option("B")
                page.get_by_role("button", name="保存答案", exact=True).click()
                page.get_by_text("服务端客观评分", exact=True).wait_for(state="visible")
                page.get_by_role("button", name="交卷", exact=True).click()
                page.get_by_text("试卷已提交", exact=False).wait_for(state="visible")
                report["screenshots"].append(shot(page, "01-learner-submitted"))

                closed = page.request.post(f"{BASE_URL}/api/v1/m5/assessment/exams/{exam['id']}/transition", headers=teacher_headers,
                                           data={"expected_lock_version": exam["lock_version"], "target_status": "closed"})
                assert closed.ok, closed.text()
                page.reload(wait_until="commit", timeout=30_000)
                page.get_by_role("button", name="生成报告", exact=True).click()
                page.get_by_test_id("formal-exam-report").get_by_text("100%", exact=True).wait_for(state="visible")
                page.get_by_role("button", name="申请复核", exact=True).click()
                page.get_by_text("复核申请已进入教师队列。", exact=True).wait_for(state="visible")
                report["screenshots"].append(shot(page, "02-learner-report"))

                login(page, registrations["teacher"], "teacher", "正式考试验收教师")
                page.goto(f"{BASE_URL}/formal-exams", wait_until="commit", timeout=30_000)
                page.get_by_text("复核队列", exact=True).wait_for(state="visible", timeout=20_000)
                page.get_by_role("button", name="完成复核", exact=True).click()
                page.get_by_text("人工复核（演示角色）已追加", exact=False).wait_for(state="visible")
                report["screenshots"].append(shot(page, "03-teacher-review"))

                with sqlite3.connect(DB_PATH) as db:
                    sitting_id = db.execute("SELECT id FROM assessment_exam_sittings WHERE exam_id=?", (exam["id"],)).fetchone()[0]
                    initial_grade_count = db.execute("SELECT COUNT(*) FROM assessment_grading_results WHERE owner_public_id=?", (registrations["learner"]["user_id"],)).fetchone()[0]
                regenerated = page.request.post(f"{BASE_URL}/api/v1/m5/assessment/exam-sittings/{sitting_id}/reports", headers=teacher_headers)
                assert regenerated.ok and regenerated.json()["report_version"] == 2, regenerated.text()
                report_id = regenerated.json()["id"]
                assert initial_grade_count == 2
                json_export = page.request.get(
                    f"{BASE_URL}/api/v1/m5/assessment/exam-reports/{report_id}/export/json",
                    headers=teacher_headers,
                )
                csv_export = page.request.get(
                    f"{BASE_URL}/api/v1/m5/assessment/exam-reports/{report_id}/export/csv",
                    headers=teacher_headers,
                )
                assert json_export.ok and json_export.json()["report_version"] == 2
                assert csv_export.ok
                assert "position,question_version_id,points,score,status,grading_label" in csv_export.text()
                assert "人工复核（演示角色）" in csv_export.text()
                denied = page.request.get(f"{BASE_URL}/api/v1/m5/assessment/exam-reports/{report_id}", headers={"Authorization": f"Bearer {registrations['other']['access_token']}"})
                assert denied.status == 403
                report["checks"]["cross_owner_report_status"] = denied.status
                report["checks"]["report_version_after_review"] = 2
                report["checks"]["initial_and_human_grade_count"] = initial_grade_count
                report["checks"]["authenticated_exports"] = {
                    "json_status": json_export.status, "csv_status": csv_export.status,
                    "json_report_version": 2, "csv_has_review_label": True,
                }

                page.set_viewport_size({"width": 390, "height": 844})
                page.reload(wait_until="commit", timeout=30_000)
                page.get_by_test_id("formal-exam-workspace").wait_for(state="visible")
                page.wait_for_function("""() => {
                  const workspace = document.querySelector('[data-testid="formal-exam-workspace"]')
                  return workspace && getComputedStyle(workspace).opacity === '1'
                }""")
                geometry = page.evaluate("""() => ({width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
                  shellWidth: document.querySelector('[data-testid="formal-exam-workspace"]')?.getBoundingClientRect().width})""")
                assert geometry["width"] == 390 and geometry["scrollWidth"] <= 390 and geometry["shellWidth"] >= 350
                report["checks"]["mobile_viewport"] = geometry
                report["checks"]["mobile_transition_settled"] = True
                report["screenshots"].append(shot(page, "04-mobile-review"))
                browser.close()

        with sqlite3.connect(DB_PATH) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            assert integrity == "ok"
        report["checks"]["sqlite_integrity"] = integrity
        report["checks"]["refresh_recovery"] = True
        report["checks"]["external_model_calls"] = False
        shutil.copyfile(DB_PATH, EVIDENCE_DB)
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        stop(backend)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        report_path = OUTPUT / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        files = [path for path in OUTPUT.iterdir() if path.is_file() and path.name != "manifest.json"]
        manifest = {"schema_version": "next.formal-exam-manifest.v1", "files": [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)} for path in sorted(files)
        ]}
        (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
