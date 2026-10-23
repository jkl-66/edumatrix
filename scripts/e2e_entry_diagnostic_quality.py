"""Real Chromium acceptance for entry-diagnostic question quality."""

from __future__ import annotations

import hashlib
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
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "ENTRY-DIAGNOSTIC-QUALITY-01"
OUTPUT_DIR = EVIDENCE / "browser"
DB_PATH = EVIDENCE / "diagnostic_quality_runtime.db"
PORT = int(os.getenv("EDUMATRIX_ENTRY_DIAGNOSTIC_PORT", "8934"))
BASE_URL = f"http://127.0.0.1:{PORT}"
COURSE_ID = "course-ai-deep-learning-agents-v1"
QUESTION_COUNT = 20
PASSWORD = "EntryDiagnostic-Quality-2026!"
USERNAME = f"entry_quality_{int(time.time())}"


def wait_port(expected: bool, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.25)
    raise RuntimeError(f"port {PORT} did not reach expected state {expected}")


def clear_evidence() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    if DB_PATH.exists():
        DB_PATH.unlink()


def seed_isolated_database(env: dict[str, str]) -> None:
    setup = r'''
from app.database import DBProfileSnapshot, DBStudentProfile, DBUser, SessionLocal, init_db, DBCourse
from app.auth import get_password_hash
from course_catalog import MASTER_COURSE_ID, seed_default_courses, ensure_primary_course_membership
import hashlib, json, os
init_db()
db = SessionLocal()
seed_default_courses(db)
username, password = os.environ["ENTRY_DIAGNOSTIC_USERNAME"], os.environ["ENTRY_DIAGNOSTIC_PASSWORD"]
user = DBUser(username=username, hashed_password=get_password_hash(password), role="student", display_name="入学测评质量验收学生")
db.add(user)
db.flush()
ensure_primary_course_membership(db, user)
course = db.get(DBCourse, MASTER_COURSE_ID)
profile = DBStudentProfile(
    student_id=username,
    target_course=course.title if course else "",
    knowledge_base="Python、线性代数、概率；正在补强深度学习与大模型工程",
    major="计算机科学与技术",
    cognitive_style="先看直觉例子，再分步推导，最后用代码验证",
    motivation_type="岗位项目",
    learning_goals=["完成一个可用于 AI 应用开发岗位的 RAG 与 Agent 项目"],
    interaction_preferences=["中文", "例子", "分步推导", "代码实践"],
    weak_points=["注意力机制", "模型评估", "检索评测"],
    concept_mastery={"overall": 0.35},
)
db.add(profile)
snapshot = {
    "schema_version": "entry.diagnostic.quality.profile.v1",
    "course_id": MASTER_COURSE_ID,
    "mastery": 0.35,
    "self_report": {
        "goal": {"summary": "完成一个可用于 AI 应用开发岗位的 RAG 与 Agent 项目"},
        "foundation": {"summary": "有 Python、线性代数和概率基础，神经网络与检索评测仍需巩固"},
        "preference": {"summary": "先看直觉例子，再分步推导，最后用代码验证"},
    },
    "profile_projection": {
        "knowledge_base": "Python、线性代数、概率；正在补强深度学习与大模型工程",
        "weak_points": ["注意力机制", "模型评估", "检索评测"],
    },
    "weak_points": ["注意力机制", "模型评估", "检索评测"],
    "concept_mastery": {"overall": 0.35},
    "confirmed": True,
}
text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
db.add(DBProfileSnapshot(
    id="entry-quality-profile-" + username, owner_public_id=user.public_id,
    legacy_student_id=username, profile_version="entry.diagnostic.quality.profile.v1",
    snapshot=snapshot, content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    trace_id="entry-diagnostic-quality-trace",
))
db.commit()
print(json.dumps({"username": username, "public_id": user.public_id}, ensure_ascii=False))
db.close()
'''
    subprocess.run(
        [sys.executable, "-c", setup],
        cwd=ROOT,
        env={**env, "ENTRY_DIAGNOSTIC_USERNAME": USERNAME, "ENTRY_DIAGNOSTIC_PASSWORD": PASSWORD},
        check=True,
        capture_output=True,
        text=True,
        timeout=240,
    )


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    dotenv = ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in {
                "EDUMATRIX_LLM_PROVIDER", "EDUMATRIX_LLM_ENDPOINT", "EDUMATRIX_LLM_API_KEY",
                "EDUMATRIX_LLM_MODEL", "EDUMATRIX_LLM_THINKING_MODE", "EDUMATRIX_LLM_REASONING_EFFORT",
            }:
                env[key.strip()] = value.strip().strip('"').strip("'")
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "entry-diagnostic-quality-isolated-secret",
        "EDUMATRIX_ONBOARDING_V2": "1", "EDUMATRIX_DEMO_MODE": "0",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0",
        # A large-question generation plus independent review can exceed the
        # default 120s request timeout; keep the live model and no-fallback
        # policy, but allow this isolated acceptance run to finish honestly.
        "EDUMATRIX_LLM_TIMEOUT": "300",
        "EDUMATRIX_LLM_MAX_TOKENS": "32768",
        "EDUMATRIX_HOST": "127.0.0.1", "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1", "PYTHONUNBUFFERED": "1",
        "ENTRY_DIAGNOSTIC_USERNAME": USERNAME, "ENTRY_DIAGNOSTIC_PASSWORD": PASSWORD,
    })
    env["EDUMATRIX_LLM_PROVIDER"] = env.get("EDUMATRIX_LLM_PROVIDER") or "openai"
    env["EDUMATRIX_LLM_MODEL"] = env.get("EDUMATRIX_LLM_MODEL") or "deepseek-v4-flash"
    return env


def attach_errors(page: Page, report: dict[str, Any], scope: str) -> None:
    page.on("pageerror", lambda error: report["browser_errors"].append({"scope": scope, "type": "pageerror", "message": str(error)}))
    page.on("console", lambda message: report["browser_errors"].append({"scope": scope, "type": "console", "message": message.text}) if message.type == "error" else None)
    page.on("requestfailed", lambda request: report["browser_errors"].append({"scope": scope, "type": "requestfailed", "url": request.url, "message": str(request.failure)}))
    page.on("response", lambda response: report["http_errors"].append({"scope": scope, "status": response.status, "url": response.url}) if response.status >= 400 else None)


def visual_metrics(page: Page, root_testid: str) -> dict[str, Any]:
    return page.evaluate(
        """(rootTestId) => {
          const root = document.querySelector('[data-testid="' + rootTestId + '"]') || document.body;
          const visible = (el) => { const s=getComputedStyle(el), r=el.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity)>0 && r.width>1 && r.height>1; };
          const controls=[...root.querySelectorAll('button,a[href],input,textarea,select')].filter(visible);
          const collisions=[];
          for(let i=0;i<controls.length;i++) for(let j=i+1;j<controls.length;j++) { const a=controls[i].getBoundingClientRect(), b=controls[j].getBoundingClientRect(); const w=Math.min(a.right,b.right)-Math.max(a.left,b.left), h=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top); if(w>3&&h>3) collisions.push([controls[i].innerText||controls[i].getAttribute('aria-label')||controls[i].tagName, controls[j].innerText||controls[j].getAttribute('aria-label')||controls[j].tagName]); }
          const clipped=[...root.querySelectorAll('h1,h2,h3,strong,p,span,button,label,small,dd')].filter(el=>visible(el) && getComputedStyle(el).textOverflow !== 'ellipsis' && (el.getBoundingClientRect().right > document.documentElement.scrollWidth+1 || (el.scrollWidth>el.clientWidth+4 && getComputedStyle(el).whiteSpace !== 'nowrap'))).map(el=>(el.innerText||'').trim().slice(0,80)).filter(Boolean).slice(0,20);
          return {viewport:[innerWidth,innerHeight], documentWidth:document.documentElement.scrollWidth, bodyTextLength:(root.innerText||'').trim().length, collisions, clipped};
        }""",
        root_testid,
    )


def capture(page: Page, report: dict[str, Any], name: str, root_testid: str) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(450)
    path = OUTPUT_DIR / name
    page.screenshot(path=str(path), full_page=True)
    metrics = visual_metrics(page, root_testid)
    report["screenshots"].append(name)
    report["visual_checks"][name] = metrics
    if metrics["documentWidth"] > metrics["viewport"][0]:
        raise AssertionError(f"horizontal overflow at {name}: {metrics}")
    if metrics["collisions"]:
        raise AssertionError(f"visible control collision at {name}: {metrics['collisions']}")
    if metrics["clipped"]:
        raise AssertionError(f"clipped text at {name}: {metrics['clipped']}")


def login(page: Page) -> str:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=40_000)
    page.get_by_test_id("login-username").fill(USERNAME)
    page.get_by_test_id("login-password").fill(PASSWORD)
    with page.expect_response(lambda response: response.url.endswith("/api/auth/login") and response.status == 200, timeout=40_000):
        page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(rf"{re.escape(BASE_URL)}/(?:onboarding|workspace|$).*"), timeout=40_000)
    token = page.evaluate("() => localStorage.getItem('edumatrix_token')")
    if not token:
        raise AssertionError("login token missing")
    # The profile snapshot is seeded as an already-confirmed diagnostic fixture;
    # mark the browser session onboarded so the protected assessment route is
    # reached without running a second onboarding journey.
    page.evaluate("() => localStorage.setItem('edumatrix_onboarded', 'true')")
    return token


def create_blueprint(page: Page, report: dict[str, Any]) -> dict[str, Any]:
    page.goto(f"{BASE_URL}/workspace/assessment/entry?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_test_id("entry-diagnostic").wait_for(state="visible", timeout=60_000)
    try:
        page.get_by_test_id("diagnostic-overview").wait_for(state="visible", timeout=60_000)
    except PlaywrightTimeoutError:
        report["diagnostic_debug"] = {
            "url": page.url,
            "body_text": page.get_by_test_id("entry-diagnostic").inner_text(),
            "html": page.get_by_test_id("entry-diagnostic").inner_html(),
        }
        page.screenshot(path=str(OUTPUT_DIR / "1440x900-debug-entry.png"), full_page=True)
        raise
    assert page.get_by_text("人工智能与深度学习：从机器学习基础到大模型智能体", exact=True).count() >= 1
    page.get_by_label("诊断题目数量").select_option(str(QUESTION_COUNT))
    page.wait_for_function(
        "() => { const button = document.querySelector('[data-testid=\"generate-diagnostic\"]'); return button && !button.disabled; }",
        timeout=60_000,
    )
    capture(page, report, "1440x900-01-preflight.png", "entry-diagnostic")
    with page.expect_response(lambda response: response.url.endswith("/api/v1/diagnostics/blueprints"), timeout=240_000) as response_info:
        page.get_by_test_id("generate-diagnostic").click()
    blueprint_response = response_info.value
    if blueprint_response.status != 201:
        try:
            detail = blueprint_response.json()
        except Exception:
            detail = {"text": blueprint_response.text()[:4000]}
        capture(page, report, "1440x900-02-generation-failed.png", "entry-diagnostic")
        raise AssertionError(f"diagnostic blueprint generation returned HTTP {blueprint_response.status}: {detail}")
    page.get_by_test_id("diagnostic-ready").wait_for(state="visible", timeout=60_000)
    blueprint = blueprint_response.json()["blueprint"]
    report["checks"]["generation"] = {
        "question_count": blueprint["questionCount"],
        "coverage_count": len(blueprint.get("knowledgePointCoverage") or []),
        "source_count": len(blueprint.get("sourceRefs") or []),
        "question_types": blueprint.get("difficultyBands", {}).get("questionTypes", {}),
        "question_kinds": blueprint.get("difficultyBands", {}).get("questionKinds", {}),
        "target_difficulty": blueprint.get("difficultyBands", {}).get("targetDifficulty"),
        "coverage_contract": blueprint.get("coverageContract", {}),
        "profile_snapshot_id": blueprint.get("profileSnapshotId"),
    }
    capture(page, report, "1440x900-02-generated-ready.png", "entry-diagnostic")
    return blueprint


def question_oracle(question_ids: list[str]) -> dict[str, dict[str, Any]]:
    placeholders = ",".join("?" for _ in question_ids)
    with sqlite3.connect(DB_PATH) as db:
        rows = db.execute(
            "SELECT v.id, q.question_type, v.answer_key "
            f"FROM assessment_question_versions v JOIN assessment_questions q ON q.id=v.question_id WHERE v.id IN ({placeholders})",
            question_ids,
        ).fetchall()
    result = {}
    for row in rows:
        answer_key = json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
        result[row[0]] = {
            "question_type": row[1],
            "answer_key": answer_key,
            "reference_answer": answer_key.get("reference_answer"),
        }
    return result


def audit_blueprint(blueprint: dict[str, Any]) -> dict[str, Any]:
    questions = blueprint.get("questions") or []
    coverage = blueprint.get("knowledgePointCoverage") or []
    types = [item.get("questionType") for item in questions]
    prompts = ["".join(str(item.get("prompt") or "").lower().split()) for item in questions]
    kp_ids = [item.get("primaryKnowledgePointId") for item in questions]
    coverage_ids = [item.get("id") for item in coverage]
    invalid_prompts = [item.get("id") for item in questions if len(str(item.get("prompt") or "").strip()) < 8]
    invalid_options = [item.get("id") for item in questions if item.get("questionType") == "single_choice" and len(item.get("options") or []) != 4]
    type_counts = {key: types.count(key) for key in sorted(set(types))}
    assert len(questions) == QUESTION_COUNT
    assert type_counts == {"short_answer": 6, "single_choice": 7, "true_false": 7}, type_counts
    assert len(set(types)) == 3
    assert len(prompts) - len(set(prompts)) == 0
    assert not invalid_prompts and not invalid_options
    assert not (set(coverage_ids) - set(kp_ids)) and not (set(kp_ids) - set(coverage_ids))
    assert set(item.get("diagnosticKind") for item in questions) == {"theory", "application", "engineering_judgment"}
    oracle = question_oracle([str(item["id"]) for item in questions])
    assert len(oracle) == len(questions)
    return {
        "question_count": len(questions), "question_type_counts": type_counts,
        "diagnostic_dimensions": sorted(set(item.get("diagnosticKind") for item in questions)),
        "coverage_count": len(coverage_ids), "covered_knowledge_point_ids": sorted(set(kp_ids)),
        "missing_knowledge_points": sorted(set(coverage_ids) - set(kp_ids)),
        "extra_knowledge_points": sorted(set(kp_ids) - set(coverage_ids)),
        "duplicate_prompt_count": len(prompts) - len(set(prompts)),
        "invalid_prompt_count": len(invalid_prompts), "invalid_choice_count": len(invalid_options),
        "question_oracle": oracle,
    }


def select_answer(page: Page, question: dict[str, Any], oracle: dict[str, Any], index: int) -> bool:
    intentionally_correct = index % 3 != 0
    question_type = question["questionType"]
    key = oracle.get("answer_key") or {}
    if question_type == "true_false":
        expected = bool(key.get("value"))
        value = expected if intentionally_correct else not expected
        page.get_by_role("button", name="正确" if value else "错误", exact=True).click()
    elif question_type == "single_choice":
        expected = str(key.get("choice") or "A").strip()[:1].upper()
        value = expected if intentionally_correct else ("B" if expected != "B" else "A")
        page.locator(".option-list label").nth(ord(value) - ord("A")).click()
    else:
        reference = str(oracle.get("reference_answer") or "解释该知识点的定义、关键步骤和适用边界，并联系一个课程案例。").strip()
        page.locator("textarea.text-answer").fill(reference if intentionally_correct else "我还不确定，无法说明关键条件。")
    page.locator(".understanding-control label").nth(2 if intentionally_correct else 1).click()
    return intentionally_correct


def run_session(page: Page, report: dict[str, Any], blueprint: dict[str, Any]) -> dict[str, Any]:
    with page.expect_response(lambda response: response.url.endswith("/sessions") and response.status == 200, timeout=60_000) as session_info:
        page.get_by_test_id("enter-diagnostic").click()
    page.get_by_test_id("diagnostic-session").wait_for(state="visible", timeout=60_000)
    session_payload = session_info.value.json()["session"]
    session_id = session_payload["id"]
    questions = blueprint["questions"]
    audit = audit_blueprint(blueprint)
    oracle = audit["question_oracle"]
    first_types = {"true_false": False, "single_choice": False, "short_answer": False}
    for index, question in enumerate(questions):
        qtype = question["questionType"]
        if not first_types[qtype]:
            capture(page, report, f"1440x900-{3 + sum(first_types.values()):02d}-{qtype}.png", "diagnostic-session")
            first_types[qtype] = True
        selected_correct = select_answer(page, question, oracle[question["id"]], index)
        report.setdefault("checks", {}).setdefault("answers", []).append({
            "index": index + 1, "question_id": question["id"], "question_type": qtype,
            "intentionally_correct": selected_correct, "knowledge_point_id": question["primaryKnowledgePointId"],
        })
        if index < len(questions) - 1:
            with page.expect_response(lambda response: "/responses/" in response.url and response.status == 200, timeout=40_000):
                page.get_by_role("button", name="保存并进入下一题", exact=True).click()
            page.get_by_text(f"第 {index + 2} / {len(questions)} 题", exact=True).wait_for(state="visible", timeout=40_000)
        else:
            with page.expect_response(lambda response: response.url.endswith("/submit") and response.status == 200, timeout=60_000):
                page.get_by_role("button", name="提交本次诊断", exact=True).click()
    page.get_by_test_id("diagnostic-submitted").wait_for(state="visible", timeout=60_000)
    capture(page, report, "1440x900-06-report-loading.png", "diagnostic-submitted")
    page.get_by_role("heading", name="你的入学诊断结果").wait_for(state="visible", timeout=300_000)
    capture(page, report, "1440x900-06-submitted-report.png", "diagnostic-submitted")
    page.get_by_test_id("report-knowledge-toggle").click()
    page.get_by_test_id("report-evidence-toggle").click()
    capture(page, report, "1440x900-07-mastery-and-evidence.png", "diagnostic-submitted")
    return {"session_id": session_id, "audit": audit, "first_types": first_types}


def report_audit(report: dict[str, Any], session_id: str) -> None:
    with sqlite3.connect(DB_PATH) as db:
        session_row = db.execute("SELECT status FROM diagnostic_sessions WHERE id=?", (session_id,)).fetchone()
        draft_count = db.execute("SELECT COUNT(*) FROM diagnostic_response_drafts WHERE session_id=?", (session_id,)).fetchone()[0]
        complete_count = db.execute("SELECT COUNT(*) FROM diagnostic_response_drafts WHERE session_id=? AND understanding_level IS NOT NULL", (session_id,)).fetchone()[0]
        report_row = db.execute("SELECT id, profile_snapshot_id FROM diagnostic_reports WHERE session_id=?", (session_id,)).fetchone()
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        fk = db.execute("PRAGMA foreign_key_check").fetchall()
        attempts = db.execute("SELECT COUNT(*) FROM assessment_attempts WHERE owner_public_id=(SELECT owner_public_id FROM diagnostic_sessions WHERE id=?) AND mode='diagnostic'", (session_id,)).fetchone()[0]
    assert session_row and session_row[0] == "submitted"
    assert draft_count == QUESTION_COUNT and complete_count == QUESTION_COUNT and report_row is not None
    assert integrity == "ok" and not fk and attempts == QUESTION_COUNT
    report["checks"]["submission"] = {
        "session_id": session_id, "session_status": session_row[0], "response_drafts": draft_count,
        "complete_responses": complete_count, "diagnostic_report_id": report_row[0],
        "report_profile_snapshot_id": report_row[1], "graded_attempts": attempts,
        "integrity_check": integrity, "foreign_key_violations": len(fk),
    }


def main() -> int:
    clear_evidence()
    formal_db = ROOT / "edumatrix.db"
    before_formal = formal_db.read_bytes() if formal_db.exists() else None
    env = runtime_env()
    report: dict[str, Any] = {
        "schema_version": "entry-diagnostic-quality.browser-e2e.v1", "result": "running",
        "course_id": COURSE_ID, "username": USERNAME, "database": str(DB_PATH), "service": BASE_URL,
        "viewport_contract": [[1440, 900], [1366, 768]], "screenshots": [], "visual_checks": {},
        "checks": {}, "browser_errors": [], "http_errors": [], "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    process = None
    try:
        seed_isolated_database(env)
        with (EVIDENCE / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page(); page.set_default_timeout(60_000)
                attach_errors(page, report, "1440x900")
                token = login(page)
                blueprint = create_blueprint(page, report)
                report["checks"]["blueprint_audit"] = audit_blueprint(blueprint)
                session_info = run_session(page, report, blueprint)
                report_audit(report, session_info["session_id"])
                compact = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
                compact_page = compact.new_page(); compact_page.set_default_timeout(60_000)
                attach_errors(compact_page, report, "1366x768")
                login(compact_page)
                compact_page.goto(
                    f"{BASE_URL}/workspace/assessment?course_id={COURSE_ID}&blueprint_id={blueprint['id']}&question_version_id={blueprint['questions'][0]['id']}",
                    wait_until="domcontentloaded", timeout=60_000,
                )
                compact_page.get_by_test_id("diagnostic-submitted").wait_for(state="visible", timeout=60_000)
                capture(compact_page, report, "1366x768-01-submitted-report.png", "diagnostic-submitted")
                compact.close(); context.close(); browser.close()
        after_formal = formal_db.read_bytes() if formal_db.exists() else None
        report["checks"]["formal_database_unchanged"] = before_formal == after_formal
        if before_formal != after_formal:
            raise AssertionError("formal edumatrix.db changed during isolated acceptance")
        if report["http_errors"] or report["browser_errors"]:
            raise AssertionError({"http_errors": report["http_errors"], "browser_errors": report["browser_errors"]})
        report["checks"]["no_unexpected_errors"] = True
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"; report["error"] = f"{type(exc).__name__}: {exc}"; report["traceback"] = traceback.format_exc()
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=20)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            try:
                wait_port(False, 20)
            except RuntimeError:
                pass
        report["process_cleanup"] = process is None or process.poll() is not None
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (EVIDENCE / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "screenshots": len(report["screenshots"]), "error": report.get("error")}, ensure_ascii=False))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
