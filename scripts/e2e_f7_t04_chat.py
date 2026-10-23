"""F7-T04 focused Chat and multimodal parsing desktop E2E on isolated SQLite."""

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
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "f7_t04_chat"
    / "browser"
)
COURSE_ID = "demo-course-rag-trust-v1"
KNOWLEDGE_POINT_ID = "demo-kp-07"
SOURCE_REF_ID = "demo-ref-07"
USERNAME = "lzz"
PASSWORD = "404404aA"
PORT_START = int(os.getenv("EDUMATRIX_F7_T04_PORT", "8997"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F7-T04 E2E port")


def wait_port(port: int, expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(port) is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {port} did not reach expected state: {expected}")


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def runtime_env(db_path: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(db_path),
        "EDUMATRIX_AUTH_SECRET_KEY": "f7-t04-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(port),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def seed_fixture(env: dict[str, str]) -> dict[str, object]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import hashlib
import json
from datetime import datetime
from pathlib import Path

from app.chat_api import MessageInput, create_message_pair
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBAssessmentQuestionVersion, DBArtifact, DBChatAttachment, DBChatConversation,
    DBChatMessage, DBGenerationTask, DBLearningEvent, DBProfileSnapshot,
    DBSourceDocument, DBSourceRef, DBStudentProfile, DBUser, SessionLocal, init_db,
)
from app.m5_resources import resource_detail
from app.resource_bundles import create_generation_job, execute_generation_job_demo
from app.schemas import ContextRef

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    learner = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    profile = db.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).order_by(DBProfileSnapshot.created_at.desc()).first()
    source = db.get(DBSourceRef, {SOURCE_REF_ID!r})
    if profile is None or source is None:
        raise RuntimeError("F7-T04 browser fixture requires the competition profile and canonical source")

    quiz_job = create_generation_job(
        db,
        learner,
        course_id={COURSE_ID!r},
        knowledge_point_id={KNOWLEDGE_POINT_ID!r},
        profile_snapshot_id=profile.id,
        idempotency_key="f7-t04-browser-quiz-001",
        scope="single",
        items=[{{
            "type": "quiz",
            "title": "对话内即时练习",
            "source_ref_ids": [source.id],
            "completion_rule": "至少提交一道题并获得服务端判分",
        }}],
        learning_goal="在对话中完成一题并按需继续追问",
    )
    db.commit()
    quiz_result = execute_generation_job_demo(db, learner, quiz_job["job_id"])
    db.commit()
    quiz_resource_id = quiz_result["items"][0]["resource"]["resource_id"]
    quiz_artifact = db.get(DBArtifact, quiz_resource_id)
    quiz_detail = resource_detail(db, quiz_artifact)
    quiz_question = quiz_detail["quiz"]["current"]["questions"][0]
    quiz_version = db.get(DBAssessmentQuestionVersion, quiz_question["id"])

    conversation = DBChatConversation(
        id="chat-f7-t04-resource",
        owner_public_id=learner.public_id,
        course_id={COURSE_ID!r},
        title="来源约束问答",
    )
    db.add(conversation)
    db.flush()
    context = ContextRef(
        courseId={COURSE_ID!r},
        knowledgePointId={KNOWLEDGE_POINT_ID!r},
        sourceRefId=source.id,
    )
    pair = create_message_pair(
        db,
        learner,
        conversation.id,
        MessageInput(
            content="请结合课程来源解释学习率过大时为什么会震荡。",
            context_refs=[context],
            idempotency_key="f7-t04-browser-message-001",
            return_to="/workspace/path",
        ),
    )
    answer = db.get(DBChatMessage, pair["assistantMessage"]["id"])
    answer_text = """## 直接回答

学习率过大时，参数更新会跨过损失谷底，在两侧反复越界，因此损失表现为震荡。

### 依据

- 当前课程来源给出了步长与稳定性的关系。
- 可以先减小学习率，再观察损失曲线是否收敛。"""
    answer.status = "completed"
    answer.content = answer_text
    answer.content_sha256 = hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
    answer.stream_checkpoint = {{"status": "completed", "receivedCharacters": len(answer_text), "returnTo": "/workspace/path"}}
    answer.completed_at = datetime.utcnow()
    answer.lock_version += 1

    attachment_specs = [
        {{
            "id": "chatatt-f7-t04-partial", "filename": "部分可读讲义.pdf", "file_format": "pdf",
            "mime_type": "application/pdf", "raw": b"synthetic partial pdf", "parsed_text": "已读取第一页的学习率说明。",
            "parser_version": "f7-t04-parser-v1", "locations": [{{"kind": "page", "index": 1, "label": "第 1 页"}}],
            "metadata": {{"page_count": 2}}, "warnings": ["第 2 页无法读取"], "status": "partial_failed",
            "stage": "failed", "progress": 0.62, "error_code": "page_parse_partial",
            "error_message": "部分页面解析失败，可确认后使用已读取内容。", "retryable": True,
            "parse_version": 1, "lock_version": 2, "raw_override": None,
        }},
        {{
            "id": "chatatt-f7-t04-failed", "filename": "损坏实验说明.docx", "file_format": "docx",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "raw": b"invalid docx payload", "parsed_text": "", "parser_version": "", "locations": [],
            "metadata": {{}}, "warnings": [], "status": "failed", "stage": "failed", "progress": 0.2,
            "error_code": "document_parse_failed", "error_message": "DOCX 内容无法读取，请检查文件后重试。",
            "retryable": True, "parse_version": 1, "lock_version": 2, "raw_override": None,
        }},
        {{
            "id": "chatatt-f7-t04-removed", "filename": "已移除示意图.png", "file_format": "png",
            "mime_type": "image/png", "raw": b"removed image", "parsed_text": "", "parser_version": "",
            "locations": [], "metadata": {{}}, "warnings": [], "status": "removed", "stage": "removed",
            "progress": 0.0, "error_code": "", "error_message": "", "retryable": False,
            "parse_version": 0, "lock_version": 2, "raw_override": b"",
        }},
    ]
    for item in attachment_specs:
        raw = item["raw"]
        row = DBChatAttachment(
            id=item["id"], conversation_id=conversation.id, owner_public_id=learner.public_id,
            filename=item["filename"], file_format=item["file_format"], mime_type=item["mime_type"],
            file_size=len(raw), source_sha256=hashlib.sha256(raw).hexdigest(),
            raw_bytes=item["raw_override"] if item["raw_override"] is not None else raw,
            parsed_text=item["parsed_text"], parser_version=item["parser_version"], locations=item["locations"],
            parse_metadata=item["metadata"], warnings=item["warnings"], status=item["status"], stage=item["stage"],
            progress=item["progress"], error_code=item["error_code"], error_message=item["error_message"],
            retryable=item["retryable"], partial_confirmed=False, parse_version=item["parse_version"],
            lock_version=item["lock_version"], idempotency_key=f"browser-{{item['id']}}",
            removed_at=datetime.utcnow() if item["status"] == "removed" else None,
        )
        db.add(row)

    recovery = DBChatConversation(
        id="chat-f7-t04-recovery",
        owner_public_id=learner.public_id,
        course_id={COURSE_ID!r},
        title="停止与继续",
    )
    db.add(recovery)
    db.flush()
    recovery_pair = create_message_pair(
        db,
        learner,
        recovery.id,
        MessageInput(
            content="分步骤解释梯度下降的更新过程。",
            context_refs=[context],
            idempotency_key="f7-t04-browser-message-002",
            return_to="/workspace/path",
        ),
    )
    recovery_answer = db.get(DBChatMessage, recovery_pair["assistantMessage"]["id"])
    partial_text = "先确定当前位置的梯度方向，再决定参数更新步长。"
    recovery_answer.status = "stopped"
    recovery_answer.content = partial_text
    recovery_answer.content_sha256 = hashlib.sha256(partial_text.encode("utf-8")).hexdigest()
    recovery_answer.stream_checkpoint = {{"status": "stopped", "receivedCharacters": len(partial_text), "returnTo": "/workspace/path"}}
    recovery_answer.lock_version += 1
    db.commit()

    student = db.get(DBStudentProfile, {USERNAME!r})
    payload = {{
        "owner_public_id": learner.public_id,
        "conversation_id": conversation.id,
        "recovery_conversation_id": recovery.id,
        "recovery_assistant_id": recovery_answer.id,
        "quiz_resource_id": quiz_resource_id,
        "quiz_question_id": quiz_question["id"],
        "quiz_correct_choice": quiz_version.answer_key["choice"],
        "source_ref_id": source.id,
        "initial": {{
            "learning_events": db.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count(),
            "profile_snapshots": db.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).count(),
            "generation_tasks": db.query(DBGenerationTask).filter_by(owner_public_id=learner.public_id).count(),
            "source_documents": db.query(DBSourceDocument).count(),
            "source_refs": db.query(DBSourceRef).count(),
            "mastery": json.dumps({{
                "concept_mastery": student.concept_mastery if student else {{}},
                "dimension_states": student.dimension_states if student else {{}},
                "weak_points": student.weak_points if student else [],
            }}, ensure_ascii=False, sort_keys=True),
        }},
    }}
    Path({str(fixture_path)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=180)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def start_service(env: dict[str, str], port: int) -> subprocess.Popen:
    log = (OUTPUT_DIR / "server.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    process._edumatrix_log = log  # type: ignore[attr-defined]
    wait_port(port, True)
    return process


def stop_service(process: subprocess.Popen | None, port: int) -> None:
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
    wait_port(port, False, timeout=20)


def login(page: Page, base_url: str) -> None:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": USERNAME, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    state = json.dumps(response.json(), ensure_ascii=False)
    page.add_init_script(f"""
      const session = {state};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_display_name', session.display_name || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_role', session.role || 'student');
      localStorage.setItem('edumatrix_student_id', session.student_id || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', '{COURSE_ID}');
      localStorage.setItem('edumatrix_course_title', 'RAG 应用开发与负责任评测实训');
    """)


def database_state(db_path: Path, owner_public_id: str) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        student = db.execute(
            "SELECT concept_mastery, dimension_states, weak_points FROM student_profiles WHERE student_id=?",
            (USERNAME,),
        ).fetchone()
        return {
            "learning_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "profile_snapshots": db.execute(
                "SELECT COUNT(*) FROM profile_snapshots WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "generation_tasks": db.execute(
                "SELECT COUNT(*) FROM generation_tasks WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "assessment_attempts": db.execute(
                "SELECT COUNT(*) FROM assessment_attempts WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "chat_messages": db.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE owner_public_id=?", (owner_public_id,)
            ).fetchone()[0],
            "source_documents": db.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0],
            "source_refs": db.execute("SELECT COUNT(*) FROM source_refs").fetchone()[0],
            "mastery": json.dumps(student, ensure_ascii=False) if student else "null",
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def page_diagnostics(page: Page, report: dict[str, object]) -> None:
    def response_handler(response) -> None:
        parsed = urlparse(response.url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            report["external_requests"].append(response.url)
        if response.status >= 400:
            report["http_errors"].append({"status": response.status, "url": response.url})

    page.on("response", response_handler)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url,
        "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def capture(page: Page, report: dict[str, object], filename: str) -> None:
    page.screenshot(path=OUTPUT_DIR / filename, full_page=True)
    report["screenshots"].append(filename)


def visual_contract(page: Page) -> dict[str, object]:
    return page.evaluate(
        """
        () => {
          const root = document.querySelector('[data-testid="focused-chat-workspace"]')
          if (!root) return { missingRoot: true }
          const visible = element => {
            const style = getComputedStyle(element)
            const box = element.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0
          }
          const columns = [
            root.querySelector('[data-testid="chat-conversation-rail"]'),
            root.querySelector('[data-testid="chat-answer-workspace"]'),
            root.querySelector('[data-testid="chat-evidence-rail"]'),
          ].map(element => element?.getBoundingClientRect())
          const textNodes = [...root.querySelectorAll('button, a, h1, h2, h3, p, span, strong, small, label, dt, dd, li')]
            .filter(element => visible(element) && element.textContent.trim())
          const smallText = textNodes
            .filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 13.9)
            .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 80), size: getComputedStyle(element).fontSize }))
          const clippedText = textNodes
            .filter(element => {
              if (element.closest('.sr-only')) return false
              const style = getComputedStyle(element)
              if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
              if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
              return element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1
            })
            .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 80) }))
          const backgroundImages = [...root.querySelectorAll('*')]
            .filter(visible)
            .map(element => getComputedStyle(element).backgroundImage)
            .filter(value => value && value !== 'none')
          const forbiddenColors = new Set([
            'rgb(16, 185, 129)', 'rgb(34, 197, 94)', 'rgb(59, 130, 246)',
            'rgb(14, 165, 233)', 'rgb(139, 92, 246)', 'rgb(168, 85, 247)',
            'rgb(120, 53, 15)', 'rgb(146, 64, 14)'
          ])
          const forbiddenThemeHits = [...root.querySelectorAll('*')]
            .filter(visible)
            .flatMap(element => {
              const style = getComputedStyle(element)
              return [style.color, style.backgroundColor, style.borderColor]
                .filter(value => forbiddenColors.has(value))
                .map(value => ({ tag: element.tagName, value, text: element.textContent.trim().slice(0, 60) }))
            })
          return {
            missingRoot: false,
            rootBackground: getComputedStyle(root).backgroundColor,
            pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
            rootOverflow: root.scrollWidth > root.clientWidth + 1 || root.scrollHeight > root.clientHeight + 1,
            columnWidths: columns.map(box => box?.width || 0),
            overlaps: columns.slice(0, -1).map((box, index) => !box || !columns[index + 1] || box.right > columns[index + 1].left + 1),
            smallText,
            clippedText,
            backgroundImages,
            forbiddenThemeHits,
          }
        }
        """
    )


def assert_visual(page: Page, report: dict[str, object], key: str) -> None:
    result = visual_contract(page)
    report["visual"][key] = result
    assert result["missingRoot"] is False, result
    assert result["rootBackground"] == "rgb(245, 247, 247)", result
    assert result["pageOverflow"] is False, result
    assert result["rootOverflow"] is False, result
    left, center, right = result["columnWidths"]
    assert 226 <= left <= 230 and center >= 520 and 290 <= right <= 294, result
    assert result["overlaps"] == [False, False], result
    assert result["smallText"] == [], result
    assert result["clippedText"] == [], result
    assert result["backgroundImages"] == [], result
    assert result["forbiddenThemeHits"] == [], result


def chat_url(base_url: str, fixture: dict[str, object], *, conversation_id: str, quiz: bool = False) -> str:
    query = {
        "course_id": COURSE_ID,
        "knowledge_point_id": KNOWLEDGE_POINT_ID,
        "source_ref_id": fixture["source_ref_id"],
        "conversation_id": conversation_id,
        "return_to": "/workspace/path",
    }
    if quiz:
        query.update({
            "quiz_resource_id": fixture["quiz_resource_id"],
            "question_version_id": fixture["quiz_question_id"],
        })
    return f"{base_url}/learn?{urlencode(query)}"


def open_chat(page: Page, base_url: str, fixture: dict[str, object], *, conversation_id: str, quiz: bool = False) -> None:
    page.goto(chat_url(base_url, fixture, conversation_id=conversation_id, quiz=quiz), wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible")
    page.get_by_test_id("chat-conversation-loading").wait_for(state="hidden")


def install_slow_local_stream(page: Page) -> None:
    page.evaluate(
        """
        () => {
          if (!window.__edumatrixOriginalFetch) window.__edumatrixOriginalFetch = window.fetch.bind(window)
          window.fetch = async (input, init = {}) => {
            const url = typeof input === 'string' ? input : input.url
            if (!url.includes('/api/stream/chat')) return window.__edumatrixOriginalFetch(input, init)
            const encoder = new TextEncoder()
            let closed = false
            let timer = null
            const stream = new ReadableStream({
              start(controller) {
                controller.enqueue(encoder.encode('event: progress\\ndata: {"progress":18,"message":"正在整理回答"}\\n\\n'))
                timer = setTimeout(() => {
                  if (closed) return
                  controller.enqueue(encoder.encode('event: chat_chunk\\ndata: {"content":"这是一段可停止的本地流式回答。"}\\n\\n'))
                }, 5000)
                init.signal?.addEventListener('abort', () => {
                  if (closed) return
                  closed = true
                  clearTimeout(timer)
                  controller.close()
                }, { once: true })
              },
              cancel() {
                closed = true
                clearTimeout(timer)
              },
            })
            return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
          }
        }
        """
    )


def restore_fetch(page: Page) -> None:
    page.evaluate(
        """
        () => {
          if (window.__edumatrixOriginalFetch) window.fetch = window.__edumatrixOriginalFetch
        }
        """
    )


def exercise_primary(
    page: Page,
    base_url: str,
    fixture: dict[str, object],
    db_path: Path,
    report: dict[str, object],
) -> None:
    open_chat(page, base_url, fixture, conversation_id=str(fixture["conversation_id"]))
    assert page.get_by_text("来源约束问答", exact=True).count() >= 1
    assert page.get_by_text("部分可读讲义.pdf", exact=True).count() >= 1
    assert page.get_by_text("损坏实验说明.docx", exact=True).count() >= 1
    assert page.get_by_text("已移除，不再参与上下文", exact=True).count() >= 1
    assert_visual(page, report, "resource_initial_1440x900")
    capture(page, report, "01-focused-chat-1440x900.png")

    partial = page.locator(".attachment-row").filter(has_text="部分可读讲义.pdf")
    partial.get_by_role("button", name="确认可用部分", exact=True).click()
    partial.get_by_text("已确认可用部分", exact=False).wait_for(state="visible")

    failed = page.locator(".attachment-row").filter(has_text="损坏实验说明.docx")
    failed.get_by_role("button", name="重试解析", exact=True).click()
    failed.get_by_text("失败可重试", exact=False).wait_for(state="visible")

    upload_path = OUTPUT_DIR / "learning-rate.md"
    upload_path.write_text("# 学习率\n\n学习率过大可能导致损失在谷底两侧震荡。\n", encoding="utf-8")
    page.locator('input[type="file"]').set_input_files(str(upload_path))
    uploaded = page.locator(".attachment-row").filter(has_text="learning-rate.md")
    uploaded.get_by_text("可发送", exact=False).wait_for(state="visible", timeout=30_000)

    before_chat_actions = database_state(db_path, str(fixture["owner_public_id"]))
    page.get_by_label("输入问题").fill("结合刚上传的材料，再用两句话总结学习率过大的风险。")
    page.get_by_role("button", name="发送", exact=True).click()
    page.get_by_text("回答完成", exact=True).last.wait_for(state="visible", timeout=60_000)
    uploaded.get_by_role("button", name="移除附件", exact=True).click()
    page.get_by_text("learning-rate.md", exact=True).last.wait_for(state="visible")

    seeded_answer = page.locator(".message-row--assistant").filter(has_text="学习率过大时，参数更新会跨过损失谷底")
    seeded_answer.locator("summary").filter(has_text="生成学习资源").click()
    seeded_answer.get_by_role("button", name="个性化讲义", exact=True).click()
    seeded_answer.get_by_test_id("chat-compact-resource-links").wait_for(state="visible", timeout=30_000)
    assert "学习空间" in seeded_answer.get_by_test_id("chat-compact-resource-links").inner_text()
    assert_visual(page, report, "resource_actions_1440x900")
    capture(page, report, "02-attachments-and-resource-link-1440x900.png")

    after_chat_actions = database_state(db_path, str(fixture["owner_public_id"]))
    for key in ("learning_events", "profile_snapshots", "source_documents", "source_refs"):
        assert after_chat_actions[key] == before_chat_actions[key], (key, before_chat_actions, after_chat_actions)
    assert after_chat_actions["mastery"] == before_chat_actions["mastery"]
    assert after_chat_actions["generation_tasks"] == before_chat_actions["generation_tasks"] + 1
    report["checks"]["chat_actions_protected_state"] = {
        "before": before_chat_actions,
        "after": after_chat_actions,
    }

    page.locator(".conversation-item").filter(has_text="停止与继续").click()
    page.get_by_text("先确定当前位置的梯度方向", exact=False).wait_for(state="visible")
    page.get_by_role("button", name="继续回答", exact=True).click()
    page.get_by_text("回答完成", exact=True).last.wait_for(state="visible", timeout=60_000)

    install_slow_local_stream(page)
    page.get_by_label("输入问题").fill("请生成一段可以手动停止的回答。")
    page.get_by_role("button", name="发送", exact=True).click()
    stop_button = page.get_by_role("button", name="停止", exact=True)
    stop_button.wait_for(state="visible", timeout=10_000)
    stop_button.click()
    page.get_by_role("button", name="继续回答", exact=True).last.wait_for(state="visible", timeout=10_000)
    restore_fetch(page)
    page.get_by_role("button", name="继续回答", exact=True).last.click()
    page.get_by_text("回答完成", exact=True).last.wait_for(state="visible", timeout=60_000)
    capture(page, report, "03-stop-continue-recovery-1440x900.png")
    report["checks"]["stop_continue"] = "stopped_and_resumed_to_completed"

    page.get_by_role("button", name="新建对话", exact=True).click()
    page.get_by_test_id("chat-messages-empty").wait_for(state="visible")
    assert "今天想先弄懂什么" in page.get_by_test_id("chat-messages-empty").inner_text()
    capture(page, report, "04-empty-conversation-1440x900.png")
    with page.expect_response(
        lambda response: "/api/v1/chat/conversations/" in response.url and response.url.endswith("/archive")
    ) as archive_response:
        page.locator(".conversation-item.active").get_by_role("button", name="归档对话", exact=True).click()
    assert archive_response.value.status == 200
    page.locator(".conversation-item.active").wait_for(state="visible")
    page.locator(".message-list").wait_for(state="visible")
    page.wait_for_load_state("networkidle")


def exercise_quiz(
    page: Page,
    base_url: str,
    fixture: dict[str, object],
    db_path: Path,
    report: dict[str, object],
    suffix: str,
) -> None:
    open_chat(page, base_url, fixture, conversation_id=str(fixture["conversation_id"]), quiz=True)
    card = page.get_by_test_id("inline-quiz-card")
    card.wait_for(state="visible", timeout=30_000)
    assert page.get_by_role("button", name="完整题组", exact=True).count() == 1
    assert_visual(page, report, f"inline_quiz_{suffix}")
    capture(page, report, f"05-inline-quiz-{suffix}.png")
    if suffix != "1440x900":
        return

    before = database_state(db_path, str(fixture["owner_public_id"]))
    correct_choice = str(fixture["quiz_correct_choice"])
    option = card.locator(f'input[type="radio"][value="{correct_choice}"]')
    option.locator("xpath=..").click()
    card.get_by_role("button", name="提交答案", exact=True).click()
    card.get_by_text("回答正确", exact=True).wait_for(state="visible", timeout=30_000)
    after_submit = database_state(db_path, str(fixture["owner_public_id"]))
    assert after_submit["assessment_attempts"] == before["assessment_attempts"] + 1
    assert after_submit["learning_events"] >= before["learning_events"] + 1

    card.get_by_role("button", name="继续追问这道题", exact=True).click()
    card.get_by_placeholder("例如：为什么另一个选项不成立？").fill("为什么学习率过大时会跨过谷底？")
    card.get_by_role("button", name="带着本题上下文追问", exact=True).click()
    composer = page.get_by_label("输入问题")
    assert "为什么学习率过大时会跨过谷底" in composer.input_value()
    after_follow_up = database_state(db_path, str(fixture["owner_public_id"]))
    assert after_follow_up["assessment_attempts"] == after_submit["assessment_attempts"]
    assert after_follow_up["learning_events"] == after_submit["learning_events"]
    report["checks"]["inline_quiz_follow_up"] = {
        "before": before,
        "after_submit": after_submit,
        "after_follow_up": after_follow_up,
    }
    capture(page, report, "06-inline-quiz-feedback-follow-up-1440x900.png")


def run() -> dict[str, object]:
    clear_output()
    db_path = OUTPUT_DIR / "f7_t04.sqlite3"
    port = free_port()
    env = runtime_env(db_path, port)
    fixture = seed_fixture(env)
    process: subprocess.Popen | None = None
    report: dict[str, object] = {
        "schema_version": "f7-t04.focused-chat-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "checks": {},
        "visual": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "external_model_called": False,
    }
    try:
        process = start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)

            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            login(page, base_url)
            exercise_primary(page, base_url, fixture, db_path, report)
            exercise_quiz(page, base_url, fixture, db_path, report, "1440x900")
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            login(page, base_url)
            open_chat(page, base_url, fixture, conversation_id=str(fixture["conversation_id"]))
            assert_visual(page, report, "resource_initial_1366x768")
            capture(page, report, "07-focused-chat-1366x768.png")
            exercise_quiz(page, base_url, fixture, db_path, report, "1366x768")
            context.close()

            browser.close()

        final_state = database_state(db_path, str(fixture["owner_public_id"]))
        report["database"] = final_state
        assert final_state["integrity"] == "ok"
        assert final_state["foreign_key_violations"] == 0
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["external_requests"], report["external_requests"]
        report["status"] = "passed"
        return report
    finally:
        stop_service(process, port)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT_DIR.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT_DIR / "manifest.json").write_text(
            json.dumps({"schema_version": "f7-t04.evidence-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
