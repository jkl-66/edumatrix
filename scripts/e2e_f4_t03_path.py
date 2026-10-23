"""F4-T03 desktop acceptance for the unified total/subject learning path."""

from __future__ import annotations

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
sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f4_t03_path"
DB_PATH = OUTPUT_DIR / "f4_t03_runtime.db"
PORT = int(os.getenv("EDUMATRIX_F4_T03_PORT", "8899"))
BASE_URL = f"http://127.0.0.1:{PORT}"
COURSE_ID = "demo-course-rag-trust-v1"


def wait_port(expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected state: {expected}")


def prepare_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def env_for_runtime() -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "f4-t03-isolated-secret",
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
        "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def seed_fixture(env: dict[str, str]) -> None:
    previous = os.environ.copy()
    os.environ.update(env)
    try:
        from app.competition_demo_seed import seed_competition_demo
        from app.database import SessionLocal, init_db

        init_db()
        session = SessionLocal()
        try:
            seed_competition_demo(session)
        finally:
            session.close()
    finally:
        os.environ.clear()
        os.environ.update(previous)


def install_session(page: Page, payload: dict) -> None:
    state = json.dumps(payload, ensure_ascii=False)
    page.add_init_script(
        f"""
        const session = {state};
        localStorage.setItem('edumatrix_token', session.access_token);
        localStorage.setItem('edumatrix_username', session.username || 'lzz');
        localStorage.setItem('edumatrix_display_name', session.display_name || session.username || 'lzz');
        localStorage.setItem('edumatrix_role', session.role || 'student');
        localStorage.setItem('edumatrix_student_id', session.student_id || session.username || 'lzz');
        localStorage.setItem('edumatrix_onboarded', 'true');
        localStorage.setItem('edumatrix_course_id', '{COURSE_ID}');
        localStorage.setItem('edumatrix_course_title', '人工智能与机器学习工程');
        """
    )


def login(page: Page) -> None:
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        form={"username": "lzz", "password": "404404aA"},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    install_session(page, response.json())


def metrics(page: Page) -> dict:
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
              (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 40),
              (b.innerText || b.getAttribute('aria-label') || '').trim().slice(0, 40),
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
          }).map((el) => ({
            text: el.innerText.trim().slice(0, 40),
            size: getComputedStyle(el).fontSize,
            className: el.className,
            parentClass: el.parentElement?.className || '',
          })).slice(0, 20);
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            bodyTextLength: (document.body.innerText || '').trim().length,
            collisions,
            clipped,
            smallText,
            pathLayout: (() => {
              const main = document.querySelector('.path-main-column')?.getBoundingClientRect();
              const aside = document.querySelector('.path-side-column')?.getBoundingClientRect();
              return main && aside ? { mainWidth: main.width, asideWidth: aside.width } : null;
            })(),
          };
        }"""
    )


def assert_desktop_quality(page: Page, report: dict, name: str) -> None:
    page.wait_for_timeout(700)
    result = metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True)
    if name not in report["screenshots"]:
        report["screenshots"].append(name)
    report["checks"][name] = result
    assert result["documentWidth"] <= result["viewport"][0], result
    assert result["bodyTextLength"] > 200, result
    assert not result["collisions"], result
    assert not result["clipped"], result
    assert not result["smallText"], result


def main() -> int:
    prepare_output()
    env = env_for_runtime()
    seed_fixture(env)
    report = {
        "schema_version": "f4-t03.path-desktop.v1",
        "viewport": [1440, 900],
        "screenshots": [],
        "checks": {},
        "http_errors": [],
        "failed_requests": [],
        "console_errors": [],
        "page_errors": [],
        "result": "failed",
    }
    process = None
    try:
        with (OUTPUT_DIR / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page()
                page.set_default_timeout(30000)
                page.on("response", lambda response: report["http_errors"].append({"status": response.status, "url": response.url}) if response.status >= 400 else None)
                page.on("requestfailed", lambda request: report["failed_requests"].append({"url": request.url, "failure": request.failure}) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
                page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
                page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)
                login(page)
                page.goto(f"{BASE_URL}/workspace/path?course_id={COURSE_ID}", wait_until="networkidle", timeout=60000)
                page.get_by_test_id("path-overview").wait_for(state="visible")
                page.get_by_text("今天学什么", exact=True).wait_for(state="visible")
                page.get_by_text("科目进度", exact=True).wait_for(state="visible")
                assert_desktop_quality(page, report, "01-total-path.png")

                page.get_by_test_id("path-subject-view").click()
                page.get_by_text("当前科目 · 今天", exact=True).wait_for(state="visible")
                assert_desktop_quality(page, report, "02-subject-path.png")

                page.get_by_role("button", name="调整预算与重建").click()
                page.get_by_test_id("textbook-path-draft").wait_for(state="visible")
                assert_desktop_quality(page, report, "03-budget-history-expanded.png")
                assert "cannot revise plan from replan_pending" not in page.locator("body").inner_text()

                advanced = page.locator(".path-advanced-content")
                if not advanced.is_visible():
                    page.get_by_role("button", name="路径分析与历史").click()
                advanced.wait_for(state="visible")
                page.get_by_text("学习链条", exact=True).wait_for(state="visible")
                adaptive_route = page.get_by_text("A* 动态推荐路线", exact=True)
                if adaptive_route.count():
                    adaptive_route.first.wait_for(state="visible")
                report["interactions"] = {
                    "total_view": True,
                    "subject_view": True,
                    "budget_history_revealed": True,
                    "advanced_analysis_revealed": True,
                    "adaptive_route_present": bool(adaptive_route.count()),
                }
                context.close()
                browser.close()
            with sqlite3.connect(DB_PATH) as db:
                report["database_audit"] = {
                    "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
                    "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
                }
            assert report["database_audit"] == {"integrity": "ok", "foreign_key_violations": 0}
            assert not report["http_errors"], report["http_errors"]
            assert not report["failed_requests"], report["failed_requests"]
            assert not report["console_errors"], report["console_errors"]
            assert not report["page_errors"], report["page_errors"]
            report["result"] = "passed"
    except Exception as exc:
        report["failure"] = repr(exc)
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
            process.wait(timeout=5)
            wait_port(False, 15)
        report["process_cleanup"] = {"service_stopped": process is None or process.poll() is not None}
        (OUTPUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "failure": report.get("failure"), "cleanup": report["process_cleanup"]}, ensure_ascii=False))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
