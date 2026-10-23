"""Desktop browser acceptance for F3-T02 optional personal evidence and finalization."""

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
PORT = int(os.getenv("EDUMATRIX_F3_T02_PORT", "8893"))
BASE_URL = f"http://127.0.0.1:{PORT}"
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f3_t02_personal_evidence"
DB_PATH = OUTPUT_DIR / "f3_t02_runtime.db"
PASSWORD = "F3-t02-2026!"
ANSWERS = (
    "我在华东理工大学读人工智能专业大二。",
    "我想通过机器学习课程考试，并完成一个可信 RAG 项目。",
    "我学过 Python、线性代数和概率论。",
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


def register(page: Page, username: str) -> None:
    response = page.request.post(
        f"{BASE_URL}/api/auth/register",
        data={"username": username, "password": PASSWORD, "display_name": "F3-T02 验收学生"},
    )
    if not response.ok:
        raise AssertionError(f"register failed: {response.status} {response.text()}")


def attach_course(username: str) -> None:
    with sqlite3.connect(DB_PATH) as db:
        public_id = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
        db.execute(
            """INSERT OR IGNORE INTO courses
               (id, version, title, subject, description, domain_pack, language, content_origin,
                license_text, visibility, status, owner_public_id, manifest_version, manifest_data, created_at)
               VALUES (?, '1', ?, '人工智能', '', 'ai-ml', 'zh-CN', 'team-curated', '', 'public',
                       'published', NULL, '1', '{}', CURRENT_TIMESTAMP)""",
            ("course-f3-t02", "机器学习导论"),
        )
        db.execute(
            """INSERT INTO course_memberships
               (id, course_id, user_public_id, role, status, created_at, updated_at)
               VALUES (?, ?, ?, 'student', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (f"cm-{username}", "course-f3-t02", public_id),
        )
        db.commit()


def login(page: Page, username: str) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_test_id("login-username").fill(username)
    page.get_by_test_id("login-password").fill(PASSWORD)
    with page.expect_response(
        lambda response: response.url.endswith("/api/auth/login") and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_test_id("login-submit").click()
    page.wait_for_url(re.compile(r".*/onboarding(?:\?.*)?$"), timeout=30_000)
    page.get_by_test_id("onboarding-v2").wait_for(state="visible", timeout=30_000)


def answer_and_confirm(page: Page, answer: str) -> None:
    page.get_by_label("你的回答").fill(answer)
    with page.expect_response(
        lambda response: response.url.endswith("/api/v1/onboarding/turns") and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_role("button", name="发送回答").click()
    editor = page.get_by_test_id("onboarding-candidate-editor")
    editor.wait_for(state="visible", timeout=20_000)
    with page.expect_response(
        lambda response: "/api/v1/onboarding/turns/" in response.url
        and response.url.endswith("/confirm") and response.status == 200,
        timeout=30_000,
    ):
        editor.get_by_role("button", name=re.compile(r"确认本轮画像|再次保存到画像|更新为本次回答")).click()
    editor.wait_for(state="hidden", timeout=20_000)


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


def metrics(page: Page) -> dict:
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
            if (Math.min(x.right, y.right) - Math.max(x.left, y.left) > 3 &&
                Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top) > 3) {
              collisions.push([(a.innerText || a.title || a.tagName).trim().slice(0, 32),
                (b.innerText || b.title || b.tagName).trim().slice(0, 32)])
            }
          }
          const clipped = [...document.querySelectorAll('h1,h2,h3,strong,button,label,p,span')].filter((el) => {
            if (!visible(el)) return false
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            if (style.textOverflow === 'ellipsis') return false
            return rect.right > innerWidth + 1 || rect.left < -1 ||
              (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap')
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
            collisions, clipped, smallText, visualEffects,
          }
        }"""
    )


def capture(page: Page, report: dict, name: str) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(250)
    result = metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True)
    report["screenshots"].append(name)
    report["checks"][name] = result
    if result["documentWidth"] > result["viewport"][0]:
        raise AssertionError(f"horizontal overflow at {name}: {result}")
    if result["collisions"] or result["clipped"] or result["smallText"] or result["visualEffects"]:
        raise AssertionError(f"visual contract failed at {name}: {result}")


def create_user_page(browser, viewport: tuple[int, int], report: dict, scenario: str) -> tuple[Page, str, object]:
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    setup = context.new_page()
    username = f"f3_t02_{scenario}_{viewport[0]}_{int(time.time() * 1000)}"
    register(setup, username)
    attach_course(username)
    setup.close()
    page = context.new_page()
    attach_errors(page, report, f"{scenario}-{viewport[0]}x{viewport[1]}")
    login(page, username)
    return page, username, context


def finish_and_enter(page: Page) -> None:
    complete = page.get_by_test_id("onboarding-complete")
    complete.wait_for(state="visible", timeout=30_000)
    with page.expect_response(
        lambda response: response.url.endswith("/api/v1/onboarding/finalize") and response.status == 200,
        timeout=30_000,
    ):
        complete.get_by_role("button", name="确认初始画像").click()
    complete.get_by_role("button", name="进入入学诊断").wait_for(state="visible", timeout=20_000)
    complete.get_by_role("button", name="进入入学诊断").click()
    page.wait_for_url(re.compile(r".*/workspace/assessment/entry(?:\?.*)?$"), timeout=30_000)


def run_no_attachment(browser, report: dict) -> None:
    page, username, context = create_user_page(browser, (1440, 900), report, "no-attachment")
    try:
        capture(page, report, "1440x900-01-no-attachment-start.png")
        for answer in ANSWERS:
            answer_and_confirm(page, answer)
        capture(page, report, "1440x900-02-no-attachment-final-confirm.png")
        finish_and_enter(page)
        with sqlite3.connect(DB_PATH) as db:
            snapshot_count = db.execute(
                """SELECT COUNT(*) FROM profile_snapshots ps JOIN users u ON u.public_id=ps.owner_public_id
                   WHERE u.username=? AND ps.profile_version='onboarding.initial.v1'""",
                (username,),
            ).fetchone()[0]
        assert snapshot_count == 1
        report["checks"]["no-attachment-persistence"] = {"snapshotCount": snapshot_count, "url": page.url}
    finally:
        context.close()


def run_timetable(browser, report: dict) -> None:
    page, username, context = create_user_page(browser, (1366, 768), report, "timetable")
    try:
        page.get_by_role("button", name="课程表", exact=True).click()
        path = OUTPUT_DIR / "验收课程表.txt"
        path.write_text("周一 08:00 机器学习\n周三 14:00 数据结构\n周五 10:00 概率论", encoding="utf-8")
        with page.expect_response(
            lambda response: response.url.endswith("/api/v1/onboarding/personal-evidence") and response.status == 200,
            timeout=30_000,
        ):
            page.locator('input[type="file"]').set_input_files(path)
        editor = page.get_by_test_id("onboarding-evidence-editor")
        editor.wait_for(state="visible", timeout=20_000)
        assert editor.get_by_text("置信度", exact=False).count() > 0
        assert editor.get_by_text("验收课程表.txt", exact=False).count() > 0
        capture(page, report, "1366x768-01-timetable-candidates.png")
        with page.expect_response(
            lambda response: "/api/v1/onboarding/personal-evidence/" in response.url
            and response.url.endswith("/confirm") and response.status == 200,
            timeout=30_000,
        ):
            editor.get_by_role("button", name="确认资料字段").click()
        editor.wait_for(state="hidden", timeout=20_000)
        for answer in ANSWERS:
            answer_and_confirm(page, answer)
        capture(page, report, "1366x768-02-timetable-final-confirm.png")
        finish_and_enter(page)
        with sqlite3.connect(DB_PATH) as db:
            evidence = db.execute(
                """SELECT pe.status, pe.evidence_type, json_array_length(pe.confirmed_fields)
                   FROM onboarding_personal_evidence pe JOIN users u ON u.public_id=pe.owner_public_id
                   WHERE u.username=?""",
                (username,),
            ).fetchone()
        assert evidence[0] == "confirmed" and evidence[1] == "timetable" and evidence[2] >= 1
        report["checks"]["timetable-persistence"] = {"evidence": list(evidence), "url": page.url}
    finally:
        context.close()


def run_parse_failure(browser, report: dict) -> None:
    page, username, context = create_user_page(browser, (1440, 900), report, "parse-failure")
    try:
        path = OUTPUT_DIR / "损坏的个人成绩单.pdf"
        path.write_bytes(b"not-a-pdf")
        with page.expect_response(
            lambda response: response.url.endswith("/api/v1/onboarding/personal-evidence") and response.status == 200,
            timeout=30_000,
        ):
            page.locator('input[type="file"]').set_input_files(path)
        failure = page.get_by_test_id("onboarding-evidence-failure")
        failure.wait_for(state="visible", timeout=20_000)
        assert failure.get_by_text("对话和入学诊断不受影响", exact=False).is_visible()
        capture(page, report, "1440x900-03-parse-failure-nonblocking.png")
        for answer in ANSWERS:
            answer_and_confirm(page, answer)
        finish_and_enter(page)
        with sqlite3.connect(DB_PATH) as db:
            status = db.execute(
                """SELECT pe.status FROM onboarding_personal_evidence pe
                   JOIN users u ON u.public_id=pe.owner_public_id WHERE u.username=?""",
                (username,),
            ).fetchone()[0]
        assert status == "parse_failed"
        report["checks"]["parse-failure-persistence"] = {"evidenceStatus": status, "url": page.url}
    finally:
        context.close()


def main() -> int:
    clear_output()
    report = {
        "schema_version": "f3-t02.personal-evidence-browser-e2e.v1",
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "scenarios": ["no_attachment", "timetable_confirmed", "parse_failure_nonblocking"],
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
            "EDUMATRIX_AUTH_SECRET_KEY": "f3-t02-isolated-secret",
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
                run_no_attachment(browser, report)
                run_timetable(browser, report)
                run_parse_failure(browser, report)
                browser.close()
        if report["browser_errors"] or report["http_errors"]:
            raise AssertionError({
                "browser_errors": report["browser_errors"], "http_errors": report["http_errors"],
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
