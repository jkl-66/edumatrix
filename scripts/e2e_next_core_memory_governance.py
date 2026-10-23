"""Verify owner-scoped memory governance and profile subscriptions in Chromium."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-CORE-02" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_core_memory_e2e.db"
EVIDENCE_DB = OUTPUT / "memory_governance_evidence.db"
PORT = 8785
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-core-memory-2026!"


def wait_port(open_: bool, timeout: float = 45.0) -> None:
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
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True, text=True, timeout=15,
    )
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
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
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "next-core-memory-e2e-secret",
        "EDUMATRIX_DEMO_MODE": "0",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {
        "schema_version": "next.memory-governance-e2e.v1",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {}, "screenshots": [],
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
                    suffix = str(int(time.time()))
                    username = f"memory_student_{suffix}"
                    register = page.request.post(f"{BASE_URL}/api/auth/register", data={
                        "username": username, "password": PASSWORD,
                        "display_name": "长期记忆验收学生", "major": "计算机科学",
                    })
                    other = page.request.post(f"{BASE_URL}/api/auth/register", data={
                        "username": f"memory_other_{suffix}", "password": PASSWORD,
                        "display_name": "隔离验收用户",
                    })
                    assert register.ok and other.ok
                    token = register.json()["access_token"]
                    owner_id = register.json()["user_id"]
                    other_token = other.json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    context_id = f"tctx-{uuid.uuid4().hex}"
                    with sqlite3.connect(DB_PATH) as fixture_db:
                        fixture_db.execute(
                            """INSERT INTO tutor_context_sessions(
                            id,owner_public_id,idempotency_key,context_mode,primary_object_type,
                            primary_object_id,context_snapshot,teaching_style,explanation_depth,
                            guidance_mode,status,lock_version,last_used_at,created_at,updated_at
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)""",
                            (
                                context_id, owner_id, f"memory-e2e-{suffix}", "current_resource",
                                "chapter", "chapter-memory-e2e",
                                json.dumps({"schema_version": "m5.tutor-context.v1", "primary": {"title": "记忆验收章节"}}, ensure_ascii=False),
                                "progressive", "standard", "socratic", "active", 1,
                            ),
                        )
                        fixture_db.commit()

                    page.goto(f"{BASE_URL}/login", wait_until="commit", timeout=30_000)
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'student')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_display_name', '长期记忆验收学生')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [token, username],
                    )
                    page.goto(f"{BASE_URL}/settings", wait_until="commit", timeout=30_000)
                    panel = page.get_by_test_id("memory-governance")
                    panel.wait_for(state="visible", timeout=20_000)
                    page.get_by_test_id("memory-empty").wait_for(state="visible")

                    page.get_by_text("专业方向", exact=True).click()
                    page.get_by_text("学习目标", exact=True).click()
                    page.get_by_role("button", name="保存订阅").click()
                    page.get_by_text("画像订阅已更新", exact=True).wait_for(state="visible")
                    page.get_by_text("计算机科学", exact=True).wait_for(state="visible")

                    page.get_by_label("记忆标题").fill("代码训练约束")
                    page.get_by_label("记忆类型").select_option("constraint")
                    page.get_by_label("记忆内容").fill("先运行最小测试，再扩大回归")
                    page.get_by_role("button", name="新增").click()
                    page.get_by_text("长期记忆已保存", exact=True).wait_for(state="visible")
                    card = page.locator("article").filter(has_text="代码训练约束")
                    card.wait_for(state="visible")
                    report["screenshots"].append(shot(page, "01-desktop-memory-governance"))

                    listed = page.request.get(
                        f"{BASE_URL}/api/v1/next/core/memories", headers=headers,
                    )
                    assert listed.ok
                    manual = next(item for item in listed.json()["items"] if item["source_type"] == "manual")
                    denied = page.request.patch(
                        f"{BASE_URL}/api/v1/next/core/memories/{manual['id']}",
                        headers={"Authorization": f"Bearer {other_token}"},
                        data={"expected_version": manual["lock_version"], "content": "forbidden"},
                    )
                    assert denied.status == 403
                    report["checks"]["owner_isolation"] = {"cross_owner_update_status": denied.status}

                    card.get_by_title("编辑记忆").click()
                    page.get_by_label("编辑记忆内容").fill("先运行聚焦测试，再串行扩大回归")
                    page.get_by_test_id("memory-edit-save").click()
                    page.get_by_text("长期记忆已更新", exact=True).wait_for(state="visible")
                    page.reload(wait_until="commit", timeout=30_000)
                    page.get_by_text("先运行聚焦测试，再串行扩大回归", exact=True).wait_for(state="visible")
                    report["checks"]["refresh_recovery"] = True

                    with sqlite3.connect(DB_PATH) as evidence_db:
                        raw_snapshot, version = evidence_db.execute(
                            "SELECT context_snapshot,lock_version FROM tutor_context_sessions WHERE id=?", (context_id,),
                        ).fetchone()
                        snapshot = json.loads(raw_snapshot)
                        projected = snapshot["long_term_memory"]["items"]
                        assert any(item["content"] == "先运行聚焦测试，再串行扩大回归" for item in projected)
                        assert version > 1
                    report["checks"]["existing_context_projection"] = {
                        "context_id": context_id, "projected_items": len(projected), "lock_version": version,
                    }

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(500)
                    mobile_metrics = page.evaluate("""() => {
                      const panel = document.querySelector('[data-testid="memory-governance"]')?.getBoundingClientRect()
                      const main = document.querySelector('.app-main')?.getBoundingClientRect()
                      const sidebar = document.querySelector('.app-sidebar')?.getBoundingClientRect()
                      return {
                        innerWidth: window.innerWidth,
                        scrollWidth: document.documentElement.scrollWidth,
                        panel: panel && { x: panel.x, width: panel.width },
                        main: main && { x: main.x, width: main.width },
                        sidebar: sidebar && { x: sidebar.x, width: sidebar.width },
                      }
                    }""")
                    assert mobile_metrics["innerWidth"] == 390
                    assert mobile_metrics["scrollWidth"] <= 390
                    assert mobile_metrics["main"] and mobile_metrics["main"]["width"] >= 360
                    assert mobile_metrics["panel"] and mobile_metrics["panel"]["width"] >= 330
                    assert mobile_metrics["sidebar"] and mobile_metrics["sidebar"]["x"] < 0
                    report["screenshots"].append(shot(page, "02-mobile-memory-governance"))
                    page.get_by_role("button", name="展开导航").click()
                    page.wait_for_timeout(250)
                    open_sidebar_x = page.locator(".app-sidebar").bounding_box()["x"]
                    assert open_sidebar_x >= -1
                    page.locator(".app-brand").click()
                    page.wait_for_timeout(250)
                    closed_sidebar_x = page.locator(".app-sidebar").bounding_box()["x"]
                    assert closed_sidebar_x < 0
                    report["checks"]["mobile_viewport"] = {
                        "width": 390, "height": 844, "panel_visible": True,
                        "scroll_width": mobile_metrics["scrollWidth"],
                        "main_width": mobile_metrics["main"]["width"],
                        "panel_width": mobile_metrics["panel"]["width"],
                        "sidebar_hidden": True,
                        "drawer_open_close": True,
                    }

                    subscriptions = page.request.get(
                        f"{BASE_URL}/api/v1/next/core/memory-subscriptions", headers=headers,
                    ).json()["items"]
                    active = next(item for item in subscriptions if item["subscriber_key"] == "profile")
                    revoked = page.request.post(
                        f"{BASE_URL}/api/v1/next/core/memory-subscriptions/profile/revoke",
                        headers=headers,
                        data={"expected_version": active["lock_version"], "reason": "e2e_privacy_reset"},
                    )
                    assert revoked.ok
                    with sqlite3.connect(DB_PATH) as evidence_db:
                        raw_snapshot = evidence_db.execute(
                            "SELECT context_snapshot FROM tutor_context_sessions WHERE id=?", (context_id,),
                        ).fetchone()[0]
                        remaining = json.loads(raw_snapshot)["long_term_memory"]["items"]
                        assert len(remaining) == 1 and remaining[0]["source_type"] == "manual"
                        private_text_in_audit = evidence_db.execute(
                            "SELECT COUNT(*) FROM audit_logs WHERE metadata_json LIKE '%先运行聚焦测试%'",
                        ).fetchone()[0]
                        assert private_text_in_audit == 0
                    report["checks"]["withdrawal_propagation"] = {
                        "profile_memories_removed": True, "manual_memory_retained": True,
                        "private_content_in_audit": False,
                    }
                    report["result"] = "passed"
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
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT / "manifest.json").write_text(json.dumps({
            "schema_version": "next.memory-governance-manifest.v1", "files": files,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
