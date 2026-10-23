"""F5-T02 nine-resource orchestration E2E with isolated SQLite runtimes."""

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
import traceback
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f5_t02_resource_bundle"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
PORT_START = int(os.getenv("EDUMATRIX_F5_T02_PORT", "8921"))
RESOURCE_TYPES = (
    "handout", "mind_map", "quiz", "training_task", "code_sandbox",
    "video", "deck", "interactive_model", "feynman",
)


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F5-T02 E2E port")


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
        "EDUMATRIX_AUTH_SECRET_KEY": "f5-t02-isolated-secret",
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


def seed_fixture(env: dict[str, str]) -> None:
    script = (
        "from app.competition_demo_seed import seed_competition_demo; "
        "from app.database import SessionLocal, init_db; "
        "init_db(); db=SessionLocal(); seed_competition_demo(db); db.close()"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode:
        raise RuntimeError(f"fixture seed failed:\n{result.stdout}\n{result.stderr}")


def start_service(env: dict[str, str], port: int, log_path: Path) -> subprocess.Popen:
    log = log_path.open("a", encoding="utf-8")
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


def login(page: Page, base_url: str) -> dict[str, str]:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": USERNAME, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    payload = response.json()
    state = json.dumps(payload, ensure_ascii=False)
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
    return payload


def bearer(auth: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['access_token']}"}


def api_post(page: Page, base_url: str, auth: dict[str, str], path: str, body: dict | None = None) -> dict:
    response = page.request.post(f"{base_url}{path}", headers=bearer(auth), data=body)
    if not response.ok:
        raise AssertionError(f"POST {path}: {response.status} {response.text()}")
    return response.json()


def digest_rows(rows: list[tuple]) -> dict[str, object]:
    serialized = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return {"count": len(rows), "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest()}


def learning_state(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        owner = db.execute("SELECT public_id FROM users WHERE username=?", (USERNAME,)).fetchone()[0]
        return {
            "learning_events": digest_rows(db.execute(
                "SELECT id,event_type,evidence_status,evidence_strength,mastery_eligible,completion_effect,payload "
                "FROM learning_events WHERE owner_public_id=? ORDER BY id", (owner,),
            ).fetchall()),
            "profile_snapshots": digest_rows(db.execute(
                "SELECT id,profile_version,snapshot,content_hash FROM profile_snapshots "
                "WHERE owner_public_id=? ORDER BY id", (owner,),
            ).fetchall()),
            "path_nodes": digest_rows(db.execute(
                "SELECT n.id,n.status,n.actual_minutes,n.blocked_reason FROM path_nodes n "
                "JOIN learning_paths p ON p.id=n.learning_path_id "
                "WHERE p.owner_public_id=? ORDER BY n.id", (owner,),
            ).fetchall()),
            "generation_jobs": db.execute(
                "SELECT COUNT(*) FROM generation_tasks WHERE owner_public_id=? "
                "AND capability='learning_resource_bundle.generate'", (owner,),
            ).fetchone()[0],
            "generated_artifacts": db.execute(
                "SELECT COUNT(*) FROM artifacts WHERE owner_public_id=? AND creating_task_id IS NOT NULL", (owner,),
            ).fetchone()[0],
        }


def database_audit(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def page_diagnostics(page: Page, report: dict, expected_execute_failure: dict[str, bool]) -> None:
    def response_handler(response) -> None:
        if response.status < 400:
            return
        record = {"status": response.status, "url": response.url}
        if (
            expected_execute_failure["active"]
            and response.status == 409
            and response.url.endswith("/execute-demo")
        ):
            report["expected_http_errors"].append(record)
        else:
            report["http_errors"].append(record)

    page.on("response", response_handler)
    def failed_request_handler(request) -> None:
        if request.failure in {"net::ERR_ABORTED", "net::ERR_CANCELED"}:
            return
        record = {"url": request.url, "failure": request.failure}
        if expected_execute_failure.get("restart_active") and request.failure == "net::ERR_CONNECTION_REFUSED":
            report["expected_network_errors"].append(record)
        else:
            report["failed_requests"].append(record)

    page.on("requestfailed", failed_request_handler)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: (
        report["expected_console_errors"].append(message.text)
        if expected_execute_failure.get("restart_active") and "ERR_CONNECTION_REFUSED" in message.text
        else report["console_errors"].append(message.text)
    ) if message.type == "error" and not (
        expected_execute_failure["active"] and "status of 409" in message.text
    ) else None)


def visible_metrics(page: Page) -> dict:
    return page.evaluate("""() => {
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
      const forbiddenEffects = [...document.querySelectorAll('body *')].filter(visible).filter((el) => {
        const style = getComputedStyle(el);
        return style.backgroundImage.includes('gradient') ||
          (style.backdropFilter && style.backdropFilter !== 'none');
      }).map((el) => el.className?.toString().slice(0, 80)).slice(0, 20);
      return {
        viewport: [innerWidth, innerHeight],
        documentWidth: document.documentElement.scrollWidth,
        bodyTextLength: (document.body.innerText || '').trim().length,
        collisions, clipped, smallText, forbiddenEffects,
      };
    }""")


def capture(page: Page, report: dict, name: str) -> None:
    page.evaluate("""() => {
      window.scrollTo(0, 0);
      const content = document.querySelector('.app-content');
      if (content) content.scrollTo(0, 0);
    }""")
    page.wait_for_timeout(450)
    metrics = visible_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] > 300, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["forbiddenEffects"], metrics


def select_ready_task(page: Page, base_url: str) -> str:
    page.goto(f"{base_url}/workspace/path?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("path-overview").wait_for(state="visible")
    tasks = page.get_by_test_id("today-knowledge-points").locator("button")
    if tasks.count() < 1:
        raise AssertionError("today knowledge point selector is empty")
    tasks.first.click()
    selected = page.get_by_test_id("selected-knowledge-point")
    selected.wait_for(state="visible")
    action = selected.get_by_role("button", name="一键生成完整资源包")
    action.wait_for(state="visible")
    if action.is_disabled():
        raise AssertionError(f"first today task is not generation-ready: {selected.inner_text()}")
    return tasks.first.inner_text()


def create_from_path(page: Page, report: dict, expected_execute_failure: dict[str, bool]) -> tuple[str, str]:
    expected_execute_failure["active"] = True
    page.route("**/api/v1/resource-bundles/generation-jobs/*/execute-demo", lambda route: route.fulfill(
        status=409, content_type="application/json",
        body=json.dumps({"detail": {
            "code": "resource_generation.demo_disabled",
            "message": "F5-T02 专项验收暂缓自动执行",
        }}, ensure_ascii=False),
    ))
    with page.expect_response(lambda response: (
        response.request.method == "POST"
        and response.url.endswith("/api/v1/resource-bundles/generation-jobs")
    )) as response_info:
        page.get_by_role("button", name="一键生成完整资源包").click()
    response = response_info.value
    assert response.status == 201, response.text()
    payload = response.json()
    job_id = payload["job_id"]
    page.wait_for_url(f"**/workspace/resources/bundles/{job_id}**", timeout=30_000)
    page.get_by_test_id("resource-bundle-workspace").wait_for(state="visible")
    assert page.locator(".resource-row").count() == 9
    report.setdefault("jobs", []).append({
        "job_id": job_id,
        "context": payload["context"],
        "types": [item["type"] for item in payload["items"]],
    })
    return job_id, str(payload["checkpoint"])


def get_job(page: Page, base_url: str, auth: dict[str, str], job_id: str) -> dict:
    response = page.request.get(
        f"{base_url}/api/v1/resource-bundles/generation-jobs/{job_id}",
        headers=bearer(auth),
    )
    if not response.ok:
        raise AssertionError(f"GET job: {response.status} {response.text()}")
    return response.json()


def assert_complete_job(job: dict, preserved_handout_id: str) -> None:
    assert job["status"] == "succeeded", job
    assert [item["type"] for item in job["items"]] == list(RESOURCE_TYPES)
    assert all(item["state"] == "succeeded" for item in job["items"])
    assert len({item["resource"]["resource_id"] for item in job["items"]}) == 9
    handout = next(item for item in job["items"] if item["type"] == "handout")
    assert handout["resource"]["resource_id"] == preserved_handout_id


def run_scenario(name: str, db_path: Path, report: dict) -> None:
    port = free_port()
    env = runtime_env(db_path, port)
    seed_fixture(env)
    before = learning_state(db_path)
    base_url = f"http://127.0.0.1:{port}"
    log_path = OUTPUT_DIR / f"backend-{name}.log"
    process: subprocess.Popen | None = None
    expected_execute_failure = {"active": False, "restart_active": False}
    try:
        process = start_service(env, port, log_path)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page()
                page.set_default_timeout(30_000)
                page_diagnostics(page, report, expected_execute_failure)
                auth = login(page, base_url)
                selected_text = select_ready_task(page, base_url)
                job_id, _ = create_from_path(page, report, expected_execute_failure)
                capture(page, report, f"{name}-01-queued-1440x900.png")

                handout = api_post(
                    page, base_url, auth,
                    f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/handout/complete",
                    {"content": f"# F5-T02 {name} 讲义\n\n用于验证成功资源不会被重试或恢复覆盖。"},
                )
                handout_id = next(
                    item["resource"]["resource_id"] for item in handout["items"]
                    if item["type"] == "handout"
                )

                if name == "retry":
                    api_post(page, base_url, auth, f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/mind_map/start")
                    api_post(
                        page, base_url, auth,
                        f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/mind_map/fail",
                        {"error_code": "f5_t02_injected_failure", "error_message": "思维导图暂时生成失败，请重试此项。"},
                    )
                    page.reload(wait_until="networkidle", timeout=60_000)
                    row = page.get_by_test_id("bundle-item-mind_map")
                    row.get_by_role("button", name="重试此项").wait_for(state="visible")
                    capture(page, report, "retry-02-single-item-failed-1440x900.png")
                    page.unroute("**/api/v1/resource-bundles/generation-jobs/*/execute-demo")
                    expected_execute_failure["active"] = False
                    row.get_by_role("button", name="重试此项").click()
                else:
                    api_post(page, base_url, auth, f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/mind_map/start")
                    api_post(
                        page, base_url, auth,
                        f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/quiz/fail",
                        {"error_code": "f5_t02_interrupted_failure", "error_message": "服务中断前留下的失败项。"},
                    )
                    expected_execute_failure["restart_active"] = True
                    stop_service(process, port)
                    process = start_service(env, port, log_path)
                    page.reload(wait_until="networkidle", timeout=60_000)
                    expected_execute_failure["restart_active"] = False
                    page.get_by_role("button", name="恢复中断项").wait_for(state="visible")
                    capture(page, report, "recovery-02-restored-after-service-restart-1440x900.png")
                    page.unroute("**/api/v1/resource-bundles/generation-jobs/*/execute-demo")
                    expected_execute_failure["active"] = False
                    page.get_by_role("button", name="恢复中断项").click()

                page.get_by_text("完整资源包已就绪", exact=True).wait_for(state="visible", timeout=45_000)
                page.get_by_text("9 / 9 已归档", exact=True).wait_for(state="visible")
                completed = get_job(page, base_url, auth, job_id)
                assert_complete_job(completed, handout_id)
                capture(page, report, f"{name}-03-complete-1440x900.png")

                handout_row = page.get_by_test_id("bundle-item-handout")
                handout_row.get_by_role("button", name="打开").click()
                page.wait_for_url("**/workspace/resources/handouts/**", timeout=30_000)
                assert "/workspace/resources/handouts/" in page.url
                page.go_back(wait_until="networkidle")
                page.get_by_test_id("resource-bundle-workspace").wait_for(state="visible")

                page.get_by_role("button", name="返回今日任务").last.click()
                page.get_by_test_id("path-overview").wait_for(state="visible", timeout=60_000)
                selected = page.get_by_test_id("selected-knowledge-point")
                selected.wait_for(state="visible")
                assert selected_text.splitlines()[0] in selected.inner_text()

                page.goto(
                    f"{base_url}/workspace/resources/bundles/{job_id}?course_id={COURSE_ID}&return_task=demo-task-lzz-read-01",
                    wait_until="networkidle", timeout=60_000,
                )
                page.set_viewport_size({"width": 1366, "height": 768})
                page.reload(wait_until="networkidle", timeout=60_000)
                page.get_by_text("完整资源包已就绪", exact=True).wait_for(state="visible")
                capture(page, report, f"{name}-04-complete-1366x768.png")
                context.close()
            finally:
                browser.close()

        after = learning_state(db_path)
        report.setdefault("scenarios", {})[name] = {
            "state_before": before,
            "state_after": after,
            "learning_events_unchanged": before["learning_events"] == after["learning_events"],
            "profile_snapshots_unchanged": before["profile_snapshots"] == after["profile_snapshots"],
            "path_nodes_unchanged": before["path_nodes"] == after["path_nodes"],
            "one_generation_job": after["generation_jobs"] == before["generation_jobs"] + 1,
            "nine_generated_artifacts": after["generated_artifacts"] == before["generated_artifacts"] + 9,
            "database_audit": database_audit(db_path),
            "service_restart_verified": name == "recovery",
        }
        scenario = report["scenarios"][name]
        assert scenario["learning_events_unchanged"], scenario
        assert scenario["profile_snapshots_unchanged"], scenario
        assert scenario["path_nodes_unchanged"], scenario
        assert scenario["one_generation_job"], scenario
        assert scenario["nine_generated_artifacts"], scenario
        assert scenario["database_audit"] == {"integrity": "ok", "foreign_key_violations": 0}, scenario
    finally:
        stop_service(process, port)


def main() -> int:
    clear_output()
    report = {
        "schema_version": "f5-t02.resource-bundle-desktop.v1",
        "task": "F5-T02",
        "screenshots": [], "checks": {}, "jobs": [], "scenarios": {},
        "expected_http_errors": [], "http_errors": [], "failed_requests": [],
        "expected_network_errors": [], "expected_console_errors": [],
        "console_errors": [], "page_errors": [], "result": "failed",
    }
    try:
        run_scenario("retry", OUTPUT_DIR / "f5_t02_retry.sqlite3", report)
        run_scenario("recovery", OUTPUT_DIR / "f5_t02_recovery.sqlite3", report)
        assert report["expected_http_errors"], "the expected demo-disabled branch was not exercised"
        assert report["expected_network_errors"], "the service restart branch was not exercised"
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["page_errors"], report["page_errors"]
        report["result"] = "passed"
    except Exception as exc:
        report["failure"] = repr(exc)
        report["traceback"] = traceback.format_exc()
    finally:
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "result": report["result"],
        "screenshots": len(report["screenshots"]),
        "failure": report.get("failure"),
    }, ensure_ascii=False))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
