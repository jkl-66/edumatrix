"""Verify the learner-controlled misconception and delayed-retest UI journey."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "M5_完全体核心学习平台" / "evidence" / "misconception-retest-e2e-20260802"
DB_PATH = ROOT / "outputs" / "_m5_misconception_e2e_runtime.db"
EVIDENCE_DB = OUTPUT / "m5_misconception_evidence.db"
BASE_URL = "http://127.0.0.1:8767"
PASSWORD = "M5-misconception-e2e-2026!"


def wait_port(open_: bool, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", 8767)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port 8767 did not become {'open' if open_ else 'closed'}")


def stop(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True, text=True, timeout=15,
    )
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, timeout=15)


def shot(page: Page, name: str, *, full_page: bool = False) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
    return path.name


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_manifest() -> None:
    files = [
        {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
    ]
    (OUTPUT / "manifest.json").write_text(
        json.dumps({"schema_version": "m5.misconception-e2e-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def unlink(path: Path) -> None:
    if path.exists():
        path.unlink()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        unlink(Path(f"{DB_PATH}{suffix}"))
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "m5-misconception-isolated-secret-2026",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": "8767",
        "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {
        "scope": "legacy wrong answer, canonical diagnosis confirmation, delayed retest scheduling, and refresh recovery",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "isolated_database": str(EVIDENCE_DB.relative_to(ROOT)).replace("\\", "/"),
        "checks": {},
        "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    username = f"m5_diagnosis_{int(time.time())}"
                    registration = page.request.post(
                        f"{BASE_URL}/api/auth/register",
                        data={"username": username, "password": PASSWORD, "display_name": "M5 错因验收学生"},
                    )
                    assert registration.ok, registration.text()
                    token = registration.json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}
                    quiz_id = f"m5-diagnosis-{int(time.time())}"
                    with sqlite3.connect(DB_PATH, timeout=30) as setup_db:
                        setup_db.execute(
                            """INSERT INTO quiz_records(
                            id,student_id,question,student_answer,correct_answer,
                            ai_confidence,student_confidence,accuracy_score,target_concept,
                            feedback,next_action,attempt_number,session_id,options,
                            irt_alpha,irt_beta,irt_gamma,irt_alpha_vec,irt_beta_vec,created_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                            (
                                quiz_id, username, "梯度下降中，参数更新应沿哪个方向？", "", "B",
                                0.0, 0.0, 0.0, "梯度下降", "", "review", 1, "m5-e2e",
                                json.dumps(["A. 梯度方向", "B. 梯度反方向", "C. 随机方向"]),
                                1.0, 0.0, 0.25, json.dumps([1.0, 0.8, 0.6]), json.dumps([0.0, 0.1, -0.1]),
                            ),
                        )
                        setup_db.commit()
                    wrong_answer = "A"
                    evaluated = page.request.post(
                        f"{BASE_URL}/api/quiz/evaluate",
                        headers=headers,
                        data={
                            "quiz_id": quiz_id, "student_id": username,
                            "answer": wrong_answer, "student_confidence": 0.3,
                            "attempt_number": 1, "duration_seconds": 8,
                        },
                    )
                    assert evaluated.ok, evaluated.text()
                    evaluation = evaluated.json()
                    assert evaluation["accuracy_score"] < 0.6, evaluation
                    assert evaluation["canonical_assessment"]["attempt_id"]
                    assert evaluation["misconception_candidate"]["status"] == "proposed"
                    report["checks"]["trusted_auto_candidate"] = {
                        "accuracy_score": evaluation["accuracy_score"],
                        "attempt_id": evaluation["canonical_assessment"]["attempt_id"],
                        "review_id": evaluation["misconception_candidate"]["id"],
                    }

                    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                    page.evaluate(
                        "([token, username]) => { localStorage.setItem('edumatrix_token', token); localStorage.setItem('edumatrix_role', 'student'); localStorage.setItem('edumatrix_username', username); localStorage.setItem('edumatrix_student_id', username); localStorage.setItem('edumatrix_display_name', 'M5 错因验收学生'); localStorage.setItem('edumatrix_onboarded', 'true') }",
                        [token, username],
                    )
                    page.goto(f"{BASE_URL}/wrong-questions", wait_until="networkidle")
                    wrong_card = page.locator(".card").filter(has_text="概念未掌握").last
                    wrong_card.get_by_text("梯度下降", exact=True).wait_for(state="visible", timeout=20_000)
                    wrong_card.get_by_text("梯度下降", exact=True).click()
                    proposed_badge = page.get_by_text("待你确认", exact=True)
                    proposed_badge.wait_for(state="visible", timeout=20_000)
                    proposed_badge.scroll_into_view_if_needed()
                    page.wait_for_timeout(700)
                    report["screenshots"].append(shot(page, "01-proposed-diagnosis"))
                    page.get_by_label("修改错因分类").select_option("knowledge_gap")
                    page.get_by_placeholder("补充你的判断（可选）").fill("我需要重新学习定义和适用条件")
                    page.get_by_role("button", name="按所选分类修改").click()
                    scheduled = page.get_by_text("延迟复测：", exact=False)
                    scheduled.wait_for(state="visible", timeout=20_000)
                    scheduled.scroll_into_view_if_needed()
                    page.wait_for_timeout(700)
                    report["screenshots"].append(shot(page, "02-confirmed-and-scheduled"))

                    wrong_items = page.request.get(
                        f"{BASE_URL}/api/quiz/wrong-questions/{username}", headers=headers,
                    ).json()
                    diagnosis = wrong_items[0]["canonical_diagnosis"]
                    assert diagnosis["review"]["status"] == "modified"
                    assert diagnosis["review"]["confirmed_category"] == "knowledge_gap"
                    assert diagnosis["retest_task"]["status"] == "scheduled"
                    assert diagnosis["retest_task"]["stable_mastery"] is False
                    report["checks"]["learner_decision"] = diagnosis["review"]["status"]
                    report["checks"]["retest_task"] = diagnosis["retest_task"]

                    plan_response = page.request.post(
                        f"{BASE_URL}/api/v1/m5/plans", headers=headers,
                        data={
                            "title": "错因延迟复测计划",
                            "idempotency_key": f"m5-retest-plan-{quiz_id}",
                            "spec": {
                                "goal": "通过延迟复测形成稳定掌握证据",
                                "nodes": [{
                                    "node_key": "assessment-retest",
                                    "node_type": "assessment",
                                    "target_object_id": diagnosis["retest_task"]["question_version_id"],
                                    "title": "梯度下降错因延迟复测",
                                    "resource_status": "existing",
                                    "estimate_min_minutes": 5,
                                    "estimate_max_minutes": 10,
                                }],
                            },
                        },
                    )
                    assert plan_response.ok, plan_response.text()
                    plan = plan_response.json()
                    confirmed = page.request.post(
                        f"{BASE_URL}/api/v1/m5/plans/{plan['id']}/confirm", headers=headers,
                        data={"expected_lock_version": plan["lock_version"]},
                    )
                    assert confirmed.ok, confirmed.text()
                    path_id = confirmed.json()["path"]["id"]

                    with sqlite3.connect(DB_PATH, timeout=30) as time_db:
                        time_db.execute(
                            "UPDATE assessment_retest_tasks SET due_at=datetime('now','-1 minute') WHERE id=?",
                            (diagnosis["retest_task"]["id"],),
                        )
                        time_db.commit()
                    report["checks"]["test_clock_control"] = "isolated due_at advanced to one minute before now"

                    page.goto(f"{BASE_URL}/review", wait_until="networkidle")
                    start_button = page.get_by_role("button", name="开始延迟复测")
                    start_button.wait_for(state="visible", timeout=20_000)
                    start_button.click()
                    page.get_by_text("梯度下降中，参数更新应沿哪个方向？", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("B. 梯度反方向", exact=True).click()
                    report["screenshots"].append(shot(page, "04-due-retest-ready"))
                    page.get_by_role("button", name="提交复测").click()
                    page.get_by_label("统一待复习队列").get_by_text(
                        "复测通过，强证据已回流学习路径。", exact=True,
                    ).wait_for(state="visible", timeout=20_000)
                    queue_after = page.request.get(f"{BASE_URL}/api/v1/m5/review-queue", headers=headers).json()["items"]
                    assert all(item["source_type"] != "misconception_review" for item in queue_after)
                    report["screenshots"].append(shot(page, "05-retest-passed-path-evidence"))

                    paths = page.request.get(
                        f"{BASE_URL}/api/v1/m5/paths?include_archived=true", headers=headers,
                    ).json()["items"]
                    completed_path = next(item for item in paths if item["id"] == path_id)
                    assert completed_path["status"] == "completed"
                    assert completed_path["nodes"][0]["status"] == "completed"
                    report["checks"]["path_reflow"] = {
                        "path_id": path_id,
                        "path_status": completed_path["status"],
                        "node_status": completed_path["nodes"][0]["status"],
                        "misconception_queue_exited": True,
                        "remaining_queue_sources": sorted({item["source_type"] for item in queue_after}),
                    }

                    page.goto(f"{BASE_URL}/wrong-questions", wait_until="networkidle")
                    wrong_card = page.locator(".card").filter(has_text="概念未掌握").last
                    wrong_card.get_by_text("梯度下降", exact=True).click()
                    page.get_by_text("稳定掌握证据已形成并回流路径", exact=False).wait_for(state="visible", timeout=20_000)
                    report["checks"]["refresh_recovery"] = True
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.reload(wait_until="networkidle")
                    wrong_card = page.locator(".card").filter(has_text="概念未掌握").last
                    wrong_card.get_by_text("梯度下降", exact=True).click()
                    stable_notice = page.get_by_text("稳定掌握证据已形成并回流路径", exact=False)
                    stable_notice.wait_for(state="visible", timeout=20_000)
                    stable_notice.scroll_into_view_if_needed()
                    page.wait_for_timeout(700)
                    report["screenshots"].append(shot(page, "03-mobile-refresh-recovered"))
                    report["checks"]["mobile_viewport"] = {"width": 390, "height": 844}
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
                report["checks"]["sqlite_integrity"] = destination.execute("PRAGMA integrity_check").fetchone()[0]
                report["checks"]["canonical_counts"] = {
                    "attempts": destination.execute("SELECT COUNT(*) FROM assessment_attempts").fetchone()[0],
                    "misconceptions": destination.execute("SELECT COUNT(*) FROM misconception_reviews").fetchone()[0],
                    "retest_tasks": destination.execute("SELECT COUNT(*) FROM assessment_retest_tasks").fetchone()[0],
                    "delayed_retest_events": destination.execute("SELECT COUNT(*) FROM learning_events WHERE event_type='delayed_retest_passed'").fetchone()[0],
                    "completed_paths": destination.execute("SELECT COUNT(*) FROM learning_paths WHERE status='completed'").fetchone()[0],
                }
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
