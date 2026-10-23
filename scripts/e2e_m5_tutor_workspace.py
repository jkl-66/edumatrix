"""Verify the source-bound M5 tutor workspace against an isolated database."""

from __future__ import annotations

import hashlib
import json
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
OUTPUT = ROOT / "outputs" / "M5_完全体核心学习平台" / "evidence" / "tutor-workspace-e2e-20260802"
DB_PATH = ROOT / "outputs" / "_m5_tutor_workspace_e2e_runtime.db"
EVIDENCE_DB = OUTPUT / "m5_tutor_workspace_evidence.db"
BASE_URL = "http://127.0.0.1:8768"
PASSWORD = "M5-tutor-workspace-e2e-2026!"


def wait_port(open_: bool, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", 8768)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port 8768 did not become {'open' if open_ else 'closed'}")


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


def shot(page: Page, name: str, *, full_page: bool = False) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
    return path.name


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_manifest() -> None:
    files = [
        {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
    ]
    (OUTPUT / "manifest.json").write_text(
        json.dumps({"schema_version": "m5.tutor-workspace-e2e-manifest.v1", "files": files},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def unlink(path: Path) -> None:
    if path.exists():
        path.unlink()


def register(page: Page, username: str, display_name: str) -> str:
    response = page.request.post(
        f"{BASE_URL}/api/auth/register",
        data={"username": username, "password": PASSWORD, "display_name": display_name},
    )
    assert response.ok, response.text()
    return response.json()["access_token"]


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        unlink(Path(f"{DB_PATH}{suffix}"))
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "m5-tutor-e2e-isolated-secret-2026",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": "8768",
        "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {
        "scope": "M0 course selection, source-bound tutor context, preflight truthfulness, refresh recovery, mobile UI, and owner isolation",
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
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    stamp = int(time.time())
                    owner_name = f"m5_tutor_owner_{stamp}"
                    other_name = f"m5_tutor_other_{stamp}"
                    owner_token = register(page, owner_name, "M5 上下文教师验收学生")
                    other_token = register(page, other_name, "M5 隔离检查学生")
                    owner_headers = {"Authorization": f"Bearer {owner_token}"}
                    other_headers = {"Authorization": f"Bearer {other_token}"}

                    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'student')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_display_name', 'M5 上下文教师验收学生')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [owner_token, owner_name],
                    )
                    page.goto(f"{BASE_URL}/tutor-workspace", wait_until="networkidle")
                    page.get_by_text("上下文教师工作台", exact=True).wait_for(state="visible", timeout=20_000)
                    course = page.get_by_label("课程", exact=True)
                    course.select_option("course-rag-engineering-m0")
                    page.wait_for_function(
                        '() => document.querySelector(\'[aria-label="当前资源"]\')?.options.length > 1',
                        timeout=20_000,
                    )
                    page.get_by_label("教学风格").select_option("close_reading")
                    page.get_by_label("讲解深度").select_option("deep")
                    page.get_by_label("引导模式").select_option("socratic")
                    page.locator(".source-check").first.wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "01-m0-course-source-selection", full_page=True))

                    page.get_by_role("button", name="创建可恢复上下文").click()
                    page.get_by_text("上下文已冻结并保存。当前没有调用模型。", exact=True).wait_for(
                        state="visible", timeout=20_000,
                    )
                    page.locator(".sources article").first.wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page, "02-source-bound-context", full_page=True))

                    owner_contexts = page.request.get(
                        f"{BASE_URL}/api/v1/m5/tutor-contexts", headers=owner_headers,
                    ).json()["items"]
                    assert len(owner_contexts) == 1
                    tutor_context = owner_contexts[0]
                    source = tutor_context["context"]["sources"][0]
                    assert source["quote"] and len(source["content_hash"]) == 64
                    report["checks"]["source_binding"] = {
                        "course_id": tutor_context["course_id"],
                        "context_id": tutor_context["id"],
                        "source_ref_id": source["source_ref_id"],
                        "content_hash": source["content_hash"],
                    }

                    page.get_by_label("你的问题").fill("请精读当前段落，并指出构建可靠检索系统的关键约束。")
                    page.get_by_role("button", name="执行调用前检查").click()
                    page.get_by_test_id("preflight-result").wait_for(state="visible", timeout=20_000)
                    page.get_by_text("未开始", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page, "03-preflight-generation-not-started", full_page=True))
                    report["checks"]["truthful_preflight"] = {
                        "generation_started": False,
                        "external_model_request_sent": False,
                    }

                    page.reload(wait_until="networkidle")
                    page.locator(".snapshot h3").wait_for(state="visible", timeout=20_000)
                    recovered = page.request.get(
                        f"{BASE_URL}/api/v1/m5/tutor-contexts/{tutor_context['id']}", headers=owner_headers,
                    )
                    assert recovered.ok and recovered.json()["id"] == tutor_context["id"]
                    report["checks"]["refresh_recovery"] = True
                    report["screenshots"].append(shot(page, "04-refresh-recovered", full_page=True))

                    assert page.request.get(
                        f"{BASE_URL}/api/v1/m5/tutor-contexts", headers=other_headers,
                    ).json()["items"] == []
                    assert page.request.get(
                        f"{BASE_URL}/api/v1/m5/tutor-contexts/{tutor_context['id']}", headers=other_headers,
                    ).status == 403
                    assert page.request.post(
                        f"{BASE_URL}/api/v1/m5/tutor-contexts/{tutor_context['id']}/preflight",
                        headers=other_headers, data={"question": "Attempt cross-owner access"},
                    ).status == 403
                    assert page.request.post(
                        f"{BASE_URL}/api/v1/m5/tutor-contexts/{tutor_context['id']}/archive",
                        headers=other_headers, data={"expected_lock_version": tutor_context["lock_version"]},
                    ).status == 403
                    report["checks"]["owner_isolation"] = {
                        "list_items_for_other": 0, "read_status": 403,
                        "preflight_status": 403, "archive_status": 403,
                    }

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.reload(wait_until="networkidle")
                    page.locator(".snapshot h3").wait_for(state="visible", timeout=20_000)
                    assert page.locator(".sources article").count() >= 1
                    report["checks"]["mobile_viewport"] = {"width": 390, "height": 844, "source_visible": True}
                    report["screenshots"].append(shot(page, "05-mobile-source-context", full_page=True))
                    report["result"] = "passed"
                except Exception:
                    try:
                        report["screenshots"].append(shot(page, "error", full_page=True))
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
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as destination:
                source.backup(destination)
                report["checks"]["sqlite_integrity"] = destination.execute(
                    "PRAGMA integrity_check",
                ).fetchone()[0]
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
