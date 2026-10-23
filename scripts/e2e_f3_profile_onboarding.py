"""Desktop browser acceptance for F3-T01 natural-language profile onboarding."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("EDUMATRIX_F3_ONBOARDING_PORT", "8892"))
BASE_URL = f"http://127.0.0.1:{PORT}"
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f3_t01_profile_onboarding"
DB_PATH = OUTPUT_DIR / "f3_t01_runtime.db"
PASSWORD = "F3-onboarding-2026!"
ANSWERS = (
    "我在华东理工大学读人工智能专业大二。",
    "我想先通过机器学习课程考试，再完成一个可信 RAG 项目。",
    "我学过 Python、线性代数和概率论，但模型评估基础一般。",
    "我最容易卡在公式推导和相似概念辨析。",
    "我喜欢先看例子，再分步推导，最后写代码验证。",
)


def wait_port(expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected state: {expected}")


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
        data={"username": username, "password": PASSWORD, "display_name": "画像引导验收学生"},
    )
    if not response.ok:
        raise AssertionError(f"register failed: {response.status} {response.text()}")
    payload = response.json()
    return {
        "token": payload["access_token"],
        "username": payload["username"],
    }


def attach_course(username: str) -> None:
    with sqlite3.connect(DB_PATH) as db:
        public_id = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
        db.execute(
            """INSERT OR IGNORE INTO courses
               (id, version, title, subject, description, domain_pack, language, content_origin,
                license_text, visibility, status, owner_public_id, manifest_version, manifest_data, created_at)
               VALUES (?, '1', ?, '人工智能', '', 'ai-ml', 'zh-CN', 'team-curated', '', 'public',
                       'published', NULL, '1', '{}', CURRENT_TIMESTAMP)""",
            ("course-f3-onboarding", "机器学习导论"),
        )
        db.execute(
            """INSERT INTO course_memberships
               (id, course_id, user_public_id, role, status, created_at, updated_at)
               VALUES (?, ?, ?, 'student', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (f"cm-{username}", "course-f3-onboarding", public_id),
        )
        db.commit()


def attach_errors(page: Page, report: dict, scope: str) -> None:
    page.on("pageerror", lambda error: report["browser_errors"].append({
        "scope": scope, "type": "pageerror", "message": str(error),
    }))
    page.on("console", lambda message: report["browser_errors"].append({
        "scope": scope, "type": "console", "message": message.text,
    }) if message.type == "error" else None)
    page.on("requestfailed", lambda request: report["browser_errors"].append({
        "scope": scope, "type": "requestfailed", "url": request.url, "message": str(request.failure),
    }))
    page.on("response", lambda response: report["http_errors"].append({
        "scope": scope, "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)


def page_metrics(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const visible = (el) => {
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0 &&
              rect.width > 1 && rect.height > 1 && rect.right > 0 && rect.bottom > 0 &&
              rect.left < innerWidth && rect.top < innerHeight
          }
          const controls = [...document.querySelectorAll('button,a[href],input,textarea,select')].filter(visible)
          const collisions = []
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i], b = controls[j]
            if (a.contains(b) || b.contains(a)) continue
            const x = a.getBoundingClientRect(), y = b.getBoundingClientRect()
            const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left)
            const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top)
            if (overlapW > 3 && overlapH > 3) collisions.push([
              (a.innerText || a.getAttribute('aria-label') || a.title || a.tagName).trim().slice(0, 32),
              (b.innerText || b.getAttribute('aria-label') || b.title || b.tagName).trim().slice(0, 32),
            ])
          }
          const clipped = [...document.querySelectorAll('h1,h2,h3,strong,button,label,p')].filter((el) => {
            if (!visible(el)) return false
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            if (style.textOverflow === 'ellipsis') return false
            if (rect.right > innerWidth + 1 || rect.left < -1) return true
            if (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap') return true
            return false
          }).map((el) => ({tag: el.tagName, text: (el.innerText || '').trim().slice(0, 64)}))
          const smallText = [...document.querySelectorAll('body *')].filter((el) =>
            visible(el) && el.children.length === 0 && (el.innerText || '').trim() &&
            Number.parseFloat(getComputedStyle(el).fontSize) < 13.5
          ).map((el) => ({tag: el.tagName, text: el.innerText.trim().slice(0, 48), size: getComputedStyle(el).fontSize})).slice(0, 30)
          const visualEffects = [...document.querySelectorAll('.onboarding-page *')].filter(visible).flatMap((el) => {
            const style = getComputedStyle(el), issues = []
            if (style.backgroundImage && style.backgroundImage !== 'none') issues.push('background-image')
            if (style.backdropFilter && style.backdropFilter !== 'none') issues.push('backdrop-filter')
            return issues.map((issue) => ({issue, tag: el.tagName, className: String(el.className).slice(0, 80)}))
          })
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            documentHeight: document.documentElement.scrollHeight,
            bodyTextLength: (document.body.innerText || '').trim().length,
            collisions,
            clipped,
            smallText,
            visualEffects,
            progressText: document.querySelector('[data-testid="onboarding-progress"]')?.innerText || '',
          }
        }"""
    )


def capture(page: Page, report: dict, name: str) -> dict:
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(300)
    metrics = page_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True)
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    if metrics["documentWidth"] > metrics["viewport"][0]:
        raise AssertionError(f"horizontal overflow at {name}: {metrics}")
    if metrics["collisions"]:
        raise AssertionError(f"control collision at {name}: {metrics['collisions']}")
    if metrics["clipped"]:
        raise AssertionError(f"clipped text at {name}: {metrics['clipped']}")
    if metrics["smallText"]:
        raise AssertionError(f"text below 14px at {name}: {metrics['smallText']}")
    if metrics["visualEffects"]:
        raise AssertionError(f"forbidden decorative visual effect at {name}: {metrics['visualEffects']}")
    return metrics


def login_into_onboarding(page: Page, user: dict[str, str]) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_test_id("login-username").fill(user["username"])
    page.get_by_test_id("login-password").fill(PASSWORD)
    with page.expect_response(
        lambda response: response.url.endswith("/api/auth/login") and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(r".*/onboarding(?:\?.*)?$"), timeout=30_000)
    page.get_by_test_id("onboarding-v2").wait_for(state="visible", timeout=30_000)
    page.get_by_test_id("onboarding-current-question").wait_for(state="visible", timeout=30_000)


def answer_current(page: Page, answer: str) -> None:
    page.get_by_label("你的回答").fill(answer)
    with page.expect_response(
        lambda response: response.url.endswith("/api/v1/onboarding/turns") and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_role("button", name="发送回答").click()
    editor = page.get_by_test_id("onboarding-candidate-editor")
    editor.wait_for(state="visible", timeout=20_000)
    editor.get_by_text("回答已保存", exact=False).wait_for(state="visible")


def confirm_current(page: Page) -> None:
    editor = page.get_by_test_id("onboarding-candidate-editor")
    with page.expect_response(
        lambda response: "/api/v1/onboarding/turns/" in response.url and response.url.endswith("/confirm") and response.status == 200,
        timeout=30_000,
    ):
        editor.get_by_role("button", name=re.compile(r"确认本轮画像|再次保存到画像|更新为本次回答")).click()
    editor.wait_for(state="hidden", timeout=20_000)


def run_viewport(browser, viewport: tuple[int, int], report: dict) -> None:
    suffix = f"{viewport[0]}x{viewport[1]}"
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    setup_page = context.new_page()
    user = register(setup_page, f"f3_onboarding_{viewport[0]}_{int(time.time() * 1000)}")
    attach_course(user["username"])
    setup_page.close()

    page = context.new_page()
    attach_errors(page, report, suffix)
    try:
        login_into_onboarding(page, user)
        report["checks"][f"{suffix}-login-routing"] = {
            "url": page.url,
            "onboardingVisible": page.get_by_test_id("onboarding-v2").is_visible(),
        }
        assert page.get_by_test_id("onboarding-profile-summary").is_visible()
        assert page.get_by_text("不需要上传课程材料", exact=False).is_visible()
        capture(page, report, f"{suffix}-01-first-question.png")

        answer_current(page, ANSWERS[0])
        capture(page, report, f"{suffix}-02-first-candidate.png")
        confirm_current(page)
        page.reload(wait_until="domcontentloaded")
        page.get_by_test_id("onboarding-v2").wait_for(state="visible", timeout=30_000)
        page.get_by_test_id("onboarding-progress").get_by_text("1/5", exact=True).wait_for(state="visible")
        assert page.get_by_text("人工智能", exact=False).count() > 0
        assert page.get_by_test_id("onboarding-current-question").inner_text().find("学习目标") >= 0
        capture(page, report, f"{suffix}-03-resumed-after-refresh.png")

        for answer in ANSWERS[1:]:
            answer_current(page, answer)
            confirm_current(page)

        complete = page.get_by_test_id("onboarding-complete")
        complete.wait_for(state="visible", timeout=30_000)
        assert page.get_by_test_id("onboarding-progress").get_by_text("5/5", exact=True).is_visible()
        assert complete.get_by_role("button", name="进入入学诊断").is_visible()
        final_metrics = capture(page, report, f"{suffix}-04-complete.png")
        assert "5/5" in final_metrics["progressText"]

        with sqlite3.connect(DB_PATH) as db:
            session_row = db.execute(
                "SELECT status, checkpoint, version FROM onboarding_sessions WHERE student_id=?",
                (user["username"],),
            ).fetchone()
            turn_count = db.execute(
                """SELECT COUNT(*) FROM onboarding_turns t JOIN onboarding_sessions s ON s.id=t.session_id
                   WHERE s.student_id=?""",
                (user["username"],),
            ).fetchone()[0]
            profile = db.execute(
                "SELECT major, knowledge_base, cognitive_style FROM student_profiles WHERE student_id=?",
                (user["username"],),
            ).fetchone()
        assert session_row[0] == "confirmed" and session_row[1] == 5 and session_row[2] >= 6
        assert turn_count == 5
        assert profile[0] == "人工智能"
        assert "Python" in profile[1]
        assert profile[2] == "代码实操导向"
        report["checks"][f"{suffix}-persistence"] = {
            "session": list(session_row),
            "turnCount": turn_count,
            "profile": list(profile),
        }
        complete.get_by_role("button", name="进入入学诊断").click()
        page.wait_for_url(re.compile(r".*/workspace/assessment/entry(?:\?.*)?$"), timeout=30_000)
        report["checks"][f"{suffix}-completion-routing"] = {"url": page.url}
    finally:
        context.close()


def main() -> int:
    clear_output()
    report = {
        "schema_version": "f3-t01.profile-onboarding-browser-e2e.v1",
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "database": str(DB_PATH),
        "screenshots": [],
        "checks": {},
        "browser_errors": [],
        "http_errors": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    process = None
    try:
        env = os.environ.copy()
        env.update({
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "f3-onboarding-isolated-secret",
            "EDUMATRIX_LLM_PROVIDER": "deterministic",
            "EDUMATRIX_LLM_MODEL": "deterministic",
            "EDUMATRIX_LLM_API_KEY": "",
            "EDUMATRIX_LLM_ENDPOINT": "",
            "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
            "EDUMATRIX_ONBOARDING_V2": "1",
            "EDUMATRIX_RELOAD": "0",
            "EDUMATRIX_HOST": "127.0.0.1",
            "EDUMATRIX_PORT": str(PORT),
            "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONUNBUFFERED": "1",
            "EDUMATRIX_SANDBOX_MODE": "disabled",
        })
        with (OUTPUT_DIR / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                for viewport in ((1440, 900), (1366, 768)):
                    run_viewport(browser, viewport, report)
                browser.close()
        if report["browser_errors"] or report["http_errors"]:
            raise AssertionError({
                "browser_errors": report["browser_errors"],
                "http_errors": report["http_errors"],
            })
        report["result"] = "passed"
    except Exception as error:
        report["result"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, text=True, timeout=20,
            )
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            try:
                wait_port(False, 15)
            except RuntimeError:
                pass
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
