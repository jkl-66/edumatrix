"""Real Chromium audit for learner-facing answer explanations.

The fixtures are deliberately isolated from the production database.  This script
does not replace the older F6/F8 journeys; it keeps only the interactions needed
to visually prove that quiz, intelligent-exam and wrong-question explanations are
question-specific and free of provenance-only text.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "QUIZ-EXPLANATION-CORRECTNESS-VISUAL-AUDIT-01"
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
QUIZ_DIR = OUTPUT_DIR / "quiz_runtime"
EXAM_DIR = OUTPUT_DIR / "exam_runtime"
WRONG_DIR = OUTPUT_DIR / "wrong_runtime"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
FORBIDDEN_MARKERS = (
    "先核对已冻结来源", "核对已冻结来源", "答案来自冻结", "依据冻结课程来源",
    "依据课程来源核对", "生成蓝图", "绑定课程来源", "证据核验", "content_hash",
    "parser_version", "版本哈希", "课程来源锚点", "来源锚点",
)


def _reset_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for item in path.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def _env(db_path: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(db_path),
        "EDUMATRIX_AUTH_SECRET_KEY": "quiz-explanation-visual-audit-secret",
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


def _port_free(port: int) -> bool:
    import socket
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _free_port(start: int) -> int:
    for port in range(start, start + 30):
        if _port_free(port):
            return port
    raise RuntimeError("no free browser-audit port")


def _wait_port(port: int, expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_free(port) is (not expected):
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {port} did not reach expected state {expected}")


def _start_service(env: dict[str, str], port: int, log_dir: Path) -> subprocess.Popen:
    log = (log_dir / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "run.py"], cwd=ROOT, env=env,
        stdout=log, stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    process._audit_log = log  # type: ignore[attr-defined]
    _wait_port(port, True)
    return process


def _stop_service(process: subprocess.Popen | None, port: int) -> None:
    if process is None:
        return
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
        else:
            process.terminate()
        process.wait(timeout=10)
    log = getattr(process, "_audit_log", None)
    if log is not None:
        log.close()
    _wait_port(port, False, timeout=20)


def _login(page: Page, base_url: str) -> None:
    response = page.request.post(
        f"{base_url}/api/auth/login", form={"username": USERNAME, "password": PASSWORD},
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
      localStorage.setItem('edumatrix_course_title', 'RAG 应用开发与负责任评测实践');
    """)


def _diagnostics(page: Page, report: dict) -> None:
    page.on("response", lambda response: report["http_errors"].append({"status": response.status, "url": response.url}) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({"url": request.url, "failure": request.failure}))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def _capture(page: Page, report: dict, name: str, target, *, require: tuple[str, ...] = ()) -> str:
    target.scroll_into_view_if_needed()
    page.wait_for_timeout(250)
    text = target.inner_text()
    for phrase in require:
        assert phrase in text, {"name": name, "missing": phrase, "text": text}
    assert not any(marker in text for marker in FORBIDDEN_MARKERS), {"name": name, "forbidden": text}
    path = SCREENSHOT_DIR / name
    page.screenshot(path=str(path), full_page=False, animations="disabled")
    size = Image.open(path).size
    viewport = page.evaluate("() => [innerWidth, innerHeight]")
    assert list(size) == viewport, {"name": name, "size": size, "viewport": viewport}
    report["screenshots"].append(name)
    report["visual"][name] = {
        "viewport": viewport,
        "screenshot_size": list(size),
        "text_length": len(text),
        "text_excerpt": text[:500],
        "contains_question_specific_terms": any(token in text for token in ("正确答案", "选项", "题干", "适用", "常见误区", "原因")),
    }
    return text


def _db_guard(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=20) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "attempts": db.execute("SELECT COUNT(*) FROM assessment_attempts WHERE owner_public_id=(SELECT public_id FROM users WHERE username=?)", (USERNAME,)).fetchone()[0],
        }


def _run_quiz(report: dict) -> None:
    import e2e_f6_t01_quiz_resource as fixture

    _reset_dir(QUIZ_DIR)
    original = fixture.OUTPUT_DIR
    fixture.OUTPUT_DIR = QUIZ_DIR
    db_path = QUIZ_DIR / "quiz.sqlite3"
    port = _free_port(9160)
    env = fixture.runtime_env(db_path, port)
    data = fixture.seed_fixture(env)
    process = None
    try:
        process = _start_service(env, port, QUIZ_DIR)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            _diagnostics(page, report)
            _login(page, base_url)
            page.goto(f"{base_url}/workspace/resources/quizzes/{data['resource_id']}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
            page.get_by_test_id("inline-quiz-card").wait_for(state="visible")
            labels = ["A", "B", "C", "D"]
            correct = data["correct_choice"]
            wrong = next(label for label in labels if label != correct)
            page.locator(".option-list label").nth(labels.index(wrong)).click()
            page.locator(".quiz-actions .primary-action").click()
            page.get_by_text("这次还不正确", exact=True).wait_for(state="visible")
            feedback = page.locator(".feedback-panel")
            _capture(page, report, "01-quiz-wrong-explanation-1440x900.png", feedback, require=("正确答案", "选项", "常见误区"))
            page.get_by_role("button", name="修改答案", exact=True).click()
            page.locator(".option-list label").nth(labels.index(correct)).click()
            page.locator(".quiz-actions .primary-action").click()
            page.get_by_text("回答正确", exact=True).first.wait_for(state="visible")
            _capture(page, report, "02-quiz-correct-explanation-1440x900.png", page.locator(".feedback-panel"), require=("正确答案", "选项"))
            context.close()
            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            _diagnostics(page, report)
            _login(page, base_url)
            page.goto(f"{base_url}/workspace/resources/quizzes/{data['resource_id']}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
            page.get_by_test_id("inline-quiz-card").wait_for(state="visible")
            page.locator(".option-list label").nth(labels.index(wrong)).click()
            page.locator(".quiz-actions .primary-action").click()
            page.get_by_text("这次还不正确", exact=True).wait_for(state="visible")
            _capture(page, report, "03-quiz-wrong-explanation-1366x768.png", page.locator(".feedback-panel"), require=("正确答案", "选项"))
            browser.close()
        report["scenarios"]["quiz_resource"] = {"resource_id": data["resource_id"], "db": _db_guard(db_path)}
    finally:
        _stop_service(process, port)
        fixture.OUTPUT_DIR = original


def _seed_exam(env: dict[str, str], output: Path) -> dict[str, str]:
    """Seed the gate and create a deterministic source-bound exam fixture."""
    import e2e_f6_t06_formal_exam as formal

    formal.OUTPUT_DIR = output
    formal.seed_fixture(env)
    code = f'''
import json
from pathlib import Path
from app.database import DBUser, SessionLocal, init_db
from app.m5_exam_core import IntelligentExamConfigInput, build_intelligent_exam_input, create_exam, transition_exam, assign_sitting
init_db()
db = SessionLocal()
try:
    learner = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    config = IntelligentExamConfigInput(
        idempotency_key="quiz-explanation-exam-fixture-001", course_id={COURSE_ID!r},
        title="解析正确性智能组卷", theme="理解混合检索的判断与边界", duration_minutes=30,
        difficulty="adaptive", question_type_counts={{"single_choice": 1, "true_false": 1, "fill_blank": 1}}, source_limit=8,
    )
    payload = build_intelligent_exam_input(db, owner_public_id=learner.public_id, config=config, llm=None)
    exam, _, _ = create_exam(db, owner_public_id=learner.public_id, payload=payload)
    transition_exam(db, exam=exam, target="published", expected_lock_version=exam.lock_version, actor_public_id=learner.public_id)
    sitting, _ = assign_sitting(db, exam=exam, learner_public_id=learner.public_id, actor_public_id=learner.public_id)
    transition_exam(db, exam=exam, target="open", expected_lock_version=exam.lock_version, actor_public_id=learner.public_id)
    db.commit()
    Path({str(output / "exam_fixture.json")!r}).write_text(json.dumps({{"exam_id": exam.id, "sitting_id": sitting.id}}, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True, timeout=120)
    return json.loads((output / "exam_fixture.json").read_text(encoding="utf-8"))


def _run_exam(report: dict) -> None:
    import e2e_f6_t06_formal_exam as formal

    _reset_dir(EXAM_DIR)
    original = formal.OUTPUT_DIR
    formal.OUTPUT_DIR = EXAM_DIR
    db_path = EXAM_DIR / "exam.sqlite3"
    port = _free_port(9190)
    env = _env(db_path, port)
    fixture = _seed_exam(env, EXAM_DIR)
    process = None
    try:
        process = _start_service(env, port, EXAM_DIR)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            _diagnostics(page, report)
            _login(page, base_url)
            url = f"{base_url}/workspace/assessment/exams/{fixture['exam_id']}?course_id={COURSE_ID}"
            page.goto(url, wait_until="networkidle", timeout=60_000)
            page.get_by_test_id("generated-exam-preview").wait_for(state="visible")
            page.get_by_role("button", name="开始作答", exact=True).click()
            page.get_by_text("作答已开始。", exact=False).wait_for(state="visible")
            page.wait_for_timeout(800)
            for index in range(3):
                page.locator(".answer-stage h3").wait_for(state="visible", timeout=15_000)
                page.wait_for_timeout(350)
                if page.locator(".answer-stage .option-list button").count():
                    page.locator(".answer-stage .option-list button").first.click(timeout=15_000)
                elif page.locator(".answer-stage .binary-options button").count():
                    page.locator(".answer-stage .binary-options button").filter(has_text="错误").click(timeout=15_000)
                else:
                    page.locator(".answer-stage textarea").fill("暂不确定")
                save_label = "保存并下一题" if index < 2 else "保存本题"
                page.get_by_role("button", name=save_label, exact=True).click()
                page.get_by_text("已保存", exact=False).last.wait_for(state="visible")
            page.once("dialog", lambda dialog: dialog.accept())
            page.get_by_role("button", name="提交试卷", exact=True).click()
            page.get_by_test_id("formal-exam-report").wait_for(state="visible", timeout=60_000)
            articles = page.locator(".answer-review article")
            assert articles.count() == 3
            for index in range(articles.count()):
                text = _capture(page, report, f"04-exam-report-q{index + 1}-1440x900.png", articles.nth(index), require=("解析", "正确答案"))
                assert "题目" in text or "选项" in text or "答案" in text
            context.close()
            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            _diagnostics(page, report)
            _login(page, base_url)
            page.goto(url, wait_until="networkidle", timeout=60_000)
            page.get_by_role("button", name="查看报告", exact=True).click()
            page.get_by_test_id("formal-exam-report").wait_for(state="visible")
            _capture(page, report, "07-exam-report-q1-1366x768.png", page.locator(".answer-review article").first, require=("解析", "正确答案"))
            browser.close()
        report["scenarios"]["intelligent_exam"] = {"exam_id": fixture["exam_id"], "db": _db_guard(db_path)}
    finally:
        _stop_service(process, port)
        formal.OUTPUT_DIR = original


def _run_wrong(report: dict) -> None:
    import e2e_f8_t02_wrong_questions as wrong

    _reset_dir(WRONG_DIR)
    wrong.OUTPUT_DIR = WRONG_DIR
    wrong.BROWSER_DIR = WRONG_DIR / "browser"
    wrong.RUNTIME_DIR = WRONG_DIR
    wrong.DB_PATH = WRONG_DIR / "wrong.sqlite3"
    wrong.REPORT_PATH = WRONG_DIR / "report.json"
    wrong.PORT_START = 9220
    wrong.configure_browser_base()
    env = wrong.runtime_env(wrong.PORT_START)
    fixture = wrong.seed_fixture(env)
    process = None
    try:
        process = wrong.browser_base.start_service(env, wrong.PORT_START)
        base_url = f"http://127.0.0.1:{wrong.PORT_START}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            _diagnostics(page, report)
            _login(page, base_url)
            url = wrong.wrong_question_url(base_url, fixture)
            page.goto(url, wait_until="networkidle", timeout=60_000)
            page.get_by_test_id("wrong-question-list-item").first.wait_for(state="visible")
            # The learner-facing heading follows the concrete question topic;
            # the stored broad concept remains an internal binding.
            page.get_by_test_id("wrong-question-list-item").first.click()
            detail = page.get_by_test_id("wrong-question-detail")
            _capture(page, report, "08-wrong-question-detail-1440x900.png", detail.locator(".answer-overview"), require=("解析", "负梯度", "参考答案"))
            page.get_by_test_id("wrong-question-primary-action").click()
            redo = page.get_by_test_id("wrong-question-redo")
            redo.wait_for(state="visible")
            redo.locator('input[type="radio"][value="B"]').check()
            redo.get_by_role("button", name="提交并判分", exact=True).click()
            redo.get_by_text("回答正确，这次练习已经记录。", exact=True).wait_for(state="visible", timeout=60_000)
            _capture(page, report, "09-wrong-question-redo-feedback-1440x900.png", detail, require=("解析", "负梯度"))
            context.close()
            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            _diagnostics(page, report)
            _login(page, base_url)
            page.goto(url, wait_until="networkidle", timeout=60_000)
            page.get_by_test_id("wrong-question-list-item").first.click()
            detail = page.get_by_test_id("wrong-question-detail")
            _capture(page, report, "10-wrong-question-detail-1366x768.png", detail.locator(".answer-overview"), require=("解析", "负梯度"))
            browser.close()
        report["scenarios"]["wrong_question_book"] = {"primary_wrong_id": fixture["primary_wrong_id"], "db": _db_guard(wrong.DB_PATH)}
    finally:
        wrong.browser_base.stop_service(process, wrong.PORT_START)


def run() -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for runtime_dir in (SCREENSHOT_DIR, QUIZ_DIR, EXAM_DIR, WRONG_DIR):
        _reset_dir(runtime_dir)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "schema_version": "quiz-explanation-correctness.browser.v1",
        "status": "running",
        "viewports": [[1440, 900], [1366, 768]],
        "isolated_databases": True,
        "deterministic_demo_model": True,
        "screenshots": [],
        "visual": {},
        "scenarios": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
    }
    try:
        _run_quiz(report)
        _run_exam(report)
        _run_wrong(report)
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        for scenario in report["scenarios"].values():
            assert scenario["db"]["integrity"] == "ok"
            assert scenario["db"]["foreign_key_violations"] == 0
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise
    finally:
        (OUTPUT_DIR / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        digest = hashlib.sha256((OUTPUT_DIR / "browser_report.json").read_bytes()).hexdigest()
        (OUTPUT_DIR / "browser_report.sha256").write_text(digest + "\n", encoding="ascii")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
