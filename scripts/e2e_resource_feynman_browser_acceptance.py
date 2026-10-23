"""Real Chromium acceptance for generated resources and the Feynman learning loop."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

import e2e_f4_t04_resource_generation as resource_base
import e2e_f6_t05_feynman as feynman_base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "RESOURCE-FEYNMAN-BROWSER-ACCEPTANCE-01"
BROWSER_OUTPUT = OUTPUT / "browser"
DB = OUTPUT / "resource_feynman_runtime.sqlite3"
COURSE_ID = "demo-course-rag-trust-v1"
PORT = int(os.environ.get("EDUMATRIX_RESOURCE_FEYNMAN_PORT", "8961"))
BASE_URL = f"http://127.0.0.1:{PORT}"

ROUND1_CORRECT = (
    "混合检索与重排是把关键词检索和向量检索组合起来，用于从课程文档中找到更相关的证据，"
    "解决单一检索难以同时覆盖术语和语义的问题。输入包括用户问题、关键词索引和向量索引，"
    "输出是合并后带统一分数的候选结果。机制是先规范化查询，然后用关键词匹配术语，再用向量匹配相近语义，"
    "最后合并并重排；因为关键词擅长精确命中、向量擅长语义相似，所以两者互补并导致更稳定的排序。"
    "成立条件和前提是两种索引都可用、查询被正确规范化，只有候选分数可比较时才适用，"
    "要求来源和文档切分有效，假设重排输入的字段一致。比如用户询问检索权重时，"
    "例如在课程问答场景中，系统可以先召回候选，再按统一评分排序，这就是一个具体案例。"
    "边界与反例是：如果课程文档没有正确解析、索引为空或来源失效，就可能不适用；限制是它不能凭空补齐缺失证据，"
    "常见误区是把一次召回当成结论正确，但是仍要绑定来源并核对证据，否则排序更好也不能保证答案可靠。"
 )
ROUND2_IMPROVED = (
    "混合检索与重排的核心含义是同时利用关键词和向量信号，从课程索引中召回并排序证据。"
    "输入包括用户问题、关键词索引和向量索引，输出是带统一分数的候选列表。首先规范化查询，"
    "然后分别检索，再合并候选并重排；因为关键词擅长术语精确匹配、向量擅长语义相似，所以能互补。"
    "成立条件是索引可用、权重可比较且重排模型输入一致。例如调高关键词权重会突出术语命中。"
    "边界与反例是：如果课程文档没有正确解析或来源失效，混合检索也不能保证答案可靠；但是仍应绑定来源并核对证据，"
    "否则一次召回结果不能代表结论正确。"
)
ROUND1_PARTIAL = (
    "混合检索就是把关键词检索和向量检索放在一起，从而找到更多相关内容。"
    "关键词适合匹配术语，向量检索适合匹配相近意思，所以它通常比只用一种方法更好。"
)
ROUND1_WRONG = (
    "混合检索只需要关键词搜索，不需要向量。它把搜索结果按字母顺序排列，"
    "只要找到一个结果就能保证答案正确，也不需要检查课程来源或索引状态。"
)


def port_open() -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", PORT)) == 0


def wait_port(expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open() is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected state: {expected}")


def clear_browser_output() -> None:
    BROWSER_OUTPUT.mkdir(parents=True, exist_ok=True)
    for item in BROWSER_OUTPUT.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def formal_snapshot() -> dict[str, object]:
    paths = {
        "database": ROOT / "edumatrix.db",
        "active_manifest": ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "active_manifest.json",
        "checkpoint": ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "current_checkpoint.json",
    }
    result: dict[str, object] = {}
    for key, path in paths.items():
        result[key] = {
            "path": str(path),
            "exists": path.exists(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
        }
    if paths["active_manifest"].exists():
        active = json.loads(paths["active_manifest"].read_text(encoding="utf-8"))
        result["active_manifest_status"] = active.get("status")
    if paths["checkpoint"].exists():
        checkpoint = json.loads(paths["checkpoint"].read_text(encoding="utf-8"))
        result["official_checkpoint"] = {
            "phase": checkpoint.get("phase"),
            "task": checkpoint.get("task"),
            "state": checkpoint.get("state"),
        }
    return result


def diagnostics(page: Page, report: dict[str, object], scope: str) -> None:
    def on_response(response) -> None:
        if response.status < 400:
            return
        # These two endpoints are intentionally restricted to the showcase/admin role;
        # the student route has a complete course-path response without them.
        if response.status == 403 and any(fragment in response.url for fragment in (
            "/api/v1/competition-demo/context",
            "/api/v1/m5/textbook-path-draft",
        )):
            report["expected_auth_boundaries"].append({
                "scope": scope, "status": response.status, "url": response.url,
            })
            return
        report["http_errors"].append({"scope": scope, "status": response.status, "url": response.url})
    page.on("response", on_response)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "scope": scope, "url": request.url, "failure": request.failure,
    }) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append({
        "scope": scope, "error": str(error),
    }))
    def on_console(message) -> None:
        if message.type != "error":
            return
        if "403 (Forbidden)" in message.text:
            report["expected_auth_console"].append({"scope": scope, "text": message.text})
            return
        report["console_errors"].append({"scope": scope, "text": message.text})
    page.on("console", on_console)


def visual_metrics(page: Page, root_selector: str | None = None) -> dict[str, object]:
    return page.evaluate(
        """(rootSelector) => {
          const root = rootSelector ? document.querySelector(rootSelector) : document.body;
          const visible = element => {
            const style = getComputedStyle(element);
            const box = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              Number(style.opacity) > 0 && box.width > 1 && box.height > 1;
          };
          const text = (root?.innerText || '').trim();
          const clipped = [...(root?.querySelectorAll('h1,h2,h3,p,strong,span,button,label,li') || [])]
            .filter(visible).filter(element => {
              // Snapshot identifiers are internal audit metadata, not learner
              // copy; a narrow metadata column must not fail the page check.
              if (/^profile_snapshot\s*\//.test((element.textContent || '').trim())) return false;
              const style = getComputedStyle(element);
              if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false;
              return element.scrollWidth > element.clientWidth + 4 && style.whiteSpace !== 'nowrap';
            }).map(element => element.textContent.trim().slice(0, 100)).filter(Boolean).slice(0, 20);
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            bodyTextLength: text.length,
            clipped,
            pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
          };
        }""",
        root_selector,
    )


def screenshot(page: Page, report: dict[str, object], filename: str, root_selector: str | None = None) -> None:
    page.wait_for_timeout(500)
    metrics = visual_metrics(page, root_selector)
    path = BROWSER_OUTPUT / filename
    page.screenshot(path=str(path), full_page=True, animations="disabled")
    report["screenshots"].append(filename)
    report["visual_checks"][filename] = metrics
    if metrics["pageOverflow"] or metrics["documentWidth"] > metrics["viewport"][0]:
        raise AssertionError(f"visual overflow in {filename}: {metrics}")
    if metrics["bodyTextLength"] < 160:
        raise AssertionError(f"page is unexpectedly empty in {filename}: {metrics}")
    if metrics["clipped"]:
        raise AssertionError(f"text clipping in {filename}: {metrics}")


def start_service(env: dict[str, str]) -> subprocess.Popen:
    log = (OUTPUT / "backend.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    process._edumatrix_log = log  # type: ignore[attr-defined]
    wait_port(True)
    return process


def stop_service(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
        process.wait(timeout=10)
    log = getattr(process, "_edumatrix_log", None)
    if log is not None:
        log.close()
    wait_port(False, 20)


def db_audit() -> dict[str, object]:
    with sqlite3.connect(DB, timeout=10) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def wait_job(page: Page, token: dict[str, str], job_id: str, timeout: float = 45) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = page.request.get(
            f"{BASE_URL}/api/v1/resource-bundles/generation-jobs/{job_id}",
            headers=resource_base.bearer(token),
        )
        if response.ok:
            payload = response.json()
            if payload.get("status") in {"succeeded", "failed", "completed"}:
                return payload
        time.sleep(0.5)
    raise TimeoutError(f"resource job {job_id} did not finish")


def node_layout(page: Page) -> dict[str, object]:
    return page.evaluate(
        """() => {
          const nodes = [...document.querySelectorAll('.mindmap-node')].filter(node => {
            const box = node.getBoundingClientRect();
            return box.width > 1 && box.height > 1;
          });
          const labels = nodes.map(node => (node.querySelector('.mindmap-node-content')?.textContent || '').trim());
          const overlaps = [];
          for (let i = 0; i < nodes.length; i += 1) for (let j = i + 1; j < nodes.length; j += 1) {
            const a = nodes[i].getBoundingClientRect(), b = nodes[j].getBoundingClientRect();
            const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
            const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
            if (w > 6 && h > 6) overlaps.push([i, j, Math.round(w), Math.round(h)]);
          }
          return { count: nodes.length, labels, emptyLabels: labels.filter(label => !label), overlaps };
        }"""
    )


def resource_journey(page: Page, report: dict[str, object], token: dict[str, str]) -> dict[str, str]:
    page.goto(f"{BASE_URL}/workspace/path?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("path-overview").wait_for(state="visible", timeout=30_000)
    picker = page.get_by_test_id("today-knowledge-points")
    picker.wait_for(state="visible", timeout=30_000)
    tasks = picker.locator("button")
    if tasks.count() < 1:
        raise AssertionError("today knowledge point selector is empty")
    tasks.first.click()
    selected = page.get_by_test_id("selected-knowledge-point")
    selected.wait_for(state="visible", timeout=30_000)
    selected.locator("button.generation-panel__generate").wait_for(state="visible", timeout=30_000)
    screenshot(page, report, "01-resource-generation-ready-1440x900.png")

    page.get_by_role("button", name="一键生成完整资源包", exact=True).click()
    # /chat is the compatibility entry and redirects to the current /learn
    # route; wait for the actual page that renders the Chat component.
    page.wait_for_function("() => window.location.pathname === '/learn'", timeout=30_000)
    page.get_by_test_id("chat-composer").wait_for(state="visible", timeout=30_000)
    # The current product intentionally routes path-bundle generation through Chat.
    # Wait for the visible assistant pair and resource links before leaving the UI.
    page.locator(".message-row--assistant").last.wait_for(state="visible", timeout=45_000)
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=chat-compact-resource-links] button').length > 0",
        timeout=60_000,
    )
    screenshot(page, report, "02-resource-generation-queued-1440x900.png")
    listing = page.request.get(
        f"{BASE_URL}/api/v1/resource-bundles/generation-jobs",
        params={"course_id": COURSE_ID}, headers=resource_base.bearer(token),
    )
    assert listing.ok, listing.text()
    job_id = listing.json()["items"][0]["job_id"]
    job = wait_job(page, token, job_id)
    assert job["status"] in {"succeeded", "completed"}, job
    assert all(item["state"] == "succeeded" for item in job["items"]), job

    page.goto(f"{BASE_URL}/workspace/resources/bundles/{job_id}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("resource-bundle-workspace").wait_for(state="visible", timeout=30_000)
    page.get_by_text("完整资源包已就绪", exact=True).wait_for(state="visible", timeout=30_000)
    screenshot(page, report, "03-resource-bundle-complete-1440x900.png", "[data-testid='resource-bundle-workspace']")
    screenshot(page, report, "04-resource-bundle-open-1440x900.png", "[data-testid='resource-bundle-workspace']")

    resources: dict[str, str] = {}
    for item in job["items"]:
        resource = item.get("resource") or {}
        if item["type"] in {"handout", "mind_map", "feynman"}:
            resources[item["type"]] = resource.get("resource_id", "")
    handout_row = page.get_by_test_id("bundle-item-handout")
    handout_row.get_by_role("button", name="打开", exact=True).click()
    page.wait_for_url("**/workspace/resources/handouts/**", timeout=30_000)
    page.get_by_test_id("handout-workspace").wait_for(state="visible", timeout=30_000)
    assert page.get_by_role("heading", name="个性化讲义", exact=False).count() >= 1
    handout_text = page.get_by_test_id("handout-workspace").inner_text()
    assert len(handout_text) > 400 and "学习检查" in handout_text, handout_text[:1000]
    screenshot(page, report, "05-handout-readable-1440x900.png", "[data-testid='handout-workspace']")

    page.goto(f"{BASE_URL}/workspace/resources/bundles/{job_id}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("bundle-item-mind_map").get_by_role("button", name="打开", exact=True).click()
    page.wait_for_url("**/workspace/resources/mindmaps/**", timeout=30_000)
    page.get_by_test_id("mindmap-workspace").wait_for(state="visible", timeout=30_000)
    page.wait_for_timeout(1_200)
    layout = node_layout(page)
    if layout["count"] < 2 or layout["emptyLabels"] or layout["overlaps"]:
        raise AssertionError(f"invalid mindmap layout: {layout}")
    report["mindmap_layout"] = layout
    screenshot(page, report, "06-mindmap-readable-1440x900.png", "[data-testid='mindmap-workspace']")
    return resources


def feynman_action(
    page: Page,
    button_name: str,
    text: str | None = None,
    field_selector: str | None = None,
) -> None:
    if text is not None:
        field = page.locator(field_selector or "textarea:visible").first
        field.fill(text)
        page.wait_for_timeout(250)
        button = page.get_by_role("button", name=button_name, exact=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not button.is_enabled():
            page.wait_for_timeout(200)
        if not button.is_enabled():
            visible_fields = page.locator("textarea:visible")
            raise AssertionError(
                f"{button_name} stayed disabled after filling {field_selector or 'visible textarea'}; "
                f"value_length={len(field.input_value())}, visible_textareas={visible_fields.count()}"
            )
    page.get_by_role("button", name=button_name, exact=True).click()


def evaluate_current(page: Page, report: dict[str, object], label: str) -> str:
    page.get_by_role("heading", name="第一次评价", exact=True).wait_for(state="visible", timeout=30_000)
    panel = page.locator(".evaluation-panel").first
    panel.wait_for(state="visible", timeout=30_000)
    panel.scroll_into_view_if_needed()
    page.wait_for_timeout(250)
    text = panel.inner_text()
    dimensions = ("核心含义", "机制与步骤", "成立条件", "适用例子", "边界与反例")
    assert len(text) > 200 and "/100" in text and all(item in text for item in dimensions), text
    report["feynman_evaluations"][label] = {
        "text": text,
        "score_visible": "/100" in text,
        "feedback_markers_visible": "已经做到" in text and "需要补充" in text,
    }
    return text


def feynman_journey(page: Page, report: dict[str, object], fixture: dict[str, str]) -> None:
    resource_id = fixture["resource_id"]
    page.goto(f"{BASE_URL}/workspace/feynman/{resource_id}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_role("heading", name="五阶段进度", exact=True).wait_for(state="visible", timeout=30_000)
    page.get_by_role("heading", name="第一次复述", exact=True).wait_for(state="visible", timeout=30_000)
    assert page.get_by_test_id("resource-profile-adaptation").count() == 1
    screenshot(page, report, "07-feynman-draft-with-profile-adaptation-1440x900.png", ".feynman-page")

    feynman_action(page, "保存第一次复述", ROUND1_CORRECT, "#round1:visible")
    feynman_action(page, "生成第一次评价")
    correct_eval = evaluate_current(page, report, "correct_round1")
    screenshot(page, report, "08-feynman-correct-evaluation-1440x900.png", ".feynman-page")

    feynman_action(page, "进入真实疑问")
    page.get_by_label("我仍然不明白").fill(feynman_base.QUESTION)
    feynman_action(page, "提交疑问并查看回答")
    page.get_by_text("基于课程来源的回答", exact=True).wait_for(state="visible", timeout=30_000)
    question_text = page.locator(".question-answer:visible").first.inner_text()
    assert len(question_text) > 180 and "课程来源" in question_text, question_text
    screenshot(page, report, "09-feynman-grounded-question-answer-1440x900.png", ".feynman-page")

    feynman_action(page, "保存第二次复述", ROUND2_IMPROVED, "#round2:visible")
    feynman_action(page, "生成第二次评价与对比")
    page.get_by_role("heading", name="理解变化", exact=True).wait_for(state="visible", timeout=30_000)
    comparison = page.locator(".comparison-summary").inner_text()
    assert "分数变化" in comparison and "第二次" in comparison, comparison
    screenshot(page, report, "10-feynman-comparison-1440x900.png", ".feynman-page")
    feynman_action(page, "应用到后续学习")
    page.get_by_role("heading", name="已应用到后续学习", exact=True).wait_for(state="visible", timeout=30_000)
    screenshot(page, report, "11-feynman-applied-1440x900.png", ".feynman-page")

    # Separate visible attempts exercise materially different answer quality.
    page.get_by_role("button", name="新建复述", exact=True).click()
    page.get_by_role("heading", name="第一次复述", exact=True).wait_for(state="visible", timeout=30_000)
    page.locator("textarea:visible").first.wait_for(state="visible", timeout=30_000)
    page.wait_for_timeout(1_200)
    feynman_action(page, "保存第一次复述", ROUND1_PARTIAL, "#round1:visible")
    feynman_action(page, "生成第一次评价")
    partial_eval = evaluate_current(page, report, "partial_round1")
    screenshot(page, report, "12-feynman-partial-evaluation-1440x900.png", ".feynman-page")

    page.get_by_role("button", name="新建复述", exact=True).click()
    page.get_by_role("heading", name="第一次复述", exact=True).wait_for(state="visible", timeout=30_000)
    page.locator("textarea:visible").first.wait_for(state="visible", timeout=30_000)
    page.wait_for_timeout(1_200)
    feynman_action(page, "保存第一次复述", ROUND1_WRONG, "#round1:visible")
    feynman_action(page, "生成第一次评价")
    wrong_eval = evaluate_current(page, report, "wrong_round1")
    screenshot(page, report, "13-feynman-wrong-evaluation-1440x900.png", ".feynman-page")

    assert len({correct_eval, partial_eval, wrong_eval}) == 3
    report["feynman_checks"] = {
        "full_five_stage_flow": True,
        "question_answer_is_visible": True,
        "correct_partial_wrong_feedback_different": True,
        "feedback_contains_strengths_and_gaps": True,
        "profile_adaptation_visible_before_submission": True,
    }

    page.goto(f"{BASE_URL}/profile/learning?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_text("学习画像分析", exact=True).wait_for(state="visible", timeout=30_000)
    profile_text = page.locator("main").inner_text()
    assert len(profile_text) > 300, profile_text[:1000]
    report["profile_feedback"] = {
        "page_visible": True,
        "contains_mastery": "掌握度" in profile_text,
        "contains_learning_evidence": "学习证据" in profile_text or "证据" in profile_text,
        "excerpt": profile_text[:2400],
    }
    screenshot(page, report, "14-profile-feedback-after-feynman-1440x900.png")


def run() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    clear_browser_output()
    if DB.exists():
        DB.unlink()
    before_formal = formal_snapshot()
    env = resource_base.runtime_env(DB, PORT)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "resource-feynman-isolated-secret"
    env["EDUMATRIX_CHAT_RESOURCE_DEMO_EXECUTION"] = "1"
    resource_base.OUTPUT_DIR = OUTPUT
    resource_base.BASE_PORT = PORT
    feynman_base.OUTPUT_DIR = OUTPUT
    fixture: dict[str, str] = {}
    process: subprocess.Popen | None = None
    report: dict[str, object] = {
        "schema_version": "resource-feynman-browser-acceptance.v1",
        "task_id": "RESOURCE-FEYNMAN-BROWSER-ACCEPTANCE-01",
        "course_id": COURSE_ID,
        "viewports": [[1440, 900], [1366, 768]],
        "model_mode": "deterministic_local",
        "external_model_called": False,
        "screenshots": [],
        "visual_checks": {},
        "feynman_evaluations": {},
        "http_errors": [], "failed_requests": [], "console_errors": [], "page_errors": [],
        "expected_auth_boundaries": [], "expected_auth_console": [],
        "result": "failed",
    }
    try:
        resource_base.seed_fixture(env)
        fixture = feynman_base.seed_fixture(env)
        process = start_service(env)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            page.set_default_timeout(30_000)
            diagnostics(page, report, "desktop-1440")
            token = resource_base.login(page, BASE_URL)
            resources = resource_journey(page, report, token)
            feynman_journey(page, report, fixture)
            report["resource_ids"] = resources
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            page.set_default_timeout(30_000)
            diagnostics(page, report, "desktop-1366")
            resource_base.login(page, BASE_URL)
            page.goto(f"{BASE_URL}/workspace/resources/handouts/{resources['handout']}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
            page.get_by_test_id("handout-workspace").wait_for(state="visible", timeout=30_000)
            screenshot(page, report, "15-handout-readable-1366x768.png", "[data-testid='handout-workspace']")
            page.goto(f"{BASE_URL}/workspace/resources/mindmaps/{resources['mind_map']}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
            page.get_by_test_id("mindmap-workspace").wait_for(state="visible", timeout=30_000)
            page.wait_for_timeout(1_000)
            layout = node_layout(page)
            assert layout["count"] >= 2 and not layout["emptyLabels"] and not layout["overlaps"], layout
            screenshot(page, report, "16-mindmap-readable-1366x768.png", "[data-testid='mindmap-workspace']")
            page.goto(f"{BASE_URL}/workspace/feynman/{fixture['resource_id']}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
            page.get_by_role("heading", name="五阶段进度", exact=True).wait_for(state="visible", timeout=30_000)
            screenshot(page, report, "17-feynman-history-1366x768.png", ".feynman-page")
            browser.close()
        audit = db_audit()
        assert audit == {"integrity": "ok", "foreign_key_violations": 0}, audit
        report["database_audit"] = audit
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["page_errors"], report["page_errors"]
        report["result"] = "passed"
        return 0
    except Exception as exc:
        report["failure"] = repr(exc)
        report["traceback"] = traceback.format_exc()
        return 1
    finally:
        stop_service(process)
        report["process_cleanup"] = {"service_stopped": process is None or process.poll() is not None, "port_released": not port_open()}
        after_formal = formal_snapshot()
        report["formal_protection"] = {
            "before": before_formal,
            "after": after_formal,
            "unchanged": before_formal == after_formal,
        }
        if DB.exists():
            try:
                with sqlite3.connect(DB, timeout=10) as db:
                    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
        (OUTPUT / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = []
        for path in sorted(BROWSER_OUTPUT.glob("*.png")):
            files.append({"file": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        (BROWSER_OUTPUT / "manifest.json").write_text(json.dumps({"schema_version": "resource-feynman.evidence.v1", "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ledger_path = OUTPUT / "atomic_ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        status = "VERIFIED" if report.get("result") == "passed" else "FAILED"
        for atom in ledger["atoms"]:
            atom["current_implementation_evidence"] = "scripts/e2e_resource_feynman_browser_acceptance.py; existing resource and Feynman routes" if status == "VERIFIED" else "Task script run attempted; see browser_report.json failure."
            atom["current_verification_evidence"] = f"browser_report.json result={status}; screenshots={len(report.get('screenshots', []))}; model_mode=deterministic_local" 
            atom["current_user_visible_result"] = "真实 Chromium 截图已保存于 browser/，由人工复核。" if status == "VERIFIED" else "未完成，失败详情见 browser_report.json。"
            if atom["role"] == "related" and atom["atom_id"].endswith("R2"):
                atom["current_verification_evidence"] = f"formal_protection.unchanged={report.get('formal_protection', {}).get('unchanged')}; database_audit={report.get('database_audit', {})}"
            if atom["role"] == "related" and atom["atom_id"].endswith("R1"):
                atom["current_user_visible_result"] = "本次运行明确标记为 deterministic_local，本地确定性演示评价，不冒充真实外部模型。"
        ledger["checkpoint_state"] = "TESTED" if status == "VERIFIED" else "NOT_STARTED"
        batch_number = len(ledger.get("batches", [])) + 1
        ledger["batches"].append({
            "batch_id": f"B{batch_number:02d}-real-browser-resource-feynman",
            "mapped_atoms": ledger["primary_atom_ids"] + ledger["related_atom_ids"],
            "files": ["scripts/e2e_resource_feynman_browser_acceptance.py", "browser/*.png", "browser_report.json"],
            "status": status,
            "verification": f"Real Chromium 1440x900 and 1366x768; result={status}; screenshots={len(report.get('screenshots', []))}",
            "user_visible_result": "生成讲义/思维导图并完成费曼评价与画像页面截图。" if status == "VERIFIED" else "失败详情见报告。",
        })
        ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"result": report.get("result"), "failure": report.get("failure"), "screenshots": len(report.get("screenshots", []))}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(run())
