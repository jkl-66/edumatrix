"""Desktop acceptance for P1-B03 legacy-profile fusion evidence."""

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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.legacy_adapter import LegacyDataAdapter


PORT = int(os.getenv("EDUMATRIX_P1_B03_BROWSER_PORT", "8898"))
BASE_URL = f"http://127.0.0.1:{PORT}"
EVIDENCE_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "acceptance_feedback" / "P1-B03"
DB_PATH = EVIDENCE_DIR / "P1-B03_runtime.db"
PASSWORD = "P1-B03-browser-2026!"
COURSE_ID = "course-p1-b03-browser"
COURSE_TITLE = "机器学习导论"


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


def register(page: Page, username: str, display_name: str) -> dict[str, str]:
    response = page.request.post(
        f"{BASE_URL}/api/auth/register",
        data={"username": username, "password": PASSWORD, "display_name": display_name},
    )
    if not response.ok:
        raise AssertionError(f"register failed: {response.status} {response.text()}")
    payload = response.json()
    return {
        "token": payload["access_token"],
        "username": payload["username"],
        "public_id": payload["user_id"],
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
            (COURSE_ID, COURSE_TITLE),
        )
        db.execute(
            """INSERT OR IGNORE INTO course_memberships
               (id, course_id, user_public_id, role, status, created_at, updated_at)
               VALUES (?, ?, ?, 'student', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (f"cm-{username}", COURSE_ID, public_id),
        )
        db.commit()


def complete_initial_onboarding(page: Page, user: dict[str, str]) -> None:
    response = page.request.get(
        f"{BASE_URL}/api/v1/onboarding/session",
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    if not response.ok:
        raise AssertionError(f"onboarding session failed: {response.status} {response.text()}")
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            "SELECT id, course_context FROM onboarding_sessions WHERE student_id=?", (user["username"],)
        ).fetchone()
        if row is None:
            raise AssertionError("initial onboarding session was not created")
        context = json.loads(row[1] or "{}")
        context.update({"courseId": COURSE_ID, "courseTitle": COURSE_TITLE})
        db.execute(
            """UPDATE onboarding_sessions
                  SET status='confirmed', current_dimension='completed', checkpoint=5, version=6,
                      confirmed_fields=?, missing_fields='[]', course_context=?, confirmed_at=CURRENT_TIMESTAMP
                WHERE id=?""",
            (
                json.dumps({"target_course": COURSE_TITLE}, ensure_ascii=False),
                json.dumps(context, ensure_ascii=False), row[0],
            ),
        )
        db.commit()


def seed_legacy_profile(username: str, state: str) -> None:
    with sqlite3.connect(DB_PATH) as db:
        if state == "no_legacy":
            db.execute("DELETE FROM student_profiles WHERE student_id=?", (username,))
            db.commit()
            return

        values = {
            "target_course": COURSE_TITLE,
            "knowledge_base": "初级",
            "cognitive_style": "图示+代码",
            "motivation_type": "岗位转型",
            "frustration_index": 0.31,
            "focus_level": 0.74,
            "cognitive_load": 0.78,
            "weak_points": ["正则化"],
            "learning_goals": ["能够完成模型评估"],
            "interaction_preferences": ["先看例子"],
            "concept_mastery": {"正则化": 0.38},
            "misconception_patterns": {"正则化": {"cause": "概念边界"}},
            "dimension_states": {"knowledge_mastery": {"score": 0.42, "status": "部分掌握"}},
            "learning_state_causes": {"cognitive_load": {"percentage": 64}},
            "knowledge_traces": {"正则化": {"mastery": 0.38, "attempts": 3}},
            "bkt_states": {"正则化": {"p_mastery": 0.41, "attempts": 4}},
            "dkt_bias": [0.12, -0.04],
            "mental_state_history": [{"cognitive_load": 0.7}],
            "concept_layers": {"正则化": {"layer": "应用"}},
            "cognitive_map": {"正则化": ["线性回归"]},
            "fsm_mode": "support",
            "fsm_accuracy_history": {"正则化": [0.4, 0.5]},
            "rl_q_table": {"review": {"正则化": 0.8}},
            "history_logs": "旧系统分析：正则化需要更多辨析",
            "narrative_report": "已缓存的画像叙事，仅用于本次隔离浏览器验收。",
            "dashboard_report": "已缓存的画像摘要，仅用于本次隔离浏览器验收。",
            "profile_evidence": [{
                "source": "student_message",
                "text": "我总是分不清正则化的边界",
                "features": ["weak_point"],
                "weight": 0.8,
                "confidence": 0.8,
                "timestamp": "2026-08-20T09:00:00Z",
            }],
            "customized_fields": ["cognitive_load"] if state == "conflict" else [],
        }
        assignments = [
            "target_course=?", "knowledge_base=?", "cognitive_style=?", "motivation_type=?",
            "frustration_index=?", "focus_level=?", "cognitive_load=?", "weak_points=?",
            "learning_goals=?", "interaction_preferences=?", "concept_mastery=?",
            "misconception_patterns=?", "dimension_states=?", "learning_state_causes=?",
            "knowledge_traces=?", "bkt_states=?", "dkt_bias=?", "mental_state_history=?",
            "concept_layers=?", "cognitive_map=?", "fsm_mode=?", "fsm_accuracy_history=?",
            "rl_q_table=?", "history_logs=?", "narrative_report=?", "dashboard_report=?",
            "profile_evidence=?", "customized_fields=?",
        ]
        ordered = [
            values["target_course"], values["knowledge_base"], values["cognitive_style"],
            values["motivation_type"], values["frustration_index"], values["focus_level"],
            values["cognitive_load"],
            *[
                json.dumps(values[key], ensure_ascii=False)
                for key in (
                    "weak_points", "learning_goals", "interaction_preferences", "concept_mastery",
                    "misconception_patterns", "dimension_states", "learning_state_causes",
                    "knowledge_traces", "bkt_states", "dkt_bias", "mental_state_history",
                    "concept_layers", "cognitive_map",
                )
            ],
            values["fsm_mode"],
            json.dumps(values["fsm_accuracy_history"], ensure_ascii=False),
            json.dumps(values["rl_q_table"], ensure_ascii=False),
            values["history_logs"], values["narrative_report"], values["dashboard_report"],
            json.dumps(values["profile_evidence"], ensure_ascii=False),
            json.dumps(values["customized_fields"], ensure_ascii=False),
            username,
        ]
        db.execute(f"UPDATE student_profiles SET {', '.join(assignments)} WHERE student_id=?", ordered)
        if state == "conflict":
            public_id = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
            snapshot = {
                "kind": "profile_snapshot",
                "course_id": COURSE_ID,
                "cognitive_load": 0.22,
                "weak_points": ["概率图模型"],
                "initial_fields": [{"key": "cognitive_load", "value": 0.22}],
            }
            db.execute(
                """INSERT INTO profile_snapshots
                   (id, owner_public_id, legacy_student_id, profile_version, snapshot,
                    content_hash, trace_id, created_at)
                   VALUES (?, ?, ?, 'profile.confirmed.v1', ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    f"ps-conflict-{username}", public_id, username,
                    json.dumps(snapshot, ensure_ascii=False), f"content-{username}", f"trace-{username}",
                ),
            )
        db.commit()


def replay_profile(user: dict[str, str]) -> dict[str, str]:
    engine = create_engine(f"sqlite:///{DB_PATH.as_posix()}")
    session = sessionmaker(bind=engine)()
    try:
        row = LegacyDataAdapter(session).project_profile_snapshot(user["public_id"], course_id=COURSE_ID)
        session.commit()
        return {"id": row.id, "version": row.profile_version}
    finally:
        session.close()
        engine.dispose()


def read_only_state(username: str) -> dict:
    with sqlite3.connect(DB_PATH) as db:
        public_id = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
        profile = db.execute(
            """SELECT target_course, cognitive_style, cognitive_load, weak_points, concept_mastery,
                      dimension_states, knowledge_traces, bkt_states, customized_fields, last_updated
                 FROM student_profiles WHERE student_id=?""",
            (username,),
        ).fetchone()
        return {
            "profile": list(profile) if profile else None,
            "profile_snapshots": db.execute(
                "SELECT COUNT(*) FROM profile_snapshots WHERE owner_public_id=?", (public_id,)
            ).fetchone()[0],
            "profile_evidence": db.execute(
                "SELECT COUNT(*) FROM profile_evidence_items WHERE owner_public_id=?", (public_id,)
            ).fetchone()[0],
            "learning_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=?", (public_id,)
            ).fetchone()[0],
        }


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
            "scope": scope, "type": "requestfailed", "url": request.url,
            "message": str(request.failure),
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


def panel_metrics(page: Page, selector: str) -> dict:
    return page.locator(selector).evaluate(
        """(root) => {
          const visible = (el) => {
            const style = getComputedStyle(el), box = el.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0 &&
              box.width > 1 && box.height > 1
          }
          const controls = [...root.querySelectorAll('button,a[href],input,textarea,select,summary')].filter(visible)
          const collisions = []
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i], b = controls[j]
            if (a.contains(b) || b.contains(a)) continue
            const x = a.getBoundingClientRect(), y = b.getBoundingClientRect()
            if (Math.min(x.right, y.right) - Math.max(x.left, y.left) > 3 &&
                Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top) > 3) {
              collisions.push([(a.innerText || a.tagName).trim().slice(0, 40), (b.innerText || b.tagName).trim().slice(0, 40)])
            }
          }
          const smallText = [...root.querySelectorAll('*')].filter((el) =>
            visible(el) && el.children.length === 0 && (el.innerText || '').trim() &&
            Number.parseFloat(getComputedStyle(el).fontSize) < 13.5
          ).map((el) => ({text: el.innerText.trim().slice(0, 60), size: getComputedStyle(el).fontSize}))
          const clipped = [...root.querySelectorAll('h1,h2,h3,strong,button,label,p,span,small,summary')].filter((el) => {
            if (!visible(el)) return false
            const style = getComputedStyle(el)
            return style.whiteSpace === 'nowrap' && style.textOverflow !== 'ellipsis' && el.scrollWidth > el.clientWidth + 4
          }).map((el) => (el.innerText || '').trim().slice(0, 80))
          const box = root.getBoundingClientRect()
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            targetBounds: {left: box.left, right: box.right, top: box.top, bottom: box.bottom},
            targetScrollWidth: root.scrollWidth,
            targetClientWidth: root.clientWidth,
            collisions, clipped, smallText,
          }
        }"""
    )


def capture(page: Page, report: dict, name: str, selector: str) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    target = page.locator(selector)
    target.wait_for(state="visible", timeout=60_000)
    target.scroll_into_view_if_needed()
    page.wait_for_timeout(350)
    metrics = panel_metrics(page, selector)
    page.screenshot(path=str(EVIDENCE_DIR / name), full_page=False)
    report["screenshots"].append(name)
    report["metrics"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["targetBounds"]["left"] >= -1 and metrics["targetBounds"]["right"] <= metrics["viewport"][0] + 1, metrics
    assert metrics["targetScrollWidth"] <= metrics["targetClientWidth"] + 1, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
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
    page.wait_for_timeout(1_000)
    page.evaluate(
        """([courseId, courseTitle]) => {
          localStorage.setItem('edumatrix_onboarded', 'true')
          localStorage.setItem('edumatrix_course_id', courseId)
          localStorage.setItem('edumatrix_course_title', courseTitle)
        }""",
        [COURSE_ID, COURSE_TITLE],
    )


def open_page(browser, report: dict, user: dict[str, str], viewport: tuple[int, int], scope: str) -> tuple:
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    page = context.new_page()
    attach_errors(page, report, scope)
    login(page, user)
    return context, page


def open_dashboard(page: Page) -> None:
    page.goto(f"{BASE_URL}/profile?course_id={COURSE_ID}&days=30", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_test_id("profile-dashboard").wait_for(state="visible", timeout=60_000)
    page.get_by_test_id("profile-summary").wait_for(state="visible", timeout=60_000)


def open_learning_profile(page: Page) -> None:
    page.goto(f"{BASE_URL}/profile/learning?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_test_id("profile-summary").wait_for(state="visible", timeout=60_000)


def expand(page: Page, test_id: str) -> None:
    panel = page.get_by_test_id(test_id)
    panel.wait_for(state="visible", timeout=60_000)
    if not panel.evaluate("el => el.open"):
        panel.locator("summary").click()
    assert panel.evaluate("el => el.open") is True


def run_browser_journey(browser, report: dict, users: dict[str, dict[str, str]]) -> None:
    context, page = open_page(browser, report, users["no_legacy"], (1440, 900), "no-legacy-dashboard")
    open_dashboard(page)
    assert page.get_by_test_id("dashboard-legacy-migration").count() == 0
    capture(page, report, "1440x900-01-dashboard-no-legacy.png", '[data-testid="profile-summary"]')
    context.close()

    context, page = open_page(browser, report, users["partial"], (1440, 900), "partial-student-analysis")
    open_learning_profile(page)
    panel = page.get_by_test_id("legacy-profile-migration")
    assert "待回放" in panel.locator("summary").inner_text()
    expand(page, "legacy-profile-migration")
    assert panel.get_by_text("画像影响证据", exact=True).is_visible()
    capture(page, report, "1440x900-02-learning-partial-expanded.png", '[data-testid="legacy-profile-migration"]')
    page.get_by_title("刷新画像摘要").click()
    page.wait_for_timeout(750)
    context.close()

    context, page = open_page(browser, report, users["partial"], (1366, 768), "partial-dashboard")
    open_dashboard(page)
    expand(page, "dashboard-legacy-migration")
    capture(page, report, "1366x768-03-dashboard-partial-expanded.png", '[data-testid="profile-summary"]')
    page.reload(wait_until="domcontentloaded")
    page.get_by_test_id("dashboard-legacy-migration").wait_for(state="visible", timeout=60_000)
    context.close()

    context, page = open_page(browser, report, users["conflict"], (1366, 768), "conflict-student-analysis")
    open_learning_profile(page)
    expand(page, "legacy-profile-migration")
    conflict_panel = page.get_by_test_id("legacy-profile-migration")
    conflict_text = conflict_panel.inner_text()
    report.setdefault("state_text", {})["conflict"] = conflict_text
    assert "保留已确认值" in conflict_text
    assert "待确认差异" in conflict_text
    assert "已确认的当前画像优先" in conflict_text
    capture(page, report, "1366x768-04-learning-conflict-expanded.png", '[data-testid="legacy-profile-migration"]')
    context.close()

    context, page = open_page(browser, report, users["conflict"], (1440, 900), "conflict-dashboard")
    open_dashboard(page)
    expand(page, "dashboard-legacy-migration")
    assert "已确认的当前画像优先" in page.get_by_test_id("dashboard-legacy-migration").inner_text()
    capture(page, report, "1440x900-05-dashboard-conflict-expanded.png", '[data-testid="profile-summary"]')
    context.close()

    context, page = open_page(browser, report, users["replayed"], (1440, 900), "replayed-student-analysis")
    open_learning_profile(page)
    replay_panel = page.get_by_test_id("legacy-profile-migration")
    assert "profile.legacy-migration.v1" in replay_panel.locator("summary").inner_text()
    expand(page, "legacy-profile-migration")
    capture(page, report, "1440x900-06-learning-replayed-expanded.png", '[data-testid="legacy-profile-migration"]')
    context.close()

    context, page = open_page(browser, report, users["replayed"], (1366, 768), "replayed-dashboard")
    open_dashboard(page)
    replay_dashboard = page.get_by_test_id("dashboard-legacy-migration")
    assert "profile.legacy-migration.v1" in replay_dashboard.locator("summary").inner_text()
    expand(page, "dashboard-legacy-migration")
    capture(page, report, "1366x768-07-dashboard-replayed-expanded.png", '[data-testid="profile-summary"]')
    context.close()


def main() -> int:
    clear_output()
    report = {
        "schema_version": "acceptance-feedback.p1-b03.legacy-profile-browser-e2e.v1",
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "states": ["no_legacy", "partial", "conflict", "replayed"],
        "database": str(DB_PATH),
        "screenshots": [], "metrics": {}, "browser_errors": [], "http_errors": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    process = None
    try:
        env = os.environ.copy()
        env.update({
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "p1-b03-browser-isolated-secret",
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
                setup_page = browser.new_page()
                suffix = str(int(time.time() * 1000))
                users = {
                    state: register(setup_page, f"p1_b03_{state}_{suffix}", f"旧画像{state}验收学生")
                    for state in ("no_legacy", "partial", "conflict", "replayed")
                }
                setup_page.close()
                setup_page = browser.new_page()
                for state, user in users.items():
                    attach_course(user["username"])
                    complete_initial_onboarding(setup_page, user)
                    seed_legacy_profile(user["username"], state)
                setup_page.close()
                report["replay"] = replay_profile(users["replayed"])
                tracked = ("partial", "conflict", "replayed")
                report["read_only_before"] = {state: read_only_state(users[state]["username"]) for state in tracked}
                run_browser_journey(browser, report, users)
                report["read_only_after"] = {state: read_only_state(users[state]["username"]) for state in tracked}
                report["read_only_unchanged"] = report["read_only_before"] == report["read_only_after"]
                assert report["read_only_unchanged"], {
                    "before": report["read_only_before"], "after": report["read_only_after"],
                }
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
        (EVIDENCE_DIR / "browser-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
