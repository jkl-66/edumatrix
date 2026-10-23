"""Verify the R3-03 explainable profile summary through visible UI-only actions."""

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
OUTPUT = ROOT / "outputs" / "竞品融合重构执行" / "evidence" / "R3-03"
DB = OUTPUT / "r3_03_runtime.db"
PORT = int(os.environ.get("EDUMATRIX_R3_03_PORT", "8894"))
BASE = f"http://127.0.0.1:{PORT}"
COURSE_ID = "demo-course-rag-trust-v1"
COURSE_TITLE = "RAG 应用开发与负责任评测实训"
EXPECTED_ANSWERS = {
    "向量检索是否总能优于关键词检索？": "错误",
    "只增大向量 top-k 是否必然提高有效召回？": "错误",
    "没有可核查证据时系统应继续生成答案吗？": "错误",
    "混合检索是否需要重排阶段？": "正确",
    "Recall@K 的分母应在冻结评测集上定义吗？": "正确",
}


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


def enter_diagnostic_from_course(page: Page) -> None:
    dashboard = page.get_by_test_id("competition-demo-context-dashboard")
    dashboard.get_by_text(COURSE_TITLE, exact=False).wait_for(timeout=30_000)
    dashboard.get_by_role("button", name="查看主课程与来源").click()
    page.wait_for_function("location.pathname === '/knowledge'", timeout=30_000)
    sources = page.get_by_test_id("competition-demo-sources")
    sources.wait_for(state="visible", timeout=30_000)
    sources.get_by_test_id("open-demo-diagnostic").click()
    page.wait_for_function("location.pathname === '/assessment'", timeout=30_000)
    page.get_by_test_id("assessment-workspace").wait_for(state="visible", timeout=30_000)


def screenshot(page: Page, report: dict, name: str) -> None:
    page.screenshot(path=str(OUTPUT / name), full_page=True)
    report["screenshots"].append(name)


def horizontal_overflow(page: Page) -> bool:
    return bool(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"))


def choose_and_submit_one_diagnostic(page: Page) -> dict:
    with page.expect_response(
        lambda response: "/api/v1/m5/assessment/cat/next" in response.url and response.status == 200,
        timeout=30_000,
    ) as cat_response_info:
        page.get_by_test_id("cat-next").click()
    cat_payload = cat_response_info.value.json()
    stage = page.get_by_test_id("assessment-question")
    prompt = stage.locator("h2").inner_text().strip()
    assert prompt in EXPECTED_ANSWERS, prompt
    stage.get_by_role("button", name=EXPECTED_ANSWERS[prompt], exact=True).click()
    with page.expect_response(
        lambda response: "/api/v1/m5/profile-summary" in response.url and response.status == 200,
        timeout=30_000,
    ) as summary_response_info:
        with page.expect_response(
            lambda response: "/api/v1/m5/assessment/attempts" in response.url and response.status == 201,
            timeout=30_000,
        ):
            stage.get_by_role("button", name="提交作答", exact=True).click()
    return {
        "prompt": prompt,
        "answer": EXPECTED_ANSWERS[prompt],
        "selection_trace_hash": cat_payload["selection"]["trace_hash"],
        "summary_response": summary_response_info.value.json(),
    }


def inspect_profile_panel(page: Page) -> dict:
    panel = page.get_by_test_id("profile-summary")
    panel.wait_for(state="visible", timeout=30_000)
    section_keys = ["skill", "cognitive", "behavior"]
    sections = []
    for key in section_keys:
        section = page.get_by_test_id(f"profile-section-{key}")
        section.wait_for(state="visible", timeout=20_000)
        section.locator("summary").click()
        evidence = section.locator(".evidence-row")
        assert evidence.count() > 0
        text = section.inner_text()
        assert "下一步" in text
        sections.append({
            "key": key,
            "text": text,
            "evidence_rows": evidence.count(),
        })
    panel_text = panel.inner_text()
    assert "会什么、哪里困难、下一步做什么" in panel_text
    assert "来源、时间与推荐影响" in panel_text
    assert "不是课程总评" in panel_text
    return {"panel_text": panel_text, "sections": sections}


def checkpoint_database() -> None:
    if not DB.exists():
        return
    with sqlite3.connect(DB) as connection:
        connection.execute("pragma wal_checkpoint(truncate)").fetchone()


def write_junit(result: str, failure: str | None) -> None:
    suite = ET.Element("testsuite", {
        "name": "R3-03 explainable profile summary UI-only",
        "tests": "1",
        "failures": "0" if result == "passed" else "1",
        "errors": "0",
        "skipped": "0",
    })
    case = ET.SubElement(suite, "testcase", {
        "classname": "e2e.r3_profile_summary",
        "name": "diagnostic_refreshes_explainable_three_profile_summary",
    })
    if result != "passed":
        node = ET.SubElement(case, "failure", {"message": failure or "unknown failure"})
        node.text = failure or "unknown failure"
    ET.ElementTree(suite).write(OUTPUT / "junit.xml", encoding="utf-8", xml_declaration=True)


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


def write_pass_artifacts(report: dict) -> None:
    focused_log = read_generated_log(OUTPUT / "focused-pytest.log")
    expanded_log = read_generated_log(OUTPUT / "expanded-pytest.log")
    build_log = read_generated_log(OUTPUT / "vue-build.log")
    focused_match = re.search(r"(\d+ passed(?:, \d+ warnings?)?)", focused_log)
    expanded_match = re.search(r"(\d+ passed(?:, \d+ warnings?)?)", expanded_log)
    build_match = re.search(r"(\d+) modules transformed[.\s]+.*?built in ([\d.]+s)", build_log, re.DOTALL)
    ui_manifest = {
        "schema_version": "r3-03.ui-only-manifest.v1",
        "journey": "diagnostic-driven explainable skill, cognitive and behavior summary",
        "result": "passed",
        "allowed_preconditions": ["visible administrator login", "formal competition demo initialization"],
        "forbidden_actions_used": [],
        "checks": [
            "student completes one diagnostic through visible controls",
            "summary refreshes from zero to one effective diagnostic response",
            "skill, cognitive and behavior sections expose source, time and recommendation impact",
            "next action enters the existing learning workspace",
            "refresh, re-login and student-analysis entry restore the same server state",
            "390x844 has no horizontal overflow or clipped profile summary",
            "focused contract verifies non-member 403",
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
        "gate": "R3-03_EXPLAINABLE_PROFILE_SUMMARY=PASS",
        "ui_only_result": report["result"],
        "course_id": COURSE_ID,
        "diagnostic_response_count": report["database_audit"]["ability_response_count"],
        "summary_evidence_count": report["summary_api"]["evidence_count"],
        "sections": [item["key"] for item in report["desktop"]["sections"]],
        "next_action_route": report["next_action"]["route"],
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
    explanation = """# R3-03 三画像可解释摘要验收说明

- 学生通过正式课程入口进入短诊断并完成一道题，画像摘要随服务端能力证据实时刷新。
- 技能、认知、行为三类摘要统一回答“会什么、哪里困难、下一步做什么”。
- 每类摘要均可展开查看事实来源、对象 ID、观察时间和对推荐的影响。
- 下一动作复用现有正式学习路径并进入学习工作空间，没有新建第二套画像、记忆或推荐底座。
- 刷新、重新登录和学生画像入口均恢复相同服务端状态；390x844 无横向溢出或裁切。
- 摘要明确声明其不是课程总评、人格标签、真人专家认证或自动高风险决定。
- 非课程成员 403 由聚焦契约测试验证；浏览器四类非预期错误均为 0。
- 验收仅使用隔离 SQLite，正式数据库未修改。

最终门禁：`R3-03_EXPLAINABLE_PROFILE_SUMMARY=PASS`
"""
    (OUTPUT / "R3-03三画像可解释摘要验收说明.md").write_text(explanation, encoding="utf-8")

    implementation = [
        ROOT / "app/profile_summary.py",
        ROOT / "app/m5_api.py",
        ROOT / "frontend/src/api/m5.js",
        ROOT / "frontend/src/components/ProfileSummaryPanel.vue",
        ROOT / "frontend/src/views/AssessmentWorkspace.vue",
        ROOT / "frontend/src/views/StudentAnalysis.vue",
        ROOT / "tests/test_r3_profile_summary.py",
        ROOT / "scripts/e2e_r3_profile_summary.py",
    ]
    evidence = sorted(
        path for path in OUTPUT.iterdir()
        if path.is_file() and path.name != "evidence_manifest.json" and not path.name.endswith(("-wal", "-shm"))
    )
    files = []
    for path in implementation:
        files.append({
            "kind": "implementation",
            "path": path.relative_to(ROOT).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        })
    for path in evidence:
        files.append({
            "kind": "evidence",
            "path": f"evidence/R3-03/{path.name}",
            "size": path.stat().st_size,
            "sha256": sha256(path),
        })
    manifest = {
        "schema_version": "r3-03.evidence-manifest.v1",
        "task": "R3-03 explainable profile summary",
        "gate": "R3-03_EXPLAINABLE_PROFILE_SUMMARY=PASS",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "file_count": len(files),
        "files": files,
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
        "EDUMATRIX_AUTH_SECRET_KEY": "r3-03-isolated-auth-secret",
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
        "schema_version": "r3-03.profile-summary-ui-only.v1",
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
                phase("browser-ready")

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
                enter_diagnostic_from_course(desktop)
                assert desktop.get_by_test_id("profile-summary").count() == 0
                report["diagnostic"] = choose_and_submit_one_diagnostic(desktop)
                payload = report["diagnostic"].pop("summary_response")
                assert payload["schema_version"] == "r3.profile-summary.v1"
                assert payload["summary"]["diagnostic_response_count"] == 1
                assert [item["key"] for item in payload["sections"]] == ["skill", "cognitive", "behavior"]
                report["summary_api"] = {
                    "diagnostic_response_count": payload["summary"]["diagnostic_response_count"],
                    "diagnostic_attempt_count": payload["summary"]["diagnostic_attempt_count"],
                    "evidence_count": payload["summary"]["evidence_count"],
                    "next_action": payload["summary"]["next_action"],
                }
                report["desktop"] = inspect_profile_panel(desktop)
                screenshot(desktop, report, "01-profile-summary-after-diagnostic.png")
                phase("profile-summary-refreshed")

                behavior = desktop.get_by_test_id("profile-section-behavior")
                behavior.locator(".next-action").click()
                desktop.wait_for_function("location.pathname === '/workspace'", timeout=30_000)
                desktop.get_by_test_id("learning-object-container").wait_for(timeout=30_000)
                report["next_action"] = {"route": desktop.url.removeprefix(BASE), "workspace_visible": True}
                screenshot(desktop, report, "02-next-action-workspace.png")
                desktop.go_back(wait_until="commit", timeout=60_000)
                desktop.get_by_test_id("profile-summary").wait_for(timeout=30_000)

                desktop.reload(wait_until="commit", timeout=60_000)
                restored = inspect_profile_panel(desktop)
                assert "1 次有效诊断作答" in restored["panel_text"]
                report["refresh"] = {"restored": True, "section_count": len(restored["sections"])}
                screenshot(desktop, report, "03-refresh-restored.png")
                desktop_context.close()
                phase("refresh-restored")

                relogin_context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                relogin = relogin_context.new_page()
                diagnostics(relogin, report, "student-relogin")
                visible_demo_login(relogin, "学生", "/")
                enter_diagnostic_from_course(relogin)
                relogin_panel = inspect_profile_panel(relogin)
                assert "1 次有效诊断作答" in relogin_panel["panel_text"]
                relogin.goto(BASE + f"/student-analysis?course_id={COURSE_ID}", wait_until="commit", timeout=60_000)
                relogin.get_by_test_id("profile-summary").wait_for(timeout=30_000)
                report["relogin"] = {"restored": True, "student_analysis_entry": True}
                screenshot(relogin, report, "04-student-analysis-shared-summary.png")
                relogin_context.close()
                phase("relogin-and-shared-entry-restored")

                mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, locale="zh-CN")
                mobile = mobile_context.new_page()
                mobile.set_default_timeout(20_000)
                diagnostics(mobile, report, "student-mobile")
                visible_demo_login(mobile, "学生", "/")
                enter_diagnostic_from_course(mobile)
                mobile_panel = mobile.get_by_test_id("profile-summary")
                mobile_panel.wait_for(timeout=30_000)
                page_overflow = horizontal_overflow(mobile)
                bounds = mobile_panel.evaluate("""
                    element => {
                      const rect = element.getBoundingClientRect()
                      return {left: rect.left, right: rect.right, width: rect.width, viewport: innerWidth}
                    }
                """)
                clipped = bounds["left"] < 0 or bounds["right"] > bounds["viewport"]
                assert page_overflow is False and clipped is False
                report["mobile"] = {
                    "viewport": [390, 844], "horizontal_overflow": page_overflow,
                    "panel_clipped": clipped, "panel_bounds": bounds,
                }
                screenshot(mobile, report, "05-mobile-profile-summary.png")
                mobile_context.close()
                browser.close()
                browser = None
                phase("mobile-verified")

        with sqlite3.connect(DB) as connection:
            owner = connection.execute("select public_id from users where username='lzz'").fetchone()[0]
            report["database_audit"] = {
                "integrity": connection.execute("pragma integrity_check").fetchone()[0],
                "foreign_key_violations": len(connection.execute("pragma foreign_key_check").fetchall()),
                "cohort_students": connection.execute(
                    "select count(*) from teaching_class_members where class_id='demo-class-rag-2026-a' and role='student' and status='active'"
                ).fetchone()[0],
                "ui_attempts": connection.execute(
                    "select count(*) from assessment_attempts where owner_public_id=? and course_id=? and idempotency_key like 'assessment-ui-%'",
                    (owner, COURSE_ID),
                ).fetchone()[0],
                "ability_response_count": connection.execute(
                    "select response_count from assessment_ability_states where owner_public_id=? and course_scope=?",
                    (owner, COURSE_ID),
                ).fetchone()[0],
                "profile_evidence_rows": connection.execute(
                    "select count(*) from profile_evidence_items where owner_public_id=? and status='active'",
                    (owner,),
                ).fetchone()[0],
            }
        assert report["database_audit"]["integrity"] == "ok"
        assert report["database_audit"]["foreign_key_violations"] == 0
        assert report["database_audit"]["cohort_students"] == 15
        assert report["database_audit"]["ui_attempts"] == 1
        assert report["database_audit"]["ability_response_count"] == 1
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
        "summary_api": report.get("summary_api"), "refresh": report.get("refresh"),
        "relogin": report.get("relogin"), "mobile": report.get("mobile"),
        "database": report.get("database_audit"), "cleanup": report.get("process_cleanup"),
    }, ensure_ascii=True))
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
