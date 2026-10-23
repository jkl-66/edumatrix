"""真实浏览器证据：旧版资源工厂恢复到当前结构化资源工作区。"""

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
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "RESOURCE-LEGACY-RESTORE-01" / "browser"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_port(port: int, expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            if (sock.connect_ex(("127.0.0.1", port)) == 0) is expected:
                return
        time.sleep(0.2)
    raise RuntimeError(f"port {port} did not reach expected state {expected}")


def runtime_env(db_path: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(db_path),
        "EDUMATRIX_AUTH_SECRET_KEY": "resource-legacy-restore-isolated",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_SANDBOX_MODE": "trusted_local",
        "EDUMATRIX_ENV": "development",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(port),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def seed_fixture(env: dict[str, str], fixture_path: Path) -> None:
    script = f'''
import json
from pathlib import Path
from app.competition_demo_seed import seed_competition_demo
from app.database import DBArtifact, DBArtifactVersion, DBProfileSnapshot, DBSourceRef, DBUser, SessionLocal, init_db
from app.resource_bundles import create_generation_job, execute_generation_job_demo

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    learner = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    profile = db.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
    source = db.get(DBSourceRef, "demo-ref-07")
    if profile is None or source is None:
        raise RuntimeError("competition demo profile/source missing")
    job = create_generation_job(
        db, learner, course_id={COURSE_ID!r}, knowledge_point_id="demo-kp-07",
        profile_snapshot_id=profile.id, idempotency_key="resource-legacy-restore-browser-001",
        scope="bundle", learning_goal="理解混合检索的权衡并能用代码检查召回与重排",
        items=[
            {{"type": "handout", "title": "旧版能力恢复·个性化讲义", "source_ref_ids": [source.id], "completion_rule": "完成讲义阅读和三道学习检查。"}},
            {{"type": "mind_map", "title": "旧版能力恢复·知识导图", "source_ref_ids": [source.id], "completion_rule": "展开核心分支并说明一条关系。"}},
            {{"type": "quiz", "title": "旧版能力恢复·分层测验", "source_ref_ids": [source.id], "completion_rule": "三道必做题均至少答对一次。"}},
            {{"type": "code_sandbox", "title": "旧版能力恢复·代码实操", "source_ref_ids": [source.id], "completion_rule": "完成一次通过全部必需检查的真实运行。"}},
        ],
    )
    db.commit()
    result = execute_generation_job_demo(db, learner, job["job_id"])
    db.commit()
    fixture = {{"job_id": job["job_id"], "items": {{}}}}
    for item in result.get("items") or []:
        resource = item.get("resource") or {{}}
        if item.get("type") and resource.get("resource_id"):
            fixture["items"][item["type"]] = resource["resource_id"]
    if set(fixture["items"]) != {{"handout", "mind_map", "quiz", "code_sandbox"}}:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    Path({str(fixture_path)!r}).write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    completed = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    if completed.returncode:
        raise RuntimeError(f"fixture seed failed:\n{completed.stdout}\n{completed.stderr}")


def login(page: Page, base_url: str) -> None:
    response = page.request.post(f"{base_url}/api/auth/login", form={"username": USERNAME, "password": PASSWORD})
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    session = response.json()
    state = json.dumps(session, ensure_ascii=False)
    page.add_init_script(f"""
      const session = {state};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_display_name', session.display_name || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_role', session.role || 'student');
      localStorage.setItem('edumatrix_student_id', session.student_id || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', '{COURSE_ID}');
      localStorage.setItem('edumatrix_course_title', '人工智能与机器学习工程');
    """)


def diagnostics(page: Page, report: dict) -> None:
    page.on("response", lambda response: report["http_errors"].append({"status": response.status, "url": response.url}) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({"url": request.url, "failure": request.failure}) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def capture(page: Page, report: dict, name: str, selector: str, required: list[str]) -> None:
    root = page.locator(selector)
    root.wait_for(state="visible", timeout=30_000)
    body_text = root.inner_text()
    for text in required:
        assert text in body_text, f"{text!r} not visible in {name}"
    page.wait_for_timeout(450)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["visible_text"][name] = {"length": len(body_text), "required": required}


def open_resource(page: Page, base_url: str, route: str, resource_id: str, selector: str) -> None:
    page.goto(f"{base_url}{route}/{resource_id}?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.locator(selector).wait_for(state="visible", timeout=30_000)


def database_audit(db_path: Path) -> dict:
    with sqlite3.connect(db_path, timeout=10) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "artifact_versions": db.execute("SELECT COUNT(*) FROM artifact_versions").fetchone()[0],
            "learning_events": db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
        }


def run() -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        else:
            shutil.rmtree(item)
    db_path = OUTPUT_DIR / "resource_legacy_restore.sqlite3"
    fixture_path = OUTPUT_DIR / "fixture.json"
    port = free_port()
    env = runtime_env(db_path, port)
    seed_fixture(env, fixture_path)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    log_path = OUTPUT_DIR / "server.log"
    log = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    report = {
        "schema_version": "resource-legacy-restore.browser.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [], "visible_text": {}, "http_errors": [], "failed_requests": [], "page_errors": [], "console_errors": [],
        "fixture": fixture,
    }
    try:
        wait_port(port, True)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            diagnostics(page, report)
            login(page, base_url)
            ids = fixture["items"]
            open_resource(page, base_url, "/workspace/resources/handouts", ids["handout"], '[data-testid="handout-workspace"]')
            capture(page, report, "01-handout-rich-1440x900.png", '[data-testid="handout-workspace"]', ["前置概念与最小案例", "核心机制拆解", "Worked example：从条件到结果", "闭卷检索与迁移", "常见误区：相关不等于适用", "机制检查：可运行最小示例", "学习检查 1"])
            page.locator(".outline-panel nav button").filter(has_text="Worked example").click()
            capture(page, report, "01b-handout-example-1440x900.png", '[data-testid="handout-workspace"]', ["Worked example：从条件到结果", "先写出问题条件", "独立检查"])
            page.locator(".outline-panel nav button").filter(has_text="代码阅读").click()
            capture(page, report, "01c-handout-code-reading-1440x900.png", '[data-testid="handout-workspace"]', ["机制检查：可运行最小示例", "def inspect_mechanism", "这是可直接运行的最小检查器"])
            page.locator(".outline-panel nav button").filter(has_text="学习检查 1").click()
            capture(page, report, "01d-handout-quiz-1440x900.png", '[data-testid="handout-workspace"]', ["学习检查 1", "同时说明条件、机制和验证方法", "检查答案"])

            open_resource(page, base_url, "/workspace/resources/mindmaps", ids["mind_map"], '[data-testid="mindmap-workspace"]')
            assert page.locator('[aria-label="节点详情"]').is_visible()
            capture(page, report, "02-mindmap-restored-1440x900.png", '[data-testid="mindmap-workspace"]', ["关键机制", "应用与反例"])

            open_resource(page, base_url, "/workspace/resources/quizzes", ids["quiz"], '[data-testid="quiz-resource-workspace"]')
            capture(page, report, "03-quiz-layered-1440x900.png", '[data-testid="quiz-resource-workspace"]', ["第 1 题", "第 2 题", "第 3 题", "必做题"])
            option = page.locator(".option-list label").first
            option.click()
            page.get_by_role("button", name="提交答案", exact=True).click()
            page.get_by_text("回答正确", exact=False).or_(page.get_by_text("这次还不正确", exact=False)).first.wait_for(state="visible", timeout=30_000)
            capture(page, report, "04-quiz-feedback-1440x900.png", '[data-testid="quiz-resource-workspace"]', ["解析", "本题作答历史"])

            open_resource(page, base_url, "/workspace/code", ids["code_sandbox"], '[data-testid="code-sandbox-workspace"]')
            try:
                page.get_by_text("标准输入", exact=True).wait_for(state="visible", timeout=30_000)
            except Exception:
                (OUTPUT_DIR / "debug-code-body.txt").write_text(page.locator('[data-testid="code-sandbox-workspace"]').inner_text(), encoding="utf-8")
                page.screenshot(path=str(OUTPUT_DIR / "debug-code-page.png"), full_page=True, animations="disabled")
                raise
            capture(page, report, "05-code-complete-1440x900.png", '[data-testid="code-sandbox-workspace"]', ["标准输入", "必需检查", "运行代码"])
            page.get_by_role("button", name="运行代码", exact=True).click()
            page.get_by_text("运行成功", exact=False).first.wait_for(state="visible", timeout=30_000)
            capture(page, report, "06-code-real-output-1440x900.png", '[data-testid="code-sandbox-workspace"]', ["validation_accuracy=", "confusion_matrix="])
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768})
            page = context.new_page()
            diagnostics(page, report)
            login(page, base_url)
            open_resource(page, base_url, "/workspace/resources/handouts", ids["handout"], '[data-testid="handout-workspace"]')
            capture(page, report, "07-handout-rich-1366x768.png", '[data-testid="handout-workspace"]', ["前置概念与最小案例", "闭卷检索与迁移", "学习检查 3"])
            context.close()
            browser.close()
        report["database"] = database_audit(db_path)
        assert report["database"]["integrity"] == "ok"
        assert report["database"]["foreign_key_violations"] == 0
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        if process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
        wait_port(port, False, timeout=20)


if __name__ == "__main__":
    result = run()
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    (OUTPUT_DIR / "browser_report.json").write_text(payload, encoding="utf-8")
    (OUTPUT_DIR / "browser_report.sha256").write_text(hashlib.sha256(payload.encode("utf-8")).hexdigest() + "\n", encoding="ascii")
    print(payload)
