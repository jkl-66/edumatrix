"""Continuous F8 phase acceptance on one isolated database and Chromium."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from playwright.sync_api import Browser, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import e2e_f8_t01_review_calendar as review
from scripts import e2e_f8_t02_wrong_questions as wrong
from scripts import e2e_f8_t03_notes as notes
from scripts import e2e_f8_t04_profile_history as profile
from scripts import e2e_f8_t05_learning_feedback as feedback

OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f8_phase_acceptance"
BROWSER_DIR = OUTPUT_DIR / "browser"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "f8_phase_runtime.sqlite3"
REPORT_PATH = OUTPUT_DIR / "continuous_report.json"
PORT_START = int(os.getenv("EDUMATRIX_F8_PHASE_PORT", "9160"))


def reset_generated_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in (BROWSER_DIR, RUNTIME_DIR):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    if REPORT_PATH.exists():
        REPORT_PATH.unlink()


def helper_dir(name: str) -> Path:
    path = BROWSER_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def configure_helpers() -> None:
    review.OUTPUT_DIR = OUTPUT_DIR
    review.BROWSER_DIR = helper_dir("t01")
    review.RUNTIME_DIR = RUNTIME_DIR
    review.DB_PATH = DB_PATH
    review.REPORT_PATH = REPORT_PATH
    review.PORT_START = PORT_START

    for name, module in (("t02", wrong), ("t03", notes), ("t04", profile), ("t05", feedback)):
        module.OUTPUT_DIR = OUTPUT_DIR
        module.BROWSER_DIR = helper_dir(name)
        module.RUNTIME_DIR = RUNTIME_DIR
        module.DB_PATH = DB_PATH
        module.REPORT_PATH = REPORT_PATH
        module.PORT_START = PORT_START


def runtime_env(port: int) -> dict[str, str]:
    env = review.runtime_env(port)
    env.update({
        "EDUMATRIX_AUTH_SECRET_KEY": "f8-phase-isolated-secret",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_UPLOAD_DIR": str(RUNTIME_DIR / "uploads"),
    })
    return env


def seed_fixtures(env: dict[str, str]) -> dict[str, dict[str, object]]:
    base = review.seed_fixture(env)
    profile_fixture = profile.seed_fixture(env, base_fixture=base)
    wrong_fixture = wrong.seed_fixture(env, preserve_review_plans=True)
    notes_fixture = notes.seed_fixture(env, base_fixture=base)
    feedback_fixture = feedback.seed_fixture(env, base_fixture=base)
    profile_fixture["expected_note_events"] = composite_note_event_count(
        owner_public_id=str(profile_fixture["owner_public_id"]),
        course_id=str(profile_fixture["course_id"]),
    )
    return {
        "review": base,
        "wrong": wrong_fixture,
        "notes": notes_fixture,
        "profile": profile_fixture,
        "feedback": feedback_fixture,
    }


def composite_note_event_count(*, owner_public_id: str, course_id: str) -> int:
    local_start = datetime.now(profile.LOCAL_ZONE).replace(
        hour=0, minute=0, second=0, microsecond=0,
    ) - timedelta(days=6)
    utc_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    utc_end = datetime.now(timezone.utc).replace(tzinfo=None)
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        return int(db.execute(
            "SELECT COUNT(*) FROM learning_events "
            "WHERE owner_public_id=? AND course_id=? AND occurred_at>=? AND occurred_at<=? "
            "AND lower(coalesce(event_type, '') || ' ' || coalesce(object_type, '')) LIKE '%note%'",
            (owner_public_id, course_id, utc_start, utc_end),
        ).fetchone()[0])


def prefix_new_screenshots(report: dict[str, object], start: int, prefix: str) -> None:
    screenshots = report["screenshots"]
    assert isinstance(screenshots, list)
    for index in range(start, len(screenshots)):
        screenshots[index] = f"{prefix}/{Path(str(screenshots[index])).name}"


def run_helper(report: dict[str, object], prefix: str, action: Callable[[], None]) -> None:
    screenshots = report["screenshots"]
    assert isinstance(screenshots, list)
    start = len(screenshots)
    review.BROWSER_DIR = helper_dir(prefix)
    action()
    prefix_new_screenshots(report, start, prefix)


def attach_diagnostics(page: Page, report: dict[str, object]) -> None:
    wrong.attach_diagnostics(page, report)


def protected_state(fixtures: dict[str, dict[str, object]]) -> dict[str, object]:
    owner = str(fixtures["feedback"]["owner_public_id"])
    return {
        "review": review.database_state(owner),
        "wrong": wrong.database_state(fixtures["wrong"]),
        "notes": notes.database_state(fixtures["notes"]),
        "profile": profile.database_state(owner, review.USERNAME),
        "feedback": feedback.database_state(owner),
    }


def login(page: Page, base_url: str) -> None:
    review.login(page, base_url)


def run_primary_before_restart(
    page: Page,
    base_url: str,
    fixtures: dict[str, dict[str, object]],
    report: dict[str, object],
) -> dict[str, object]:
    run_helper(report, "t04", lambda: profile.run_primary(page, base_url, fixtures["profile"], report))
    run_helper(report, "t01", lambda: review.run_primary(page, base_url, fixtures["review"], report))
    run_helper(report, "t02", lambda: wrong.run_primary(page, base_url, fixtures["wrong"], report))
    run_helper(report, "t03", lambda: notes.run_primary(page, base_url, fixtures["notes"], report))
    partial = feedback.create_partial_event(str(fixtures["feedback"]["owner_public_id"]))
    report["checks"]["partial_before_restart"] = partial
    return partial


def run_primary_after_restart(
    page: Page,
    base_url: str,
    partial: dict[str, object],
    report: dict[str, object],
) -> str:
    token_holder: dict[str, str] = {}

    def recover() -> None:
        token_holder["token"] = feedback.recover_partial(page, base_url, partial, report)

    run_helper(report, "t05", recover)
    token = token_holder["token"]
    run_helper(
        report,
        "t05",
        lambda: feedback.scan_routes(
            page,
            base_url,
            report,
            expected_token=token,
            viewport_label="1440x900",
        ),
    )
    feedback.verify_controlled_action(page, base_url)
    report["checks"]["six_views_consistent_after_restart"] = True
    return token


def run_secondary(
    page: Page,
    base_url: str,
    fixtures: dict[str, dict[str, object]],
    report: dict[str, object],
    expected_token: str,
) -> None:
    before = protected_state(fixtures)
    run_helper(report, "t01", lambda: review.run_secondary(page, base_url, fixtures["review"], report))
    run_helper(report, "t02", lambda: wrong.run_secondary(page, base_url, fixtures["wrong"], report))
    run_helper(report, "t03", lambda: notes.run_secondary(page, base_url, fixtures["notes"], report))
    run_helper(report, "t04", lambda: profile.run_secondary(page, base_url, report))
    run_helper(
        report,
        "t05",
        lambda: feedback.scan_routes(
            page,
            base_url,
            report,
            expected_token=expected_token,
            viewport_label="1366x768",
        ),
    )
    after = protected_state(fixtures)
    assert after == before, {"before": before, "after": after}
    report["database"]["final_read_only_before"] = before
    report["database"]["final_read_only_after"] = after
    report["checks"]["continuous_secondary_browsing_zero_writes"] = True


def run_empty_account(
    browser: Browser,
    base_url: str,
    fixtures: dict[str, dict[str, object]],
    report: dict[str, object],
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
    page = context.new_page()
    attach_diagnostics(page, report)
    profile.login(
        page,
        base_url,
        username=profile.EMPTY_USERNAME,
        password=profile.EMPTY_PASSWORD,
    )
    run_helper(report, "t04", lambda: profile.run_empty(page, base_url, fixtures["profile"], report))
    context.close()


def run() -> dict[str, object]:
    reset_generated_output()
    configure_helpers()
    port = review.free_port()
    env = runtime_env(port)
    fixtures = seed_fixtures(env)
    report: dict[str, object] = {
        "schema_version": "f8.phase-continuous.v1",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "viewports": [[1440, 900], [1366, 768]],
        "isolated_database": str(DB_PATH),
        "single_service_runtime": True,
        "service_restart_count": 1,
        "single_chromium_instance": True,
        "external_model_called": False,
        "fixture": fixtures["feedback"],
        "checks": {},
        "screenshots": [],
        "visual": {},
        "theme": {},
        "database": {},
        "feedback_snapshots": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "expected_http_errors": [],
        "expected_console_errors": [],
        "diagnostic_expectations": {
            "note_conflict": {
                "active": False,
                "operation": "save_stale_note_version",
                "status": 409,
                "url": "",
                "response_seen": False,
            },
        },
    }
    process = None
    browser = None
    try:
        process = review.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                primary_context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN", accept_downloads=True)
                primary = primary_context.new_page()
                attach_diagnostics(primary, report)
                login(primary, base_url)
                partial = run_primary_before_restart(primary, base_url, fixtures, report)

                review.stop_service(process, port)
                process = None
                process = review.start_service(env, port)
                recovered_token = run_primary_after_restart(primary, base_url, partial, report)
                primary_context.close()

                secondary_context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN", accept_downloads=True)
                secondary = secondary_context.new_page()
                attach_diagnostics(secondary, report)
                login(secondary, base_url)
                run_secondary(secondary, base_url, fixtures, report, recovered_token)
                secondary_context.close()

                run_empty_account(browser, base_url, fixtures, report)
            finally:
                browser.close()
                browser = None

        note_conflict = report["diagnostic_expectations"]["note_conflict"]
        assert note_conflict["response_seen"] is True, note_conflict
        assert note_conflict["active"] is False, note_conflict
        expected_http = {
            (503, f"{base_url}/api/quiz/wrong-questions/{review.USERNAME}"),
            (409, note_conflict["url"]),
        }
        observed_expected_http = {
            (item["status"], item["url"])
            for item in report["expected_http_errors"]
        }
        assert observed_expected_http == expected_http, report["expected_http_errors"]
        allowed_expected_console = {
            "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
            "Failed to load resource: the server responded with a status of 409 (Conflict)",
        }
        assert len(report["expected_console_errors"]) == len(set(report["expected_console_errors"])), report["expected_console_errors"]
        assert set(report["expected_console_errors"]) <= allowed_expected_console, report["expected_console_errors"]
        for field in ("http_errors", "failed_requests", "page_errors", "console_errors", "external_requests"):
            assert not report[field], {field: report[field]}
        final_state = protected_state(fixtures)
        for section in final_state.values():
            assert section["integrity"] == "ok", section
            assert section["foreign_key_violations"] == 0, section
        report["database"]["final"] = final_state
        report["checks"]["four_protected_surfaces_present"] = {
            "profile": True,
            "path": True,
            "notes": True,
            "wrong_questions": True,
        }
        report["checks"]["continuous_order"] = [
            "profile/history",
            "review calendar and real actions",
            "wrong-question source/diagnosis/redo",
            "source-bound notes and version recovery",
            "partial feedback",
            "service restart",
            "six-view consistency",
            "dual-desktop read-only pass",
        ]
        report["status"] = "passed"
        return report
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        cleanup_errors = []
        if browser is not None:
            try:
                browser.close()
            except Exception as exc:
                cleanup_errors.append(f"browser: {exc}")
        try:
            review.stop_service(process, port)
        except Exception as exc:
            cleanup_errors.append(f"service: {exc}")
        if cleanup_errors:
            report["cleanup_errors"] = cleanup_errors
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result["status"],
        "screenshots": len(result["screenshots"]),
        "checks": len(result["checks"]),
        "service_restart_count": result["service_restart_count"],
    }, ensure_ascii=False, indent=2))
