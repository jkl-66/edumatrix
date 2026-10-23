"""F8-T05 isolated cross-page feedback and recovery desktop acceptance."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

from playwright.sync_api import Browser, Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import e2e_f8_t01_review_calendar as browser_base  # noqa: E402


OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f8_t05_learning_feedback"
BROWSER_DIR = OUTPUT_DIR / "browser"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "f8_t05_runtime.sqlite3"
REPORT_PATH = OUTPUT_DIR / "report.json"
USERNAME = "lzz"
PASSWORD = "404404aA"
COURSE_ID = "demo-course-rag-trust-v1"
POINT_ID = "demo-kp-07"
PORT_START = int(os.getenv("EDUMATRIX_F8_T05_PORT", "9140"))
ROUTES = (
    ("dashboard", "/"),
    ("profile", "/profile/learning"),
    ("path", "/workspace/path"),
    ("wrong_questions", "/workspace/review/wrong-questions"),
    ("review", "/workspace/review"),
    ("history", "/profile/history"),
)


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
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "f8-t05-isolated-secret"
    return env


def _event(*, event_id: str, owner_public_id: str, event_type: str, occurred_at: datetime):
    from app.database import DBLearningEvent

    payload = (
        {
            "knowledge_point_scores": [{"knowledge_point_id": POINT_ID, "score": 0.78}],
            "item_results": [],
        }
        if event_type == "formal_exam_submitted"
        else {"passed_tests": 4, "total_tests": 4}
    )
    return DBLearningEvent(
        id=event_id,
        owner_public_id=owner_public_id,
        course_id=COURSE_ID,
        event_type=event_type,
        schema_version="m5.learning-event.v2",
        idempotency_key=f"f8-t05-browser-{event_id}",
        source="f8_t05_e2e",
        trace_id=f"trace-{event_id}",
        object_type="knowledge_point",
        object_id=POINT_ID,
        action="trusted_completion",
        context_ref={"courseId": COURSE_ID, "knowledgePointId": POINT_ID},
        evidence_strength=0.82,
        evidence_status="accepted",
        evidence_reason="F8-T05 isolated accepted evidence",
        mastery_eligible=True,
        completion_effect="complete",
        payload_version="1",
        payload=payload,
        occurred_at=occurred_at,
    )


def seed_fixture(
    env: dict[str, str],
    *,
    base_fixture: dict[str, object] | None = None,
) -> dict[str, object]:
    fixture = dict(base_fixture) if base_fixture is not None else browser_base.seed_fixture(env)
    os.environ.update(env)

    from app.database import DBLearningEvent, DBUser, SessionLocal
    from app.learning_aggregation import aggregate_learning_event

    db = SessionLocal()
    try:
        learner = db.query(DBUser).filter_by(username=USERNAME).one()
        occurred_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=1)
        event = _event(
            event_id="f8-t05-completed-formal-exam",
            owner_public_id=learner.public_id,
            event_type="formal_exam_submitted",
            occurred_at=occurred_at,
        )
        db.add(event)
        db.commit()
        consumption = aggregate_learning_event(db, event=db.get(DBLearningEvent, event.id))
        fixture.update({
            "owner_public_id": learner.public_id,
            "completed_event_id": event.id,
            "completed_token": consumption.result["consistencyToken"],
        })
        return fixture
    finally:
        db.close()


def create_partial_event(owner_public_id: str) -> dict[str, object]:
    from app.database import DBLearningEvent, DBLearningEventConsumption, SessionLocal
    from app.learning_aggregation import _STEP_HANDLERS, aggregate_learning_event, learning_feedback_payload

    db = SessionLocal()
    original = _STEP_HANDLERS["wrong_review"]

    def fail_wrong_review(_session, _event):
        raise RuntimeError("F8-T05 injected wrong/review projection failure")

    try:
        event = _event(
            event_id="f8-t05-partial-code",
            owner_public_id=owner_public_id,
            event_type="code_tests_passed",
            occurred_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=2),
        )
        db.add(event)
        db.commit()
        _STEP_HANDLERS["wrong_review"] = fail_wrong_review
        try:
            aggregate_learning_event(db, event=db.get(DBLearningEvent, event.id))
        except RuntimeError as exc:
            if "injected wrong/review" not in str(exc):
                raise
        consumption = db.query(DBLearningEventConsumption).filter_by(
            learning_event_id=event.id,
            consumer="learning_aggregation",
        ).one()
        feedback = learning_feedback_payload(db.get(DBLearningEvent, event.id), consumption)
        return {
            "event_id": event.id,
            "attempt": consumption.attempt,
            "statuses": {item["id"]: item["status"] for item in feedback["views"]},
        }
    finally:
        _STEP_HANDLERS["wrong_review"] = original
        db.close()


def database_state(owner_public_id: str) -> dict[str, object]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        profile = db.execute(
            "SELECT concept_mastery FROM student_profiles WHERE student_id=?", (USERNAME,),
        ).fetchone()
        return {
            "learning_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=?", (owner_public_id,),
            ).fetchone()[0],
            "consumptions": db.execute(
                "SELECT COUNT(*) FROM learning_event_consumptions c JOIN learning_events e "
                "ON e.id=c.learning_event_id WHERE e.owner_public_id=?", (owner_public_id,),
            ).fetchone()[0],
            "profile_snapshots": db.execute(
                "SELECT COUNT(*) FROM profile_snapshots WHERE owner_public_id=?", (owner_public_id,),
            ).fetchone()[0],
            "wrong_questions": db.execute(
                "SELECT COUNT(*) FROM wrong_questions WHERE student_id=?", (USERNAME,),
            ).fetchone()[0],
            "review_plans": db.execute(
                "SELECT COUNT(*) FROM review_plans WHERE student_id=?", (USERNAME,),
            ).fetchone()[0],
            "path_nodes": db.execute("SELECT COUNT(*) FROM path_nodes").fetchone()[0],
            "completed_path_nodes": db.execute(
                "SELECT COUNT(*) FROM path_nodes WHERE status='completed'",
            ).fetchone()[0],
            "profile_mastery": profile[0] if profile else None,
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def aggregation_state(event_id: str) -> dict[str, object]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        row = db.execute(
            "SELECT status, attempt, result FROM learning_event_consumptions "
            "WHERE learning_event_id=? AND consumer='learning_aggregation'",
            (event_id,),
        ).fetchone()
        result = json.loads(row[2] or "{}")
        return {
            "status": row[0],
            "attempt": row[1],
            "token": result.get("consistencyToken"),
            "completed_steps": result.get("completed_steps") or [],
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


def login(page: Page, base_url: str) -> None:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": USERNAME, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    session = json.dumps(response.json(), ensure_ascii=False)
    page.add_init_script(f"""
      const session = {session};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username || {json.dumps(USERNAME)});
      localStorage.setItem('edumatrix_display_name', session.display_name || session.username || {json.dumps(USERNAME)});
      localStorage.setItem('edumatrix_role', session.role || 'student');
      localStorage.setItem('edumatrix_student_id', session.student_id || session.username || {json.dumps(USERNAME)});
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', {json.dumps(COURSE_ID)});
      localStorage.setItem('edumatrix_course_title', 'RAG 应用开发与负责任评测实训');
    """)


def route_url(base_url: str, route: str) -> str:
    separator = "&" if "?" in route else "?"
    return f"{base_url}{route}{separator}{urlencode({'course_id': COURSE_ID})}"


def visual_metrics(page: Page) -> dict[str, object]:
    return page.evaluate(
        """() => {
          const root = document.body
          const visible = element => {
            const style = getComputedStyle(element), rect = element.getBoundingClientRect()
            const closedDetails = element.closest('details:not([open])')
            const closedSummary = closedDetails?.querySelector(':scope > summary')
            if (closedDetails && !closedSummary?.contains(element)) return false
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1
          }
          const textNodes = [...root.querySelectorAll('button,a,h1,h2,h3,h4,p,span,strong,small,label,legend,summary,dt,dd,time,li')]
            .filter(element => visible(element) && (element.textContent || '').trim())
          const clipped = textNodes.filter(element => {
            const style = getComputedStyle(element)
            if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
            if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
            const clippedX = style.overflowX !== 'visible' && element.scrollWidth > element.clientWidth + 2
            const clippedY = style.overflowY !== 'visible' && element.scrollHeight > element.clientHeight + 2
            return clippedX || clippedY
          }).map(element => {
            const style = getComputedStyle(element), rect = element.getBoundingClientRect()
            return {
              tag: element.tagName,
              text: element.textContent.trim().slice(0, 70),
              scroll: [element.scrollWidth, element.scrollHeight],
              client: [element.clientWidth, element.clientHeight],
              rect: [rect.width, rect.height],
              lineHeight: style.lineHeight,
              overflow: [style.overflowX, style.overflowY],
            }
          }).slice(0, 30)
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
          }).slice(0, 30)
          const gradients = [...root.querySelectorAll('*')].filter(visible)
            .map(element => getComputedStyle(element).backgroundImage)
            .filter(value => value && value !== 'none' && value.includes('gradient'))
          return {
            viewport: [innerWidth, innerHeight],
            pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
            clipped,
            smallText,
            collisions: collisions.slice(0, 30),
            forbiddenThemeHits,
            gradients: gradients.slice(0, 30),
          }
        }"""
    )


def assert_visual(page: Page, report: dict[str, object], key: str) -> None:
    metrics = visual_metrics(page)
    report["visual"][key] = metrics
    assert metrics["pageOverflow"] is False, metrics
    assert metrics["clipped"] == [], metrics
    assert metrics["smallText"] == [], metrics
    assert metrics["collisions"] == [], metrics
    assert metrics["forbiddenThemeHits"] == [], metrics
    assert metrics["gradients"] == [], metrics


def capture(page: Page, report: dict[str, object], name: str) -> None:
    page.screenshot(path=BROWSER_DIR / name, full_page=True, animations="disabled")
    report["screenshots"].append(str((BROWSER_DIR / name).relative_to(ROOT)))


def feedback_snapshot(page: Page) -> dict[str, object]:
    status = page.get_by_test_id("aggregation-status").first
    status.wait_for(state="visible", timeout=30_000)
    toggle = status.get_by_role("button", name="查看明细", exact=False)
    if toggle.count() and toggle.is_visible():
        toggle.click()
    status.locator(".aggregation-details").wait_for(state="visible")
    items = status.locator(".aggregation-views li")
    return {
        "headline": status.locator(".aggregation-copy strong").inner_text(),
        "summary": status.locator(".aggregation-copy span").inner_text(),
        "view_count": items.count(),
        "view_statuses": status.locator(".view-copy small").all_inner_texts(),
        "footer": status.locator("footer").inner_text() if status.locator("footer").count() else "",
        "text": status.inner_text(),
    }


def scan_routes(
    page: Page,
    base_url: str,
    report: dict[str, object],
    *,
    expected_token: str,
    viewport_label: str,
) -> None:
    short_token = expected_token[:10]
    snapshots = {}
    for index, (view_id, route) in enumerate(ROUTES, start=1):
        page.goto(route_url(base_url, route), wait_until="networkidle", timeout=60_000)
        snapshot = feedback_snapshot(page)
        assert snapshot["headline"] == "学习反馈已同步", snapshot
        assert snapshot["view_count"] == 6, snapshot
        assert snapshot["view_statuses"] == ["已同步"] * 6, snapshot
        assert short_token in snapshot["footer"], snapshot
        assert "下一日安排" in snapshot["text"], snapshot
        snapshots[view_id] = snapshot
        key = f"{view_id}_{viewport_label}"
        capture(page, report, f"{index:02d}-{view_id}-{viewport_label}.png")
        assert_visual(page, report, key)
    report["feedback_snapshots"][viewport_label] = snapshots


def verify_controlled_action(page: Page, base_url: str) -> None:
    page.goto(route_url(base_url, "/"), wait_until="networkidle", timeout=60_000)
    status = page.get_by_test_id("aggregation-status").first
    status.wait_for(state="visible")
    toggle = status.get_by_role("button", name="查看明细", exact=False)
    if toggle.count() and toggle.is_visible():
        toggle.click()
    status.get_by_title("进入学习路径").click()
    page.wait_for_url("**/workspace/path**", timeout=30_000)


def recover_partial(page: Page, base_url: str, partial: dict[str, object], report: dict[str, object]) -> str:
    page.goto(route_url(base_url, "/"), wait_until="networkidle", timeout=60_000)
    snapshot = feedback_snapshot(page)
    assert snapshot["headline"] == "部分反馈尚未同步", snapshot
    assert "已同步 2/6 项" in snapshot["summary"], snapshot
    assert snapshot["view_statuses"] == ["等待中", "已同步", "已同步", "待恢复", "待恢复", "等待中"], snapshot
    assert_visual(page, report, "partial_dashboard_1440x900")
    capture(page, report, "13-partial-dashboard-1440x900.png")

    before = database_state(str(report["fixture"]["owner_public_id"]))
    retry = page.get_by_role("button", name="重试同步", exact=True)
    retry.click()
    page.get_by_text("学习反馈已同步", exact=True).wait_for(state="visible", timeout=30_000)
    recovered = feedback_snapshot(page)
    assert recovered["view_statuses"] == ["已同步"] * 6, recovered
    state = aggregation_state(str(partial["event_id"]))
    assert state["status"] == "processed", state
    assert state["attempt"] == 2, state
    assert state["token"], state
    after = database_state(str(report["fixture"]["owner_public_id"]))
    assert after["learning_events"] == before["learning_events"], {"before": before, "after": after}
    assert after["consumptions"] == before["consumptions"], {"before": before, "after": after}
    assert_visual(page, report, "recovered_dashboard_1440x900")
    capture(page, report, "14-recovered-dashboard-1440x900.png")
    report["checks"]["partial_recovered_after_service_restart"] = True
    report["checks"]["recovery_no_duplicate_event_or_consumption"] = True
    return str(state["token"])


def run_browser_pass(
    base_url: str,
    report: dict[str, object],
    *,
    viewport: dict[str, int],
    expected_token: str,
    viewport_label: str,
    verify_action: bool = False,
) -> None:
    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport=viewport, locale="zh-CN")
            page = context.new_page()
            attach_diagnostics(page, report)
            login(page, base_url)
            before = database_state(str(report["fixture"]["owner_public_id"]))
            scan_routes(
                page,
                base_url,
                report,
                expected_token=expected_token,
                viewport_label=viewport_label,
            )
            if verify_action:
                verify_controlled_action(page, base_url)
            after = database_state(str(report["fixture"]["owner_public_id"]))
            assert after == before, {"before": before, "after": after}
            report["database"][f"browse_before_{viewport_label}"] = before
            report["database"][f"browse_after_{viewport_label}"] = after
            context.close()
        finally:
            browser.close()


def run_recovery_pass(base_url: str, partial: dict[str, object], report: dict[str, object]) -> str:
    with sync_playwright() as playwright:
        browser: Browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            attach_diagnostics(page, report)
            login(page, base_url)
            token = recover_partial(page, base_url, partial, report)
            context.close()
            return token
        finally:
            browser.close()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def run() -> dict[str, object]:
    configure_browser_base()
    browser_base.reset_output()
    port = browser_base.free_port()
    env = runtime_env(port)
    fixture = seed_fixture(env)
    base_url = f"http://127.0.0.1:{port}"
    report: dict[str, object] = {
        "schema_version": "f8-t05.learning-feedback-desktop.v1",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "viewports": [[1440, 900], [1366, 768]],
        "isolated_database": str(DB_PATH),
        "external_model_called": False,
        "fixture": fixture,
        "screenshots": [],
        "visual": {},
        "feedback_snapshots": {},
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
        run_browser_pass(
            base_url,
            report,
            viewport={"width": 1440, "height": 900},
            expected_token=str(fixture["completed_token"]),
            viewport_label="1440x900",
            verify_action=True,
        )
        browser_base.stop_service(process, port)
        process = None

        partial = create_partial_event(str(fixture["owner_public_id"]))
        report["partial_fixture"] = partial
        assert partial["statuses"] == {
            "dashboard": "pending",
            "profile": "completed",
            "path": "completed",
            "wrong_questions": "failed",
            "review": "failed",
            "history": "pending",
        }, partial

        process = browser_base.start_service(env, port)
        recovered_token = run_recovery_pass(base_url, partial, report)
        run_browser_pass(
            base_url,
            report,
            viewport={"width": 1366, "height": 768},
            expected_token=recovered_token,
            viewport_label="1366x768",
        )
        final_state = database_state(str(fixture["owner_public_id"]))
        assert final_state["integrity"] == "ok", final_state
        assert final_state["foreign_key_violations"] == 0, final_state
        report["database"]["final"] = final_state
        report["checks"].update({
            "six_views_share_one_event_and_token": True,
            "next_day_schedule_visible": True,
            "controlled_internal_action": True,
            "ordinary_browsing_zero_writes": True,
            "dual_desktop_visual_contract": True,
            "database_integrity": True,
        })
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
        files = [
            {"file": str(path.relative_to(OUTPUT_DIR)), "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT_DIR.rglob("*"))
            if path.is_file() and path.name not in {"manifest.json"} and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT_DIR / "manifest.json").write_text(
            json.dumps(
                {"schema_version": "f8-t05.evidence-manifest.v1", "files": files},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result["status"],
        "screenshots": len(result["screenshots"]),
        "checks": result["checks"],
        "database": result["database"],
    }, ensure_ascii=False, indent=2))
