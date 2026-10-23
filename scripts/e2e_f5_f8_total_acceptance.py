#!/usr/bin/env python3
"""Continuous F5-F8 acceptance journey in one isolated learner runtime."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

from playwright.sync_api import Browser, Page, sync_playwright

import e2e_f5_t02_resource_bundle as bundle
import e2e_f5_t03_handout_workspace as handout
import e2e_f5_t04_mindmap_workspace as mindmap
import e2e_f5_t05_training_task_workspace as training
import e2e_f6_t01_quiz_resource as quiz
import e2e_f6_t02_interactive_model as model
import e2e_f6_t03_code_sandbox as sandbox
import e2e_f6_t04_code_review as code_review
import e2e_f6_t05_feynman as feynman
import e2e_f6_t06_formal_exam as formal
import e2e_f7_t02_document_reader as reader
import e2e_f8_t01_review_calendar as review
import e2e_f8_t03_notes as notes
import e2e_f8_t05_learning_feedback as feedback


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f5_f8_total_acceptance"
BROWSER_DIR = OUTPUT_DIR / "browser"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "f5_f8_total_acceptance.sqlite3"
REPORT_PATH = OUTPUT_DIR / "report.json"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
RESOURCE_TYPES = bundle.RESOURCE_TYPES
PORT_START = int(os.getenv("EDUMATRIX_F5_F8_TOTAL_PORT", "9180"))
FORMAL_DB = ROOT / "edumatrix.db"


def reset_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in (BROWSER_DIR, RUNTIME_DIR):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
    for path in (REPORT_PATH, OUTPUT_DIR / "backend.log", OUTPUT_DIR / "document-fixture.json"):
        if path.exists():
            path.unlink()


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 40):
        if not bundle.port_open(port):
            return port
    raise RuntimeError("no free F5-F8 total-acceptance port")


def runtime_env(port: int) -> dict[str, str]:
    env = bundle.runtime_env(DB_PATH, port)
    env.update({
        "EDUMATRIX_AUTH_SECRET_KEY": "f5-f8-total-acceptance-secret",
        "EDUMATRIX_SANDBOX_MODE": "trusted_local",
        "EDUMATRIX_SANDBOX_TIMEOUT": "10",
        "EDUMATRIX_SANDBOX_MAX_OUTPUT_BYTES": "100000",
        "EDUMATRIX_UPLOAD_DIR": str(RUNTIME_DIR / "uploads"),
    })
    return env


def configure_helpers() -> None:
    helper_dirs = {
        quiz: BROWSER_DIR / "quiz",
        model: BROWSER_DIR / "interactive-model",
        sandbox: BROWSER_DIR / "code-sandbox",
        code_review: BROWSER_DIR / "code-review",
        feynman: BROWSER_DIR / "feynman",
        formal: BROWSER_DIR / "formal-exam",
        reader: BROWSER_DIR / "document-reader",
    }
    for module, path in helper_dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        module.OUTPUT_DIR = path
    review.DB_PATH = DB_PATH
    review.BROWSER_DIR = BROWSER_DIR / "review"
    review.BROWSER_DIR.mkdir(parents=True, exist_ok=True)
    notes.DB_PATH = DB_PATH
    notes.BROWSER_DIR = BROWSER_DIR / "notes"
    notes.BROWSER_DIR.mkdir(parents=True, exist_ok=True)
    feedback.DB_PATH = DB_PATH
    feedback.BROWSER_DIR = BROWSER_DIR / "feedback"
    feedback.BROWSER_DIR.mkdir(parents=True, exist_ok=True)


def file_record(path: Path) -> dict[str, object]:
    return {
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper() if path.exists() else "",
    }


def run_python(env: dict[str, str], code: str, *, timeout: int = 180) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(f"isolated helper failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def seed_runtime(env: dict[str, str]) -> dict[str, object]:
    bundle.seed_fixture(env)
    reader.OUTPUT_DIR = BROWSER_DIR / "document-reader"
    fixture = reader.seed_fixture(env)
    return fixture


def login(page: Page, base_url: str) -> dict[str, str]:
    return bundle.login(page, base_url)


def bearer(auth: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['access_token']}"}


def api_get(page: Page, base_url: str, auth: dict[str, str], path: str) -> dict:
    response = page.request.get(f"{base_url}{path}", headers=bearer(auth))
    if not response.ok:
        raise AssertionError(f"GET {path}: {response.status} {response.text()}")
    return response.json()


def api_post(
    page: Page,
    base_url: str,
    auth: dict[str, str],
    path: str,
    body: dict | None = None,
    *,
    expected_status: int | None = None,
) -> dict:
    response = page.request.post(f"{base_url}{path}", headers=bearer(auth), data=body or {})
    if expected_status is not None:
        assert response.status == expected_status, (path, response.status, response.text())
    elif not response.ok:
        raise AssertionError(f"POST {path}: {response.status} {response.text()}")
    return response.json()


def owner_id() -> str:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        return str(db.execute("SELECT public_id FROM users WHERE username=?", (USERNAME,)).fetchone()[0])


def digest_rows(rows: list[tuple]) -> dict[str, object]:
    raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return {"count": len(rows), "sha256": hashlib.sha256(raw).hexdigest()}


def learning_event_rows() -> dict[str, tuple]:
    owner = owner_id()
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        rows = db.execute(
            "SELECT id,event_type,evidence_status,mastery_eligible,completion_effect,"
            "source,object_type,action,payload FROM learning_events "
            "WHERE owner_public_id=? ORDER BY id",
            (owner,),
        ).fetchall()
    return {str(row[0]): tuple(row[1:]) for row in rows}


def business_state() -> dict[str, object]:
    owner = owner_id()
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        return {
            "learning_events": digest_rows(db.execute(
                "SELECT id,event_type,evidence_status,mastery_eligible,completion_effect,payload "
                "FROM learning_events WHERE owner_public_id=? ORDER BY id", (owner,),
            ).fetchall()),
            "profile_snapshots": digest_rows(db.execute(
                "SELECT id,profile_version,content_hash FROM profile_snapshots "
                "WHERE owner_public_id=? ORDER BY id", (owner,),
            ).fetchall()),
            "path_nodes": digest_rows(db.execute(
                "SELECT n.id,n.status,n.actual_minutes,n.blocked_reason FROM path_nodes n "
                "JOIN learning_paths p ON p.id=n.learning_path_id "
                "WHERE p.owner_public_id=? ORDER BY n.id", (owner,),
            ).fetchall()),
            "wrong_questions": digest_rows(db.execute(
                "SELECT id,quiz_record_id,source_event_id,source_object_id,concept_name," 
                "wrong_reason_category,pinned,notes FROM wrong_questions "
                "WHERE student_id=? ORDER BY id", (USERNAME,),
            ).fetchall()),
            "review_plans": digest_rows(db.execute(
                "SELECT id,concept,review_count,next_review_at FROM review_plans "
                "WHERE student_id=? ORDER BY id", (USERNAME,),
            ).fetchall()),
            "notes": digest_rows(db.execute(
                "SELECT id,lock_version,source,content FROM notes WHERE student_id=? ORDER BY id",
                (USERNAME,),
            ).fetchall()),
        }


def database_audit() -> dict[str, object]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "learning_events": db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
            "generation_jobs": db.execute("SELECT COUNT(*) FROM generation_tasks").fetchone()[0],
            "resources": db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],
        }


def attach_diagnostics(page: Page, report: dict[str, object], fault: dict[str, object]) -> None:
    expected_statuses = {
        (409, "/execute-demo"),
        (503, "/api/v1/m5/assessment/attempts"),
        (503, "/api/v1/interactive-lab/instances/"),
        (503, "/api/v1/feynman/sessions/"),
        (409, "/api/notes/update/"),
    }

    def local(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"blob", "data", "about"} or parsed.hostname in {"127.0.0.1", "localhost", None}

    def on_request(request) -> None:
        if not local(request.url):
            report["external_requests"].append(request.url)

    def on_response(response) -> None:
        if not local(response.url):
            report["external_requests"].append(response.url)
        if response.status < 400:
            return
        item = {"status": response.status, "url": response.url}
        if any(response.status == status and marker in response.url for status, marker in expected_statuses):
            report["expected_http_errors"].append(item)
        else:
            report["http_errors"].append(item)

    def on_failed(request) -> None:
        item = {"url": request.url, "failure": request.failure}
        if request.failure in {"net::ERR_ABORTED", "net::ERR_CANCELED"}:
            return
        if fault.get("restart_active") and request.failure == "net::ERR_CONNECTION_REFUSED":
            report["expected_network_errors"].append(item)
        else:
            report["failed_requests"].append(item)

    def on_console(message) -> None:
        if message.type != "error":
            return
        text = message.text
        if (
            "409" in text
            or "503" in text
            or (fault.get("restart_active") and "ERR_CONNECTION_REFUSED" in text)
        ):
            report["expected_console_errors"].append(text)
        else:
            report["console_errors"].append(text)

    page.on("request", on_request)
    page.on("response", on_response)
    page.on("requestfailed", on_failed)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", on_console)


def visual_metrics(page: Page, root_selector: str = "body") -> dict[str, object]:
    return page.evaluate("""selector => {
      const root = document.querySelector(selector)
      if (!root) return { missingRoot: true }
      const visible = element => {
        const style = getComputedStyle(element), box = element.getBoundingClientRect()
        const closed = element.closest('details:not([open])')
        if (closed && !closed.querySelector(':scope > summary')?.contains(element)) return false
        return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity) > 0
          && box.width > 1 && box.height > 1
      }
      const textNodes = [...root.querySelectorAll('button,a,h1,h2,h3,h4,p,span,strong,small,label,dt,dd,li,time')]
        .filter(element => visible(element) && (element.textContent || '').trim())
      const smallText = textNodes.filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 13.9)
        .map(element => ({ text: element.textContent.trim().slice(0, 70), size: getComputedStyle(element).fontSize })).slice(0, 30)
      const clipped = textNodes.filter(element => {
        const style = getComputedStyle(element)
        if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
        if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
        return element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 6
      }).map(element => element.textContent.trim().slice(0, 70)).slice(0, 30)
      const forbidden = new Set([
        'rgb(16, 185, 129)', 'rgb(34, 197, 94)', 'rgb(59, 130, 246)',
        'rgb(14, 165, 233)', 'rgb(139, 92, 246)', 'rgb(168, 85, 247)',
        'rgb(120, 53, 15)', 'rgb(146, 64, 14)'
      ])
      const forbiddenThemeHits = [...root.querySelectorAll('*')].filter(visible).flatMap(element => {
        const style = getComputedStyle(element)
        return [style.color, style.backgroundColor, style.borderColor]
          .filter(value => forbidden.has(value)).map(value => ({ value, text: element.textContent.trim().slice(0, 50) }))
      })
      const gradients = [...root.querySelectorAll('*')].filter(visible)
        .map(element => getComputedStyle(element).backgroundImage)
        .filter(value => value && value !== 'none' && value.includes('gradient'))
      return {
        missingRoot: false,
        viewport: [innerWidth, innerHeight],
        documentOverflow: document.documentElement.scrollWidth > innerWidth + 1,
        rootOverflow: root.scrollWidth > root.clientWidth + 1,
        bodyTextLength: (root.innerText || '').trim().length,
        smallText, clipped, forbiddenThemeHits, gradients,
      }
    }""", root_selector)


def capture(
    page: Page,
    report: dict[str, object],
    name: str,
    root_selector: str = "body",
    *,
    minimum_text: int = 80,
) -> None:
    path = BROWSER_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    page.wait_for_timeout(250)
    metrics = visual_metrics(page, root_selector)
    report["visual"][name] = metrics
    assert metrics["missingRoot"] is False, metrics
    assert metrics["documentOverflow"] is False, metrics
    assert metrics["rootOverflow"] is False, metrics
    assert metrics["bodyTextLength"] >= minimum_text, metrics
    assert metrics["smallText"] == [], metrics
    assert metrics["clipped"] == [], metrics
    assert metrics["forbiddenThemeHits"] == [], metrics
    assert metrics["gradients"] == [], metrics
    page.screenshot(path=path, full_page=True, animations="disabled")
    report["screenshots"].append(str(path.relative_to(ROOT)))


def record_atom(report: dict[str, object], atom: str, result: str, evidence: list[str]) -> None:
    report["atoms"][atom] = {"status": "PASSED", "result": result, "evidence": evidence}


def create_bundle_from_path(
    page: Page,
    base_url: str,
    report: dict[str, object],
    fault: dict[str, object],
) -> tuple[str, dict, str]:
    page.goto(f"{base_url}/workspace/path?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("path-overview").wait_for(state="visible")
    before = business_state()
    task_buttons = page.get_by_test_id("today-knowledge-points").locator("button")
    assert task_buttons.count() >= 1
    task_buttons.first.click()
    selected = page.get_by_test_id("selected-knowledge-point")
    selected.wait_for(state="visible")
    selected_text = selected.inner_text()
    action = selected.get_by_role("button", name="一键生成完整资源包")
    assert action.is_enabled()
    page.route(
        "**/api/v1/resource-bundles/generation-jobs/*/execute-demo",
        lambda route: route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps(
                {
                    "detail": {
                        "code": "resource_generation.demo_disabled",
                        "message": "总验收暂缓首次自动执行",
                    }
                },
                ensure_ascii=False,
            ),
        ),
    )
    with page.expect_request(lambda request: request.method == "POST" and request.url.endswith("/generation-jobs")) as request_info:
        with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/generation-jobs")) as response_info:
            action.click()
    response = response_info.value
    assert response.status == 201, response.text()
    body = request_info.value.post_data_json
    payload = response.json()
    job_id = str(payload["job_id"])
    page.wait_for_url(f"**/workspace/resources/bundles/{job_id}**", timeout=30_000)
    page.get_by_test_id("resource-bundle-workspace").wait_for(state="visible")
    assert page.locator(".resource-row").count() == 9
    capture(page, report, "01-path-and-bundle/01-created-1440x900.png", '[data-testid="resource-bundle-workspace"]')
    after = business_state()
    for key in ("learning_events", "profile_snapshots", "path_nodes", "wrong_questions", "review_plans", "notes"):
        assert before[key] == after[key], (key, before[key], after[key])
    record_atom(report, "F5F8-R02", "从正式总路径选择今日知识点并创建一个九类资源任务，生成没有冒充学习完成。", [job_id, selected_text])
    return job_id, body, selected_text


def recover_bundle(
    page: Page,
    base_url: str,
    auth: dict[str, str],
    env: dict[str, str],
    port: int,
    process: subprocess.Popen,
    job_id: str,
    request_body: dict,
    report: dict[str, object],
    fault: dict[str, object],
) -> tuple[subprocess.Popen, dict[str, str]]:
    completed = api_post(
        page, base_url, auth,
        f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/feynman/complete",
        {"content": "### 复述任务\n请围绕当前知识点完成两轮解释、真实追问和应用。"},
    )
    preserved_id = next(
        item["resource"]["resource_id"] for item in completed["items"] if item["type"] == "feynman"
    )
    api_post(page, base_url, auth, f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/mind_map/start")
    api_post(
        page, base_url, auth,
        f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/mind_map/fail",
        {"error_code": "total_acceptance_injected", "error_message": "总验收注入的单项失败。"},
    )
    api_post(page, base_url, auth, f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/quiz/start")
    page.reload(wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("bundle-item-mind_map").get_by_role("button", name="重试此项").wait_for(state="visible")
    capture(page, report, "01-path-and-bundle/02-partial-failure-1440x900.png", '[data-testid="resource-bundle-workspace"]')

    fault["restart_active"] = True
    bundle.stop_service(process, port)
    page.evaluate("""async () => {
      try { await fetch('/api/v1/m5/resources?course_id=demo-course-rag-trust-v1') } catch (_) {}
    }""")
    page.wait_for_timeout(500)
    process = bundle.start_service(env, port, OUTPUT_DIR / "backend.log")
    page.reload(wait_until="networkidle", timeout=60_000)
    fault["restart_active"] = False
    page.get_by_role("button", name="恢复中断项").wait_for(state="visible")
    page.unroute("**/api/v1/resource-bundles/generation-jobs/*/execute-demo")
    page.get_by_role("button", name="恢复中断项").click()
    page.get_by_text("完整资源包已就绪", exact=True).wait_for(state="visible", timeout=60_000)
    page.get_by_text("9 / 9 已归档", exact=True).wait_for(state="visible")
    job = bundle.get_job(page, base_url, auth, job_id)
    assert job["status"] == "succeeded", job
    assert [item["type"] for item in job["items"]] == list(RESOURCE_TYPES)
    assert len({item["resource"]["resource_id"] for item in job["items"]}) == 9
    feynman_item = next(item for item in job["items"] if item["type"] == "feynman")
    assert feynman_item["resource"]["resource_id"] == preserved_id
    mind_item = next(item for item in job["items"] if item["type"] == "mind_map")
    assert int(mind_item["attempt"]) >= 2
    capture(page, report, "01-path-and-bundle/03-recovered-1440x900.png", '[data-testid="resource-bundle-workspace"]')

    replay = page.request.post(
        f"{base_url}/api/v1/resource-bundles/generation-jobs",
        headers=bearer(auth), data=request_body,
    )
    assert replay.ok, (replay.status, replay.text())
    replay_job = replay.json()
    assert replay_job["job_id"] == job_id
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM generation_tasks WHERE owner_public_id=? "
            "AND capability='learning_resource_bundle.generate'",
            (owner_id(),),
        ).fetchone()[0]
    assert count == 1, count
    resources = {item["type"]: item["resource"]["resource_id"] for item in job["items"]}
    record_atom(
        report, "F5F8-R03",
        "单项失败、运行中断、真实连接失败和服务重启后恢复同一任务；成功项未重建，原请求重放仍返回同一任务。",
        [job_id, preserved_id, json.dumps({"mind_map_attempt": mind_item["attempt"], "job_count": count})],
    )
    return process, resources


def inspect_resource_center(
    page: Page,
    base_url: str,
    resources: dict[str, str],
    report: dict[str, object],
) -> None:
    before = business_state()
    page.goto(f"{base_url}/workspace/resources?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    root = page.get_by_test_id("resource-center")
    root.wait_for(state="visible")
    root.locator(".resource-item").first.wait_for(state="visible")
    type_buttons = root.locator(".type-option[data-resource-type]:not([data-resource-type='all'])")
    assert type_buttons.count() == 9
    for kind, resource_id in resources.items():
        current_root = page.get_by_test_id("resource-center")
        current_root.wait_for(state="visible")
        outgoing_root = current_root.element_handle()
        assert outgoing_root is not None
        button = current_root.locator(f".type-option[data-resource-type='{kind}']")
        assert int(button.locator("strong").inner_text()) >= 1
        button.click()
        page.wait_for_function("element => !element.isConnected", arg=outgoing_root)
        outgoing_root.dispose()
        page.wait_for_function(
            "expected => new URL(window.location.href).searchParams.get('type') === expected",
            arg=kind,
        )
        page.get_by_test_id("resource-center").wait_for(state="visible")
        page.wait_for_load_state("networkidle")
        page.get_by_test_id("resource-center").locator(
            f"[data-resource-id='{resource_id}']"
        ).wait_for(state="visible")
    current_root = page.get_by_test_id("resource-center")
    outgoing_root = current_root.element_handle()
    assert outgoing_root is not None
    current_root.locator(".type-option[data-resource-type='all']").click()
    page.wait_for_function("element => !element.isConnected", arg=outgoing_root)
    outgoing_root.dispose()
    page.wait_for_function(
        "() => !new URL(window.location.href).searchParams.has('type')"
    )
    page.wait_for_load_state("networkidle")
    root = page.get_by_test_id("resource-center")
    root.wait_for(state="visible")
    handout_item = root.locator(f"[data-resource-id='{resources['handout']}']")
    handout_item.wait_for(state="visible")
    handout_title = handout_item.locator(".resource-main strong").inner_text().strip()
    assert handout_title

    outgoing_root = root.element_handle()
    assert outgoing_root is not None
    search = root.get_by_placeholder("搜索标题、模块、标签或知识点")
    search.fill(handout_title)
    page.wait_for_function(
        "expected => new URL(window.location.href).searchParams.get('q') === expected",
        arg=handout_title,
    )
    page.wait_for_function("element => !element.isConnected", arg=outgoing_root)
    outgoing_root.dispose()
    page.wait_for_load_state("networkidle")
    root = page.get_by_test_id("resource-center")
    root.wait_for(state="visible")
    root.locator(f"[data-resource-id='{resources['handout']}']").wait_for(state="visible")

    outgoing_root = root.element_handle()
    assert outgoing_root is not None
    search = root.get_by_placeholder("搜索标题、模块、标签或知识点")
    search.fill("")
    page.wait_for_function("() => !new URL(window.location.href).searchParams.has('q')")
    page.wait_for_function("element => !element.isConnected", arg=outgoing_root)
    outgoing_root.dispose()
    page.wait_for_load_state("networkidle")
    root = page.get_by_test_id("resource-center")
    root.wait_for(state="visible")
    handout_item = root.locator(f"[data-resource-id='{resources['handout']}']")
    handout_item.wait_for(state="visible")
    assert handout_item.locator(".resource-main strong").inner_text().strip() == handout_title
    handout_item.click()
    preview = page.get_by_test_id("resource-preview")
    preview.get_by_role("heading", name=handout_title, exact=True).wait_for(state="visible")
    history_button = preview.get_by_role("button", name="历史", exact=False)
    history_button.wait_for(state="visible")
    history_button.click()
    page.get_by_test_id("resource-history-drawer").wait_for(state="visible")
    page.get_by_title("关闭版本历史").click()
    page.get_by_title("列表视图").click()
    page.wait_for_function(
        "() => new URL(window.location.href).searchParams.get('view') === 'list'"
    )
    page.wait_for_load_state("networkidle")
    root = page.get_by_test_id("resource-center")
    root.locator(".resource-results.mode-list").wait_for(state="visible")
    page.reload(wait_until="networkidle", timeout=60_000)
    root = page.get_by_test_id("resource-center")
    root.locator(".resource-results.mode-list").wait_for(state="visible")
    capture(page, report, "02-resource-center/01-nine-types-1440x900.png", '[data-testid="resource-center"]', minimum_text=180)
    after = business_state()
    assert before == after, {"before": before, "after": after}
    record_atom(report, "F5F8-R04", "统一资源中心可按九类检索、预览、打开历史并恢复列表视图，全部浏览零学习写入。", list(resources.values()))


def inspect_f5_resources(
    page: Page,
    base_url: str,
    resources: dict[str, str],
    report: dict[str, object],
) -> None:
    before = business_state()
    handout.open_handout(page, base_url, resources["handout"])
    assert page.locator(".outline-panel nav button").count() >= 7
    for marker in ("关键概念", "例子", "反例", "代码", "学习检查", "来源"):
        assert marker in page.get_by_test_id("handout-workspace").inner_text()
    with page.expect_download() as download_info:
        page.get_by_role("button", name="导出 HTML").click()
    export_path = RUNTIME_DIR / "generated-handout.html"
    download_info.value.save_as(export_path)
    assert export_path.stat().st_size > 500
    capture(page, report, "03-f5-resources/01-handout-1440x900.png", '[data-testid="handout-workspace"]', minimum_text=220)

    mindmap.open_mindmap(page, base_url, resources["mind_map"])
    assert page.locator(".mindmap-node").count() >= 6
    search_term = page.locator(".node-panel h2").inner_text().strip()
    assert search_term
    page.get_by_label("搜索思维导图节点").fill(search_term)
    assert page.locator(".search-results button").count() >= 1
    page.get_by_role("button", name="折叠全部分支").click()
    page.get_by_role("button", name="放大导图").click()
    capture(page, report, "03-f5-resources/02-mindmap-1440x900.png", '[data-testid="mindmap-workspace"]')

    training.open_training_task(page, base_url, resources["training_task"])
    assert page.locator(".step-list > li").count() == 4
    assert page.locator(".checkpoint-list > section").count() == 3
    assert page.locator(".deliverable-list > section").count() >= 2
    assert page.locator(".rubric-row").count() == 4
    sandbox_link = page.get_by_role("button", name="进入代码沙盒", exact=False)
    model_link = page.get_by_role("button", name="打开可交互模型", exact=False)
    assert sandbox_link.is_enabled() and model_link.is_enabled()
    capture(page, report, "03-f5-resources/03-training-task-1440x900.png", '[data-testid="training-task-workspace"]')

    page.goto(
        f"{base_url}/workspace/resources/videos/{resources['video']}?course_id={COURSE_ID}",
        wait_until="networkidle", timeout=60_000,
    )
    video_root = page.get_by_test_id("video-recommendation-workspace")
    video_root.wait_for(state="visible")
    video_text = video_root.inner_text()
    assert "来源" in video_text and ("许可" in video_text or "授权" in video_text)
    capture(page, report, "03-f5-resources/04-video-recommendation-1440x900.png", '[data-testid="video-recommendation-workspace"]')

    page.goto(
        f"{base_url}/workspace/resources/decks/{resources['deck']}?course_id={COURSE_ID}",
        wait_until="networkidle", timeout=60_000,
    )
    deck_root = page.get_by_test_id("web-deck-workspace")
    deck_root.wait_for(state="visible")
    assert page.locator(".outline-row").count() >= 5
    page.get_by_role("button", name="下一页", exact=True).click()
    with page.expect_download() as download_info:
        page.get_by_role("button", name="导出 HTML", exact=True).click()
    deck_html = RUNTIME_DIR / "generated-deck.html"
    download_info.value.save_as(deck_html)
    assert deck_html.stat().st_size > 500
    with page.expect_download() as download_info:
        page.get_by_role("button", name="导出 PPTX", exact=True).click()
    deck_pptx = RUNTIME_DIR / "generated-deck.pptx"
    download_info.value.save_as(deck_pptx)
    assert deck_pptx.stat().st_size > 1000
    capture(page, report, "03-f5-resources/05-deck-1440x900.png", '[data-testid="web-deck-workspace"]')

    after = business_state()
    assert before == after, {"before": before, "after": after}
    record_atom(report, "F5F8-R05", "生成讲义具备完整结构和导出，思维导图可搜索、折叠与缩放，两者共享当前课程知识点。", [resources["handout"], resources["mind_map"]])
    record_atom(
        report, "F5F8-R06",
        "实训任务书、代码沙盒、交互模型、视频推荐、五页课件和费曼任务各有正式归宿；视频仅推荐来源，没有生成视频文件。",
        [resources[kind] for kind in ("training_task", "code_sandbox", "interactive_model", "video", "deck", "feynman")],
    )


def seed_model_history(env: dict[str, str], resource_id: str) -> dict[str, str | int]:
    output = RUNTIME_DIR / "interactive-model-history-fixture.json"
    script = f'''
import json
from pathlib import Path
from app.database import DBArtifact, DBArtifactVersion, DBUser, SessionLocal, init_db
from app.m5_resources import ResourceVersionCreateRequest, create_resource_version

init_db()
db = SessionLocal()
try:
    user = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    artifact = db.get(DBArtifact, {resource_id!r})
    if artifact is None or artifact.owner_public_id != user.public_id:
        raise RuntimeError('interactive-model resource is missing')
    versions = db.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).order_by(DBArtifactVersion.version_number).all()
    if len(versions) != 1 or artifact.current_version_id != versions[0].id:
        raise RuntimeError(f'expected one current interactive-model version, got {{len(versions)}}')
    original = versions[0]
    revised = json.loads(original.content)
    revised['summary'] = '总验收历史版本：比较关键词与向量权重对召回、排序质量和延迟的影响。'
    detail = create_resource_version(
        db,
        artifact=artifact,
        actor_public_id=user.public_id,
        request=ResourceVersionCreateRequest(
            expected_lock_version=artifact.lock_version,
            source_version_id=original.id,
            content=json.dumps(revised, ensure_ascii=False),
            content_format='json',
        ),
    )
    db.commit()
    payload = {{
        'resource_id': artifact.id,
        'owner_public_id': user.public_id,
        'initial_version_count': len(detail['interactive_model']['versions']),
    }}
    Path({str(output)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
finally:
    db.close()
'''
    run_python(env, script)
    return json.loads(output.read_text(encoding="utf-8"))


def exercise_quiz(
    page: Page,
    base_url: str,
    resources: dict[str, str],
    report: dict[str, object],
) -> None:
    fixture = {"resource_id": resources["quiz"], "correct_choice": "A"}
    quiz.exercise_primary_flow(page, base_url, fixture, DB_PATH, report)
    record_atom(report, "F5F8-R07", "测验题在资源页完成失败保留、错答、改答、即时解析、来源、追问和刷新历史；提交才形成证据。", [resources["quiz"], "2 practice attempts"])


def exercise_model(
    page: Page,
    base_url: str,
    env: dict[str, str],
    resources: dict[str, str],
    report: dict[str, object],
) -> None:
    fixture = seed_model_history(env, resources["interactive_model"])
    before = model.database_state(DB_PATH, fixture)
    model.open_model(page, base_url, resources["interactive_model"])
    assert page.locator(".parameter-control").count() == 4
    keyword = page.get_by_role("slider", name="关键词权重")
    vector = page.get_by_role("slider", name="向量权重")
    keyword.fill("0.35")
    vector.fill("0.65")
    page.get_by_role("button", name="开始实验", exact=True).click()
    page.get_by_text("实验结果已更新。调参和运行不会写入学习证据。", exact=True).wait_for(state="visible")
    assert model.database_state(DB_PATH, fixture)["observation_events"] == before["observation_events"]
    action_url = "**/api/v1/interactive-lab/instances/*/actions"
    page.route(action_url, lambda route: route.fulfill(
        status=503, content_type="application/json",
        body=json.dumps({"detail": {"message": "总验收注入的实验运行失败"}}, ensure_ascii=False),
    ), times=1)
    keyword.fill("0.4")
    vector.fill("0.6")
    page.get_by_role("button", name="按当前参数运行", exact=True).click()
    page.get_by_text("总验收注入的实验运行失败", exact=True).wait_for(state="visible")
    assert keyword.input_value() == "0.4" and vector.input_value() == "0.6"
    page.get_by_role("button", name="按当前参数运行", exact=True).click()
    page.get_by_text("实验结果已更新。调参和运行不会写入学习证据。", exact=True).wait_for(state="visible")
    observation = "提高关键词权重后结果排序发生变化，仍需结合召回、延迟和当前课程目标判断。"
    field = page.get_by_role("textbox", name="观察结论")
    field.fill(observation)
    page.route(action_url, lambda route: route.fulfill(
        status=503, content_type="application/json",
        body=json.dumps({"detail": {"message": "总验收注入的观察提交失败"}}, ensure_ascii=False),
    ), times=1)
    page.get_by_role("button", name="提交观察结论", exact=True).click()
    page.get_by_text("总验收注入的观察提交失败", exact=True).wait_for(state="visible")
    assert field.input_value() == observation
    page.get_by_role("button", name="提交观察结论", exact=True).click()
    page.get_by_test_id("interactive-model-completion").wait_for(state="visible")
    after = model.database_state(DB_PATH, fixture)
    assert after["observation_events"] == before["observation_events"] + 1
    page.reload(wait_until="networkidle", timeout=60_000)
    assert page.get_by_role("textbox", name="观察结论").input_value() == observation
    history = page.get_by_test_id("resource-toolbar").get_by_role("button", name="版本历史", exact=False)
    history.click()
    drawer = page.get_by_test_id("resource-history-drawer")
    drawer.wait_for(state="visible")
    version_count = drawer.locator(".history-list li").count()
    assert version_count >= 1
    restore_button = drawer.get_by_role("button", name="恢复为当前", exact=True).first
    restore_button.wait_for(state="visible")
    restore_button.click()
    drawer.wait_for(state="hidden")
    expected_version_count = int(fixture["initial_version_count"]) + 1
    version_line = page.get_by_test_id("resource-toolbar").locator(".toolbar-identity p")
    version_line.filter(has_text=f"v{expected_version_count}").wait_for(state="visible")
    assert model.database_state(DB_PATH, fixture)["resource_versions"] == expected_version_count
    capture(page, report, "04-f6-training/01-interactive-model-1440x900.png", '[data-testid="interactive-lab-workspace"]')
    record_atom(report, "F5F8-R08", "交互模型完成调参、运行、失败保留、观察提交、刷新和历史另存；只有观察提交形成一条证据。", [resources["interactive_model"], observation])


def revise_code_resource(env: dict[str, str], resource_id: str, action: str) -> dict[str, object]:
    output = RUNTIME_DIR / f"code-{action}.json"
    error_code = code_review.ERROR_CODE
    script = f'''
import json
from pathlib import Path
from app.database import DBArtifact, DBArtifactVersion, DBUser, SessionLocal, init_db
from app.m5_resources import ResourceVersionCreateRequest, ResourceVersionRestoreRequest, create_resource_version, restore_resource_version
init_db()
db = SessionLocal()
try:
    user = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    artifact = db.get(DBArtifact, {resource_id!r})
    if artifact is None or artifact.owner_public_id != user.public_id:
        raise RuntimeError('sandbox resource is missing')
    versions = db.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).order_by(DBArtifactVersion.version_number).all()
    if {action!r} == 'error':
        current = db.get(DBArtifactVersion, artifact.current_version_id)
        payload = json.loads(current.content)
        payload['files'][0]['content'] = {error_code!r}
        create_resource_version(db, artifact=artifact, actor_public_id=user.public_id, request=ResourceVersionCreateRequest(
            expected_lock_version=artifact.lock_version,
            source_version_id=current.id,
            content=json.dumps(payload, ensure_ascii=False),
            content_format='json',
        ))
    else:
        restore_resource_version(db, artifact=artifact, actor_public_id=user.public_id, request=ResourceVersionRestoreRequest(
            expected_lock_version=artifact.lock_version,
            version_id=versions[0].id,
        ))
    db.commit()
    payload = {{
        'resource_id': artifact.id,
        'owner_public_id': user.public_id,
        'initial_version_count': db.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).count(),
    }}
    Path({str(output)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
finally:
    db.close()
'''
    run_python(env, script)
    return json.loads(output.read_text(encoding="utf-8"))


def exercise_code(
    page: Page,
    base_url: str,
    env: dict[str, str],
    resources: dict[str, str],
    report: dict[str, object],
) -> None:
    fixture = revise_code_resource(env, resources["code_sandbox"], "error")
    code_review.run_error_review_apply_rerun(page, base_url, fixture, DB_PATH, report)
    fixture = revise_code_resource(env, resources["code_sandbox"], "restore")
    before = sandbox.database_state(DB_PATH, fixture)
    sandbox.open_sandbox(page, base_url, resources["code_sandbox"])
    assert sandbox.assert_three_columns(page) == [0.22, 0.5, 0.28]
    standard_input = page.locator(".stdin-panel textarea")
    standard_input.fill("0.60")
    page.get_by_role("button", name="保存新版本", exact=True).click()
    page.get_by_text("代码和标准输入已另存为新版本。请基于新版本重新运行。", exact=True).wait_for(state="visible")
    previous_run_count = page.locator(".run-history > button").count()
    page.get_by_role("button", name="运行代码", exact=True).click()
    page.wait_for_function(
        "previous => document.querySelectorAll('.run-history > button').length > previous",
        arg=previous_run_count,
        timeout=60_000,
    )
    page.locator(".result-summary").get_by_text("运行成功", exact=True).wait_for(state="visible", timeout=60_000)
    page.wait_for_function(
        """() => {
          const output = document.querySelector('.terminal-output')?.textContent || '';
          return output.includes('threshold=0.60') && output.includes('validation_accuracy=');
        }""",
        timeout=60_000,
    )
    page.get_by_role("button", name="图表", exact=False).click()
    plot = page.locator(".plot-viewer img")
    plot.wait_for(state="visible")
    assert plot.evaluate("image => image.naturalWidth > 0 && image.naturalHeight > 0")
    page.get_by_role("button", name="AI 点评", exact=True).click()
    page.get_by_text("真实证据已就绪", exact=True).wait_for(state="visible")
    assert page.get_by_test_id("code-review-panel").get_by_text("runAttemptId", exact=False).count() >= 1
    page.get_by_role("button", name="完成学习", exact=True).click()
    page.get_by_text("完成证据已记录", exact=False).wait_for(state="visible")
    after = sandbox.database_state(DB_PATH, fixture)
    assert after["completion_events"] == before["completion_events"] + 1
    page.reload(wait_until="networkidle", timeout=60_000)
    page.get_by_text("本次学习已完成", exact=True).wait_for(state="visible")
    capture(page, report, "04-f6-training/02-code-complete-1440x900.png", '[data-testid="code-sandbox-workspace"]')
    record_atom(
        report, "F5F8-R09",
        "同一沙盒先真实报错并生成绑定运行证据的点评，应用建议后重跑成功；随后恢复任务代码、输出图表并记录一次完成证据。",
        [resources["code_sandbox"], "runtime_error -> review -> applied version -> successful rerun -> completion"],
    )


def exercise_feynman(
    page: Page,
    base_url: str,
    resources: dict[str, str],
    report: dict[str, object],
) -> str:
    fixture = {"resource_id": resources["feynman"], "owner_public_id": owner_id()}
    session_id = feynman.complete_journey(page, base_url, fixture, DB_PATH, report)
    record_atom(report, "F5F8-R10", "费曼任务按第一轮、评价、真实追问、来源回答、第二轮、对比和应用顺序完成；评价失败与刷新均保留原文。", [resources["feynman"], session_id])
    return session_id


def seed_formal_questions(env: dict[str, str], job_id: str) -> dict[str, object]:
    output = RUNTIME_DIR / "formal-question-fixture.json"
    script = f'''
import json
from pathlib import Path
from app.database import DBAssessmentQuestion, DBGenerationTask, DBTaskEvent, DBUser, SessionLocal, init_db
from app.m5_assessment_core import QuestionVersionInput, create_question_version
init_db()
db = SessionLocal()
try:
    user = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    task = db.get(DBGenerationTask, {job_id!r})
    event = db.query(DBTaskEvent).filter_by(task_id=task.id, event_type='resource_generation.requested').one()
    manifest = dict((event.payload or {{}}).get('manifest') or {{}})
    point_id = str(manifest.get('knowledge_point_id') or 'demo-kp-07')
    source_ids = list(manifest.get('source_ref_ids') or ['demo-ref-07'])
    source_id = str(source_ids[0])
    specs = [
        ('true_false', '可信学习结论必须能够回查冻结课程来源。', (), {{'value': True}}),
        ('short_answer', '说明混合检索为什么需要来源约束与结果重排。', (), {{'reference_answer': '混合检索合并关键词与向量候选，并通过来源约束与重排保持结果可核查。'}}),
    ]
    created = []
    for question_type, prompt, options, answer_key in specs:
        scoring_rule = {{'version': 'total-acceptance-v1', 'correct_threshold': 0.6}}
        if question_type == 'short_answer':
            scoring_rule['criteria'] = [{{'id': 'coverage', 'label': '关键概念覆盖', 'weight': 1.0}}]
        question, version = create_question_version(
            db,
            owner_public_id=user.public_id,
            course_id={COURSE_ID!r},
            question_type=question_type,
            origin='manual',
            version=QuestionVersionInput(
                prompt=prompt,
                options=options,
                answer_key=answer_key,
                scoring_rule=scoring_rule,
                explanation='答案必须同时说明机制、来源边界和可验证方式。',
                misconception_tags=('evidence_boundary',),
                primary_knowledge_point_id=point_id,
                expert_difficulty=0.5,
                source_ref_ids=(source_id,),
            ),
        )
        question.status = 'approved'
        created.append(version.id)
    db.commit()
    payload = {{'owner_public_id': user.public_id, 'point_id': point_id, 'source_ref_id': source_id, 'created_versions': created}}
    Path({str(output)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
finally:
    db.close()
'''
    run_python(env, script)
    return json.loads(output.read_text(encoding="utf-8"))


def create_trusted_gate_evidence(env: dict[str, str], job_id: str) -> dict[str, object]:
    output = RUNTIME_DIR / "gate-evidence.json"
    script = f'''
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app.database import DBGenerationTask, DBPathNode, DBTaskEvent, DBUser, SessionLocal, init_db
from app.exam_gate import exam_gate_status
from app.m5_learning import LearningEventInput, process_path_event, record_learning_event
init_db()
db = SessionLocal()
try:
    user = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    task = db.get(DBGenerationTask, {job_id!r})
    requested = db.query(DBTaskEvent).filter_by(task_id=task.id, event_type='resource_generation.requested').one()
    snapshot = dict((requested.payload or {{}}).get('manifest', {{}}).get('exam_gate') or {{}})
    before = exam_gate_status(db, owner_public_id=user.public_id, course_id={COURSE_ID!r})
    if before.get('unlocked'):
        raise RuntimeError('gate unexpectedly unlocked before trusted completion')
    event_ids = []
    moment = datetime.now(timezone.utc) + timedelta(seconds=1)
    for index, item in enumerate(snapshot.get('required_tasks') or [], start=1):
        node = db.get(DBPathNode, item['id'])
        event, _ = record_learning_event(
            db,
            owner_public_id=user.public_id,
            user=user,
            trusted_source=True,
            event=LearningEventInput(
                idempotency_key=f'total-acceptance-complete-{{node.id}}',
                event_type='quiz_answered',
                course_id={COURSE_ID!r},
                object_type='path_target',
                object_id=node.target_object_id or node.id,
                source='backend',
                context={{'userId': user.public_id, 'courseId': {COURSE_ID!r}, 'taskId': node.id}},
                occurred_at=moment + timedelta(seconds=index),
                payload={{'graded': True, 'correct': True, 'attempt_id': f'total-gate-{{index}}'}},
            ),
        )
        process_path_event(db, event=event)
        event_ids.append(event.id)
    db.commit()
    after = exam_gate_status(db, owner_public_id=user.public_id, course_id={COURSE_ID!r})
    if not after.get('unlocked'):
        raise RuntimeError(after)
    Path({str(output)!r}).write_text(json.dumps({{'before': before, 'after': after, 'event_ids': event_ids}}, ensure_ascii=False), encoding='utf-8')
finally:
    db.close()
'''
    run_python(env, script)
    return json.loads(output.read_text(encoding="utf-8"))


def complete_formal_exam(
    page: Page,
    base_url: str,
    report: dict[str, object],
) -> tuple[str, dict[str, object]]:
    formal.open_exam_builder(page, base_url)
    formal.clear_optional_type(page, "多选题")
    formal.clear_optional_type(page, "填空题")
    page.get_by_label("检验主题").fill("混合检索、来源约束与可核查结论")
    page.get_by_role("button", name="生成并冻结试卷", exact=True).click()
    page.get_by_test_id("generated-exam-preview").wait_for(state="visible")
    assert page.get_by_text("正确答案", exact=True).count() == 0
    exam_id = page.url.split("/workspace/assessment/exams/", 1)[1].split("?", 1)[0]
    page.get_by_role("button", name="开始作答", exact=True).click()
    page.locator(".option-list button").nth(1).click()
    formal.save_current(page)
    page.reload(wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("exam-taking").wait_for(state="visible")
    assert page.locator(".question-nav button.saved").count() == 1
    page.locator(".option-list button").nth(1).click()
    formal.save_current(page)
    page.get_by_role("button", name="正确", exact=True).click()
    formal.save_current(page)
    page.locator(".answer-stage textarea").fill("我还不能完整说明来源约束和重排之间的关系。")
    formal.save_current(page, last=True)
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="提交试卷", exact=True).click()
    page.get_by_test_id("formal-exam-report").wait_for(state="visible", timeout=60_000)
    for label in ("学习画像", "学习路径", "下一日安排", "错题本", "复习中心"):
        assert page.get_by_text(label, exact=True).count() >= 1, label
    formal.focus_report(page)
    capture(page, report, "05-formal-exam/01-report-1440x900.png", '[data-testid="formal-exam-report"]', minimum_text=220)
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        event = db.execute(
            "SELECT id FROM learning_events WHERE owner_public_id=? AND event_type='formal_exam_submitted' "
            "ORDER BY occurred_at DESC,id DESC LIMIT 1", (owner_id(),),
        ).fetchone()
        assert event is not None
        consumption = db.execute(
            "SELECT id,status,result FROM learning_event_consumptions WHERE learning_event_id=?", (event[0],),
        ).fetchone()
        assert consumption and consumption[1] == "processed", consumption
        result = json.loads(consumption[2] or "{}")
    return exam_id, {"event_id": event[0], "consumption_id": consumption[0], "result": result}


def exercise_formal_exam(
    page: Page,
    base_url: str,
    env: dict[str, str],
    job_id: str,
    report: dict[str, object],
) -> tuple[str, dict[str, object]]:
    page.goto(f"{base_url}/workspace/assessment/exams?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("exam-gate-locked").wait_for(state="visible")
    assert page.get_by_role("button", name="生成并冻结试卷", exact=True).count() == 0
    assert page.get_by_text("可选资源不会阻塞解锁", exact=False).is_visible()
    assert page.locator(".missing-list > button").count() > 0
    seed_formal_questions(env, job_id)
    gate = create_trusted_gate_evidence(env, job_id)
    assert gate["before"]["unlocked"] is False and gate["after"]["unlocked"] is True
    exam_id, formal_event = complete_formal_exam(page, base_url, report)
    state = formal.database_state(DB_PATH, owner_id())
    assert state["submission_event_count"] == 1
    assert state["consumption_status"] == "processed"
    assert state["wrong_question_count"] >= 1 and state["review_plan_count"] >= 1
    record_atom(
        report, "F5F8-R11",
        "智能组卷先显示缺失必做任务，可信完成证据齐备后解锁；配置、冻结、刷新草稿、交卷、报告及五类反馈来自同一交卷事件。",
        [exam_id, str(formal_event["event_id"]), json.dumps(gate, ensure_ascii=False)],
    )
    return exam_id, formal_event


def formal_feedback_token(formal_event: dict[str, object]) -> str:
    result = dict(formal_event.get("result") or {})
    token = str(result.get("consistency_token") or result.get("token") or "")
    if token:
        return token
    state = feedback.aggregation_state(str(formal_event["event_id"]))
    return str(state.get("token") or "")


def exercise_feedback(
    page: Page,
    base_url: str,
    env: dict[str, str],
    port: int,
    process: subprocess.Popen,
    formal_event: dict[str, object],
    report: dict[str, object],
    fault: dict[str, object],
) -> subprocess.Popen:
    token = formal_feedback_token(formal_event)
    assert token
    feedback.scan_routes(page, base_url, report, expected_token=token, viewport_label="1440x900")
    formal.force_recoverable_projection(DB_PATH, owner_id())
    fault["restart_active"] = True
    bundle.stop_service(process, port)
    process = bundle.start_service(env, port, OUTPUT_DIR / "backend.log")
    try:
        page.reload(wait_until="networkidle", timeout=60_000)
        recovered = feedback.recover_partial(
            page, base_url, {"event_id": formal_event["event_id"]}, report,
        )
        assert recovered
        page.set_viewport_size({"width": 1366, "height": 768})
        feedback.scan_routes(page, base_url, report, expected_token=recovered, viewport_label="1366x768")
        page.set_viewport_size({"width": 1440, "height": 900})
        record_atom(report, "F5F8-R15", "正式组卷反馈在首页、画像、路径、错题、复习和历史六页读取同一一致性令牌与下一日安排。", [token, recovered])
        return process
    except BaseException:
        try:
            bundle.stop_service(process, port)
        except Exception as cleanup_error:
            report.setdefault("cleanup_errors", []).append(
                f"replacement service cleanup failed: {cleanup_error}"
            )
        raise
    finally:
        fault["restart_active"] = False


def exercise_documents(
    page: Page,
    base_url: str,
    fixture: dict[str, object],
    report: dict[str, object],
) -> None:
    before = business_state()
    before_events = learning_event_rows()
    reader.verify_text_reader(page, base_url, fixture, report)
    after_text = business_state()
    after_text_events = learning_event_rows()
    assert {
        event_id: after_text_events.get(event_id)
        for event_id in before_events
    } == before_events
    added_event_ids = set(after_text_events) - set(before_events)
    assert len(added_event_ids) == 1, added_event_ids
    added_event = after_text_events[added_event_ids.pop()]
    assert added_event[:7] == (
        "note.created", "none", 0, "none", "note_workspace", "note", "created",
    ), added_event
    added_payload = json.loads(added_event[7] or "{}")
    assert added_payload.get("mastery_updated") is False, added_payload
    for key in ("profile_snapshots", "path_nodes", "wrong_questions", "review_plans"):
        assert after_text[key] == before[key], (key, before[key], after_text[key])
    reader.verify_image_reader(page, base_url, fixture, report)
    after_image = business_state()
    assert learning_event_rows() == after_text_events
    for key in ("profile_snapshots", "path_nodes", "wrong_questions", "review_plans"):
        assert after_image[key] == before[key], (key, before[key], after_image[key])
    record_atom(
        report, "F5F8-R12",
        "预置书架无需上传即可进入大阅读器；文本划选与图片框选/OCR失败均保留精确来源、问题、缩放和选区并可刷新恢复。",
        [str(fixture["source_id"]), str(fixture["pdf_source_id"])],
    )


def create_resource_notes(page: Page, base_url: str, resources: dict[str, str]) -> None:
    handout.open_handout(page, base_url, resources["handout"])
    page.get_by_test_id("resource-toolbar").get_by_role("button", name="记笔记", exact=True).click()
    notes.wait_for_notes(page)
    sandbox.open_sandbox(page, base_url, resources["code_sandbox"])
    page.get_by_role("button", name="保存当前代码版本的来源笔记", exact=True).click()
    notes.wait_for_notes(page)


def latest_review_plan() -> dict[str, object]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        row = db.execute(
            "SELECT id,next_review_at,concept FROM review_plans "
            "WHERE student_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
            (USERNAME,),
        ).fetchone()
        assert row is not None
    raw = str(row[1])
    moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local_day = moment.astimezone().date()
    return {
        "id": row[0],
        "course_id": COURSE_ID,
        "date": local_day.isoformat(),
        "month": local_day.strftime("%Y-%m"),
        "knowledge_point": row[2],
    }


def open_review_plan(page: Page, base_url: str, plan: dict[str, object]) -> None:
    query = urlencode({"course_id": COURSE_ID, "month": plan["month"], "date": plan["date"]})
    page.goto(f"{base_url}/workspace/review?{query}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("review-schedule-board").wait_for(state="visible")
    page.get_by_test_id("review-calendar-loading").wait_for(state="hidden")


def create_review_note(page: Page, base_url: str, plan: dict[str, object]) -> None:
    open_review_plan(page, base_url, plan)
    task = page.locator(f"[data-task-id='review-plan:{plan['id']}']")
    if not task.count():
        task = page.locator(".review-task").filter(has_text=str(plan["knowledge_point"])).first
    task.get_by_role("button", name="去复习", exact=True).click()
    note_button = task.get_by_role("button", name="记笔记", exact=True)
    note_button.wait_for(state="visible")
    note_button.click()
    notes.wait_for_notes(page)


def selection_note_id() -> str:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        row = db.execute(
            "SELECT id FROM notes WHERE student_id=? AND source='knowledge_selection' "
            "ORDER BY created_at DESC,id DESC LIMIT 1", (USERNAME,),
        ).fetchone()
        assert row is not None
        return str(row[0])


def exercise_notes(
    page: Page,
    base_url: str,
    resources: dict[str, str],
    plan: dict[str, object],
    report: dict[str, object],
) -> None:
    create_resource_notes(page, base_url, resources)
    create_review_note(page, base_url, plan)
    note_id = selection_note_id()
    page.goto(f"{base_url}/workspace/notes?note_id={note_id}", wait_until="networkidle", timeout=60_000)
    notes.wait_for_notes(page)
    source_labels = page.locator(".note-list-item .source-label").all_inner_texts()
    for expected in ("知识库选区", "个性化讲义", "代码沙盒", "复习任务"):
        assert expected in source_labels, (expected, source_labels)
    before_browse = business_state()
    before_browse_events = learning_event_rows()
    page.get_by_placeholder("搜索正文、概念或标签").fill("教材")
    page.get_by_placeholder("搜索正文、概念或标签").fill("")
    page.get_by_role("button", name="编辑", exact=True).click()
    editor = page.get_by_role("textbox", name="笔记正文", exact=True)
    draft = "# 来源笔记总验收\n\n保留原文选区，同时记录我对来源边界的理解。"
    editor.fill(draft)
    page.reload(wait_until="networkidle", timeout=60_000)
    notes.wait_for_notes(page)
    assert page.get_by_role("textbox", name="笔记正文", exact=True).input_value() == draft
    stale = notes.fetch_note(page, note_id)
    update = notes.external_update(page, stale)
    assert update["status"] == 200
    page.get_by_role("button", name="保存新版本", exact=True).click()
    conflict = page.get_by_test_id("notes-conflict")
    conflict.wait_for(state="visible")
    assert page.get_by_role("textbox", name="笔记正文", exact=True).input_value() == draft
    conflict.get_by_role("button", name="同步最新版本", exact=True).click()
    conflict.wait_for(state="hidden")
    page.get_by_role("button", name="保存新版本", exact=True).click()
    page.get_by_text("已保存为版本", exact=False).wait_for(state="visible")
    ai = page.get_by_test_id("notes-ai-suggestion")
    ai.get_by_role("button", name="生成排版建议", exact=True).click()
    ai.get_by_role("button", name="应用并另存新版本", exact=True).wait_for(state="visible", timeout=60_000)
    saved = notes.fetch_note(page, note_id)
    assert saved["ai_suggestion"] and saved["content"] == draft
    ai.get_by_role("button", name="应用并另存新版本", exact=True).click()
    page.get_by_text("AI 建议已作为版本", exact=False).wait_for(state="visible")
    version_one = page.get_by_test_id("notes-history").locator(".version-row").filter(has_text="版本 1")
    page.once("dialog", lambda dialog: dialog.accept())
    version_one.get_by_role("button", name="将版本 1 另存为新版本", exact=True).click()
    page.get_by_text("版本 1 已另存为版本", exact=False).wait_for(state="visible")
    capture(page, report, "07-notes/01-four-sources-and-history-1440x900.png", '[data-testid="notes-workspace"]', minimum_text=180)
    after = business_state()
    after_events = learning_event_rows()
    assert {
        event_id: after_events.get(event_id)
        for event_id in before_browse_events
    } == before_browse_events
    note_events = [after_events[event_id] for event_id in set(after_events) - set(before_browse_events)]
    assert sorted(event[0] for event in note_events) == sorted([
        "note.saved", "note.saved", "note.ai_suggestion_created",
        "note.ai_suggestion_applied", "note.restored",
    ]), note_events
    for event in note_events:
        assert event[1:6] == ("none", 0, "none", "note_workspace", "note"), event
        assert json.loads(event[7] or "{}").get("mastery_updated") is False, event
    for key in ("profile_snapshots", "path_nodes", "wrong_questions", "review_plans"):
        assert after[key] == before_browse[key], (key, before_browse[key], after[key])
    record_atom(report, "F5F8-R13", "知识库选区、讲义、代码沙盒和复习四类笔记统一可达；本地草稿、409冲突、AI建议分离和历史另存均保留用户正文。", [note_id, *source_labels])


def exercise_wrong_questions(
    page: Page,
    base_url: str,
    report: dict[str, object],
) -> None:
    page.goto(f"{base_url}/workspace/review/wrong-questions?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("wrong-question-workspace").wait_for(state="visible")
    page.get_by_label("错题加载中").wait_for(state="hidden")
    rows = page.get_by_test_id("wrong-question-list-item")
    assert rows.count() >= 1
    merged = rows.filter(has_text="测验题资源").filter(has_text="智能组卷")
    assert merged.count() == 1, "no unique wrong question merged practice and formal attempts"
    merged.first.click()
    page.wait_for_function(
        "element => element?.getAttribute('aria-current') === 'true'",
        arg=merged.first.element_handle(),
    )
    history = page.get_by_test_id("wrong-question-attempt-history")
    history.wait_for(state="visible")
    history_text = history.inner_text()
    assert "测验题资源" in history_text and "智能组卷" in history_text, history_text
    before_attempts = history.locator(".attempt-list li").count()
    assert before_attempts >= 2
    sources = page.get_by_test_id("wrong-question-sources")
    if not sources.get_attribute("open"):
        sources.locator("summary").click()
    assert sources.get_by_role("button").count() >= 1
    diagnosis = page.get_by_test_id("wrong-question-diagnosis")
    accept = diagnosis.get_by_role("button", name="接受候选", exact=True)
    if accept.count() and accept.is_visible():
        accept.click()
        page.get_by_text("已记录你的决定", exact=True).wait_for(state="visible")
    page.get_by_test_id("wrong-question-primary-action").click()
    redo = page.get_by_test_id("wrong-question-redo")
    redo.wait_for(state="visible")
    correct = page.locator(".answer-overview > div").nth(1).locator("strong").inner_text().strip()
    option = redo.locator(f"input[type='radio'][value='{correct}']")
    assert option.count() == 1, correct
    option.check()
    redo.get_by_role("button", name="提交并判分", exact=True).click()
    redo.get_by_text("回答正确，新的强证据已进入学习聚合。", exact=True).wait_for(state="visible", timeout=60_000)
    assert history.locator(".attempt-list li").count() == before_attempts + 1
    page.reload(wait_until="networkidle", timeout=60_000)
    page.get_by_label("错题加载中").wait_for(state="hidden")
    capture(page, report, "08-wrong-review/01-merged-wrong-question-1440x900.png", '[data-testid="wrong-question-workspace"]', minimum_text=220)


def exercise_review(
    page: Page,
    base_url: str,
    plan: dict[str, object],
    report: dict[str, object],
) -> None:
    open_review_plan(page, base_url, plan)
    board = page.get_by_test_id("review-schedule-board")
    assert board.locator(".review-day").count() == 42
    before = business_state()
    board.get_by_role("button", name="查看上个月").click()
    board.get_by_role("button", name="查看下个月").click()
    board.locator("select[aria-label='筛选复习课程']").select_option(COURSE_ID)
    board.locator(f".review-day[data-date='{plan['date']}']").click()
    after_browse = business_state()
    assert before == after_browse
    task = board.locator(f"[data-task-id='review-plan:{plan['id']}']")
    if not task.count():
        task = page.locator(".review-task").filter(has_text=str(plan["knowledge_point"])).first
    task.get_by_role("button", name="去复习").click()
    confidence = task.get_by_text("一般", exact=True)
    if confidence.count():
        confidence.click()
    minutes = task.locator("input[type='number']")
    if minutes.count():
        minutes.fill("12")
    task.get_by_role("button", name="完成复习并更新安排").click()
    page.get_by_text("复习已完成", exact=False).wait_for(state="visible", timeout=60_000)
    board.get_by_role("button", name="复习工具与历史").click()
    page.locator("#legacy-review-tools[open]").wait_for(state="visible")
    capture(page, report, "08-wrong-review/02-review-calendar-1440x900.png", '[data-testid="review-schedule-board"]', minimum_text=180)
    record_atom(report, "F5F8-R14", "同一道错题合并测验题与智能组卷历史并完成错因确认、来源查看和重做；真实42格月历浏览零写入，完成复习后才产生证据。", [str(plan["id"]), str(plan["date"])])


def verify_protected_pages(page: Page, base_url: str, report: dict[str, object]) -> None:
    checks = {
        "/profile/learning": ("学习画像", ("证据", "掌握")),
        f"/workspace/path?course_id={COURSE_ID}": ("学习路径", ("今日", "任务")),
        "/workspace/notes": ("笔记", ("搜索", "历史")),
        f"/workspace/review/wrong-questions?course_id={COURSE_ID}": ("错题", ("作答历史",)),
    }
    before = business_state()
    for index, (route, (title, markers)) in enumerate(checks.items(), start=1):
        page.goto(f"{base_url}{route}", wait_until="networkidle", timeout=60_000)
        body = page.locator("body").inner_text()
        assert title in body and all(marker in body for marker in markers), (route, title, markers, body[:1000])
        if route.startswith("/workspace/review/wrong-questions"):
            filters = page.get_by_test_id("wrong-question-filters")
            filters.wait_for(state="visible")
            for label in ("知识点", "来源", "状态"):
                assert filters.get_by_role("combobox", name=label, exact=True).count() == 1, label
            source_filter = filters.get_by_role("combobox", name="来源", exact=True)
            source_filter.select_option("formal_exam")
            assert page.get_by_test_id("wrong-question-list-item").count() >= 1
            source_filter.select_option("all")
            page.get_by_test_id("wrong-question-attempt-history").wait_for(state="visible")
        capture(page, report, f"09-protection/{index:02d}-{title}-1440x900.png", "body", minimum_text=200)
    after = business_state()
    assert before == after, {"before": before, "after": after}
    record_atom(report, "F5F8-R17", "学习画像、学习路径、笔记本和错题本四个7.20保护页仍有证据/任务/搜索历史/筛选作答等实质能力，普通浏览零写入。", list(checks))


def verify_secondary_viewport(
    page: Page,
    base_url: str,
    resources: dict[str, str],
    report: dict[str, object],
) -> None:
    page.set_viewport_size({"width": 1366, "height": 768})
    routes = [
        (f"/workspace/resources?course_id={COURSE_ID}", '[data-testid="resource-center"]', "resource-center"),
        (f"/workspace/resources/handouts/{resources['handout']}?course_id={COURSE_ID}", '[data-testid="handout-workspace"]', "handout"),
        (f"/workspace/resources/mindmaps/{resources['mind_map']}?course_id={COURSE_ID}", '[data-testid="mindmap-workspace"]', "mindmap"),
        (f"/workspace/code/{resources['code_sandbox']}?course_id={COURSE_ID}", '[data-testid="code-sandbox-workspace"]', "code"),
        (f"/workspace/review/wrong-questions?course_id={COURSE_ID}", '[data-testid="wrong-question-workspace"]', "wrong-questions"),
        (f"/workspace/review?course_id={COURSE_ID}", '[data-testid="review-schedule-board"]', "review"),
    ]
    before = business_state()
    for index, (route, root, label) in enumerate(routes, start=1):
        page.goto(f"{base_url}{route}", wait_until="networkidle", timeout=60_000)
        page.locator(root).wait_for(state="visible")
        capture(page, report, f"10-secondary/{index:02d}-{label}-1366x768.png", root, minimum_text=120)
    after = business_state()
    assert before == after
    page.set_viewport_size({"width": 1440, "height": 900})


def validate_diagnostics(report: dict[str, object]) -> None:
    assert report["http_errors"] == [], report["http_errors"]
    assert report["failed_requests"] == [], report["failed_requests"]
    assert report["page_errors"] == [], report["page_errors"]
    assert report["console_errors"] == [], report["console_errors"]
    assert report["external_requests"] == [], report["external_requests"]
    expected = report["expected_http_errors"]
    assert any(item["status"] == 409 and "/execute-demo" in item["url"] for item in expected)
    assert any(item["status"] == 503 and "/assessment/attempts" in item["url"] for item in expected)
    assert len([item for item in expected if item["status"] == 503 and "/interactive-lab/instances/" in item["url"]]) == 2
    assert any(item["status"] == 503 and "/feynman/sessions/" in item["url"] for item in expected)
    assert any(item["status"] == 409 and "/api/notes/update/" in item["url"] for item in expected)
    assert len(report["expected_network_errors"]) >= 1


def run(report: dict[str, object]) -> dict[str, object]:
    reset_output()
    configure_helpers()
    port = free_port()
    env = runtime_env(port)
    base_url = f"http://127.0.0.1:{port}"
    formal_before = file_record(FORMAL_DB)
    document_fixture = seed_runtime(env)
    report.update({
        "schema_version": "f5-f8.total-acceptance.v1",
        "status": "RUNNING",
        "started_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "runtime": {"database": str(DB_PATH.relative_to(ROOT)), "port": port, "browser_instances": 1},
        "fixture": {"owner_public_id": owner_id(), "course_id": COURSE_ID, **document_fixture},
        "atoms": {},
        "checks": {},
        "database": {},
        "visual": {},
        "feedback_snapshots": {},
        "screenshots": [],
        "http_errors": [],
        "expected_http_errors": [],
        "failed_requests": [],
        "expected_network_errors": [],
        "page_errors": [],
        "console_errors": [],
        "expected_console_errors": [],
        "external_requests": [],
        "expected_injected_failures": [],
        "expected_injected_console": [],
        "formal_database_before": formal_before,
    })
    process: subprocess.Popen | None = None
    fault: dict[str, object] = {"restart_active": False}
    try:
        process = bundle.start_service(env, port, OUTPUT_DIR / "backend.log")
        with sync_playwright() as playwright:
            browser: Browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN", accept_downloads=True)
                page = context.new_page()
                page.set_default_timeout(30_000)
                attach_diagnostics(page, report, fault)
                auth = login(page, base_url)
                record_atom(report, "F5F8-R01", "同一匿名学生、隔离SQLite、一个Chromium实例和受控服务生命周期开始连续总旅程。", [str(DB_PATH), str(port)])

                job_id, request_body, _ = create_bundle_from_path(page, base_url, report, fault)
                process, resources = recover_bundle(
                    page, base_url, auth, env, port, process, job_id, request_body, report, fault,
                )
                report["fixture"].update({"job_id": job_id, "resources": resources})
                inspect_resource_center(page, base_url, resources, report)
                inspect_f5_resources(page, base_url, resources, report)
                exercise_quiz(page, base_url, resources, report)
                exercise_model(page, base_url, env, resources, report)
                exercise_code(page, base_url, env, resources, report)
                exercise_feynman(page, base_url, resources, report)
                exercise_documents(page, base_url, document_fixture, report)
                exam_id, formal_event = exercise_formal_exam(page, base_url, env, job_id, report)
                report["fixture"].update({"exam_id": exam_id, "formal_event_id": formal_event["event_id"]})
                process = exercise_feedback(page, base_url, env, port, process, formal_event, report, fault)
                exercise_wrong_questions(page, base_url, report)
                plan = latest_review_plan()
                exercise_notes(page, base_url, resources, plan, report)
                exercise_review(page, base_url, plan, report)
                verify_protected_pages(page, base_url, report)
                verify_secondary_viewport(page, base_url, resources, report)
                context.close()
            finally:
                browser.close()

        validate_diagnostics(report)
        report["database"]["final"] = database_audit()
        assert report["database"]["final"]["integrity"] == "ok"
        assert report["database"]["final"]["foreign_key_violations"] == 0
        formal_after = file_record(FORMAL_DB)
        report["formal_database_after"] = formal_after
        assert formal_after == formal_before, {"before": formal_before, "after": formal_after}
        record_atom(
            report, "F5F8-R16",
            "刷新、重复提交、资源单项失败、实验失败、评价失败、连接中断、两次服务重启和部分聚合失败均恢复原任务且未复制事实。",
            [json.dumps({"expected_http": len(report["expected_http_errors"]), "expected_network": len(report["expected_network_errors"])})],
        )
        assert set(report["atoms"]) == {f"F5F8-R{index:02d}" for index in range(1, 18)}
        report["status"] = "PASSED"
        report["completed_at"] = datetime.now(timezone.utc).astimezone().isoformat()
        return report
    finally:
        bundle.stop_service(process, port)
        report["cleanup"] = {"port_closed": not bundle.port_open(port)}


def main() -> int:
    report: dict[str, object] = {}
    try:
        run(report)
        return 0
    except Exception as exc:
        report.setdefault("schema_version", "f5-f8.total-acceptance.v1")
        report["status"] = "FAILED"
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
        return 1
    finally:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": report.get("status"),
            "report": str(REPORT_PATH),
            "atoms": sorted((report.get("atoms") or {}).keys()),
            "error": report.get("error"),
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
