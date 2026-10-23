"""Real Chromium acceptance for the lzz diagnostic course-catalog repair."""

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
OUTPUT_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "custom_tasks"
    / "ENTRY-DIAGNOSTIC-COURSE-CATALOG-REPAIR-01"
    / "browser"
)
FORMAL_DB = ROOT / "edumatrix.db"
RUNTIME_DB = OUTPUT_DIR / "entry_diagnostic_catalog.sqlite3"
USERNAME = "lzz"
PASSWORD = "404404aA"
MAIN_COURSE_ID = "course-ai-deep-learning-agents-v1"
SECOND_COURSE_ID = "course-data-structures-algorithms-engineering-v1"
COURSE_IDS = (MAIN_COURSE_ID, SECOND_COURSE_ID)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
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
        "EDUMATRIX_AUTH_SECRET_KEY": "entry-diagnostic-catalog-repair-secret",
        "EDUMATRIX_UPLOAD_DIR": str(OUTPUT_DIR / "uploads"),
        "EDUMATRIX_SANDBOX_MODE": "disabled",
    })
    return env


def login(page: Page, base_url: str) -> dict[str, object]:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": USERNAME, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"lzz login failed: {response.status} {response.text()}")
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
      localStorage.setItem('edumatrix_course_id', '{MAIN_COURSE_ID}');
    """)
    return session


def attach_diagnostics(page: Page, report: dict[str, object]) -> None:
    def on_response(response) -> None:
        parsed = urlparse(response.url)
        if parsed.hostname not in {"127.0.0.1", "localhost"} and parsed.scheme not in {"blob", "data"}:
            report["external_requests"].append(response.url)
        if response.status >= 400:
            report["http_errors"].append({"status": response.status, "url": response.url})

    page.on("response", on_response)
    page.on(
        "requestfailed",
        lambda request: report["failed_requests"].append(
            {"url": request.url, "failure": request.failure}
        ),
    )
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on(
        "console",
        lambda message: report["console_errors"].append(message.text)
        if message.type == "error"
        else None,
    )


def layout_contract(page: Page) -> dict[str, object]:
    return page.evaluate("""
      () => {
        const root = document.querySelector('[data-testid="entry-diagnostic"]')
        const visible = element => {
          if (!element) return false
          const style = getComputedStyle(element)
          const box = element.getBoundingClientRect()
          return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0
        }
        const controls = [...(root?.querySelectorAll('button, input, select') || [])]
          .filter(visible)
          .map(element => ({
            name: element.getAttribute('aria-label') || element.textContent.trim().slice(0, 80),
            rect: element.getBoundingClientRect().toJSON(),
          }))
        const collisions = []
        for (let i = 0; i < controls.length; i += 1) {
          for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i].rect
            const b = controls[j].rect
            const area = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left))
              * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top))
            if (area > 2) collisions.push([controls[i].name, controls[j].name])
          }
        }
        const smallText = [...(root?.querySelectorAll('h1,h2,h3,h4,p,span,small,strong,label,legend,button') || [])]
          .filter(element => visible(element) && element.children.length === 0 && element.textContent.trim())
          .filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 14)
          .map(element => element.textContent.trim().slice(0, 80))
        return {
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: document.documentElement.clientWidth,
          horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          collisions,
          smallText,
          errorNoticeVisible: visible(document.querySelector('[data-testid="diagnostic-courses-error"]')),
          selectionVisible: visible(document.querySelector('[data-testid="diagnostic-selection"]')),
          overviewVisible: visible(document.querySelector('[data-testid="diagnostic-overview"]')),
          generateVisible: visible(document.querySelector('[data-testid="generate-diagnostic"]')),
          generateEnabled: !document.querySelector('[data-testid="generate-diagnostic"]')?.disabled,
        }
      }
    """)


def selected_course_id(page: Page) -> str:
    return page.evaluate("""
      () => [...document.querySelectorAll('.course-choice input:checked')]
        .map(element => element.getAttribute('aria-label') || '')
        .join('|')
    """)


def select_only(page: Page, titles: dict[str, str], target_id: str) -> None:
    target = page.get_by_role("checkbox", name=f"选择课程 {titles[target_id]}")
    if not target.is_checked():
        target.check()
        page.get_by_test_id("diagnostic-overview").wait_for(state="visible", timeout=60_000)
    for course_id in COURSE_IDS:
        if course_id == target_id:
            continue
        other = page.get_by_role("checkbox", name=f"选择课程 {titles[course_id]}")
        if other.is_checked():
            other.uncheck()
            page.get_by_test_id("diagnostic-overview").wait_for(state="visible", timeout=60_000)
    page.get_by_text(titles[target_id], exact=True).last.wait_for(state="visible", timeout=60_000)


def capture_course(
    page: Page,
    report: dict[str, object],
    *,
    width: int,
    height: int,
    label: str,
    course_id: str,
    titles: dict[str, str],
) -> None:
    select_only(page, titles, course_id)
    question_count = page.get_by_label("诊断题目数量")
    if question_count.input_value() != "25":
        question_count.select_option("25")
        page.get_by_test_id("diagnostic-overview").wait_for(state="visible", timeout=60_000)
    page.wait_for_timeout(300)
    layout = layout_contract(page)
    assert layout["errorNoticeVisible"] is False, layout
    assert layout["selectionVisible"] is True, layout
    assert layout["overviewVisible"] is True, layout
    assert layout["generateVisible"] is True, layout
    assert layout["generateEnabled"] is True, layout
    assert layout["horizontalOverflow"] is False, layout
    assert not layout["collisions"], layout
    assert not layout["smallText"], layout
    screenshot_name = f"{width}x{height}-{label}.png"
    page.screenshot(path=OUTPUT_DIR / screenshot_name, full_page=False)
    image_size = list(Image.open(OUTPUT_DIR / screenshot_name).size)
    assert image_size == [width, height], image_size
    report["screenshots"].append(screenshot_name)
    report["checks"][f"{width}x{height}-{label}"] = {
        "course_id": course_id,
        "course_title": titles[course_id],
        "checked_labels": selected_course_id(page),
        "question_count": question_count.input_value(),
        "layout": layout,
        "screenshot_size": image_size,
    }


def database_audit() -> dict[str, object]:
    with sqlite3.connect(RUNTIME_DB) as db:
        user = db.execute(
            "SELECT public_id, role FROM users WHERE username=?", (USERNAME,)
        ).fetchone()
        memberships = db.execute(
            "SELECT course_id, role, status FROM course_memberships WHERE user_public_id=? AND course_id IN (?, ?) ORDER BY course_id",
            (user[0], *COURSE_IDS),
        ).fetchall()
        return {
            "integrity_check": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "lzz_role": user[1],
            "built_in_memberships": [list(row) for row in memberships],
        }


def run() -> dict[str, object]:
    clear_output()
    formal_hash_before = digest(FORMAL_DB)
    copy_formal_database()
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = int(os.getenv("EDUMATRIX_ENTRY_DIAGNOSTIC_REPAIR_PORT", "9050"))
    port = base.free_port()
    env = runtime_env(port)
    process = None
    report: dict[str, object] = {
        "schema_version": "entry-diagnostic-course-catalog-repair.browser.v1",
        "task_id": "ENTRY-DIAGNOSTIC-COURSE-CATALOG-REPAIR-01",
        "user": USERNAME,
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "checks": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "external_model_called": False,
        "formal_database_hash_before": formal_hash_before,
    }
    try:
        process = base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(
                    viewport={"width": width, "height": height}, locale="zh-CN"
                )
                page = context.new_page()
                attach_diagnostics(page, report)
                session = login(page, base_url)
                headers = {"Authorization": f"Bearer {session['access_token']}"}
                catalog_response = page.request.get(
                    f"{base_url}/api/v1/diagnostics/courses", headers=headers
                )
                assert catalog_response.status == 200, catalog_response.text()
                catalog = catalog_response.json()
                courses = {item["id"]: item for item in catalog["courses"]}
                assert all(course_id in courses for course_id in COURSE_IDS), courses.keys()
                titles = {course_id: courses[course_id]["title"] for course_id in COURSE_IDS}
                assert all(courses[course_id]["sourceSummary"]["readyDocuments"] > 0 for course_id in COURSE_IDS)
                report["checks"][f"catalog-{width}x{height}"] = {
                    "status": catalog_response.status,
                    "schema_version": catalog["schemaVersion"],
                    "course_count": len(catalog["courses"]),
                    "built_in_courses": [courses[course_id] for course_id in COURSE_IDS],
                }

                page.goto(
                    f"{base_url}/workspace/assessment/entry?course_id={MAIN_COURSE_ID}",
                    wait_until="networkidle",
                    timeout=90_000,
                )
                page.get_by_test_id("diagnostic-selection").wait_for(timeout=60_000)
                capture_course(
                    page,
                    report,
                    width=width,
                    height=height,
                    label="01-main-course",
                    course_id=MAIN_COURSE_ID,
                    titles=titles,
                )
                capture_course(
                    page,
                    report,
                    width=width,
                    height=height,
                    label="02-second-course",
                    course_id=SECOND_COURSE_ID,
                    titles=titles,
                )
                context.close()
            browser.close()

        report["database"] = database_audit()
        assert report["database"]["integrity_check"] == "ok"
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["external_requests"], report["external_requests"]
        report["status"] = "passed"
        return report
    finally:
        base.stop_service(process, port)
        report["formal_database_hash_after"] = digest(FORMAL_DB)
        report["formal_database_unchanged"] = (
            report["formal_database_hash_before"] == report["formal_database_hash_after"]
        )
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "browser_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
