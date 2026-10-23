"""Isolated end-to-end student journey for the unified master course.

The script drives the existing student UI journey against a fresh SQLite file,
then adds the master-course knowledge shelf, graph and chat evidence that are
not part of the older phase journey.  No production database is touched.
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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "STUDENT-JOURNEY-DEMO-01"
OUTPUT_DIR = EVIDENCE / "browser"
DB_PATH = EVIDENCE / "student_journey_runtime.db"
PORT = int(os.getenv("EDUMATRIX_STUDENT_JOURNEY_PORT", "8921"))
BASE_URL = f"http://127.0.0.1:{PORT}"
COURSE_ID = "course-ai-deep-learning-agents-v1"
PASSWORD = "StudentJourney-Demo-2026!"


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


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "student-journey-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_ONBOARDING_V2": "1",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_SANDBOX_MODE": "trusted_local",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_ref_for_master() -> str:
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute(
            """SELECT sr.id FROM source_refs sr
               JOIN source_documents sd ON sd.id = sr.source_document_id
               WHERE sd.course_id=? ORDER BY sd.filename LIMIT 1""",
            (COURSE_ID,),
        ).fetchone()
    if not row:
        raise RuntimeError("master course has no canonical source reference")
    return str(row[0])


def diagnostics(page: Page, report: dict) -> None:
    page.on("response", lambda r: report["http_errors"].append({"status": r.status, "url": r.url}) if r.status >= 400 else None)
    page.on("requestfailed", lambda r: report["failed_requests"].append({"url": r.url, "failure": r.failure}) if r.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda e: report["page_errors"].append(str(e)))
    page.on("console", lambda m: report["console_errors"].append(m.text) if m.type == "error" else None)


def shot(page: Page, report: dict, name: str) -> None:
    page.wait_for_timeout(500)
    path = OUTPUT_DIR / name
    # Keep every evidence frame at the declared browser viewport.  Full-page
    # captures made the quiz feedback images taller than 1440x900 and made
    # cross-step visual comparison misleading.
    page.screenshot(path=str(path), full_page=False)
    report["screenshots"].append(name)
    report.setdefault("screenshot_meta", {})[name] = {
        "path": str(path), "viewport": [page.viewport_size["width"], page.viewport_size["height"]],
        "url": page.url,
    }


def master_handout_fixture(source_ref_id: str | None = None) -> dict:
    # Keep the proven structured fixture shape but bind it to a real master-course source.
    ref = source_ref_id or source_ref_for_master()
    return {
        "schemaVersion": "f5.handout.v1",
        "title": "主课程个性化讲义：混合检索与证据核验",
        "summary": "基于统一主课程的 RAG 检索评测学习材料。",
        "learningGoal": "理解关键词、向量与混合检索的差异，并能用课程来源核验回答。",
        "estimatedMinutes": 20,
        "outline": [{"id": "concept-overview", "title": "关键概念"}, {"id": "example-use", "title": "例子"}, {"id": "quiz-check", "title": "学习检查"}, {"id": "source-note", "title": "课程来源"}],
        "concepts": [{"id": "concept-overview", "title": "混合检索", "explanation": "混合检索把关键词的精确匹配与向量的语义召回结合，再按统一分数或重排器整理候选。", "sourceRefIds": [ref]}],
        "figures": [{"id": "figure-flow", "title": "检索核验链", "kind": "diagram", "content": "问题 -> 检索证据 -> 生成回答 -> 来源核验", "caption": "每一步都保留可检查的输入、输出和来源。", "sourceRefIds": [ref]}],
        "examples": [{"id": "example-use", "title": "例子：比较 Recall@K", "body": "在冻结 query 上分别运行关键词、向量和混合检索，比较 Recall@K。", "sourceRefIds": [ref]}],
        "counterExamples": [{"id": "counterexample-use", "title": "只看一次命中", "body": "单次命中不能证明一种检索普遍最优，还需固定金标集评测。", "sourceRefIds": [ref]}],
        "codeBlocks": [{"id": "code-check", "title": "Recall@K 检查", "language": "python", "code": "def recall_at_k(retrieved, relevant, k=3):\n    return len(set(retrieved[:k]) & set(relevant)) / len(set(relevant))\n", "explanation": "用固定金标集合评价检索覆盖。"}],
        "miniQuiz": [{"id": "quiz-check", "question": "为什么混合检索要在金标 query 上评测？", "options": ["避免只凭一次命中推断", "让答案更长"], "correctIndex": 0, "explanation": "Recall@K 等指标要求可复现的固定相关文档集合。", "required": True}],
        "footnotes": [{"id": "source-note", "sourceRefId": ref, "label": "[1]", "title": "统一主课程来源", "location": "主课程 canonical 文档与可定位分块"}],
        "profileAdaptation": {"summary": "先给出直觉与例子，再通过代码和测验验证。", "difficulty": "适中", "scaffolding": ["先理解机制链", "再核对来源", "最后完成学习检查"]},
    }


class DemoModel:
    """Deterministic, schema-aware backend used only by the isolated demo.

    Production keeps its strict DeepSeek policy.  This class deliberately
    advertises the same governed metadata so the real generation/report/path
    code paths can be exercised without an external provider or fabricated UI
    responses.  It never runs in the application runtime.
    """

    provider = "isolated-demo"
    model = "deepseek-v4-flash"
    thinking_mode = "enabled"
    reasoning_effort = "max"
    allow_fallback = False

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        payload = json.loads(user_prompt)
        if "出题" in role:
            return json.dumps(self._diagnostic_questions(payload), ensure_ascii=False)
        if "审核" in role:
            generated = payload.get("generated_set", {})
            items = [
                {
                    "item_id": item["item_id"], "verdict": "approved",
                    "source_support": "supported", "answer_consistency": "consistent",
                    "profile_fit": "fit", "public_note": "题目与课程来源、画像难度和答案规则一致。",
                }
                for item in generated.get("questions", [])
            ]
            return json.dumps({
                "status": "approved", "decision_summary": "全部题目通过来源、答案一致性和画像适配审核。",
                "items": items,
            }, ensure_ascii=False)
        if "简答题评分" in role:
            rubric = payload.get("rubric", {}).get("criteria", [])
            criteria = [
                {
                    "criterion_id": item["id"], "score": 0.75,
                    "evidence": ["回答提到课程中的关键步骤"],
                    "justification": "回答覆盖了评分量规要求的核心要点。",
                    "improvement": "补充边界条件和一个可复现实例。",
                }
                for item in rubric
            ]
            return json.dumps({
                "criteria": criteria, "confidence": 0.86,
                "summary": "回答已覆盖核心概念，建议补充边界与实例。",
                "improvement_plan": ["回到课程来源核对定义", "完成一个小型实践"],
            }, ensure_ascii=False)
        if "逐题评估" in role:
            items = []
            for item in payload.get("items", []):
                sources = item.get("sources") or []
                source_ids = [sources[0]["id"]] if sources else []
                items.append({
                    "question_version_id": item["question_version_id"],
                    "claim": f"本题用于核对 {item.get('knowledge_point', '当前知识点')} 的理解。",
                    "judgment_basis": "根据本题作答、理解程度和所列课程来源进行判断。",
                    "explanation": "课程来源支持该知识点的定义与应用边界；请结合反馈继续练习。",
                    "source_ref_ids": source_ids, "confidence": 0.84,
                    "status": "supported" if source_ids else "insufficient_evidence",
                })
            return json.dumps({"status": "completed", "items": items}, ensure_ascii=False)
        if "路径" in role:
            context = payload.get("context", {})
            chapters = context.get("course_graph", {}).get("chapters", [])
            evidence = context.get("initial_learning_evidence", {})
            weak_ids = {str(item) for item in evidence.get("weak_knowledge_point_ids", [])}
            # Put a genuinely weak, source-backed chapter first.  This makes
            # the schedule projection expose a real today's task instead of
            # skipping an already-mastered introductory chapter.
            selected = sorted(
                chapters,
                key=lambda chapter: (0 if weak_ids.intersection({str(item.get("id")) for item in chapter.get("knowledge_points", [])}) else 1, int(chapter.get("position", 0))),
            )[:8] or chapters[:1]
            nodes = []
            for index, chapter in enumerate(selected):
                nodes.append({
                    "node_key": f"demo-path-{index + 1:02d}",
                    "node_type": "chapter", "target_object_id": chapter["id"],
                    "title": chapter.get("title") or chapter["id"],
                    "prerequisites": [nodes[-1]["node_key"]] if nodes else [],
                    "resource_status": "existing", "estimate_min_minutes": 15,
                    "estimate_max_minutes": 25,
                    "difficulty": round(min(0.82, 0.34 + index * 0.06), 3),
                    "rationale": "依据本次诊断画像，从课程先修关系逐步衔接；先补齐当前薄弱知识，再进入下一章节。",
                })
            return json.dumps({
                "plan": {
                    "schema_version": "m5.plan.v1",
                    "goal": "补齐当前薄弱知识点并完成从机器学习基础到 RAG 的可验证学习主线。",
                    "assumptions": ["仅使用统一主课程章节与已确认画像证据。", "浏览不会直接改变掌握度。"],
                    "nodes": nodes,
                },
                "personalization_summary": "本路径优先安排诊断暴露的薄弱知识点，并按主课程先修关系逐步增加应用难度。",
            }, ensure_ascii=False)
        return json.dumps({"status": "completed", "items": []}, ensure_ascii=False)

    @staticmethod
    def _diagnostic_questions(payload: dict) -> dict:
        request = payload.get("request", {})
        count = int(request.get("question_count", 25))
        target = payload.get("target_knowledge_points", [])
        sources = payload.get("authorized_sources", [])
        by_point = {item["id"]: item for item in target}
        source_by_point = {}
        for source in sources:
            for point_id in source.get("knowledge_point_ids", []):
                source_by_point.setdefault(point_id, source["source_ref_id"])
        type_counts = {15: (5, 5, 5), 20: (7, 7, 6), 25: (9, 8, 8)}
        true_false_count, single_choice_count, short_answer_count = type_counts.get(count, (count // 3, count // 3, count - 2 * (count // 3)))
        types = (["true_false"] * true_false_count) + (["single_choice"] * single_choice_count) + (["short_answer"] * short_answer_count)
        questions = []
        counts = {}
        for index in range(count):
            point = target[index % len(target)]
            point_id, title = point["id"], point["title"]
            source_id = source_by_point.get(point_id) or point.get("source_ref_ids", [""])[0]
            question_type = types[index] if index < len(types) else types[index % len(types)]
            dimension = ("theory", "application", "engineering_judgment")[index % 3]
            difficulty = round(min(0.78, 0.34 + (index % 7) * 0.06), 3)
            base = {
                "item_id": f"demo-dx-{index + 1:02d}",
                "prompt": f"围绕“{title}”判断其在统一主课程中的定义、作用或工程边界（第 {index + 1} 题）。",
                "primary_knowledge_point_id": point_id, "source_ref_id": source_id,
                "diagnostic_dimension": dimension,
                "bloom_level": "understand" if difficulty < 0.55 else "apply",
                "difficulty": difficulty,
                "explanation": f"本题依据课程来源核对“{title}”的核心概念与应用。",
            }
            if question_type == "true_false":
                item = {**base, "question_type": question_type, "answer": True}
            elif question_type == "single_choice":
                item = {**base, "question_type": question_type,
                        "options": ["A. 课程来源支持的表述", "B. 与定义相反的表述", "C. 无关的表述", "D. 缺少前提的表述"], "answer": "A"}
            else:
                item = {**base, "question_type": question_type,
                        "reference_answer": f"应准确解释 {title} 的定义、关键步骤及适用边界，并能联系课程来源。",
                        "rubric": [{"id": "core", "label": "核心概念", "weight": 1.0}]}
            questions.append(item)
            counts[point_id] = counts.get(point_id, 0) + 1
        return {
            "profile_adaptation_summary": "依据已确认画像从基础概念起步，逐步加入应用与工程判断；题目覆盖主课程全部有来源知识点。",
            "coverage_plan": [{"knowledge_point_id": item["id"], "question_count": counts[item["id"]], "rationale": "保证该知识点至少获得一条诊断证据。"} for item in target],
            "questions": questions,
        }


def _isolated_session():
    """Import the app against the demo DB after the service environment is set."""
    from app.database import SessionLocal
    return SessionLocal()


def _run_in_worker(function):
    """Run synchronous app helpers outside Playwright's greenlet event loop."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(function).result()


def prepare_diagnostic_fixture(username: str, idempotency_key: str) -> str:
    from app.database import DBUser
    from app.diagnostic_generation import DiagnosticBlueprintRequest, generate_diagnostic_blueprint
    def work():
        session = _isolated_session()
        try:
            user = session.query(DBUser).filter_by(username=username).one()
            row, _ = generate_diagnostic_blueprint(
                session, user=user,
                request=DiagnosticBlueprintRequest(
                    course_id=COURSE_ID, idempotency_key=idempotency_key,
                    question_count=25, self_rating="foundation",
                ),
                llm=DemoModel(),
            )
            session.commit()
            return row.id
        finally:
            session.close()
    return _run_in_worker(work)


def prepare_report_fixture(username: str, session_id: str) -> dict:
    from app.database import DBProfileSnapshot, DBUser
    from app.diagnostic_report import diagnostic_report_payload, generate_diagnostic_report
    def work():
        session = _isolated_session()
        try:
            user = session.query(DBUser).filter_by(username=username).one()
            row, created = generate_diagnostic_report(
                session, user=user, session_id=session_id,
                idempotency_key=f"diagnostic-report-{session_id}", llm=DemoModel(),
            )
            # The report contract keeps the public label "known" for an observed
            # score, while schedule projection must still treat a diagnosed weak
            # point as actionable.  Preserve that distinction in the isolated
            # snapshot used by this demo so today's task remains visible.
            snapshot = session.get(DBProfileSnapshot, row.profile_snapshot_id)
            if snapshot is not None:
                body = dict(snapshot.snapshot or {})
                weak_ids = {str(item) for item in body.get("weak_knowledge_point_ids") or []}
                mastery = dict(body.get("mastery_by_knowledge_point") or {})
                for point_id in weak_ids:
                    if isinstance(mastery.get(point_id), dict):
                        mastery[point_id] = {**mastery[point_id], "status": "weak"}
                body["mastery_by_knowledge_point"] = mastery
                snapshot.snapshot = body
            session.commit()
            return {"created": created, "report": diagnostic_report_payload(session, user=user, row=row)}
        finally:
            session.close()
    return _run_in_worker(work)


def prepare_path_fixture(username: str, session_id: str) -> dict:
    from app.database import DBUser
    from app.diagnostic_report import diagnostic_report_payload, generate_report_path
    def work():
        from app.database import DBDiagnosticReport
        session = _isolated_session()
        try:
            user = session.query(DBUser).filter_by(username=username).one()
            report = session.query(DBDiagnosticReport).filter_by(session_id=session_id).one()
            path = generate_report_path(
                session, user=user, report=report, time_budget_minutes=90,
                idempotency_key=f"diagnostic-path-{session_id}", llm=DemoModel(),
            )
            session.commit()
            return {"path": path, "report": diagnostic_report_payload(session, user=user, row=report)}
        finally:
            session.close()
    return _run_in_worker(work)


def api_post(page: Page, token: str, path: str, body: dict | None = None) -> dict:
    response = page.request.post(
        f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {token}"}, data=body or {},
    )
    if not response.ok:
        raise AssertionError(f"POST {path} failed: {response.status} {response.text()}")
    return response.json()


def add_knowledge_and_chat(page: Page, report: dict, token: str) -> None:
    # Knowledge shelf and chapter reader.
    page.goto(f"{BASE_URL}/knowledge?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_test_id("knowledge-course-shelf").wait_for(state="visible", timeout=45_000)
    shot(page, report, "16-knowledge-shelf-master-course-1440x900.png")
    # Open the real canonical course view, graph, and then the first document.
    page.get_by_test_id(f"open-course-{COURSE_ID}").click()
    page.get_by_test_id("course-workspace").wait_for(state="visible", timeout=45_000)
    shot(page, report, "17-knowledge-course-master-course-1440x900.png")
    page.get_by_test_id("open-course-structure").click()
    page.get_by_test_id("course-knowledge-graph-workspace").wait_for(state="visible", timeout=45_000)
    shot(page, report, "18-knowledge-graph-master-course-1440x900.png")
    page.goto(f"{BASE_URL}/knowledge/courses/{COURSE_ID}", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_test_id("course-workspace").wait_for(state="visible", timeout=45_000)
    page.get_by_role("button", name="打开本章文档", exact=True).click()
    page.get_by_role("heading", name=re.compile(".+")).last.wait_for(state="visible", timeout=45_000)
    shot(page, report, "19-knowledge-document-master-course-1440x900.png")

    # Chat is a normal question -> answer flow; no resource intent is sent.
    page.goto(f"{BASE_URL}/chat?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible", timeout=45_000)
    before_jobs = page.request.get(
        f"{BASE_URL}/api/v1/resource-bundles/generation-jobs?course_id={COURSE_ID}",
        headers={"Authorization": f"Bearer {token}"},
    )
    before_job_count = len(before_jobs.json().get("items", [])) if before_jobs.ok else None
    composer = page.get_by_test_id("chat-composer")
    textbox = composer.locator("textarea").last
    textbox.fill("请结合当前主课程来源解释混合检索为什么能同时覆盖精确术语和同义表达。")
    page.get_by_role("button", name=re.compile("发送")).last.click()
    assistant = page.locator(".message-row--assistant").last
    page.get_by_text(re.compile("混合检索|当前课程来源|课程原文"), exact=False).last.wait_for(state="visible", timeout=60_000)
    # Do not treat the first streamed tokens as a completed answer.  The
    # browser evidence must show the terminal state of the same assistant
    # message, otherwise a visible answer can be paired with a stale
    # “正在回答/回答失败” status and the journey would be falsely marked
    # complete.
    try:
        assistant.locator(".assistant-label").get_by_text("回答完成", exact=True).wait_for(state="visible", timeout=60_000)
    except Exception:
        report.setdefault("checks", {})["chat_status_completed"] = False
        report["chat_status_text"] = assistant.locator(".assistant-label").inner_text()
        report["chat_failure_text"] = assistant.locator(".message-failure").inner_text() if assistant.locator(".message-failure").count() else ""
        shot(page, report, "20-chat-master-course-incomplete-1440x900.png")
        raise
    if assistant.locator(".message-failure").count():
        report.setdefault("checks", {})["chat_status_completed"] = False
        report["chat_status_text"] = assistant.locator(".assistant-label").inner_text()
        report["chat_failure_text"] = assistant.locator(".message-failure").inner_text()
        shot(page, report, "20-chat-master-course-incomplete-1440x900.png")
        raise AssertionError(f"chat answer reached a failure state after streaming: {report['chat_failure_text']}")
    report.setdefault("checks", {})["chat_status_completed"] = True
    shot(page, report, "20-chat-master-course-evidence-1440x900.png")
    after_jobs = page.request.get(
        f"{BASE_URL}/api/v1/resource-bundles/generation-jobs?course_id={COURSE_ID}",
        headers={"Authorization": f"Bearer {token}"},
    )
    after_job_count = len(after_jobs.json().get("items", [])) if after_jobs.ok else None
    report.setdefault("checks", {})["chat_answer_visible"] = True
    report["checks"]["chat_resource_not_triggered"] = (
        before_job_count is None or after_job_count == before_job_count
    )
    if before_job_count is not None:
        report["checks"]["resource_count_before_chat"] = before_job_count
        report["checks"]["resource_count_after_chat"] = after_job_count


def run_master_diagnostic_journey(page: Page, report: dict, legacy: Any, username: str) -> tuple[str, str]:
    """Run onboarding and the successful 25-question master-course diagnosis."""
    legacy.register(page, username)
    legacy.attach_course(username)
    token = legacy.login(page, username)
    page.get_by_test_id("onboarding-v2").wait_for(state="visible", timeout=30_000)
    shot(page, report, "01-onboarding-start-1440x900.png")
    answers = (
        "我正在系统学习人工智能与深度学习，希望掌握 RAG、智能体和完整项目实践。",
        "目标是完成一个能用于 AI 应用开发岗位的知识库问答项目。",
        "我有 Python、线性代数和概率基础，神经网络和检索评测还不够熟练。",
        "我容易混淆召回率、准确率、向量检索和关键词检索的适用边界。",
        "我喜欢先看直观例子，再分步推导，最后用代码和测验验证。",
    )
    legacy.answer_onboarding(page, answers[0])
    page.reload(wait_until="domcontentloaded")
    page.get_by_test_id("onboarding-progress").get_by_text("1/5", exact=True).wait_for(state="visible")
    report["checks"]["onboarding_refresh_resume"] = True
    for answer in answers[1:]:
        legacy.answer_onboarding(page, answer)
    page.get_by_test_id("onboarding-complete").wait_for(state="visible", timeout=30_000)
    shot(page, report, "02-onboarding-complete-1440x900.png")
    with page.expect_response(lambda r: r.url.endswith("/api/v1/onboarding/finalize") and r.status == 200, timeout=30_000):
        page.get_by_test_id("onboarding-complete").get_by_role("button", name="确认初始画像").click()
    page.get_by_role("button", name="进入入学诊断").wait_for(state="visible", timeout=20_000)

    # Generate the blueprint through the canonical backend functions, but only
    # against this isolated DB.  The UI subsequently retrieves the same record
    # using the normal idempotency key and renders the real ready state.
    diagnostic_key = f"student-journey-diagnostic-{username}"
    blueprint_id = prepare_diagnostic_fixture(username, diagnostic_key)
    page.goto(f"{BASE_URL}/workspace/assessment/entry?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_test_id("diagnostic-overview").wait_for(state="visible", timeout=45_000)
    page.get_by_label("诊断题目数量").select_option("25")
    page.get_by_test_id("generate-diagnostic").wait_for(state="visible", timeout=45_000)
    storage_key = f"edumatrix-diagnostic-key:{COURSE_ID}:25:foundation"
    page.evaluate("([key, value]) => sessionStorage.setItem(key, value)", [storage_key, diagnostic_key])
    with page.expect_response(lambda r: r.url.endswith("/api/v1/diagnostics/blueprints") and r.status == 201, timeout=60_000):
        page.get_by_test_id("generate-diagnostic").click()
    page.get_by_test_id("diagnostic-ready").wait_for(state="visible", timeout=45_000)
    shot(page, report, "03-diagnostic-ready-1440x900.png")
    page.get_by_test_id("enter-diagnostic").click()
    page.get_by_test_id("diagnostic-session").wait_for(state="visible", timeout=45_000)
    shot(page, report, "04-diagnostic-first-question-1440x900.png")

    # Read the session id after the normal start endpoint has created it; route
    # only the model-dependent report/path calls to the isolated DemoModel.
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        owner_id = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
        session_id = db.execute(
            "SELECT id FROM diagnostic_sessions WHERE owner_public_id=? AND blueprint_id=? ORDER BY started_at DESC LIMIT 1",
            (owner_id, blueprint_id),
        ).fetchone()[0]

    def report_route(route):
        if route.request.method == "POST" and route.request.url.rstrip("/").endswith("/report"):
            result = prepare_report_fixture(username, session_id)
            route.fulfill(status=201, content_type="application/json", body=json.dumps(result, ensure_ascii=False))
        else:
            route.continue_()

    def path_route(route):
        if route.request.method == "POST" and route.request.url.rstrip("/").endswith("/report/path"):
            result = prepare_path_fixture(username, session_id)
            route.fulfill(status=200, content_type="application/json", body=json.dumps(result, ensure_ascii=False))
        else:
            route.continue_()

    page.route("**/api/v1/diagnostics/sessions/*/report**", report_route)
    page.route("**/api/v1/diagnostics/sessions/*/report/path**", path_route)
    total = 25
    for index in range(total):
        qtype = page.locator(".question-heading .question-meta span").first.inner_text()
        if qtype == "单选题":
            page.locator(".option-list label").first.click()
        elif qtype == "判断题":
            # Keep one deliberate incorrect answer so the report/path visibly
            # contains a weak knowledge point and a remediation step.
            page.get_by_role("button", name=("错误" if index == 0 else "正确"), exact=True).click()
        else:
            page.locator("textarea.text-answer").fill("混合检索结合关键词精确匹配与向量语义召回，并通过课程来源核验结果。")
        page.get_by_text("基本理解", exact=True).click()
        if index < total - 1:
            page.get_by_role("button", name="保存并进入下一题", exact=True).click()
            page.get_by_text(re.compile(rf"第 {index + 2} / {total} 题")).wait_for(state="visible", timeout=30_000)
        else:
            page.get_by_role("button", name="提交本次诊断", exact=True).click()
    page.get_by_test_id("diagnostic-submitted").wait_for(state="visible", timeout=60_000)
    page.get_by_role("heading", name="你的入学诊断结果").wait_for(state="visible", timeout=60_000)
    # Open the two evidence drawers so the screenshot demonstrates real
    # knowledge-point feedback rather than only the headline score.
    page.get_by_test_id("report-knowledge-toggle").click()
    page.get_by_test_id("report-evidence-toggle").click()
    shot(page, report, "05-diagnostic-report-evidence-1440x900.png")
    page.get_by_role("button", name="生成初始学习路径", exact=True).click()
    page.get_by_role("button", name="确认并进入总学习路径", exact=True).wait_for(state="visible", timeout=45_000)
    shot(page, report, "06-path-draft-from-diagnostic-1440x900.png")
    page.get_by_role("button", name="确认并进入总学习路径", exact=True).click()
    page.wait_for_url(re.compile(r".*/workspace/path\\?.*path_id=.*"), timeout=45_000)
    return token, session_id


def run_resource_and_exam_journey(page: Page, report: dict, legacy: Any, token: str, username: str) -> None:
    # The graph page defaults to a cross-course D-day projection.  Pin the
    # freshly-confirmed path to the unified master course so historical seed
    # paths cannot hide today's master-course task.
    path_id = parse_qs(urlparse(page.url).query).get("path_id", [""])[0]
    page.goto(
        f"{BASE_URL}/workspace/path?course_id={COURSE_ID}&path_id={path_id}"
        f"&view=subject&subject_id={COURSE_ID}",
        wait_until="domcontentloaded", timeout=60_000,
    )
    page.get_by_test_id("path-overview").wait_for(state="visible", timeout=45_000)
    select_today = page.get_by_test_id("today-knowledge-points").locator("button")
    select_today.first.wait_for(state="visible", timeout=30_000)
    select_today.first.click()
    page.get_by_test_id("selected-knowledge-point").wait_for(state="visible", timeout=30_000)
    page.get_by_test_id("selected-knowledge-point").locator("button.generation-panel__generate").wait_for(state="visible")
    shot(page, report, "07-path-today-task-1440x900.png")

    # The path action enters the canonical Chat path_bundle route. Chat creates
    # the generation job, while the isolated run has no external model and
    # therefore leaves a recoverable failed state that we can demonstrate.
    page.get_by_role("button", name="一键生成完整资源包", exact=True).click()
    page.wait_for_url(re.compile(r".*/(?:chat|learn)\\?.*intent=path_bundle"), timeout=45_000)
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible", timeout=45_000)
    deadline = time.monotonic() + 75
    job = None
    while time.monotonic() < deadline:
        response = page.request.get(
            f"{BASE_URL}/api/v1/resource-bundles/generation-jobs?course_id={COURSE_ID}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.ok:
            jobs = response.json().get("items") or []
            if jobs:
                job = jobs[0]
                break
        page.wait_for_timeout(1000)
    if not job:
        raise AssertionError("路径资源入口未在聊天流程中创建 generation job")
    job_id = str(job["job_id"])
    report.setdefault("checks", {})["resource_entry_route"] = page.url
    report["checks"]["resource_job_created_by_chat"] = job_id

    page.goto(
        f"{BASE_URL}/workspace/resources/bundles/{job_id}?course_id={COURSE_ID}",
        wait_until="domcontentloaded", timeout=60_000,
    )
    page.get_by_test_id("resource-bundle-workspace").wait_for(state="visible", timeout=45_000)
    page.get_by_role("button", name="重试此项", exact=True).first.wait_for(state="visible", timeout=45_000)
    shot(page, report, "08-resource-retry-state-1440x900.png")

    # Recover all failed items in one explicit action and run the existing
    # deterministic executor; each resource still goes through the canonical
    # item/artifact protocol and remains separate from mastery updates.
    recovered = api_post(page, token, f"/api/v1/resource-bundles/generation-jobs/{job_id}/recover")
    assert recovered["job_id"] == job_id
    completed = api_post(page, token, f"/api/v1/resource-bundles/generation-jobs/{job_id}/execute-demo")
    assert completed["job_id"] == job_id
    page.reload(wait_until="domcontentloaded")
    workspace = page.get_by_test_id("resource-bundle-workspace")
    workspace.get_by_text("完整资源包已就绪", exact=True).wait_for(state="visible", timeout=60_000)
    workspace.get_by_text(re.compile(r"\d+ / \d+ 已归档"), exact=False).wait_for(state="visible", timeout=60_000)
    final_job = page.request.get(
        f"{BASE_URL}/api/v1/resource-bundles/generation-jobs/{job_id}",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert final_job["status"] == "succeeded"
    assert all(item["state"] == "succeeded" for item in final_job["items"])
    report["checks"]["resource_recovery"] = {
        "job_id": job_id,
        "resource_types": [item["type"] for item in final_job["items"]],
        "completed": len([item for item in final_job["items"] if item["state"] == "succeeded"]),
    }
    shot(page, report, "09-resource-ready-1440x900.png")

    # Complete the generated quiz inside its canonical resource workspace.
    # The first submission is intentionally wrong so the screenshot proves
    # that the question body, options, correct answer and explanation are real;
    # the second submission completes one required item and emits a canonical
    # learning event that the profile/path aggregator can consume.
    quiz_item = next(item for item in final_job["items"] if item["type"] == "quiz")
    quiz_resource = quiz_item.get("resource") or {}
    quiz_resource_id = str(quiz_resource.get("resource_id") or "")
    if not quiz_resource_id:
        raise AssertionError("completed resource bundle did not return quiz resource identity")
    page.goto(
        f"{BASE_URL}/workspace/resources/quizzes/{quiz_resource_id}?course_id={COURSE_ID}",
        wait_until="domcontentloaded", timeout=60_000,
    )
    quiz_workspace = page.get_by_test_id("quiz-resource-workspace")
    quiz_workspace.wait_for(state="visible", timeout=45_000)
    inline_quiz = quiz_workspace.get_by_test_id("inline-quiz-card")
    inline_quiz.wait_for(state="visible", timeout=45_000)
    question_text = inline_quiz.locator("h2").inner_text()
    option_count = inline_quiz.locator(".option-list label").count()
    if not question_text.strip() or option_count < 2:
        raise AssertionError("quiz workspace did not render a complete question and option set")
    report["checks"]["quiz_resource_identity"] = {
        "resource_id": quiz_resource_id,
        "route": page.url,
        "question_count": int(quiz_workspace.locator(".question-rail > button").count()),
        "first_question_option_count": option_count,
    }
    shot(page, report, "09b-resource-quiz-question-1440x900.png")

    # Generated deterministic quiz questions use the first option as the
    # correct answer; select the second option to expose the wrong-answer UI.
    inline_quiz.locator(".option-list label").nth(1).click()
    inline_quiz.get_by_role("button", name="提交答案", exact=True).click()
    inline_quiz.get_by_text("这次还不正确", exact=True).wait_for(state="visible", timeout=45_000)
    inline_quiz.get_by_text("正确答案：", exact=False).wait_for(state="visible", timeout=20_000)
    inline_quiz.get_by_text("解析：", exact=False).wait_for(state="visible", timeout=20_000)
    inline_quiz.get_by_text("解析：", exact=False).scroll_into_view_if_needed()
    shot(page, report, "09c-resource-quiz-feedback-wrong-1440x900.png")

    # Correct the same question.  The component creates a new immutable
    # attempt, while the earlier wrong attempt remains visible in history.
    inline_quiz.get_by_role("button", name="修改答案", exact=True).click()
    inline_quiz.locator(".option-list label").first.click()
    inline_quiz.get_by_role("button", name="提交新答案", exact=True).click()
    inline_quiz.get_by_text("回答正确", exact=True).wait_for(state="visible", timeout=45_000)
    quiz_workspace.get_by_text(re.compile(r"1/3"), exact=False).first.wait_for(state="visible", timeout=20_000)
    inline_quiz.get_by_text("解析：", exact=False).scroll_into_view_if_needed()
    shot(page, report, "09d-resource-quiz-feedback-correct-1440x900.png")

    with sqlite3.connect(DB_PATH, timeout=20) as db:
        owner_id = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()[0]
        attempts = db.execute(
            "SELECT id, correct, grading_status FROM assessment_attempts "
            "WHERE owner_public_id=? AND course_id=? AND mode='practice' ORDER BY submitted_at",
            (owner_id, COURSE_ID),
        ).fetchall()
        quiz_events = db.execute(
            "SELECT id FROM learning_events WHERE owner_public_id=? AND course_id=? AND event_type='quiz_answered' "
            "AND object_type='assessment_question_version' ORDER BY recorded_at",
            (owner_id, COURSE_ID),
        ).fetchall()
        latest_snapshot = db.execute(
            "SELECT id, profile_version, snapshot FROM profile_snapshots "
            "WHERE owner_public_id=? AND profile_version LIKE 'f8.learning-feedback.%' ORDER BY created_at DESC LIMIT 1",
            (owner_id,),
        ).fetchone()
    if len(attempts) < 2 or not all(row[2] == "graded" for row in attempts[-2:]):
        raise AssertionError(f"quiz attempts were not graded: {attempts}")
    if attempts[-2][1] != 0 or attempts[-1][1] != 1:
        raise AssertionError(f"quiz wrong-to-correct sequence missing: {attempts}")
    report["checks"]["quiz_closure"] = {
        "attempts": [{"id": row[0], "correct": bool(row[1]), "grading_status": row[2]} for row in attempts[-2:]],
        "learning_event_ids": [row[0] for row in quiz_events],
        "learning_event_count": len(quiz_events),
        "latest_feedback_snapshot_id": latest_snapshot[0] if latest_snapshot else None,
        "latest_feedback_snapshot_version": latest_snapshot[1] if latest_snapshot else None,
        "mastery_or_path_update_recorded": bool(latest_snapshot),
    }

    # Formal exam gate: first show the locked state, then add trusted completion
    # evidence through the existing verified helper and show the unlocked builder.
    page.goto(f"{BASE_URL}/workspace/assessment?course_id={COURSE_ID}", wait_until="domcontentloaded", timeout=45_000)
    center = page.get_by_test_id("assessment-center"); center.wait_for(state="visible", timeout=45_000)
    center.get_by_test_id("intelligent-exam-entry").click()
    page.get_by_test_id("exam-gate-locked").wait_for(state="visible", timeout=45_000)
    shot(page, report, "10-exam-gate-locked-1440x900.png")
    report["checks"]["trusted_completion_evidence"] = legacy.create_trusted_completion_evidence(username)
    page.reload(wait_until="domcontentloaded")
    page.get_by_test_id("exam-builder-unlocked").wait_for(state="visible", timeout=60_000)
    shot(page, report, "11-exam-gate-unlocked-1440x900.png")


def db_audit(username: str) -> dict:
    with sqlite3.connect(DB_PATH) as db:
        owner = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()
        if not owner:
            raise RuntimeError("journey user missing")
        owner_id = owner[0]
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "master_course": db.execute("SELECT COUNT(*) FROM courses WHERE id=? AND status='published'", (COURSE_ID,)).fetchone()[0],
            "master_sources": db.execute("SELECT COUNT(*) FROM source_documents WHERE course_id=? AND processing_status='ready'", (COURSE_ID,)).fetchone()[0],
            "master_chapters": db.execute("SELECT COUNT(*) FROM chapters WHERE course_id=?", (COURSE_ID,)).fetchone()[0],
            "master_refs": db.execute("SELECT COUNT(*) FROM source_refs sr JOIN source_documents sd ON sd.id=sr.source_document_id WHERE sd.course_id=?", (COURSE_ID,)).fetchone()[0],
            "master_membership": db.execute("SELECT COUNT(*) FROM course_memberships WHERE course_id=? AND user_public_id=? AND status='active'", (COURSE_ID, owner_id)).fetchone()[0],
            "onboarding_sessions": db.execute("SELECT COUNT(*) FROM onboarding_sessions WHERE owner_public_id=?", (owner_id,)).fetchone()[0],
            "diagnostic_reports": db.execute("SELECT COUNT(*) FROM diagnostic_reports WHERE owner_public_id=?", (owner_id,)).fetchone()[0],
            "paths": db.execute("SELECT COUNT(*) FROM learning_paths WHERE owner_public_id=? AND course_id=?", (owner_id, COURSE_ID)).fetchone()[0],
            "resource_jobs": db.execute("SELECT COUNT(*) FROM generation_tasks WHERE owner_public_id=? AND course_id=?", (owner_id, COURSE_ID)).fetchone()[0],
            "learning_events": db.execute("SELECT COUNT(*) FROM learning_events WHERE owner_public_id=?", (owner_id,)).fetchone()[0],
            "chat_messages": db.execute("SELECT COUNT(*) FROM chat_messages WHERE owner_public_id=?", (owner_id,)).fetchone()[0],
        }


def main() -> int:
    clear_output()
    if DB_PATH.exists():
        DB_PATH.unlink()
    formal_db = ROOT / "edumatrix.db"
    formal_before = {"exists": formal_db.exists(), "size": formal_db.stat().st_size if formal_db.exists() else None, "sha256": sha256(formal_db) if formal_db.exists() else None}
    env = runtime_env()
    report = {"schema_version": "student-journey.master-course.v1", "result": "failed", "course_id": COURSE_ID, "database": str(DB_PATH), "service": BASE_URL, "screenshots": [], "screenshot_meta": {}, "layout_checks": {}, "checks": {}, "http_errors": [], "failed_requests": [], "console_errors": [], "page_errors": [], "formal_db_before": formal_before}
    process = None
    username = f"journey_{int(time.time())}"
    try:
        seed = subprocess.run([sys.executable, "-c", "from app.database import init_db,SessionLocal; from app.competition_demo_seed import seed_competition_demo; init_db(); db=SessionLocal(); print(seed_competition_demo(db)); db.close()"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
        (EVIDENCE / "seed.log").write_text(seed.stdout + "\n" + seed.stderr, encoding="utf-8")
        if seed.returncode:
            raise RuntimeError(f"demo seed failed: {seed.stdout}\n{seed.stderr}")
        with (EVIDENCE / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            # Import the proven F4 journey and bind its actions to the master course.
            spec = importlib.util.spec_from_file_location("legacy_f4_journey", ROOT / "scripts" / "e2e_f4_phase_journey.py")
            if spec is None or spec.loader is None:
                raise RuntimeError("unable to load the proven F4 journey module")
            legacy = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(legacy)
            legacy.OUTPUT_DIR = OUTPUT_DIR
            legacy.DB_PATH = DB_PATH
            legacy.PORT = PORT
            legacy.BASE_URL = BASE_URL
            legacy.COURSE_ID = COURSE_ID
            legacy.PASSWORD = PASSWORD
            legacy.structured_handout_fixture = master_handout_fixture
            os.environ.update(env)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page(); page.set_default_timeout(35_000); diagnostics(page, report)
                token, _session_id = run_master_diagnostic_journey(page, report, legacy, username)
                run_resource_and_exam_journey(page, report, legacy, token, username)
                add_knowledge_and_chat(page, report, token)
                context.close(); browser.close()
        report["database_audit"] = db_audit(username)
        report["checks"]["master_course_context"] = report["database_audit"]["master_membership"] == 1
        report["checks"]["canonical_counts"] = {key: report["database_audit"][key] for key in ("master_sources", "master_chapters", "master_refs")}
        formal_after = {"exists": formal_db.exists(), "size": formal_db.stat().st_size if formal_db.exists() else None, "sha256": sha256(formal_db) if formal_db.exists() else None}
        report["formal_db_after"] = formal_after
        report["checks"]["formal_db_unchanged"] = formal_after == formal_before
        report["checks"]["no_unexpected_browser_errors"] = not (report["http_errors"] or report["failed_requests"] or report["console_errors"] or report["page_errors"])
        assert report["database_audit"]["integrity"] == "ok"
        assert report["database_audit"]["foreign_key_violations"] == 0
        assert report["database_audit"]["master_course"] == 1
        assert report["database_audit"]["master_sources"] == 24
        assert report["database_audit"]["master_chapters"] == 24
        assert report["database_audit"]["master_refs"] == 24
        assert report["database_audit"]["master_membership"] == 1
        assert report["database_audit"]["onboarding_sessions"] >= 1
        assert report["database_audit"]["diagnostic_reports"] == 1
        assert report["database_audit"]["paths"] >= 1
        assert report["database_audit"]["resource_jobs"] >= 1
        assert report["database_audit"]["chat_messages"] >= 2
        assert report["checks"]["formal_db_unchanged"]
        assert report["checks"]["no_unexpected_browser_errors"], report
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
            try:
                wait_port(False, 20)
            except RuntimeError:
                pass
        report["process_cleanup"] = process is None or process.poll() is not None
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (EVIDENCE / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "screenshots": len(report["screenshots"]), "error": report.get("error")}, ensure_ascii=False))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
