"""F10-T01 route migration E2E on an isolated competition-demo database."""

from __future__ import annotations

import argparse
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
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f10_t01_route_migration"
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "f10_t01_route_migration.sqlite3"
FIXTURE_PATH = RUNTIME_DIR / "fixture.json"
REPORT_PATH = OUTPUT_DIR / "browser_report.json"
MANAGED_SERVER_LOG = RUNTIME_DIR / "managed_server.log"
PORT = int(os.getenv("EDUMATRIX_F10_T01_PORT", "8995"))
COURSE_ID = "demo-course-rag-trust-v1"
COURSE_TITLE = "RAG 应用开发与负责任评测实训"
VIEWPORTS = ((1440, 900), (1366, 768))
PASSWORDS = {
    "lzz": "404404aA",
    "teacher": "admin123",
    "demo-admin": "EduMatrix-Demo-2026",
}


def configure_environment(port: int) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "f10-t01-isolated-browser-secret",
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


def remove_runtime_files() -> None:
    runtime = RUNTIME_DIR.resolve()
    output = OUTPUT_DIR.resolve()
    if runtime == output or output not in runtime.parents:
        raise RuntimeError(f"runtime directory escapes F10-T01 evidence: {runtime}")
    for suffix in ("", "-shm", "-wal"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    for path in (FIXTURE_PATH, REPORT_PATH):
        if path.exists():
            path.unlink()
    for path in SCREENSHOT_DIR.glob("*.png"):
        path.unlink()


def prepare_fixture(port: int) -> None:
    configure_environment(port)
    remove_runtime_files()
    from app.competition_demo_seed import seed_competition_demo
    from app.database import (
        DBArtifact,
        DBAssessmentQuestionVersion,
        DBProfileSnapshot,
        DBSourceRef,
        DBUser,
        SessionLocal,
        init_db,
    )
    from app.m5_assessment_core import AttemptInput, record_attempt
    from app.m5_resources import resource_detail
    from app.resource_bundles import create_generation_job, execute_generation_job_demo

    init_db()
    with SessionLocal() as db:
        result = seed_competition_demo(db)
        learner = db.query(DBUser).filter_by(username="lzz").one()
        profile = db.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
        source = db.get(DBSourceRef, "demo-ref-07")
        if profile is None or source is None:
            raise RuntimeError("competition demo profile or source is missing")
        job = create_generation_job(
            db,
            learner,
            course_id=COURSE_ID,
            knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id,
            idempotency_key="f10-t01-b03-quiz-resource-001",
            scope="single",
            items=[{
                "type": "quiz",
                "title": "课程上下文即时练习",
                "source_ref_ids": [source.id],
                "completion_rule": "三道必做题均至少正确一次",
            }],
            learning_goal="依据当前课程来源完成一次可追溯即时练习",
        )
        db.commit()
        generated = execute_generation_job_demo(db, learner, job["job_id"])
        db.commit()
        generated_item = generated["items"][0]
        if generated_item["state"] != "succeeded":
            raise RuntimeError(f"quiz fixture generation failed: {generated_item}")
        resource_id = generated_item["resource"]["resource_id"]
        artifact = db.get(DBArtifact, resource_id)
        quiz_detail = resource_detail(db, artifact)
        quiz_projection = quiz_detail["quiz"]["current"]
        question = quiz_projection["questions"][0]
        question_version = db.get(DBAssessmentQuestionVersion, question["id"])
        correct_choice = question_version.answer_key["choice"]
        wrong_choice = next(choice for choice in ("A", "B", "C", "D") if choice != correct_choice)
        attempt, created = record_attempt(
            db,
            owner_public_id=learner.public_id,
            attempt=AttemptInput(
                question_version_id=question["id"],
                idempotency_key="f10-t01-b03-existing-attempt-001",
                mode="practice",
                answer={"choice": wrong_choice},
            ),
        )
        if not created or attempt.correct is not False:
            raise RuntimeError("quiz fixture did not create the expected incorrect attempt")
        db.commit()
        quiz_detail = resource_detail(db, artifact)
        quiz_projection = quiz_detail["quiz"]["current"]
        question = next(item for item in quiz_projection["questions"] if item["id"] == question_version.id)
        source_projection = quiz_projection["source_refs"][0]
        source_ref_id = source_projection.get("source_ref_id") or source_projection.get("id")
        if not source_ref_id:
            raise RuntimeError(f"quiz fixture source projection has no identity: {source_projection}")
        quiz_fixture = {
            "resource_id": resource_id,
            "title": quiz_projection["structured"]["title"],
            "question_id": question["id"],
            "question_prompt": question["prompt"],
            "attempt_id": attempt.id,
            "selected_choice": wrong_choice,
            "correct_choice": correct_choice,
            "source_ref_id": source_ref_id,
            "source_title": (
                source_projection.get("title")
                or source_projection.get("document_title")
                or source_projection.get("filename")
                or source_projection.get("locator")
                or source_ref_id
            ),
        }
    fixture = {
        "course_id": COURSE_ID,
        "course_title": COURSE_TITLE,
        "users": {
            "student": "lzz",
            "teacher": "teacher",
            "admin": "demo-admin",
        },
        "identity_bindings": result.identity_bindings,
        "quiz": quiz_fixture,
    }
    FIXTURE_PATH.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "prepared",
        "database": str(DB_PATH),
        "seed_status": result.status,
        "course_id": COURSE_ID,
    }, ensure_ascii=False))


def serve(port: int) -> None:
    configure_environment(port)
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=False)


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def wait_for_server(process: subprocess.Popen, port: int, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"managed F10-T01 server exited with {process.returncode}; see {MANAGED_SERVER_LOG}"
            )
        if port_is_open(port):
            return
        time.sleep(0.25)
    raise TimeoutError(f"managed F10-T01 server did not open port {port} within {timeout}s")


def stop_managed_server(process: subprocess.Popen, port: int) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and port_is_open(port):
        time.sleep(0.2)
    if port_is_open(port):
        raise RuntimeError(f"managed F10-T01 server left port {port} listening")


def managed_run(port: int) -> None:
    configure_environment(port)
    if port_is_open(port):
        raise RuntimeError(f"port {port} is already in use before managed F10-T01 E2E")
    prepare_fixture(port)
    MANAGED_SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--serve",
        "--port",
        str(port),
    ]
    with MANAGED_SERVER_LOG.open("w", encoding="utf-8") as server_log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )
        try:
            wait_for_server(process, port)
            with sync_playwright() as playwright:
                run_e2e(playwright, f"http://127.0.0.1:{port}", port=port)
        finally:
            stop_managed_server(process, port)


def api_login(context: BrowserContext, base_url: str, username: str) -> dict:
    response = context.request.post(
        f"{base_url}/api/auth/login",
        form={"username": username, "password": PASSWORDS[username]},
    )
    assert response.ok, f"login failed for {username}: {response.status} {response.text()}"
    return response.json()


def add_session(context: BrowserContext, session: dict) -> None:
    public_session = {
        "access_token": session["access_token"],
        "username": session["username"],
        "display_name": session["display_name"],
        "role": session["role"],
        "student_id": session["student_id"],
        "course_id": COURSE_ID,
        "course_title": COURSE_TITLE,
    }
    context.add_init_script(script=f"""
      const session = {json.dumps(public_session, ensure_ascii=False)};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username);
      localStorage.setItem('edumatrix_display_name', session.display_name);
      localStorage.setItem('edumatrix_role', session.role);
      localStorage.setItem('edumatrix_student_id', session.student_id);
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', session.course_id);
      localStorage.setItem('edumatrix_course_title', session.course_title);
    """)


def open_role_page(browser: Browser, base_url: str, username: str, viewport: tuple[int, int], report: dict) -> tuple[BrowserContext, Page]:
    context = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        locale="zh-CN",
        color_scheme="light",
    )
    session = api_login(context, base_url, username)
    add_session(context, session)
    page = context.new_page()
    attach_diagnostics(page, base_url, username, viewport, report)
    return context, page


def attach_diagnostics(page: Page, base_url: str, username: str, viewport: tuple[int, int], report: dict) -> None:
    origin = urlparse(base_url).netloc
    diagnostics = {
        "username": username,
        "viewport": list(viewport),
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "off_origin_requests": [],
    }
    report["browser_pages"].append(diagnostics)

    def on_response(response) -> None:
        if response.status >= 400:
            diagnostics["http_errors"].append({"status": response.status, "url": response.url})

    def on_request(request) -> None:
        parsed = urlparse(request.url)
        if parsed.scheme in {"http", "https"} and parsed.netloc != origin:
            diagnostics["off_origin_requests"].append(request.url)

    page.on("response", on_response)
    page.on("request", on_request)
    page.on("requestfailed", lambda request: diagnostics["failed_requests"].append({
        "url": request.url,
        "failure": request.failure,
    }))
    page.on("pageerror", lambda error: diagnostics["page_errors"].append(str(error)))
    page.on("console", lambda message: diagnostics["console_errors"].append(message.text) if message.type == "error" else None)


def goto(page: Page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(700)


def visible_metrics(page: Page) -> dict:
    return page.evaluate("""() => {
      const visible = (el) => {
        const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
      };
      const controls = [...document.querySelectorAll('button,a[href],input,select,textarea,[role="button"],[role="tab"]')]
        .filter(visible).map((el) => ({ el, rect: el.getBoundingClientRect() }));
      const collisions = [];
      for (let i = 0; i < controls.length; i += 1) {
        for (let j = i + 1; j < controls.length; j += 1) {
          const a = controls[i], b = controls[j];
          if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
          const overlapW = Math.min(a.rect.right, b.rect.right) - Math.max(a.rect.left, b.rect.left);
          const overlapH = Math.min(a.rect.bottom, b.rect.bottom) - Math.max(a.rect.top, b.rect.top);
          if (overlapW > 4 && overlapH > 4) collisions.push([
            (a.el.innerText || a.el.getAttribute('aria-label') || '').trim().slice(0, 48),
            (b.el.innerText || b.el.getAttribute('aria-label') || '').trim().slice(0, 48),
          ]);
        }
      }
      const textNodes = [...document.querySelectorAll('button,a[href],h1,h2,h3,strong,p,span,label,small,dt,dd')]
        .filter(visible).filter((el) => (el.innerText || '').trim());
      const clipped = textNodes.filter((el) => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false;
        return rect.right > innerWidth + 1 || rect.left < -1 ||
          (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap');
      }).map((el) => (el.innerText || '').trim().slice(0, 80)).slice(0, 20);
      const smallText = textNodes.filter((el) => Number.parseFloat(getComputedStyle(el).fontSize) < 13.5)
        .map((el) => ({ text: el.innerText.trim().slice(0, 48), size: getComputedStyle(el).fontSize })).slice(0, 20);
      const parseRgb = (value) => {
        const match = value.match(/[\d.]+/g);
        return match && match.length >= 3 ? match.slice(0, 3).map(Number) : null;
      };
      const luminance = (rgb) => {
        const values = rgb.map((value) => {
          const normalized = value / 255;
          return normalized <= .03928 ? normalized / 12.92 : ((normalized + .055) / 1.055) ** 2.4;
        });
        return .2126 * values[0] + .7152 * values[1] + .0722 * values[2];
      };
      const lowContrastPrimary = [...document.querySelectorAll('.button-primary,.primary-button,.publish-button')]
        .filter(visible).map((el) => {
          const style = getComputedStyle(el), foreground = parseRgb(style.color), background = parseRgb(style.backgroundColor);
          if (!foreground || !background) return null;
          const high = Math.max(luminance(foreground), luminance(background));
          const low = Math.min(luminance(foreground), luminance(background));
          return { text: (el.innerText || '').trim().slice(0, 48), ratio: (high + .05) / (low + .05) };
        }).filter((item) => item && item.ratio < 4.5);
      const forbiddenEffects = [...document.querySelectorAll('body *')].filter(visible).filter((el) => {
        const style = getComputedStyle(el);
        return style.backgroundImage.includes('gradient') || (style.backdropFilter && style.backdropFilter !== 'none');
      }).map((el) => String(el.className).slice(0, 80)).slice(0, 20);
      const themedColorRegression = [...document.querySelectorAll('body *')].filter(visible).filter((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.width * rect.height < 3000) return false;
        const rgb = parseRgb(getComputedStyle(el).backgroundColor);
        if (!rgb) return false;
        const [r, g, b] = rgb.map((value) => value / 255);
        const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
        const light = (max + min) / 2;
        const saturation = delta === 0 ? 0 : delta / (1 - Math.abs(2 * light - 1));
        let hue = 0;
        if (delta) {
          if (max === r) hue = 60 * (((g - b) / delta) % 6);
          else if (max === g) hue = 60 * ((b - r) / delta + 2);
          else hue = 60 * ((r - g) / delta + 4);
          if (hue < 0) hue += 360;
        }
        const green = hue >= 70 && hue <= 170 && saturation > .2;
        const brown = hue >= 15 && hue <= 50 && saturation > .28 && light < .7;
        const lightBlue = hue > 170 && hue <= 220 && saturation > .22 && light > .62;
        const bluePurple = hue > 220 && hue <= 300 && saturation > .3;
        return green || brown || lightBlue || bluePurple;
      }).map((el) => ({ className: String(el.className).slice(0, 80), color: getComputedStyle(el).backgroundColor })).slice(0, 20);
      return {
        viewport: [innerWidth, innerHeight],
        documentWidth: document.documentElement.scrollWidth,
        bodyTextLength: (document.body.innerText || '').trim().length,
        collisions, clipped, smallText, lowContrastPrimary, forbiddenEffects, themedColorRegression,
      };
    }""")


def capture(page: Page, report: dict, name: str) -> None:
    page.evaluate("""() => {
      window.scrollTo(0, 0);
      const content = document.querySelector('.app-content');
      if (content) content.scrollTo(0, 0);
    }""")
    page.wait_for_timeout(250)
    metrics = visible_metrics(page)
    filename = f"{name}.png"
    page.screenshot(path=str(SCREENSHOT_DIR / filename), full_page=True, animations="disabled")
    report["screenshots"].append(f"screenshots/{filename}")
    report["visual_checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] > 100, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["lowContrastPrimary"], metrics
    assert not metrics["forbiddenEffects"], metrics
    assert not metrics["themedColorRegression"], metrics


def assert_path(page: Page, expected_path: str) -> None:
    try:
        page.wait_for_function("expected => location.pathname === expected", arg=expected_path, timeout=20_000)
    except PlaywrightTimeoutError as exc:
        diagnostic = page.evaluate("""() => ({
          url: location.href,
          role: localStorage.getItem('edumatrix_role'),
          hasToken: Boolean(localStorage.getItem('edumatrix_token')),
          onboarded: localStorage.getItem('edumatrix_onboarded'),
          courseId: localStorage.getItem('edumatrix_course_id'),
          historyState: history.state,
          body: (document.body.innerText || '').trim().slice(0, 1200),
        })""")
        raise AssertionError(json.dumps({"expected_path": expected_path, **diagnostic}, ensure_ascii=False)) from exc
    assert urlparse(page.url).path == expected_path, page.url


def assert_course_preserved(page: Page) -> None:
    assert page.evaluate("localStorage.getItem('edumatrix_course_id')") == COURSE_ID


def query_value(page: Page, name: str) -> str:
    return (parse_qs(urlparse(page.url).query).get(name) or [""])[0]


def assert_recovery(page: Page, expected_title: str, expected_source: str, primary_label: str) -> None:
    assert_path(page, "/context-recovery")
    page.get_by_role("heading", name=expected_title, exact=True).wait_for(state="visible")
    page.get_by_text(expected_source, exact=True).wait_for(state="visible")
    primary = page.get_by_role("button", name=primary_label, exact=True)
    primary.wait_for(state="visible")
    primary.focus()
    focus = primary.evaluate("el => ({outline: getComputedStyle(el).outlineStyle, width: getComputedStyle(el).outlineWidth})")
    assert focus["outline"] != "none" and focus["width"] != "0px", focus
    assert page.get_by_text("没有创建空对象，也没有修改现有学习记录", exact=True).is_visible()


def run_quiz_chat_round_trip(
    page: Page, base_url: str, viewport: tuple[int, int], fixture: dict, report: dict,
) -> None:
    quiz = fixture["quiz"]
    suffix = f"student-{viewport[0]}x{viewport[1]}"
    resource_path = (
        f"/workspace/resources/quizzes/{quiz['resource_id']}"
        f"?course_id={COURSE_ID}&question_version_id={quiz['question_id']}"
    )
    goto(page, base_url, resource_path)
    assert_path(page, f"/workspace/resources/quizzes/{quiz['resource_id']}")
    assert query_value(page, "question_version_id") == quiz["question_id"]
    workspace = page.get_by_test_id("quiz-resource-workspace")
    workspace.wait_for(state="visible", timeout=30_000)
    card = workspace.get_by_test_id("inline-quiz-card")
    card.wait_for(state="visible", timeout=30_000)
    card.get_by_role("heading", name=quiz["question_prompt"], exact=True).wait_for(state="visible")
    feedback = card.locator(".feedback-panel")
    feedback.wait_for(state="visible")
    assert "这次还不正确" in feedback.inner_text()
    assert quiz["correct_choice"] in feedback.inner_text()
    history = workspace.locator(".attempt-history")
    history.get_by_text("本题作答历史", exact=True).wait_for(state="visible")
    assert history.get_by_text("1 次提交", exact=True).is_visible()
    assert quiz["selected_choice"] in history.inner_text()
    capture(page, report, f"{suffix}-quiz-resource")

    card.get_by_role("button", name="继续追问这道题", exact=True).click()
    follow_up = "为什么另一个选项不成立？"
    card.locator(".follow-up-form textarea").fill(follow_up)
    card.get_by_role("button", name="带着本题上下文追问", exact=True).click()
    assert_path(page, "/learn")
    assert query_value(page, "quiz_resource_id") == quiz["resource_id"]
    assert query_value(page, "question_version_id") == quiz["question_id"]
    assert query_value(page, "attempt_id") == quiz["attempt_id"]
    assert query_value(page, "course_id") == COURSE_ID
    assert follow_up in query_value(page, "quiz_follow_up")
    chat = page.get_by_test_id("focused-chat-workspace")
    chat.wait_for(state="visible", timeout=30_000)
    context = chat.get_by_test_id("chat-quiz-context")
    context.wait_for(state="visible", timeout=30_000)
    context.get_by_text(quiz["title"], exact=True).wait_for(state="visible")
    context.get_by_text(quiz["question_prompt"], exact=True).wait_for(state="visible")
    context.get_by_role("button", name=quiz["source_title"], exact=True).wait_for(state="visible")
    assert context.locator('input, select, textarea, [data-testid="inline-quiz-card"]').count() == 0
    for forbidden in ("提交答案", "提交新答案", "修改答案", "本题作答历史", "回答正确", "这次还不正确"):
        assert context.get_by_text(forbidden, exact=False).count() == 0, forbidden
    primary = context.get_by_role("button", name="进入测验题资源作答", exact=True)
    assert primary.count() == 1
    prompt = page.get_by_label("输入问题", exact=True).input_value()
    assert follow_up in prompt and quiz["selected_choice"] in prompt
    chat_url = page.url
    capture(page, report, f"{suffix}-chat-quiz-context")

    primary.click()
    assert_path(page, f"/workspace/resources/quizzes/{quiz['resource_id']}")
    assert query_value(page, "question_version_id") == quiz["question_id"]
    assert query_value(page, "course_id") == COURSE_ID
    returned_card = page.get_by_test_id("inline-quiz-card")
    returned_card.wait_for(state="visible", timeout=30_000)
    returned_card.get_by_role("heading", name=quiz["question_prompt"], exact=True).wait_for(state="visible")
    returned_card.locator(".feedback-panel").wait_for(state="visible")
    capture(page, report, f"{suffix}-quiz-returned")
    report["quiz_chat_round_trips"].append({
        "viewport": list(viewport),
        "resource_id": quiz["resource_id"],
        "question_version_id": quiz["question_id"],
        "attempt_id": quiz["attempt_id"],
        "chat_url": chat_url,
        "returned_url": page.url,
        "chat_answer_controls": 0,
        "primary_resource_actions": 1,
    })


def run_student(
    browser: Browser, base_url: str, viewport: tuple[int, int], fixture: dict, report: dict,
) -> None:
    suffix = f"student-{viewport[0]}x{viewport[1]}"
    context, page = open_role_page(browser, base_url, "lzz", viewport, report)
    try:
        goto(page, base_url, "/missing-f10-route?keep=1")
        assert_recovery(page, "没有找到这个页面", "/missing-f10-route", "返回学习首页")
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-unknown")
        page.get_by_role("button", name="返回学习首页", exact=True).click()
        assert_path(page, "/")
        assert_course_preserved(page)

        goto(page, base_url, "/spatial-workspace?keep=removed")
        assert_recovery(page, "此入口已停止使用", "/spatial-workspace", "返回学习首页")
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-removed")

        goto(page, base_url, f"/knowledge?course_id={COURSE_ID}")
        assert_path(page, "/knowledge")
        page.get_by_text("我的书架", exact=True).wait_for(state="visible", timeout=30_000)
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-knowledge")

        goto(page, base_url, "/marketplace")
        assert_path(page, "/marketplace")
        page.get_by_test_id("marketplace-workspace").wait_for(state="visible", timeout=30_000)
        page.locator(".loading-surface").wait_for(state="hidden", timeout=30_000)
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-marketplace")

        goto(page, base_url, "/interactive-lab?keep=model")
        assert_path(page, "/workspace/resources/models/legacy")
        page.get_by_text("可交互模型", exact=True).first.wait_for(state="visible", timeout=30_000)
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-resource-detail")

        run_quiz_chat_round_trip(page, base_url, viewport, fixture, report)
    finally:
        context.close()


def run_teacher(browser: Browser, base_url: str, viewport: tuple[int, int], report: dict) -> None:
    suffix = f"teacher-{viewport[0]}x{viewport[1]}"
    context, page = open_role_page(browser, base_url, "teacher", viewport, report)
    try:
        goto(page, base_url, "/enterprise-training?keep=deferred")
        assert_recovery(page, "此功能暂未开放", "/enterprise-training", "返回教学总览")
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-deferred")
        page.get_by_role("button", name="返回教学总览", exact=True).click()
        assert_path(page, "/teacher/overview")
        assert_course_preserved(page)

        goto(page, base_url, f"/knowledge?course_id={COURSE_ID}")
        assert_path(page, "/knowledge")
        page.get_by_text("我的书架", exact=True).wait_for(state="visible", timeout=30_000)
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-knowledge")

        goto(page, base_url, "/marketplace")
        assert_path(page, "/marketplace")
        page.get_by_test_id("marketplace-workspace").wait_for(state="visible", timeout=30_000)
        page.locator(".loading-surface").wait_for(state="hidden", timeout=30_000)
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-marketplace")

        goto(page, base_url, "/interactive-lab?keep=model")
        assert_path(page, "/workspace/resources/models/legacy")
        page.get_by_text("可交互模型", exact=True).first.wait_for(state="visible", timeout=30_000)
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-resource-detail")
    finally:
        context.close()


def run_admin(browser: Browser, base_url: str, viewport: tuple[int, int], report: dict) -> None:
    suffix = f"admin-{viewport[0]}x{viewport[1]}"
    context, page = open_role_page(browser, base_url, "demo-admin", viewport, report)
    try:
        goto(page, base_url, "/plugins?keep=internal")
        assert_recovery(page, "此入口仅供内部验证", "/plugins", "返回系统管理")
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-internal")
        page.get_by_role("button", name="返回系统管理", exact=True).click()
        assert_path(page, "/admin/system")
        assert_course_preserved(page)

        goto(page, base_url, "/knowledge")
        assert_path(page, "/admin/system")
        assert "access=forbidden" in page.url
        assert page.get_by_test_id("knowledge-shelf").count() == 0
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-knowledge-denied")

        goto(page, base_url, "/workspace/resources/models/legacy")
        assert_path(page, "/admin/system")
        assert "access=forbidden" in page.url
        assert_course_preserved(page)
        capture(page, report, f"{suffix}-resource-denied")
    finally:
        context.close()


def table_digest(database: Path, tables: tuple[str, ...]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    with sqlite3.connect(database, timeout=20) as db:
        for table in tables:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,),
            ).fetchone()
            if not exists:
                continue
            rows = db.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            encoded = json.dumps(rows, ensure_ascii=False, default=str, separators=(",", ":"))
            result[table] = {
                "rows": len(rows),
                "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            }
    return result


def database_audit(database: Path) -> dict[str, object]:
    with sqlite3.connect(database, timeout=20) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def run_e2e(playwright: Playwright, base_url: str, *, port: int = PORT) -> None:
    configure_environment(port)
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["course_id"] == COURSE_ID
    protected_tables = (
        "learning_events", "profile_snapshots", "student_profiles", "learning_paths",
        "path_nodes", "artifacts", "artifact_versions", "wrong_questions", "review_plans", "notes",
        "assessment_questions", "assessment_question_versions", "assessment_attempts",
        "assessment_grading_results", "assessment_ability_states",
        "chat_conversations", "chat_messages", "chat_attachments", "model_calls",
    )
    before = table_digest(DB_PATH, protected_tables)
    report = {
        "schema_version": "f10-t01-route-migration-browser.v2",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "database": str(DB_PATH),
        "viewports": [list(item) for item in VIEWPORTS],
        "screenshots": [],
        "visual_checks": {},
        "browser_pages": [],
        "quiz_chat_round_trips": [],
        "ordinary_browse_database_unchanged": False,
        "external_model_called": False,
    }
    browser = playwright.chromium.launch(headless=True)
    try:
        for viewport in VIEWPORTS:
            run_student(browser, base_url, viewport, fixture, report)
            run_teacher(browser, base_url, viewport, report)
            run_admin(browser, base_url, viewport, report)
        after = table_digest(DB_PATH, protected_tables)
        report["protected_state_before"] = before
        report["protected_state_after"] = after
        assert before == after, {"before": before, "after": after}
        report["ordinary_browse_database_unchanged"] = True
        report["external_model_called"] = before.get("model_calls") != after.get("model_calls")
        report["external_model_evidence"] = {
            "provider": os.environ["EDUMATRIX_LLM_PROVIDER"],
            "endpoint_configured": bool(os.environ["EDUMATRIX_LLM_ENDPOINT"]),
            "model_calls_before": before.get("model_calls"),
            "model_calls_after": after.get("model_calls"),
            "off_origin_request_count": sum(
                len(item["off_origin_requests"]) for item in report["browser_pages"]
            ),
        }
        assert report["external_model_called"] is False, report["external_model_evidence"]
        assert len(report["quiz_chat_round_trips"]) == len(VIEWPORTS), report["quiz_chat_round_trips"]
        audit = database_audit(DB_PATH)
        assert audit["integrity"] == "ok", audit
        assert audit["foreign_key_violations"] == 0, audit
        report["database_audit"] = audit
        for page_report in report["browser_pages"]:
            assert not page_report["http_errors"], page_report
            assert not page_report["failed_requests"], page_report
            assert not page_report["page_errors"], page_report
            assert not page_report["console_errors"], page_report
            assert not page_report["off_origin_requests"], page_report
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = repr(exc)
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        browser.close()
    print(json.dumps({
        "status": report["status"],
        "screenshots": len(report["screenshots"]),
        "database": report.get("database_audit"),
        "external_model_called": report["external_model_called"],
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--serve", action="store_true")
    group.add_argument("--run", action="store_true")
    group.add_argument("--managed-run", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    configure_environment(args.port)
    if args.prepare:
        prepare_fixture(args.port)
    elif args.serve:
        serve(args.port)
    elif args.managed_run:
        managed_run(args.port)
    else:
        with sync_playwright() as playwright:
            run_e2e(playwright, f"http://127.0.0.1:{args.port}", port=args.port)


if __name__ == "__main__":
    main()
