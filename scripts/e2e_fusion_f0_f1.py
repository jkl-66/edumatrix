"""Isolated desktop browser acceptance for the F0/F1 fusion refactor.

The run uses a deterministic model path and a throw-away SQLite database.  It
proves the public entry, the three supported roles, the unified shell, the
settings states, and the four 7.20 protected pages without requiring an
external model or Docker.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("EDUMATRIX_F1_PORT", "8891"))
BASE_URL = f"http://127.0.0.1:{PORT}"
OUTPUT_DIR = Path(
    os.getenv(
        "EDUMATRIX_E2E_OUTPUT_DIR",
        str(ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f0_f1_browser_e2e"),
    )
).resolve()
DB_PATH = Path(
    os.getenv(
        "EDUMATRIX_E2E_DB_PATH",
        str(OUTPUT_DIR / "f0_f1_runtime.db"),
    )
).resolve()
PASSWORD = "F0F1-acceptance-2026!"

STUDENT_PROTECTED = [
    ("profile", "/profile/learning", "学习画像"),
    ("path", "/workspace/path", "学习路径"),
    ("notes", "/workspace/notes", "笔记本"),
    ("wrong-questions", "/workspace/review/wrong-questions", "错题本"),
]


def wait_port(expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected state: {expected}")


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()


def register_and_login(page: Page, username: str, role: str) -> dict[str, str]:
    registered = page.request.post(
        f"{BASE_URL}/api/auth/register",
        data={"username": username, "password": PASSWORD, "display_name": f"F1 {role}验收"},
    )
    if not registered.ok:
        raise AssertionError(f"register failed: {registered.status} {registered.text()}")
    with sqlite3.connect(DB_PATH) as db:
        db.execute("UPDATE users SET role=? WHERE username=?", (role, username))
        db.commit()
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        form={"username": username, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    payload = response.json()
    return {
        "username": username,
        "role": role,
        "token": payload["access_token"],
        "landing_path": payload.get("landing_path") or "",
    }


def login_existing(page: Page, username: str, password: str, role: str) -> dict[str, str]:
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        form={"username": username, "password": password},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    payload = response.json()
    return {
        "username": username,
        "role": role,
        "token": payload["access_token"],
        "landing_path": payload.get("landing_path") or "",
    }


def initialize_demo(page: Page, admin: dict[str, str]) -> dict:
    headers = {"Authorization": f"Bearer {admin['token']}"}
    response = page.request.post(f"{BASE_URL}/api/v1/competition-demo/initialize", headers=headers)
    if not response.ok:
        raise AssertionError(f"demo initialization failed: {response.status} {response.text()}")
    return response.json()


def set_browser_state(page: Page, user: dict[str, str]) -> None:
    state = json.dumps([user["token"], user["username"], user["role"]], ensure_ascii=False)
    page.add_init_script(
        f"""
          const [token, username, role] = {state}
          localStorage.setItem('edumatrix_token', token)
          localStorage.setItem('edumatrix_username', username)
          localStorage.setItem('edumatrix_display_name', username)
          localStorage.setItem('edumatrix_role', role)
          localStorage.setItem('edumatrix_student_id', username)
          localStorage.setItem('edumatrix_onboarded', 'true')
          localStorage.setItem('edumatrix_course_id', 'demo-course-rag-trust-v1')
          localStorage.setItem('edumatrix_course_title', '人工智能与机器学习工程')
        """,
    )


def metrics(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const visible = (el) => {
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1 &&
              rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight
          }
          const controls = [...document.querySelectorAll('button,a[href],input,select,textarea')].filter(visible)
          const collisions = []
          for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
            const a = controls[i], b = controls[j]
            if (a.contains(b) || b.contains(a)) continue
            const x = a.getBoundingClientRect(), y = b.getBoundingClientRect()
            const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left)
            const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top)
            if (overlapW > 3 && overlapH > 3) collisions.push([a.tagName, (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 32), b.tagName, (b.innerText || b.getAttribute('aria-label') || '').trim().slice(0, 32)])
          }
          const clipped = [...document.querySelectorAll('button,a[href],h1,h2,h3,h4,strong')].filter((el) => {
            if (!visible(el)) return false
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            if (style.textOverflow === 'ellipsis') return false
            if (rect.right > innerWidth + 1 || rect.left < -1) return true
            if (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap') return true
            const parent = el.parentElement
            if (!parent) return false
            const parentStyle = getComputedStyle(parent), parentRect = parent.getBoundingClientRect()
            const clips = ['hidden', 'clip'].includes(parentStyle.overflow) || ['hidden', 'clip'].includes(parentStyle.overflowY)
            return clips && (rect.top < parentRect.top - 1 || rect.bottom > parentRect.bottom + 1)
          }).map((el) => ({tag: el.tagName, text: (el.innerText || '').trim().slice(0, 64)}))
          const textNodes = [...document.querySelectorAll('body *')].filter((el) => visible(el) && el.children.length === 0 && (el.innerText || '').trim())
          const smallText = textNodes.filter((el) => Number.parseFloat(getComputedStyle(el).fontSize) < 13.5).map((el) => ({tag: el.tagName, text: el.innerText.trim().slice(0, 40), size: getComputedStyle(el).fontSize})).slice(0, 20)
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            bodyTextLength: (document.body.innerText || '').trim().length,
            controls: controls.length,
            collisions,
            clipped,
            smallText,
          }
        }"""
    )


def capture(page: Page, key: str, report: dict) -> dict:
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(500)
    result = metrics(page)
    path = OUTPUT_DIR / f"{key}.png"
    page.screenshot(path=str(path), full_page=True)
    report["screenshots"].append(path.name)
    if result["documentWidth"] > result["viewport"][0]:
        raise AssertionError(f"horizontal overflow at {key}: {result}")
    if result["bodyTextLength"] < 80:
        raise AssertionError(f"blank page at {key}: {result}")
    if result["collisions"]:
        raise AssertionError(f"control collisions at {key}: {result['collisions']}")
    if result["clipped"]:
        raise AssertionError(f"clipped content at {key}: {result['clipped']}")
    if result["smallText"]:
        raise AssertionError(f"text below 14px at {key}: {result['smallText']}")
    report["checks"][key] = result
    return result


def wait_route(page: Page, path: str) -> None:
    page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded", timeout=30_000)
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    page.locator("#app").wait_for(state="visible", timeout=15_000)


def attach_browser_errors(page: Page, report: dict) -> list[dict]:
    errors: list[dict] = []
    page.on("pageerror", lambda exc: errors.append({"type": "pageerror", "page_url": page.url, "message": str(exc)}))
    page.on("console", lambda msg: errors.append({"type": "console", "page_url": page.url, "message": msg.text}) if msg.type == "error" else None)
    page.on("requestfailed", lambda req: errors.append({"type": "requestfailed", "page_url": page.url, "url": req.url, "failure": req.failure}))
    report.setdefault("browser_errors", []).append(errors)
    return errors


def flatten_browser_errors(report: dict) -> list[dict]:
    groups = report.get("browser_errors", [])
    if not groups or isinstance(groups[0], dict):
        return groups
    flattened = [error for group in groups for error in group]
    report["browser_errors"] = flattened
    return flattened


def public_pages(browser, viewport: tuple[int, int], report: dict) -> None:
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    page = context.new_page()
    errors = attach_browser_errors(page, report)
    suffix = f"{viewport[0]}x{viewport[1]}"
    try:
        wait_route(page, "/landing")
        page.get_by_role("heading", name="EduMatrix", exact=True).wait_for(state="visible")
        page.get_by_role("tab", name="项目学习者").click()
        page.get_by_text("训练震荡原因", exact=False).wait_for(state="visible")
        capture(page, f"{suffix}-landing", report)

        wait_route(page, "/login")
        assert page.locator('[data-testid="login-role-student"]').is_visible()
        assert page.locator('[data-testid="login-role-teacher"]').is_visible()
        assert page.locator('[data-testid="login-role-admin"]').is_visible()
        assert page.locator('[data-testid="login-role-assistant"]').count() == 0
        assert page.locator('[data-testid="login-role-visitor"]').count() == 0
        capture(page, f"{suffix}-login", report)
    finally:
        report.setdefault("page_error_counts", {})[f"public:{suffix}"] = len(errors)
        context.close()


def role_pages(browser, user: dict[str, str], viewport: tuple[int, int], report: dict) -> None:
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    page = context.new_page()
    errors = attach_browser_errors(page, report)
    suffix = f"{viewport[0]}x{viewport[1]}"
    prefix = f"{user['role']}:{suffix}"
    try:
        if user["role"] == "student":
            wait_route(page, "/login")
            page.get_by_test_id("login-role-student").click()
            page.get_by_test_id("fill-demo-account").click()
            page.get_by_test_id("login-submit").click()
            page.wait_for_url(re.compile(r"/$"), timeout=25_000)
            assert page.locator(".app-shell").is_visible()
            page.get_by_test_id("dashboard-today-tasks").wait_for(state="visible", timeout=25_000)
            labels = ["首页", "个人中心", "学习画像", "学习空间", "智能对话", "知识库", "学习市场", "设置"]
            for label in labels:
                assert page.get_by_role("link", name=re.compile(f"^{label}$")).is_visible(), label
            capture(page, f"{suffix}-student-home", report)

            detail = page.get_by_test_id("dashboard-detail")
            detail.locator(":scope > summary").click()
            page.wait_for_timeout(350)
            detail.evaluate("(element) => element.scrollIntoView({ block: 'start', behavior: 'instant' })")
            page.wait_for_timeout(250)
            capture(page, f"{suffix}-student-home-detail", report)
            adjust_goal = page.get_by_test_id("dashboard-adjust-goal")
            if adjust_goal.count() and adjust_goal.is_visible():
                adjust_goal.click()
                page.get_by_role("dialog", name="调整最终学习目标").wait_for(state="visible")
                capture(page, f"{suffix}-student-home-goal-modal", report)
                page.get_by_role("button", name="关闭目标设置").click()
            else:
                report["checks"][f"{suffix}-student-home-goal-modal"] = {"skipped": "demo context has no adjustable target"}

            wait_route(page, "/settings")
            page.get_by_role("heading", name="设置系统如何协助你学习", exact=True).wait_for(state="visible")
            capture(page, f"{suffix}-student-settings", report)
            page.get_by_text("测试连接", exact=True).first.click()
            page.get_by_text("文本模型测试结果", exact=True).wait_for(state="visible", timeout=15_000)
            checkbox = page.locator('input[type="checkbox"]').first
            checkbox.click()
            page.get_by_test_id("save-settings").click()
            page.get_by_text("已保存", exact=True).wait_for(state="visible")
            disclosure = page.locator('[data-testid="memory-governance"]')
            disclosure.locator("summary").click()
            page.wait_for_timeout(600)
            capture(page, f"{suffix}-student-settings-detail", report)

            for name, route, title in STUDENT_PROTECTED:
                if name == "notes":
                    with page.expect_response(re.compile(r"/api/notes/lzz(?:\?|$)"), timeout=25_000) as notes_response, page.expect_response(re.compile(r"/api/review/lzz(?:\?|$)"), timeout=25_000) as reviews_response:
                        wait_route(page, route)
                    assert notes_response.value.ok, notes_response.value.status
                    assert reviews_response.value.ok, reviews_response.value.status
                else:
                    wait_route(page, route)
                assert page.get_by_text(title, exact=True).count() >= 1, route
                if name == "profile":
                    page.get_by_test_id("profile-compact-focus").wait_for(state="visible", timeout=25_000)
                    page.get_by_text("正在组合课程画像证据", exact=True).wait_for(state="hidden", timeout=25_000)
                    page.get_by_text("智能助教正在为您撰写成长信笺...", exact=True).wait_for(state="hidden", timeout=25_000)
                elif name == "path":
                    page.get_by_test_id("textbook-path-draft").wait_for(state="visible", timeout=25_000)
                elif name == "notes":
                    page.get_by_text(re.compile(r"^知识库笔记 \(\d+\)$")).wait_for(state="visible", timeout=25_000)
                elif name == "wrong-questions":
                    page.get_by_text("加载错题数据...", exact=True).wait_for(state="hidden", timeout=25_000)
                capture(page, f"{suffix}-student-{name}", report)
        elif user["role"] == "teacher":
            set_browser_state(page, user)
            wait_route(page, "/teacher/overview")
            assert page.get_by_role("link", name="教学总览", exact=True).is_visible()
            assert page.get_by_role("link", name="学生学情", exact=True).is_visible()
            capture(page, f"{suffix}-teacher", report)
        else:
            set_browser_state(page, user)
            wait_route(page, "/admin/system")
            assert page.get_by_role("link", name="系统状态", exact=True).is_visible()
            assert page.get_by_role("link", name="账号权限", exact=True).is_visible()
            capture(page, f"{suffix}-admin", report)
    finally:
        report.setdefault("page_error_counts", {})[prefix] = len(errors)
        context.close()


def main() -> int:
    clear_output()
    report: dict = {
        "schema_version": "fusion-f0-f1-browser-e2e.v1",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "database": str(DB_PATH),
        "screenshots": [],
        "checks": {},
        "browser_errors": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    process = None
    try:
        env = os.environ.copy()
        env.update(
            {
                "EDUMATRIX_DB_PATH": str(DB_PATH),
                "EDUMATRIX_AUTH_SECRET_KEY": "f0-f1-isolated-secret",
                "EDUMATRIX_LLM_PROVIDER": "deterministic",
                "EDUMATRIX_LLM_MODEL": "deterministic",
                "EDUMATRIX_LLM_API_KEY": "",
                "EDUMATRIX_LLM_ENDPOINT": "",
                "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
                "EDUMATRIX_RELOAD": "0",
                "EDUMATRIX_HOST": "127.0.0.1",
                "EDUMATRIX_PORT": str(PORT),
                "PYTHON_DOTENV_DISABLED": "1",
                "PYTHONUNBUFFERED": "1",
                "EDUMATRIX_SANDBOX_MODE": "disabled",
            }
        )
        log_path = OUTPUT_DIR / "backend.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                setup_context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                setup_page = setup_context.new_page()
                admin = register_and_login(setup_page, f"f1_admin_{int(time.time())}", "admin")
                initialized = initialize_demo(setup_page, admin)
                report["checks"]["competition_demo_seed"] = {
                    "status": initialized.get("status", {}).get("status"),
                    "cohort_student_count": initialized.get("cohort_student_count"),
                }
                student = register_and_login(setup_page, f"f1_student_{int(time.time())}", "student")
                teacher = login_existing(setup_page, "teacher", "admin123", "teacher")
                setup_context.close()

                # Public pages are tested without a token; role pages use fresh contexts.
                for viewport in ((1440, 900), (1366, 768)):
                    public_pages(browser, viewport, report)
                    role_pages(browser, student, viewport, report)
                    role_pages(browser, teacher, viewport, report)
                    role_pages(browser, admin, viewport, report)
                browser.close()
                browser_errors = flatten_browser_errors(report)
                if browser_errors:
                    raise AssertionError(f"browser errors detected: {browser_errors}")
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=20)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            try:
                wait_port(False, 15)
            except RuntimeError:
                pass
        flatten_browser_errors(report)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
