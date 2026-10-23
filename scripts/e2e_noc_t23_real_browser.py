"""Real-backend browser evidence for NOC-T23 quiz, graph and chat repairs.

The run copies the previously seeded student journey database into this task's
evidence directory, starts the actual FastAPI service, and drives the built SPA
with Chromium.  No production database is opened for writes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "STUDENT-JOURNEY-DEMO-01" / "student_journey_runtime.db"
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "NOC-T23-UX-EVIDENCE-01"
OUT = EVIDENCE / "browser"
DB_PATH = EVIDENCE / "noc_t23_real_browser.db"
PORT = int(os.getenv("NOC_T23_REAL_BROWSER_PORT", "8943"))
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "StudentJourney-Demo-2026!"
COURSE_ID = "course-ai-deep-learning-agents-v1"


def env_for_run() -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "noc-t23-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_ONBOARDING_V2": "1",
        "EDUMATRIX_SANDBOX_MODE": "trusted_local",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def wait_port(expected: bool, timeout: float = 60.0) -> None:
    import socket
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            if (sock.connect_ex(("127.0.0.1", PORT)) == 0) is expected:
                return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected={expected}")


def copy_isolated_db() -> None:
    if not SOURCE_DB.exists():
        raise RuntimeError(f"seeded browser database missing: {SOURCE_DB}")
    OUT.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    shutil.copy2(SOURCE_DB, DB_PATH)
    for suffix in ("-wal", "-shm"):
        extra = Path(str(DB_PATH) + suffix)
        if extra.exists():
            extra.unlink()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def db_identity() -> tuple[str, str, str]:
    with sqlite3.connect(DB_PATH) as db:
        username, public_id = db.execute(
            "SELECT username, public_id FROM users WHERE username LIKE 'journey_%' ORDER BY username DESC LIMIT 1"
        ).fetchone() or (None, None)
        course = db.execute("SELECT id, title, status FROM courses WHERE id=?", (COURSE_ID,)).fetchone()
    if not username or not course:
        raise RuntimeError("isolated seed does not contain the master-course journey user")
    return str(username), str(public_id), str(course[0])


def diagnostics(page: Page, report: dict) -> None:
    page.on("response", lambda response: report["http_errors"].append({"status": response.status, "url": response.url}) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({"url": request.url, "failure": request.failure}) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)
    page.on("request", lambda request: report["external_requests"].append(request.url) if not request.url.startswith(BASE_URL) and not request.url.startswith("data:") and not request.url.startswith("blob:") else None)


def shot(page: Page, report: dict, name: str) -> None:
    page.wait_for_timeout(450)
    path = OUT / name
    page.screenshot(path=str(path), full_page=True)
    report["screenshots"].append({"name": name, "path": str(path), "viewport": [page.viewport_size["width"], page.viewport_size["height"]], "url": page.url})


def login(page: Page, username: str) -> str:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_test_id("login-username").fill(username)
    page.get_by_test_id("login-password").fill(PASSWORD)
    page.get_by_test_id("login-submit").click()
    page.wait_for_timeout(900)
    token = page.evaluate("() => localStorage.getItem('edumatrix_token')")
    if not token:
        raise AssertionError(f"login did not produce an auth token; url={page.url}")
    return str(token)


def api_json(page: Page, token: str, path: str) -> dict:
    response = page.request.get(f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {token}"})
    if not response.ok:
        raise AssertionError(f"GET {path} failed: {response.status} {response.text()[:400]}")
    return response.json()


def quiz_artifact_id() -> str:
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            "SELECT id FROM artifacts WHERE artifact_type='quiz' AND status IN ('approved','published','active') ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        raise RuntimeError("isolated database has no quiz artifact")
    return str(row[0])


def quiz_visual_check(page: Page, report: dict, token: str, size: str) -> dict:
    resource_id = quiz_artifact_id()
    page.goto(f"{BASE_URL}/workspace/resources/quizzes/{quote(resource_id)}?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=60_000)
    workspace = page.get_by_test_id("quiz-resource-workspace")
    workspace.wait_for(state="visible", timeout=45_000)
    card = workspace.get_by_test_id("inline-quiz-card")
    card.wait_for(state="visible", timeout=45_000)
    option_texts = [text.strip() for text in card.locator(".option-text").all_inner_texts()]
    question = card.locator("h2").inner_text().strip()
    forbidden = re.compile(r"source[_-]?path|source[_-]?ref|hash|commit|manifest|版本|画像|\.(?:md|pdf|docx|pptx)\b|chapter[_-]", re.I)
    if not question or len(option_texts) < 2:
        raise AssertionError(f"quiz question incomplete: question={question!r}, options={option_texts!r}")
    if any(not item or forbidden.search(item) for item in option_texts):
        raise AssertionError(f"quiz options contain internal metadata: {option_texts!r}")
    source_button = card.get_by_role("button", name="查看来源", exact=True)
    if source_button.count() < 1:
        raise AssertionError("quiz lost its on-demand source entry")
    source_visible_text = workspace.inner_text()
    if source_visible_text.count("来源") > 8:
        raise AssertionError("source/provenance occupies the primary quiz surface")
    shot(page, report, f"01-quiz-natural-options-{size}.png")
    return {"resource_id": resource_id, "question": question, "options": option_texts, "source_entry": True}


def graph_state(page: Page) -> dict:
    return page.evaluate(
        """
        () => {
          const host = document.querySelector('[data-testid="knowledge-graph-explorer"] .chart')
          const chart = host?.__edumatrixChartInstance
          if (!host || !chart) return { missing: true }
          const option = chart.getOption()?.series?.[0] || {}
          const data = option.data || []
          const links = option.links || option.edges || []
          const rect = host.getBoundingClientRect()
          const points = data.map((node) => {
            const raw = [Number(node.x || 0), Number(node.y || 0)]
            const pixel = chart.convertToPixel({seriesIndex: 0}, raw)
            const rawSize = Array.isArray(node.symbolSize) ? Math.max(Number(node.symbolSize[0] || 0), Number(node.symbolSize[1] || 0)) : Number(node.symbolSize || 0)
            return { id: String(node.id || ''), name: String(node.name || ''), x: pixel[0], y: pixel[1], size: rawSize, symbolSize: node.symbolSize }
          })
          const distanceViolations = []
          for (let i = 0; i < points.length; i += 1) for (let j = i + 1; j < points.length; j += 1) {
            const a = points[i], b = points[j]
            const distance = Math.hypot(a.x - b.x, a.y - b.y)
            const minimum = (a.size + b.size) / 2 + 5
            if (distance < minimum) distanceViolations.push({a: a.id, b: b.id, distance, minimum})
          }
          const orient = (a,b,c) => (b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x)
          const intersects = (a,b,c,d) => orient(a,b,c)*orient(a,b,d)<0 && orient(c,d,a)*orient(c,d,b)<0
          const crossings = []
          for (let i=0;i<links.length;i+=1) for (let j=i+1;j<links.length;j+=1) {
            const e=links[i], f=links[j]
            if ([String(e.source),String(e.target)].some(id => id===String(f.source)||id===String(f.target))) continue
            const a=points.find(p=>p.id===String(e.source)), b=points.find(p=>p.id===String(e.target))
            const c=points.find(p=>p.id===String(f.source)), d=points.find(p=>p.id===String(f.target))
            if (a&&b&&c&&d&&intersects(a,b,c,d)) crossings.push([String(e.source),String(e.target),String(f.source),String(f.target)])
          }
          return { missing:false, rect:{width:rect.width,height:rect.height}, nodes:points, links:links.length, emptyNodes:points.filter(p=>!p.name.trim()).length, distanceViolations, crossings }
        }
        """
    )


def graph_visual_check(page: Page, report: dict, token: str, size: str) -> dict:
    graph = api_json(page, token, f"/api/knowledge/courses/{COURSE_ID}/graph")
    page.goto(f"{BASE_URL}/knowledge/graph/{quote(COURSE_ID)}", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_test_id("course-knowledge-graph-workspace").wait_for(state="visible", timeout=45_000)
    page.get_by_test_id("knowledge-graph-explorer").wait_for(state="visible", timeout=45_000)
    chart_host = page.locator('[data-testid="knowledge-graph-explorer"] .chart')
    chart_host.scroll_into_view_if_needed()
    page.wait_for_timeout(900)
    initial = graph_state(page)
    if initial.get("missing"):
        raise AssertionError("ECharts graph instance is not mounted")
    if initial["emptyNodes"] or initial["distanceViolations"]:
        raise AssertionError(f"initial graph is not readable: {initial}")
    shot(page, report, f"02-graph-layer-1-{size}.png")

    all_nodes = {str(item.get("id")): item for item in graph.get("nodes", []) if str(item.get("id") or "").strip() and str(item.get("name") or "").strip()}
    prerequisite_edges = [item for item in graph.get("edges", []) if str(item.get("relationType") or "").lower() == "prerequisite"]
    visible_ids = {item["id"] for item in initial["nodes"]}
    expandable = next((edge for edge in prerequisite_edges if str(edge.get("source")) in visible_ids and str(edge.get("target")) not in visible_ids), None)
    if expandable:
        source_id = str(expandable["source"])
        target_id = str(expandable["target"])
        point = next(item for item in initial["nodes"] if item["id"] == source_id)
        box = chart_host.bounding_box()
        if not box:
            raise AssertionError("graph canvas has no visible bounding box")
        page.mouse.click(point["x"] + box["x"], point["y"] + box["y"])
        page.wait_for_timeout(650)
        expanded = graph_state(page)
        if target_id not in {item["id"] for item in expanded["nodes"]}:
            raise AssertionError(f"clicking root {source_id} did not reveal child {target_id}: {expanded}")
        if expanded["emptyNodes"] or expanded["distanceViolations"]:
            raise AssertionError(f"expanded graph is not readable: {expanded}")
        shot(page, report, f"03-graph-layer-2-{size}.png")
    else:
        expanded = initial
    return {"api_nodes": len(graph.get("nodes", [])), "api_edges": len(graph.get("edges", [])), "initial": initial, "expanded": expanded, "expanded_edge": expandable}


def chat_visual_check(page: Page, report: dict, token: str, size: str) -> dict:
    before = api_json(page, token, f"/api/v1/resource-bundles/generation-jobs?course_id={COURSE_ID}")
    before_count = len(before.get("items", []))
    page.goto(f"{BASE_URL}/chat?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible", timeout=45_000)
    composer = page.get_by_label("输入问题")
    question_text = "请解释二分查找的循环不变量，并给出一个边界条件例子。"
    composer.fill(question_text)
    page.locator(".send-button").click()
    # A fresh browser context may restore a previously selected conversation.
    # Locate the assistant paired with this exact user message instead of
    # relying on DOM order across restored conversations and viewport runs.
    user_row = page.locator(".message-row--user").filter(has_text=question_text).last
    user_row.wait_for(state="visible", timeout=45_000)
    assistant = user_row.locator("xpath=following-sibling::article[contains(@class,'message-row--assistant')][1]")
    assistant.wait_for(state="visible", timeout=60_000)
    assistant_id = assistant.get_attribute("data-message-id")
    page.wait_for_function("""(messageId) => {
      const row = document.querySelector(`[data-message-id="${messageId}"]`)
      const label = row?.querySelector('.assistant-label')?.innerText || ''
      const answer = row?.querySelector('.assistant-answer')?.innerText || ''
      return label.includes('回答完成') && answer.trim().length > 30
    }""", arg=assistant_id, timeout=60_000)
    content = assistant.locator(".assistant-answer").inner_text().strip()
    if len(content) < 800 or "循环不变量" not in content:
        raise AssertionError(f"ordinary chat did not produce a readable answer: {content!r}")
    if assistant.get_by_text("回答失败", exact=False).count():
        raise AssertionError("ordinary chat remained in a failure state")
    shot(page, report, f"04-chat-answer-{size}.png")
    follow_up = "那 left 和 right 在闭区间写法中分别何时移动？"
    composer.fill(follow_up)
    page.locator(".send-button").click()
    follow_user_row = page.locator(".message-row--user").filter(has_text=follow_up).last
    follow_user_row.wait_for(state="visible", timeout=45_000)
    follow_assistant = follow_user_row.locator("xpath=following-sibling::article[contains(@class,'message-row--assistant')][1]")
    follow_assistant.wait_for(state="visible", timeout=60_000)
    follow_assistant_id = follow_assistant.get_attribute("data-message-id")
    page.wait_for_function("""(messageId) => {
      const row = document.querySelector(`[data-message-id="${messageId}"]`)
      const label = row?.querySelector('.assistant-label')?.innerText || ''
      const answer = row?.querySelector('.assistant-answer')?.innerText || ''
      return label.includes('回答完成') && answer.trim().length > 30
    }""", arg=follow_assistant_id, timeout=60_000)
    page.wait_for_timeout(700)
    assistant_count = page.locator(".message-row--assistant").count()
    follow_content = follow_assistant.locator(".assistant-answer").inner_text().strip()
    if assistant_count < 1 or len(follow_content) < 800 or follow_content == content:
        raise AssertionError("ordinary chat follow-up did not create a second assistant answer")
    if "right = mid - 1" not in follow_content or "left = mid + 1" not in follow_content:
        raise AssertionError(
            f"ordinary chat follow-up answered the wrong topic: {follow_content!r}"
        )
    shot(page, report, f"05-chat-follow-up-{size}.png")
    after = api_json(page, token, f"/api/v1/resource-bundles/generation-jobs?course_id={COURSE_ID}")
    after_count = len(after.get("items", []))
    if after_count != before_count:
        raise AssertionError(f"ordinary chat unexpectedly created a resource job: {before_count}->{after_count}")
    return {
        "first_answer_chars": len(content),
        "first_answer_topic_evidence": "循环不变量",
        "follow_up_answer_chars": len(follow_content),
        "follow_up_topic_evidence": "right = mid - 1; left = mid + 1",
        "answers_are_distinct": follow_content != content,
        "assistant_count": assistant_count,
        "resource_jobs_before": before_count,
        "resource_jobs_after": after_count,
    }


def main() -> int:
    copy_isolated_db()
    username, public_id, _ = db_identity()
    report: dict = {
        "schema_version": "noc-t23.real-browser.v1",
        "result": "failed",
        "service": BASE_URL,
        "database": str(DB_PATH),
        "username": username,
        "public_id": public_id,
        "screenshots": [],
        "quiz": {},
        "graph": {},
        "chat": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "formal_db_before": {"exists": (ROOT / "edumatrix.db").exists(), "sha256": digest(ROOT / "edumatrix.db") if (ROOT / "edumatrix.db").exists() else None},
    }
    process = None
    try:
        env = env_for_run()
        log_path = EVIDENCE / "browser_backend.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page(); diagnostics(page, report)
                token = login(page, username)
                report["quiz"]["1440x900"] = quiz_visual_check(page, report, token, "1440x900")
                report["graph"]["1440x900"] = graph_visual_check(page, report, token, "1440x900")
                report["chat"]["1440x900"] = chat_visual_check(page, report, token, "1440x900")
                context.close()
                context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
                page = context.new_page(); diagnostics(page, report)
                token = login(page, username)
                report["quiz"]["1366x768"] = quiz_visual_check(page, report, token, "1366x768")
                report["graph"]["1366x768"] = graph_visual_check(page, report, token, "1366x768")
                report["chat"]["1366x768"] = chat_visual_check(page, report, token, "1366x768")
                context.close(); browser.close()
        with sqlite3.connect(DB_PATH) as db:
            report["database"] = {
                "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
                "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
                "chat_messages": db.execute("SELECT COUNT(*) FROM chat_messages WHERE owner_public_id=?", (public_id,)).fetchone()[0],
            }
        report["formal_db_after"] = {"exists": (ROOT / "edumatrix.db").exists(), "sha256": digest(ROOT / "edumatrix.db") if (ROOT / "edumatrix.db").exists() else None}
        report["checks"] = {
            "formal_db_unchanged": report["formal_db_after"] == report["formal_db_before"],
            "no_unexpected_browser_errors": not (report["http_errors"] or report["failed_requests"] or report["page_errors"] or report["console_errors"] or report["external_requests"]),
            "all_graph_nodes_non_empty": all(not item["initial"]["emptyNodes"] and not item["expanded"]["emptyNodes"] for item in report["graph"].values()),
            "all_graph_nodes_separated": all(not item["initial"]["distanceViolations"] and not item["expanded"]["distanceViolations"] for item in report["graph"].values()),
        }
        if report["database"]["integrity"] != "ok" or report["database"]["foreign_key_violations"] or not report["checks"]["formal_db_unchanged"] or not report["checks"]["no_unexpected_browser_errors"]:
            raise AssertionError(report["checks"])
        report["result"] = "passed"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=20)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        report["process_cleanup"] = process is None or process.poll() is not None
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (EVIDENCE / "real_browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "screenshots": len(report["screenshots"]), "error": report.get("error")}, ensure_ascii=False))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
