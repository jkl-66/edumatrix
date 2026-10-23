"""Verify deterministic parameter-driven teaching animations in system Chrome."""

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

from playwright.sync_api import Page, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC1-007" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_fc1_teaching_animation_e2e.db"
EVIDENCE_DB = OUTPUT / "teaching_animation_evidence.db"
PORT = 8817
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC1-teaching-animation-2026!"


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


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path.name


def authenticate(page: Page, token: str, username: str) -> None:
    page.goto(BASE_URL + "/login", wait_until="domcontentloaded")
    page.evaluate(
        """([token, username]) => {
          localStorage.setItem('edumatrix_token', token);
          localStorage.setItem('edumatrix_role', 'student');
          localStorage.setItem('edumatrix_username', username);
          localStorage.setItem('edumatrix_student_id', username);
          localStorage.setItem('edumatrix_display_name', '动画实验用户');
          localStorage.setItem('edumatrix_onboarded', 'true');
        }""",
        [token, username],
    )


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
        "EDUMATRIX_AUTH_SECRET_KEY": "fc1-teaching-animation-e2e-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled", "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT), "PYTHONUNBUFFERED": "1", "PYTHON_DOTENV_DISABLED": "1",
    })
    report: dict[str, Any] = {
        "schema_version": "fc1-007.teaching-animation-browser-e2e.v1",
        "checks": {}, "screenshots": [], "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    stamp = str(int(time.time()))
                    owner_name, outsider_name = f"fc1_animation_owner_{stamp}", f"fc1_animation_outsider_{stamp}"
                    owner = page.request.post(BASE_URL + "/api/auth/register", data={"username": owner_name, "password": PASSWORD, "display_name": "动画实验用户"})
                    outsider = page.request.post(BASE_URL + "/api/auth/register", data={"username": outsider_name, "password": PASSWORD, "display_name": "隔离用户"})
                    assert owner.ok and outsider.ok
                    owner_token, outsider_token = owner.json()["access_token"], outsider.json()["access_token"]
                    owner_headers = {"Authorization": "Bearer " + owner_token}
                    outsider_headers = {"Authorization": "Bearer " + outsider_token}
                    authenticate(page, owner_token, owner_name)
                    page.goto(BASE_URL + "/teaching-animations", wait_until="domcontentloaded")
                    root = page.get_by_test_id("teaching-animation-workspace")
                    root.wait_for(state="visible", timeout=30_000)
                    expect(root.get_by_text("无随机结果 · 无外部模型", exact=True)).to_be_visible()
                    root.get_by_role("button", name="创建动画项目").click()
                    root.get_by_test_id("animation-player").wait_for(state="visible", timeout=30_000)
                    projects = page.request.get(BASE_URL + "/api/v1/teaching-animations", headers=owner_headers).json()["items"]
                    assert len(projects) == 1
                    animation_id = projects[0]["id"]
                    initial = page.request.get(BASE_URL + f"/api/v1/teaching-animations/{animation_id}", headers=owner_headers).json()
                    assert initial["current_version"]["frames"][0]["loss"] == 49.0
                    assert initial["current_version"]["frames"][1]["x"] == 5.9

                    canvas_check = page.locator("canvas").evaluate("""canvas => {
                      const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
                      let nonBackground=0;
                      for(let i=0;i<data.length;i+=4){ if(data[i] < 240 || data[i+1] < 240 || data[i+2] < 240) nonBackground++; }
                      return {width:canvas.width,height:canvas.height,nonBackground};
                    }""")
                    assert canvas_check["nonBackground"] > 500
                    report["checks"]["canvas_pixels"] = canvas_check

                    root.get_by_role("button", name="播放", exact=True).click()
                    page.wait_for_function("() => Number(document.querySelector('[data-testid=frame-counter]').textContent.trim().split('/')[0]) >= 2", timeout=8_000)
                    frame_during_play = int(root.get_by_test_id("frame-counter").inner_text().split("/")[0].strip())
                    assert frame_during_play >= 2
                    root.get_by_role("button", name="暂停", exact=True).click()
                    paused = page.request.get(BASE_URL + f"/api/v1/teaching-animations/{animation_id}", headers=owner_headers).json()
                    assert paused["current_frame"] >= 2 and paused["playback_status"] == "paused"
                    paused_frame = paused["current_frame"]
                    root.get_by_role("button", name="单步", exact=True).click()
                    expect(root.get_by_test_id("frame-counter")).to_contain_text(str(paused_frame + 1), timeout=5_000)
                    stepped = page.request.get(BASE_URL + f"/api/v1/teaching-animations/{animation_id}", headers=owner_headers).json()
                    assert stepped["current_frame"] == paused_frame + 1
                    root.get_by_role("button", name="重置", exact=True).click()
                    expect(root.get_by_test_id("frame-counter")).to_have_text(f"0 / {stepped['max_frame']}", timeout=5_000)
                    report["checks"]["playback"] = {"played_to": frame_during_play, "paused_at": paused_frame, "stepped_to": paused_frame + 1, "reset_to": 0}

                    page.get_by_role("slider", name="学习率").fill("0.1")
                    root.get_by_role("button", name="保存参数版本").click()
                    expect(root.get_by_text("新参数版本已生成，播放位置已重置。", exact=True)).to_be_visible(timeout=5_000)
                    versions = root.get_by_test_id("animation-version")
                    assert versions.count() == 2
                    latest = page.request.get(BASE_URL + f"/api/v1/teaching-animations/{animation_id}", headers=owner_headers).json()
                    assert latest["current_version"]["version_number"] == 2
                    assert latest["current_version"]["parameters"]["learning_rate"] == 0.1
                    report["checks"]["immutable_versions"] = {"count": 2, "current": 2}

                    root.get_by_role("button", name="单步", exact=True).click()
                    root.get_by_role("button", name="单步", exact=True).click()
                    before_refresh = page.request.get(BASE_URL + f"/api/v1/teaching-animations/{animation_id}", headers=owner_headers).json()["current_frame"]
                    page.reload(wait_until="domcontentloaded")
                    root = page.get_by_test_id("teaching-animation-workspace")
                    root.get_by_test_id("animation-player").wait_for(state="visible", timeout=30_000)
                    expect(root.get_by_test_id("frame-counter")).to_have_text(f"{before_refresh} / {latest['max_frame']}")
                    report["checks"]["refresh_recovery"] = before_refresh

                    root.get_by_role("button", name="静态数据视图").click()
                    fallback = root.get_by_test_id("animation-static-fallback")
                    expect(fallback).to_be_visible()
                    assert fallback.locator("tbody tr").count() == latest["max_frame"] + 1
                    report["checks"]["static_fallback_rows"] = fallback.locator("tbody tr").count()
                    report["screenshots"].append(shot(page, "01-desktop-animation-static-fallback"))
                    root.get_by_role("button", name="显示动画画布").click()
                    report["screenshots"].append(shot(page, "02-desktop-animation-canvas"))

                    denied_get = page.request.get(BASE_URL + f"/api/v1/teaching-animations/{animation_id}", headers=outsider_headers)
                    denied_put = page.request.put(BASE_URL + f"/api/v1/teaching-animations/{animation_id}/playback", headers=outsider_headers, data={
                        "current_frame": 0, "playback_status": "paused", "expected_lock_version": latest["lock_version"],
                    })
                    assert denied_get.status == denied_put.status == 403
                    report["checks"]["owner_boundary"] = [denied_get.status, denied_put.status]

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(350)
                    geometry = page.evaluate("""() => { const root=document.querySelector('[data-testid=teaching-animation-workspace]').getBoundingClientRect(); return {viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,root:{x:root.x,right:root.right,width:root.width}} }""")
                    assert geometry["documentWidth"] <= 390 and geometry["root"]["x"] >= 0 and geometry["root"]["right"] <= 391
                    report["checks"]["mobile_viewport"] = geometry
                    report["screenshots"].append(shot(page, "03-mobile-animation"))
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
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target)
                report["checks"]["sqlite_integrity"] = target.execute("PRAGMA integrity_check").fetchone()[0]
                report["checks"]["evidence_rows"] = {
                    "projects": target.execute("SELECT COUNT(*) FROM teaching_animations").fetchone()[0],
                    "versions": target.execute("SELECT COUNT(*) FROM teaching_animation_versions").fetchone()[0],
                }
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{
            "file": path.name, "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        } for path in sorted(OUTPUT.iterdir()) if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))]
        (OUTPUT / "manifest.json").write_text(json.dumps({
            "schema_version": "fc1-007.teaching-animation-manifest.v1", "files": files,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
