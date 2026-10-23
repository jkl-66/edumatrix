"""F6-T05 five-stage Feynman workspace E2E on isolated SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, Route, sync_playwright

import e2e_f6_t03_code_sandbox as base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f6_t05_feynman"
COURSE_ID = "demo-course-rag-trust-v1"
ROUND1 = (
    "混合检索要解决的是单一检索方式容易漏掉资料的问题。它先分别进行关键词检索和向量检索，"
    "然后把两路候选结果合并并重新排序。例如查找课程中的专业缩写时，关键词能够精确命中，"
    "向量检索能补充语义相近内容。但是如果课程来源没有被正确解析，最终结果仍可能缺少依据。"
)
ROUND2 = (
    "混合检索的核心含义是同时利用词面匹配和语义匹配。前提是课程文档已经解析并建立索引。"
    "执行时先用关键词检索找到精确术语，再用向量检索扩展语义候选，随后合并、去重并重排。"
    "例如学习者查询 RAG 评测时，两路结果可以同时覆盖术语定义和相关案例。反例是来源缺失或"
    "索引过期，此时不能把低质量候选当成可靠答案，必须回到来源检查。"
)
QUESTION = "为什么课程来源没有正确解析时，混合检索仍然不能保证结果可靠？"


def seed_fixture(env: dict[str, str]) -> dict[str, str]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import json
from pathlib import Path
from app.competition_demo_seed import seed_competition_demo
from app.database import DBProfileSnapshot, DBSourceRef, DBUser, SessionLocal, init_db
from app.resource_bundles import create_generation_job, execute_generation_job_demo

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    learner = db.query(DBUser).filter_by(username="lzz").one()
    profile = db.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
    source = db.get(DBSourceRef, "demo-ref-07")
    if profile is None or source is None:
        raise RuntimeError("competition demo profile or source is missing")
    job = create_generation_job(
        db,
        learner,
        course_id={COURSE_ID!r},
        knowledge_point_id="demo-kp-07",
        profile_snapshot_id=profile.id,
        idempotency_key="f6-t05-browser-fixture-001",
        scope="single",
        items=[{{
            "type": "feynman",
            "title": "混合检索费曼复述",
            "source_ref_ids": [source.id],
            "completion_rule": "完成两轮复述、真实疑问和理解对比后，再应用到后续学习。",
        }}],
        learning_goal="说明混合检索的机制、成立条件、例子和边界",
    )
    db.commit()
    result = execute_generation_job_demo(db, learner, job["job_id"])
    db.commit()
    payload = {{
        "resource_id": result["items"][0]["resource"]["resource_id"],
        "owner_public_id": learner.public_id,
        "source_ref_id": source.id,
    }}
    Path({str(fixture_path)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=120)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def database_state(db_path: Path, fixture: dict[str, str]) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        owner = fixture["owner_public_id"]
        resource_id = fixture["resource_id"]
        session_rows = db.execute(
            "SELECT id, current_version_id FROM artifacts "
            "WHERE owner_public_id=? AND artifact_type='feynman_session' ORDER BY created_at",
            (owner,),
        ).fetchall()
        versions = {
            session_id: db.execute(
                "SELECT COUNT(*) FROM artifact_versions WHERE artifact_id=?",
                (session_id,),
            ).fetchone()[0]
            for session_id, _ in session_rows
        }
        events = db.execute(
            "SELECT id, payload FROM learning_events WHERE owner_public_id=? "
            "AND event_type='feynman_submitted' AND object_id=?",
            (owner, resource_id),
        ).fetchall()
        return {
            "session_count": len(session_rows),
            "session_versions": versions,
            "event_count": len(events),
            "event_payloads": [json.loads(row[1]) for row in events],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def capture(page: Page, report: dict, filename: str) -> None:
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=OUTPUT_DIR / filename, full_page=True)
    report["screenshots"].append(filename)


def page_diagnostics(page: Page, report: dict) -> None:
    def on_response(response) -> None:
        if response.status < 400:
            return
        if response.status == 503 and "/api/v1/feynman/" in response.url:
            report["expected_injected_failures"].append({"status": response.status, "url": response.url})
            return
        report["http_errors"].append({"status": response.status, "url": response.url})

    page.on("response", on_response)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url, "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    def on_console(message) -> None:
        if message.type != "error":
            return
        if "503 (Service Unavailable)" in message.text:
            report["expected_injected_console"].append(message.text)
            return
        report["console_errors"].append(message.text)

    page.on("console", on_console)


def visual_contract(page: Page) -> dict[str, object]:
    return page.evaluate("""
      () => {
        const root = document.querySelector('.feynman-page')
        const visible = element => {
          const style = getComputedStyle(element)
          const box = element.getBoundingClientRect()
          return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0
        }
        const textNodes = [...root.querySelectorAll(
          'button, h1, h2, h3, p, span, strong, small, label, summary, dt, dd, li'
        )].filter(element => visible(element) && element.textContent.trim())
        const smallText = textNodes
          .filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 13.9)
          .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 80), size: getComputedStyle(element).fontSize }))
        const clippedText = textNodes
          .filter(element => {
            const style = getComputedStyle(element)
            if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
            if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
            return element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1
          })
          .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 80) }))
        const decorated = [...root.querySelectorAll('*')]
          .filter(element => visible(element))
          .map(element => getComputedStyle(element).backgroundImage)
          .filter(value => value && value !== 'none')
        const main = root.querySelector('.main-workspace')?.getBoundingClientRect()
        const rail = root.querySelector('.context-rail')?.getBoundingClientRect()
        const overlap = main && rail
          ? !(main.right <= rail.left + 1 || rail.right <= main.left + 1 || main.bottom <= rail.top + 1 || rail.bottom <= main.top + 1)
          : false
        return {
          pageOverflow: root.scrollWidth > root.clientWidth + 1,
          workspaceOverlap: overlap,
          smallText,
          clippedText,
          decorativeBackgroundImages: decorated,
        }
      }
    """)


def assert_visual_contract(page: Page, report: dict, key: str) -> None:
    result = visual_contract(page)
    report["visual"][key] = result
    assert result["pageOverflow"] is False, result
    assert result["workspaceOverlap"] is False, result
    assert result["smallText"] == [], result
    assert result["clippedText"] == [], result
    assert result["decorativeBackgroundImages"] == [], result


def open_workspace(page: Page, base_url: str, resource_id: str, session_id: str = "") -> None:
    suffix = f"&session_id={session_id}" if session_id else ""
    page.goto(
        f"{base_url}/workspace/feynman/{resource_id}?course_id={COURSE_ID}{suffix}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.get_by_role("heading", name="五阶段进度", exact=True).wait_for(state="visible")


def inject_one_evaluation_failure(page: Page) -> None:
    state = {"used": False}

    def handler(route: Route) -> None:
        data = route.request.post_data_json or {}
        if not state["used"] and data.get("action") == "evaluate_round1":
            state["used"] = True
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": {"code": "injected", "message": "注入评价失败"}}, ensure_ascii=False),
            )
            return
        route.continue_()

    page.route("**/api/v1/feynman/sessions/*/actions", handler)


def complete_journey(
    page: Page,
    base_url: str,
    fixture: dict[str, str],
    db_path: Path,
    report: dict,
) -> str:
    open_workspace(page, base_url, fixture["resource_id"])
    page.get_by_role("heading", name="第一次复述", exact=True).wait_for(state="visible")
    speech_button = page.get_by_role("button", name="语音输入", exact=True)
    speech_count = speech_button.count()
    assert speech_count in {0, 1}
    if speech_count:
        assert speech_button.is_visible()
        assert speech_button.get_attribute("title") == "使用浏览器语音输入"
    report["checks"]["speech_optional"] = "available" if speech_count else "absent"
    assert_visual_contract(page, report, "draft_1440x900")
    capture(page, report, "01-draft-1440x900.png")

    page.get_by_label("用自己的话复述").fill(ROUND1)
    page.get_by_role("button", name="保存第一次复述", exact=True).click()
    page.get_by_text("第一次原始复述", exact=True).wait_for(state="visible")
    assert database_state(db_path, fixture)["event_count"] == 0

    inject_one_evaluation_failure(page)
    page.get_by_role("button", name="生成第一次评价", exact=True).click()
    page.get_by_text("注入评价失败", exact=False).wait_for(state="visible")
    assert page.get_by_text(ROUND1, exact=True).is_visible()
    assert page.get_by_role("button", name="生成第一次评价", exact=True).is_visible()
    report["checks"]["failed_evaluation_preserved_stage"] = True
    page.get_by_role("button", name="生成第一次评价", exact=True).click()
    page.get_by_role("heading", name="第一次评价", exact=True).wait_for(state="visible")
    capture(page, report, "02-first-review-1440x900.png")

    page.get_by_role("button", name="进入真实疑问", exact=True).click()
    question = page.get_by_label("我仍然不明白")
    question.fill(QUESTION)
    page.reload(wait_until="networkidle", timeout=60_000)
    page.get_by_role("heading", name="提出真实疑问", exact=True).wait_for(state="visible")
    assert page.get_by_label("我仍然不明白").input_value() == QUESTION
    report["checks"]["question_draft_survived_refresh"] = True
    page.get_by_role("button", name="提交疑问并查看回答", exact=True).click()
    page.get_by_text("基于课程来源的回答", exact=True).wait_for(state="visible")
    page.get_by_text("本地确定性、来源约束", exact=False).first.wait_for(state="visible")
    capture(page, report, "03-grounded-question-1440x900.png")

    page.get_by_label("重新组织你的理解").fill(ROUND2)
    page.get_by_role("button", name="保存第二次复述", exact=True).click()
    page.get_by_text("第二次原始复述", exact=True).wait_for(state="visible")
    page.get_by_role("button", name="生成第二次评价与对比", exact=True).click()
    page.get_by_role("heading", name="理解变化", exact=True).wait_for(state="visible")
    page.get_by_text("比较只读取两次已保存评价", exact=False).wait_for(state="visible")
    assert_visual_contract(page, report, "comparison_1440x900")
    capture(page, report, "04-comparison-1440x900.png")

    session_id = page.url.split("session_id=", 1)[1].split("&", 1)[0]
    assert database_state(db_path, fixture)["event_count"] == 0
    page.get_by_role("button", name="应用到后续学习", exact=True).click()
    page.get_by_role("heading", name="已应用到后续学习", exact=True).wait_for(state="visible")
    assert database_state(db_path, fixture)["event_count"] == 1
    capture(page, report, "05-applied-1440x900.png")

    page.get_by_role("button", name="新建复述", exact=True).click()
    page.get_by_role("heading", name="第一次复述", exact=True).wait_for(state="visible")
    page.locator(".context-rail details").filter(has_text="复述历史").locator("summary").click()
    assert page.locator(".history-list button").count() == 2
    assert database_state(db_path, fixture)["event_count"] == 1
    report["checks"]["new_attempt_preserved_history"] = True
    capture(page, report, "06-new-attempt-history-1440x900.png")
    return session_id


def verify_secondary_viewport(
    page: Page,
    base_url: str,
    fixture: dict[str, str],
    session_id: str,
    report: dict,
) -> None:
    open_workspace(page, base_url, fixture["resource_id"], session_id)
    page.get_by_role("heading", name="已应用到后续学习", exact=True).wait_for(state="visible")
    assert_visual_contract(page, report, "applied_1366x768")
    capture(page, report, "07-applied-1366x768.png")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def run() -> dict:
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = 8995
    base.clear_output()
    db_path = OUTPUT_DIR / "f6_t05.sqlite3"
    port = base.free_port()
    env = base.runtime_env(db_path, port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "f6-t05-isolated-secret"
    fixture = seed_fixture(env)
    process: subprocess.Popen | None = None
    report = {
        "schema_version": "f6-t05.feynman-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "checks": {},
        "visual": {},
        "expected_injected_failures": [],
        "expected_injected_console": [],
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_model_called": False,
    }
    try:
        process = base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            page.add_init_script("delete window.SpeechRecognition; delete window.webkitSpeechRecognition;")
            page_diagnostics(page, report)
            base.login(page, base_url)
            completed_session_id = complete_journey(page, base_url, fixture, db_path, report)
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            page.add_init_script("delete window.SpeechRecognition; delete window.webkitSpeechRecognition;")
            page_diagnostics(page, report)
            base.login(page, base_url)
            verify_secondary_viewport(page, base_url, fixture, completed_session_id, report)
            context.close()
            browser.close()

        report["database"] = database_state(db_path, fixture)
        assert report["database"]["session_count"] == 2
        assert report["database"]["event_count"] == 1
        assert report["database"]["event_payloads"][0]["source_ref_ids"] == [fixture["source_ref_id"]]
        assert report["database"]["integrity"] == "ok"
        assert report["database"]["foreign_key_violations"] == 0
        assert len(report["expected_injected_failures"]) == 1
        assert len(report["expected_injected_console"]) == 1
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        base.stop_service(process, port)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT_DIR.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT_DIR / "manifest.json").write_text(
            json.dumps(
                {"schema_version": "f6-t05.evidence-manifest.v1", "files": files},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
