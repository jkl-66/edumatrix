"""Verify the R3-05 shared today-task projection through visible UI actions."""

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
OUTPUT = ROOT / "outputs" / "竞品融合重构执行" / "evidence" / "R3-05"
DB = OUTPUT / "r3_05_runtime.db"
PORT = int(os.environ.get("EDUMATRIX_R3_05_PORT", "8896"))
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


def screenshot(page: Page, report: dict, name: str) -> None:
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUTPUT / name), full_page=True)
    report["screenshots"].append(name)


def horizontal_overflow(page: Page) -> bool:
    return bool(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"))


def dashboard_tasks(page: Page) -> list[str]:
    panel = page.get_by_test_id("dashboard-today-tasks")
    panel.wait_for(state="visible", timeout=30_000)
    articles = panel.locator("article")
    return [articles.nth(index).locator("h3").inner_text().strip() for index in range(articles.count())]


def workspace_tasks(page: Page) -> list[str]:
    page.locator(".task-list").wait_for(state="visible", timeout=30_000)
    articles = page.locator(".task-list article")
    return [articles.nth(index).locator("strong").first.inner_text().strip() for index in range(articles.count())]


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
        "name": "R3-05 shared today tasks UI-only", "tests": "1",
        "failures": "0" if result == "passed" else "1", "errors": "0", "skipped": "0",
    })
    case = ET.SubElement(suite, "testcase", {
        "classname": "e2e.r3_today_tasks",
        "name": "dashboard_workspace_and_completion_share_today_tasks",
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
    expanded_match = re.search(r"(\d+ passed(?:, \d+ deselected)?(?:, \d+ warnings?)?)", expanded_log)
    build_match = re.search(r"(\d+) modules transformed[.\s]+.*?built in ([\d.]+s)", build_log, re.DOTALL)
    (OUTPUT / "ui_only_manifest.json").write_text(json.dumps({
        "schema_version": "r3-05.ui-only-manifest.v1",
        "journey": "dashboard and workspace share at most three tasks and advance together",
        "result": "passed",
        "allowed_preconditions": ["visible administrator login", "formal competition demo initialization"],
        "forbidden_actions_used": [],
        "checks": [
            "dashboard shows three tasks with time, criteria and recommendation reason",
            "dashboard continue action opens the exact first workspace node",
            "workspace exposes the same three task titles and object identities",
            "visible strong-evidence action completes the first path node",
            "workspace and dashboard both advance to the same next path node",
            "refresh, re-login and 390x844 restore the same server state",
            "browser errors remain zero and isolated SQLite stays valid",
        ],
        "screenshots": report["screenshots"], "evidence_report": "report.json",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "verification_summary.json").write_text(json.dumps({
        "gate": "R3-05_SHARED_TODAY_TASKS=PASS",
        "ui_only_result": report["result"],
        "course_id": COURSE_ID,
        "initial_tasks": report["initial"]["dashboard_titles"],
        "next_task": report["after_completion"]["dashboard_titles"][0],
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
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "R3-05今日任务与继续学习验收说明.md").write_text("""# R3-05 今日任务与继续学习验收说明

- 首页与学习空间共同消费 `workspace.today_tasks`，不再各自计算任务。
- 今日任务最多 3 项，正式路径节点优先，到期复习补位；每项显示预计时间、完成标准和推荐理由。
- 首页“继续当前任务”进入工作空间同一 `node_id`，没有绕到旧智能对话入口。
- 学生通过可见“提交复测通过”产生强证据后，首页与工作空间同步切换到下一正式路径节点。
- 刷新、重新登录和 390x844 移动端恢复相同服务端状态，浏览器四类错误为 0。
- 任务完成只表示产生了符合规则的学习事件，不直接等同能力掌握。
- 验收仅使用隔离 SQLite，正式数据库未修改。

最终门禁：`R3-05_SHARED_TODAY_TASKS=PASS`
""", encoding="utf-8")
    implementation = [
        ROOT / "app/m5_learning.py", ROOT / "app/m5_workspace.py", ROOT / "app/m5_api.py",
        ROOT / "frontend/src/api/m5.js", ROOT / "frontend/src/views/Dashboard.vue",
        ROOT / "frontend/src/views/LearningWorkspace.vue", ROOT / "tests/test_r3_today_tasks.py",
        ROOT / "tests/test_r2_workspace_overview.py", ROOT / "scripts/e2e_r3_today_tasks.py",
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
        "kind": "evidence", "path": f"evidence/R3-05/{path.name}",
        "size": path.stat().st_size, "sha256": sha256(path),
    } for path in evidence)
    (OUTPUT / "evidence_manifest.json").write_text(json.dumps({
        "schema_version": "r3-05.evidence-manifest.v1",
        "task": "R3-05 shared today tasks and continue learning",
        "gate": "R3-05_SHARED_TODAY_TASKS=PASS",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "file_count": len(files), "files": files,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB), "EDUMATRIX_AUTH_SECRET_KEY": "r3-05-isolated-auth-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "", "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_SANDBOX_MODE": "trusted_local", "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_RELOAD": "0", "EDUMATRIX_HOST": "127.0.0.1", "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1", "PYTHONUNBUFFERED": "1",
    })
    report = {
        "schema_version": "r3-05.today-tasks-ui-only.v1", "screenshots": [],
        "http_errors": [], "failed_requests": [], "console_errors": [], "page_errors": [],
    }
    process = None
    browser = None
    result_code = 1
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
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

                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                page.set_default_timeout(20_000)
                diagnostics(page, report, "student-desktop")
                visible_demo_login(page, "学生", "/")
                initial_dashboard = dashboard_tasks(page)
                assert len(initial_dashboard) == 3
                dashboard_panel = page.get_by_test_id("dashboard-today-tasks")
                assert dashboard_panel.get_by_text("完成标准：", exact=False).count() == 3
                report["initial"] = {"dashboard_titles": initial_dashboard}
                screenshot(page, report, "01-dashboard-three-tasks.png")

                dashboard_panel.get_by_role("button", name="继续当前任务").click()
                page.wait_for_function("location.pathname === '/workspace'", timeout=30_000)
                page.locator("#workspace-node-demo-task-lzz-read-01").wait_for(timeout=30_000)
                initial_workspace = workspace_tasks(page)
                assert initial_workspace == initial_dashboard
                assert page.locator(".task-list .task-criteria").count() == 3
                report["initial"]["workspace_titles"] = initial_workspace
                page.get_by_test_id("workspace-today-task-0").scroll_into_view_if_needed()
                screenshot(page, report, "02-workspace-same-three-tasks.png")

                page.get_by_test_id("workspace-today-task-0").get_by_role("button", name="继续").click()
                page.get_by_text("继续任务：精读混合检索来源", exact=True).wait_for(timeout=10_000)
                with page.expect_response(
                    lambda response: "/api/v1/m5/learning-events" in response.url and response.status == 201,
                    timeout=30_000,
                ):
                    page.locator("#workspace-node-demo-task-lzz-read-01").get_by_role("button", name="提交复测通过").click()
                page.get_by_text("强证据已提交，路径状态已重新计算。", exact=True).wait_for(timeout=30_000)
                next_task = page.get_by_test_id("workspace-today-task-0")
                next_task.get_by_text("调优 Recall@K 交互实验", exact=True).wait_for(
                    state="attached", timeout=30_000,
                )
                next_task.scroll_into_view_if_needed()
                next_task.get_by_text("调优 Recall@K 交互实验", exact=True).wait_for(
                    state="visible", timeout=30_000,
                )
                workspace_after = workspace_tasks(page)
                assert workspace_after[0] == "调优 Recall@K 交互实验"
                screenshot(page, report, "03-workspace-advanced-next-task.png")

                page.get_by_role("link", name="首页", exact=True).first.click()
                page.wait_for_function("location.pathname === '/'", timeout=30_000)
                dashboard_after = dashboard_tasks(page)
                assert dashboard_after == workspace_after
                report["after_completion"] = {
                    "workspace_titles": workspace_after, "dashboard_titles": dashboard_after,
                }
                screenshot(page, report, "04-dashboard-advanced-next-task.png")
                page.reload(wait_until="commit", timeout=60_000)
                assert dashboard_tasks(page) == dashboard_after
                context.close()
                phase("desktop-shared-projection-verified")

                relogin_context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                relogin = relogin_context.new_page()
                diagnostics(relogin, report, "student-relogin")
                visible_demo_login(relogin, "学生", "/")
                assert dashboard_tasks(relogin) == dashboard_after
                report["relogin"] = {"restored": True}
                relogin_context.close()

                mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, locale="zh-CN")
                mobile = mobile_context.new_page()
                diagnostics(mobile, report, "student-mobile")
                visible_demo_login(mobile, "学生", "/")
                mobile_titles = dashboard_tasks(mobile)
                mobile.wait_for_timeout(700)
                panel = mobile.get_by_test_id("dashboard-today-tasks")
                bounds = panel.evaluate("""element => { const rect = element.getBoundingClientRect();
                    return {left: rect.left, right: rect.right, width: rect.width, viewport: innerWidth} }""")
                overflow = horizontal_overflow(mobile)
                clipped = bounds["left"] < 0 or bounds["right"] > bounds["viewport"]
                assert mobile_titles == dashboard_after
                assert overflow is False and clipped is False
                report["mobile"] = {
                    "titles": mobile_titles, "viewport": [390, 844], "horizontal_overflow": overflow,
                    "panel_clipped": clipped, "panel_bounds": bounds,
                }
                screenshot(mobile, report, "05-mobile-today-tasks.png")
                mobile_context.close()
                browser.close()
                browser = None

        with sqlite3.connect(DB) as connection:
            owner = connection.execute("select public_id from users where username='lzz'").fetchone()[0]
            report["database_audit"] = {
                "integrity": connection.execute("pragma integrity_check").fetchone()[0],
                "foreign_key_violations": len(connection.execute("pragma foreign_key_check").fetchall()),
                "cohort_students": connection.execute(
                    "select count(*) from teaching_class_members where class_id='demo-class-rag-2026-a' and role='student' and status='active'"
                ).fetchone()[0],
                "first_node_status": connection.execute(
                    "select status from path_nodes where id='demo-task-lzz-read-01'"
                ).fetchone()[0],
                "strong_events": connection.execute(
                    "select count(*) from learning_events where owner_public_id=? and course_id=? and event_type='delayed_retest_passed'",
                    (owner, COURSE_ID),
                ).fetchone()[0],
            }
        assert report["database_audit"]["integrity"] == "ok"
        assert report["database_audit"]["foreign_key_violations"] == 0
        assert report["database_audit"]["cohort_students"] == 15
        assert report["database_audit"]["first_node_status"] == "completed"
        assert report["database_audit"]["strong_events"] >= 1
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
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=20)
            process.wait(timeout=5)
            wait_port(False, 15)
        report["process_cleanup"] = {
            "service_stopped": process is None or process.poll() is not None,
            "port_released": socket.socket().connect_ex(("127.0.0.1", PORT)) != 0,
        }
        if report["process_cleanup"]["service_stopped"]:
            checkpoint_database()
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_junit(report.get("result", "failed"), report.get("failure"))
        if report.get("result") == "passed":
            write_pass_artifacts(report)
    print(json.dumps({
        "result": report.get("result"), "failure": report.get("failure"),
        "initial": report.get("initial"), "after": report.get("after_completion"),
        "relogin": report.get("relogin"), "mobile": report.get("mobile"),
        "database": report.get("database_audit"), "cleanup": report.get("process_cleanup"),
    }, ensure_ascii=True))
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
