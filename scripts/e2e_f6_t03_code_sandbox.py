"""F6-T03 canonical code-sandbox desktop E2E on isolated SQLite."""

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
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f6_t03_code_sandbox"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
PORT_START = int(os.getenv("EDUMATRIX_F6_T03_PORT", "8993"))


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F6-T03 E2E port")


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
        "EDUMATRIX_AUTH_SECRET_KEY": "f6-t03-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_SANDBOX_MODE": "trusted_local",
        "EDUMATRIX_SANDBOX_TIMEOUT": "10",
        "EDUMATRIX_SANDBOX_MAX_OUTPUT_BYTES": "100000",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(port),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def seed_fixture(env: dict[str, str]) -> dict[str, str | int]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import json
from pathlib import Path
from app.competition_demo_seed import seed_competition_demo
from app.database import DBArtifact, DBArtifactVersion, DBProfileSnapshot, DBSourceRef, DBUser, SessionLocal, init_db
from app.m5_resources import ResourceVersionCreateRequest, create_resource_version
from app.resource_bundles import create_generation_job, execute_generation_job_demo

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    learner = db.query(DBUser).filter_by(username={USERNAME!r}).one()
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
        idempotency_key="f6-t03-browser-fixture-001",
        scope="single",
        items=[{{
            "type": "code_sandbox",
            "title": "分类阈值代码实训",
            "source_ref_ids": [source.id],
            "completion_rule": "保存代码，完成一次通过全部必需检查的真实运行，再明确提交完成。",
        }}],
        learning_goal="通过真实代码运行理解分类阈值、混淆矩阵和误差边界",
    )
    db.commit()
    result = execute_generation_job_demo(db, learner, job["job_id"])
    db.commit()
    resource_id = result["items"][0]["resource"]["resource_id"]
    artifact = db.get(DBArtifact, resource_id)
    original = db.get(DBArtifactVersion, artifact.current_version_id)
    revised = json.loads(original.content)
    revised["summary"] = "调整分类阈值，核对准确率、混淆矩阵与阈值图表。"
    detail = create_resource_version(
        db,
        artifact=artifact,
        actor_public_id=learner.public_id,
        request=ResourceVersionCreateRequest(
            expected_lock_version=artifact.lock_version,
            source_version_id=original.id,
            content=json.dumps(revised, ensure_ascii=False),
            content_format="json",
        ),
    )
    db.commit()
    payload = {{
        "resource_id": resource_id,
        "owner_public_id": learner.public_id,
        "current_version_id": detail["code_sandbox"]["current_version_id"],
        "initial_version_count": len(detail["code_sandbox"]["versions"]),
    }}
    Path({str(fixture_path)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=120)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def start_service(env: dict[str, str], port: int) -> subprocess.Popen:
    log = (OUTPUT_DIR / "server.log").open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "run.py"], cwd=ROOT, env=env,
        stdout=log, stderr=subprocess.STDOUT,
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
            capture_output=True, timeout=20,
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


def database_state(db_path: Path, fixture: dict[str, str | int]) -> dict[str, int | str]:
    with sqlite3.connect(db_path, timeout=10) as db:
        resource_id = str(fixture["resource_id"])
        owner = str(fixture["owner_public_id"])
        return {
            "completion_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=? AND event_type='code_tests_passed' AND object_id=?",
                (owner, resource_id),
            ).fetchone()[0],
            "resource_versions": db.execute(
                "SELECT COUNT(*) FROM artifact_versions WHERE artifact_id=?",
                (resource_id,),
            ).fetchone()[0],
            "run_artifacts": db.execute(
                "SELECT COUNT(*) FROM artifacts WHERE owner_public_id=? AND artifact_type='code_sandbox_run'",
                (owner,),
            ).fetchone()[0],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def page_diagnostics(page: Page, report: dict) -> None:
    page.on("response", lambda response: report["http_errors"].append({
        "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url, "failure": request.failure,
    }))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def capture(page: Page, report: dict, filename: str) -> None:
    path = OUTPUT_DIR / filename
    page.screenshot(path=path, full_page=True)
    report["screenshots"].append(filename)


def open_sandbox(page: Page, base_url: str, resource_id: str) -> None:
    page.goto(
        f"{base_url}/workspace/code/{resource_id}?course_id={COURSE_ID}",
        wait_until="networkidle", timeout=60_000,
    )
    page.get_by_test_id("code-sandbox-workspace").wait_for(state="visible")
    page.get_by_test_id("monaco-editor").locator(".monaco-editor").wait_for(state="visible")


def assert_three_columns(page: Page) -> list[float]:
    values = page.locator(".sandbox-grid").evaluate("""element =>
      getComputedStyle(element).gridTemplateColumns.split(' ').map(value => Number.parseFloat(value))
    """)
    assert len(values) == 3
    total = sum(values)
    ratios = [round(value / total, 2) for value in values]
    assert ratios == [0.22, 0.5, 0.28], ratios
    return ratios


def exercise_primary_flow(
    page: Page,
    base_url: str,
    fixture: dict[str, str | int],
    db_path: Path,
    report: dict,
) -> None:
    open_sandbox(page, base_url, str(fixture["resource_id"]))
    report["checks"]["grid_ratios"] = assert_three_columns(page)
    assert page.get_by_text("本地研究模式", exact=True).is_visible()
    assert page.get_by_text("不具备 Docker 容器隔离", exact=False).is_visible()
    assert database_state(db_path, fixture)["completion_events"] == 0
    capture(page, report, "01-code-sandbox-1440x900.png")

    standard_input = page.locator(".stdin-panel textarea")
    standard_input.fill("0.60")
    assert standard_input.input_value() == "0.60"
    save_button = page.get_by_role("button", name="保存新版本", exact=True)
    assert save_button.is_enabled()
    save_button.click()
    page.get_by_text("代码和标准输入已另存为新版本。请基于新版本重新运行。", exact=True).wait_for(state="visible")
    assert database_state(db_path, fixture)["resource_versions"] == int(fixture["initial_version_count"]) + 1

    page.get_by_role("button", name="运行代码", exact=True).click()
    page.locator(".result-summary").get_by_text("运行成功", exact=True).wait_for(state="visible", timeout=60_000)
    terminal_output = page.locator(".terminal-output")
    terminal_output.wait_for(state="visible")
    assert "threshold=0.60" in terminal_output.inner_text()
    assert "validation_accuracy=" in terminal_output.inner_text()
    assert database_state(db_path, fixture)["completion_events"] == 0
    assert database_state(db_path, fixture)["run_artifacts"] == 1

    page.get_by_role("button", name="图表", exact=False).click()
    plot = page.locator(".plot-viewer img")
    plot.wait_for(state="visible")
    assert plot.evaluate("image => image.naturalWidth > 0 && image.naturalHeight > 0")
    capture(page, report, "02-real-run-and-plot-1440x900.png")

    page.get_by_role("button", name="AI 点评", exact=True).click()
    page.get_by_text("真实证据已就绪", exact=True).wait_for(state="visible")
    review_panel = page.get_by_test_id("code-review-panel")
    assert review_panel.get_by_text("runAttemptId", exact=False).count() >= 1
    report["checks"]["review_run_attempt"] = "visible_and_bound"

    page.get_by_role("button", name="完成学习", exact=True).click()
    page.get_by_text("完成证据已记录，画像、路径和今日任务会读取同一条学习事件。", exact=True).wait_for(state="visible")
    assert database_state(db_path, fixture)["completion_events"] == 1
    capture(page, report, "03-completion-recorded-1440x900.png")

    page.reload(wait_until="networkidle")
    page.get_by_test_id("monaco-editor").locator(".monaco-editor").wait_for(state="visible")
    page.get_by_text("本次学习已完成", exact=True).wait_for(state="visible")
    assert page.locator(".stdin-panel textarea").input_value() == "0.60"
    assert database_state(db_path, fixture)["completion_events"] == 1
    report["checks"]["refresh_restored"] = True


def exercise_secondary_viewport(page: Page, base_url: str, fixture: dict[str, str | int], report: dict) -> None:
    open_sandbox(page, base_url, str(fixture["resource_id"]))
    report["checks"]["secondary_grid_ratios"] = assert_three_columns(page)
    boxes = [page.locator(selector).bounding_box() for selector in (".left-panel", ".editor-panel", ".result-panel")]
    assert all(box and box["width"] > 210 for box in boxes), boxes
    assert page.get_by_role("button", name="运行代码", exact=True).is_visible()
    capture(page, report, "04-code-sandbox-1366x768.png")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def run() -> dict:
    clear_output()
    db_path = OUTPUT_DIR / "f6_t03.sqlite3"
    port = free_port()
    env = runtime_env(db_path, port)
    fixture = seed_fixture(env)
    process: subprocess.Popen | None = None
    report = {
        "schema_version": "f6-t03.code-sandbox-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [], "checks": {},
        "http_errors": [], "failed_requests": [], "page_errors": [], "console_errors": [],
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
            exercise_primary_flow(page, base_url, fixture, db_path, report)
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            login(page, base_url)
            exercise_secondary_viewport(page, base_url, fixture, report)
            context.close()
            browser.close()
        report["database"] = database_state(db_path, fixture)
        assert report["database"]["completion_events"] == 1
        assert report["database"]["resource_versions"] == int(fixture["initial_version_count"]) + 1
        assert report["database"]["run_artifacts"] == 1
        assert report["database"]["integrity"] == "ok"
        assert report["database"]["foreign_key_violations"] == 0
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        stop_service(process, port)
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
            json.dumps({"schema_version": "f6-t03.evidence-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
