"""Run the M2 golden loop against real local services and an isolated database."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "M2_单画像黄金闭环" / "evidence" / "browser-e2e"
DB_PATH = OUTPUT_DIR / "m2_e2e.db"
BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:5173"
BASELINE_USERNAME = "m2-golden-learner"
BASELINE_PASSWORD = "M2-E2E-only-2026!"


def _wait_port(port: int, *, open_: bool, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", port)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    state = "open" if open_ else "closed"
    raise RuntimeError(f"port {port} did not become {state}")


def _ensure_ports_free() -> None:
    occupied = []
    for port in (8000, 5173):
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                occupied.append(port)
    if occupied:
        raise RuntimeError(f"acceptance ports already in use: {occupied}")


def _process_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "m2-e2e-auth-secret-isolated-2026-0001",
            "EDUMATRIX_DEMO_MODE": "0",
            "EDUMATRIX_LLM_PROVIDER": "deterministic",
            "EDUMATRIX_LLM_API_KEY": "",
            "EDUMATRIX_LLM_ENDPOINT": "",
            "EDUMATRIX_LLM_MODEL": "deterministic",
            "EDUMATRIX_RELOAD": "0",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def _prepare_database(env: dict[str, str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    code = """
from app.auth import get_password_hash
from app.database import DBUser, SessionLocal, init_db
from app.m2_baseline import M2_BASELINE_USERNAME, seed_m2_baseline
init_db()
with SessionLocal() as session:
    seed_m2_baseline(session)
    user = session.query(DBUser).filter_by(username=M2_BASELINE_USERNAME).one()
    user.hashed_password = get_password_hash(%r)
    session.commit()
""" % BASELINE_PASSWORD
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True, timeout=90)


def _start_backend(env: dict[str, str], log) -> subprocess.Popen[Any]:
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    _wait_port(8000, open_=True)
    return process


def _start_frontend(env: dict[str, str], log) -> subprocess.Popen[Any]:
    process = subprocess.Popen(
        ["npm.cmd", "--prefix", "frontend", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    _wait_port(5173, open_=True)
    return process


def _stop(process: subprocess.Popen[Any] | None, port: int) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    _wait_port(port, open_=False, timeout=15)


def _screenshot(page: Page, name: str) -> str:
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _login(page: Page) -> None:
    page.goto(f"{FRONTEND_URL}/login", wait_until="networkidle")
    page.get_by_placeholder("请输入用户名").fill(BASELINE_USERNAME)
    page.get_by_placeholder("请输入密码").fill(BASELINE_PASSWORD)
    page.get_by_role("button", name="启动学习").click()
    page.wait_for_function("() => Boolean(localStorage.getItem('edumatrix_token'))")
    page.evaluate("localStorage.setItem('edumatrix_onboarded', 'true')")


def _register_intruder(page: Page) -> str:
    username = f"m2-intruder-{int(time.time())}"
    response = page.request.post(
        f"{BACKEND_URL}/api/auth/register",
        data={"username": username, "password": "M2-intruder!", "display_name": "M2 越权验收用户"},
    )
    if response.status != 200:
        raise AssertionError(f"intruder registration failed: {response.status} {response.text()}")
    return response.json()["access_token"]


def main() -> int:
    report: dict[str, Any] = {
        "scope": "M2-012 real frontend/backend/browser/persistence acceptance",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "database": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
        "llm_mode": "deterministic (workflow evidence only; not model-quality evidence)",
        "checks": {},
        "screenshots": [],
    }
    env = _process_env()
    backend = None
    frontend = None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        _ensure_ports_free()
        _prepare_database(env)
        with (OUTPUT_DIR / "backend.log").open("w", encoding="utf-8") as backend_log, (OUTPUT_DIR / "frontend.log").open("w", encoding="utf-8") as frontend_log:
            backend = _start_backend(env, backend_log)
            frontend = _start_frontend(env, frontend_log)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    health = page.request.get(f"{BACKEND_URL}/api/health")
                    assert health.ok, health.text()
                    report["checks"]["services_started"] = True

                    _login(page)
                    report["screenshots"].append(_screenshot(page, "01-login-complete"))
                    report["checks"]["real_login"] = True

                    page.goto(f"{FRONTEND_URL}/golden-loop", wait_until="networkidle")
                    page.locator(".golden-page h2").wait_for(state="visible", timeout=20_000)
                    assert page.locator(".error-banner").count() == 0
                    report["screenshots"].append(_screenshot(page, "02-baseline-loaded"))
                    report["checks"]["baseline_initialized"] = True

                    page.get_by_role("button", name="创建任务").click()
                    page.get_by_role("button", name="生成并检查").wait_for(state="visible", timeout=20_000)
                    page.get_by_role("button", name="生成并检查").click()
                    page.get_by_text("9/9").wait_for(state="visible", timeout=90_000)
                    for label in ("讲义", "实操指南", "分阶测试"):
                        page.get_by_role("button", name=label).click()
                        page.locator(".resource-body").wait_for(state="visible")
                    report["screenshots"].append(_screenshot(page, "03-three-resources-quality"))
                    report["checks"]["three_resources_and_quality"] = True

                    owner_token = page.evaluate("localStorage.getItem('edumatrix_token')")
                    task_response = page.request.get(
                        f"{BACKEND_URL}/api/v1/m2/golden-tasks/latest",
                        headers={"Authorization": f"Bearer {owner_token}"},
                    )
                    assert task_response.ok, task_response.text()
                    task_id = task_response.json()["task_id"]
                    report["task_id"] = task_id

                    page.get_by_role("button", name="提交反馈").click()
                    page.get_by_text("闭环完成").wait_for(state="visible", timeout=30_000)
                    report["screenshots"].append(_screenshot(page, "04-feedback-complete"))
                    report["checks"]["feedback_and_decision"] = True

                    page.reload(wait_until="networkidle")
                    page.get_by_text("闭环完成").wait_for(state="visible", timeout=20_000)
                    report["checks"]["browser_refresh_recovery"] = True

                    _stop(backend, 8000)
                    backend = _start_backend(env, backend_log)
                    page.reload(wait_until="networkidle")
                    page.get_by_text("闭环完成").wait_for(state="visible", timeout=30_000)
                    report["screenshots"].append(_screenshot(page, "05-backend-restart-recovery"))
                    report["checks"]["backend_restart_recovery"] = True

                    intruder_token = _register_intruder(page)
                    forbidden_headers = {"Authorization": f"Bearer {intruder_token}"}
                    baseline_forbidden = page.request.get(f"{BACKEND_URL}/api/v1/m2/baseline", headers=forbidden_headers)
                    bundle_forbidden = page.request.get(f"{BACKEND_URL}/api/v1/m2/golden-tasks/{task_id}/bundle", headers=forbidden_headers)
                    assert baseline_forbidden.status == 403, baseline_forbidden.text()
                    assert bundle_forbidden.status == 403, bundle_forbidden.text()
                    report["checks"]["owner_boundary"] = {"baseline": 403, "bundle": 403}

                    bundle = page.request.get(
                        f"{BACKEND_URL}/api/v1/m2/golden-tasks/{task_id}/bundle",
                        headers={"Authorization": f"Bearer {owner_token}"},
                    )
                    assert bundle.ok, bundle.text()
                    payload = bundle.json()
                    assert payload["task"]["status"] == "completed"
                    assert len(payload["resources"]) == 3
                    assert len(payload["quality_checks"]) == 9
                    assert payload["feedback_events"] and payload["decisions"]
                    report["checks"]["persistent_bundle"] = {
                        "status": payload["task"]["status"],
                        "resources": len(payload["resources"]),
                        "quality_checks": len(payload["quality_checks"]),
                        "feedback_events": len(payload["feedback_events"]),
                        "decisions": len(payload["decisions"]),
                    }
                    report["result"] = "passed"
                except Exception:
                    try:
                        report["screenshots"].append(_screenshot(page, "error"))
                    except Exception:
                        pass
                    raise
                finally:
                    context.close()
                    browser.close()
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _stop(frontend, 5173)
        _stop(backend, 8000)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
