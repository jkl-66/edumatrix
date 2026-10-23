"""F9-T04 authorization and summary-audit E2E on isolated SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Browser, Playwright, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import e2e_f9_t03_admin_teacher as base  # noqa: E402


OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f9_t04_authorization_audit"
DB_PATH = OUTPUT_DIR / "f9_t04_authorization_audit.sqlite3"
FIXTURE_PATH = OUTPUT_DIR / "fixture.json"
REPORT_PATH = OUTPUT_DIR / "report.json"
PORT = int(os.getenv("EDUMATRIX_F9_T04_PORT", "8994"))
ASSISTANT_USERNAME = "f9-legacy-assistant"
AUDIT_SCHEMA_VERSION = "edumatrix.audit.summary.v1"
INTERNAL_AUDIT_ACTIONS = {
    "assessment.exam.create",
    "assessment.exam.transition",
    "assessment.question.create",
    "plan.confirmed",
    "plan.draft_created",
}
ALLOWED_AUDIT_FIELDS = {
    "id", "actorPublicId", "action", "objectType", "objectId", "outcome",
    "beforeSummary", "afterSummary", "createdAt", "detailsAvailable",
}


def configure_runtime(port: int) -> None:
    base.OUTPUT_DIR = OUTPUT_DIR
    base.DB_PATH = DB_PATH
    base.FIXTURE_PATH = FIXTURE_PATH
    base.REPORT_PATH = REPORT_PATH
    base.PORT = port
    base.configure_runtime(port)
    os.environ["EDUMATRIX_AUTH_SECRET_KEY"] = "f9-t04-isolated-browser-secret"


def prepare_fixture(port: int) -> None:
    configure_runtime(port)
    base.prepare_fixture(port)

    from app.auth import get_password_hash
    from app.database import DBUser, SessionLocal

    with SessionLocal() as db:
        db.add(DBUser(
            public_id="f9-legacy-assistant",
            username=ASSISTANT_USERNAME,
            display_name="历史助教账号",
            hashed_password=get_password_hash(base.TEST_PASSWORD),
            role="assistant",
            is_active=True,
        ))
        db.commit()

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture["assistant_username"] = ASSISTANT_USERNAME
    FIXTURE_PATH.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / ".gitkeep").write_text(
        "F9-T04 isolated browser evidence directory.\n", encoding="utf-8"
    )
    print(json.dumps({"status": "prepared", "database": str(DB_PATH)}, ensure_ascii=False))


def validate_audit_payload(payload: dict) -> None:
    audits = payload.get("recent_audits") or []
    assert audits, payload
    for audit in audits:
        assert set(audit) == ALLOWED_AUDIT_FIELDS, audit
        assert "metadata_json" not in audit and "trace_id" not in audit, audit
    base.scan_sensitive(audits)


def assert_audit_cells_fit(page) -> None:
    overflow = page.locator(".audit-table tbody tr").evaluate_all(
        """rows => rows.flatMap((row, rowIndex) =>
            Array.from(row.cells).flatMap((cell, cellIndex) => {
                const cellRect = cell.getBoundingClientRect();
                const range = document.createRange();
                range.selectNodeContents(cell);
                const contentRect = range.getBoundingClientRect();
                const outside = contentRect.left < cellRect.left - 1 ||
                    contentRect.right > cellRect.right + 1 ||
                    cell.scrollWidth > cell.clientWidth + 1;
                return outside ? [{
                    row: rowIndex,
                    cell: cellIndex,
                    text: (cell.innerText || '').trim(),
                    cellLeft: cellRect.left,
                    cellRight: cellRect.right,
                    contentLeft: contentRect.left,
                    contentRight: contentRect.right,
                    clientWidth: cell.clientWidth,
                    scrollWidth: cell.scrollWidth,
                }] : [];
            })
        )"""
    )
    assert not overflow, overflow


def run_audit_panel(
    browser: Browser,
    base_url: str,
    fixture: dict,
    report: dict,
) -> None:
    learning_before = base.teacher_base.learning_state(DB_PATH)
    for width, height in base.VIEWPORTS:
        context = browser.new_context(
            viewport={"width": width, "height": height}, locale="zh-CN", color_scheme="light"
        )
        session = base.api_login(context, base_url, fixture["admin_username"])
        base.teacher_base.add_session(context, session, fixture)
        page = context.new_page()
        base.teacher_base.attach_diagnostics(page, report)
        try:
            base.goto_target(page, base_url, "/admin/system", "admin-system-page", "系统状态")
            panel = page.locator("details.audit-panel")
            panel.wait_for(state="visible")
            assert panel.get_attribute("open") is None

            response = context.request.get(
                f"{base_url}/api/v1/admin/system", headers=base.auth_headers(session)
            )
            assert response.ok, (response.status, response.text())
            validate_audit_payload(response.json())

            panel.locator("summary").click()
            assert panel.get_attribute("open") is not None
            page.locator(".audit-table tbody tr").first.wait_for(state="visible")
            assert_audit_cells_fit(page)
            page_text = page.locator("body").inner_text()
            assert not (INTERNAL_AUDIT_ACTIONS & set(page_text.split())), page_text
            base.scan_sensitive(page_text)
            base.capture(page, report, f"{width}x{height}_14_admin_audit_expanded.png")
        finally:
            context.close()

    assert base.teacher_base.learning_state(DB_PATH) == learning_before
    report["audit_panel_default_collapsed"] = True
    report["audit_panel_expanded_at_both_viewports"] = True
    report["audit_payload_allowlist_verified"] = True
    report["audit_browse_learning_state_unchanged"] = True


def run_legacy_assistant_boundary(
    browser: Browser,
    base_url: str,
    fixture: dict,
    report: dict,
) -> None:
    context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
    session = base.api_login(context, base_url, fixture["assistant_username"])
    try:
        for path in (
            "/api/v1/teacher/courses",
            "/api/v1/admin/accounts",
            "/api/v1/admin/system",
        ):
            response = context.request.get(f"{base_url}{path}", headers=base.auth_headers(session))
            assert response.status == 403, (path, response.status, response.text())

        queue_response = context.request.get(
            f"{base_url}/api/v1/content-review/queue", headers=base.auth_headers(session)
        )
        assert queue_response.ok, (queue_response.status, queue_response.text())
        assert queue_response.json()["items"] == [], queue_response.json()
        decision_response = context.request.post(
            f"{base_url}/api/v1/content-review/cases/{fixture['review_case_id']}/decisions",
            headers=base.auth_headers(session),
            data={"action": "publish", "reason": "legacy assistant forbidden", "expected_version": 1},
        )
        assert decision_response.status == 403, (
            decision_response.status, decision_response.text()
        )

        base.teacher_base.add_session(context, session, fixture)
        page = context.new_page()
        base.teacher_base.attach_diagnostics(page, report)
        page.goto(f"{base_url}/settings", wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_load_state("networkidle")
        assert urlparse(page.url).path == "/landing", page.url
        assert not page.locator('[data-testid="admin-system-page"]').is_visible()
        assert not page.locator('[data-testid="teacher-overview-page"]').is_visible()
    finally:
        context.close()
    report["legacy_assistant_private_api_denied"] = True
    report["legacy_assistant_review_queue_empty"] = True
    report["legacy_assistant_public_landing_only"] = True


def audit_database() -> dict[str, object]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        summary_rows = []
        for (raw_metadata,) in db.execute("SELECT metadata_json FROM audit_logs"):
            metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else raw_metadata
            if isinstance(metadata, dict) and metadata.get("schemaVersion") == AUDIT_SCHEMA_VERSION:
                summary_rows.append(metadata)
        base.scan_sensitive(summary_rows)
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "summary_audit_rows": len(summary_rows),
            "learning_event_rows": db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
        }


def run_e2e(playwright: Playwright, base_url: str) -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    report = {
        "task": "F9-T04",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "viewports": [list(item) for item in base.VIEWPORTS],
        "screenshots": [],
        "visual_checks": {},
        "browser_pages": [],
        "ordinary_browse_database_unchanged": False,
        "teacher_exam_published": False,
        "teacher_intervention_published": False,
        "admin_accounts_checked": False,
        "admin_models_checked": False,
        "content_review_approved": False,
        "failed_task_recovered": False,
        "role_boundaries_verified": False,
        "mastery_unchanged_by_teacher_actions": False,
        "external_model_called": False,
    }
    browser = playwright.chromium.launch(headless=True)
    try:
        base.run_teacher_journey(browser, base_url, fixture, report)
        base.run_admin_journey(browser, base_url, fixture, report)
        base.run_role_boundaries(browser, base_url, fixture, report)
        base.run_compact_routes(browser, base_url, fixture, report)
        run_audit_panel(browser, base_url, fixture, report)
        run_legacy_assistant_boundary(browser, base_url, fixture, report)
        base.assert_browser_clean(report)
        database = audit_database()
        assert database["integrity"] == "ok", database
        assert database["foreign_key_violations"] == 0, database
        assert database["summary_audit_rows"] >= 3, database
        report["database_audit"] = database
        base.scan_sensitive(report)
        report["status"] = "passed"
    except Exception as exception:
        report["status"] = "failed"
        report["failure"] = {"type": type(exception).__name__, "message": str(exception)}
        raise
    finally:
        browser.close()
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        base.write_manifest()
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
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    configure_runtime(args.port)
    if args.prepare:
        prepare_fixture(args.port)
    elif args.serve:
        base.serve(args.port)
    else:
        with sync_playwright() as playwright:
            run_e2e(playwright, f"http://127.0.0.1:{args.port}")


if __name__ == "__main__":
    main()
