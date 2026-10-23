"""F6-T01 canonical quiz-resource desktop E2E on isolated SQLite."""

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

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f6_t01_quiz_resource"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
PORT_START = int(os.getenv("EDUMATRIX_F6_T01_PORT", "8991"))


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F6-T01 E2E port")


def wait_port(port: int, expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(port) is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {port} did not reach expected state: {expected}")


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def runtime_env(db_path: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(db_path),
        "EDUMATRIX_AUTH_SECRET_KEY": "f6-t01-isolated-secret",
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


def seed_fixture(env: dict[str, str]) -> dict[str, str]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import json
from pathlib import Path
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBAssessmentQuestionVersion, DBProfileSnapshot, DBSourceRef, DBUser,
    SessionLocal, init_db,
)
from app.resource_bundles import create_generation_job, execute_generation_job_demo

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    learner = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    profile = db.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
    source = db.get(DBSourceRef, "demo-ref-07")
    if profile is None or source is None:
        raise RuntimeError("competition demo profile or source is missing")
    job = create_generation_job(
        db,
        learner,
        course_id={COURSE_ID!r},
        knowledge_point_id="demo-kp-07",
        profile_snapshot_id=profile.id,
        idempotency_key="f6-t01-browser-fixture-001",
        scope="single",
        items=[{{
            "type": "quiz",
            "title": "课程上下文即时练习",
            "source_ref_ids": [source.id],
            "completion_rule": "三道必做题均至少正确一次",
        }}],
        learning_goal="依据当前课程来源完成一次可追溯即时练习",
    )
    db.commit()
    result = execute_generation_job_demo(db, learner, job["job_id"])
    db.commit()
    resource = result["items"][0]["resource"]
    resource_id = resource["resource_id"]
    from app.database import DBArtifact
    from app.m5_resources import resource_detail
    artifact = db.get(DBArtifact, resource_id)
    detail = resource_detail(db, artifact)
    question = detail["quiz"]["current"]["questions"][0]
    version = db.get(DBAssessmentQuestionVersion, question["id"])
    payload = {{
        "resource_id": resource_id,
        "question_id": question["id"],
        "correct_choice": version.answer_key["choice"],
        "source_ref_id": source.id,
    }}
    Path({str(fixture_path)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=120)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def start_service(env: dict[str, str], port: int) -> subprocess.Popen:
    log = (OUTPUT_DIR / "server.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "run.py"], cwd=ROOT, env=env,
        stdout=log, stderr=subprocess.STDOUT,
    )
    process._edumatrix_log = log  # type: ignore[attr-defined]
    wait_port(port, True)
    return process


def stop_service(process: subprocess.Popen | None, port: int) -> None:
    if process is None:
        return
    if process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, timeout=20,
        )
        process.wait(timeout=10)
    log = getattr(process, "_edumatrix_log", None)
    if log is not None:
        log.close()
    wait_port(port, False, timeout=20)


def login(page: Page, base_url: str) -> None:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": USERNAME, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    payload = response.json()
    state = json.dumps(payload, ensure_ascii=False)
    page.add_init_script(f"""
      const session = {state};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_display_name', session.display_name || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_role', session.role || 'student');
      localStorage.setItem('edumatrix_student_id', session.student_id || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', '{COURSE_ID}');
      localStorage.setItem('edumatrix_course_title', '人工智能与机器学习工程');
    """)


def quiz_state(db_path: Path) -> dict[str, int | str]:
    with sqlite3.connect(db_path, timeout=10) as db:
        owner = db.execute("SELECT public_id FROM users WHERE username=?", (USERNAME,)).fetchone()[0]
        return {
            "attempts": db.execute(
                "SELECT COUNT(*) FROM assessment_attempts WHERE owner_public_id=? AND mode='practice'",
                (owner,),
            ).fetchone()[0],
            "quiz_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=? AND event_type='quiz_answered'",
                (owner,),
            ).fetchone()[0],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def page_diagnostics(page: Page, report: dict) -> None:
    page.on("response", lambda response: report["http_errors"].append({
        "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url, "failure": request.failure,
    }) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def visible_metrics(page: Page, root_selector: str) -> dict:
    return page.evaluate("""(selector) => {
      const root = document.querySelector(selector);
      const visible = (el) => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1;
      };
      const elements = root ? [root, ...root.querySelectorAll('*')] : [];
      const controls = elements.filter((el) => el.matches('button,a[href],input,select,textarea') &&
        visible(el) && !el.classList.contains('history-backdrop'));
      const collisions = [];
      for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
        const a = controls[i], b = controls[j];
        if (a.contains(b) || b.contains(a)) continue;
        const x = a.getBoundingClientRect(), y = b.getBoundingClientRect();
        const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left);
        const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top);
        if (overlapW > 3 && overlapH > 3) collisions.push([
          (a.innerText || a.getAttribute('aria-label') || a.title || '').trim().slice(0, 48),
          (b.innerText || b.getAttribute('aria-label') || b.title || '').trim().slice(0, 48),
        ]);
      }
      const clipped = elements.filter(visible).filter((el) => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false;
        return rect.right > innerWidth + 1 || rect.left < -1 ||
          (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap' && style.overflowX !== 'auto');
      }).map((el) => (el.innerText || '').trim().slice(0, 80)).filter(Boolean).slice(0, 20);
      const smallText = elements.filter((el) => {
        const text = (el.innerText || '').replaceAll('\u200b', '').trim();
        return visible(el) && el.children.length === 0 && text &&
          Number.parseFloat(getComputedStyle(el).fontSize) < 13.5;
      }).map((el) => ({ text: el.innerText.trim().slice(0, 40), size: getComputedStyle(el).fontSize })).slice(0, 20);
      const forbiddenEffects = elements.filter(visible).filter((el) => {
        const style = getComputedStyle(el);
        return (style.backgroundImage || '').includes('gradient') ||
          !['none', ''].includes(style.backdropFilter || 'none');
      }).map((el) => el.className?.toString().slice(0, 80)).slice(0, 20);
      return {
        viewport: [innerWidth, innerHeight],
        documentWidth: document.documentElement.scrollWidth,
        bodyTextLength: (root?.innerText || '').trim().length,
        collisions, clipped, smallText, forbiddenEffects,
      };
    }""", root_selector)


def capture(page: Page, report: dict, name: str, root_selector: str, minimum_text: int = 120) -> None:
    page.wait_for_timeout(300)
    metrics = visible_metrics(page, root_selector)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] >= minimum_text, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["forbiddenEffects"], metrics


def open_quiz(page: Page, base_url: str, resource_id: str) -> None:
    page.goto(
        f"{base_url}/workspace/resources/quizzes/{resource_id}?course_id={COURSE_ID}",
        wait_until="networkidle", timeout=60_000,
    )
    page.get_by_test_id("quiz-resource-workspace").wait_for(state="visible")
    page.get_by_test_id("inline-quiz-card").wait_for(state="visible")


def exercise_primary_flow(page: Page, base_url: str, fixture: dict[str, str], db_path: Path, report: dict) -> None:
    open_quiz(page, base_url, fixture["resource_id"])
    resource_title = (
        page.get_by_test_id("resource-toolbar")
        .locator("h1")
        .inner_text()
        .strip()
    )
    assert resource_title
    assert page.locator(".question-rail > button").count() == 3
    before_browse = quiz_state(db_path)
    capture(page, report, "01-quiz-ready-1440x900.png", '[data-testid="quiz-resource-workspace"]')
    after_browse = quiz_state(db_path)
    assert after_browse == before_browse
    baseline_attempts = before_browse["attempts"]
    baseline_quiz_events = before_browse["quiz_events"]

    correct = fixture["correct_choice"]
    labels = ["A", "B", "C", "D"]
    wrong = next(label for label in labels if label != correct)
    option_labels = page.locator(".option-list label")
    option_labels.nth(labels.index(wrong)).click()

    attempt_url = "**/api/v1/m5/assessment/attempts"
    page.route(attempt_url, lambda route: route.fulfill(
        status=503,
        content_type="application/json",
        body=json.dumps({"detail": {"message": "模拟判分暂时不可用"}}, ensure_ascii=False),
    ))
    page.get_by_role("button", name="提交答案", exact=True).click()
    page.get_by_text("模拟判分暂时不可用", exact=True).wait_for(state="visible")
    assert option_labels.nth(labels.index(wrong)).locator("input").is_checked()
    failed_state = quiz_state(db_path)
    assert failed_state["attempts"] == baseline_attempts
    assert failed_state["quiz_events"] == baseline_quiz_events
    page.unroute(attempt_url)
    report["expected_submission_failure"] = {
        "selected_choice_preserved": True,
        "attempts_created": failed_state["attempts"] - baseline_attempts,
        "quiz_events_created": failed_state["quiz_events"] - baseline_quiz_events,
    }
    report["expected_http_errors"].extend([
        item for item in report["http_errors"]
        if item["status"] == 503 and item["url"].endswith("/api/v1/m5/assessment/attempts")
    ])
    report["http_errors"] = [
        item for item in report["http_errors"]
        if not (item["status"] == 503 and item["url"].endswith("/api/v1/m5/assessment/attempts"))
    ]
    report["expected_console_errors"].extend([
        item for item in report["console_errors"]
        if "status of 503" in item
    ])
    report["console_errors"] = [
        item for item in report["console_errors"]
        if "status of 503" not in item
    ]

    page.get_by_role("button", name="提交答案", exact=True).click()
    page.get_by_text("这次还不正确", exact=True).wait_for(state="visible")
    page.get_by_text(f"正确答案：{correct}", exact=False).wait_for(state="visible")
    state_after_wrong = quiz_state(db_path)
    assert state_after_wrong["attempts"] == baseline_attempts + 1
    assert state_after_wrong["quiz_events"] == baseline_quiz_events + 1
    capture(page, report, "02-wrong-feedback-1440x900.png", '[data-testid="quiz-resource-workspace"]')

    page.get_by_role("button", name="修改答案", exact=True).click()
    option_labels = page.locator(".option-list label")
    option_labels.nth(labels.index(correct)).click()
    page.get_by_role("button", name="提交新答案", exact=True).click()
    page.get_by_text("回答正确", exact=True).first.wait_for(state="visible")
    state_after_correct = quiz_state(db_path)
    assert state_after_correct["attempts"] == baseline_attempts + 2
    assert state_after_correct["quiz_events"] == baseline_quiz_events + 2
    capture(page, report, "03-correct-resubmission-1440x900.png", '[data-testid="quiz-resource-workspace"]')

    page.reload(wait_until="networkidle")
    page.get_by_test_id("inline-quiz-card").wait_for(state="visible")
    page.get_by_text("本题作答历史", exact=True).wait_for(state="visible")
    assert page.locator(".attempt-history li").count() == 2
    assert page.get_by_text("2 次提交", exact=True).is_visible()
    capture(page, report, "04-refresh-restored-history-1440x900.png", '[data-testid="quiz-resource-workspace"]')

    page.get_by_role("button", name="查看来源", exact=True).click()
    page.wait_for_url(lambda url: "/knowledge" in url, timeout=30_000)
    report["source_url"] = page.url
    open_quiz(page, base_url, fixture["resource_id"])

    history_button = page.get_by_test_id("resource-toolbar").get_by_role("button", name="版本历史", exact=False)
    history_button.wait_for(state="visible")
    assert history_button.is_enabled()
    history_button.click()
    page.get_by_test_id("resource-history-drawer").wait_for(state="visible")
    capture(page, report, "05-version-history-1440x900.png", '[data-testid="resource-history-drawer"]', minimum_text=60)
    page.get_by_title("关闭版本历史").click()

    page.get_by_role("button", name="继续追问这道题", exact=True).click()
    page.locator(".follow-up-form textarea").fill("为什么另一个选项不成立？")
    page.get_by_role("button", name="带着本题上下文追问", exact=True).click()
    page.wait_for_url(lambda url: "/learn" in url, timeout=30_000)
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible")
    question_id = str(page.evaluate(
        "() => new URL(window.location.href).searchParams.get('question_version_id') || ''"
    )).strip()
    assert question_id
    composer = page.get_by_label("输入问题", exact=True)
    composer.wait_for(state="visible")
    prompt = composer.input_value()
    assert "为什么另一个选项不成立" in prompt and "我的答案" in prompt
    report["follow_up"] = {
        "url": page.url,
        "prompt": prompt,
        "resource_title": resource_title,
        "question_id": question_id,
    }
    context = page.get_by_test_id("chat-quiz-context")
    context.wait_for(state="visible")
    context.get_by_text(resource_title, exact=True).wait_for(state="visible")
    assert context.locator(".quiz-context__sources button").count() >= 1
    assert context.locator('input, select, textarea, [data-testid="inline-quiz-card"]').count() == 0
    primary = context.get_by_role("button", name="进入测验题资源作答", exact=True)
    assert primary.count() == 1
    capture(page, report, "06-chat-quiz-context-1440x900.png", '[data-testid="chat-quiz-context"]')

    primary.click()
    page.wait_for_url(
        lambda url: (
            f"/workspace/resources/quizzes/{fixture['resource_id']}" in url
            and f"question_version_id={question_id}" in url
        ),
        timeout=30_000,
    )
    page.get_by_test_id("inline-quiz-card").wait_for(state="visible")
    report["follow_up"]["returned_url"] = page.url

    page.goto(f"{base_url}/workspace/assessment?course_id={COURSE_ID}", wait_until="networkidle")
    page.get_by_test_id("assessment-center").wait_for(state="visible")
    assert page.locator(".assessment-entry-list > button").count() == 2
    assert page.get_by_test_id("entry-diagnostic").is_visible()
    assert page.get_by_test_id("intelligent-exam-entry").is_visible()
    report["assessment_center_entries"] = 2


def exercise_secondary_viewport(page: Page, base_url: str, fixture: dict[str, str], report: dict) -> None:
    open_quiz(page, base_url, fixture["resource_id"])
    page.get_by_text("本题作答历史", exact=True).wait_for(state="visible")
    capture(page, report, "07-quiz-restored-1366x768.png", '[data-testid="quiz-resource-workspace"]')


def run() -> dict:
    clear_output()
    db_path = OUTPUT_DIR / "f6_t01.sqlite3"
    port = free_port()
    env = runtime_env(db_path, port)
    fixture = seed_fixture(env)
    process: subprocess.Popen | None = None
    report = {
        "schema_version": "f6-t01.quiz-resource-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [], "checks": {},
        "http_errors": [], "failed_requests": [], "page_errors": [], "console_errors": [],
        "expected_http_errors": [], "expected_console_errors": [], "expected_submission_failure": {},
        "source_url": "", "follow_up": {}, "assessment_center_entries": 0,
    }
    try:
        process = start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page_diagnostics(page, report)
            login(page, base_url)
            exercise_primary_flow(page, base_url, fixture, db_path, report)
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768})
            page = context.new_page()
            page_diagnostics(page, report)
            login(page, base_url)
            exercise_secondary_viewport(page, base_url, fixture, report)
            context.close()
            browser.close()
        report["database"] = quiz_state(db_path)
        assert report["database"]["integrity"] == "ok"
        assert report["database"]["foreign_key_violations"] == 0
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        stop_service(process, port)


if __name__ == "__main__":
    result = run()
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    (OUTPUT_DIR / "browser_report.json").write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (OUTPUT_DIR / "browser_report.sha256").write_text(digest + "\n", encoding="ascii")
    print(payload)
