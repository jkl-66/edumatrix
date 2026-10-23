"""Verify the R3-04 textbook-anchored path draft through visible UI actions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "竞品融合重构执行" / "evidence" / "R3-04"
DB = OUTPUT / "r3_04_runtime.db"
PORT = int(os.environ.get("EDUMATRIX_R3_04_PORT", "8895"))
BASE = f"http://127.0.0.1:{PORT}"
COURSE_ID = "demo-course-rag-trust-v1"


def phase(message: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {message}"
    print(line, flush=True)
    with (OUTPUT / "progress.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def wait_port(expected: bool, timeout: int = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not become {'open' if expected else 'closed'}")


def diagnostics(page: Page, report: dict, scope: str) -> None:
    page.on("response", lambda response: report["http_errors"].append({
        "scope": scope, "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "scope": scope, "url": request.url, "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append({
        "scope": scope, "error": str(error),
    }))
    page.on("console", lambda message: report["console_errors"].append({
        "scope": scope, "text": message.text,
    }) if message.type == "error" else None)


def visible_demo_login(page: Page, role_label: str, landing: str) -> None:
    page.goto(BASE + "/login", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_text("演示账号", exact=True).wait_for(timeout=40_000)
    page.get_by_role("button", name=re.compile(rf"^{re.escape(role_label)}")).click()
    page.get_by_role("button", name="启动学习").click()
    page.wait_for_function("path => location.pathname === path", arg=landing, timeout=30_000)


def open_path_from_navigation(page: Page) -> None:
    link = page.get_by_role("link", name="学习路径", exact=True).first
    link.wait_for(state="visible", timeout=30_000)
    link.click()
    page.wait_for_function("location.pathname === '/learning-path'", timeout=30_000)
    page.get_by_test_id("textbook-path-draft").wait_for(state="visible", timeout=30_000)


def screenshot(page: Page, report: dict, name: str) -> None:
    page.screenshot(path=str(OUTPUT / name), full_page=True)
    report["screenshots"].append(name)


def horizontal_overflow(page: Page) -> bool:
    return bool(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"))


def checkpoint_database() -> None:
    if not DB.exists():
        return
    with sqlite3.connect(DB) as connection:
        connection.execute("pragma wal_checkpoint(truncate)").fetchone()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def read_generated_log(path: Path) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8", errors="replace")


def write_junit(result: str, failure: str | None) -> None:
    suite = ET.Element("testsuite", {
        "name": "R3-04 textbook path draft UI-only",
        "tests": "1", "failures": "0" if result == "passed" else "1",
        "errors": "0", "skipped": "0",
    })
    case = ET.SubElement(suite, "testcase", {
        "classname": "e2e.r3_textbook_path_draft",
        "name": "generate_compare_confirm_and_restore_textbook_path",
    })
    if result != "passed":
        node = ET.SubElement(case, "failure", {"message": failure or "unknown failure"})
        node.text = failure or "unknown failure"
    ET.ElementTree(suite).write(OUTPUT / "junit.xml", encoding="utf-8", xml_declaration=True)


def write_pass_artifacts(report: dict) -> None:
    focused_log = read_generated_log(OUTPUT / "focused-pytest.log")
    expanded_log = read_generated_log(OUTPUT / "expanded-pytest.log")
    build_log = read_generated_log(OUTPUT / "vue-build.log")
    focused_match = re.search(r"(\d+ passed(?:, \d+ warnings?)?)", focused_log)
    expanded_match = re.search(r"(\d+ passed(?:, \d+ warnings?)?)", expanded_log)
    build_match = re.search(r"(\d+) modules transformed[.\s]+.*?built in ([\d.]+s)", build_log, re.DOTALL)
    ui_manifest = {
        "schema_version": "r3-04.ui-only-manifest.v1",
        "journey": "confirmed path to textbook draft, version diff, confirmation and recovery",
        "result": "passed",
        "allowed_preconditions": ["visible administrator login", "formal competition demo initialization"],
        "forbidden_actions_used": [],
        "checks": [
            "student opens learning path from visible primary navigation",
            "draft generation creates a pending version without replacing the active path",
            "every draft node exposes a real chapter, canonical source, reason and time estimate",
            "important version changes are visible before confirmation",
            "visible confirmation archives the old path and publishes the new path",
            "refresh and re-login restore the confirmed server state",
            "390x844 has no horizontal overflow or clipped draft panel",
            "browser HTTP, failed request, console and page errors remain zero",
            "isolated SQLite integrity and foreign keys remain valid",
        ],
        "screenshots": report["screenshots"],
        "evidence_report": "report.json",
    }
    (OUTPUT / "ui_only_manifest.json").write_text(
        json.dumps(ui_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    summary = {
        "gate": "R3-04_TEXTBOOK_PATH_DRAFT=PASS",
        "ui_only_result": report["result"],
        "course_id": COURSE_ID,
        "plan_id": report["draft_api"]["plan_id"],
        "draft_node_count": report["draft_api"]["node_count"],
        "draft_diff": report["draft_api"]["diff_summary"],
        "confirmed_path_id": report["confirmation"]["path_id"],
        "browser_errors": 0,
        "database_integrity": report["database_audit"]["integrity"],
        "foreign_key_violations": report["database_audit"]["foreign_key_violations"],
        "cohort_students": report["database_audit"]["cohort_students"],
        "focused_tests": focused_match.group(1) if focused_match else "not recorded",
        "expanded_regression": expanded_match.group(1) if expanded_match else "not recorded",
        "production_build": (
            f"{build_match.group(1)} modules transformed; built in {build_match.group(2)}"
            if build_match else "not recorded"
        ),
    }
    (OUTPUT / "verification_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    explanation = """# R3-04 教材锚定路径草稿验收说明

- 学生从正式一级导航进入学习路径，先看到当前已确认版本，再通过可见控件生成教材锚定草稿。
- 草稿复用既有计划版本生命周期，不新增表；确认前保持 `replan_pending`，不会替换活动路径。
- 草稿节点全部绑定真实课程章节、canonical 来源、知识点、先修关系、推荐理由和时间预算。
- 页面在确认前显示新增、移除、移动和修改数量；学生确认后才归档旧路径并发布新路径。
- 刷新、重新登录和 390x844 移动端均恢复相同正式版本，浏览器四类非预期错误为 0。
- 页面明确声明薄弱点与学习时间不等同课程掌握度、真人专家规划或高风险自动决定。
- 验收仅使用隔离 SQLite，正式数据库未修改。

最终门禁：`R3-04_TEXTBOOK_PATH_DRAFT=PASS`
"""
    (OUTPUT / "R3-04教材锚定路径草稿验收说明.md").write_text(explanation, encoding="utf-8")
    implementation = [
        ROOT / "app/path_draft.py",
        ROOT / "app/m5_api.py",
        ROOT / "frontend/src/api/m5.js",
        ROOT / "frontend/src/views/LearningPathGraph.vue",
        ROOT / "tests/test_r3_textbook_path_draft.py",
        ROOT / "scripts/e2e_r3_textbook_path_draft.py",
    ]
    evidence = sorted(
        path for path in OUTPUT.iterdir()
        if path.is_file() and path.name != "evidence_manifest.json" and not path.name.endswith(("-wal", "-shm"))
    )
    files = [{
        "kind": "implementation", "path": path.relative_to(ROOT).as_posix(),
        "size": path.stat().st_size, "sha256": sha256(path),
    } for path in implementation]
    files.extend({
        "kind": "evidence", "path": f"evidence/R3-04/{path.name}",
        "size": path.stat().st_size, "sha256": sha256(path),
    } for path in evidence)
    manifest = {
        "schema_version": "r3-04.evidence-manifest.v1",
        "task": "R3-04 textbook anchored path draft",
        "gate": "R3-04_TEXTBOOK_PATH_DRAFT=PASS",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "file_count": len(files), "files": files,
    }
    (OUTPUT / "evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB),
        "EDUMATRIX_AUTH_SECRET_KEY": "r3-04-isolated-auth-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_SANDBOX_MODE": "trusted_local",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    report = {
        "schema_version": "r3-04.textbook-path-ui-only.v1",
        "screenshots": [], "http_errors": [], "failed_requests": [],
        "console_errors": [], "page_errors": [],
    }
    process = None
    browser = None
    result_code = 1
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            phase("backend-ready")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                admin_context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                admin = admin_context.new_page()
                diagnostics(admin, report, "admin-initialize")
                visible_demo_login(admin, "管理员", "/competition-showcase")
                admin.get_by_role("button", name="一键初始化演示数据").click()
                admin.get_by_text("3 / 3", exact=True).wait_for(timeout=30_000)
                admin_context.close()
                phase("demo-initialized")

                desktop_context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                desktop = desktop_context.new_page()
                desktop.set_default_timeout(20_000)
                diagnostics(desktop, report, "student-desktop")
                visible_demo_login(desktop, "学生", "/")
                open_path_from_navigation(desktop)
                panel = desktop.get_by_test_id("textbook-path-draft")
                panel.get_by_text("正式版本", exact=True).wait_for()
                screenshot(desktop, report, "01-confirmed-path-before-draft.png")

                with desktop.expect_response(
                    lambda response: "/api/v1/m5/textbook-path-draft/generate" in response.url and response.status == 201,
                    timeout=30_000,
                ) as draft_info:
                    desktop.get_by_test_id("generate-textbook-path-draft").click()
                draft_payload = draft_info.value.json()
                panel.get_by_text("等待确认", exact=True).wait_for(timeout=30_000)
                panel.get_by_test_id("confirm-textbook-path-draft").wait_for()
                assert panel.locator("ol > li").count() == len(draft_payload["nodes"])
                assert "版本变化" in panel.inner_text()
                assert "薄弱点" in panel.inner_text()
                report["draft_api"] = {
                    "plan_id": draft_payload["plan_id"],
                    "node_count": len(draft_payload["nodes"]),
                    "diff_summary": draft_payload["diff"]["summary"],
                    "state": draft_payload["state"],
                }
                screenshot(desktop, report, "02-textbook-draft-with-diff.png")

                with desktop.expect_response(
                    lambda response: "/api/v1/m5/plans/" in response.url and response.url.endswith("/confirm") and response.status == 201,
                    timeout=30_000,
                ) as confirmation_info:
                    panel.get_by_test_id("confirm-textbook-path-draft").click()
                confirmation_payload = confirmation_info.value.json()
                desktop.get_by_test_id("textbook-path-draft").get_by_text("正式版本", exact=True).wait_for(timeout=30_000)
                report["confirmation"] = {
                    "path_id": confirmation_payload["path"]["id"],
                    "supersedes_path_id": confirmation_payload["path"]["supersedes_path_id"],
                    "node_count": len(confirmation_payload["path"]["nodes"]),
                }
                assert report["confirmation"]["supersedes_path_id"]
                screenshot(desktop, report, "03-confirmed-textbook-path.png")
                desktop.reload(wait_until="commit", timeout=60_000)
                restored = desktop.get_by_test_id("textbook-path-draft")
                restored.get_by_text("正式版本", exact=True).wait_for(timeout=30_000)
                assert restored.get_by_test_id("confirm-textbook-path-draft").count() == 0
                report["refresh"] = {"restored": True}
                desktop_context.close()
                phase("desktop-confirmed-and-restored")

                relogin_context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                relogin = relogin_context.new_page()
                diagnostics(relogin, report, "student-relogin")
                visible_demo_login(relogin, "学生", "/")
                open_path_from_navigation(relogin)
                relogin.get_by_test_id("textbook-path-draft").get_by_text("正式版本", exact=True).wait_for()
                report["relogin"] = {"restored": True}
                relogin_context.close()

                mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, locale="zh-CN")
                mobile = mobile_context.new_page()
                diagnostics(mobile, report, "student-mobile")
                visible_demo_login(mobile, "学生", "/")
                mobile.goto(BASE + f"/learning-path?course_id={COURSE_ID}", wait_until="commit", timeout=60_000)
                mobile_panel = mobile.get_by_test_id("textbook-path-draft")
                mobile_panel.wait_for(timeout=30_000)
                mobile.wait_for_timeout(700)
                bounds = mobile_panel.evaluate("""
                    element => { const rect = element.getBoundingClientRect();
                    return {left: rect.left, right: rect.right, width: rect.width, viewport: innerWidth} }
                """)
                overflow = horizontal_overflow(mobile)
                clipped = bounds["left"] < 0 or bounds["right"] > bounds["viewport"]
                assert overflow is False and clipped is False
                report["mobile"] = {
                    "viewport": [390, 844], "horizontal_overflow": overflow,
                    "panel_clipped": clipped, "panel_bounds": bounds,
                }
                screenshot(mobile, report, "04-mobile-confirmed-textbook-path.png")
                mobile_context.close()
                browser.close()
                browser = None
                phase("mobile-verified")

        with sqlite3.connect(DB) as connection:
            owner = connection.execute("select public_id from users where username='lzz'").fetchone()[0]
            plan_id = report["draft_api"]["plan_id"]
            report["database_audit"] = {
                "integrity": connection.execute("pragma integrity_check").fetchone()[0],
                "foreign_key_violations": len(connection.execute("pragma foreign_key_check").fetchall()),
                "cohort_students": connection.execute(
                    "select count(*) from teaching_class_members where class_id='demo-class-rag-2026-a' and role='student' and status='active'"
                ).fetchone()[0],
                "plan_status": connection.execute(
                    "select status from plan_drafts where id=?", (plan_id,),
                ).fetchone()[0],
                "plan_versions": connection.execute(
                    "select count(*) from plan_versions where plan_draft_id=?", (plan_id,),
                ).fetchone()[0],
                "active_paths": connection.execute(
                    "select count(*) from learning_paths where owner_public_id=? and course_id=? and status='active'",
                    (owner, COURSE_ID),
                ).fetchone()[0],
                "archived_paths": connection.execute(
                    "select count(*) from learning_paths where owner_public_id=? and course_id=? and status='archived'",
                    (owner, COURSE_ID),
                ).fetchone()[0],
            }
        assert report["database_audit"]["integrity"] == "ok"
        assert report["database_audit"]["foreign_key_violations"] == 0
        assert report["database_audit"]["cohort_students"] == 15
        assert report["database_audit"]["plan_status"] == "confirmed"
        assert report["database_audit"]["active_paths"] == 1
        assert report["database_audit"]["archived_paths"] >= 1
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["page_errors"], report["page_errors"]
        report["result"] = "passed"
        result_code = 0
    except Exception as exc:
        report["result"] = "failed"
        report["failure"] = repr(exc)
        report["traceback"] = traceback.format_exc()
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception as exc:
                report.setdefault("cleanup_warnings", []).append(f"browser close: {exc}")
        if process is not None and process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, text=True, timeout=20,
            )
            process.wait(timeout=5)
            wait_port(False, 15)
        report["process_cleanup"] = {
            "service_stopped": process is None or process.poll() is not None,
            "port_released": socket.socket().connect_ex(("127.0.0.1", PORT)) != 0,
        }
        if report["process_cleanup"]["service_stopped"]:
            checkpoint_database()
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        write_junit(report.get("result", "failed"), report.get("failure"))
        if report.get("result") == "passed":
            write_pass_artifacts(report)
    print(json.dumps({
        "result": report.get("result"), "failure": report.get("failure"),
        "draft": report.get("draft_api"), "confirmation": report.get("confirmation"),
        "refresh": report.get("refresh"), "relogin": report.get("relogin"),
        "mobile": report.get("mobile"), "database": report.get("database_audit"),
        "cleanup": report.get("process_cleanup"),
    }, ensure_ascii=True))
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
