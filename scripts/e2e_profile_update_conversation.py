"""Real-browser evidence for the independent conversational profile update page."""

from __future__ import annotations

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
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "LEARNING-PROFILE-CONVERSATIONAL-UPDATE-01"
OUTPUT_DIR = EVIDENCE / "browser"
DB_PATH = EVIDENCE / "profile_update_runtime.db"
PORT = int(os.getenv("EDUMATRIX_PROFILE_UPDATE_PORT", "8947"))
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Profile-Update-2026!"
COURSE_ID = "course-profile-update-conversation"


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
        data={"username": username, "password": PASSWORD, "display_name": "自然更新验收学生"},
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
               VALUES (?, '1', ?, '人工智能', '用于独立画像更新验收的课程上下文。', 'ai-ml', 'zh-CN', 'team-curated', '', 'public',
                       'published', NULL, '1', '{}', CURRENT_TIMESTAMP)""",
            (COURSE_ID, "人工智能与深度学习：从机器学习基础到大模型智能体"),
        )
        db.execute(
            """INSERT OR IGNORE INTO course_memberships
               (id, course_id, user_public_id, role, status, created_at, updated_at)
               VALUES (?, ?, ?, 'student', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (f"cm-profile-update-{username}", COURSE_ID, public_id),
        )
        db.execute(
            """UPDATE student_profiles
               SET target_course=?, major=?, motivation_type=?, learning_goals=?, interaction_preferences=?
               WHERE student_id=?""",
            (
                "人工智能与深度学习：从机器学习基础到大模型智能体",
                "软件工程",
                "希望把知识用进项目",
                json.dumps(["完成一个能上线的知识库问答项目"], ensure_ascii=False),
                json.dumps(["先看例子，再动手验证"], ensure_ascii=False),
                username,
            ),
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
    page.wait_for_timeout(500)
    path = OUTPUT_DIR / name
    page.screenshot(path=str(path), full_page=True)
    report["screenshots"].append(str(path))
    report.setdefault("screenshot_meta", {})[name] = {
        "viewport": [page.viewport_size["width"], page.viewport_size["height"]],
        "url": page.url,
        "visible_text": page.locator("body").inner_text()[:3500],
    }


def seed_session(page: Page, user: dict[str, str]) -> None:
    page.add_init_script(f"""(() => {{
      localStorage.setItem('edumatrix_token', {json.dumps(user['token'])});
      localStorage.setItem('edumatrix_role', 'student');
      localStorage.setItem('edumatrix_student_id', {json.dumps(user['username'])});
      localStorage.setItem('edumatrix_onboarded', 'true');
    }})()""")


def run_viewport(browser, viewport: tuple[int, int], report: dict) -> None:
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    setup = context.new_page()
    username = f"profile_update_{viewport[0]}_{int(time.time() * 1000)}"
    user = register(setup, username)
    attach_course(username)
    setup.close()
    page = context.new_page()
    seed_session(page, user)
    attach_diagnostics(page, report, f"{viewport[0]}x{viewport[1]}")
    try:
        page.goto(f"{BASE_URL}/profile/learning?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=30_000)
        page.get_by_test_id("profile-continuous-update").wait_for(state="visible", timeout=30_000)
        capture(page, report, f"{viewport[0]}x{viewport[1]}-01-profile-entry.png")
        page.get_by_test_id("profile-continuous-update").click()
        page.get_by_test_id("profile-update-page").wait_for(state="visible", timeout=30_000)
        capture(page, report, f"{viewport[0]}x{viewport[1]}-02-independent-page.png")

        questions = [
            "最近做检索项目时，关键词命中已经顺手了，但换一种说法就不太确定；我通常会先看一个小例子再动手改代码。",
            "我想把这个项目真正上线，也想能把每一步讲给面试官听清楚；通勤时间比较碎，遇到长公式会有点紧张。",
            "如果今天只有二十分钟，我希望先看结论和图，再自己做一个小实验，错了能马上告诉我哪里需要重来。",
            "接下来一段时间我最想把学到的东西用在检索项目和面试准备上。平时只能利用通勤和晚饭后的零碎时间，连续学太久反而容易走神。",
            "如果我连续几次做错，希望你先指出我卡在哪一步，再给一个小提示让我自己改；改对之后我想再换一道相近的题确认真的会了。",
        ]
        for index, text in enumerate(questions, start=1):
            page.get_by_label("想和我说什么").fill(text)
            page.get_by_role("button", name="发送这一段").click()
            page.get_by_test_id("profile-update-round-review").wait_for(state="visible", timeout=30_000)
            review_step = 3 + (index - 1) * 3
            capture(page, report, f"{viewport[0]}x{viewport[1]}-{review_step:02d}-round-{index}-review.png")
            if index < len(questions):
                page.get_by_role("button", name="记下这些，继续聊一会儿").click()
                page.get_by_test_id("profile-update-current-question").wait_for(state="visible", timeout=30_000)
                capture(page, report, f"{viewport[0]}x{viewport[1]}-{review_step + 1:02d}-round-{index}-continued.png")
            else:
                page.get_by_role("button", name="这次先聊到这里").click()
                page.get_by_test_id("profile-update-complete").wait_for(state="visible", timeout=30_000)
                capture(page, report, f"{viewport[0]}x{viewport[1]}-{review_step + 1:02d}-complete.png")

        body_text = page.locator("body").inner_text()
        report.setdefault("conversation_text", {})[str(viewport)] = body_text[:7000]
        conversation_text = page.locator('[aria-label="学习伙伴对话"]').inner_text()
        forbidden_terms = ("上下文", "约束", "确定性", "confidence", "prompt", "trace", "内部", "字段", "十维", "置信度")
        quality_issues = [term for term in forbidden_terms if term.lower() in conversation_text.lower()]
        if "。。" in conversation_text or "你刚才讲的是：你刚才讲的是" in conversation_text:
            quality_issues.append("重复回声或标点")
        report.setdefault("conversation_quality", {})[str(viewport)] = {
            "forbidden_terms": quality_issues,
            "duplicate_echo_free": "。。" not in conversation_text and "你刚才讲的是：你刚才讲的是" not in conversation_text,
            "conversation_length": len(conversation_text),
        }
        if quality_issues:
            raise AssertionError({"conversation_quality": quality_issues})
        report.setdefault("navigation", {})[str(viewport)] = {
            "independent_route": "/profile/update" in page.url,
            "complete_visible": page.get_by_test_id("profile-update-complete").is_visible(),
        }
        page.get_by_role("button", name="回到学习画像").click()
        page.get_by_test_id("profile-knowledge-map").wait_for(state="visible", timeout=30_000)
        capture(page, report, f"{viewport[0]}x{viewport[1]}-17-return-profile.png")
        report["last_username"] = username
    finally:
        context.close()


def db_audit(report: dict) -> None:
    with sqlite3.connect(DB_PATH) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
        rows = db.execute(
            "SELECT profile_version, snapshot FROM profile_snapshots ORDER BY created_at"
        ).fetchall()
        turns = db.execute(
            "SELECT status, question_dimension, user_answer FROM onboarding_turns WHERE question_dimension='continuous' ORDER BY created_at"
        ).fetchall()
    report["database_audit"] = {
        "integrity_check": integrity,
        "foreign_key_violations": foreign_keys,
        "continuous_snapshots": [
            {"profile_version": row[0], "kind": (json.loads(row[1] or "{}").get("kind") if isinstance(row[1], str) else None)}
            for row in rows
        ],
        "continuous_turns": [list(row) for row in turns],
    }
    expected_dimensions = {
        "knowledge_mastery",
        "misconception_profile",
        "understanding_fluency_transfer",
        "cognitive_processing",
        "learning_strategy",
        "metacognition",
        "motivation_and_purpose",
        "affect_resilience",
        "interaction_preference",
        "learning_context",
    }
    observed_dimensions: set[str] = set()
    for row in rows:
        try:
            snapshot = json.loads(row[1] or "{}")
        except (TypeError, json.JSONDecodeError):
            snapshot = {}
        observed_dimensions.update((snapshot.get("dimension_states") or {}).keys())
    report["database_audit"]["continuous_dimension_keys"] = sorted(observed_dimensions)
    report["database_audit"]["continuous_dimension_count"] = len(observed_dimensions)
    if observed_dimensions != expected_dimensions:
        raise AssertionError({"continuous_dimension_keys": sorted(observed_dimensions)})
    if integrity != "ok" or foreign_keys:
        raise AssertionError(report["database_audit"])


def main() -> int:
    clear_output()
    report = {
        "schema_version": "profile-update-conversation.browser-e2e.v1",
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
            "EDUMATRIX_AUTH_SECRET_KEY": "profile-update-isolated-secret",
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
        db_audit(report)
        if report["page_errors"] or report["console_errors"] or report["failed_requests"] or report["http_errors"]:
            raise AssertionError({key: report[key] for key in ("page_errors", "console_errors", "failed_requests", "http_errors")})
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = repr(exc)
        raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (EVIDENCE / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        try:
            wait_port(False, timeout=10)
        except Exception:
            pass
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
