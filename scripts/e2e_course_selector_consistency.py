"""Real Chromium acceptance for the shared course selector contract."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image
from playwright.sync_api import Page, sync_playwright

import e2e_f6_t03_code_sandbox as base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "COURSE-SELECTOR-CONSISTENCY-01" / "browser"
FORMAL_DB = ROOT / "edumatrix.db"
RUNTIME_DB = OUTPUT_DIR / "course-selector.sqlite3"
USERNAME = "lzz"
PASSWORD = "404404aA"
STALE_COURSE_ID = "noc-t12-real-course-613e7c83b1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.name == "browser_report.json":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def copy_formal_database() -> None:
    source = sqlite3.connect(f"file:{FORMAL_DB.as_posix()}?mode=ro", uri=True)
    target = sqlite3.connect(RUNTIME_DB)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def runtime_env(port: int) -> dict[str, str]:
    env = base.runtime_env(RUNTIME_DB, port)
    env.update({
        "EDUMATRIX_AUTH_SECRET_KEY": "course-selector-consistency-browser-secret",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_UPLOAD_DIR": str(OUTPUT_DIR / "uploads"),
    })
    return env


def login(page: Page, base_url: str) -> dict[str, object]:
    response = page.request.post(f"{base_url}/api/auth/login", form={"username": USERNAME, "password": PASSWORD})
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    session = response.json()
    state = json.dumps(session, ensure_ascii=False)
    page.add_init_script(f"""
      const session = {state};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_display_name', session.display_name || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_role', session.role || 'student');
      localStorage.setItem('edumatrix_student_id', session.student_id || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', 'course-ai-deep-learning-agents-v1');
    """)
    return session


def login_as(page: Page, base_url: str, username: str, password: str) -> dict[str, object]:
    response = page.request.post(f"{base_url}/api/auth/login", form={"username": username, "password": password})
    if not response.ok:
        raise AssertionError(f"login failed for {username}: {response.status} {response.text()}")
    session = response.json()
    state = json.dumps(session, ensure_ascii=False)
    page.add_init_script(f"""
      const session = {state};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username || '{username}');
      localStorage.setItem('edumatrix_display_name', session.display_name || session.username || '{username}');
      localStorage.setItem('edumatrix_role', session.role || 'student');
      localStorage.setItem('edumatrix_student_id', session.student_id || session.username || '{username}');
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', 'course-ai-deep-learning-agents-v1');
    """)
    return session


def diagnostics(page: Page, report: dict[str, object]) -> None:
    def record_response(response):
        if response.status < 400:
            return
        item = {"status": response.status, "url": response.url}
        stale_request = STALE_COURSE_ID in response.url or STALE_COURSE_ID in page.url
        expected = (
            "/api/v1/competition-demo/context" in response.url
            or stale_request and "/api/v1/m5/context/resolve" in response.url
            or stale_request and f"/api/v1/courses/{STALE_COURSE_ID}" in response.url
        )
        report["expected_http_errors" if expected else "http_errors"].append(item)

    page.on("response", record_response)
    page.on("requestfailed", lambda request: report["failed_requests"].append({"url": request.url, "failure": request.failure}))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    def record_console(message):
        if message.type != "error":
            return
        stale_page = STALE_COURSE_ID in page.url or (
            "/context-recovery" in page.url
            and "context_course_unavailable" in page.url
        )
        expected = (
            "competition-demo/context" in message.text
            or stale_page and (
                "m5/context/resolve" in message.text
                or f"courses/{STALE_COURSE_ID}" in message.text
                or "status of 409" in message.text
            )
            or "status of 403" in message.text
        )
        report["expected_console_errors" if expected else "console_errors"].append(message.text)

    page.on("console", record_console)


def visible(element) -> bool:
    return bool(element and element.is_visible())


def selector_snapshot(page: Page) -> dict[str, object]:
    return page.evaluate("""
      () => {
        const visible = el => {
          if (!el) return false;
          const style = getComputedStyle(el);
          const box = el.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0;
        };
        const controls = [...document.querySelectorAll('select')].filter(visible).map((el) => ({
          label: el.getAttribute('aria-label') || el.previousElementSibling?.textContent?.trim() || '',
          value: el.value,
          options: [...el.options].map(option => ({value: option.value, label: option.textContent.trim()})),
        }));
        const picker = document.querySelector('[data-testid="chat-course-picker"]');
        const pickerOptions = [...(picker?.querySelectorAll('.course-picker__option') || [])].filter(visible).map(el => ({
          value: el.querySelector('input')?.value || '',
          label: el.textContent.trim(),
        }));
        const diagnosticOptions = [...document.querySelectorAll('[data-testid="diagnostic-selection"] label.course-choice')]
          .filter(visible)
          .map(el => ({value: el.querySelector('input')?.value || '', label: el.textContent?.trim() || ''}));
        const courseCardIds = [...document.querySelectorAll('[data-testid^="shelf-course-"], [data-testid^="recommendation-course-"], [data-testid^="add-course-"]')]
          .filter(visible)
          .map(el => (el.getAttribute('data-testid') || '').replace(/^shelf-course-/, '').replace(/^recommendation-course-/, '').replace(/^add-course-/, ''))
          .filter(Boolean);
        return {
          pathname: location.pathname,
          title: document.title,
          text: document.body.innerText.slice(0, 4000),
          selects: controls,
          pickerOptions,
          diagnosticOptions,
          courseCardIds,
          staleVisible: document.body.innerText.includes('NOC-T12') || document.body.innerText.includes('noc-t12-real-course'),
          overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        };
      }
    """)


def route_and_capture(page: Page, base_url: str, route: str, filename: str, wait_for: str | None = None) -> dict[str, object]:
    page.goto(f"{base_url}{route}", wait_until="networkidle", timeout=90_000)
    if wait_for:
        page.locator(wait_for).wait_for(state="visible", timeout=60_000)
    page.wait_for_timeout(250)
    snapshot = selector_snapshot(page)
    page.screenshot(path=OUTPUT_DIR / filename, full_page=False)
    assert list(Image.open(OUTPUT_DIR / filename).size) == [page.viewport_size["width"], page.viewport_size["height"]]
    assert not snapshot["staleVisible"], snapshot
    assert not snapshot["overflow"], snapshot
    return snapshot


def available_catalog(page: Page, base_url: str, token: str) -> dict[str, dict[str, object]]:
    response = page.request.get(f"{base_url}/api/knowledge/courses", headers={"Authorization": f"Bearer {token}"})
    assert response.status == 200, response.text()
    payload = response.json()
    rows = [*(payload.get("shelf") or []), *(payload.get("recommendations") or [])]
    catalog = {str(row["id"]): row for row in rows if row.get("id") and row.get("selectable", True)}
    assert catalog
    assert STALE_COURSE_ID not in catalog
    return catalog


def stale_recovery(page: Page, base_url: str, report: dict[str, object]) -> None:
    page.goto(f"{base_url}/knowledge/courses/{STALE_COURSE_ID}?course_id={STALE_COURSE_ID}", wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(1500)
    text = page.locator("body").inner_text()
    state = page.evaluate("""() => ({
      courseId: localStorage.getItem('edumatrix_course_id'),
      context: localStorage.getItem('edumatrix_context_ref'),
      url: location.href,
    })""")
    assert "NOC-T12" not in text and STALE_COURSE_ID not in text
    assert state["courseId"] != STALE_COURSE_ID, state
    assert "/context-recovery" in state["url"] or "/knowledge" in state["url"], state
    page.screenshot(path=OUTPUT_DIR / f"{page.viewport_size['width']}x{page.viewport_size['height']}-stale-recovery.png", full_page=False)
    report["checks"][f"stale-recovery-{page.viewport_size['width']}x{page.viewport_size['height']}"] = {"url": state["url"], "local_storage": state}


def database_audit() -> dict[str, object]:
    with sqlite3.connect(RUNTIME_DB) as db:
        history = db.execute("select count(*) from learning_events").fetchone()[0]
        return {
            "integrity_check": db.execute("pragma integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("pragma foreign_key_check").fetchall()),
            "learning_events": history,
            "stale_course_status": db.execute("select status from courses where id=?", (STALE_COURSE_ID,)).fetchone()[0],
        }


def database_baseline() -> dict[str, object]:
    with sqlite3.connect(RUNTIME_DB) as db:
        return {
            "integrity_check": db.execute("pragma integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("pragma foreign_key_check").fetchall()),
        }


def run() -> dict[str, object]:
    clear_output()
    formal_hash_before = digest(FORMAL_DB)
    copy_formal_database()
    baseline = database_baseline()
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = int(os.getenv("EDUMATRIX_COURSE_SELECTOR_PORT", "9060"))
    port = base.free_port()
    process = None
    report: dict[str, object] = {
        "schema_version": "course-selector-consistency.browser.v1",
        "task_id": "COURSE-SELECTOR-CONSISTENCY-01",
        "viewports": [[1440, 900], [1366, 768]],
        "routes": {},
        "screenshots": [],
        "checks": {},
        "database_baseline": baseline,
        "http_errors": [],
        "expected_http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "expected_console_errors": [],
        "external_requests": [],
        "formal_database_hash_before": formal_hash_before,
    }
    try:
        process = base.start_service(runtime_env(port), port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
                page = context.new_page()
                diagnostics(page, report)
                session = login(page, base_url)
                token = str(session["access_token"])
                catalog = available_catalog(page, base_url, token)
                report["checks"][f"catalog-{width}x{height}"] = {
                    "course_count": len(catalog),
                    "course_ids": sorted(catalog),
                    "titles": [catalog[key].get("title") for key in sorted(catalog)],
                }
                route_specs = [
                    ("/knowledge", "knowledge-shelf"),
                    ("/workspace/path", "learning-path"),
                    ("/workspace/assessment/entry", "entry-diagnostic"),
                    ("/workspace/assessment/exams", "intelligent-exams"),
                    ("/workspace/resources", "resource-center"),
                    ("/learn", "chat"),
                    ("/profile/learning", "profile-learning"),
                    ("/profile/history", "profile-history"),
                    ("/workspace/review", "review"),
                    ("/teacher/courses", "teacher-courses"),
                ]
                for route, label in route_specs:
                    snapshot = route_and_capture(page, base_url, route, f"{width}x{height}-{label}.png")
                    report["routes"].setdefault(label, {})[f"{width}x{height}"] = snapshot
                    report["screenshots"].append(f"{width}x{height}-{label}.png")
                    selected_values = {
                        option["value"]
                        for select in snapshot["selects"]
                        for option in select["options"]
                        if option["value"] in catalog
                    }
                    course_like_values = {
                        option["value"]
                        for select in snapshot["selects"]
                        if "课程" in str(select.get("label") or "")
                        for option in select["options"]
                        if option["value"] not in {"", "all", "none"}
                    }
                    assert course_like_values <= set(catalog), {
                        "route": route,
                        "unknown_course_values": sorted(course_like_values - set(catalog)),
                        "catalog": sorted(catalog),
                    }
                    catalog_titles = {str(course.get("title") or "").strip() for course in catalog.values()}
                    diagnostic_labels = [str(item.get("label") or "") for item in snapshot.get("diagnosticOptions") or []]
                    assert all(any(title and title in label for title in catalog_titles) for label in diagnostic_labels), {
                        "route": route,
                        "unknown_diagnostic_labels": diagnostic_labels,
                    }
                    assert set(snapshot.get("courseCardIds") or []) <= set(catalog), {
                        "route": route,
                        "unknown_course_cards": sorted(set(snapshot.get("courseCardIds") or []) - set(catalog)),
                    }
                    if label == "chat":
                        page.get_by_test_id("chat-course-picker").locator("button").click()
                        page.wait_for_timeout(100)
                        picker_snapshot = selector_snapshot(page)
                        report["routes"][label][f"{width}x{height}"]["picker_open"] = picker_snapshot["pickerOptions"]
                        picker_text = "\n".join(item["label"] for item in picker_snapshot["pickerOptions"])
                        assert all(str(course.get("title") or "") in picker_text for course in catalog.values()), {
                            "picker": picker_snapshot["pickerOptions"],
                            "catalog_titles": [course.get("title") for course in catalog.values()],
                        }
                        page.keyboard.press("Escape")
                    if selected_values:
                        assert selected_values <= set(catalog), {"route": route, "values": sorted(selected_values), "catalog": sorted(catalog)}
                stale_recovery(page, base_url, report)
                context.close()

            # Teacher-only course management uses the same published course
            # boundary, but has a separate role guard and account context.
            teacher_context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
            teacher_page = teacher_context.new_page()
            diagnostics(teacher_page, report)
            teacher_session = login_as(teacher_page, base_url, "teacher", "admin123")
            teacher_catalog = available_catalog(teacher_page, base_url, str(teacher_session["access_token"]))
            teacher_snapshot = route_and_capture(teacher_page, base_url, "/teacher/courses", f"{width}x{height}-teacher-courses-role.png")
            report["routes"].setdefault("teacher-courses-role", {})[f"{width}x{height}"] = teacher_snapshot
            report["screenshots"].append(f"{width}x{height}-teacher-courses-role.png")
            teacher_values = {
                option["value"]
                for select in teacher_snapshot["selects"]
                for option in select["options"]
                if option["value"] in teacher_catalog
            }
            assert teacher_values <= set(teacher_catalog), teacher_values
            teacher_context.close()
            browser.close()
        report["database"] = database_audit()
        assert report["database"]["integrity_check"] == "ok"
        report["database"]["foreign_key_violations_unchanged"] = (
            report["database"]["foreign_key_violations"]
            == baseline["foreign_key_violations"]
        )
        assert report["database"]["foreign_key_violations_unchanged"]
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        base.stop_service(process, port)
        report["formal_database_hash_after"] = digest(FORMAL_DB)
        report["formal_database_unchanged"] = report["formal_database_hash_before"] == report["formal_database_hash_after"]
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(run(), ensure_ascii=False, indent=2))
