"""Continuous F7 desktop acceptance on one isolated runtime and Chromium."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
import traceback
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, sync_playwright

import e2e_f7_t01_knowledge_shelf as shelf_base
import e2e_f7_t02_document_reader as reader_base
import e2e_f7_t03_graph_admission as graph_base
import e2e_f7_t04_chat as chat_base
import e2e_f7_t05_evidence as evidence_base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f7_phase_acceptance"
BROWSER_DIR = OUTPUT_DIR / "browser"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "f7_phase_runtime.sqlite3"
REPORT_PATH = OUTPUT_DIR / "continuous_report.json"
PORT_START = 9040


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


def seed_fixtures(env: dict[str, str]) -> dict[str, dict[str, object]]:
    shelf_base.OUTPUT_DIR = helper_dir("t01")
    reader_base.OUTPUT_DIR = helper_dir("t02")
    graph_base.OUTPUT_DIR = helper_dir("t03")
    chat_base.OUTPUT_DIR = helper_dir("t04")
    evidence_base.OUTPUT_DIR = helper_dir("t05")
    env["EDUMATRIX_UPLOAD_DIR"] = str(RUNTIME_DIR / "uploads")
    return {
        "shelf": shelf_base.seed_fixture(env),
        "reader": reader_base.seed_fixture(env),
        "graph": graph_base.seed_fixture(env),
        "chat": chat_base.seed_fixture(env),
        "evidence": evidence_base.seed_fixture(env),
    }


def prefix_new_screenshots(report: dict[str, object], start: int, prefix: str) -> None:
    screenshots = report["screenshots"]
    assert isinstance(screenshots, list)
    for index in range(start, len(screenshots)):
        screenshots[index] = f"{prefix}/{screenshots[index]}"


def run_helper(
    report: dict[str, object],
    prefix: str,
    output_dir: Path,
    set_output: Callable[[Path], None],
    action: Callable[[], None],
) -> None:
    screenshots = report["screenshots"]
    assert isinstance(screenshots, list)
    start = len(screenshots)
    set_output(output_dir)
    action()
    prefix_new_screenshots(report, start, prefix)


def set_shelf_output(path: Path) -> None:
    shelf_base.OUTPUT_DIR = path


def set_reader_output(path: Path) -> None:
    reader_base.OUTPUT_DIR = path


def set_graph_output(path: Path) -> None:
    graph_base.OUTPUT_DIR = path


def set_chat_output(path: Path) -> None:
    chat_base.OUTPUT_DIR = path
    chat_base.COURSE_ID = "demo-course-rag-trust-v1"


def set_evidence_output(path: Path) -> None:
    evidence_base.OUTPUT_DIR = path
    evidence_base.configure_shared_helpers()


def attach_diagnostics(page: Page, report: dict[str, object]) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.scheme in {"http", "https"} and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
        }:
            report["external_requests"].append(response.url)
        if response.status < 400:
            return
        if response.status == 503 and "/api/knowledge/discovery/search" in response.url:
            report["expected_injected_failures"].append(
                {"status": response.status, "url": response.url}
            )
            return
        report["http_errors"].append({"status": response.status, "url": response.url})

    def on_console(message) -> None:
        if message.type != "error":
            return
        if "503 (Service Unavailable)" in message.text:
            report["expected_injected_console"].append(message.text)
            return
        report["console_errors"].append(message.text)

    page.on("response", on_response)
    page.on(
        "requestfailed",
        lambda request: report["failed_requests"].append(
            {"url": request.url, "failure": request.failure}
        ),
    )
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", on_console)


def login(page: Page, base_url: str, *, course_id: str) -> None:
    chat_base.COURSE_ID = course_id
    chat_base.login(page, base_url)


def capture_shelf(
    page: Page,
    base_url: str,
    fixture: dict[str, object],
    report: dict[str, object],
    suffix: str,
) -> None:
    shelf_base.open_home(page, base_url)
    page.get_by_test_id("my-course-shelf").wait_for(state="visible")
    flagship = page.get_by_test_id(f"shelf-course-{shelf_base.COURSE_ID}")
    flagship.wait_for(state="visible")
    assert str(fixture["course_title"]) in flagship.inner_text()
    assert "来源与索引完整" in flagship.inner_text()
    assert page.get_by_text("拖拽文件到此处，或点击选择文件").is_visible() is False
    positions = page.evaluate(
        """() => ['my-shelf-title', 'recommendation-title', 'discovery-title']
        .map(id => document.getElementById(id).getBoundingClientRect().top + window.scrollY)"""
    )
    assert positions == sorted(positions), positions
    shelf_base.assert_visual_contract(page, report, f"phase_shelf_{suffix}", primary_actions=1)
    shelf_base.capture(page, report, f"01-course-shelf-{suffix}.png")


def assert_sensitive_fields_absent(page: Page) -> None:
    text = page.locator("body").inner_text().lower()
    for forbidden in (
        "api_key",
        "reasoning_content",
        "chain_of_thought",
        "raw_trace",
        "raw_log",
        "system prompt",
    ):
        assert forbidden not in text, forbidden


def protected_state(db_path: Path, owner_public_id: str) -> dict[str, object]:
    state = chat_base.database_state(db_path, owner_public_id)
    with sqlite3.connect(db_path, timeout=20) as db:
        state.update(
            {
                "path_nodes": db.execute(
                    """SELECT COUNT(*)
                       FROM path_nodes AS node
                       JOIN learning_paths AS path ON path.id = node.learning_path_id
                       WHERE path.owner_public_id=?""",
                    (owner_public_id,),
                ).fetchone()[0],
                "document_selections": db.execute(
                    "SELECT COUNT(*) FROM document_selections WHERE owner_public_id=?", (owner_public_id,)
                ).fetchone()[0],
                "source_candidates": db.execute(
                    "SELECT COUNT(*) FROM web_source_candidates WHERE owner_public_id=?",
                    (owner_public_id,),
                ).fetchone()[0],
            }
        )
    return state


def assert_protected_state(before: dict[str, object], after: dict[str, object]) -> None:
    for key in (
        "learning_events",
        "profile_snapshots",
        "assessment_attempts",
        "source_documents",
        "source_refs",
        "path_nodes",
        "mastery",
    ):
        assert after[key] == before[key], (key, before[key], after[key])
    assert after["generation_tasks"] >= before["generation_tasks"] + 3, (before, after)
    assert after["chat_messages"] > before["chat_messages"], (before, after)
    assert after["document_selections"] >= before["document_selections"] + 2, (before, after)
    assert after["source_candidates"] >= before["source_candidates"] + 1, (before, after)
    assert after["integrity"] == "ok", after
    assert after["foreign_key_violations"] == 0, after


def run_primary_journey(
    browser: Browser,
    base_url: str,
    fixtures: dict[str, dict[str, object]],
    report: dict[str, object],
) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        accept_downloads=True,
    )
    page = context.new_page()
    attach_diagnostics(page, report)
    login(page, base_url, course_id=shelf_base.COURSE_ID)

    run_helper(
        report,
        "t01",
        helper_dir("t01"),
        set_shelf_output,
        lambda: capture_shelf(page, base_url, fixtures["shelf"], report, "1440x900"),
    )
    run_helper(
        report,
        "t02",
        helper_dir("t02"),
        set_reader_output,
        lambda: reader_base.verify_text_reader(page, base_url, fixtures["reader"], report),
    )
    run_helper(
        report,
        "t02",
        helper_dir("t02"),
        set_reader_output,
        lambda: reader_base.verify_image_reader(page, base_url, fixtures["reader"], report),
    )
    run_helper(
        report,
        "t03",
        helper_dir("t03"),
        set_graph_output,
        lambda: graph_base.verify_graph(page, base_url, fixtures["graph"], report, "1440x900"),
    )
    run_helper(
        report,
        "t03",
        helper_dir("t03"),
        set_graph_output,
        lambda: graph_base.verify_discovery(
            page,
            base_url,
            report,
            "1440x900",
            full_flow=True,
        ),
    )
    run_helper(
        report,
        "t04",
        helper_dir("t04"),
        set_chat_output,
        lambda: chat_base.exercise_primary(page, base_url, fixtures["chat"], DB_PATH, report),
    )
    run_helper(
        report,
        "t05",
        helper_dir("t05"),
        set_evidence_output,
        lambda: evidence_base.exercise_handout_reader_round_trip(
            page, base_url, report, "1440x900"
        ),
    )
    run_helper(
        report,
        "t05",
        helper_dir("t05"),
        set_evidence_output,
        lambda: evidence_base.exercise_chat_round_trip(page, base_url, report, "1440x900"),
    )
    assert_sensitive_fields_absent(page)
    report["checks"]["primary_journey"] = (
        "shelf -> text/image selection -> graph/source -> candidate boundary -> "
        "attachments/stream recovery -> exact source/public Agent audit"
    )
    context.close()


def run_secondary_journey(
    browser: Browser,
    base_url: str,
    fixtures: dict[str, dict[str, object]],
    report: dict[str, object],
) -> None:
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},
        locale="zh-CN",
        accept_downloads=True,
    )
    page = context.new_page()
    attach_diagnostics(page, report)
    login(page, base_url, course_id=shelf_base.COURSE_ID)

    run_helper(
        report,
        "t01",
        helper_dir("t01"),
        set_shelf_output,
        lambda: capture_shelf(page, base_url, fixtures["shelf"], report, "1366x768"),
    )
    run_helper(
        report,
        "t02",
        helper_dir("t02"),
        set_reader_output,
        lambda: reader_base.verify_secondary_viewport(page, base_url, fixtures["reader"], report),
    )
    run_helper(
        report,
        "t03",
        helper_dir("t03"),
        set_graph_output,
        lambda: graph_base.verify_graph(page, base_url, fixtures["graph"], report, "1366x768"),
    )
    run_helper(
        report,
        "t05",
        helper_dir("t05"),
        set_evidence_output,
        lambda: evidence_base.exercise_handout_reader_round_trip(
            page, base_url, report, "1366x768"
        ),
    )
    run_helper(
        report,
        "t05",
        helper_dir("t05"),
        set_evidence_output,
        lambda: evidence_base.exercise_chat_round_trip(page, base_url, report, "1366x768"),
    )
    assert_sensitive_fields_absent(page)
    report["checks"]["secondary_journey"] = "critical F7 surfaces verified at 1366x768"
    context.close()


def run() -> dict[str, object]:
    reset_generated_output()
    chat_base.OUTPUT_DIR = RUNTIME_DIR
    chat_base.PORT_START = PORT_START
    port = chat_base.free_port()
    env = chat_base.runtime_env(DB_PATH, port)
    env["EDUMATRIX_UPLOAD_DIR"] = str(RUNTIME_DIR / "uploads")
    fixtures = seed_fixtures(env)
    report: dict[str, object] = {
        "status": "running",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "viewports": [[1440, 900], [1366, 768]],
        "isolated_database": str(DB_PATH),
        "single_service": True,
        "single_chromium_instance": True,
        "external_model_called": False,
        "checks": {},
        "screenshots": [],
        "visual": {},
        "theme": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "expected_injected_failures": [],
        "expected_injected_console": [],
    }
    process = None
    try:
        chat_base.OUTPUT_DIR = RUNTIME_DIR
        process = chat_base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        owner_id = str(fixtures["chat"]["owner_public_id"])
        before = protected_state(DB_PATH, owner_id)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                run_primary_journey(browser, base_url, fixtures, report)
                run_secondary_journey(browser, base_url, fixtures, report)
            finally:
                browser.close()
        after = protected_state(DB_PATH, owner_id)
        assert_protected_state(before, after)
        report["database"] = {"before": before, "after": after}
        assert len(report["expected_injected_failures"]) == 1, report[
            "expected_injected_failures"
        ]
        assert len(report["expected_injected_console"]) <= 1, report[
            "expected_injected_console"
        ]
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
        chat_base.stop_service(process, port)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "status": result["status"],
        "screenshots": len(result["screenshots"]),
        "database": result["database"],
    }, ensure_ascii=False, indent=2))
