"""Real-browser evidence for the conversational initial learner profile.

Runs against an isolated SQLite database, uses Chromium through Playwright and
captures the learner-visible conversation, richer profile signals and a
profile-aware follow-up chat.  The production database and official checkpoint
are never opened for writes.
"""

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

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "ONBOARDING-CONVERSATIONAL-PROFILE-01"
OUTPUT_DIR = EVIDENCE / "browser"
DB_PATH = EVIDENCE / "conversational_onboarding_runtime.db"
PORT = int(os.getenv("EDUMATRIX_CONVERSATIONAL_ONBOARDING_PORT", "8934"))
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Conversational-Onboarding-2026!"
COURSE_ID = "course-conversational-onboarding"


def wait_port(expected: bool, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected state {expected}")


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()


def register(page: Page, username: str) -> dict[str, str]:
    response = page.request.post(
        f"{BASE_URL}/api/auth/register",
        data={"username": username, "password": PASSWORD, "display_name": "自然对话验收学生"},
    )
    if not response.ok:
        raise AssertionError(f"register failed: {response.status} {response.text()}")
    payload = response.json()
    return {"username": payload["username"], "token": payload["access_token"]}


def attach_course(username: str) -> None:
    with sqlite3.connect(DB_PATH) as db:
        public_id = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
        db.execute(
            """INSERT OR IGNORE INTO courses
               (id, version, title, subject, description, domain_pack, language, content_origin,
                license_text, visibility, status, owner_public_id, manifest_version, manifest_data, created_at)
               VALUES (?, '1', ?, '人工智能', '用于自然对话画像验收的公开课程上下文。', 'ai-ml', 'zh-CN', 'team-curated', '', 'public',
                       'published', NULL, '1', '{}', CURRENT_TIMESTAMP)""",
            (COURSE_ID, "人工智能与深度学习：从机器学习基础到大模型智能体"),
        )
        db.execute(
            """INSERT OR IGNORE INTO course_memberships
               (id, course_id, user_public_id, role, status, created_at, updated_at)
               VALUES (?, ?, ?, 'student', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (f"cm-{username}", COURSE_ID, public_id),
        )
        db.execute(
            "UPDATE student_profiles SET target_course=? WHERE student_id=?",
            ("人工智能与深度学习：从机器学习基础到大模型智能体", username),
        )
        db.commit()


def attach_diagnostics(page: Page, report: dict, scope: str) -> None:
    page.on("pageerror", lambda error: report["page_errors"].append({"scope": scope, "message": str(error)}))
    page.on("console", lambda message: report["console_errors"].append({"scope": scope, "message": message.text}) if message.type == "error" else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({"scope": scope, "url": request.url, "failure": str(request.failure)}))
    page.on("response", lambda response: report["http_errors"].append({"scope": scope, "status": response.status, "url": response.url}) if response.status >= 400 else None)


def capture(page: Page, report: dict, name: str) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(450)
    path = OUTPUT_DIR / name
    page.screenshot(path=str(path), full_page=True)
    report["screenshots"].append(str(path))
    report.setdefault("screenshot_meta", {})[name] = {
        "viewport": [page.viewport_size["width"], page.viewport_size["height"]],
        "url": page.url,
        "visible_text": page.locator("body").inner_text()[:2200],
    }


def login(page: Page, user: dict[str, str]) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_test_id("login-username").fill(user["username"])
    page.get_by_test_id("login-password").fill(PASSWORD)
    page.get_by_test_id("login-submit").click()
    page.wait_for_url("**/onboarding**", timeout=30_000)
    page.get_by_test_id("onboarding-current-question").wait_for(state="visible", timeout=30_000)


def send_answer(page: Page, text: str) -> None:
    page.get_by_label("你的回答").fill(text)
    page.get_by_role("button", name="发送回答").click()
    page.get_by_test_id("onboarding-candidate-editor").wait_for(state="visible", timeout=30_000)


def confirm_answer(page: Page) -> None:
    editor = page.get_by_test_id("onboarding-candidate-editor")
    editor.get_by_role("button", name="确认本轮画像").click()
    editor.wait_for(state="hidden", timeout=30_000)


def db_audit(report: dict, username: str) -> None:
    with sqlite3.connect(DB_PATH) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        profile = db.execute(
            "SELECT major, motivation_type, focus_level, cognitive_load, frustration_index, interaction_preferences, dimension_states FROM student_profiles WHERE student_id=?",
            (username,),
        ).fetchone()
        turns = db.execute(
            """SELECT t.question_dimension, t.user_answer FROM onboarding_turns t
               JOIN onboarding_sessions s ON s.id=t.session_id WHERE s.student_id=? ORDER BY t.created_at""",
            (username,),
        ).fetchall()
    report["database_audit"] = {
        "integrity_check": integrity,
        "foreign_key_violations": foreign_keys,
        "profile": list(profile) if profile else None,
        "turns": [list(item) for item in turns],
    }
    if integrity != "ok" or foreign_keys:
        raise AssertionError(report["database_audit"])


def run_viewport(browser, viewport: tuple[int, int], report: dict) -> None:
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    setup = context.new_page()
    username = f"conv_onboard_{viewport[0]}_{int(time.time() * 1000)}"
    user = register(setup, username)
    attach_course(username)
    setup.close()
    page = context.new_page()
    attach_diagnostics(page, report, f"{viewport[0]}x{viewport[1]}")
    try:
        login(page, user)
        capture(page, report, f"{viewport[0]}x{viewport[1]}-01-open-conversation.png")

        send_answer(page, "我在公司做知识库问答项目，最近想把检索效果做稳，也准备面试时讲清楚项目。")
        assert page.get_by_text("我听到的是：", exact=False).is_visible()
        capture(page, report, f"{viewport[0]}x{viewport[1]}-02-reflection-and-candidate.png")
        confirm_answer(page)
        assert "知识库问答项目" in page.get_by_test_id("onboarding-current-question").inner_text()
        capture(page, report, f"{viewport[0]}x{viewport[1]}-03-contextual-follow-up.png")

        answers = [
            "希望能上线一个可用版本，最好能通过面试中的项目追问。",
            "Python 和线性代数做过一些，但时间很碎，通勤时学习，基础有些断层。",
            "我最容易在公式推导和概念区别上卡住，一看到长题就焦虑。",
            "先看一个真实例子，再画图解释，最后我自己写代码验证；每次短一点。",
        ]
        for answer in answers:
            send_answer(page, answer)
            confirm_answer(page)

        complete = page.get_by_test_id("onboarding-complete")
        complete.wait_for(state="visible", timeout=30_000)
        assert page.get_by_text("学习伙伴已经注意到", exact=False).is_visible()
        capture(page, report, f"{viewport[0]}x{viewport[1]}-04-richer-profile-confirmed.png")
        complete.get_by_role("button", name="确认初始画像").click()
        page.get_by_test_id("onboarding-complete").wait_for(state="visible", timeout=30_000)
        capture(page, report, f"{viewport[0]}x{viewport[1]}-05-initial-profile-finalized.png")

        # Demonstrate the same learner profile entering a normal Chat question.
        page.goto(f"{BASE_URL}/chat?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=30_000)
        page.get_by_test_id("chat-answer-workspace").wait_for(state="visible", timeout=30_000)
        page.get_by_label("输入问题").fill("请用一个真实项目例子解释混合检索，并给我一个短练习。")
        page.get_by_role("button", name="发送").click()
        page.wait_for_timeout(2_500)
        capture(page, report, f"{viewport[0]}x{viewport[1]}-06-profile-aware-chat.png")
        report.setdefault("chat_text", {})[str(viewport)] = page.locator("body").inner_text()[:4000]

        db_audit(report, username)
    finally:
        context.close()


def main() -> int:
    clear_output()
    report = {
        "schema_version": "onboarding-conversational-profile.browser-e2e.v1",
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "database": str(DB_PATH),
        "screenshots": [],
        "screenshot_meta": {},
        "page_errors": [],
        "console_errors": [],
        "failed_requests": [],
        "http_errors": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    process = None
    try:
        env = os.environ.copy()
        env.update({
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "conversational-onboarding-isolated-secret",
            "EDUMATRIX_LLM_PROVIDER": "deterministic",
            "EDUMATRIX_LLM_MODEL": "deterministic",
            "EDUMATRIX_LLM_API_KEY": "",
            "EDUMATRIX_LLM_ENDPOINT": "",
            "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
            "EDUMATRIX_ONBOARDING_V2": "1",
            "EDUMATRIX_DEMO_MODE": "1",
            "EDUMATRIX_SANDBOX_MODE": "trusted_local",
            "EDUMATRIX_RELOAD": "0",
            "EDUMATRIX_HOST": "127.0.0.1",
            "EDUMATRIX_PORT": str(PORT),
            "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONUNBUFFERED": "1",
        })
        log_path = OUTPUT_DIR / "backend.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                for viewport in ((1440, 900), (1366, 768)):
                    run_viewport(browser, viewport, report)
                browser.close()
        if report["page_errors"] or report["console_errors"] or report["failed_requests"] or report["http_errors"]:
            raise AssertionError({key: report[key] for key in ("page_errors", "console_errors", "failed_requests", "http_errors")})
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=20)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            try:
                wait_port(False, 15)
            except RuntimeError:
                pass
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (EVIDENCE / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
