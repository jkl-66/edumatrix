"""Continuous real-browser learning loop for demo-video evidence.

The journey uses one disposable SQLite database and one authenticated Chromium
session for every learner action. Database reads are audit-only; resources,
attempts, learning events, chat messages, and profile feedback are created by
the visible product flow.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Locator, Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import e2e_chat_comprehensive_visual_audit as chat_audit  # noqa: E402
import e2e_f6_t06_formal_exam as exam_audit  # noqa: E402
import e2e_resource_execution_quality as resource_audit  # noqa: E402
import e2e_resource_feynman_browser_acceptance as feynman_audit  # noqa: E402
import e2e_student_journey_master_course as master  # noqa: E402


TASK_ID = "DEMO-LEARNING-CLOSED-LOOP-PROFILE-01"
EVIDENCE = (
    ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / TASK_ID
)
BROWSER = EVIDENCE / "browser"
DB_PATH = EVIDENCE / "learning_closed_loop_runtime.sqlite3"
PORT = int(os.getenv("EDUMATRIX_DEMO_CLOSED_LOOP_PORT", "8973"))
BASE_URL = f"http://127.0.0.1:{PORT}"
COURSE_ID = "course-ai-deep-learning-agents-v1"
PASSWORD = "ClosedLoop-Demo-2026!"
DEMO_CHAPTER_TITLE = "D2L 深度学习计算"
DEMO_KNOWLEDGE_POINT_TITLE = "优化算法、正则化与训练稳定性"

ROUND1 = (
    "优化算法就是让损失下降，正则化可以防止过拟合，训练不稳定时可以调整学习率。"
    "我知道这些词，但还说不清训练损失和验证损失分离时应该怎样判断，也不清楚早停与 L2 的区别。"
)
ROUND2 = (
    "训练稳定性不能只看训练损失。若训练损失继续下降而验证损失连续上升，说明模型正在记忆训练样本，"
    "泛化能力开始变差。L2 正则化把权重平方和加入目标函数，通过限制参数规模降低模型复杂度；"
    "早停则监控验证指标，在连续若干轮没有改善时停止并恢复最佳检查点。两者可以联合使用，但作用环节不同。"
    "例如固定数据划分后，同时比较不同正则化强度、学习率和 patience 的训练/验证曲线，保留验证损失最低的模型。"
    "边界是验证集过小、标签噪声或数据漂移也会造成波动，所以不能凭单轮上升判断过拟合，要结合连续趋势和独立测试集复核。"
)
FEYNMAN_QUESTION = "为什么训练损失继续下降但验证损失上升时不应该一直训练，L2 正则化和早停分别解决什么问题？"


def digest(path: Path) -> str | None:
    if not path.exists():
        return None
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest().upper()


def formal_snapshot() -> dict[str, Any]:
    database = ROOT / "edumatrix.db"
    manifest_path = (
        ROOT
        / "outputs"
        / "原系统融合重构执行"
        / "evidence"
        / "context_recovery"
        / "active_manifest.json"
    )
    checkpoint_path = manifest_path.with_name("current_checkpoint.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    return {
        "database": {"exists": database.exists(), "sha256": digest(database)},
        "active_manifest": {
            "sha256": digest(manifest_path),
            "status": manifest.get("status"),
            "active_version": manifest.get("active_version"),
        },
        "official_checkpoint": {
            "sha256": digest(checkpoint_path),
            "phase": checkpoint.get("phase"),
            "task": checkpoint.get("task"),
            "state": checkpoint.get("state"),
            "gate": checkpoint.get("gate"),
        },
    }


def clear_runtime() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    BROWSER.mkdir(parents=True, exist_ok=True)
    for item in BROWSER.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        else:
            shutil.rmtree(item)
    for name in (
        "browser_report.json",
        "backend.log",
        "seed.log",
        "screenshot_manifest.md",
        f"{TASK_ID}-report.md",
        f"{TASK_ID}-THEORY-REPORT.md",
        f"{TASK_ID}-ISSUE-REPORT.md",
    ):
        path = EVIDENCE / name
        if path.exists():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()


def runtime_env() -> dict[str, str]:
    env = master.runtime_env()
    env.update(
        {
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "closed-loop-isolated-secret",
            "EDUMATRIX_CHAT_RESOURCE_DEMO_EXECUTION": "1",
            "EDUMATRIX_SANDBOX_MODE": "trusted_local",
            "EDUMATRIX_SANDBOX_TIMEOUT": "10",
            "EDUMATRIX_SANDBOX_MAX_OUTPUT_BYTES": "100000",
        }
    )
    return env


def configure_reused_modules() -> None:
    master.EVIDENCE = EVIDENCE
    master.OUTPUT_DIR = BROWSER
    master.DB_PATH = DB_PATH
    master.PORT = PORT
    master.BASE_URL = BASE_URL
    master.COURSE_ID = COURSE_ID
    master.PASSWORD = PASSWORD

    feynman_audit.OUTPUT = EVIDENCE
    feynman_audit.BROWSER_OUTPUT = BROWSER
    feynman_audit.DB = DB_PATH
    feynman_audit.PORT = PORT
    feynman_audit.BASE_URL = BASE_URL
    feynman_audit.COURSE_ID = COURSE_ID

    resource_audit.EVIDENCE = EVIDENCE
    resource_audit.BROWSER = BROWSER
    resource_audit.DB_PATH = DB_PATH
    resource_audit.PORT = PORT
    resource_audit.BASE_URL = BASE_URL

    exam_audit.OUTPUT_DIR = BROWSER
    exam_audit.COURSE_ID = COURSE_ID
    chat_audit.OUT = BROWSER
    chat_audit.BASE_URL = BASE_URL
    chat_audit.COURSE_ID = COURSE_ID


def port_open() -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", PORT)) == 0


def wait_port(expected: bool, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open() is expected:
            return
        time.sleep(0.25)
    raise RuntimeError(f"port {PORT} did not reach expected state {expected}")


def start_service(env: dict[str, str]) -> subprocess.Popen:
    log = (EVIDENCE / "backend.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    process._edumatrix_log = log  # type: ignore[attr-defined]
    wait_port(True)
    return process


def stop_service(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=20,
        )
        process.wait(timeout=10)
    log = getattr(process, "_edumatrix_log", None)
    if log is not None:
        log.close()
    wait_port(False, 20)


def browser_diagnostics(page: Page, report: dict[str, Any]) -> None:
    def response(response) -> None:
        if response.status >= 400:
            parsed = urlparse(response.url)
            if response.status == 403 and parsed.path == "/api/v1/competition-demo/context":
                report["authorization_boundaries"].append(
                    {"status": response.status, "url": response.url, "result": "student_access_denied"}
                )
                return
            report["http_errors"].append({"status": response.status, "url": response.url})

    def console(message) -> None:
        expected_403 = (
            message.text == "Failed to load resource: the server responded with a status of 403 (Forbidden)"
            and report["authorization_boundaries"]
        )
        if message.type == "error" and not expected_403:
            report["console_errors"].append(message.text)

    def request(request) -> None:
        parsed = urlparse(request.url)
        if parsed.scheme in {"http", "https"} and parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(request.url)

    page.on("response", response)
    page.on("request", request)
    page.on(
        "requestfailed",
        lambda request: report["failed_requests"].append(
            {"url": request.url, "failure": request.failure}
        )
        if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"}
        else None,
    )
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", console)


def visible_metrics(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const intersects = rect => rect.width > 1 && rect.height > 1
            && rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
          const visible = element => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            if (style.display === 'none' || style.visibility === 'hidden'
              || Number(style.opacity) <= 0 || !intersects(rect)) return false;
            const x = Math.max(0, Math.min(innerWidth - 1, rect.left + rect.width / 2));
            const y = Math.max(0, Math.min(innerHeight - 1, rect.top + rect.height / 2));
            const topmost = document.elementFromPoint(x, y);
            return Boolean(topmost && (topmost === element || element.contains(topmost) || topmost.contains(element)));
          };
          const visibleControl = element => {
            if (!visible(element)) return false;
            const rect = element.getBoundingClientRect();
            const x = Math.max(0, Math.min(innerWidth - 1, rect.left + rect.width / 2));
            const y = Math.max(0, Math.min(innerHeight - 1, rect.top + rect.height / 2));
            const topmost = document.elementFromPoint(x, y);
            return Boolean(topmost && (topmost === element || element.contains(topmost)));
          };
          const leafText = [...document.querySelectorAll('h1,h2,h3,h4,p,span,strong,small,label,button,a,li,dt,dd')]
            .filter(visible)
            .filter(element => element.children.length === 0 && (element.textContent || '').trim());
          const smallText = leafText
            .filter(element => parseFloat(getComputedStyle(element).fontSize) < 13.9)
            .map(element => ({ text: element.textContent.trim().slice(0, 90), size: getComputedStyle(element).fontSize }))
            .slice(0, 30);
          const clippedText = leafText.filter(element => {
            const style = getComputedStyle(element);
            if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false;
            return element.scrollWidth > element.clientWidth + 4 || element.scrollHeight > element.clientHeight + 4;
          }).map(element => element.textContent.trim().slice(0, 90)).slice(0, 30);
          const controls = [...document.querySelectorAll('button,a[href],input,textarea,select,[role=button]')].filter(visibleControl);
          const overlaps = [];
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i], b = controls[j];
            if (a.contains(b) || b.contains(a)) continue;
            const ar = a.getBoundingClientRect(), br = b.getBoundingClientRect();
            const width = Math.min(ar.right, br.right) - Math.max(ar.left, br.left);
            const height = Math.min(ar.bottom, br.bottom) - Math.max(ar.top, br.top);
            if (width > 12 && height > 12) overlaps.push([
              (a.getAttribute('aria-label') || a.textContent || a.tagName).trim().slice(0, 60),
              (b.getAttribute('aria-label') || b.textContent || b.tagName).trim().slice(0, 60),
              Math.round(width), Math.round(height),
            ]);
          }
          return {
            viewport: [innerWidth, innerHeight],
            bodyTextLength: (document.body.innerText || '').trim().length,
            pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
            documentWidth: document.documentElement.scrollWidth,
            smallText,
            clippedText,
            controlOverlaps: overlaps.slice(0, 20),
            scrollY: Math.round(scrollY),
          };
        }"""
    )


def capture(page: Page, report: dict[str, Any], filename: str, *, allow_empty: bool = False) -> None:
    page.wait_for_timeout(500)
    metrics = visible_metrics(page)
    path = BROWSER / filename
    page.screenshot(path=str(path), full_page=False, animations="disabled")
    report["screenshots"].append(
        {
            "name": filename,
            "path": str(path),
            "url": page.url,
            "viewport": list(page.viewport_size.values()),
            "metrics": metrics,
        }
    )
    if metrics["pageOverflow"]:
        raise AssertionError(f"horizontal overflow in {filename}: {metrics}")
    if not allow_empty and metrics["bodyTextLength"] < 120:
        raise AssertionError(f"unexpectedly empty page in {filename}: {metrics}")
    if metrics["smallText"]:
        raise AssertionError(f"visible text below 14px in {filename}: {metrics['smallText']}")
    if metrics["clippedText"]:
        raise AssertionError(f"visible text clipping in {filename}: {metrics['clippedText']}")
    if metrics["controlOverlaps"]:
        raise AssertionError(f"overlapping controls in {filename}: {metrics['controlOverlaps']}")


def api_get(page: Page, token: str, path: str) -> dict[str, Any]:
    response = page.request.get(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if not response.ok:
        raise AssertionError(f"GET {path} failed: {response.status} {response.text()}")
    return response.json()


def owner_public_id(username: str) -> str:
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        raise RuntimeError("journey owner is missing")
    return str(row[0])


def json_value(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


def profile_state(username: str) -> dict[str, Any]:
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        profile = db.execute(
            "SELECT focus_level,cognitive_load,frustration_index,concept_mastery,weak_points,"
            "dimension_states,mental_state_history,knowledge_traces FROM student_profiles WHERE student_id=?",
            (username,),
        ).fetchone()
        owner = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
        events = db.execute(
            "SELECT id,event_type,course_id,object_type,object_id,evidence_status,mastery_eligible,"
            "completion_effect,context_ref,payload,occurred_at FROM learning_events "
            "WHERE owner_public_id=? ORDER BY occurred_at,id",
            (owner,),
        ).fetchall()
        snapshots = db.execute(
            "SELECT id,profile_version,snapshot,created_at FROM profile_snapshots "
            "WHERE owner_public_id=? ORDER BY created_at,id",
            (owner,),
        ).fetchall()
    if profile is None:
        raise RuntimeError("journey profile is missing")
    return {
        "focus_level": profile["focus_level"],
        "cognitive_load": profile["cognitive_load"],
        "frustration_index": profile["frustration_index"],
        "concept_mastery": json_value(profile["concept_mastery"], {}),
        "weak_points": json_value(profile["weak_points"], []),
        "dimension_states": json_value(profile["dimension_states"], {}),
        "mental_state_history": json_value(profile["mental_state_history"], []),
        "knowledge_traces": json_value(profile["knowledge_traces"], {}),
        "events": [
            {
                **{key: row[key] for key in row.keys() if key not in {"context_ref", "payload"}},
                "context_ref": json_value(row["context_ref"], {}),
                "payload": json_value(row["payload"], {}),
            }
            for row in events
        ],
        "snapshots": [
            {
                "id": row["id"],
                "profile_version": row["profile_version"],
                "snapshot": json_value(row["snapshot"], {}),
                "created_at": row["created_at"],
            }
            for row in snapshots
        ],
    }


def capture_profile_baseline(page: Page, report: dict[str, Any], username: str) -> None:
    page.goto(
        f"{BASE_URL}/profile/learning?course_id={COURSE_ID}&student_id={username}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.get_by_text("学习画像分析", exact=True).wait_for(state="visible", timeout=45_000)
    capture(page, report, "07-profile-baseline-1440x900.png")
    page.get_by_role("tab", name="十维分析", exact=True).click()
    page.locator(".profile-detail-section").scroll_into_view_if_needed()
    capture(page, report, "08-profile-baseline-ten-dimensions-1440x900.png")


def wait_generation_job(page: Page, token: str, timeout: float = 90) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        listing = api_get(
            page,
            token,
            f"/api/v1/resource-bundles/generation-jobs?course_id={COURSE_ID}",
        )
        items = listing.get("items") or []
        if items:
            latest = items[0]
            job = api_get(
                page,
                token,
                f"/api/v1/resource-bundles/generation-jobs/{latest['job_id']}",
            )
            if job.get("status") in {"succeeded", "completed", "partial_success", "failed"}:
                return job
        page.wait_for_timeout(750)
    raise TimeoutError(f"resource generation did not finish: {latest}")


def open_bundle_item(page: Page, bundle_url: str, item_type: str) -> None:
    page.goto(bundle_url, wait_until="networkidle", timeout=60_000)
    workspace = page.get_by_test_id("resource-bundle-workspace")
    workspace.wait_for(state="visible", timeout=45_000)
    row = page.get_by_test_id(f"bundle-item-{item_type}")
    row.get_by_role("button", name="打开", exact=True).click()


def resource_generation_journey(
    page: Page,
    report: dict[str, Any],
    token: str,
    path_id: str,
) -> dict[str, Any]:
    if not path_id:
        raise AssertionError("confirmed learning path id is missing")
    page.goto(
        f"{BASE_URL}/workspace/path?course_id={COURSE_ID}&path_id={path_id}"
        f"&view=subject&subject_id={COURSE_ID}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.get_by_test_id("path-overview").wait_for(state="visible", timeout=45_000)
    choices = page.get_by_test_id("today-knowledge-points").locator("button")
    choices.first.wait_for(state="visible", timeout=30_000)
    choices.first.click()
    selected = page.get_by_test_id("selected-knowledge-point")
    selected.wait_for(state="visible", timeout=30_000)
    selected_text = selected.inner_text()
    if DEMO_KNOWLEDGE_POINT_TITLE not in selected_text or DEMO_CHAPTER_TITLE not in selected_text:
        raise AssertionError(f"path resource topic and parent chapter are not both visible: {selected_text}")
    capture(page, report, "09-path-today-knowledge-point-1440x900.png")

    page.get_by_role("button", name="一键生成完整资源包", exact=True).click()
    page.wait_for_url(re.compile(r".*/learn\?.*intent=path_bundle"), timeout=45_000)
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible", timeout=45_000)
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=chat-compact-resource-links] button').length === 9",
        timeout=90_000,
    )
    chat_topic = page.locator(".answer-heading > div > span").first.inner_text()
    if chat_topic != DEMO_KNOWLEDGE_POINT_TITLE or page.get_by_text("未绑定具体知识点", exact=True).count():
        raise AssertionError(f"resource chat lost the selected knowledge point title: {chat_topic}")
    capture(page, report, "10-chat-resource-package-complete-1440x900.png")
    job = wait_generation_job(page, token)
    if job.get("status") not in {"succeeded", "completed"}:
        raise AssertionError(f"resource package failed: {job}")
    if not job.get("items") or any(item.get("state") != "succeeded" for item in job["items"]):
        raise AssertionError(f"resource package is incomplete: {job}")
    manifest = job.get("manifest") or {}
    if not manifest.get("path_id") or not manifest.get("task_id"):
        raise AssertionError(f"path resource manifest lost task context: {manifest}")

    bundle_url = (
        f"{BASE_URL}/workspace/resources/bundles/{job['job_id']}?course_id={COURSE_ID}"
        f"&return_task={manifest['task_id']}"
    )
    page.goto(bundle_url, wait_until="networkidle", timeout=60_000)
    page.get_by_text("完整资源包已就绪", exact=True).wait_for(state="visible", timeout=45_000)
    capture(page, report, "11-resource-package-nine-items-1440x900.png")
    return {
        "path_id": manifest["path_id"],
        "task_id": manifest["task_id"],
        "selected_text": selected_text,
        "job": job,
        "bundle_url": bundle_url,
    }


def job_item(job: dict[str, Any], item_type: str) -> dict[str, Any]:
    return next(item for item in job["items"] if item.get("type") == item_type)


def inspect_passive_resources(page: Page, report: dict[str, Any], journey: dict[str, Any]) -> None:
    bundle_url = journey["bundle_url"]
    open_bundle_item(page, bundle_url, "handout")
    workspace = page.get_by_test_id("handout-workspace")
    workspace.wait_for(state="visible", timeout=45_000)
    workspace.get_by_text("学习检查", exact=True).first.wait_for(state="visible", timeout=45_000)
    handout_text = workspace.inner_text()
    if len(handout_text) < 500 or "学习检查" not in handout_text:
        raise AssertionError(f"generated handout is incomplete: {handout_text[:1000]}")
    capture(page, report, "12-handout-real-reading-1440x900.png")

    open_bundle_item(page, bundle_url, "mind_map")
    page.get_by_test_id("mindmap-workspace").wait_for(state="visible", timeout=45_000)
    page.wait_for_timeout(1200)
    layout = feynman_audit.node_layout(page)
    if layout["count"] < 2 or layout["emptyLabels"] or layout["overlaps"]:
        raise AssertionError(f"mind map visual layout is invalid: {layout}")
    report["checks"]["mindmap_layout"] = layout
    capture(page, report, "13-mindmap-real-reading-1440x900.png")


def complete_quiz(page: Page, report: dict[str, Any], journey: dict[str, Any]) -> None:
    open_bundle_item(page, journey["bundle_url"], "quiz")
    workspace = page.get_by_test_id("quiz-resource-workspace")
    workspace.wait_for(state="visible", timeout=45_000)
    card = workspace.get_by_test_id("inline-quiz-card")
    card.wait_for(state="visible", timeout=30_000)
    if card.locator(".option-list label").count() < 2:
        raise AssertionError("quiz options are incomplete")
    capture(page, report, "14-resource-quiz-question-1440x900.png")
    card.locator(".option-list label").nth(1).click()
    card.get_by_role("button", name="提交答案", exact=True).click()
    card.get_by_text("这次还不正确", exact=True).wait_for(state="visible", timeout=45_000)
    explanation_row = card.locator(".feedback-panel p").filter(has_text="解析：").first
    explanation_row.scroll_into_view_if_needed()
    explanation = explanation_row.inner_text()
    if len(explanation) < 20 or "证据核验通过" in explanation:
        raise AssertionError(f"quiz explanation is not question-specific: {explanation}")
    capture(page, report, "15-resource-quiz-wrong-and-explanation-1440x900.png")
    card.get_by_role("button", name="修改答案", exact=True).click()
    card.locator(".option-list label").first.click()
    card.get_by_role("button", name="提交新答案", exact=True).click()
    card.get_by_text("回答正确", exact=True).wait_for(state="visible", timeout=45_000)
    explanation_row.scroll_into_view_if_needed()
    capture(page, report, "16-resource-quiz-corrected-1440x900.png")
    report["checks"]["resource_quiz_explanation"] = explanation


def run_code_learning(page: Page, report: dict[str, Any], journey: dict[str, Any]) -> None:
    item = job_item(journey["job"], "code_sandbox")
    resource_id = item["resource"]["resource_id"]
    open_bundle_item(page, journey["bundle_url"], "code_sandbox")
    page.get_by_test_id("code-sandbox-workspace").wait_for(state="visible", timeout=45_000)
    query = parse_qs(urlparse(page.url).query)
    if query.get("task_id", [""])[0] != journey["task_id"] or query.get("path_id", [""])[0] != journey["path_id"]:
        raise AssertionError(f"resource route lost path context: {page.url}")
    detail = api_get(page, report["token"], f"/api/v1/m5/resources/{resource_id}")
    structured = detail["code_sandbox"]["current"]["structured"]
    public_task_text = page.get_by_test_id("code-sandbox-workspace").inner_text()
    if any(marker in public_task_text for marker in ("上游仓库", "固定版本", "文件路径")) or re.search(
        r"\b[0-9a-f]{12,64}\b", public_task_text, re.I,
    ):
        raise AssertionError("code task exposes repository metadata or an internal content hash")
    capture(page, report, "17-code-learning-ready-1440x900.png")
    page.locator(".stdin-panel textarea").fill(str(structured.get("standardInput") or ""))
    page.get_by_role("button", name="运行代码", exact=True).click()
    page.locator(".result-summary").get_by_text("运行成功", exact=True).wait_for(state="visible", timeout=60_000)
    stdout = page.locator(".terminal-output").inner_text()
    if not stdout.strip():
        raise AssertionError("code resource returned empty stdout")
    chart_button = page.get_by_role("button", name="图表", exact=False)
    if chart_button.count():
        chart_button.click()
        page.locator(".plot-viewer img").wait_for(state="visible", timeout=30_000)
    stderr_tab = page.locator(".result-tabs button").nth(1).inner_text().strip()
    if "1" in stderr_tab and "警告" not in stderr_tab:
        raise AssertionError(f"successful run mislabeled stderr as an error: {stderr_tab}")
    capture(page, report, "18-code-learning-real-run-1440x900.png")
    page.get_by_role("button", name="完成学习", exact=True).click()
    page.get_by_text("本次学习已完成", exact=True).wait_for(state="visible", timeout=45_000)
    capture(page, report, "19-code-learning-trusted-completion-1440x900.png")
    report["checks"]["code_learning"] = {"stdout": stdout, "stderr_tab": stderr_tab, "route": page.url}


def run_interactive_learning(page: Page, report: dict[str, Any], journey: dict[str, Any]) -> None:
    item = job_item(journey["job"], "interactive_model")
    resource_id = item["resource"]["resource_id"]
    detail = api_get(page, report["token"], f"/api/v1/m5/resources/{resource_id}")
    structured = detail["interactive_model"]["current"]["structured"]
    open_bundle_item(page, journey["bundle_url"], "interactive_model")
    page.get_by_test_id("interactive-lab-workspace").wait_for(state="visible", timeout=45_000)
    page.locator(".model-layout").wait_for(state="visible", timeout=45_000)
    capture(page, report, "20-interactive-learning-ready-1440x900.png")
    first_values = resource_audit.set_parameter_controls(page, structured, 1)
    page.get_by_role("button", name=re.compile("开始实验|按当前参数运行")).click()
    page.get_by_text("实验结果已更新", exact=False).wait_for(state="visible", timeout=60_000)
    first_metrics = page.get_by_test_id("lab-results").inner_text()
    capture(page, report, "21-interactive-learning-first-run-1440x900.png")
    second_values = resource_audit.set_parameter_controls(page, structured, 2)
    page.get_by_role("button", name="按当前参数运行", exact=True).click()
    page.get_by_text("实验结果已更新", exact=False).wait_for(state="visible", timeout=60_000)
    second_metrics = page.get_by_test_id("lab-results").inner_text()
    if first_metrics == second_metrics:
        raise AssertionError("interactive metrics did not change after parameter change")
    labels = [str(item.get("label") or "参数") for item in structured.get("parameters") or []]
    observation = (
        f"我比较了{labels[0] if labels else '第一组参数'}前后两组结果，指标和曲线发生了可见变化；"
        "在其他条件保持不变时，学习率过大会增加损失振荡，适度正则化有助于抑制过拟合。"
        "一次运行不能证明参数全局最优，还应结合收敛速度、训练稳定性和验证指标复核。"
    )
    if any(term in observation for term in ("精确匹配", "语义召回", "来源缺失", "RAG", "检索", "重排")):
        raise AssertionError(f"optimization observation was hijacked by a retrieval topic: {observation}")
    page.get_by_role("textbox", name="观察结论").fill(observation)
    page.get_by_role("button", name="提交观察结论", exact=True).click()
    page.get_by_test_id("interactive-model-completion").wait_for(state="visible", timeout=45_000)
    capture(page, report, "22-interactive-learning-complete-1440x900.png")
    report["checks"]["interactive_learning"] = {
        "template_id": structured.get("templateId"),
        "first_values": first_values,
        "second_values": second_values,
        "first_metrics": first_metrics,
        "second_metrics": second_metrics,
    }


def feynman_action(page: Page, name: str, text: str | None = None, selector: str | None = None) -> None:
    if text is not None:
        page.locator(selector or "textarea:visible").first.fill(text)
    button = page.get_by_role("button", name=name, exact=True)
    button.wait_for(state="visible", timeout=30_000)
    page.wait_for_function(
        "label => [...document.querySelectorAll('button')].some(button => button.innerText.trim() === label && !button.disabled)",
        arg=name,
        timeout=30_000,
    )
    button.click()


def run_feynman_learning(page: Page, report: dict[str, Any], journey: dict[str, Any]) -> None:
    open_bundle_item(page, journey["bundle_url"], "feynman")
    page.get_by_role("heading", name="五阶段进度", exact=True).wait_for(state="visible", timeout=45_000)
    initial_text = page.locator("main.feynman-page").inner_text()
    if re.search(r"\b(?:f\d+-)?(?:kp|event|trace|run)-[a-z0-9-]{6,}\b", initial_text, re.I):
        raise AssertionError("Feynman task exposes an internal identifier")
    if any(marker in initial_text for marker in ("召回率", "向量检索", "关键词检索")):
        raise AssertionError("Feynman task was overridden by an unrelated profile weakness")
    capture(page, report, "23-feynman-first-retelling-1440x900.png")
    feynman_action(page, "保存第一次复述", ROUND1, "#round1:visible")
    feynman_action(page, "生成第一次评价")
    first_panel = page.locator(".evaluation-panel").first
    first_panel.wait_for(state="visible", timeout=45_000)
    first_evaluation = first_panel.inner_text()
    if not all(label in first_evaluation for label in ("核心含义", "机制与步骤", "成立条件", "边界与反例")):
        raise AssertionError(f"Feynman first evaluation is incomplete: {first_evaluation}")
    if re.search(r"\b(?:f\d+-)?(?:kp|event|trace|run)-[a-z0-9-]{6,}\b", first_evaluation, re.I):
        raise AssertionError("Feynman evaluation exposes an internal identifier")
    first_panel.scroll_into_view_if_needed()
    capture(page, report, "24-feynman-first-ai-evaluation-1440x900.png")
    feynman_action(page, "进入真实疑问")
    page.get_by_label("我仍然不明白").fill(FEYNMAN_QUESTION)
    feynman_action(page, "提交疑问并查看回答")
    answer = page.locator(".question-answer:visible").first
    answer.wait_for(state="visible", timeout=45_000)
    answer_text = answer.inner_text()
    if len(answer_text) < 300 or not all(marker in answer_text for marker in ("训练损失", "验证损失", "L2", "早停")):
        raise AssertionError(f"Feynman grounded answer is too short: {answer_text}")
    workspace_text = page.locator("main.feynman-page").inner_text()
    forbidden = ("deterministic_local", "context_fingerprint", "sha256", "feynman_submitted", ".md", "kp-")
    leaked = [marker for marker in forbidden if marker.lower() in workspace_text.lower()]
    if leaked:
        raise AssertionError(f"Feynman page exposes internal metadata: {leaked}")
    answer.scroll_into_view_if_needed()
    capture(page, report, "25-feynman-grounded-question-answer-1440x900.png")
    feynman_action(page, "保存第二次复述", ROUND2, "#round2:visible")
    feynman_action(page, "生成第二次评价与对比")
    comparison = page.locator(".comparison-summary")
    comparison.wait_for(state="visible", timeout=45_000)
    comparison_text = comparison.inner_text()
    if "分数变化" not in comparison_text:
        raise AssertionError(f"Feynman comparison is incomplete: {comparison_text}")
    comparison.scroll_into_view_if_needed()
    capture(page, report, "26-feynman-understanding-comparison-1440x900.png")
    feynman_action(page, "应用到后续学习")
    page.get_by_role("heading", name="已应用到后续学习", exact=True).wait_for(state="visible", timeout=45_000)
    capture(page, report, "27-feynman-applied-to-profile-1440x900.png")
    report["checks"]["feynman"] = {
        "first_evaluation": first_evaluation,
        "grounded_answer": answer_text,
        "comparison": comparison_text,
    }


def verify_path_complete(page: Page, report: dict[str, Any], journey: dict[str, Any]) -> None:
    page.goto(
        f"{BASE_URL}/workspace/path?course_id={COURSE_ID}&path_id={journey['path_id']}"
        f"&view=subject&subject_id={COURSE_ID}&node_id={journey['task_id']}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.get_by_test_id("path-overview").wait_for(state="visible", timeout=45_000)
    receipt = page.get_by_test_id("path-completion-receipt")
    receipt.wait_for(state="visible", timeout=30_000)
    receipt_text = receipt.inner_text()
    if "本轮学习已完成" not in receipt_text or "1/1 完成" not in receipt_text:
        raise AssertionError(f"completed path task is not visibly reconciled: {receipt_text}")
    receipt.evaluate("element => element.scrollIntoView({ block: 'center' })")
    text = page.get_by_test_id("path-overview").inner_text()
    capture(page, report, "28-path-task-after-trusted-learning-1440x900.png")
    gate = api_get(page, report["token"], f"/api/v1/m5/assessment/exam-gate?course_id={COURSE_ID}")
    if not gate.get("unlocked"):
        raise AssertionError(f"trusted learning did not unlock the exam gate: {gate}")
    report["checks"]["path_after_learning"] = {"text": text[:3000], "completion_receipt": receipt_text, "gate": gate}


def complete_formal_exam(page: Page, report: dict[str, Any]) -> str:
    page.goto(
        f"{BASE_URL}/workspace/assessment/exams?course_id={COURSE_ID}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.get_by_test_id("exam-builder-unlocked").wait_for(state="visible", timeout=45_000)
    exam_audit.clear_optional_type(page, "简答题")
    page.get_by_role("button", name="增加单选题", exact=True).click()
    page.get_by_label("检验主题").fill("混合检索、来源核验与智能体学习闭环")
    builder = page.get_by_test_id("exam-builder-unlocked")
    builder.locator(".unlock-mark").scroll_into_view_if_needed()
    capture(page, report, "29-intelligent-exam-builder-unlocked-1440x900.png")
    generate_button = page.get_by_role("button", name="生成并冻结试卷", exact=True)
    generate_button.scroll_into_view_if_needed()
    capture(page, report, "29b-intelligent-exam-builder-action-1440x900.png")
    generate_button.click()
    page.get_by_test_id("generated-exam-preview").wait_for(state="visible", timeout=60_000)
    exam_id = page.url.split("/workspace/assessment/exams/", 1)[1].split("?", 1)[0]
    capture(page, report, "30-intelligent-exam-frozen-preview-1440x900.png")
    page.get_by_role("button", name="开始作答", exact=True).click()
    page.get_by_test_id("exam-taking").wait_for(state="visible", timeout=45_000)
    capture(page, report, "31-intelligent-exam-taking-1440x900.png")

    page.locator(".option-list button").nth(1).click()
    exam_audit.save_current(page)
    page.locator(".option-list button").nth(0).click()
    exam_audit.save_current(page)
    page.locator(".option-list button").nth(0).click()
    exam_audit.save_current(page)
    page.get_by_role("button", name="错误", exact=True).click()
    exam_audit.save_current(page, last=True)
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="提交试卷", exact=True).click()
    report_panel = page.get_by_test_id("formal-exam-report")
    report_panel.wait_for(state="visible", timeout=90_000)
    if page.get_by_text("正确答案", exact=True).count() < 4 or page.get_by_text("解析", exact=True).count() < 4:
        raise AssertionError("formal exam report does not contain four question explanations")
    report_text = report_panel.inner_text()
    if re.search(r"\b(?:f\d+-)?(?:kp|event|trace|run)-[a-z0-9-]{6,}\b", report_text, re.I):
        raise AssertionError("formal exam report exposes an internal identifier")
    explanation_texts = []
    review_items = report_panel.locator(".answer-review article")
    if review_items.count() != 4:
        raise AssertionError(f"formal exam report item count is not four: {review_items.count()}")
    for index in range(review_items.count()):
        review_item = review_items.nth(index)
        prompt = review_item.locator("h4").inner_text().strip()
        explanation = review_item.locator("dl > div").nth(2).locator("dd").inner_text().strip()
        knowledge_match = re.search(r"知识点“([^”]+)”", prompt)
        if len(explanation) < 120 or not knowledge_match or knowledge_match.group(1) not in explanation:
            raise AssertionError(
                f"formal exam item {index + 1} explanation is not question-specific: {explanation[:600]}"
            )
        explanation_texts.append(explanation)
        review_item.scroll_into_view_if_needed()
        page.evaluate("window.scrollBy(0, -110)")
        capture(page, report, f"32-exam-question-{index + 1}-explanation-1440x900.png")
    if len(set(explanation_texts)) != len(explanation_texts):
        raise AssertionError("formal exam explanations repeat across different questions")
    report_panel.scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, -72)")
    capture(page, report, "32-intelligent-exam-report-and-explanations-1440x900.png")
    report["checks"]["formal_exam"] = {"exam_id": exam_id, "report_text": report_text[:6000]}
    return exam_id


def send_chat_round(page: Page, report: dict[str, Any], number: int, question: str) -> str:
    answer, message_id = chat_audit.send_and_wait(page, question)
    assistant = page.locator(f'[data-message-id="{message_id}"]')
    assistant.scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, -90)")
    capture(page, report, f"{32 + number:02d}-chat-round-{number}-1440x900.png")
    report["checks"].setdefault("chat_rounds", []).append(
        {"round": number, "question": question, "answer": answer, "message_id": message_id}
    )
    return answer


def complete_chat(page: Page, report: dict[str, Any]) -> None:
    with sqlite3.connect(DB_PATH) as db:
        before_events = db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0]
        before_jobs = db.execute("SELECT COUNT(*) FROM generation_tasks").fetchone()[0]
    page.goto(f"{BASE_URL}/chat?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible", timeout=45_000)
    page.get_by_role("button", name="新建对话", exact=True).click()
    page.wait_for_function("() => document.querySelectorAll('.message-row').length === 0", timeout=30_000)
    questions = [
        "我喜欢先看直观例子。请用一个生活类比完整解释混合检索为什么要结合关键词和向量召回。",
        "现在改用严格推导风格，按输入、评分归一化、候选合并、重排和边界条件逐步说明混合检索。",
        "请给我一段可以直接运行的 Python 示例，比较关键词权重和向量权重变化对混合检索排序的影响，并解释输出。",
        "结合我刚才先答错再纠正、完成代码和交互实验、费曼复述，以及智能组卷50分的表现，帮我反思哪里已经掌握，下一步怎样降低认知负荷并巩固薄弱点？",
    ]
    answers = [send_chat_round(page, report, index, question) for index, question in enumerate(questions, 1)]
    if any(len(answer) < 450 for answer in answers):
        raise AssertionError(f"chat answer is too short: {[len(answer) for answer in answers]}")
    if len(set(answers)) != len(answers):
        raise AssertionError("chat rounds returned duplicate answers")
    code_answer = answers[2].lower()
    if not all(marker in code_answer for marker in ("python", "def rank", "keyword_weight", "权重")):
        raise AssertionError("code-style chat answer did not address the current question")
    with sqlite3.connect(DB_PATH) as db:
        after_events = db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0]
        after_jobs = db.execute("SELECT COUNT(*) FROM generation_tasks").fetchone()[0]
    report["checks"]["chat_boundaries"] = {
        "learning_events_before": before_events,
        "learning_events_after": after_events,
        "generation_jobs_before": before_jobs,
        "generation_jobs_after": after_jobs,
        "ordinary_chat_profile_neutral": before_events == after_events,
        "ordinary_chat_created_no_resource": before_jobs == after_jobs,
        "answer_lengths": [len(answer) for answer in answers],
        "answers_distinct": len(set(answers)) == len(answers),
    }


def capture_final_profile(page: Page, report: dict[str, Any], username: str) -> None:
    page.goto(
        f"{BASE_URL}/profile/learning?course_id={COURSE_ID}&student_id={username}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.get_by_text("学习画像分析", exact=True).wait_for(state="visible", timeout=45_000)
    summary_text = page.locator("body").inner_text()
    if "数学推理仍需更多证据确认" in summary_text:
        raise AssertionError("profile top summary still overrides current course weak-point evidence")
    capture(page, report, "37-profile-final-summary-1440x900.png")
    evidence_rail = page.get_by_test_id("profile-node-evidence")
    evidence_rail.scroll_into_view_if_needed()
    capture(page, report, "38-profile-mastery-and-visible-evidence-1440x900.png")

    page.get_by_role("tab", name="十维分析", exact=True).click()
    dimension_cards = page.locator(".profile-detail-section > div.space-y-4 > div.bg-white")
    dimension_count = dimension_cards.count()
    if dimension_count != 10:
        raise AssertionError(f"expected ten profile dimensions, got {dimension_count}")
    dimension_texts = [dimension_cards.nth(index).inner_text() for index in range(dimension_count)]
    for group_index, start in enumerate(range(0, dimension_count, 2), start=1):
        dimension_cards.nth(start).evaluate("element => element.scrollIntoView({ block: 'center' })")
        capture(page, report, f"39-{group_index}-profile-ten-dimensions-{start + 1:02d}-{min(start + 2, dimension_count):02d}-1440x900.png")
    report["checks"]["ten_dimensions_visual"] = {
        "count": dimension_count,
        "cards": dimension_texts,
    }

    page.get_by_role("tab", name="薄弱点归因", exact=True).click()
    page.locator(".profile-detail-section").scroll_into_view_if_needed()
    capture(page, report, "41-profile-weak-points-1440x900.png")

    page.get_by_test_id("digital-twin-tab").click()
    mental = page.get_by_test_id("mental-state-card")
    mental.evaluate("element => element.scrollIntoView({ block: 'center' })")
    page.get_by_test_id("mental-state-summary").wait_for(state="visible", timeout=30_000)
    canvas = page.get_by_test_id("mental-state-chart").locator("canvas")
    canvas.wait_for(state="visible", timeout=30_000)
    canvas_pixels = canvas.evaluate("""canvas => {
      const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
      let visible = 0
      for (let index = 3; index < pixels.length; index += 4) if (pixels[index] > 0) visible += 1
      return { width: canvas.width, height: canvas.height, visible }
    }""")
    if canvas_pixels["visible"] < 500:
        raise AssertionError(f"mental-state chart is blank: {canvas_pixels}")
    capture(page, report, "42-profile-mental-load-and-frustration-1440x900.png")
    report["checks"]["mental_state_visual"] = {
        "summary": page.get_by_test_id("mental-state-summary").inner_text(),
        "canvas": canvas_pixels,
    }

    page.set_viewport_size({"width": 1366, "height": 768})
    page.goto(
        f"{BASE_URL}/profile/learning?course_id={COURSE_ID}&student_id={username}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.get_by_text("学习画像分析", exact=True).wait_for(state="visible", timeout=45_000)
    capture(page, report, "43-profile-final-summary-1366x768.png")
    page.get_by_role("tab", name="十维分析", exact=True).click()
    dimension_cards = page.locator(".profile-detail-section > div.space-y-4 > div.bg-white")
    for group_index, start in enumerate((0, 4, 8), start=1):
        dimension_cards.nth(start).evaluate("element => element.scrollIntoView({ block: 'center' })")
        capture(page, report, f"44-{group_index}-profile-ten-dimensions-{start + 1:02d}-{min(start + 2, 10):02d}-1366x768.png")
    page.get_by_test_id("digital-twin-tab").click()
    mental = page.get_by_test_id("mental-state-card")
    mental.evaluate("element => element.scrollIntoView({ block: 'center' })")
    page.get_by_test_id("mental-state-summary").wait_for(state="visible", timeout=30_000)
    page.get_by_test_id("mental-state-chart").locator("canvas").wait_for(state="visible", timeout=30_000)
    capture(page, report, "45-profile-mental-load-1366x768.png")


def database_audit(username: str) -> dict[str, Any]:
    owner = owner_public_id(username)
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        events = db.execute(
            "SELECT id,event_type,course_id,object_type,object_id,evidence_status,mastery_eligible,"
            "completion_effect,context_ref,payload,occurred_at FROM learning_events "
            "WHERE owner_public_id=? ORDER BY occurred_at,id",
            (owner,),
        ).fetchall()
        attempts = db.execute(
            "SELECT id,mode,score,correct,grading_status,submitted_at FROM assessment_attempts "
            "WHERE owner_public_id=? ORDER BY submitted_at,id",
            (owner,),
        ).fetchall()
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "event_count": len(events),
            "trusted_event_count": sum(
                bool(row["mastery_eligible"]) and row["evidence_status"] == "accepted" for row in events
            ),
            "event_types": [row["event_type"] for row in events],
            "events": [
                {
                    **{key: row[key] for key in row.keys() if key not in {"context_ref", "payload"}},
                    "context_ref": json_value(row["context_ref"], {}),
                    "payload": json_value(row["payload"], {}),
                }
                for row in events
            ],
            "attempts": [dict(row) for row in attempts],
            "resource_jobs": db.execute(
                "SELECT COUNT(*) FROM generation_tasks WHERE owner_public_id=? AND course_id=?",
                (owner, COURSE_ID),
            ).fetchone()[0],
            "chat_messages": db.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE owner_public_id=?",
                (owner,),
            ).fetchone()[0],
            "wrong_questions": db.execute(
                "SELECT COUNT(*) FROM wrong_questions WHERE student_id=?",
                (username,),
            ).fetchone()[0],
            "profile_feedback_snapshots": db.execute(
                "SELECT COUNT(*) FROM profile_snapshots WHERE owner_public_id=? "
                "AND profile_version='f8.learning-feedback.v3'",
                (owner,),
            ).fetchone()[0],
        }


def compare_profile(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = ("focus_level", "cognitive_load", "frustration_index")
    scalar_changes = {
        key: {"before": before.get(key), "after": after.get(key), "delta": round(float(after.get(key) or 0) - float(before.get(key) or 0), 4)}
        for key in keys
    }
    before_dimensions = before.get("dimension_states") or {}
    after_dimensions = after.get("dimension_states") or {}
    dimension_changes = {}
    for key in sorted(set(before_dimensions) | set(after_dimensions)):
        old = before_dimensions.get(key) or {}
        new = after_dimensions.get(key) or {}
        old_score = float(old.get("score") or 0)
        new_score = float(new.get("score") or 0)
        dimension_changes[key] = {
            "before": old_score,
            "after": new_score,
            "delta": round(new_score - old_score, 4),
            "evidence": list(new.get("evidence_fragments") or []),
        }
    return {
        "scalars": scalar_changes,
        "dimensions": dimension_changes,
        "mastery_before": before.get("concept_mastery") or {},
        "mastery_after": after.get("concept_mastery") or {},
        "weak_points_before": before.get("weak_points") or [],
        "weak_points_after": after.get("weak_points") or [],
        "mental_history_before": len(before.get("mental_state_history") or []),
        "mental_history_after": len(after.get("mental_state_history") or []),
        "events_before": len(before.get("events") or []),
        "events_after": len(after.get("events") or []),
    }


def write_reports(report: dict[str, Any]) -> None:
    screenshots = report.get("screenshots") or []
    manifest_lines = ["# Screenshot manifest", ""]
    for index, item in enumerate(screenshots, 1):
        manifest_lines.append(
            f"{index}. `{item['name']}` - {item['viewport'][0]}x{item['viewport'][1]} - `{item['url']}`"
        )
    (EVIDENCE / "screenshot_manifest.md").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    checks = report.get("checks") or {}
    audit = report.get("database_audit") or {}
    journey_lines = [
        f"# {TASK_ID} 连续学生旅程报告",
        "",
        f"- 结果：`{report.get('result')}`",
        f"- 账号：`{report.get('username')}`（隔离 SQLite）",
        f"- 课程：`{COURSE_ID}`",
        f"- 截图：`{len(screenshots)}` 张",
        f"- 模型：`deterministic_local`，外部模型调用：`false`",
        "",
        "## 旅程顺序",
        "",
        "画像基线 → 今日路径知识点 → 九项资源包 → 讲义/思维导图 → 测验错后纠正 → 代码真实运行 → 参数实验 → 费曼复述 → 路径完成 → 智能组卷 → 四轮智能对话 → 最终画像与数字孪生。",
        "",
        "## 机器核对",
        "",
        f"- SQLite integrity：`{audit.get('integrity')}`；外键违规：`{audit.get('foreign_key_violations')}`。",
        f"- 可信学习事件：`{audit.get('trusted_event_count')}`；事件类型：`{', '.join(audit.get('event_types') or [])}`。",
        f"- 普通聊天不新增学习事件：`{checks.get('chat_boundaries', {}).get('ordinary_chat_profile_neutral')}`。",
        f"- 普通聊天不新增资源任务：`{checks.get('chat_boundaries', {}).get('ordinary_chat_created_no_resource')}`。",
        f"- 正式数据库与官方恢复状态未变化：`{report.get('formal_protection', {}).get('unchanged')}`。",
        "",
        "完整截图顺序见 `screenshot_manifest.md`，结构化审计见 `browser_report.json`。",
    ]
    (EVIDENCE / f"{TASK_ID}-report.md").write_text("\n".join(journey_lines) + "\n", encoding="utf-8")

    profile = report.get("profile_comparison") or {}
    theory_lines = [
        f"# {TASK_ID} 画像理论一致性报告",
        "",
        "本次只把服务端接受且可计入掌握度的测验、代码、实验、费曼和正式组卷事件投影到画像；讲义浏览、图谱查看与普通聊天保持中性。",
        "",
        "## 三项连续指标",
        "",
    ]
    for key, value in (profile.get("scalars") or {}).items():
        theory_lines.append(
            f"- `{key}`：{value.get('before')} → {value.get('after')}（Δ {value.get('delta')}）"
        )
    theory_lines.extend(["", "## 十维画像", ""])
    for key, value in (profile.get("dimensions") or {}).items():
        theory_lines.append(
            f"- `{key}`：{value.get('before')} → {value.get('after')}（Δ {value.get('delta')}）；证据：{'；'.join(value.get('evidence') or ['无新增证据'])}"
        )
    theory_lines.extend(
        [
            "",
            f"- 心智历史：{profile.get('mental_history_before')} → {profile.get('mental_history_after')} 条。",
            f"- 薄弱点：`{profile.get('weak_points_before')}` → `{profile.get('weak_points_after')}`。",
            "- 理论判定：错误会暂时抬高理解负担和受挫感，后续纠正、代码通过、实验提交与费曼改进应形成恢复；没有新证据的维度不应被强行统一上调。",
        ]
    )
    (EVIDENCE / f"{TASK_ID}-THEORY-REPORT.md").write_text("\n".join(theory_lines) + "\n", encoding="utf-8")

    issues = report.get("issues") or []
    issue_lines = [f"# {TASK_ID} 问题报告", ""]
    if issues:
        for index, issue in enumerate(issues, 1):
            issue_lines.append(
                f"{index}. **{issue.get('scope', '待分类')}** - {issue.get('summary')}（状态：{issue.get('status')}）"
            )
    else:
        issue_lines.append("本次连续旅程未发现未解决问题。")
    issue_lines.extend(
        [
            "",
            "已修复的通用问题：资源包打开资源时曾丢失 `path_id/task_id`，导致真实代码完成事件无法稳定回写今日路径；现已在资源包统一保留冻结上下文，并由路径完成和智能组卷解锁截图验证。",
        ]
    )
    (EVIDENCE / f"{TASK_ID}-ISSUE-REPORT.md").write_text("\n".join(issue_lines) + "\n", encoding="utf-8")


def normalize_screenshots(report: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = report.get("screenshot_meta") or {}
    normalized = []
    for item in report.get("screenshots") or []:
        if isinstance(item, dict):
            normalized.append(item)
            continue
        details = metadata.get(item) or {}
        normalized.append(
            {
                "name": item,
                "path": details.get("path") or str(BROWSER / item),
                "url": details.get("url") or "unknown",
                "viewport": details.get("viewport") or [1440, 900],
                "metrics": details.get("metrics") or {},
            }
        )
    return normalized


def main() -> int:
    clear_runtime()
    configure_reused_modules()
    before_formal = formal_snapshot()
    env = runtime_env()
    report: dict[str, Any] = {
        "schema_version": "demo-learning-closed-loop-profile.v1",
        "task_id": TASK_ID,
        "result": "failed",
        "course_id": COURSE_ID,
        "database": str(DB_PATH),
        "service": BASE_URL,
        "viewports": [[1440, 900], [1366, 768]],
        "model_mode": "deterministic_local",
        "external_model_called": False,
        "screenshots": [],
        "checks": {},
        "issues": [],
        "http_errors": [],
        "failed_requests": [],
        "console_errors": [],
        "page_errors": [],
        "external_requests": [],
        "authorization_boundaries": [],
        "formal_before": before_formal,
    }
    process: subprocess.Popen | None = None
    username = f"closed_loop_{int(time.time())}"
    report["username"] = username
    try:
        seed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from app.database import init_db,SessionLocal; "
                "from app.competition_demo_seed import seed_competition_demo; "
                "init_db(); db=SessionLocal(); print(seed_competition_demo(db)); db.close()",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        (EVIDENCE / "seed.log").write_text(seed.stdout + "\n" + seed.stderr, encoding="utf-8")
        if seed.returncode:
            raise RuntimeError(f"demo seed failed: {seed.stdout}\n{seed.stderr}")

        process = start_service(env)
        spec = importlib.util.spec_from_file_location(
            "closed_loop_legacy_f4", SCRIPTS / "e2e_f4_phase_journey.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to load the proven F4 journey helper")
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        legacy.OUTPUT_DIR = BROWSER
        legacy.DB_PATH = DB_PATH
        legacy.PORT = PORT
        legacy.BASE_URL = BASE_URL
        legacy.COURSE_ID = COURSE_ID
        legacy.PASSWORD = PASSWORD
        legacy.structured_handout_fixture = master.master_handout_fixture
        os.environ.update(env)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            page = context.new_page()
            page.set_default_timeout(35_000)
            browser_diagnostics(page, report)
            token, _ = master.run_master_diagnostic_journey(page, report, legacy, username)
            report["token"] = token
            path_id = parse_qs(urlparse(page.url).query).get("path_id", [""])[0]
            if not path_id:
                raise AssertionError(f"diagnostic journey did not confirm a learning path: {page.url}")
            capture_profile_baseline(page, report, username)
            before_profile = profile_state(username)
            journey = resource_generation_journey(page, report, token, path_id)
            report["checks"]["resource_journey"] = {
                "path_id": journey["path_id"],
                "task_id": journey["task_id"],
                "selected_text": journey["selected_text"],
                "job_id": journey["job"]["job_id"],
                "resource_types": [item["type"] for item in journey["job"]["items"]],
            }
            inspect_passive_resources(page, report, journey)
            complete_quiz(page, report, journey)
            run_code_learning(page, report, journey)
            run_interactive_learning(page, report, journey)
            run_feynman_learning(page, report, journey)
            verify_path_complete(page, report, journey)
            complete_formal_exam(page, report)
            complete_chat(page, report)
            after_profile = profile_state(username)
            report["profile_before"] = before_profile
            report["profile_after"] = after_profile
            report["profile_comparison"] = compare_profile(before_profile, after_profile)
            capture_final_profile(page, report, username)
            context.close()
            browser.close()

        report.pop("token", None)
        report["database_audit"] = database_audit(username)
        after_formal = formal_snapshot()
        report["formal_after"] = after_formal
        report["formal_protection"] = {
            "before": before_formal,
            "after": after_formal,
            "unchanged": before_formal == after_formal,
        }
        audit = report["database_audit"]
        profile = report["profile_comparison"]
        required_events = {
            "quiz_answered",
            "code_tests_passed",
            "interactive_model_observation_submitted",
            "feynman_submitted",
            "formal_exam_submitted",
        }
        if audit["integrity"] != "ok" or audit["foreign_key_violations"]:
            raise AssertionError(f"isolated database integrity failed: {audit}")
        if not required_events.issubset(set(audit["event_types"])):
            raise AssertionError(f"trusted learning event coverage is incomplete: {audit['event_types']}")
        if profile["mental_history_after"] <= profile["mental_history_before"]:
            raise AssertionError(f"mental-state history did not update: {profile}")
        if not any(item["evidence"] for item in profile["dimensions"].values()):
            raise AssertionError(f"ten-dimensional profile has no visible evidence: {profile}")
        if not report["formal_protection"]["unchanged"]:
            raise AssertionError("formal database or official recovery state changed")
        if report["http_errors"] or report["failed_requests"] or report["page_errors"] or report["console_errors"]:
            raise AssertionError("unexpected browser errors were recorded")
        if report["external_requests"]:
            raise AssertionError(f"unexpected external requests: {report['external_requests']}")
        report["result"] = "passed"
        return 0
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        report["issues"].append(
            {
                "scope": "本次旅程或系统通用问题，待按失败点复核",
                "summary": report["error"],
                "status": "unresolved",
            }
        )
        return 1
    finally:
        report.pop("token", None)
        stop_service(process)
        report["process_cleanup"] = {
            "service_stopped": process is None or process.poll() is not None,
            "port_released": not port_open(),
        }
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        report["screenshots"] = normalize_screenshots(report)
        (EVIDENCE / "browser_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        write_reports(report)
        print(
            json.dumps(
                {
                    "result": report.get("result"),
                    "screenshots": len(report.get("screenshots") or []),
                    "error": report.get("error"),
                },
                ensure_ascii=True,
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
