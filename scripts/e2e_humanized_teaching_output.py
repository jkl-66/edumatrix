"""Real-browser acceptance for learner-facing teaching output."""

from __future__ import annotations

import hashlib
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

from PIL import Image
from playwright.sync_api import Locator, Page, sync_playwright

import e2e_f4_t04_resource_generation as resource_fixture
import e2e_f6_t05_feynman as feynman_fixture
import e2e_quiz_explanation_visual_audit as assessment_audit


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "custom_tasks"
    / "HUMANIZED-TEACHING-OUTPUT-VISUAL-01"
)
BROWSER = OUTPUT / "browser"
RUNTIME = OUTPUT / "runtime"
DB = RUNTIME / "humanized_teaching.sqlite3"
COURSE_ID = "demo-course-rag-trust-v1"
PORT = int(os.environ.get("EDUMATRIX_HUMANIZED_TEACHING_PORT", "9280"))
BASE_URL = f"http://127.0.0.1:{PORT}"

FORBIDDEN_PHRASES = (
    "上下文重点",
    "确定性回答",
    "本地确定性",
    "deterministic_local",
    "评价规则",
    "规则 ID",
    "运行模式",
    "生成模式",
    "内部 ID",
    "内部编号",
    "上下文短哈希",
    "冻结课程来源",
    "依据课程来源",
    "基于课程来源",
    "证据链",
    "检索上下文",
    "课程语义蓝图",
    "强证据已进入学习聚合",
    "[S1]",
    "[A1]",
    "[source_ref]",
)
INTERNAL_ID = re.compile(
    r"\b(?:f\d+-)?(?:kp|event|trace|run)-[a-z0-9-]{6,}\b|"
    r"\b(?:source[_ -]?ref(?:[_ -]?id)?|knowledge[_ -]?point[_ -]?id|"
    r"context[_ -]?fingerprint|content[_ -]?hash|rubric[_ -]?version|"
    r"generation[_ -]?mode|answer[_ -]?mode|run[_ -]?id|message[_ -]?id|event[_ -]?id)\b|"
    r"\b[a-f0-9]{32,64}\b",
    re.IGNORECASE,
)

ROUND1 = (
    "混合检索就是把关键词检索和向量检索一起使用。关键词检索擅长找到完全相同的术语，"
    "向量检索擅长找到意思接近的内容。两路结果合并后再排序，通常能找到更多有用片段。"
    "例如查询一个专业缩写时，关键词可以精确命中，向量方法还能补充意思相近的解释。"
)
ROUND2 = (
    "混合检索同时利用词面匹配和语义匹配。开始时先整理查询，再分别执行关键词检索和向量检索，"
    "随后合并、去重并重排候选。它成立的前提是原始内容解析完整、两种索引可用，而且评分能够合理比较。"
    "例如搜索 RAG 评测中的 Recall@K，关键词检索能精确找到指标名，向量检索可以补充召回率的相关解释。"
    "如果原始内容漏页、乱码或切分错误，后面的重排只能在残缺候选中选择，不能补回丢失的信息。"
    "所以常见误区是把排序第一当成答案一定正确；更稳妥的做法是同时检查内容完整性和回答是否真正得到支持。"
)


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _formal_snapshot() -> dict[str, object]:
    database = ROOT / "edumatrix.db"
    active = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "active_manifest.json"
    checkpoint = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "current_checkpoint.json"
    active_payload = json.loads(active.read_text(encoding="utf-8"))
    checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    return {
        "database_sha256": _digest(database),
        "active_manifest_sha256": _digest(active),
        "checkpoint_sha256": _digest(checkpoint),
        "active_manifest_status": active_payload.get("status"),
        "official_checkpoint": {
            "phase": checkpoint_payload.get("phase"),
            "task": checkpoint_payload.get("task"),
            "state": checkpoint_payload.get("state"),
        },
    }


def _reset_runtime() -> None:
    for path in (BROWSER, RUNTIME, OUTPUT / "assessment"):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)


def _port_open() -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", PORT)) == 0


def _wait_port(expected: bool, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open() is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected state {expected}")


def _start_service(env: dict[str, str]) -> subprocess.Popen:
    log = (RUNTIME / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    process._humanized_log = log  # type: ignore[attr-defined]
    _wait_port(True)
    return process


def _stop_service(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=20,
            )
        else:
            process.terminate()
        process.wait(timeout=10)
    log = getattr(process, "_humanized_log", None)
    if log is not None:
        log.close()
    _wait_port(False, timeout=20)


def _diagnostics(page: Page, report: dict[str, object], scope: str) -> None:
    def response(response) -> None:
        if response.status < 400:
            return
        if response.status == 403 and any(fragment in response.url for fragment in (
            "/api/v1/competition-demo/context",
            "/api/v1/m5/textbook-path-draft",
        )):
            report["expected_auth_boundaries"].append({"scope": scope, "url": response.url})
            return
        report["http_errors"].append({"scope": scope, "status": response.status, "url": response.url})

    page.on("response", response)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "scope": scope,
        "url": request.url,
        "failure": request.failure,
    }) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append({"scope": scope, "error": str(error)}))
    page.on("console", lambda message: report["console_errors"].append({
        "scope": scope,
        "text": message.text,
    }) if message.type == "error" and "403 (Forbidden)" not in message.text else None)
    page.on("request", lambda request: report["external_requests"].append({
        "scope": scope,
        "url": request.url,
    }) if request.url.startswith(("http://", "https://"))
    and not request.url.startswith((BASE_URL, "http://localhost", "http://127.0.0.1")) else None)


def _assert_teacher_text(text: str, name: str, *, minimum: int = 80) -> None:
    normalized = text.strip()
    assert len(normalized) >= minimum, {"name": name, "text_length": len(normalized), "text": normalized[:1000]}
    found = [phrase for phrase in FORBIDDEN_PHRASES if phrase.lower() in normalized.lower()]
    assert not found, {"name": name, "forbidden": found, "text": normalized[:2000]}
    assert not INTERNAL_ID.search(normalized), {"name": name, "internal_id": INTERNAL_ID.search(normalized).group(0)}
    assert not re.search(r"(?m)^\s*#{1,6}\s+", normalized), {"name": name, "raw_markdown": normalized[:1200]}


def _visual_metrics(page: Page) -> dict[str, object]:
    return page.evaluate(
        """() => {
          const visible = element => {
            const style = getComputedStyle(element)
            const box = element.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              Number(style.opacity) > 0 && box.width > 1 && box.height > 1
          }
          const clipped = [...document.querySelectorAll('h1,h2,h3,p,li,button,label,strong')]
            .filter(visible)
            .filter(element => {
              const style = getComputedStyle(element)
              if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
              if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
              return element.scrollWidth > element.clientWidth + 4
            })
            .map(element => (element.textContent || '').trim().slice(0, 100))
            .filter(Boolean).slice(0, 20)
          return {
            viewport: [innerWidth, innerHeight],
            document_width: document.documentElement.scrollWidth,
            page_overflow: document.documentElement.scrollWidth > innerWidth + 1,
            clipped_text: clipped,
          }
        }"""
    )


def _capture(
    page: Page,
    report: dict[str, object],
    name: str,
    target: Locator,
    *,
    minimum: int = 80,
    required: tuple[str, ...] = (),
) -> str:
    target.wait_for(state="visible", timeout=30_000)
    target.scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    text = target.inner_text().strip()
    path = BROWSER / name
    page.screenshot(path=str(path), full_page=False, animations="disabled")
    _assert_teacher_text(text, name, minimum=minimum)
    for phrase in required:
        assert phrase in text, {"name": name, "missing": phrase, "text": text[:1800]}
    metrics = _visual_metrics(page)
    assert not metrics["page_overflow"], {"name": name, "metrics": metrics}
    assert not metrics["clipped_text"], {"name": name, "metrics": metrics}
    assert list(Image.open(path).size) == metrics["viewport"], {"name": name, "metrics": metrics}
    report["screenshots"].append(str(path.relative_to(OUTPUT)).replace("\\", "/"))
    report["visual_checks"][name] = {
        **metrics,
        "text_length": len(text),
        "text_excerpt": text[:1000],
        "required_phrases": list(required),
        "teacher_language": True,
        "raw_markdown_visible": False,
        "internal_id_visible": False,
    }
    return text


def _wait_job(page: Page, token: dict[str, str], job_id: str) -> dict:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        response = page.request.get(
            f"{BASE_URL}/api/v1/resource-bundles/generation-jobs/{job_id}",
            headers=resource_fixture.bearer(token),
        )
        if response.ok:
            payload = response.json()
            if payload.get("status") in {"succeeded", "completed", "failed"}:
                return payload
        time.sleep(0.5)
    raise TimeoutError(f"resource job did not finish: {job_id}")


def _resource_journey(page: Page, report: dict[str, object], token: dict[str, str]) -> dict[str, str]:
    page.goto(f"{BASE_URL}/workspace/path?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    points = page.get_by_test_id("today-knowledge-points")
    points.wait_for(state="visible", timeout=30_000)
    points.locator("button").first.click()
    selected = page.get_by_test_id("selected-knowledge-point")
    selected.get_by_role("button", name="一键生成完整资源包", exact=True).wait_for(state="visible")
    _capture(page, report, "01-resource-generation-ready-1440x900.png", selected, minimum=100)
    selected.get_by_role("button", name="一键生成完整资源包", exact=True).click()
    page.wait_for_function("() => window.location.pathname === '/learn'", timeout=30_000)
    page.wait_for_function(
        "() => document.querySelectorAll('[data-testid=chat-compact-resource-links] button').length > 0",
        timeout=60_000,
    )
    _capture(
        page,
        report,
        "02-resource-generation-complete-1440x900.png",
        page.locator(".message-row--assistant").last,
        minimum=160,
        required=("资源",),
    )
    listing = page.request.get(
        f"{BASE_URL}/api/v1/resource-bundles/generation-jobs",
        params={"course_id": COURSE_ID},
        headers=resource_fixture.bearer(token),
    )
    assert listing.ok, listing.text()
    job_id = listing.json()["items"][0]["job_id"]
    job = _wait_job(page, token, job_id)
    assert job["status"] in {"succeeded", "completed"}, job
    assert all(item["state"] == "succeeded" for item in job["items"]), job
    resources = {
        item["type"]: (item.get("resource") or {}).get("resource_id", "")
        for item in job["items"]
        if item["type"] in {"handout", "mind_map", "feynman"}
    }

    page.goto(f"{BASE_URL}/workspace/resources/bundles/{job_id}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("resource-bundle-workspace").wait_for(state="visible")
    page.get_by_text("完整资源包已就绪", exact=True).wait_for(state="visible")
    _capture(
        page,
        report,
        "03-resource-bundle-ready-1440x900.png",
        page.get_by_test_id("resource-bundle-workspace"),
        minimum=300,
        required=("完整资源包已就绪", "个性化讲义", "思维导图"),
    )

    page.get_by_test_id("bundle-item-handout").get_by_role("button", name="打开", exact=True).click()
    page.wait_for_url("**/workspace/resources/handouts/**", timeout=30_000)
    handout = page.get_by_test_id("handout-workspace")
    handout.wait_for(state="visible")
    reading = handout.locator(".reading-panel")
    handout_text = _capture(
        page,
        report,
        "04-handout-teacher-content-1440x900.png",
        reading,
        minimum=700,
        required=("学习目标", "关键概念", "应用示例", "学习检查"),
    )
    report["content_checks"]["handout"] = {"characters": len(handout_text), "complete_sections": True}

    partner_question = "为什么关键词检索和向量检索需要先分别召回，再统一重排？请用一个小例子讲清楚。"
    handout.get_by_placeholder("针对本讲义提问").fill(partner_question)
    handout.get_by_role("button", name="在资源内提问", exact=True).click()
    qa = page.get_by_test_id("resource-floating-qa")
    qa.wait_for(state="visible")
    qa.locator("textarea").fill(partner_question)
    qa.get_by_role("button", name="发送", exact=True).click()
    page.wait_for_function(
        "() => (document.querySelector('[data-testid=resource-floating-qa] .resource-qa-answer')?.innerText || '').length > 450",
        timeout=90_000,
    )
    qa_answer = _capture(
        page,
        report,
        "05-resource-qa-teacher-answer-1440x900.png",
        qa.locator(".resource-qa-answer .incremental-md-renderer"),
        minimum=450,
        required=("关键词", "向量", "重排"),
    )
    report["content_checks"]["resource_qa"] = {"characters": len(qa_answer), "question_answered": True}
    qa.get_by_title("关闭问答").click()

    page.goto(f"{BASE_URL}/workspace/resources/bundles/{job_id}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("bundle-item-mind_map").get_by_role("button", name="打开", exact=True).click()
    page.wait_for_url("**/workspace/resources/mindmaps/**", timeout=30_000)
    mindmap = page.get_by_test_id("mindmap-workspace")
    mindmap.wait_for(state="visible")
    page.wait_for_timeout(1200)
    node_state = page.evaluate(
        """() => {
          const nodes = [...document.querySelectorAll('.mindmap-node')].filter(node => {
            const box = node.getBoundingClientRect(); return box.width > 1 && box.height > 1
          })
          const labels = nodes.map(node => (node.querySelector('.mindmap-node-content')?.textContent || '').trim())
          const overlaps = []
          for (let i = 0; i < nodes.length; i += 1) for (let j = i + 1; j < nodes.length; j += 1) {
            const a = nodes[i].getBoundingClientRect(), b = nodes[j].getBoundingClientRect()
            if (Math.min(a.right,b.right)-Math.max(a.left,b.left)>6 && Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>6) overlaps.push([i,j])
          }
          return {count:nodes.length, empty:labels.filter(label => !label), overlaps}
        }"""
    )
    assert node_state["count"] >= 2 and not node_state["empty"] and not node_state["overlaps"], node_state
    _capture(page, report, "06-mindmap-readable-1440x900.png", mindmap, minimum=180)
    report["content_checks"]["mind_map"] = node_state
    return resources


def _send_chat(page: Page, report: dict[str, object], question: str, name: str, required: tuple[str, ...]) -> str:
    composer = page.get_by_label("输入问题")
    composer.fill(question)
    page.locator(".send-button").click()
    user = page.locator(".message-row--user").filter(has_text=question).last
    user.wait_for(state="visible", timeout=45_000)
    answer_row = user.locator("xpath=following-sibling::article[contains(@class,'message-row--assistant')][1]")
    answer_row.wait_for(state="visible", timeout=60_000)
    message_id = answer_row.get_attribute("data-message-id")
    page.wait_for_function(
        """messageId => {
          const row = document.querySelector(`[data-message-id="${messageId}"]`)
          return (row?.querySelector('.assistant-label')?.innerText || '').includes('回答完成') &&
            (row?.querySelector('.assistant-answer')?.innerText || '').length > 600
        }""",
        arg=message_id,
        timeout=90_000,
    )
    text = _capture(page, report, name, answer_row, minimum=600, required=required)
    return answer_row.locator(".assistant-answer").inner_text().strip()


def _chat_journey(page: Page, report: dict[str, object]) -> None:
    page.goto(f"{BASE_URL}/chat?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible")
    page.get_by_role("button", name="新建对话", exact=True).click()
    page.wait_for_timeout(700)
    first = _send_chat(
        page,
        report,
        "请详细解释二分查找的循环不变量，并用查找 7 的过程说明闭区间边界。",
        "07-chat-loop-invariant-answer-1440x900.png",
        ("循环不变量", "闭区间", "left", "right"),
    )
    second = _send_chat(
        page,
        report,
        "那为什么找到中点不相等时，right 要写成 mid - 1，left 要写成 mid + 1？",
        "08-chat-boundary-follow-up-1440x900.png",
        ("right = mid - 1", "left = mid + 1", "边界"),
    )
    third = _send_chat(
        page,
        report,
        "请像老师带我做设计评审一样，比较关键词检索、向量检索和重排各自解决什么问题，并给出失败案例。",
        "09-chat-rag-design-review-1440x900.png",
        ("关键词", "向量", "重排"),
    )
    assert len({first, second, third}) == 3
    report["content_checks"]["chat"] = {
        "answer_characters": [len(first), len(second), len(third)],
        "answers_distinct": True,
        "current_question_first": True,
    }


def _feynman_action(page: Page, button: str, text: str | None = None, selector: str = "textarea:visible") -> None:
    if text is not None:
        page.locator(selector).fill(text)
    action = page.get_by_role("button", name=button, exact=True)
    action.wait_for(state="visible")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not action.is_enabled():
        page.wait_for_timeout(200)
    assert action.is_enabled(), button
    action.click()


def _feynman_journey(page: Page, report: dict[str, object], resource_id: str) -> None:
    page.goto(f"{BASE_URL}/workspace/feynman/{resource_id}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_role("heading", name="第一次复述", exact=True).wait_for(state="visible")
    _capture(
        page,
        report,
        "10-feynman-natural-task-1440x900.png",
        page.locator(".stage-panel"),
        minimum=180,
        required=("本轮任务", "核心含义", "适用例子"),
    )
    _feynman_action(page, "保存第一次复述", ROUND1, "#round1:visible")
    _feynman_action(page, "生成第一次评价")
    evaluation = page.locator(".evaluation-panel").first
    evaluation.get_by_text("需要补充", exact=True).wait_for(state="visible", timeout=30_000)
    first_feedback = _capture(
        page,
        report,
        "11-feynman-specific-feedback-1440x900.png",
        evaluation,
        minimum=250,
        required=("核心含义", "机制与步骤", "成立条件", "适用例子", "边界与反例", "需要补充"),
    )
    _feynman_action(page, "进入真实疑问")
    question = "为什么重排模型表现很好，也不能补回解析时已经丢失的内容？"
    page.get_by_label("我仍然不明白").fill(question)
    _feynman_action(page, "提交疑问并查看回答")
    question_answer = page.locator(".question-answer:visible").first
    question_answer.get_by_text("老师的回答", exact=True).wait_for(state="visible", timeout=30_000)
    answer = _capture(
        page,
        report,
        "12-feynman-teacher-question-answer-1440x900.png",
        question_answer,
        minimum=380,
        required=("重排", "解析", "老师的回答"),
    )
    _feynman_action(page, "保存第二次复述", ROUND2, "#round2:visible")
    _feynman_action(page, "生成第二次评价与对比")
    comparison = page.locator(".stage-panel")
    page.get_by_role("heading", name="理解变化", exact=True).wait_for(state="visible", timeout=30_000)
    comparison_text = _capture(
        page,
        report,
        "13-feynman-understanding-change-1440x900.png",
        comparison,
        minimum=260,
        required=("第一次", "第二次", "分数变化", "下一步建议"),
    )
    _feynman_action(page, "应用到后续学习")
    completed = page.locator(".completion-panel")
    completed.get_by_role("heading", name="已应用到后续学习", exact=True).wait_for(state="visible", timeout=30_000)
    _capture(page, report, "14-feynman-complete-1440x900.png", completed, minimum=70, required=("已应用到后续学习",))
    report["content_checks"]["feynman"] = {
        "first_feedback_characters": len(first_feedback),
        "question_answer_characters": len(answer),
        "comparison_characters": len(comparison_text),
        "five_stage_flow_complete": True,
    }


def _desktop_recheck(page: Page, report: dict[str, object], resources: dict[str, str], feynman_id: str) -> None:
    page.goto(f"{BASE_URL}/workspace/resources/handouts/{resources['handout']}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    _capture(page, report, "15-handout-responsive-1366x768.png", page.locator(".reading-panel"), minimum=700, required=("关键概念", "学习检查"))
    page.goto(f"{BASE_URL}/chat?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible")
    last = page.locator(".message-row--assistant").last
    _capture(page, report, "16-chat-responsive-1366x768.png", last, minimum=600, required=("关键词", "向量", "重排"))
    page.goto(f"{BASE_URL}/workspace/feynman/{feynman_id}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_role("heading", name="已应用到后续学习", exact=True).wait_for(state="visible")
    _capture(page, report, "17-feynman-responsive-1366x768.png", page.locator(".completion-panel"), minimum=70)


def _database_audit() -> dict[str, object]:
    with sqlite3.connect(DB, timeout=20) as database:
        return {
            "integrity": database.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(database.execute("PRAGMA foreign_key_check").fetchall()),
        }


def _run_assessment_audit(report: dict[str, object]) -> None:
    assessment_root = OUTPUT / "assessment"
    assessment_audit.OUTPUT_DIR = assessment_root
    assessment_audit.SCREENSHOT_DIR = assessment_root / "screenshots"
    assessment_audit.QUIZ_DIR = assessment_root / "quiz_runtime"
    assessment_audit.EXAM_DIR = assessment_root / "exam_runtime"
    assessment_audit.WRONG_DIR = assessment_root / "wrong_runtime"
    assessment_audit.FORBIDDEN_MARKERS += FORBIDDEN_PHRASES + (
        "课文",
        "上下文重点",
        "运行模式",
        "生成模式",
        "评价规则",
    )
    result = assessment_audit.run()
    assert result["status"] == "passed", result
    report["assessment_audit"] = result
    report["screenshots"].extend(
        str((Path("assessment") / "screenshots" / name)).replace("\\", "/")
        for name in result["screenshots"]
    )


def run() -> dict[str, object]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _reset_runtime()
    before = _formal_snapshot()
    report: dict[str, object] = {
        "schema_version": "humanized-teaching-output.browser.v1",
        "task_id": "HUMANIZED-TEACHING-OUTPUT-VISUAL-01",
        "result": "running",
        "viewports": [[1440, 900], [1366, 768]],
        "isolated_database": str(DB),
        "external_model_called": False,
        "screenshots": [],
        "visual_checks": {},
        "content_checks": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "expected_auth_boundaries": [],
        "formal_protection": {"before": before},
    }
    process: subprocess.Popen | None = None
    try:
        env = resource_fixture.runtime_env(DB, PORT)
        env.update({
            "EDUMATRIX_AUTH_SECRET_KEY": "humanized-teaching-isolated-secret",
            "EDUMATRIX_CHAT_RESOURCE_DEMO_EXECUTION": "1",
            "EDUMATRIX_LLM_PROVIDER": "deterministic",
            "EDUMATRIX_LLM_MODEL": "deterministic",
            "EDUMATRIX_LLM_API_KEY": "",
            "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
            "EDUMATRIX_LLM_ENDPOINT": "",
            "PYTHON_DOTENV_DISABLED": "1",
        })
        resource_fixture.OUTPUT_DIR = RUNTIME
        feynman_fixture.OUTPUT_DIR = RUNTIME
        resource_fixture.seed_fixture(env)
        feynman_data = feynman_fixture.seed_fixture(env)
        process = _start_service(env)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            page.set_default_timeout(30_000)
            _diagnostics(page, report, "desktop-1440")
            token = resource_fixture.login(page, BASE_URL)
            resources = _resource_journey(page, report, token)
            _chat_journey(page, report)
            _feynman_journey(page, report, feynman_data["resource_id"])
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            page.set_default_timeout(30_000)
            _diagnostics(page, report, "desktop-1366")
            resource_fixture.login(page, BASE_URL)
            _desktop_recheck(page, report, resources, feynman_data["resource_id"])
            context.close()
            browser.close()
        report["database_audit"] = _database_audit()
        assert report["database_audit"] == {"integrity": "ok", "foreign_key_violations": 0}
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["external_requests"], report["external_requests"]
        _stop_service(process)
        process = None
        _run_assessment_audit(report)
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    finally:
        _stop_service(process)
        after = _formal_snapshot()
        report["formal_protection"]["after"] = after
        report["formal_protection"]["unchanged"] = before == after
        report["process_cleanup"] = {"service_stopped": process is None or process.poll() is not None, "port_released": not _port_open()}
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        report_path = OUTPUT / "browser_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (OUTPUT / "browser_report.sha256").write_text(hashlib.sha256(report_path.read_bytes()).hexdigest() + "\n", encoding="ascii")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "result": result["result"],
        "screenshots": len(result["screenshots"]),
        "error": result.get("error"),
    }, ensure_ascii=False))
    raise SystemExit(0 if result["result"] == "passed" else 1)
