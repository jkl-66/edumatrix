"""Verify FC3-04A artifacts, planning, close reading, flashcards and media recovery."""

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
OUTPUT = ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC3-04A" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_fc3_artifacts_workspace_e2e.db"
EVIDENCE_DB = OUTPUT / "fc3_artifacts_workspace_evidence.db"
PORT = 8830
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC3-artifacts-workspace-2026!"


def wait_port(open_: bool, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} state timeout")


def stop(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, 15)


def shot(page: Page, name: str, *, full_page: bool = True) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
    return path.name


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def register(page: Page, username: str, display_name: str) -> str:
    response = page.request.post(f"{BASE_URL}/api/auth/register", data={
        "username": username, "password": PASSWORD, "display_name": display_name,
    })
    assert response.ok, response.text()
    return response.json()["access_token"]


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "fc3-artifacts-workspace-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled", "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT), "PYTHONUNBUFFERED": "1", "PYTHON_DOTENV_DISABLED": "1",
    })
    report: dict[str, Any] = {
        "schema_version": "fc3.artifacts-learning-workspace-e2e.v1",
        "scope": "plan/today work, source-bound close reading, canonical flashcards, media position, navigation, refresh, owner isolation and mobile",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": {}, "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    stamp = str(int(time.time()))
                    owner_name, other_name = f"fc3_workspace_owner_{stamp}", f"fc3_workspace_other_{stamp}"
                    owner_token = register(page, owner_name, "FC3 学习工作台学生")
                    other_token = register(page, other_name, "FC3 越权检查学生")
                    owner_headers = {"Authorization": f"Bearer {owner_token}"}
                    other_headers = {"Authorization": f"Bearer {other_token}"}
                    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
                    page.evaluate("""([token, username]) => {
                      localStorage.setItem('edumatrix_token', token); localStorage.setItem('edumatrix_role','student');
                      localStorage.setItem('edumatrix_username',username); localStorage.setItem('edumatrix_student_id',username);
                      localStorage.setItem('edumatrix_display_name','FC3 学习工作台学生'); localStorage.setItem('edumatrix_onboarded','true');
                    }""", [owner_token, owner_name])

                    # Plan draft -> confirmed path -> today task.
                    page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
                    page.get_by_text("创建学习计划").wait_for(state="visible", timeout=30_000)
                    page.get_by_label("计划名称").fill("FC3 可恢复精读计划")
                    page.get_by_label("学习目标").fill("完成来源绑定精读并形成可验证学习任务")
                    page.get_by_label("课程").select_option(index=1)
                    page.locator(".node-fields select").select_option(index=1)
                    page.get_by_role("button", name="保存草稿").click()
                    page.get_by_text("草稿已保存，尚未创建正式学习路径。").wait_for(state="visible", timeout=20_000)
                    page.once("dialog", lambda dialog: dialog.accept())
                    page.get_by_role("button", name="确认并生效").click()
                    page.get_by_text("计划已确认，正式路径已生效。").wait_for(state="visible", timeout=20_000)
                    today = page.request.get(f"{BASE_URL}/api/v1/m5/today", headers=owner_headers)
                    assert today.ok and len(today.json()["items"]) == 1
                    report["checks"]["plan_path_today"] = {"today_items": 1, "node_status": today.json()["items"][0]["status"]}
                    report["screenshots"].append(shot(page, "01-plan-path-today"))

                    # Source-bound close-reading context and refresh recovery.
                    page.goto(f"{BASE_URL}/tutor-workspace", wait_until="networkidle")
                    page.get_by_text("上下文教师工作台", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_label("课程", exact=True).select_option("course-rag-engineering-m0")
                    page.wait_for_function('() => document.querySelector(\'[aria-label="当前资源"]\')?.options.length > 1', timeout=20_000)
                    page.get_by_label("教学风格").select_option("close_reading")
                    page.get_by_label("讲解深度").select_option("deep")
                    page.get_by_role("button", name="创建可恢复上下文").click()
                    page.get_by_text("上下文已冻结并保存。当前没有调用模型。", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_label("你的问题").fill("请精读当前段落并指出可靠检索的关键约束。")
                    page.get_by_role("button", name="执行调用前检查").click()
                    page.get_by_test_id("preflight-result").wait_for(state="visible", timeout=20_000)
                    contexts = page.request.get(f"{BASE_URL}/api/v1/m5/tutor-contexts", headers=owner_headers).json()["items"]
                    assert len(contexts) == 1 and contexts[0]["teaching_style"] == "close_reading"
                    context_id = contexts[0]["id"]
                    assert page.request.get(f"{BASE_URL}/api/v1/m5/tutor-contexts/{context_id}", headers=other_headers).status == 403
                    page.reload(wait_until="networkidle")
                    page.locator(".snapshot h3").wait_for(state="visible", timeout=20_000)
                    report["checks"]["close_reading"] = {"context_id": context_id, "source_count": len(contexts[0]["context"]["sources"]), "other_read": 403, "refresh": True}
                    report["screenshots"].append(shot(page, "02-close-reading-recovered"))

                    # Create a review plan through the public API, then use the canonical card in UI.
                    created_plan = page.request.post(f"{BASE_URL}/api/review/{owner_name}", headers=owner_headers, data={
                        "concept": "检索证据边界", "mastery": 0.3, "interval_days": 1,
                    })
                    assert created_plan.ok, created_plan.text()
                    page.goto(f"{BASE_URL}/review", wait_until="networkidle")
                    card = page.get_by_test_id("canonical-flashcard")
                    card.wait_for(state="visible", timeout=20_000)
                    card_id = page.request.get(f"{BASE_URL}/api/flashcard/all", headers=owner_headers, params={"student_id": owner_name}).json()["cards"][0]["id"]
                    card.locator(".anki-card-front").click()
                    card.get_by_role("button", name="一般").click()
                    page.get_by_text("闪卡复习已记录，调度与卡片版本均已恢复。").wait_for(state="visible", timeout=20_000)
                    assert page.request.post(f"{BASE_URL}/api/flashcard/review", headers=other_headers, data={"student_id": other_name, "concept": "检索证据边界", "card_id": card_id, "quality": 4}).status == 403
                    page.reload(wait_until="networkidle")
                    page.get_by_test_id("canonical-flashcard").wait_for(state="visible", timeout=20_000)
                    recovered_card = page.request.get(f"{BASE_URL}/api/flashcard/all", headers=owner_headers, params={"student_id": owner_name}).json()["cards"][0]
                    assert recovered_card["id"] == card_id and recovered_card["review_count"] == 1
                    report["checks"]["canonical_flashcard"] = {"card_id": card_id, "version_id": recovered_card["version_id"], "review_count": 1, "other_review": 403, "refresh": True}
                    report["screenshots"].append(shot(page, "03-canonical-flashcard-recovered"))

                    # Real media object and position, then formal workspace recovery.
                    media = page.request.post(f"{BASE_URL}/api/v1/media-context/resources", headers=owner_headers, data={
                        "resource_type": "code", "title": "FC3 精读代码", "content": "line1\nline2\nline3\nline4", "language": "python",
                    })
                    assert media.ok, media.text()
                    resource = media.json()
                    position = page.request.put(f"{BASE_URL}/api/v1/media-context/resources/{resource['id']}/position", headers=owner_headers, data={
                        "expected_lock_version": resource["position"]["lock_version"], "line_number": 4,
                        "column_number": 1, "playback_ms": 0, "scroll_ratio": 0.8,
                    })
                    assert position.ok, position.text()
                    assert page.request.get(f"{BASE_URL}/api/v1/media-context/resources/{resource['id']}", headers=other_headers).status == 403
                    page.goto(f"{BASE_URL}/media-context", wait_until="networkidle")
                    page.get_by_test_id("media-context-workspace").wait_for(state="visible", timeout=20_000)
                    assert page.get_by_test_id("media-position-controls").get_by_label("定位行").input_value() == "4"
                    report["checks"]["media_position"] = {"resource_id": resource["id"], "line": 4, "other_read": 403, "refresh": True}

                    # Navigation discoverability and mobile geometry.
                    nav_text = page.locator(".app-sidebar").inner_text()
                    for label in ("计划工作台", "上下文教师", "学习路径", "学习笔记", "学习资源包", "媒体上下文"):
                        assert label in nav_text
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.reload(wait_until="networkidle")
                    workspace = page.get_by_test_id("media-context-workspace")
                    workspace.wait_for(state="visible", timeout=20_000)
                    geometry = page.evaluate("() => ({viewport: innerWidth, documentWidth: document.documentElement.scrollWidth})")
                    assert geometry["documentWidth"] <= geometry["viewport"] + 1
                    report["checks"]["navigation_and_mobile"] = {"labels": 6, **geometry}
                    report["screenshots"].append(shot(page, "04-mobile-media-position"))
                    report["result"] = "passed"
                except Exception:
                    try:
                        report["screenshots"].append(shot(page, "error"))
                    except Exception:
                        pass
                    raise
                finally:
                    context.close(); browser.close()
    except Exception as exc:
        report["result"] = "failed"; report["error"] = f"{type(exc).__name__}: {exc}"; raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target); report["checks"]["sqlite_integrity"] = target.execute("PRAGMA integrity_check").fetchone()[0]
                report["checks"]["database_counts"] = {
                    "flashcards": target.execute("SELECT COUNT(*) FROM flashcards").fetchone()[0],
                    "flashcard_versions": target.execute("SELECT COUNT(*) FROM flashcard_versions").fetchone()[0],
                    "plan_drafts": target.execute("SELECT COUNT(*) FROM plan_drafts").fetchone()[0],
                    "tutor_contexts": target.execute("SELECT COUNT(*) FROM tutor_context_sessions").fetchone()[0],
                    "media_resources": target.execute("SELECT COUNT(*) FROM media_context_resources").fetchone()[0],
                }
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{"file": p.name, "bytes": p.stat().st_size, "sha256": digest(p)} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name != "manifest.json" and not p.name.endswith(("-wal", "-shm"))]
        (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version": "fc3.artifacts-learning-workspace-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
