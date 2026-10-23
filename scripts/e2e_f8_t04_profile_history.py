"""F8-T04 isolated dual-desktop profile and learning-history acceptance."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import Browser, Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import e2e_f8_t01_review_calendar as browser_base  # noqa: E402


OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f8_t04_profile_history"
BROWSER_DIR = OUTPUT_DIR / "browser"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "f8_t04_runtime.sqlite3"
REPORT_PATH = OUTPUT_DIR / "report.json"
USERNAME = "lzz"
PASSWORD = "404404aA"
EMPTY_USERNAME = "f8-profile-empty"
EMPTY_PASSWORD = "Empty-Profile-2026"
COURSE_ID = "demo-course-rag-trust-v1"
LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
PORT_START = int(os.getenv("EDUMATRIX_F8_T04_PORT", "9120"))


def configure_browser_base() -> None:
    browser_base.OUTPUT_DIR = OUTPUT_DIR
    browser_base.BROWSER_DIR = BROWSER_DIR
    browser_base.RUNTIME_DIR = RUNTIME_DIR
    browser_base.DB_PATH = DB_PATH
    browser_base.REPORT_PATH = REPORT_PATH
    browser_base.USERNAME = USERNAME
    browser_base.PASSWORD = PASSWORD
    browser_base.COURSE_ID = COURSE_ID
    browser_base.PORT_START = PORT_START


def runtime_env(port: int) -> dict[str, str]:
    env = browser_base.runtime_env(port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "f8-t04-isolated-secret"
    return env


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def seed_fixture(
    env: dict[str, str],
    *,
    base_fixture: dict[str, object] | None = None,
) -> dict[str, object]:
    fixture = dict(base_fixture) if base_fixture is not None else browser_base.seed_fixture(env)
    os.environ.update(env)

    from app.auth import get_password_hash
    from app.database import (
        DBLearningEvent,
        DBLearningEventConsumption,
        DBStudentProfile,
        DBUser,
        SessionLocal,
    )

    db = SessionLocal()
    try:
        learner = db.query(DBUser).filter_by(username=USERNAME).one()
        owner_event_ids = [
            row[0] for row in db.query(DBLearningEvent.id).filter_by(
                owner_public_id=learner.public_id,
            ).all()
        ]
        if owner_event_ids:
            db.query(DBLearningEventConsumption).filter(
                DBLearningEventConsumption.learning_event_id.in_(owner_event_ids),
            ).delete(synchronize_session=False)
            db.query(DBLearningEvent).filter(
                DBLearningEvent.id.in_(owner_event_ids),
            ).delete(synchronize_session=False)

        empty_user = DBUser(
            public_id="usr-f8-profile-empty",
            username=EMPTY_USERNAME,
            hashed_password=get_password_hash(EMPTY_PASSWORD),
            role="student",
            display_name="空记录学生",
            is_active=True,
        )
        db.add(empty_user)
        db.flush()
        db.add(DBStudentProfile(student_id=EMPTY_USERNAME, major="人工智能"))

        now = datetime.now(LOCAL_ZONE).replace(second=0, microsecond=0)

        def event(
            event_id: str,
            occurred_at: datetime,
            *,
            event_type: str,
            object_type: str,
            object_id: str,
            payload: dict[str, object] | None = None,
            accepted: bool = False,
        ) -> DBLearningEvent:
            row = DBLearningEvent(
                id=event_id,
                owner_public_id=learner.public_id,
                course_id=COURSE_ID,
                event_type=event_type,
                source="f8_t04_e2e",
                trace_id=f"trace-{event_id}",
                object_type=object_type,
                object_id=object_id,
                action="read",
                evidence_strength=0.84 if accepted else 0.0,
                evidence_status="accepted" if accepted else "none",
                evidence_reason="隔离验收中的已接受学习证据" if accepted else "真实学习记录",
                mastery_eligible=accepted,
                completion_effect="complete" if accepted else "none",
                payload=payload or {},
                occurred_at=_utc_naive(occurred_at),
            )
            db.add(row)
            db.flush()
            return row

        event(
            "f8-t04-duration-today-a",
            now - timedelta(minutes=20),
            event_type="resource_completed",
            object_type="artifact",
            object_id="demo-artifact-lzz-handout-01",
            payload={"actual_minutes": 12},
        )
        event(
            "f8-t04-duration-today-b",
            now - timedelta(minutes=15),
            event_type="code_tests_passed",
            object_type="code_run_attempt",
            object_id="f8-t04-code-run",
            payload={"duration_minutes": 8},
        )
        event(
            "f8-t04-duration-yesterday",
            now - timedelta(days=1, minutes=5),
            event_type="resource_completed",
            object_type="artifact",
            object_id="demo-artifact-lzz-handout-01",
            payload={"active_seconds": 300},
        )
        prior = event(
            "f8-t04-trend-prior",
            now - timedelta(days=3),
            event_type="assessment_correct",
            object_type="knowledge_point",
            object_id="demo-kp-06",
            accepted=True,
        )
        newest = event(
            "f8-t04-deep-link",
            now - timedelta(minutes=2),
            event_type="assessment_correct",
            object_type="knowledge_point",
            object_id="demo-kp-07",
            accepted=True,
        )
        for index, (row, mastery) in enumerate(((prior, 0.46), (newest, 0.68)), start=1):
            db.add(DBLearningEventConsumption(
                id=f"f8-t04-consumption-{index}",
                learning_event_id=row.id,
                consumer="learning_aggregation",
                processor_version="f8-t04-browser-v1",
                status="processed",
                result={"steps": {"dashboard": {"summary": {"mastery_average": mastery}}}},
                created_at=row.occurred_at + timedelta(minutes=1),
                processed_at=row.occurred_at + timedelta(minutes=2),
            ))
        for index in range(13):
            event(
                f"f8-t04-note-{index + 1:02d}",
                now - timedelta(hours=2 + index * 3),
                event_type="note_version_saved",
                object_type="note",
                object_id=f"f8-t04-note-object-{index + 1:02d}",
            )
        db.commit()
        fixture.update({
            "owner_public_id": learner.public_id,
            "empty_owner_public_id": empty_user.public_id,
            "course_id": COURSE_ID,
            "expected_today_minutes": 20,
            "expected_week_minutes": 25,
            "expected_note_events": 13,
            "deep_link_event_id": newest.id,
        })
        return fixture
    finally:
        db.close()


def database_state(owner_public_id: str, username: str) -> dict[str, object]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        mastery = db.execute(
            "SELECT concept_mastery FROM student_profiles WHERE student_id=?", (username,),
        ).fetchone()
        return {
            "learning_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=?", (owner_public_id,),
            ).fetchone()[0],
            "consumptions": db.execute(
                "SELECT COUNT(*) FROM learning_event_consumptions c "
                "JOIN learning_events e ON e.id=c.learning_event_id WHERE e.owner_public_id=?",
                (owner_public_id,),
            ).fetchone()[0],
            "profile_snapshots": db.execute(
                "SELECT COUNT(*) FROM profile_snapshots WHERE owner_public_id=?", (owner_public_id,),
            ).fetchone()[0],
            "review_plans": db.execute(
                "SELECT COUNT(*) FROM review_plans WHERE student_id=?", (username,),
            ).fetchone()[0],
            "assessment_attempts": db.execute(
                "SELECT COUNT(*) FROM assessment_attempts WHERE owner_public_id=?", (owner_public_id,),
            ).fetchone()[0],
            "generation_tasks": db.execute(
                "SELECT COUNT(*) FROM generation_tasks WHERE owner_public_id=?", (owner_public_id,),
            ).fetchone()[0],
            "student_profile_mastery": mastery[0] if mastery else None,
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def attach_diagnostics(page: Page, report: dict[str, object]) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(response.url)
        if response.status >= 400:
            report["http_errors"].append({"status": response.status, "url": response.url})

    page.on("response", on_response)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url,
        "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def login(page: Page, base_url: str, *, username: str, password: str, course_id: str = "") -> None:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": username, "password": password},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    state = json.dumps(response.json(), ensure_ascii=False)
    course_state = json.dumps(course_id, ensure_ascii=False)
    page.add_init_script(f"""
      const session = {state};
      const courseId = {course_state};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username || {json.dumps(username)});
      localStorage.setItem('edumatrix_display_name', session.display_name || session.username || {json.dumps(username)});
      localStorage.setItem('edumatrix_role', session.role || 'student');
      localStorage.setItem('edumatrix_student_id', session.student_id || session.username || {json.dumps(username)});
      localStorage.setItem('edumatrix_onboarded', 'true');
      if (courseId) {{
        localStorage.setItem('edumatrix_course_id', courseId);
        localStorage.setItem('edumatrix_course_title', 'RAG 应用开发与负责任评测实训');
      }} else {{
        localStorage.removeItem('edumatrix_course_id');
        localStorage.removeItem('edumatrix_course_title');
      }}
    """)


def wait_profile(page: Page) -> None:
    page.get_by_test_id("profile-dashboard").wait_for(state="visible")
    page.get_by_test_id("profile-heatmap").wait_for(state="visible", timeout=30_000)


def wait_history(page: Page) -> None:
    page.get_by_test_id("profile-history").wait_for(state="visible")
    page.get_by_test_id("history-timeline").wait_for(state="visible", timeout=30_000)


def visual_metrics(page: Page, root_test_id: str) -> dict[str, object]:
    return page.evaluate(
        """rootTestId => {
          const root = document.querySelector(`[data-testid="${rootTestId}"]`)
          if (!root) return { missingRoot: true }
          const visible = element => {
            const style = getComputedStyle(element), rect = element.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1
          }
          const textNodes = [...root.querySelectorAll('button,a,h1,h2,h3,p,span,strong,small,label,legend,summary,dt,dd,time')]
            .filter(element => visible(element) && (element.textContent || '').trim())
          const clipped = textNodes.filter(element => {
            const style = getComputedStyle(element)
            if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
            if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
            return element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 2
          }).map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 70) })).slice(0, 30)
          const smallText = textNodes.filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 13.9)
            .map(element => ({ text: element.textContent.trim().slice(0, 60), size: getComputedStyle(element).fontSize })).slice(0, 30)
          const controls = [...root.querySelectorAll('button,a[href],input,select,textarea,summary')].filter(visible)
          const collisions = []
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const left = controls[i], right = controls[j]
            if (left.contains(right) || right.contains(left)) continue
            const a = left.getBoundingClientRect(), b = right.getBoundingClientRect()
            const overlapWidth = Math.min(a.right, b.right) - Math.max(a.left, b.left)
            const overlapHeight = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
            if (overlapWidth > 3 && overlapHeight > 3) collisions.push([
              (left.textContent || left.getAttribute('aria-label') || '').trim().slice(0, 36),
              (right.textContent || right.getAttribute('aria-label') || '').trim().slice(0, 36),
            ])
          }
          const forbidden = new Set([
            'rgb(16, 185, 129)', 'rgb(34, 197, 94)', 'rgb(22, 163, 74)', 'rgb(21, 128, 61)',
            'rgb(14, 165, 233)', 'rgb(59, 130, 246)', 'rgb(139, 92, 246)', 'rgb(168, 85, 247)',
            'rgb(120, 53, 15)', 'rgb(146, 64, 14)', 'rgb(180, 83, 9)', 'rgb(161, 98, 7)',
          ])
          const forbiddenThemeHits = [...root.querySelectorAll('*')].filter(visible).flatMap(element => {
            const style = getComputedStyle(element)
            return [style.color, style.backgroundColor, style.borderColor]
              .filter(value => forbidden.has(value))
              .map(value => ({ value, text: element.textContent.trim().slice(0, 60) }))
          })
          const gradients = [...root.querySelectorAll('*')].filter(visible)
            .map(element => getComputedStyle(element).backgroundImage)
            .filter(value => value && value !== 'none' && value.includes('gradient'))
          const profileTrend = root.querySelector('[data-testid="profile-trend"]')?.getBoundingClientRect()
          const profileActivity = root.querySelector('[data-testid="profile-activity"]')?.getBoundingClientRect()
          const profileSummary = root.querySelector('[data-testid="profile-summary"]')?.getBoundingClientRect()
          const profileReport = root.querySelector('[data-testid="profile-report"]')?.getBoundingClientRect()
          const filters = root.querySelector('[data-testid="history-filters"]')?.getBoundingClientRect()
          const timeline = root.querySelector('[data-testid="history-timeline"]')?.getBoundingClientRect()
          const detail = root.querySelector('[data-testid="history-detail"]')?.getBoundingClientRect()
          return {
            missingRoot: false,
            viewport: [innerWidth, innerHeight],
            pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
            rootOverflow: root.scrollWidth > root.clientWidth + 1,
            clipped,
            smallText,
            collisions,
            forbiddenThemeHits,
            gradients,
            profileLayout: profileTrend && profileActivity && profileSummary && profileReport ? {
              trendBeforeActivity: profileTrend.left < profileActivity.left,
              trendActivityOverlap: Math.max(0, profileTrend.right - profileActivity.left),
              summaryBeforeReport: profileSummary.left < profileReport.left,
              summaryReportOverlap: Math.max(0, profileSummary.right - profileReport.left),
            } : null,
            historyLayout: filters && timeline && detail ? {
              filtersBeforeTimeline: filters.left < timeline.left,
              timelineBeforeDetail: timeline.left < detail.left,
              leftOverlap: Math.max(0, filters.right - timeline.left),
              rightOverlap: Math.max(0, timeline.right - detail.left),
            } : null,
          }
        }""",
        root_test_id,
    )


def assert_visual(page: Page, report: dict[str, object], key: str, root_test_id: str) -> None:
    metrics = visual_metrics(page, root_test_id)
    report["visual"][key] = metrics
    assert metrics["missingRoot"] is False, metrics
    assert metrics["pageOverflow"] is False, metrics
    assert metrics["rootOverflow"] is False, metrics
    assert metrics["clipped"] == [], metrics
    assert metrics["smallText"] == [], metrics
    assert metrics["collisions"] == [], metrics
    assert metrics["forbiddenThemeHits"] == [], metrics
    assert metrics["gradients"] == [], metrics
    if root_test_id == "profile-dashboard":
        assert metrics["profileLayout"] == {
            "trendBeforeActivity": True,
            "trendActivityOverlap": 0,
            "summaryBeforeReport": True,
            "summaryReportOverlap": 0,
        }, metrics
    else:
        assert metrics["historyLayout"] == {
            "filtersBeforeTimeline": True,
            "timelineBeforeDetail": True,
            "leftOverlap": 0,
            "rightOverlap": 0,
        }, metrics


def capture(page: Page, report: dict[str, object], name: str) -> None:
    browser_base.capture(page, report, name)


def profile_url(base_url: str, *, course_id: str = "", days: int = 30) -> str:
    query = {"days": days}
    if course_id:
        query["course_id"] = course_id
    return f"{base_url}/profile?{urlencode(query)}"


def run_primary(page: Page, base_url: str, fixture: dict[str, object], report: dict[str, object]) -> None:
    before = database_state(str(fixture["owner_public_id"]), USERNAME)
    page.goto(profile_url(base_url, course_id=COURSE_ID), wait_until="networkidle", timeout=60_000)
    wait_profile(page)
    profile = page.get_by_test_id("profile-dashboard")
    assert profile.get_by_text("20 分钟", exact=True).count() >= 1
    assert profile.get_by_text("25 分钟", exact=True).count() >= 2
    assert profile.get_by_text("2 天", exact=True).count() >= 1
    assert profile.locator(".heatmap-cell").count() == 30
    assert profile.locator(".heatmap-cell.level-1, .heatmap-cell.level-2, .heatmap-cell.level-3").count() >= 2
    assert profile.locator(".learning-trend-chart--empty").count() == 0
    profile.locator(".calculation-details summary").click()
    assert profile.get_by_text("页面停留和普通点击不计时", exact=False).count() == 1
    assert_visual(page, report, "profile_1440x900", "profile-dashboard")
    capture(page, report, "01-profile-1440x900.png")

    with page.expect_response(lambda response: "/api/v1/m5/personal-activity" in response.url and "days=7" in response.url):
        profile.get_by_role("button", name="7 天", exact=True).click()
    wait_profile(page)
    assert "days=7" in page.url

    profile.get_by_role("button", name="查看全部", exact=False).click()
    page.wait_for_url("**/profile/history**", timeout=30_000)
    wait_history(page)
    history = page.get_by_test_id("profile-history")
    assert "查看、筛选和展开历史不会改变掌握度" in history.inner_text()
    assert_visual(page, report, "history_1440x900", "profile-history")
    capture(page, report, "02-history-1440x900.png")

    with page.expect_response(lambda response: "/api/v1/m5/personal-activity" in response.url and "kind=note" in response.url):
        history.get_by_label("学习历史筛选").locator("select").nth(1).select_option("note")
    wait_history(page)
    history.get_by_text(f"共 {fixture['expected_note_events']} 条", exact=False).wait_for(state="visible")
    assert history.locator(".timeline-row").count() == 12
    with page.expect_response(lambda response: "/api/v1/m5/personal-activity" in response.url and "offset=12" in response.url):
        history.get_by_role("button", name="下一页", exact=False).click()
    wait_history(page)
    assert history.locator(".timeline-row").count() == int(fixture["expected_note_events"]) - 12
    capture(page, report, "03-history-pagination-1440x900.png")
    history.get_by_role("button", name="清除全部筛选", exact=True).click()
    wait_history(page)

    deep_link_row = history.locator(".timeline-row").filter(has_text="完成一次正确作答").first
    deep_link_row.click()
    history.get_by_test_id("history-detail").get_by_role("button", name="回到知识点", exact=False).click()
    try:
        page.wait_for_function(
            "() => ['/workspace/review', '/context-recovery'].includes(window.location.pathname)",
            timeout=30_000,
        )
    except Exception:
        report["checks"]["controlled_deep_link_diagnostic"] = {
            "url": page.url,
            "pathname": urlparse(page.url).path,
            "navigation": "timed_out",
        }
        capture(page, report, "04-controlled-deep-link-timeout-1440x900.png")
        raise

    parsed_deep_link = urlparse(page.url)
    query = parse_qs(parsed_deep_link.query)
    deep_link_diagnostic = {
        "url": page.url,
        "pathname": parsed_deep_link.path,
        "navigation": "arrived",
    }
    if parsed_deep_link.path == "/context-recovery":
        deep_link_diagnostic["recovery"] = {
            field: values[-1]
            for field in ("reason", "field", "object_id", "course_id", "return_to")
            if (values := query.get(field))
        }
    report["checks"]["controlled_deep_link_diagnostic"] = deep_link_diagnostic
    if parsed_deep_link.path != "/workspace/review":
        capture(page, report, "04-controlled-deep-link-recovery-1440x900.png")
    assert parsed_deep_link.path == "/workspace/review", deep_link_diagnostic
    try:
        page.get_by_test_id("review-schedule-board").wait_for(state="visible", timeout=60_000)
    except Exception:
        deep_link_diagnostic["component_mount"] = {
            "status": "timed_out",
            "page_title": page.title(),
            "visible_body_text": page.locator("body").inner_text(timeout=5_000)[:2_000],
        }
        capture(page, report, "04-controlled-deep-link-component-timeout-1440x900.png")
        raise
    deep_link_diagnostic["component_mount"] = {"status": "visible"}
    report["checks"]["controlled_deep_link"] = page.url

    after = database_state(str(fixture["owner_public_id"]), USERNAME)
    assert after == before, {"before": before, "after": after}
    assert after["integrity"] == "ok" and after["foreign_key_violations"] == 0
    report["database"]["learner_before"] = before
    report["database"]["learner_after"] = after
    report["checks"].update({
        "real_minutes_and_streak": True,
        "processed_mastery_trend": True,
        "thirty_day_heatmap": True,
        "history_filters_and_pagination": True,
        "ordinary_browsing_zero_writes": True,
    })


def run_secondary(page: Page, base_url: str, report: dict[str, object]) -> None:
    page.goto(profile_url(base_url, course_id=COURSE_ID), wait_until="networkidle", timeout=60_000)
    wait_profile(page)
    assert_visual(page, report, "profile_1366x768", "profile-dashboard")
    capture(page, report, "04-profile-1366x768.png")
    page.get_by_test_id("profile-dashboard").get_by_role("button", name="查看全部", exact=False).click()
    page.wait_for_url("**/profile/history**", timeout=30_000)
    wait_history(page)
    assert_visual(page, report, "history_1366x768", "profile-history")
    capture(page, report, "05-history-1366x768.png")


def run_empty(page: Page, base_url: str, fixture: dict[str, object], report: dict[str, object]) -> None:
    before = database_state(str(fixture["empty_owner_public_id"]), EMPTY_USERNAME)
    page.goto(profile_url(base_url), wait_until="networkidle", timeout=60_000)
    wait_profile(page)
    profile = page.get_by_test_id("profile-dashboard")
    assert profile.get_by_text("0 分钟", exact=True).count() >= 3
    assert profile.get_by_text("0 天", exact=True).count() >= 1
    assert profile.locator(".heatmap-cell").count() == 30
    assert profile.locator(".heatmap-cell.level-1, .heatmap-cell.level-2, .heatmap-cell.level-3").count() == 0
    assert profile.get_by_text("暂无可用于趋势计算的已处理学习证据。", exact=True).count() == 1
    assert profile.get_by_text("所选范围内还没有学习记录", exact=True).count() == 1
    assert_visual(page, report, "empty_profile_1440x900", "profile-dashboard")
    capture(page, report, "06-empty-profile-1440x900.png")

    profile.get_by_role("button", name="查看全部", exact=False).click()
    page.wait_for_url("**/profile/history**", timeout=30_000)
    wait_history(page)
    history = page.get_by_test_id("profile-history")
    assert history.get_by_text("所选范围内没有学习历史", exact=True).count() == 1
    assert_visual(page, report, "empty_history_1440x900", "profile-history")
    capture(page, report, "07-empty-history-1440x900.png")
    after = database_state(str(fixture["empty_owner_public_id"]), EMPTY_USERNAME)
    assert after == before, {"before": before, "after": after}
    report["database"]["empty_before"] = before
    report["database"]["empty_after"] = after
    report["checks"]["honest_empty_account"] = True


def run() -> dict[str, object]:
    configure_browser_base()
    browser_base.reset_output()
    port = browser_base.free_port()
    env = runtime_env(port)
    fixture = seed_fixture(env)
    base_url = f"http://127.0.0.1:{port}"
    report: dict[str, object] = {
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "viewports": [[1440, 900], [1366, 768]],
        "isolated_database": str(DB_PATH),
        "single_service": True,
        "single_chromium_instance": True,
        "external_model_called": False,
        "screenshots": [],
        "visual": {},
        "database": {},
        "checks": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
    }
    process = None
    try:
        process = browser_base.start_service(env, port)
        with sync_playwright() as playwright:
            browser: Browser = playwright.chromium.launch(headless=True)
            try:
                primary_context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                primary = primary_context.new_page()
                attach_diagnostics(primary, report)
                login(primary, base_url, username=USERNAME, password=PASSWORD, course_id=COURSE_ID)
                run_primary(primary, base_url, fixture, report)
                primary_context.close()

                secondary_context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
                secondary = secondary_context.new_page()
                attach_diagnostics(secondary, report)
                login(secondary, base_url, username=USERNAME, password=PASSWORD, course_id=COURSE_ID)
                run_secondary(secondary, base_url, report)
                secondary_context.close()

                empty_context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                empty = empty_context.new_page()
                attach_diagnostics(empty, report)
                login(empty, base_url, username=EMPTY_USERNAME, password=EMPTY_PASSWORD)
                run_empty(empty, base_url, fixture, report)
                empty_context.close()
            finally:
                browser.close()
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["external_requests"], report["external_requests"]
        report["status"] = "passed"
        return report
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        browser_base.stop_service(process, port)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result["status"],
        "screenshots": len(result["screenshots"]),
        "checks": result["checks"],
        "database": result["database"],
    }, ensure_ascii=False, indent=2))
