"""Verify the reusable two-template interactive lab in real Chromium."""

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
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-MEDIA-05" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_interactive_lab_e2e.db"
EVIDENCE_DB = OUTPUT / "interactive_lab_evidence.db"
PORT = 8792
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-interactive-lab-2026!"


def wait_port(open_: bool, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_: return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} state timeout")


def stop(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None: return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired: pass
    wait_port(False, 15)


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"; page.screenshot(path=str(path), full_page=True); return path.name


def digest(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file(): path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists(): path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH), "EDUMATRIX_AUTH_SECRET_KEY": "next-interactive-lab-e2e-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "", "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "", "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled", "EDUMATRIX_HOST": "127.0.0.1", "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {"schema_version": "next.interactive-lab-e2e.v1", "checks": {}, "screenshots": [],
                              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
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
                    owner_name, other_name = f"lab_owner_{suffix}", f"lab_other_{suffix}"
                    owner = page.request.post(f"{BASE_URL}/api/auth/register", data={"username": owner_name, "password": PASSWORD, "display_name": "虚拟实验用户"})
                    other = page.request.post(f"{BASE_URL}/api/auth/register", data={"username": other_name, "password": PASSWORD, "display_name": "隔离用户"})
                    assert owner.ok and other.ok
                    owner_token, other_token = owner.json()["access_token"], other.json()["access_token"]
                    owner_headers, other_headers = {"Authorization": f"Bearer {owner_token}"}, {"Authorization": f"Bearer {other_token}"}
                    media = page.request.post(f"{BASE_URL}/api/v1/media-context/resources", headers=owner_headers, data={
                        "resource_type": "video", "title": "阈值校准讲解", "course_id": None, "language": "",
                        "locator": "/media/calibration.mp4", "content": "", "duration_ms": 120000,
                    })
                    assert media.ok
                    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
                    page.evaluate("""([token, username]) => { localStorage.setItem('edumatrix_token',token); localStorage.setItem('edumatrix_role','student'); localStorage.setItem('edumatrix_username',username); localStorage.setItem('edumatrix_student_id',username); localStorage.setItem('edumatrix_display_name','虚拟实验用户'); localStorage.setItem('edumatrix_onboarded','true') }""", [owner_token, owner_name])
                    page.goto(f"{BASE_URL}/interactive-lab", wait_until="domcontentloaded", timeout=30000)
                    workspace = page.get_by_test_id("interactive-lab-workspace"); workspace.wait_for(state="visible", timeout=30000)
                    cards = page.get_by_test_id("lab-template-list").locator("button")
                    assert cards.count() == 2
                    cards.filter(has_text="分类阈值校准实验").click()
                    page.get_by_label("联动媒体资源").select_option(media.json()["id"])
                    page.get_by_role("slider", name="决策阈值").fill("0.55")
                    page.get_by_role("slider", name="拒判区间").fill("0.1")
                    page.get_by_role("spinbutton", name="校准分桶").fill("12")
                    page.get_by_role("button", name="创建实验").click()
                    page.get_by_test_id("lab-instance").wait_for(state="visible", timeout=30000)
                    page.get_by_role("button", name="运行实验").click()
                    results = page.get_by_test_id("lab-results"); results.wait_for(state="visible", timeout=30000)
                    assert "平衡准确率" in results.inner_text() and "校准误差" in results.inner_text()
                    page.get_by_role("button", name="隐藏验收").click()
                    acceptance = page.get_by_test_id("lab-acceptance"); acceptance.wait_for(state="visible")
                    assert "隐藏验收通过" in acceptance.inner_text() and "未暴露隐藏期望值" in acceptance.inner_text()
                    report["screenshots"].append(shot(page, "01-classifier-hidden-acceptance"))

                    instances = page.request.get(f"{BASE_URL}/api/v1/interactive-lab/instances", headers=owner_headers).json()["items"]
                    classifier = instances[0]
                    assert classifier["linked_media_resource_id"] == media.json()["id"]
                    forbidden = [
                        page.request.get(f"{BASE_URL}/api/v1/interactive-lab/instances/{classifier['instance_id']}", headers=other_headers),
                        page.request.post(f"{BASE_URL}/api/v1/interactive-lab/instances/{classifier['instance_id']}/actions", headers=other_headers,
                                          data={"action":"reset","parameters":None,"expected_version":classifier["version_number"],"idempotency_key":"other-reset"}),
                        page.request.post(f"{BASE_URL}/api/v1/interactive-lab/instances", headers=other_headers, data={
                            "template_id":"classifier-threshold-calibration","title":"stolen","parameters":{"decision_threshold":0.55,"abstain_margin":0.1,"calibration_bins":12},
                            "linked_media_resource_id":media.json()["id"],"idempotency_key":"other-media-link"}),
                    ]
                    assert [item.status for item in forbidden] == [403, 403, 403]
                    report["checks"]["cross_owner"] = [item.status for item in forbidden]

                    page.reload(wait_until="domcontentloaded", timeout=30000)
                    acceptance = page.get_by_test_id("lab-acceptance"); acceptance.wait_for(state="visible", timeout=30000)
                    assert "隐藏验收通过" in acceptance.inner_text()
                    assert page.get_by_label("联动媒体资源").input_value() == media.json()["id"]
                    report["checks"]["refresh_recovery"] = {"status":"passed","media_link":True}

                    page.get_by_test_id("lab-template-list").locator("button").filter(has_text="混合检索调优实验").click()
                    page.get_by_role("spinbutton", name="召回数量").fill("5")
                    page.get_by_role("slider", name="关键词权重").fill("0.4")
                    page.get_by_role("slider", name="向量权重").fill("0.6")
                    page.get_by_role("slider", name="重排阈值").fill("0.55")
                    page.get_by_role("button", name="创建实验").click()
                    page.get_by_role("button", name="运行实验").click()
                    page.get_by_role("button", name="隐藏验收").click()
                    assert "隐藏验收通过" in page.get_by_test_id("lab-acceptance").inner_text()
                    report["checks"]["two_templates"] = ["classifier-threshold-calibration", "rag-hybrid-tuning"]

                    page.set_viewport_size({"width":390,"height":844}); page.wait_for_timeout(300)
                    geometry = page.evaluate("""() => { const box=document.querySelector('[data-testid="interactive-lab-workspace"]')?.getBoundingClientRect(); return {viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,panel:box?{x:box.x,right:box.right,width:box.width}:null} }""")
                    assert geometry["documentWidth"] <= geometry["viewport"] + 1
                    assert geometry["panel"] and geometry["panel"]["x"] >= 0 and geometry["panel"]["right"] <= 391
                    report["checks"]["mobile_viewport"] = geometry
                    report["screenshots"].append(shot(page, "02-mobile-rag-lab")); report["result"] = "passed"
                except Exception:
                    try: report["screenshots"].append(shot(page, "error"))
                    except Exception: pass
                    raise
                finally: context.close(); browser.close()
    except Exception as exc:
        report["result"] = "failed"; report["error"] = f"{type(exc).__name__}: {exc}"; raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z"); stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target); report["checks"]["sqlite_integrity"] = target.execute("pragma integrity_check").fetchone()[0]
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        files=[{"file":p.name,"bytes":p.stat().st_size,"sha256":digest(p)} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name!="manifest.json" and not p.name.endswith(("-wal","-shm"))]
        (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version":"next.interactive-lab-manifest.v1","files":files},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
