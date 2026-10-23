"""Verify the NC-CORE-06 canonical assessment workspace in Chromium."""

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
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-CORE-06" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_core_assessment_e2e.db"
EVIDENCE_DB = OUTPUT / "assessment_evidence.db"
PORT = 8785
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-core-assessment-2026!"


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
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "next-core-assessment-e2e-secret",
        "EDUMATRIX_DEMO_MODE": "0",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "trusted_local",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {
        "schema_version": "next.assessment-e2e.v1",
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
                    suffix = str(int(time.time()))
                    registrations = {}
                    for role in ("teacher", "learner", "other"):
                        username = f"assessment_{role}_{suffix}"
                        response = page.request.post(f"{BASE_URL}/api/auth/register", data={
                            "username": username, "password": PASSWORD,
                            "display_name": f"测评验收{role}",
                        })
                        assert response.ok, response.text()
                        registrations[role] = {**response.json(), "username": username}
                    with sqlite3.connect(DB_PATH) as fixture_db:
                        fixture_db.execute(
                            "UPDATE users SET role='teacher' WHERE public_id=?",
                            (registrations["teacher"]["user_id"],),
                        )
                        fixture_db.execute(
                            """INSERT INTO courses(
                            id,version,title,subject,description,domain_pack,language,content_origin,
                            license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                            (
                                "assessment-e2e-course", "1.0.0", "机器学习能力测评", "人工智能",
                                "冻结合成测评课程", "assessment-e2e", "zh-CN", "synthetic-e2e",
                                "Synthetic test fixture", "public", "published",
                                registrations["teacher"]["user_id"], "1.0.0", "{}",
                            ),
                        )
                        fixture_db.commit()

                    teacher_headers = {"Authorization": f"Bearer {registrations['teacher']['access_token']}"}
                    question_specs = [
                        {
                            "question_type": "short_answer",
                            "prompt": "简述训练集与验证集分离的主要目的。",
                            "options": [],
                            "answer_key": {"reference_answer": "验证集用于估计泛化表现并支持模型选择。"},
                            "scoring_rule": {
                                "type": "rubric", "version": "rubric-e2e-v1", "correct_threshold": 0.6,
                                "criteria": [{"id": "generalization", "label": "泛化评估", "description": "说明泛化评估或模型选择", "weight": 1.0}],
                            },
                            "irt_parameters": {"alpha": [0.9, 0.4, 0.7], "beta": [0.2, 0.2, 0.2], "gamma": 0.0},
                        },
                        {
                            "question_type": "code",
                            "prompt": "实现 add(a, b)，返回两个输入之和。",
                            "options": [],
                            "answer_key": {
                                "entrypoint": "add",
                                "hidden_tests": [
                                    {"args": [2, 3], "expected": 5},
                                    {"args": [-4, 9], "expected": 5},
                                ],
                            },
                            "scoring_rule": {"type": "hidden_tests", "version": "hidden-e2e-v1", "correct_threshold": 1.0},
                            "irt_parameters": {"alpha": [0.4, 1.3, 0.6], "beta": [0.1, 0.1, 0.1], "gamma": 0.0},
                        },
                        {
                            "question_type": "true_false",
                            "prompt": "逻辑回归可以直接输出任意实数作为分类概率。",
                            "options": [], "answer_key": {"value": False},
                            "scoring_rule": {"type": "exact", "version": "objective-v1"},
                            "irt_parameters": {"alpha": [0.8, 0.4, 0.5], "beta": [-0.4, -0.4, -0.4], "gamma": 0.5},
                        },
                        {
                            "question_type": "multiple_choice",
                            "prompt": "以下哪些方法可以缓解过拟合？",
                            "options": ["A. L2 正则化", "B. 数据增强", "C. 无限增加模型参数"],
                            "answer_key": {"choices": ["A", "B"]},
                            "scoring_rule": {"type": "exact", "version": "objective-v1", "partial_credit": True},
                            "irt_parameters": {"alpha": [1.1, 0.6, 0.7], "beta": [0.2, 0.2, 0.2], "gamma": 0.25},
                        },
                        {
                            "question_type": "single_choice",
                            "prompt": "Sigmoid 函数在逻辑回归中的主要作用是什么？",
                            "options": ["A. 直接删除异常值", "B. 将线性输出映射到 0 到 1", "C. 自动生成训练标签"],
                            "answer_key": {"choice": "B"},
                            "scoring_rule": {"type": "exact", "version": "objective-v1"},
                            "irt_parameters": {"alpha": [1.0, 0.5, 0.8], "beta": [0.0, 0.0, 0.0], "gamma": 0.25},
                        },
                    ]
                    created = []
                    for spec in question_specs:
                        response = page.request.post(
                            f"{BASE_URL}/api/v1/m5/assessment/questions",
                            headers=teacher_headers,
                            data={
                                "course_id": "assessment-e2e-course",
                                "question_type": spec["question_type"],
                                "origin": "manual",
                                "version": {
                                    "prompt": spec["prompt"], "options": spec["options"],
                                    "answer_key": spec["answer_key"], "scoring_rule": spec["scoring_rule"],
                                    "irt_parameters": spec["irt_parameters"],
                                },
                            },
                        )
                        assert response.ok, response.text()
                        item = response.json()["question_version"]
                        approval = page.request.post(
                            f"{BASE_URL}/api/v1/m5/assessment/questions/{item['question_id']}/status",
                            headers=teacher_headers,
                            data={"expected_current_version_id": item["id"], "status": "approved"},
                        )
                        assert approval.ok, approval.text()
                        created.append(item)

                    learner = registrations["learner"]
                    learner_headers = {"Authorization": f"Bearer {learner['access_token']}"}
                    catalog = page.request.get(f"{BASE_URL}/api/v1/m5/assessment/questions", headers=learner_headers)
                    assert catalog.ok and len(catalog.json()["items"]) == 5
                    assert all("answer_key" not in item for item in catalog.json()["items"])
                    code_public = next(item for item in catalog.json()["items"] if item["question_type"] == "code")
                    assert code_public["response_spec"]["hidden_test_count"] == 2
                    assert "hidden_tests" not in json.dumps(code_public, ensure_ascii=False)

                    page.goto(f"{BASE_URL}/login", wait_until="commit", timeout=30_000)
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'student')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_display_name', '测评验收学习者')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [learner["access_token"], learner["username"]],
                    )
                    page.goto(f"{BASE_URL}/assessment", wait_until="commit", timeout=30_000)
                    page.get_by_test_id("assessment-workspace").wait_for(state="visible", timeout=20_000)
                    page.get_by_role("heading", name="Sigmoid 函数在逻辑回归中的主要作用是什么？", exact=True).wait_for(state="visible")
                    page.get_by_text("B. 将线性输出映射到 0 到 1", exact=True).click()
                    page.get_by_test_id("assessment-submit").click()
                    result = page.get_by_test_id("assessment-result")
                    result.get_by_text("100 分", exact=True).wait_for(state="visible")
                    result.get_by_text("服务端客观评分", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "01-desktop-assessment-result"))

                    with sqlite3.connect(DB_PATH) as evidence_db:
                        attempt_id = evidence_db.execute(
                            "SELECT id FROM assessment_attempts WHERE owner_public_id=? ORDER BY submitted_at DESC LIMIT 1",
                            (learner["user_id"],),
                        ).fetchone()[0]
                        answer_leak = evidence_db.execute(
                            "SELECT COUNT(*) FROM audit_logs WHERE metadata_json LIKE '%linear output%' OR metadata_json LIKE '%将线性输出%'",
                        ).fetchone()[0]
                        assert answer_leak == 0

                    denied = page.request.get(
                        f"{BASE_URL}/api/v1/m5/assessment/attempts/{attempt_id}",
                        headers={"Authorization": f"Bearer {registrations['other']['access_token']}"},
                    )
                    assert denied.status == 403
                    report["checks"]["owner_isolation"] = {"cross_owner_attempt_status": denied.status}

                    page.reload(wait_until="commit", timeout=30_000)
                    page.get_by_test_id("assessment-result").get_by_text("100 分", exact=True).wait_for(state="visible")
                    report["checks"]["refresh_recovery"] = True

                    page.get_by_test_id("cat-next").click()
                    page.locator(".question-meta").get_by_text("mirt-d-optimal-v1", exact=True).wait_for(state="visible")
                    assert page.get_by_role("heading", name="Sigmoid 函数在逻辑回归中的主要作用是什么？", exact=True).count() == 0
                    report["checks"]["cat_selection"] = True

                    page.get_by_role("button", name="代码题 实现 add(a, b)，返回两个输入之和。").click()
                    page.get_by_role("heading", name="实现 add(a, b)，返回两个输入之和。", exact=True).wait_for(state="visible")
                    page.locator(".code-answer textarea").fill("def add(a, b):\n    return a + b")
                    page.get_by_test_id("assessment-submit").click()
                    code_result = page.get_by_test_id("assessment-result")
                    code_result.get_by_text("100 分", exact=True).wait_for(state="visible", timeout=20_000)
                    code_result.get_by_text("代码隐藏测试", exact=True).wait_for(state="visible")
                    code_evidence_text = code_result.locator(".code-evidence").inner_text()
                    assert "隐藏测试 2/2" in code_evidence_text and "套件" in code_evidence_text
                    assert "expected" not in code_evidence_text.lower()
                    report["screenshots"].append(shot(page, "02-desktop-hidden-code-result"))

                    with sqlite3.connect(DB_PATH) as evidence_db:
                        code_attempt_id = evidence_db.execute(
                            "SELECT id FROM assessment_attempts WHERE owner_public_id=? AND question_version_id=?",
                            (learner["user_id"], code_public["id"]),
                        ).fetchone()[0]
                        code_grade = evidence_db.execute(
                            "SELECT grader_type,score,evidence FROM assessment_grading_results WHERE attempt_id=?",
                            (code_attempt_id,),
                        ).fetchone()
                    persisted_code_evidence = json.loads(code_grade[2])
                    assert code_grade[0] == "code" and code_grade[1] == 1.0
                    assert persisted_code_evidence["hidden_inputs_included"] is False
                    assert persisted_code_evidence["hidden_expected_included"] is False
                    denied_code = page.request.get(
                        f"{BASE_URL}/api/v1/m5/assessment/attempts/{code_attempt_id}",
                        headers={"Authorization": f"Bearer {registrations['other']['access_token']}"},
                    )
                    assert denied_code.status == 403
                    page.reload(wait_until="commit", timeout=30_000)
                    page.get_by_role("button", name="代码题 实现 add(a, b)，返回两个输入之和。").click()
                    page.get_by_test_id("assessment-result").get_by_text("代码隐藏测试", exact=True).wait_for(state="visible")
                    report["checks"]["hidden_code"] = {
                        "passed": 2, "total": 2, "suite_hash_present": bool(persisted_code_evidence["suite_hash"]),
                        "hidden_inputs_included": False, "hidden_expected_included": False,
                        "cross_owner_attempt_status": denied_code.status, "refresh_recovery": True,
                        "execution_boundary": "trusted_local_research_only_no_container_isolation",
                    }

                    page.get_by_role("button", name="简答题 简述训练集与验证集分离的主要目的。").click()
                    page.locator(".text-answer").fill("验证集用于观察未参与训练的数据表现，并据此选择模型。")
                    page.get_by_test_id("assessment-submit").click()
                    ai_result = page.get_by_test_id("assessment-result")
                    ai_result.get_by_text("待评分", exact=True).wait_for(state="visible", timeout=20_000)
                    ai_result.get_by_text("AI 智能初评", exact=True).wait_for(state="visible")
                    ai_result.get_by_text("AI 智能初评暂不可用，本次作答已保存。", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "03-desktop-ai-grading-failure"))
                    with sqlite3.connect(DB_PATH) as evidence_db:
                        ai_row = evidence_db.execute(
                            """SELECT g.status,g.score,g.correct,g.evidence
                            FROM assessment_grading_results g JOIN assessment_attempts a ON a.id=g.attempt_id
                            WHERE a.owner_public_id=? AND a.question_version_id=?""",
                            (learner["user_id"], next(item["id"] for item in catalog.json()["items"] if item["question_type"] == "short_answer")),
                        ).fetchone()
                    assert ai_row[:3] == ("failed", None, None)
                    assert json.loads(ai_row[3])["error_code"] == "ai_grading_unavailable"
                    report["checks"]["ai_initial_grading_failure"] = {
                        "status": "failed", "score": None, "correct": None,
                        "answer_persisted": True, "fake_score_emitted": False,
                        "external_model_calls": False,
                    }

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(500)
                    mobile = page.evaluate("""() => {
                      const shell = document.querySelector('[data-testid="assessment-workspace"]')?.getBoundingClientRect()
                      const stage = document.querySelector('.question-stage')?.getBoundingClientRect()
                      return { width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
                        shell: shell && {x: shell.x, width: shell.width}, stage: stage && {x: stage.x, width: stage.width} }
                    }""")
                    assert mobile["width"] == 390 and mobile["scrollWidth"] <= 390
                    assert mobile["shell"] and mobile["shell"]["width"] >= 350
                    assert mobile["stage"] and mobile["stage"]["width"] >= 350
                    report["screenshots"].append(shot(page, "04-mobile-assessment"))
                    report["checks"]["mobile_viewport"] = mobile

                    with sqlite3.connect(DB_PATH) as evidence_db:
                        grade = evidence_db.execute(
                            "SELECT grader_type,score,correct FROM assessment_grading_results WHERE attempt_id=?",
                            (attempt_id,),
                        ).fetchone()
                        ability = evidence_db.execute(
                            "SELECT response_count,lock_version,last_attempt_id FROM assessment_ability_states WHERE owner_public_id=?",
                            (learner["user_id"],),
                        ).fetchone()
                        trace_count = evidence_db.execute(
                            "SELECT COUNT(*) FROM assessment_selection_traces WHERE owner_public_id=?",
                            (learner["user_id"],),
                        ).fetchone()[0]
                        assert grade == ("deterministic", 1.0, 1)
                        assert ability[0] == 2 and ability[2] == code_attempt_id
                        assert trace_count >= 1
                    report["checks"]["canonical_evidence"] = {
                        "grader_type": grade[0], "score": grade[1], "ability_response_count": ability[0],
                        "cat_trace_count": trace_count, "answer_text_in_audit": False,
                    }
                    report["result"] = "passed"
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
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target)
                report["checks"]["sqlite_integrity"] = target.execute("PRAGMA integrity_check").fetchone()[0]
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT / "manifest.json").write_text(json.dumps({
            "schema_version": "next.assessment-manifest.v1", "files": files,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
