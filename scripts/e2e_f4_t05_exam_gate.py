"""F4-T05 desktop E2E for assessment-center boundaries and exam unlocking."""

from __future__ import annotations

import json
import os
import io
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f4_t05_exam_gate"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
BASE_PORT = int(os.getenv("EDUMATRIX_F4_T05_PORT", "8903"))
VIEWPORTS = ((1440, 900), (1366, 768))


def wait_port(port: int, expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", port)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {port} did not reach expected state: {expected}")


def prepare_output() -> None:
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
        "EDUMATRIX_AUTH_SECRET_KEY": "f4-t05-isolated-secret",
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


def seed_fixture(env: dict[str, str], *, unlocked: bool) -> None:
    script = r'''
from datetime import datetime, timedelta
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBGenerationTask, DBLearningEvent, DBPathNode, DBTaskEvent, DBUser,
    SessionLocal, init_db,
)
from app.exam_gate import freeze_exam_gate_snapshot
from app.m5_learning import today_work_items

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    user = db.query(DBUser).filter_by(username="lzz").one()
    today = list(today_work_items(
        db, owner_public_id=user.public_id,
        course_id="demo-course-rag-trust-v1", limit=50,
    ))
    selected = next(item for item in today if item.get("required") is not False)
    snapshot = freeze_exam_gate_snapshot(
        db,
        owner_public_id=user.public_id,
        course_id="demo-course-rag-trust-v1",
        path_id=selected["path_id"],
        task_id=selected["node_id"],
    )
    generation = DBGenerationTask(
        id="f4-t05-gate-job",
        owner_public_id=user.public_id,
        course_id="demo-course-rag-trust-v1",
        trace_id="f4-t05-gate-trace",
        status="completed",
        progress=1,
        capability="learning_resource_bundle.generate",
        idempotency_key="f4-t05-gate-job-key",
    )
    db.add(generation)
    db.flush()
    db.add(DBTaskEvent(
        id="f4-t05-gate-request",
        task_id=generation.id,
        sequence=1,
        event_type="resource_generation.requested",
        payload={"manifest": {"exam_gate": snapshot}},
    ))
    if __UNLOCKED__:
        moment = datetime.utcnow()
        for index, task in enumerate(snapshot["required_tasks"], start=1):
            node = db.get(DBPathNode, task["id"])
            node.status = "completed"
            db.add(DBLearningEvent(
                id=f"f4-t05-evidence-{index}",
                owner_public_id=user.public_id,
                course_id="demo-course-rag-trust-v1",
                event_type="quiz_answered",
                schema_version="m5.learning-event.v1",
                idempotency_key=f"f4-t05-evidence-key-{index}",
                source="backend",
                trace_id=f"f4-t05-evidence-trace-{index}",
                object_type="path_target",
                object_id=node.target_object_id or node.id,
                action="assessment.answered",
                context_ref={
                    "userId": user.public_id,
                    "courseId": "demo-course-rag-trust-v1",
                    "taskId": node.id,
                },
                evidence_strength=0.8,
                evidence_status="accepted",
                evidence_reason="F4-T05 isolated server evidence",
                mastery_eligible=True,
                completion_effect="complete",
                payload_version="1",
                payload={"graded": True, "correct": True, "attempt_id": f"f4-t05-attempt-{index}"},
                occurred_at=moment + timedelta(seconds=index),
            ))
    db.commit()
finally:
    db.close()
'''.replace("__UNLOCKED__", "True" if unlocked else "False")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError(f"fixture seed failed: {result.stdout}\n{result.stderr}")


def login(page: Page, base_url: str) -> None:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": USERNAME, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    state = json.dumps(response.json(), ensure_ascii=False)
    page.add_init_script(
        f"""
        const session = {state};
        localStorage.setItem('edumatrix_token', session.access_token);
        localStorage.setItem('edumatrix_username', session.username || '{USERNAME}');
        localStorage.setItem('edumatrix_display_name', session.display_name || session.username || '{USERNAME}');
        localStorage.setItem('edumatrix_role', session.role || 'student');
        localStorage.setItem('edumatrix_student_id', session.student_id || session.username || '{USERNAME}');
        localStorage.setItem('edumatrix_onboarded', 'true');
        localStorage.setItem('edumatrix_course_id', '{COURSE_ID}');
        localStorage.setItem('edumatrix_course_title', '人工智能与机器学习工程');
        """
    )


def diagnostics(page: Page, report: dict, scope: str) -> None:
    page.on("response", lambda response: report["http_errors"].append({
        "scope": scope, "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "scope": scope, "url": request.url, "failure": request.failure,
    }) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append({"scope": scope, "error": str(error)}))
    page.on("console", lambda message: report["console_errors"].append({
        "scope": scope, "text": message.text,
    }) if message.type == "error" else None)


def visible_metrics(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const visible = (el) => {
            const style = getComputedStyle(el), rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1;
          };
          const controls = [...document.querySelectorAll('button,a[href],input,select,textarea')].filter(visible);
          const collisions = [];
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i], b = controls[j];
            if (a.contains(b) || b.contains(a)) continue;
            const x = a.getBoundingClientRect(), y = b.getBoundingClientRect();
            const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left);
            const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top);
            if (overlapW > 3 && overlapH > 3) collisions.push([
              (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 48),
              (b.innerText || b.getAttribute('aria-label') || '').trim().slice(0, 48),
            ]);
          }
          const clipped = [...document.querySelectorAll('button,a[href],h1,h2,h3,strong,p,span,label')]
            .filter(visible).filter((el) => {
              const style = getComputedStyle(el), rect = el.getBoundingClientRect();
              if (style.textOverflow === 'ellipsis') return false;
              return rect.right > innerWidth + 1 || rect.left < -1 ||
                (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap');
            }).map((el) => (el.innerText || '').trim().slice(0, 80)).filter(Boolean).slice(0, 20);
          const smallText = [...document.querySelectorAll('body *')].filter((el) => {
            return visible(el) && el.children.length === 0 && (el.innerText || '').trim() &&
              Number.parseFloat(getComputedStyle(el).fontSize) < 13.5;
          }).map((el) => ({ text: el.innerText.trim().slice(0, 40), size: getComputedStyle(el).fontSize })).slice(0, 20);
          const builder = document.querySelector('.builder-layout')?.getBoundingClientRect();
          const config = document.querySelector('.exam-config')?.getBoundingClientRect();
          const preview = document.querySelector('.exam-preview')?.getBoundingClientRect();
          const shell = document.querySelector('.app-shell')?.getBoundingClientRect();
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            bodyTextLength: (document.body.innerText || '').trim().length,
            collisions, clipped, smallText,
            shellRect: shell ? {
              x: Math.round(shell.x), y: Math.round(shell.y),
              width: Math.round(shell.width), height: Math.round(shell.height),
            } : null,
            builderSplit: builder && config && preview ? {
              configRatio: Number((config.width / builder.width).toFixed(3)),
              previewRatio: Number((preview.width / builder.width).toFixed(3)),
            } : null,
          };
        }"""
    )


def capture(page: Page, report: dict, name: str, *, expect_split: bool = False) -> None:
    shell = page.locator(".app-shell")
    shell.wait_for(state="visible")
    page.locator(".app-brand").wait_for(state="visible")
    page.locator(".app-nav").get_by_text("学习空间", exact=True).wait_for(state="visible")
    page.wait_for_timeout(700)
    metrics = visible_metrics(page)
    page.screenshot(animations="disabled")
    page.wait_for_timeout(100)
    sidebar_png = page.locator(".app-sidebar").screenshot(animations="disabled")
    frame_png = page.locator(".app-frame").screenshot(animations="disabled")
    with Image.open(io.BytesIO(sidebar_png)) as sidebar, Image.open(io.BytesIO(frame_png)) as frame:
        assert sidebar.height == frame.height == metrics["viewport"][1]
        assert sidebar.width + frame.width == metrics["viewport"][0]
        screenshot = Image.new("RGB", tuple(metrics["viewport"]), "white")
        screenshot.paste(sidebar.convert("RGB"), (0, 0))
        screenshot.paste(frame.convert("RGB"), (sidebar.width, 0))
        screenshot.save(OUTPUT_DIR / name)
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] > 180, metrics
    assert metrics["shellRect"] == {
        "x": 0, "y": 0,
        "width": metrics["viewport"][0], "height": metrics["viewport"][1],
    }, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    if expect_split:
        assert metrics["builderSplit"], metrics
        assert 0.32 <= metrics["builderSplit"]["configRatio"] <= 0.38, metrics


def answer_and_submit(page: Page) -> None:
    page.get_by_role("button", name="开始作答").click()
    page.get_by_role("button", name="提交试卷").wait_for(state="visible")
    articles = page.locator(".question-paper > article")
    assert articles.count() > 0
    for index in range(articles.count()):
        article = articles.nth(index)
        if article.locator(".binary-options").count():
            article.locator(".binary-options button").first.click()
        elif article.locator("select").count():
            article.locator("select").select_option(index=1)
        else:
            article.locator("textarea").fill("结合冻结课程来源完成本题作答。")
        article.get_by_role("button", name="保存本题").click()
        article.get_by_text("答案已保存", exact=True).wait_for(state="visible")
    page.get_by_role("button", name="提交试卷").click()
    page.get_by_test_id("formal-exam-report").wait_for(state="visible", timeout=30_000)


def run_scenario(db_path: Path, port: int, scenario: str, report: dict) -> None:
    env = runtime_env(db_path, port)
    seed_fixture(env, unlocked=scenario == "unlocked")
    base_url = f"http://127.0.0.1:{port}"
    process = None
    try:
        with (OUTPUT_DIR / f"backend-{scenario}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(port, True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                for width, height in VIEWPORTS:
                    context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
                    page = context.new_page()
                    page.set_default_timeout(30_000)
                    diagnostics(page, report, f"{scenario}-{width}x{height}")
                    login(page, base_url)
                    if scenario == "locked":
                        page.goto(f"{base_url}/workspace/assessment?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
                        page.get_by_test_id("assessment-center").wait_for(state="visible")
                        assert page.get_by_test_id("assessment-center").get_by_role("button").count() == 2
                        capture(page, report, f"locked-center-{width}x{height}.png")
                        page.get_by_test_id("intelligent-exam-entry").click()
                        page.get_by_test_id("exam-gate-locked").wait_for(state="visible")
                        assert page.get_by_text("可选资源不会阻塞解锁", exact=False).is_visible()
                        assert page.locator(".missing-list > button").count() > 0
                        capture(page, report, f"locked-gate-{width}x{height}.png")
                    else:
                        page.goto(f"{base_url}/workspace/assessment/exams?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
                        page.get_by_test_id("exam-builder-unlocked").wait_for(state="visible")
                        capture(page, report, f"unlocked-builder-{width}x{height}.png", expect_split=True)
                        if width == 1440:
                            page.get_by_role("button", name="生成并冻结试卷").click()
                            page.get_by_test_id("exam-taking").wait_for(state="visible", timeout=30_000)
                            capture(page, report, "unlocked-exam-created-1440x900.png")
                            answer_and_submit(page)
                            capture(page, report, "unlocked-report-1440x900.png")
                    context.close()
                browser.close()
        with sqlite3.connect(db_path, timeout=10) as db:
            report["database_audit"][scenario] = {
                "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
                "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
                "self_generated_exams": db.execute(
                    "SELECT COUNT(*) FROM assessment_exams WHERE owner_public_id=(SELECT public_id FROM users WHERE username=?)",
                    (USERNAME,),
                ).fetchone()[0],
                "reports": db.execute("SELECT COUNT(*) FROM assessment_exam_reports").fetchone()[0],
            }
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
            process.wait(timeout=5)
            wait_port(port, False, 15)
        report["process_cleanup"][scenario] = process is None or process.poll() is not None


def main() -> int:
    prepare_output()
    report = {
        "schema_version": "f4-t05.exam-gate-desktop.v1",
        "viewports": [list(item) for item in VIEWPORTS],
        "screenshots": [],
        "checks": {},
        "database_audit": {},
        "process_cleanup": {},
        "http_errors": [],
        "failed_requests": [],
        "console_errors": [],
        "page_errors": [],
        "result": "failed",
    }
    try:
        run_scenario(OUTPUT_DIR / "locked-runtime.db", BASE_PORT, "locked", report)
        run_scenario(OUTPUT_DIR / "unlocked-runtime.db", BASE_PORT + 1, "unlocked", report)
        assert all(item == {"integrity": "ok", "foreign_key_violations": 0, "self_generated_exams": 0, "reports": 0}
                   for key, item in report["database_audit"].items() if key == "locked")
        unlocked = report["database_audit"]["unlocked"]
        assert unlocked["integrity"] == "ok" and unlocked["foreign_key_violations"] == 0
        assert unlocked["self_generated_exams"] == 1 and unlocked["reports"] == 1
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["page_errors"], report["page_errors"]
        assert all(report["process_cleanup"].values())
        report["result"] = "passed"
    except Exception as exc:
        report["failure"] = repr(exc)
        report["traceback"] = traceback.format_exc()
    finally:
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({"result": report["result"], "failure": report.get("failure"), "cleanup": report["process_cleanup"]}, ensure_ascii=False))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
