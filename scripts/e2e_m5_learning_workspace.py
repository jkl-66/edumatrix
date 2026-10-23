"""Run the M5 planning workspace golden journey against an isolated database."""

from __future__ import annotations

import json
import hashlib
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "M5_完全体核心学习平台" / "evidence" / "learning-workspace-e2e-20260802"
DB_PATH = ROOT / "outputs" / "_m5_workspace_e2e_runtime.db"
EVIDENCE_DB = OUTPUT / "m5_workspace_evidence.db"
BASE_URL = "http://127.0.0.1:8766"
PASSWORD = "M5-workspace-e2e-2026!"


def wait_port(open_: bool, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", 8766)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port 8766 did not become {'open' if open_ else 'closed'}")


def stop(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True, text=True, timeout=15,
    )
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, timeout=15)


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path.name


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest() -> None:
    files = []
    for path in sorted(OUTPUT.iterdir()):
        if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm")):
            files.append({"file": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    (OUTPUT / "manifest.json").write_text(
        json.dumps({"schema_version": "m5.workspace-e2e-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def unlink_with_retry(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while path.exists():
        try:
            path.unlink()
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.1)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.glob("*"):
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        unlink_with_retry(Path(f"{DB_PATH}{suffix}"))
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "m5-workspace-e2e-isolated-secret-2026",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": "8766",
        "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {
        "scope": "M5 plan confirmation, path, today work, event evidence, and refresh recovery",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "isolated_database": str(EVIDENCE_DB.relative_to(ROOT)).replace("\\", "/"),
        "checks": {},
        "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page()
                try:
                    username = f"m5_workspace_{int(time.time())}"
                    registration = page.request.post(
                        f"{BASE_URL}/api/auth/register",
                        data={"username": username, "password": PASSWORD, "display_name": "M5 计划验收学生"},
                    )
                    assert registration.ok, registration.text()
                    identity = registration.json()
                    token = identity["access_token"]
                    headers = auth_headers(token)
                    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                    page.evaluate(
                        "([token, username]) => { localStorage.setItem('edumatrix_token', token); localStorage.setItem('edumatrix_role', 'student'); localStorage.setItem('edumatrix_username', username); localStorage.setItem('edumatrix_display_name', 'M5 计划验收学生'); localStorage.setItem('edumatrix_onboarded', 'true') }",
                        [token, username],
                    )
                    page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
                    page.get_by_text("创建学习计划").wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "01-empty-workspace"))

                    page.get_by_label("计划名称").fill("RAG 实训闭环计划")
                    page.get_by_label("学习目标").fill("完成一项可验证的 RAG 工程学习任务")
                    course_select = page.locator("form.editor .fields select")
                    course_select.select_option(index=1)
                    object_select = page.locator(".node-fields select")
                    object_select.select_option(index=1)
                    page.get_by_role("button", name="保存草稿").click()
                    page.get_by_text("草稿已保存，尚未创建正式学习路径。").wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "02-draft-saved-no-path"))

                    plans = page.request.get(f"{BASE_URL}/api/v1/m5/plans", headers=headers).json()["items"]
                    paths_before = page.request.get(f"{BASE_URL}/api/v1/m5/paths", headers=headers).json()["items"]
                    assert len(plans) == 1 and paths_before == [], (plans, paths_before)
                    report["checks"]["draft_confirmation_gate"] = {"plans": 1, "paths_before_confirmation": 0}

                    page.once("dialog", lambda dialog: dialog.accept())
                    page.get_by_role("button", name="确认并生效").click()
                    page.get_by_text("计划已确认，正式路径已生效。").wait_for(state="visible", timeout=20_000)
                    page.get_by_text("0/1 节点完成", exact=True).wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "03-confirmed-active-path"))

                    assert page.get_by_role("button", name="提交复测通过").count() == 0
                    page.get_by_role("button", name="记录学习活动").click()
                    page.get_by_text("学习活动已记录，不影响掌握度。").wait_for(state="visible", timeout=20_000)
                    paths_after_open = page.request.get(f"{BASE_URL}/api/v1/m5/paths", headers=headers).json()["items"]
                    assert paths_after_open[0]["nodes"][0]["status"] == "in_progress"
                    events_after_open = page.request.get(
                        f"{BASE_URL}/api/v1/m5/learning-events", headers=headers,
                    ).json()["items"]
                    assert events_after_open[0]["evidence_status"] == "none"
                    assert events_after_open[0]["mastery_eligible"] is False
                    report["checks"]["browser_activity"] = {
                        "node_status": "in_progress",
                        "evidence_status": "none",
                        "mastery_eligible": False,
                    }

                    node = paths_after_open[0]["nodes"][0]
                    forged = page.request.post(
                        f"{BASE_URL}/api/v1/m5/learning-events",
                        headers=headers,
                        data={
                            "idempotency_key": "e2e-forged-retest-001",
                            "event_type": "delayed_retest_passed",
                            "context": {
                                "courseId": paths_after_open[0]["course_id"],
                                "taskId": node["id"],
                            },
                            "course_id": paths_after_open[0]["course_id"],
                            "object_type": node["node_type"],
                            "object_id": node["target_object_id"],
                            "source": "backend",
                            "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "payload": {
                                "correct": True,
                                "delay_hours": 24,
                                "attempt_id": "forged-attempt",
                            },
                        },
                    )
                    assert forged.ok, forged.text()
                    forged_event = forged.json()
                    assert forged_event["source"] == "frontend"
                    assert forged_event["evidence_status"] == "rejected"
                    assert forged_event["mastery_eligible"] is False
                    paths_after_forgery = page.request.get(
                        f"{BASE_URL}/api/v1/m5/paths", headers=headers,
                    ).json()["items"]
                    assert paths_after_forgery[0]["status"] == "active"
                    assert paths_after_forgery[0]["nodes"][0]["status"] == "in_progress"
                    report["checks"]["forged_strong_evidence"] = {
                        "evidence_status": "rejected",
                        "path_status": "active",
                        "node_status": "in_progress",
                    }

                    page.reload(wait_until="networkidle")
                    page.get_by_text("active", exact=True).first.wait_for(state="visible", timeout=20_000)
                    assert page.locator(".timeline article.in_progress").count() == 1
                    report["checks"]["refresh_recovery"] = True
                    report["screenshots"].append(shot(page, "04-evidence-protocol-refresh-recovered"))
                    page.set_viewport_size({"width": 1366, "height": 768})
                    page.reload(wait_until="networkidle")
                    page.locator(".path-summary strong").wait_for(state="visible", timeout=20_000)
                    assert page.locator(".path-summary strong").inner_text().strip().lower() == "active"
                    assert page.locator(".timeline article.in_progress").count() == 1
                    report["checks"]["desktop_viewports"] = [
                        {"width": 1440, "height": 900},
                        {"width": 1366, "height": 768},
                    ]
                    report["screenshots"].append(shot(page, "05-desktop-1366x768"))
                    report["result"] = "passed"
                except Exception:
                    try:
                        report["screenshots"].append(shot(page, "error"))
                    except Exception:
                        pass
                    raise
                finally:
                    context.close()
                    browser.close()
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        stop(backend)
        backend = None
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as destination:
                source.backup(destination)
                integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
            report["checks"]["sqlite_integrity"] = integrity
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
