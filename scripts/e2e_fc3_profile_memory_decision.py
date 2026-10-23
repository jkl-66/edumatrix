"""Verify FC3-02A profile matching, proposed decisions and memory governance."""

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

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC3-02A" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_fc3_profile_memory_e2e.db"
EVIDENCE_DB = OUTPUT / "fc3_profile_memory_evidence.db"
PORT = 8828
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC3-profile-memory-2026!"


def wait_port(expected_open: bool, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            opened = probe.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected_open:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} state timeout")


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    process.wait(timeout=10)
    wait_port(False, 20)


def clean_runtime() -> None:
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()


def api(page, method: str, path: str, token: str, data: dict | None = None):
    options = {"headers": {"Authorization": f"Bearer {token}"}, "timeout": 60_000}
    if data is not None:
        options["data"] = data
    response = getattr(page.request, method)(f"{BASE_URL}{path}", **options)
    assert response.ok, f"{method.upper()} {path}: {response.status} {response.text()}"
    return response.json()


def write_manifest() -> None:
    files = []
    for path in sorted(OUTPUT.iterdir()):
        if not path.is_file() or path.name == "manifest.json" or path.name.endswith(("-wal", "-shm")):
            continue
        files.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (OUTPUT / "manifest.json").write_text(
        json.dumps({"schema_version": "edumatrix.fc3-profile-memory-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    clean_runtime()
    env = os.environ.copy()
    env.update(
        {
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "fc3-profile-memory-secret",
            "EDUMATRIX_LLM_PROVIDER": "deterministic",
            "EDUMATRIX_LLM_MODEL": "deterministic",
            "EDUMATRIX_LLM_API_KEY": "",
            "EDUMATRIX_LLM_ENDPOINT": "",
            "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
            "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
            "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
            "EDUMATRIX_RELOAD": "0",
            "EDUMATRIX_HOST": "127.0.0.1",
            "EDUMATRIX_PORT": str(PORT),
            "PYTHONUNBUFFERED": "1",
            "PYTHON_DOTENV_DISABLED": "1",
        }
    )
    report = {
        "schema_version": "edumatrix.fc3-profile-memory-e2e.v1",
        "work_package": "FC3-02A",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {},
        "screenshots": [],
    }
    backend = None
    page_errors: list[str] = []
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                page.on("pageerror", lambda error: page_errors.append(f"pageerror:{error}"))
                page.on(
                    "response",
                    lambda response: page_errors.append(f"http_{response.status}:{response.url}")
                    if response.status >= 500
                    else None,
                )

                suffix = str(int(time.time()))
                username = f"fc3_profile_{suffix}"
                registration = page.request.post(
                    f"{BASE_URL}/api/auth/register",
                    data={"username": username, "password": PASSWORD, "display_name": "FC3 画像验收学生", "major": "计算机科学"},
                )
                outsider = page.request.post(
                    f"{BASE_URL}/api/auth/register",
                    data={"username": f"fc3_outsider_{suffix}", "password": PASSWORD, "display_name": "隔离用户"},
                )
                assert registration.ok and outsider.ok
                token = registration.json()["access_token"]
                outsider_token = outsider.json()["access_token"]

                profiles = api(page, "get", "/api/v1/m3/profiles", token)
                assert len(profiles["profiles"]) == 3
                task = api(
                    page,
                    "post",
                    "/api/v1/m3/tasks",
                    token,
                    {
                        "profile_id": "profile-m0-theory",
                        "idempotency_key": f"fc3-profile-{suffix}",
                        "model": "deterministic",
                    },
                )
                task_id = task["id"]
                for action in ("start", "diagnose", "generate", "review", "matching-report", "decision"):
                    api(page, "post", f"/api/v1/m3/tasks/{task_id}/{action}", token)
                bundle = api(page, "get", f"/api/v1/m3/tasks/{task_id}/bundle", token)
                assert bundle["task"]["status"] == "completed"
                matching_version = bundle["artifacts"]["m3_matching_report"][0]["versions"][-1]
                matching = matching_version["content"]
                if isinstance(matching, str):
                    matching = json.loads(matching)
                decision_version = bundle["artifacts"]["m3_decision_comparison"][0]["versions"][-1]
                decision = decision_version["content"]
                if isinstance(decision, str):
                    decision = json.loads(decision)
                assert len(matching["resource_matches"]) == 3
                assert matching["recommended_interval"]["lower"] < matching["recommended_interval"]["upper"]
                assert decision["status"] == "proposed"
                assert decision["user_confirmed"] is False
                assert decision["mastery_update"] == "none"
                assert len(decision["candidates"]) == 5

                denied_task = page.request.get(
                    f"{BASE_URL}/api/v1/m3/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {outsider_token}"},
                )
                assert denied_task.status == 403

                page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                page.evaluate(
                    """([token, username]) => {
                      localStorage.setItem('edumatrix_token', token)
                      localStorage.setItem('edumatrix_role', 'student')
                      localStorage.setItem('edumatrix_username', username)
                      localStorage.setItem('edumatrix_student_id', username)
                      localStorage.setItem('edumatrix_onboarded', 'true')
                    }""",
                    [token, username],
                )
                page.goto(f"{BASE_URL}/competition-loop", wait_until="networkidle")
                matching_heading = page.get_by_text("学情与资源匹配", exact=True)
                matching_heading.wait_for(state="visible", timeout=20_000)
                page.get_by_text("动态决策候选", exact=True).wait_for(state="visible")
                assert "推荐难度" in page.locator("body").inner_text()
                matching_heading.scroll_into_view_if_needed()
                page.wait_for_timeout(300)
                page.screenshot(path=str(OUTPUT / "01-desktop-matching-and-proposed-decision.png"))
                report["screenshots"].append("01-desktop-matching-and-proposed-decision.png")

                page.goto(f"{BASE_URL}/settings", wait_until="networkidle")
                panel = page.get_by_test_id("memory-governance")
                panel.wait_for(state="visible", timeout=20_000)
                page.get_by_text("专业方向", exact=True).click()
                page.get_by_text("学习目标", exact=True).click()
                page.get_by_role("button", name="保存订阅").click()
                page.get_by_text("画像订阅已更新", exact=True).wait_for(state="visible")
                page.get_by_placeholder("记忆标题").fill("匹配学习约束")
                page.get_by_label("记忆类型").select_option("constraint")
                page.get_by_label("记忆内容").fill("先看匹配证据，再确认是否调整难度")
                page.get_by_role("button", name="新增").click()
                page.get_by_text("长期记忆已保存", exact=True).wait_for(state="visible")
                memory_card = page.locator("article").filter(has_text="匹配学习约束")
                memory_card.wait_for(state="visible")
                page.screenshot(path=str(OUTPUT / "02-desktop-memory-subscription.png"), full_page=True)
                report["screenshots"].append("02-desktop-memory-subscription.png")

                memories = api(page, "get", "/api/v1/next/core/memories", token)
                manual = next(item for item in memories["items"] if item["title"] == "匹配学习约束")
                denied_memory = page.request.patch(
                    f"{BASE_URL}/api/v1/next/core/memories/{manual['id']}",
                    headers={"Authorization": f"Bearer {outsider_token}"},
                    data={"expected_version": manual["lock_version"], "content": "forbidden"},
                )
                assert denied_memory.status == 403

                page.reload(wait_until="networkidle")
                page.get_by_text("先看匹配证据，再确认是否调整难度", exact=True).wait_for(state="visible")
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(500)
                sidebar = page.locator(".app-sidebar").bounding_box()
                assert sidebar and sidebar["x"] + sidebar["width"] <= 1
                assert page.evaluate("document.documentElement.scrollWidth") <= 390
                page.screenshot(path=str(OUTPUT / "03-mobile-memory-recovery.png"), full_page=True)
                report["screenshots"].append("03-mobile-memory-recovery.png")

                subscriptions = api(page, "get", "/api/v1/next/core/memory-subscriptions", token)
                active = next(item for item in subscriptions["items"] if item["subscriber_key"] == "profile")
                revoked_subscription = api(
                    page,
                    "post",
                    "/api/v1/next/core/memory-subscriptions/profile/revoke",
                    token,
                    {"expected_version": active["lock_version"], "reason": "fc3_privacy_reset"},
                )
                revoked_memory = api(
                    page,
                    "post",
                    f"/api/v1/next/core/memories/{manual['id']}/withdraw",
                    token,
                    {"expected_version": manual["lock_version"], "reason": "fc3_user_withdrawal"},
                )
                assert revoked_subscription["status"] == "revoked"
                assert revoked_memory["status"] == "withdrawn"

                report["checks"].update(
                    {
                        "profiles": [item["profile_id"] for item in profiles["profiles"]],
                        "profile_snapshot_id": matching["profile_snapshot_id"],
                        "recommended_interval": matching["recommended_interval"],
                        "resource_match_count": len(matching["resource_matches"]),
                        "decision_candidate_count": len(decision["candidates"]),
                        "decision_status": decision["status"],
                        "user_confirmed": decision["user_confirmed"],
                        "mastery_update": decision["mastery_update"],
                        "owner_task_status": denied_task.status,
                        "owner_memory_status": denied_memory.status,
                        "refresh_recovery": True,
                        "subscription_revoked": True,
                        "memory_withdrawn": True,
                        "mobile_width": 390,
                        "mobile_sidebar_hidden": True,
                        "page_or_http_5xx_errors": page_errors,
                        "dotenv_isolated": True,
                    }
                )
                assert not page_errors, page_errors
                report["result"] = "passed"
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
                    "PRAGMA integrity_check"
                ).fetchone()[0]
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
