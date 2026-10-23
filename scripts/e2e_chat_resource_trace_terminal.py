"""Visual acceptance for terminal Chat resource timelines."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

from jose import jwt
from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "custom_tasks"
    / "CHAT-RESOURCE-TRACE-STALE-01"
    / "browser"
)
SOURCE_DB = ROOT / "edumatrix.db"
ISOLATED_DB = OUTPUT_DIR / "chat_resource_trace.sqlite3"
SECRET = "chat-resource-trace-isolated-secret"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_service(base_url: str, timeout: float = 40.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(base_url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"service did not start: {base_url}")


def backup_database() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if ISOLATED_DB.exists():
        ISOLATED_DB.unlink()
    with sqlite3.connect(SOURCE_DB) as source, sqlite3.connect(ISOLATED_DB) as target:
        source.backup(target)


def target_context() -> dict[str, str]:
    with sqlite3.connect(ISOLATED_DB) as db:
        db.row_factory = sqlite3.Row
        user = db.execute(
            "SELECT public_id, username, display_name, role FROM users WHERE username=?",
            ("lzz",),
        ).fetchone()
        if user is None:
            raise AssertionError("lzz user is unavailable in the isolated database")
        rows = db.execute(
            "SELECT id, conversation_id, stream_checkpoint FROM chat_messages "
            "WHERE owner_public_id=? AND role='assistant' ORDER BY created_at DESC",
            (user["public_id"],),
        ).fetchall()
        selected = None
        checkpoint: dict[str, object] = {}
        for row in rows:
            candidate = json.loads(row["stream_checkpoint"] or "{}")
            if candidate.get("resourceStatus") == "partial_success":
                selected = row
                checkpoint = candidate
                break
        if selected is None:
            raise AssertionError("no partial_success resource Chat message was found")
        snapshot = dict(checkpoint.get("contextSnapshot") or {})
        course_id = str(snapshot.get("course_id") or "")
        course = db.execute("SELECT title FROM courses WHERE id=?", (course_id,)).fetchone()
        failed_types = sorted({
            str(event.get("stageId") or "").split(":", 1)[1]
            for event in list(checkpoint.get("runEvents") or [])
            if event.get("eventType") == "resource.item.failed"
            and str(event.get("stageId") or "").startswith("resource:")
        })
        return {
            "user_id": str(user["public_id"]),
            "username": str(user["username"]),
            "display_name": str(user["display_name"] or user["username"]),
            "role": str(user["role"]),
            "message_id": str(selected["id"]),
            "conversation_id": str(selected["conversation_id"]),
            "course_id": course_id,
            "course_title": str(course[0] if course else course_id),
            "checkpoint": json.dumps(checkpoint, ensure_ascii=False, sort_keys=True),
            "failed_types": json.dumps(failed_types, ensure_ascii=False),
            "foreign_key_violations": str(len(db.execute("PRAGMA foreign_key_check").fetchall())),
        }


def access_token(context: dict[str, str]) -> str:
    payload = {
        "uid": context["user_id"],
        "sub": context["user_id"],
        "username": context["username"],
        "role": context["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=2),
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")


def start_service(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(ISOLATED_DB),
        "EDUMATRIX_AUTH_SECRET_KEY": SECRET,
        "EDUMATRIX_DEMO_MODE": "0",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(port),
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    log = (OUTPUT_DIR / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    process._edumatrix_log = log  # type: ignore[attr-defined]
    return process


def stop_service(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=20,
        )
        process.wait(timeout=10)
    log = getattr(process, "_edumatrix_log", None)
    if log is not None:
        log.close()


def attach_diagnostics(page: Page, report: dict[str, object]) -> None:
    page.on("response", lambda response: (
        report["http_errors"].append({"status": response.status, "url": response.url})
        if response.status >= 400 else None
    ))
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url,
        "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: (
        report["console_errors"].append(message.text)
        if message.type == "error" else None
    ))


def add_session(page: Page, context: dict[str, str], token: str) -> None:
    state = json.dumps({
        "token": token,
        "username": context["username"],
        "displayName": context["display_name"],
        "role": context["role"],
        "courseId": context["course_id"],
        "courseTitle": context["course_title"],
    }, ensure_ascii=False)
    page.add_init_script(f"""
      const state = {state};
      localStorage.setItem('edumatrix_token', state.token);
      localStorage.setItem('edumatrix_username', state.username);
      localStorage.setItem('edumatrix_display_name', state.displayName);
      localStorage.setItem('edumatrix_role', state.role);
      localStorage.setItem('edumatrix_student_id', state.username);
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', state.courseId);
      localStorage.setItem('edumatrix_course_title', state.courseTitle);
    """)


def assert_terminal_timeline(timeline, label: str) -> dict[str, object]:
    text = timeline.inner_text()
    assert "资源进度" in text, f"{label}: resource progress is missing"
    assert "8/9" in text, f"{label}: expected 8/9 partial result, got {text}"
    assert "1 项失败，可重试" in text, f"{label}: retryable failure summary is missing"
    stale = timeline.locator(
        'li[data-status="pending"], li[data-status="queued"], li[data-status="running"]'
    ).count()
    failed = timeline.locator('li[data-status="failed"]').count()
    assert stale == 0, f"{label}: {stale} stale pending/running rows remain"
    assert failed == 1, f"{label}: expected one concrete failed resource, got {failed}"
    assert timeline.locator(".spin").count() == 0, f"{label}: spinner remains after terminal state"
    assert "测验题" in text, f"{label}: failed resource type is not named"
    return {"text": text, "stale_rows": stale, "failed_rows": failed}


def verify_viewport(
    browser,
    base_url: str,
    context: dict[str, str],
    token: str,
    viewport: tuple[int, int],
    report: dict[str, object],
) -> None:
    width, height = viewport
    browser_context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
    page = browser_context.new_page()
    attach_diagnostics(page, report)
    add_session(page, context, token)
    page.goto(
        f"{base_url}/learn?conversation_id={context['conversation_id']}&course_id={context['course_id']}",
        wait_until="networkidle",
    )
    article = page.locator(f'[data-message-id="{context["message_id"]}"]')
    article.wait_for(state="visible", timeout=60_000)
    article.locator(".assistant-label").click()
    workflow = article.locator("details.message-workflow")
    workflow.wait_for(state="attached")
    if workflow.get_attribute("open") is None:
        workflow.locator("summary").click()
    inline_timeline = workflow.get_by_test_id("agent-audit-timeline")
    inline_timeline.wait_for(state="visible")
    inline_result = assert_terminal_timeline(inline_timeline, "message timeline")

    page.get_by_test_id("chat-evidence-toggle").click()
    inspector = page.get_by_test_id("chat-agent-audit").get_by_test_id("agent-audit-timeline")
    inspector.wait_for(state="visible")
    inspector_result = assert_terminal_timeline(inspector, "inspector timeline")
    inline_timeline.scroll_into_view_if_needed()
    screenshot = OUTPUT_DIR / f"{width}x{height}-terminal-resource-trace.png"
    page.screenshot(path=screenshot, full_page=False)
    report["screenshots"].append(str(screenshot))
    report["view_results"].append({
        "viewport": [width, height],
        "inline": inline_result,
        "inspector": inspector_result,
    })
    browser_context.close()


def run() -> dict[str, object]:
    backup_database()
    context = target_context()
    token = access_token(context)
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = None
    report: dict[str, object] = {
        "schema_version": "chat-resource-trace-terminal.browser.v1",
        "status": "running",
        "source_message_id": context["message_id"],
        "resource_status": "partial_success",
        "failed_types": json.loads(context["failed_types"]),
        "screenshots": [],
        "view_results": [],
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
    }
    try:
        process = start_service(port)
        wait_for_service(base_url)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for viewport in ((1440, 900), (1366, 768)):
                verify_viewport(browser, base_url, context, token, viewport, report)
            browser.close()

        with sqlite3.connect(ISOLATED_DB) as db:
            row = db.execute(
                "SELECT stream_checkpoint FROM chat_messages WHERE id=?",
                (context["message_id"],),
            ).fetchone()
            foreign_key_violations = len(db.execute("PRAGMA foreign_key_check").fetchall())
            report["database"] = {
                "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
                "foreign_key_violations_before": int(context["foreign_key_violations"]),
                "foreign_key_violations_after": foreign_key_violations,
                "new_foreign_key_violations": foreign_key_violations - int(context["foreign_key_violations"]),
                "target_message_unchanged": json.dumps(
                    json.loads(row[0] or "{}"), ensure_ascii=False, sort_keys=True
                ) == context["checkpoint"],
            }
        assert report["database"]["integrity"] == "ok"
        assert report["database"]["new_foreign_key_violations"] == 0
        assert report["database"]["target_message_unchanged"] is True
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        stop_service(process)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "browser_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
