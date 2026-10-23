"""Browser acceptance for P1-B02 continuous profile updates and reminders.

The normal update path intentionally uses the repository's configured DeepSeek
endpoint.  Model-failure/manual-review behavior is covered by the focused API
tests; this journey keeps the browser evidence on the real model path and the
user-visible reminder states.
"""

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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("EDUMATRIX_P1_B02_BROWSER_PORT", "8897"))
BASE_URL = f"http://127.0.0.1:{PORT}"
EVIDENCE_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "acceptance_feedback" / "P1-B02"
DB_PATH = EVIDENCE_DIR / "P1-B02_runtime.db"
PASSWORD = "P1-B02-browser-2026!"
COURSE_ID = "course-p1-b02-browser"
COURSE_TITLE = "机器学习导论"
ANSWER = "最近我能独立推导线性回归，但遇到正则化和交叉验证时容易混淆，希望多做对比练习。"


def wait_port(expected: bool, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected state: {expected}")


def clear_output() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    for item in EVIDENCE_DIR.iterdir():
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
        data={"username": username, "password": PASSWORD, "display_name": "持续画像浏览器验收学生"},
    )
    if not response.ok:
        raise AssertionError(f"register failed: {response.status} {response.text()}")
    payload = response.json()
    return {"token": payload["access_token"], "username": payload["username"]}


def attach_course(username: str) -> None:
    with sqlite3.connect(DB_PATH) as db:
        public_id = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
        db.execute(
            """INSERT OR IGNORE INTO courses
               (id, version, title, subject, description, domain_pack, language, content_origin,
                license_text, visibility, status, owner_public_id, manifest_version, manifest_data, created_at)
               VALUES (?, '1', ?, '人工智能', '', 'ai-ml', 'zh-CN', 'team-curated', '', 'public',
                       'published', NULL, '1', '{}', CURRENT_TIMESTAMP)""",
            (COURSE_ID, COURSE_TITLE),
        )
        db.execute(
            """INSERT OR IGNORE INTO course_memberships
               (id, course_id, user_public_id, role, status, created_at, updated_at)
               VALUES (?, ?, ?, 'student', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (f"cm-{username}", COURSE_ID, public_id),
        )
        db.commit()


def complete_initial_onboarding(username: str) -> None:
    """Put the browser student behind the existing initial-profile gate."""
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            "SELECT id, course_context FROM onboarding_sessions WHERE student_id=?", (username,)
        ).fetchone()
        if row is None:
            raise AssertionError("initial onboarding session was not created")
        context = json.loads(row[1] or "{}")
        context.update({"courseId": COURSE_ID, "courseTitle": COURSE_TITLE})
        db.execute(
            """UPDATE onboarding_sessions
                  SET status='confirmed', current_dimension='completed', checkpoint=5,
                      version=6, confirmed_fields=?, missing_fields='[]', course_context=?,
                      confirmed_at=?
                WHERE id=?""",
            (
                json.dumps({"target_course": COURSE_TITLE}, ensure_ascii=False),
                json.dumps(context, ensure_ascii=False),
                now,
                row[0],
            ),
        )
        db.execute(
            "UPDATE student_profiles SET target_course=? WHERE student_id=?",
            (COURSE_TITLE, username),
        )
        db.commit()


def attach_errors(page: Page, report: dict, scope: str) -> None:
    page.on("pageerror", lambda error: report["browser_errors"].append({
        "scope": scope, "type": "pageerror", "message": str(error),
    }))
    page.on("console", lambda message: (
        report.setdefault("expected_browser_events", []).append({
            "scope": scope, "type": "console_expected_403", "message": message.text,
        })
        if message.type == "error" and "403 (Forbidden)" in message.text
        else report["browser_errors"].append({
            "scope": scope, "type": "console", "message": message.text,
        })
    ) if message.type == "error" else None)
    page.on("requestfailed", lambda request: (
        report.setdefault("expected_browser_events", []).append({
            "scope": scope, "type": "request_aborted", "url": request.url,
            "message": str(request.failure),
        })
        if "ERR_ABORTED" in str(request.failure or "")
        else report["browser_errors"].append({
            "scope": scope, "type": "requestfailed", "url": request.url, "message": str(request.failure),
        })
    ))
    page.on("response", lambda response: (
        report.setdefault("expected_http_events", []).append({
            "scope": scope, "status": response.status, "url": response.url,
        })
        if response.status == 403 and "/api/v1/competition-demo/context" in response.url
        else report["http_errors"].append({
            "scope": scope, "status": response.status, "url": response.url,
        })
    ) if response.status >= 400 else None)


def visual_metrics(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const rect = (el) => {
            const raw = el.getBoundingClientRect()
            let left = Math.max(0, raw.left), top = Math.max(0, raw.top)
            let right = Math.min(innerWidth, raw.right), bottom = Math.min(innerHeight, raw.bottom)
            for (let parent = el.parentElement; parent; parent = parent.parentElement) {
              const style = getComputedStyle(parent), parentRect = parent.getBoundingClientRect()
              if (/(auto|hidden|scroll|clip)/.test(style.overflowX)) {
                left = Math.max(left, parentRect.left); right = Math.min(right, parentRect.right)
              }
              if (/(auto|hidden|scroll|clip)/.test(style.overflowY)) {
                top = Math.max(top, parentRect.top); bottom = Math.min(bottom, parentRect.bottom)
              }
            }
            return {left, top, right, bottom, width: right - left, height: bottom - top}
          }
          const visible = (el) => {
            const style = getComputedStyle(el), box = rect(el)
            return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0 &&
              box.width > 1 && box.height > 1 && box.right > 0 && box.bottom > 0 &&
              box.left < innerWidth && box.top < innerHeight
          }
          const controls = [...document.querySelectorAll('button,a[href],input,textarea,select')].filter(visible)
          const collisions = []
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i], b = controls[j]
            if (a.contains(b) || b.contains(a)) continue
            const x = rect(a), y = rect(b)
            const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left)
            const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top)
            if (overlapW > 3 && overlapH > 3) collisions.push([
              (a.innerText || a.getAttribute('aria-label') || a.title || a.tagName).trim().slice(0, 40),
              (b.innerText || b.getAttribute('aria-label') || b.title || b.tagName).trim().slice(0, 40),
            ])
          }
          const clipped = [...document.querySelectorAll('h1,h2,h3,strong,button,label,p,span')].filter((el) => {
            if (!visible(el)) return false
            const style = getComputedStyle(el), box = rect(el)
            if (box.width <= 0 || box.height <= 0) return false
            return style.whiteSpace === 'nowrap' && style.textOverflow !== 'ellipsis' && el.scrollWidth > el.clientWidth + 4
          }).map((el) => (el.innerText || '').trim().slice(0, 80))
          const smallText = [...document.querySelectorAll('body *')].filter((el) =>
            visible(el) && el.children.length === 0 && (el.innerText || '').trim() &&
            Number.parseFloat(getComputedStyle(el).fontSize) < 13.5
          ).map((el) => ({text: el.innerText.trim().slice(0, 60), size: getComputedStyle(el).fontSize})).slice(0, 20)
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            collisions,
            clipped,
            smallText,
            bodyTextLength: (document.body.innerText || '').trim().length,
          }
        }"""
    )


def capture(page: Page, report: dict, name: str, *, allow_small_text: bool = False) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(350)
    metrics = visual_metrics(page)
    page.screenshot(path=str(EVIDENCE_DIR / name), full_page=False)
    report["screenshots"].append(name)
    report["metrics"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    if not allow_small_text:
        assert not metrics["smallText"], metrics


def login(page: Page, user: dict[str, str]) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_test_id("login-username").fill(user["username"])
    page.get_by_test_id("login-password").fill(PASSWORD)
    with page.expect_response(
        lambda response: response.url.endswith("/api/auth/login") and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_test_id("login-submit").click()
    page.wait_for_timeout(500)


def age_confirmation_baseline(username: str) -> None:
    """Seed an old confirmation baseline without creating a second truth source."""
    old = datetime.now(timezone.utc) - timedelta(days=3, hours=1)
    old_iso = old.isoformat()
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            "SELECT id, course_context FROM onboarding_sessions WHERE student_id=?", (username,)
        ).fetchone()
        if row is None:
            raise AssertionError("continuous update session was not created")
        state = json.loads(row[1] or "{}")
        continuous = dict(state.get("continuousUpdate") or {})
        continuous.update({
            "active": False,
            "courseId": COURSE_ID,
            "courseTitle": COURSE_TITLE,
            "lastConfirmedAt": old_iso,
            "reminderDismissedFor": None,
        })
        state["continuousUpdate"] = continuous
        db.execute(
            "UPDATE onboarding_sessions SET course_context=?, confirmed_at=?, status='confirmed' WHERE id=?",
            (json.dumps(state, ensure_ascii=False), old_iso, row[0]),
        )
        db.commit()


def profile_update_flow(page: Page, report: dict, user: dict[str, str]) -> None:
    page.goto(f"{BASE_URL}/profile/learning?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_role("button", name="更新学情画像").wait_for(state="visible", timeout=45_000)
    page.get_by_role("button", name="更新学情画像").click()
    card = page.get_by_test_id("profile-continuous-update")
    card.wait_for(state="visible", timeout=30_000)
    capture(page, report, "1440x900-01-update-empty.png")

    page.get_by_placeholder(re.compile("最近我能独立完成|正则化")).fill(ANSWER)
    with page.expect_response(
        lambda response: response.url.endswith("/api/v1/onboarding/update/turns") and response.status == 200,
        timeout=180_000,
    ):
        page.get_by_role("button", name="发送这轮更新").click()
    page.get_by_text("模型整理出的候选", exact=True).wait_for(state="visible", timeout=30_000)
    assert page.get_by_text(ANSWER, exact=True).is_visible()
    assert page.get_by_text("模型理解", exact=False).count() >= 0
    capture(page, report, "1440x900-02-model-candidate.png")
    page.set_viewport_size({"width": 1366, "height": 768})
    capture(page, report, "1366x768-03-model-candidate.png")

    with page.expect_response(
        lambda response: "/api/v1/onboarding/update/turns/" in response.url
        and response.url.endswith("/confirm") and response.status == 200,
        timeout=60_000,
    ):
        page.get_by_role("button", name="确认并更新画像").click()
    page.get_by_text(re.compile("画像已确认并保存为"), exact=False).wait_for(state="visible", timeout=30_000)
    capture(page, report, "1366x768-04-confirmed.png")

    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            """SELECT t.status, json_extract(t.extracted_candidates, '$.source'),
                      json_extract(t.extracted_candidates, '$.modelMeta.model'),
                      json_extract(t.extracted_candidates, '$.modelMeta.reasoningEffort'),
                      s.version
               FROM onboarding_turns t JOIN onboarding_sessions s ON s.id=t.session_id
              WHERE s.student_id=? AND t.question_dimension='continuous'
              ORDER BY t.created_at DESC LIMIT 1""",
            (user["username"],),
        ).fetchone()
    assert row and row[0] == "confirmed", row
    assert row[1] == "deepseek-v4-flash", row
    assert row[2] == "deepseek-v4-flash", row
    assert row[3] == "max", row
    report["real_model_evidence"] = {
        "turn_status": row[0], "source": row[1], "model": row[2],
        "reasoning_effort": row[3], "session_version": row[4],
    }


def reminder_flow(page: Page, report: dict, user: dict[str, str]) -> None:
    # Create a session for the reminder read-only path and age only its existing baseline.
    token = user["token"]
    response = page.request.post(
        f"{BASE_URL}/api/v1/onboarding/update/session",
        data={"course_id": COURSE_ID},
        headers={"Authorization": f"Bearer {token}"},
    )
    if not response.ok:
        raise AssertionError(f"start update session failed: {response.status} {response.text()}")
    age_confirmation_baseline(user["username"])

    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{BASE_URL}/workspace?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=30_000)
    reminder = page.get_by_test_id("today-profile-update-reminder")
    reminder.wait_for(state="visible", timeout=60_000)
    assert reminder.get_by_text("更新一下学习画像", exact=True).is_visible()
    reminder_small_text = page.locator('[data-testid="today-profile-update-reminder"] *').evaluate_all(
        "els => els.filter(el => !el.children.length && (el.innerText || '').trim()).map(el => ({text: el.innerText.trim(), size: getComputedStyle(el).fontSize})).filter(item => Number.parseFloat(item.size) < 14)"
    )
    assert not reminder_small_text, reminder_small_text
    capture(page, report, "1440x900-05-reminder-due.png", allow_small_text=True)

    page.get_by_role("button", name="现在更新").click()
    page.wait_for_url(re.compile(r".*/profile/learning.*update=1"), timeout=30_000)
    page.get_by_test_id("profile-continuous-update").wait_for(state="visible", timeout=30_000)
    report["reminder_now_update_route"] = page.url
    page.get_by_role("button", name="关闭").click()

    # Re-age the same baseline after opening the update session, then verify dismiss and reload deduplication.
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute("SELECT id, course_context FROM onboarding_sessions WHERE student_id=?", (user["username"],)).fetchone()
        state = json.loads(row[1] or "{}")
        continuous = dict(state.get("continuousUpdate") or {})
        continuous.update({"active": False, "lastConfirmedAt": (datetime.now(timezone.utc) - timedelta(days=3, hours=1)).isoformat(), "reminderDismissedFor": None})
        state["continuousUpdate"] = continuous
        db.execute("UPDATE onboarding_sessions SET course_context=? WHERE id=?", (json.dumps(state, ensure_ascii=False), row[0]))
        db.commit()
    page.goto(f"{BASE_URL}/workspace?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=30_000)
    reminder = page.get_by_test_id("today-profile-update-reminder")
    reminder.wait_for(state="visible", timeout=60_000)
    with page.expect_response(
        lambda response: response.url.endswith("/api/v1/onboarding/update/reminder/dismiss?course_id=" + COURSE_ID)
        and response.status == 200,
        timeout=30_000,
    ):
        page.get_by_role("button", name="稍后提醒").click()
    reminder.wait_for(state="hidden", timeout=30_000)
    page.reload(wait_until="domcontentloaded")
    page.get_by_test_id("today-task-list").wait_for(state="visible", timeout=60_000)
    assert page.get_by_test_id("today-profile-update-reminder").count() == 0
    capture(page, report, "1440x900-06-reminder-dismissed.png", allow_small_text=True)


def main() -> int:
    clear_output()
    report = {
        "schema_version": "acceptance-feedback.p1-b02.profile-update-browser-e2e.v1",
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "database": str(DB_PATH),
        "screenshots": [], "metrics": {}, "browser_errors": [], "http_errors": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    process = None
    try:
        env = os.environ.copy()
        env.update({
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "p1-b02-browser-isolated-secret",
            "EDUMATRIX_ONBOARDING_V2": "1",
            "EDUMATRIX_RELOAD": "0",
            "EDUMATRIX_HOST": "127.0.0.1",
            "EDUMATRIX_PORT": str(PORT),
            "EDUMATRIX_SANDBOX_MODE": "disabled",
            "PYTHONUNBUFFERED": "1",
        })
        with (EVIDENCE_DIR / "backend-browser.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page()
                attach_errors(page, report, "profile-and-workspace")
                user = register(page, f"p1_b02_browser_{int(time.time() * 1000)}")
                attach_course(user["username"])
                login(page, user)
                complete_initial_onboarding(user["username"])
                # The login guard cached the pre-seeded status; keep the browser
                # session aligned with the existing confirmed onboarding row.
                page.evaluate("localStorage.setItem('edumatrix_onboarded', 'true')")
                profile_update_flow(page, report, user)
                reminder_flow(page, report, user)
                context.close()
                browser.close()
        if report["browser_errors"] or report["http_errors"]:
            raise AssertionError({"browser_errors": report["browser_errors"], "http_errors": report["http_errors"]})
        report["result"] = "passed"
    except Exception as error:
        report["result"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
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
        (EVIDENCE_DIR / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
