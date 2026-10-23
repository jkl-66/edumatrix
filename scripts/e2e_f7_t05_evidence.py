"""F7-T05 canonical source and public Agent audit desktop E2E."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import Page, sync_playwright

import e2e_f5_t03_handout_workspace as handout_base
import e2e_f7_t02_document_reader as reader_base
import e2e_f7_t04_chat as chat_base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f7_t05_source_agent" / "browser"
COURSE_ID = "course-f7-t05-browser"
DOCUMENT_ID = "document-f7-t05-browser"
SOURCE_ID = "source-f7-t05-browser"
CHAPTER_ID = "chapter-f7-t05-browser"
SOURCE_REF_ID = "ref-f7-t05-browser"
SELECTION_ID = "selection-f7-t05-browser"
HANDOUT_ID = "handout-f7-t05-browser"
COMPLETED_CONVERSATION_ID = "chat-f7-t05-browser-completed"
FAILED_CONVERSATION_ID = "chat-f7-t05-browser-failed"
USERNAME = "lzz"
PORT_START = int(os.getenv("EDUMATRIX_F7_T05_PORT", "9027"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def configure_shared_helpers() -> None:
    chat_base.OUTPUT_DIR = OUTPUT_DIR
    chat_base.COURSE_ID = COURSE_ID
    chat_base.PORT_START = PORT_START
    handout_base.OUTPUT_DIR = OUTPUT_DIR
    handout_base.COURSE_ID = COURSE_ID


def seed_fixture(env: dict[str, str]) -> dict[str, object]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    handout = handout_base.handout_content(
        SOURCE_REF_ID,
        "本讲义以统一来源引用连接个性化解释、反例、代码和学习检查。",
    )
    handout_json = json.dumps(handout, ensure_ascii=False)
    content = (
        "# 梯度下降与学习率\n\n"
        "梯度表示目标函数增长最快的方向，因此参数沿负梯度方向更新。\n\n"
        "## 学习率与稳定性\n\n"
        "学习率决定每一步的长度。学习率过大时，参数可能跨过损失谷底，在两侧反复震荡；"
        "合理减小学习率后，更新通常会更稳定。\n\n"
        "## 验证方法\n\n"
        "观察连续迭代的损失曲线，并将相同初始点下的不同学习率进行对比。"
    )
    script = f'''
import hashlib
import json
from datetime import datetime

from app.agent_audit import build_chat_agent_audit
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBArtifact, DBChapter, DBChatConversation, DBChatMessage, DBCourse, DBCourseMembership,
    DBDocumentSelection, DBKnowledgeDocument, DBSourceDocument, DBSourceRef,
    DBStudentProfile, DBUser, SessionLocal, init_db,
)
from app.m1_repository import add_artifact_version
from app.source_refs import chat_source_ref, project_source_ref

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    learner = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    if db.get(DBStudentProfile, {USERNAME!r}) is None:
        db.add(DBStudentProfile(student_id={USERNAME!r}))
        db.flush()

    course = DBCourse(
        id={COURSE_ID!r}, version="1", title="优化算法可信学习课程",
        description="隔离浏览器验收课程", visibility="private", status="published",
        owner_public_id=learner.public_id, manifest_version="f7-t05-browser-v1",
        content_origin="isolated_e2e_fixture", license_text="仅用于隔离自动验收",
    )
    document = DBKnowledgeDocument(
        id={DOCUMENT_ID!r}, student_id={USERNAME!r}, filename="gradient-descent.md",
        file_type="md", title="统一来源讲义", content={content!r},
        file_size=len({content!r}.encode("utf-8")), tags=["优化算法", "梯度下降"], chunk_count=3,
    )
    content_hash = hashlib.sha256({content!r}.encode("utf-8")).hexdigest()
    source = DBSourceDocument(
        id={SOURCE_ID!r}, course_id=course.id, legacy_document_id=document.id,
        title=document.title, filename=document.filename, file_format="markdown",
        content_hash=content_hash, source_sha256=content_hash, processed_sha256=content_hash,
        source_path="isolated-e2e/gradient-descent.md", uploader_public_id=learner.public_id,
        parser_version="f7-t05-browser-parser-v1", processing_status="ready",
        license_text="仅用于隔离自动验收",
    )
    db.add_all([course, document, source])
    db.flush()
    db.add(DBCourseMembership(
        course_id=course.id, user_public_id=learner.public_id,
        role="student", status="active",
    ))
    chapter = DBChapter(
        id={CHAPTER_ID!r}, course_id=course.id, source_document_id=source.id,
        stable_key="learning-rate", title="学习率与稳定性", position=1,
        char_start=0, char_end=len({content!r}),
    )
    db.add(chapter)
    db.flush()
    source_ref = DBSourceRef(
        id={SOURCE_REF_ID!r}, source_document_id=source.id, chapter_id=chapter.id,
        parser_version=source.parser_version, char_start=0, char_end=len({content!r}),
        location_kind="section", location_index=1,
        location_label="学习率与稳定性 · 字符 0-{{}}".format(len({content!r})),
        content_hash=content_hash, quote="学习率过大时，参数可能跨过损失谷底，在两侧反复震荡。",
    )
    db.add(source_ref)
    db.flush()

    selection = DBDocumentSelection(
        id={SELECTION_ID!r}, owner_public_id=learner.public_id,
        source_document_id=source.id, source_ref_id=source_ref.id,
        document_version=content_hash, selection_type="text", section_id=chapter.id,
        char_start=0, char_end=22, quote="梯度表示目标函数增长最快的方向",
        ocr_status="not_required", question_draft="为什么要沿负梯度方向更新？",
        answer_status="ready", answer_text="依据当前原文，负梯度方向对应目标函数下降最快的局部方向。",
        answer_source_ref_id=source_ref.id, answer_idempotency_key="f7-t05-selection-answer",
        status="active", idempotency_key="f7-t05-selection",
    )
    db.add(selection)

    artifact = DBArtifact(
        id={HANDOUT_ID!r}, owner_public_id=learner.public_id, course_id=course.id,
        artifact_type="handout", title="梯度下降个性化讲义", status="published",
    )
    db.add(artifact)
    db.flush()
    add_artifact_version(
        db, artifact=artifact, content={handout_json!r}, content_format="json",
        created_by_public_id=learner.public_id,
        metadata={{
            "resource_type": "handout", "module": "优化算法",
            "knowledge_point_title": "梯度下降", "source_ref_ids": [source_ref.id],
            "completion_rule": "阅读关键概念、反例并完成小测",
        }},
    )

    frozen_refs = [chat_source_ref(project_source_ref(db, source_ref.id, actor=learner))]
    return_to = "/workspace/resources/handouts/{HANDOUT_ID}?course_id={COURSE_ID}"

    completed_conversation = DBChatConversation(
        id={COMPLETED_CONVERSATION_ID!r}, owner_public_id=learner.public_id,
        course_id=course.id, title="可信来源问答",
    )
    db.add(completed_conversation)
    db.flush()
    completed_user_text = "学习率过大为什么会震荡？"
    completed_answer_text = "学习率过大时，参数会跨过损失谷底并在两侧反复越界。[S1]"
    completed_audit = build_chat_agent_audit(
        message_id="chatmsg-f7-t05-completed-answer", status="completed",
        input_refs=["source:{SOURCE_REF_ID}"], source_count=1,
        received_characters=len(completed_answer_text),
    )
    db.add_all([
        DBChatMessage(
            id="chatmsg-f7-t05-completed-user", conversation_id=completed_conversation.id,
            owner_public_id=learner.public_id, sequence=1, role="user", status="completed",
            content=completed_user_text,
            content_sha256=hashlib.sha256(completed_user_text.encode("utf-8")).hexdigest(),
            idempotency_key="f7-t05-completed-user", context_refs=[], source_refs=[],
        ),
        DBChatMessage(
            id="chatmsg-f7-t05-completed-answer", conversation_id=completed_conversation.id,
            owner_public_id=learner.public_id, sequence=2, role="assistant", status="completed",
            content=completed_answer_text,
            content_sha256=hashlib.sha256(completed_answer_text.encode("utf-8")).hexdigest(),
            idempotency_key="f7-t05-completed-answer", context_refs=[], source_refs=frozen_refs,
            stream_checkpoint={{
                "status": "completed", "receivedCharacters": len(completed_answer_text),
                "returnTo": return_to, "agentAudit": completed_audit,
            }},
            completed_at=datetime.utcnow(),
        ),
    ])

    failed_conversation = DBChatConversation(
        id={FAILED_CONVERSATION_ID!r}, owner_public_id=learner.public_id,
        course_id=course.id, title="失败与历史结果",
    )
    db.add(failed_conversation)
    db.flush()
    old_text = "这是此前已经完成且有来源的回答。[S1]"
    current_text = "本次回答仅保留到这里。"
    failed_audit = build_chat_agent_audit(
        message_id="chatmsg-f7-t05-failed-answer", status="failed",
        input_refs=["source:{SOURCE_REF_ID}"], source_count=1,
        received_characters=len(current_text),
        failure_message="provider failed; api_key=hidden; raw_trace=hidden; reasoning_content=hidden",
        historical_result={{
            "label": "历史已完成回答（非本次结果）",
            "messageId": "chatmsg-f7-t05-old-answer", "preview": old_text,
            "route": "/learn?conversation_id={FAILED_CONVERSATION_ID}&message_id=chatmsg-f7-t05-old-answer",
            "raw_log": "hidden",
        }},
    )
    failed_rows = [
        ("chatmsg-f7-t05-old-user", 1, "user", "请解释学习率。", "completed", None),
        ("chatmsg-f7-t05-old-answer", 2, "assistant", old_text, "completed", None),
        ("chatmsg-f7-t05-failed-user", 3, "user", "请重新核对这个结论。", "completed", None),
        ("chatmsg-f7-t05-failed-answer", 4, "assistant", current_text, "failed", failed_audit),
    ]
    for message_id, sequence, role, text, status, audit in failed_rows:
        checkpoint = {{"status": status, "receivedCharacters": len(text), "returnTo": return_to}}
        if audit is not None:
            checkpoint["agentAudit"] = audit
        db.add(DBChatMessage(
            id=message_id, conversation_id=failed_conversation.id,
            owner_public_id=learner.public_id, sequence=sequence, role=role, status=status,
            content=text, content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            idempotency_key=message_id, context_refs=[],
            source_refs=frozen_refs if role == "assistant" else [],
            stream_checkpoint=checkpoint,
            error_code="chat_stream_provider_failed" if status == "failed" else "",
            error_message="模型暂时不可用，当前回答已保留。" if status == "failed" else "",
            completed_at=datetime.utcnow() if status == "completed" else None,
        ))

    db.commit()
    payload = {{
        "owner_public_id": learner.public_id,
        "course_id": course.id,
        "source_id": source.id,
        "source_ref_id": source_ref.id,
        "handout_id": artifact.id,
        "completed_conversation_id": completed_conversation.id,
        "failed_conversation_id": failed_conversation.id,
    }}
    from pathlib import Path
    Path({str(fixture_path)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        raise RuntimeError(f"fixture seed failed:\n{result.stdout}\n{result.stderr}")
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def capture(page: Page, report: dict[str, object], filename: str) -> None:
    page.screenshot(path=OUTPUT_DIR / filename, full_page=True, animations="disabled")
    report["screenshots"].append(filename)


def assert_theme(page: Page, report: dict[str, object], key: str, root_selector: str) -> None:
    result = page.evaluate(
        """
        selector => {
          const root = document.querySelector(selector)
          if (!root) return { missingRoot: true }
          const visible = element => {
            const style = getComputedStyle(element)
            const box = element.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0
          }
          const forbidden = new Set([
            'rgb(16, 185, 129)', 'rgb(34, 197, 94)', 'rgb(59, 130, 246)',
            'rgb(14, 165, 233)', 'rgb(139, 92, 246)', 'rgb(168, 85, 247)',
            'rgb(120, 53, 15)', 'rgb(146, 64, 14)'
          ])
          const hits = [...root.querySelectorAll('*')].filter(visible).flatMap(element => {
            const style = getComputedStyle(element)
            return [style.color, style.backgroundColor, style.borderColor]
              .filter(value => forbidden.has(value))
              .map(value => ({ tag: element.tagName, value, text: element.textContent.trim().slice(0, 60) }))
          })
          const gradients = [...root.querySelectorAll('*')].filter(visible)
            .map(element => getComputedStyle(element).backgroundImage)
            .filter(value => value && value !== 'none')
          return { missingRoot: false, hits, gradients }
        }
        """,
        root_selector,
    )
    report["theme"][key] = result
    assert result["missingRoot"] is False, result
    assert result["hits"] == [], result
    assert result["gradients"] == [], result


def handout_url(base_url: str) -> str:
    return f"{base_url}/workspace/resources/handouts/{HANDOUT_ID}?course_id={COURSE_ID}"


def chat_url(base_url: str, conversation_id: str) -> str:
    query = urlencode({
        "course_id": COURSE_ID,
        "source_ref_id": SOURCE_REF_ID,
        "conversation_id": conversation_id,
        "return_to": f"/workspace/resources/handouts/{HANDOUT_ID}?course_id={COURSE_ID}",
    })
    return f"{base_url}/learn?{query}"


def open_chat(page: Page, base_url: str, conversation_id: str) -> None:
    page.goto(chat_url(base_url, conversation_id), wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible")
    page.get_by_test_id("chat-conversation-loading").wait_for(state="hidden")


def assert_public_audit(page: Page, *, status: str) -> None:
    timeline = page.get_by_test_id("agent-audit-timeline")
    timeline.wait_for(state="visible")
    for role in ("分析", "生成", "校验", "决策"):
        assert timeline.get_by_text(role, exact=True).count() == 1
    assert timeline.get_by_text(status, exact=True).count() >= 1
    text = timeline.inner_text().lower()
    for forbidden in ("api_key", "raw_trace", "raw_log", "reasoning_content", "chain_of_thought"):
        assert forbidden not in text


def exercise_handout_reader_round_trip(
    page: Page,
    base_url: str,
    report: dict[str, object],
    suffix: str,
) -> None:
    page.goto(handout_url(base_url), wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("handout-workspace").wait_for(state="visible")
    handout_base.capture(page, report, f"01-handout-source-{suffix}.png")
    assert_theme(page, report, f"handout_{suffix}", '[data-testid="handout-workspace"]')

    page.get_by_role("button", name="查看来源：统一来源讲义", exact=True).first.click()
    page.locator(".reader-page").wait_for(state="visible")
    page.get_by_text("正在打开原文", exact=True).wait_for(state="hidden")
    assert SOURCE_REF_ID in page.url
    assert f"chapter_id={CHAPTER_ID}" in page.url
    assert "char_start=0" in page.url
    page.get_by_text("基于选区的回答", exact=True).wait_for(state="visible")
    assert_public_audit(page, status="已完成")
    reader_base.assert_visual_contract(page, report, f"reader_from_handout_{suffix}")
    assert_theme(page, report, f"reader_{suffix}", ".reader-page")
    capture(page, report, f"02-reader-exact-source-{suffix}.png")

    page.get_by_role("button", name="返回知识库", exact=True).click()
    page.get_by_test_id("handout-workspace").wait_for(state="visible")
    assert page.url.startswith(handout_url(base_url))


def exercise_chat_round_trip(
    page: Page,
    base_url: str,
    report: dict[str, object],
    suffix: str,
) -> None:
    open_chat(page, base_url, COMPLETED_CONVERSATION_ID)
    page.get_by_text("学习率过大时，参数会跨过损失谷底", exact=False).wait_for(state="visible")
    page.get_by_test_id("chat-agent-audit").wait_for(state="visible")
    assert_public_audit(page, status="已完成")
    chat_base.assert_visual(page, report, f"chat_completed_{suffix}")
    assert_theme(page, report, f"chat_completed_{suffix}", '[data-testid="focused-chat-workspace"]')
    capture(page, report, f"03-chat-completed-audit-{suffix}.png")

    page.get_by_test_id("chat-source-list").get_by_role(
        "button", name="查看来源：统一来源讲义", exact=True
    ).click()
    page.locator(".reader-page").wait_for(state="visible")
    page.get_by_text("正在打开原文", exact=True).wait_for(state="hidden")
    assert SOURCE_REF_ID in page.url
    page.get_by_role("button", name="返回知识库", exact=True).click()
    page.get_by_test_id("focused-chat-workspace").wait_for(state="visible")
    assert COMPLETED_CONVERSATION_ID in page.url

    if suffix != "1440x900":
        return
    page.locator(".conversation-item").filter(has_text="失败与历史结果").click()
    page.get_by_text("本次回答仅保留到这里。", exact=True).wait_for(state="visible")
    assert_public_audit(page, status="失败")
    page.get_by_text("历史已完成回答（非本次结果）", exact=True).wait_for(state="visible")
    assert "api_key" not in page.get_by_test_id("chat-agent-audit").inner_text().lower()
    chat_base.assert_visual(page, report, "chat_failed_1440x900")
    assert_theme(page, report, "chat_failed_1440x900", '[data-testid="focused-chat-workspace"]')
    capture(page, report, "04-chat-failed-history-1440x900.png")


def run() -> dict[str, object]:
    clear_output()
    configure_shared_helpers()
    db_path = OUTPUT_DIR / "f7_t05.sqlite3"
    port = chat_base.free_port()
    env = chat_base.runtime_env(db_path, port)
    fixture = seed_fixture(env)
    owner_id = str(fixture["owner_public_id"])
    before: dict[str, object] | None = None
    process: subprocess.Popen | None = None
    report: dict[str, object] = {
        "schema_version": "f7-t05.source-agent-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "checks": {},
        "visual": {},
        "theme": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_requests": [],
        "external_model_called": False,
    }
    try:
        process = chat_base.start_service(env, port)
        before = chat_base.database_state(db_path, owner_id)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in report["viewports"]:
                suffix = f"{width}x{height}"
                context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
                page = context.new_page()
                chat_base.page_diagnostics(page, report)
                chat_base.login(page, base_url)
                exercise_handout_reader_round_trip(page, base_url, report, suffix)
                exercise_chat_round_trip(page, base_url, report, suffix)
                context.close()
            browser.close()

        after = chat_base.database_state(db_path, owner_id)
        assert before is not None
        for key in (
            "learning_events", "profile_snapshots", "generation_tasks", "assessment_attempts",
            "chat_messages", "source_documents", "source_refs", "mastery",
        ):
            assert after[key] == before[key], (key, before, after)
        assert after["integrity"] == "ok"
        assert after["foreign_key_violations"] == 0
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["external_requests"], report["external_requests"]
        report["database"] = {"before": before, "after": after}
        report["status"] = "passed"
        return report
    finally:
        chat_base.stop_service(process, port)
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
            json.dumps({"schema_version": "f7-t05.evidence-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
