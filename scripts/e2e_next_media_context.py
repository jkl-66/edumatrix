"""Verify resource-bound code/video positions and conversations in Chromium."""

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
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-MEDIA-04" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_media_context_e2e.db"
EVIDENCE_DB = OUTPUT / "media_context_evidence.db"
PORT = 8791
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-media-context-2026!"


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
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired: pass
    wait_port(False, 15)


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path.name


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file(): path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists(): path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH), "EDUMATRIX_AUTH_SECRET_KEY": "next-media-context-e2e-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0", "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_HOST": "127.0.0.1", "EDUMATRIX_PORT": str(PORT), "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {"schema_version": "next.media-context-e2e.v1", "checks": {}, "screenshots": [], "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
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
                    suffix = str(int(time.time()))
                    owner_name, other_name = f"media_ctx_owner_{suffix}", f"media_ctx_other_{suffix}"
                    owner = page.request.post(f"{BASE_URL}/api/auth/register", data={"username": owner_name, "password": PASSWORD, "display_name": "媒体上下文用户"})
                    other = page.request.post(f"{BASE_URL}/api/auth/register", data={"username": other_name, "password": PASSWORD, "display_name": "媒体隔离用户"})
                    assert owner.ok and other.ok
                    owner_token, other_token = owner.json()["access_token"], other.json()["access_token"]
                    owner_headers, other_headers = {"Authorization": f"Bearer {owner_token}"}, {"Authorization": f"Bearer {other_token}"}
                    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
                    page.evaluate("""([token, username]) => { localStorage.setItem('edumatrix_token', token); localStorage.setItem('edumatrix_role','student'); localStorage.setItem('edumatrix_username',username); localStorage.setItem('edumatrix_student_id',username); localStorage.setItem('edumatrix_display_name','媒体上下文用户'); localStorage.setItem('edumatrix_onboarded','true') }""", [owner_token, owner_name])
                    page.goto(f"{BASE_URL}/media-context", wait_until="domcontentloaded", timeout=30_000)
                    workspace = page.get_by_test_id("media-context-workspace")
                    workspace.wait_for(state="visible", timeout=30_000)
                    form = page.get_by_test_id("media-resource-form")
                    form.get_by_label("标题").fill("RAG reranker lab")
                    form.get_by_label("代码正文").fill("def rank(items):\n    scored = sorted(items)\n    return scored\nprint(rank([3, 1, 2]))\n")
                    form.get_by_role("button", name="固化资源").click()
                    code_card = page.get_by_test_id("media-resource").filter(has_text="RAG reranker lab")
                    code_card.wait_for(state="visible", timeout=30_000)
                    controls = page.get_by_test_id("media-position-controls")
                    controls.get_by_label("定位行").fill("4")
                    controls.get_by_label("阅读进度").fill("0.8")
                    controls.get_by_role("button", name="保存位置").click()
                    page.get_by_text("当前位置已保存。").wait_for(state="visible")
                    conversation = page.get_by_test_id("media-conversation-panel")
                    conversation.get_by_placeholder("记录当前代码行或视频时间点的问题。").fill("Line 4 verifies the sorted output.")
                    conversation.get_by_role("button", name="追加消息").click()
                    conversation.get_by_text("Line 4 verifies the sorted output.").wait_for(state="visible")
                    assert "记录于第 4 行" in conversation.inner_text()
                    report["screenshots"].append(shot(page, "01-code-position-conversation"))

                    form.get_by_label("类型").select_option("video")
                    form.get_by_label("标题").fill("Vector search walkthrough")
                    form.get_by_label("本地路径或 HTTPS URL").fill("")
                    form.get_by_label("时长（毫秒）").fill("180000")
                    form.get_by_role("button", name="固化资源").click()
                    video_card = page.get_by_test_id("media-resource").filter(has_text="Vector search walkthrough")
                    video_card.wait_for(state="visible", timeout=30_000)
                    assert "不宣称播放成功" in page.get_by_test_id("video-reader").inner_text()
                    controls = page.get_by_test_id("media-position-controls")
                    controls.get_by_label("毫秒位置").fill("42500")
                    controls.get_by_label("阅读进度").fill("0.24")
                    controls.get_by_role("button", name="保存位置").click()
                    page.get_by_text("当前位置已保存。").wait_for(state="visible")

                    code_card.click()
                    page.get_by_test_id("code-reader").wait_for(state="visible")
                    assert page.get_by_test_id("media-position-controls").get_by_label("定位行").input_value() == "4"
                    assert "Line 4 verifies the sorted output." in page.get_by_test_id("media-conversation-panel").inner_text()
                    video_card.click()
                    page.get_by_test_id("video-reader").wait_for(state="visible")
                    assert page.get_by_test_id("media-position-controls").get_by_label("毫秒位置").input_value() == "42500"
                    report["checks"]["resource_switch"] = {"code_line": 4, "video_ms": 42500, "conversation_restored": True}

                    listing = page.request.get(f"{BASE_URL}/api/v1/media-context/resources", headers=owner_headers).json()["items"]
                    code = next(item for item in listing if item["title"] == "RAG reranker lab")
                    video = next(item for item in listing if item["title"] == "Vector search walkthrough")
                    conversation_id = code["conversations"][0]["id"]
                    denied = [
                        page.request.get(f"{BASE_URL}/api/v1/media-context/resources/{code['id']}", headers=other_headers),
                        page.request.put(f"{BASE_URL}/api/v1/media-context/resources/{code['id']}/position", headers=other_headers, data={"expected_lock_version":2,"line_number":1,"column_number":1,"playback_ms":0,"scroll_ratio":0}),
                        page.request.post(f"{BASE_URL}/api/v1/media-context/resources/{code['id']}/conversations", headers=other_headers, data={"title":"denied"}),
                        page.request.get(f"{BASE_URL}/api/v1/media-context/conversations/{conversation_id}", headers=other_headers),
                        page.request.post(f"{BASE_URL}/api/v1/media-context/conversations/{conversation_id}/messages", headers=other_headers, data={"expected_lock_version":2,"role":"note","content":"denied"}),
                        page.request.post(f"{BASE_URL}/api/v1/media-context/conversations/{conversation_id}/archive", headers=other_headers, data={"expected_lock_version":2}),
                    ]
                    assert [item.status for item in denied] == [403] * 6
                    report["checks"]["cross_owner"] = [item.status for item in denied]

                    page.reload(wait_until="domcontentloaded", timeout=30_000)
                    page.get_by_test_id("media-reader").wait_for(state="visible", timeout=30_000)
                    video_card = page.get_by_test_id("media-resource").filter(has_text="Vector search walkthrough")
                    video_card.click()
                    assert page.get_by_test_id("media-position-controls").get_by_label("毫秒位置").input_value() == "42500"
                    report["checks"]["refresh_recovery"] = True

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(300)
                    geometry = page.evaluate("""() => { const box=document.querySelector('[data-testid="media-context-workspace"]')?.getBoundingClientRect(); return {viewport:innerWidth, documentWidth:document.documentElement.scrollWidth, panel:box?{x:box.x,right:box.right,width:box.width}:null} }""")
                    assert geometry["documentWidth"] <= geometry["viewport"] + 1
                    assert geometry["panel"] and geometry["panel"]["x"] >= 0 and geometry["panel"]["right"] <= 391
                    report["checks"]["mobile_viewport"] = geometry
                    report["screenshots"].append(shot(page, "02-mobile-media-context"))
                    report["result"] = "passed"
                except Exception:
                    try: report["screenshots"].append(shot(page, "error"))
                    except Exception: pass
                    raise
                finally:
                    context.close(); browser.close()
    except Exception as exc:
        report["result"] = "failed"; report["error"] = f"{type(exc).__name__}: {exc}"; raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z"); stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target); report["checks"]["sqlite_integrity"] = target.execute("pragma integrity_check").fetchone()[0]
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)} for path in sorted(OUTPUT.iterdir()) if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))]
        (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version":"next.media-context-manifest.v1","files":files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
