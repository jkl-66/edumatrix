"""F9 phase acceptance on one isolated SQLite, service and Chromium instance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Playwright, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import e2e_f9_t01_marketplace as market  # noqa: E402
import e2e_f9_t04_authorization_audit as authorization  # noqa: E402


OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f9_phase_acceptance"
BROWSER_DIR = OUTPUT_DIR / "browser"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "f9_phase_acceptance.sqlite3"
TEACHER_FIXTURE_PATH = RUNTIME_DIR / "teacher_fixture.json"
PHASE_FIXTURE_PATH = RUNTIME_DIR / "phase_fixture.json"
REPORT_PATH = OUTPUT_DIR / "continuous_report.json"
LEDGER_PATH = OUTPUT_DIR / "atomic_execution_ledger.json"
PORT = int(os.getenv("EDUMATRIX_F9_PHASE_PORT", "8995"))
VIEWPORTS = ((1440, 900), (1366, 768))


def configure_modules(port: int) -> None:
    BROWSER_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    authorization.OUTPUT_DIR = BROWSER_DIR
    authorization.DB_PATH = DB_PATH
    authorization.FIXTURE_PATH = TEACHER_FIXTURE_PATH
    authorization.REPORT_PATH = REPORT_PATH
    authorization.PORT = port
    authorization.base.VIEWPORTS = VIEWPORTS
    authorization.configure_runtime(port)

    market.OUTPUT_DIR = BROWSER_DIR
    market.DB_PATH = DB_PATH
    market.FIXTURE_PATH = PHASE_FIXTURE_PATH
    market.REPORT_PATH = REPORT_PATH
    market.PORT = port
    market.VIEWPORTS = VIEWPORTS

    os.environ.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "f9-phase-isolated-browser-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(port),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })


def update_ledger(status: str, verification: str) -> None:
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    atom_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    previous = next(
        (item for item in ledger.get("execution_batches", []) if item.get("batch") == "PA-B01-continuous-journey"),
        None,
    )
    attempt_history = list((previous or {}).get("attempt_history", []))
    if previous and previous.get("status") not in {None, "PREPARED"}:
        attempt_history.append({
            "status": previous["status"],
            "verification": previous.get("verification", ""),
            "recorded_at": previous.get("updated_at"),
        })
    batches = [item for item in ledger.get("execution_batches", []) if item.get("batch") != "PA-B01-continuous-journey"]
    batches.append({
        "batch": "PA-B01-continuous-journey",
        "status": status,
        "mapped_atoms": atom_ids,
        "protection_contracts": [
            "market_copy", "teacher_read_only", "admin_minimal_scope", "formal_roles",
            "learning_state", "audit_privacy", "data_integrity", "visual", "environment",
        ],
        "changed_files": [
            "scripts/e2e_f9_phase_acceptance.py",
            "outputs/原系统融合重构执行/evidence/f9_phase_acceptance/continuous_report.json",
            "outputs/原系统融合重构执行/evidence/f9_phase_acceptance/browser/",
            "outputs/原系统融合重构执行/evidence/f9_phase_acceptance/runtime/f9_phase_acceptance.sqlite3",
        ],
        "result": "One phase journey reuses the closed F9 implementation without changing business code.",
        "verification": verification,
        "attempt_history": attempt_history,
        "product_fixes": [{
            "atoms": ["G23-R05", "G23-R06"],
            "files": [
                "frontend/src/views/AdminAccounts.vue",
                "tests/test_f9_t03_admin_teacher_frontend_contract.py",
            ],
            "result": "Long formal usernames wrap inside the fixed-layout account table instead of being clipped by the panel.",
            "verification": "Focused administrator frontend contracts passed 2 tests and the production build transformed 6937 modules; the next dual-desktop browser pass must confirm the rendered fix. No role, API or account behavior changed.",
        }],
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    ledger["execution_batches"] = batches
    ledger["state"] = "TESTED" if status == "PASSED" else "EDITING"
    ledger["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_runtime_database() -> None:
    runtime_root = RUNTIME_DIR.resolve()
    output_root = OUTPUT_DIR.resolve()
    if output_root != runtime_root and output_root not in runtime_root.parents:
        raise RuntimeError(f"Runtime directory escapes phase output: {runtime_root}")
    for suffix in ("", "-shm", "-wal"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    for path in (TEACHER_FIXTURE_PATH, PHASE_FIXTURE_PATH, REPORT_PATH):
        if path.exists():
            path.unlink()


def seed_marketplace() -> dict:
    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_f9_t01_marketplace_service import _publish, _seed_marketplace_objects, _submit

    with TestClient(app) as client:
        seeded = _seed_marketplace_objects(client)
        headers = seeded["headers"]
        suffix = str(seeded["suffix"])
        resource = _publish(client, headers["admin"], _submit(
            client,
            headers["publisher"],
            suffix=suffix,
            item_type="resource",
            source_object_id=str(seeded["artifact_id"]),
            source_version_id=str(seeded["artifact_version_id"]),
        ))
        learning_path = _publish(client, headers["admin"], _submit(
            client,
            headers["publisher"],
            suffix=suffix,
            item_type="learning_path",
            source_object_id=str(seeded["path_id"]),
            source_version_id=str(seeded["path_version_id"]),
        ))

    return {
        "suffix": suffix,
        "course_id": seeded["course_id"],
        "bundle_id": seeded["bundle_id"],
        "bundle_version_id": seeded["bundle_version_id"],
        "usernames": {
            role: f"f9_market_{role}_{suffix}"
            for role in ("publisher", "admin", "learner", "outsider")
        },
        "published_listings": {
            "resource": resource,
            "learning_path": learning_path,
        },
    }


def prepare_fixture(port: int) -> None:
    configure_modules(port)
    remove_runtime_database()
    authorization.prepare_fixture(port)
    teacher_fixture = json.loads(TEACHER_FIXTURE_PATH.read_text(encoding="utf-8"))
    teacher_fixture["usernames"]["assistant"] = teacher_fixture["assistant_username"]
    market_fixture = seed_marketplace()
    PHASE_FIXTURE_PATH.write_text(
        json.dumps({"teacher": teacher_fixture, "market": market_fixture}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    update_ledger(
        "PREPARED",
        "A fresh isolated SQLite fixture now contains the marketplace, teacher, administrator, formal-role and historical-assistant records required by all 29 atoms; no service or browser has run yet.",
    )
    print(json.dumps({
        "status": "prepared",
        "database": str(DB_PATH),
        "teacher_course": teacher_fixture["course_id"],
        "market_course": market_fixture["course_id"],
    }, ensure_ascii=False))


def protected_learning_state() -> dict[str, object]:
    teacher_base = authorization.base.teacher_base
    state = teacher_base.learning_state(DB_PATH)
    return {
        "learning_events": state["learning_events"],
        "profile_snapshots": state["profile_snapshots"],
        "student_profiles": state["student_profiles"],
        "mastery_digest": teacher_base.mastery_digest(DB_PATH),
    }


def database_audit() -> dict[str, object]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "learning_event_rows": db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
            "profile_snapshot_rows": db.execute("SELECT COUNT(*) FROM profile_snapshots").fetchone()[0],
            "market_personal_copies": db.execute("SELECT COUNT(*) FROM marketplace_personal_copies").fetchone()[0],
            "published_exams": db.execute("SELECT COUNT(*) FROM assessment_exams WHERE status='published'").fetchone()[0],
            "approved_review_cases": db.execute("SELECT COUNT(*) FROM content_review_cases WHERE status='approved'").fetchone()[0],
            "summary_audit_rows": db.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE metadata_json LIKE '%edumatrix.audit.summary.v1%'"
            ).fetchone()[0],
        }


def write_manifest() -> None:
    files = []
    for path in sorted(OUTPUT_DIR.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        files.append({
            "path": path.relative_to(OUTPUT_DIR).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps({"files": files}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_teacher_observation_journey(browser, base_url: str, fixture: dict, report: dict) -> None:
    """Verify T02 observation and idempotency after T03 has published its intervention."""
    teacher_base = authorization.base.teacher_base
    context = browser.new_context(
        viewport={"width": 1440, "height": 900}, locale="zh-CN", color_scheme="light"
    )
    page = context.new_page()
    page_report = teacher_base.attach_diagnostics(page, report)
    intervention_payloads: list[dict] = []

    def record_intervention(request) -> None:
        if request.method == "POST" and request.url.split("?", 1)[0].endswith("/api/v1/teacher/interventions"):
            intervention_payloads.append(request.post_data_json)

    page.on("request", record_intervention)
    try:
        session = teacher_base.login_through_ui(page, base_url, fixture, report)
        page.locator(".state-panel").filter(has_text="正在读取教学数据").wait_for(
            state="hidden", timeout=30_000
        )
        course_select = page.locator("#overview-course")
        assert course_select.input_value() == fixture["course_id"]
        assert course_select.locator("option").all_inner_texts() == ["可信 RAG 工程", "第二门视觉模型课程"]
        teacher_base.capture(page, report, "1440x900_01_teacher_overview.png")

        course_select.select_option(fixture["secondary_course_id"])
        teacher_base.wait_query(page, "courseId", fixture["secondary_course_id"])
        course_select.select_option(fixture["course_id"])
        teacher_base.wait_query(page, "courseId", fixture["course_id"])

        teacher_base.goto_teacher(page, base_url, "/teacher/courses", "课程与资源")
        page.get_by_placeholder("搜索课程、方向或简介").fill("第二门")
        page.get_by_role("heading", name="第二门视觉模型课程", exact=True).wait_for(state="visible")
        assert page.locator(".course-row").count() == 1
        page.get_by_placeholder("搜索课程、方向或简介").fill("")
        assert page.locator(".course-row").count() == 2
        teacher_base.capture(page, report, "1440x900_02_teacher_courses.png")

        teacher_base.goto_teacher(
            page, base_url, f"/teacher/courses/{fixture['course_id']}", "可信 RAG 工程"
        )
        for tab in ("章节", "来源", "资源", "班级与任务"):
            page.get_by_role("tab", name=tab, exact=True).click()
            page.locator(".course-detail-section").wait_for(state="visible")
        page.get_by_role("tab", name="章节", exact=True).click()
        teacher_base.capture(page, report, "1440x900_03_teacher_course_detail.png")

        teacher_base.goto_teacher(
            page,
            base_url,
            f"/teacher/students?courseId={fixture['course_id']}",
            "学生学情",
        )
        page.get_by_placeholder("搜索姓名或账号").fill("学员一")
        page.get_by_role("button", name="查找", exact=True).click()
        teacher_base.wait_query(page, "q", "学员一")
        page.wait_for_function(
            "() => document.querySelectorAll('.student-row:not(.student-row--header)').length === 1",
            timeout=30_000,
        )
        row_text = page.locator(".student-row:not(.student-row--header)").first.inner_text()
        assert "学员一" in row_text
        assert '{"title"' not in row_text and "/workspace?" not in row_text
        teacher_base.capture(page, report, "1440x900_04_teacher_students.png")

        browse_before = teacher_base.learning_state(DB_PATH)
        mastery_before = teacher_base.mastery_digest(DB_PATH)
        teacher_base.goto_teacher(
            page,
            base_url,
            f"/teacher/students/{fixture['learner_id']}?courseId={fixture['course_id']}",
            "学员一",
        )
        assert page.get_by_text("掌握度只读", exact=True).is_visible()
        assert page.get_by_text("混合检索与重排", exact=True).is_visible()
        page.locator(".weak-list details").first.locator("summary").click()
        weak_text = page.locator(".weak-detail").first.inner_text()
        assert "建议动作：开始针对性学习" in weak_text and '{"title"' not in weak_text
        page.locator(".timeline details").first.locator("summary").click()
        page.locator(".agent-audit > summary").click()
        page.locator(".agent-list p").filter(has_text="分歧：候选难度存在分歧").wait_for(state="visible")
        authorization.base.scan_sensitive(page.locator("body").inner_text())
        teacher_base.capture(page, report, "1440x900_05_teacher_student_detail.png")
        assert teacher_base.learning_state(DB_PATH) == browse_before
        report["ordinary_browse_database_unchanged"] = True

        page.route(
            "**/api/v1/teacher/students/f9-learner-1?*",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "isolated refresh failure"}),
            ),
            times=1,
        )
        page.get_by_role("button", name="刷新当前教学数据", exact=True).click()
        page.get_by_text("已保留上一次读取结果。", exact=False).wait_for(state="visible")
        assert page.get_by_text("混合检索与重排", exact=True).is_visible()
        page.get_by_role("button", name="重试", exact=True).click()
        page.get_by_text("已保留上一次读取结果。", exact=False).wait_for(state="hidden")
        report["refresh_failure_preserved_and_recovered"] = True

        page.get_by_role("button", name="创建学习干预", exact=True).click()
        page.get_by_text("干预任务已加入学生路径", exact=False).wait_for(state="visible", timeout=30_000)
        assert len(intervention_payloads) == 1, intervention_payloads
        replay = context.request.post(
            f"{base_url}/api/v1/teacher/interventions",
            headers=teacher_base.auth_headers(session),
            data=intervention_payloads[0],
        )
        assert replay.status == 201 and replay.json()["created"] is False, replay.text()
        after = teacher_base.learning_state(DB_PATH)
        for table in ("learning_events", "profile_snapshots", "student_profiles"):
            assert after[table] == browse_before[table], (table, browse_before[table], after[table])
        assert teacher_base.mastery_digest(DB_PATH) == mastery_before
        for table in ("learning_paths", "path_nodes", "plan_drafts", "plan_versions"):
            assert after[table]["count"] - browse_before[table]["count"] in {0, 1}, (table, browse_before[table], after[table])
        report["intervention_idempotent"] = True
        report["mastery_unchanged"] = True
        teacher_base.consume_expected_http_error(
            page_report,
            report,
            status=503,
            path="/api/v1/teacher/students/f9-learner-1",
        )
    finally:
        context.close()


def run_e2e(playwright: Playwright, base_url: str) -> None:
    fixture = json.loads(PHASE_FIXTURE_PATH.read_text(encoding="utf-8"))
    teacher_fixture = fixture["teacher"]
    teacher_fixture["usernames"].setdefault("assistant", teacher_fixture["assistant_username"])
    market_fixture = fixture["market"]
    report = {
        "task": "F9-PHASE-ACCEPTANCE",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "viewports": [list(item) for item in VIEWPORTS],
        "single_database": True,
        "single_service_runtime": True,
        "service_restart_count": 0,
        "single_chromium_instance": True,
        "screenshots": [],
        "visual_checks": {},
        "browser_pages": [],
        "expected_http_errors": [],
        "ordinary_browse_database_unchanged": False,
        "learning_state_unchanged_after_publish_and_save": False,
        "refresh_failure_preserved_and_recovered": False,
        "intervention_idempotent": False,
        "mastery_unchanged": False,
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
    protected_before = protected_learning_state()
    try:
        bundle_listing, _ = market.run_publisher_journey(browser, base_url, market_fixture, report)
        admin_context = browser.new_context()
        try:
            published_bundle, market_admin_session = market.publish_with_admin(
                admin_context.request, base_url, market_fixture, bundle_listing
            )
        finally:
            admin_context.close()
        market_fixture["published_listings"]["resource_bundle"] = published_bundle
        copies = market.run_learner_journey(
            browser, base_url, market_fixture, report, market_admin_session
        )
        market.run_outsider_path_check(
            browser, base_url, market_fixture, report, copies["path_copy"]
        )
        market.run_compact_viewport_checks(browser, base_url, market_fixture, report, copies)

        authorization.base.run_teacher_journey(browser, base_url, teacher_fixture, report)
        run_teacher_observation_journey(browser, base_url, teacher_fixture, report)
        teacher_base = authorization.base.teacher_base
        teacher_base.run_role_boundaries(browser, base_url, teacher_fixture, report)
        teacher_base.run_compact_teacher(browser, base_url, teacher_fixture, report)
        authorization.base.run_admin_journey(browser, base_url, teacher_fixture, report)
        authorization.base.run_role_boundaries(browser, base_url, teacher_fixture, report)
        authorization.base.run_compact_routes(browser, base_url, teacher_fixture, report)
        authorization.run_audit_panel(browser, base_url, teacher_fixture, report)
        authorization.run_legacy_assistant_boundary(browser, base_url, teacher_fixture, report)

        market.assert_browser_clean(report)
        authorization.base.assert_browser_clean(report)
        protected_after = protected_learning_state()
        assert protected_after == protected_before, (protected_before, protected_after)
        report["phase_protected_learning_state_unchanged"] = True

        audit = database_audit()
        assert audit["integrity"] == "ok", audit
        assert audit["foreign_key_violations"] == 0, audit
        assert audit["market_personal_copies"] >= 2, audit
        assert audit["published_exams"] >= 1, audit
        assert audit["approved_review_cases"] >= 1, audit
        assert audit["summary_audit_rows"] >= 3, audit
        report["database_audit"] = audit
        report["copies"] = {
            "bundle": {key: copies["bundle_copy"][key] for key in ("id", "copy_object_id", "copy_version_id", "open_route")},
            "learning_path": {key: copies["path_copy"][key] for key in ("id", "copy_object_id", "copy_version_id", "open_route")},
        }
        report["published_listing_ids"] = {
            key: value["id"] for key, value in market_fixture["published_listings"].items()
        }
        report["status"] = "passed"
    except Exception as exception:
        report["status"] = "failed"
        report["failure"] = {"type": type(exception).__name__, "message": str(exception)}
        raise
    finally:
        browser.close()
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_manifest()
        verification = (
            f"status={report['status']}; screenshots={len(report['screenshots'])}; "
            f"browser_pages={len(report['browser_pages'])}; single database/service/Chromium; "
            f"external_model_called={report['external_model_called']}."
        )
        update_ledger("PASSED" if report["status"] == "passed" else "FAILED", verification)
    print(json.dumps({
        "status": report["status"],
        "screenshots": len(report["screenshots"]),
        "browser_pages": len(report["browser_pages"]),
        "database": report.get("database_audit"),
        "external_model_called": report["external_model_called"],
    }, ensure_ascii=False))


def serve(port: int) -> None:
    configure_modules(port)
    authorization.base.serve(port)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--serve", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    configure_modules(args.port)
    if args.prepare:
        prepare_fixture(args.port)
    elif args.serve:
        serve(args.port)
    else:
        with sync_playwright() as playwright:
            run_e2e(playwright, f"http://127.0.0.1:{args.port}")


if __name__ == "__main__":
    main()
