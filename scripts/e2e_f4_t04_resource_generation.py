"""F4-T04 desktop E2E for today's knowledge-point resource generation.

The two scenarios use isolated SQLite files. The first exercises a single-item
failure and retry; the second exercises interrupted-item recovery. Resource
generation is deliberately checked against the learning-evidence tables so a
successful generation cannot be mistaken for mastery or task completion.
"""

from __future__ import annotations

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
sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f4_t04_resource_generation"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
BASE_PORT = int(os.getenv("EDUMATRIX_F4_T04_PORT", "8901"))
RESOURCE_TYPES = (
    "handout",
    "mind_map",
    "quiz",
    "training_task",
    "code_sandbox",
    "video",
    "deck",
    "interactive_model",
    "feynman",
)


def wait_port(port: int, expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", port)) == 0
        if opened is expected:
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
        "EDUMATRIX_AUTH_SECRET_KEY": "f4-t04-isolated-secret",
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
        "init_db(); db=SessionLocal(); "
        "seed_competition_demo(db); db.close()"
    )
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


def login(page: Page, base_url: str) -> dict[str, str]:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": USERNAME, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    payload = response.json()
    state = json.dumps(payload, ensure_ascii=False)
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
    return payload


def bearer(payload: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {payload['access_token']}"}


def api_post(
    page: Page,
    base_url: str,
    payload: dict[str, str],
    path: str,
    expected: set[int] = {200},
    body: dict | None = None,
) -> dict:
    response = page.request.post(f"{base_url}{path}", headers=bearer(payload), data=body)
    if response.status not in expected:
        raise AssertionError(f"POST {path}: {response.status} {response.text()}")
    return response.json()


def sqlite_metrics(db_path: Path, username: str = USERNAME) -> dict:
    with sqlite3.connect(db_path, timeout=10) as db:
        owner_row = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()
        if owner_row is None:
            raise AssertionError(f"user {username!r} is missing from isolated database")
        owner_id = owner_row[0]
        snapshot_row = db.execute(
            "SELECT snapshot FROM profile_snapshots WHERE owner_public_id=? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (owner_id,),
        ).fetchone()
        return {
            "learning_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=?", (owner_id,)
            ).fetchone()[0],
            "profile_snapshots": db.execute(
                "SELECT COUNT(*) FROM profile_snapshots WHERE owner_public_id=?", (owner_id,)
            ).fetchone()[0],
            "latest_profile_snapshot": snapshot_row[0] if snapshot_row else None,
            "artifacts": db.execute(
                "SELECT COUNT(*) FROM artifacts WHERE owner_public_id=?", (owner_id,)
            ).fetchone()[0],
            "generation_jobs": db.execute(
                "SELECT COUNT(*) FROM generation_tasks WHERE owner_public_id=? "
                "AND capability='learning_resource_bundle.generate'",
                (owner_id,),
            ).fetchone()[0],
            "today_path_node_status": db.execute(
                "SELECT status FROM path_nodes WHERE id='demo-task-lzz-read-01'"
            ).fetchone()[0],
        }


def database_audit(db_path: Path) -> dict:
    with sqlite3.connect(db_path, timeout=10) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def page_diagnostics(page: Page, report: dict, scope: str) -> None:
    page.on("response", lambda response: report["http_errors"].append({
        "scope": scope, "status": response.status, "url": response.url,
    }) if response.status >= 400 and not (
        response.status == 409 and response.url.endswith("/execute-demo")
        and scope in {"retry", "recovery"}
    ) else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "scope": scope, "url": request.url, "failure": request.failure,
    }) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append({
        "scope": scope, "error": str(error),
    }))
    page.on("console", lambda message: report["console_errors"].append({
        "scope": scope, "text": message.text,
    }) if message.type == "error" and "server responded with a status of 409" not in message.text else None)


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
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            bodyTextLength: (document.body.innerText || '').trim().length,
            collisions, clipped, smallText,
          };
        }"""
    )


def capture(page: Page, report: dict, name: str) -> dict:
    page.wait_for_timeout(700)
    metrics = visible_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True)
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] > 200, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    return metrics


def select_task(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/workspace/path?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("path-overview").wait_for(state="visible")
    page.get_by_text("今天学什么", exact=True).wait_for(state="visible")
    page.get_by_test_id("today-knowledge-points").wait_for(state="visible")
    tasks = page.get_by_test_id("today-knowledge-points").locator("button")
    if tasks.count() < 1:
        raise AssertionError("today knowledge point selector is empty")
    tasks.first.click()
    page.get_by_test_id("selected-knowledge-point").wait_for(state="visible")
    action = page.get_by_test_id("selected-knowledge-point").locator("button.generation-panel__generate")
    action.wait_for(state="visible")
    label = action.inner_text().strip()
    if label not in {"一键生成完整资源包", "已创建，等待生成执行"}:
        raise AssertionError(f"unexpected generation action state: {label}")


def verify_blocked_context(page: Page, report: dict, name: str) -> None:
    tasks = page.get_by_test_id("today-knowledge-points").locator("button")
    blocked_index = next((index for index in range(tasks.count()) if index > 0), None)
    if blocked_index is None:
        raise AssertionError("isolated demo fixture does not expose a context-blocked today task")
    tasks.nth(blocked_index).click()
    selected = page.get_by_test_id("selected-knowledge-point")
    action = selected.locator("button.generation-panel__generate")
    action.wait_for(state="visible")
    assert action.is_disabled(), "generation must remain disabled without a complete server context"
    capture(page, report, name)
    tasks.first.click()
    selected.locator("button.generation-panel__generate").wait_for(state="visible")


def generation_payload_from_ui(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const button = document.querySelector('[data-testid="selected-knowledge-point"]');
          const task = document.querySelector('[data-testid="today-knowledge-points"] button');
          return {
            task_text: button?.innerText || '',
            selected: task?.innerText || '',
            context_ready: !button?.innerText?.includes('还缺少'),
          };
        }"""
    )


def create_queued_job(page: Page, report: dict) -> str:
    result = page.get_by_test_id("selected-knowledge-point")
    result.get_by_role("button", name="一键生成完整资源包").click()
    page.get_by_test_id("resource-generation-status").wait_for(state="visible")
    page.get_by_text("已进入生成队列", exact=True).wait_for(state="visible")
    job_id = page.evaluate(
        """() => document.querySelector('[data-testid="resource-generation-status"]')?.dataset.jobId || ''"""
    )
    report["ui_generation"] = {
        "clicked": True,
        "queued_visible": True,
        "job_id_from_dom": job_id,
        "context": generation_payload_from_ui(page),
    }
    return job_id


def wait_for_archived(page: Page) -> None:
    status = page.get_by_test_id("resource-generation-status")
    status.get_by_text("全部已归档", exact=True).wait_for(state="visible", timeout=30_000)
    status.get_by_text("9/9 · 100%", exact=True).wait_for(state="visible", timeout=30_000)
    for resource_type in RESOURCE_TYPES:
        item = page.locator(".generation-resource-item").filter(has=page.locator(f"[data-resource-type='{resource_type}']"))
        if item.count():
            item.get_by_text("已归档", exact=False).wait_for(state="visible")


def run_scenario(db_path: Path, port: int, scenario: str, screenshots: list[str], report: dict) -> None:
    env = runtime_env(db_path, port)
    seed_fixture(env)
    base_url = f"http://127.0.0.1:{port}"
    process = None
    browser = None
    try:
        log_path = OUTPUT_DIR / f"backend-{scenario}.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(port, True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page()
                page.set_default_timeout(30_000)
                page_diagnostics(page, report, scenario)
                auth = login(page, base_url)
                select_task(page, base_url)
                before = sqlite_metrics(db_path)
                verify_blocked_context(page, report, f"{scenario}-00-context-blocked-1440x900.png")
                capture(page, report, f"{scenario}-01-ready-1440x900.png")

                endpoint_fragment = "/api/v1/resource-bundles/generation-jobs/"
                execute_fragment = "/execute-demo"
                if scenario in {"retry", "recovery"}:
                    def hold_demo_execution(route):
                        route.fulfill(
                            status=409,
                            content_type="application/json",
                            body=json.dumps({"detail": {"code": "resource_generation.demo_disabled", "message": "专项测试暂缓自动执行"}}),
                        )
                    page.route(f"**{endpoint_fragment}*{execute_fragment}", hold_demo_execution)

                page.get_by_role("button", name="一键生成完整资源包").click()
                page.get_by_test_id("resource-generation-status").wait_for(state="visible")
                page.get_by_test_id("resource-generation-status").get_by_text(
                    "已进入生成队列", exact=True,
                ).wait_for(state="visible")
                queued_job = page.request.get(
                    f"{base_url}/api/v1/resource-bundles/generation-jobs",
                    params={"course_id": COURSE_ID}, headers=bearer(auth),
                ).json()["items"][0]
                job_id = queued_job["job_id"]
                report.setdefault("scenarios", {}).setdefault(scenario, {})["job_id"] = job_id
                capture(page, report, f"{scenario}-02-queued-1440x900.png")

                if scenario == "retry":
                    api_post(
                        page,
                        base_url,
                        auth,
                        f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/handout/start",
                    )
                    page.reload(wait_until="networkidle", timeout=60_000)
                    select_task(page, base_url)
                    capture(page, report, "retry-03-resource-running-1440x900.png")
                    handout = api_post(
                        page,
                        base_url,
                        auth,
                        f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/handout/complete",
                        body={"content": "# F4-T04 已归档讲义\n\n用于验证成功项不会被失败重试覆盖。"},
                    )
                    handout_id = next(
                        item["resource"]["resource_id"] for item in handout["items"]
                        if item["type"] == "handout"
                    )
                    api_post(page, base_url, auth, f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/mind_map/start")
                    api_post(
                        page,
                        base_url,
                        auth,
                        f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/mind_map/fail",
                        body={"error_code": "f4_t04_injected_failure", "error_message": "专项验收注入的单项失败"},
                    )
                    page.reload(wait_until="networkidle", timeout=60_000)
                    select_task(page, base_url)
                    page.get_by_role("button", name="重试此项").wait_for(state="visible")
                    capture(page, report, "retry-04-single-item-failed-1440x900.png")
                    page.unroute(f"**{endpoint_fragment}*{execute_fragment}")
                    page.get_by_role("button", name="重试此项").click()
                    wait_for_archived(page)
                    final_job = page.request.get(
                        f"{base_url}/api/v1/resource-bundles/generation-jobs/{job_id}", headers=bearer(auth)
                    ).json()
                    assert next(
                        item["resource"]["resource_id"] for item in final_job["items"]
                        if item["type"] == "handout"
                    ) == handout_id
                    capture(page, report, "retry-05-single-item-retried-archived-1440x900.png")
                else:
                    handout = api_post(
                        page,
                        base_url,
                        auth,
                        f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/handout/complete",
                        body={"content": "# F4-T04 恢复场景讲义\n\n用于验证中断恢复不会覆盖成功资源。"},
                    )
                    handout_id = next(
                        item["resource"]["resource_id"] for item in handout["items"]
                        if item["type"] == "handout"
                    )
                    api_post(page, base_url, auth, f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/mind_map/start")
                    api_post(
                        page,
                        base_url,
                        auth,
                        f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/quiz/fail",
                        body={"error_code": "f4_t04_interrupted_failure", "error_message": "专项验收注入的中断项"},
                    )
                    page.reload(wait_until="networkidle", timeout=60_000)
                    select_task(page, base_url)
                    page.get_by_role("button", name="恢复中断项").wait_for(state="visible")
                    capture(page, report, "recovery-03-interrupted-items-1440x900.png")
                    page.unroute(f"**{endpoint_fragment}*{execute_fragment}")
                    page.get_by_role("button", name="恢复中断项").click()
                    wait_for_archived(page)
                    final_job = page.request.get(
                        f"{base_url}/api/v1/resource-bundles/generation-jobs/{job_id}", headers=bearer(auth)
                    ).json()
                    assert next(
                        item["resource"]["resource_id"] for item in final_job["items"]
                        if item["type"] == "handout"
                    ) == handout_id
                    capture(page, report, "recovery-04-interrupted-items-recovered-1440x900.png")

                after = sqlite_metrics(db_path)
                assert after["learning_events"] == before["learning_events"], {"before": before, "after": after}
                assert after["profile_snapshots"] == before["profile_snapshots"], {"before": before, "after": after}
                assert after["latest_profile_snapshot"] == before["latest_profile_snapshot"], {"before": before, "after": after}
                assert after["artifacts"] == before["artifacts"] + 9, {"before": before, "after": after}
                assert after["generation_jobs"] == 1, {"before": before, "after": after}
                assert after["today_path_node_status"] == before["today_path_node_status"] == "in_progress"
                report["scenarios"][scenario]["metrics_before"] = before
                report["scenarios"][scenario]["metrics_after"] = after

                page.set_viewport_size({"width": 1366, "height": 768})
                page.reload(wait_until="networkidle", timeout=60_000)
                select_task(page, base_url)
                job = page.request.get(
                    f"{base_url}/api/v1/resource-bundles/generation-jobs/{job_id}", headers=bearer(auth)
                ).json()
                assert job["status"] == "succeeded"
                assert len(job["items"]) == 9
                assert all(item["state"] == "succeeded" for item in job["items"])
                assert len({item["resource"]["resource_id"] for item in job["items"]}) == 9
                capture(page, report, f"{scenario}-06-archived-1366x768.png")
                report["scenarios"][scenario]["assertions"] = {
                    "nine_resource_types": [item["type"] for item in job["items"]],
                    "nine_distinct_artifacts": True,
                    "learning_evidence_unchanged": True,
                    "profile_snapshot_unchanged": True,
                    "mastery_unchanged": True,
                    "single_idempotent_job": True,
                    "successful_resource_preserved": True,
                    "path_task_not_auto_completed": True,
                }
                context.close()
                browser.close()
                browser = None
    finally:
        if process is not None and process.poll() is None:
            try:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
                process.wait(timeout=5)
                wait_port(port, False, 15)
            except Exception as exc:
                report.setdefault("cleanup_warnings", []).append(f"{scenario} service cleanup: {exc}")
        report.setdefault("cleanup", {})[scenario] = {
            "service_stopped": process is None or process.poll() is not None,
            "database": database_audit(db_path),
        }


def main() -> int:
    clear_output()
    report = {
        "schema_version": "f4-t04.resource-generation-desktop.v1",
        "task": "F4-T04",
        "course_id": COURSE_ID,
        "screenshots": [],
        "checks": {},
        "http_errors": [],
        "failed_requests": [],
        "console_errors": [],
        "page_errors": [],
        "result": "failed",
    }
    retry_db = OUTPUT_DIR / "f4_t04_retry_runtime.db"
    recovery_db = OUTPUT_DIR / "f4_t04_recovery_runtime.db"
    try:
        run_scenario(retry_db, BASE_PORT, "retry", [], report)
        run_scenario(recovery_db, BASE_PORT + 1, "recovery", [], report)
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["page_errors"], report["page_errors"]
        report["result"] = "passed"
    except Exception as exc:
        report["failure"] = repr(exc)
        report["traceback"] = traceback.format_exc()
    finally:
        (OUTPUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        combined_log = []
        for name in ("backend-retry.log", "backend-recovery.log"):
            path = OUTPUT_DIR / name
            if path.exists():
                combined_log.append(f"===== {name} =====\n{path.read_text(encoding='utf-8', errors='replace')}")
        if combined_log:
            (OUTPUT_DIR / "backend.log").write_text("\n".join(combined_log), encoding="utf-8")
    print(json.dumps({"result": report["result"], "failure": report.get("failure")}, ensure_ascii=False))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
