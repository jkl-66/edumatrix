"""Isolated desktop browser acceptance for F4-T02 learning profile."""

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

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PORT = int(os.getenv("EDUMATRIX_F4_T02_PORT", "8898"))
BASE_URL = f"http://127.0.0.1:{PORT}"
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f4_t02_profile"
DB_PATH = OUTPUT_DIR / "f4_t02_runtime.db"
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


def seed_fixture() -> None:
    os.environ.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "f4-t02-isolated-secret",
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
    })
    from app.competition_demo_seed import seed_competition_demo
    from app.database import SessionLocal, init_db

    init_db()
    session = SessionLocal()
    try:
        seed_competition_demo(session)
    finally:
        session.close()


def learning_state_counts() -> dict[str, int]:
    with sqlite3.connect(DB_PATH) as db:
        return {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("learning_events", "profile_snapshots", "learning_paths", "review_plans")
        }


def login(page: Page) -> dict:
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        form={"username": "lzz", "password": "404404aA"},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    return response.json()


def install_session(page: Page, payload: dict) -> None:
    state = json.dumps(payload, ensure_ascii=False)
    page.add_init_script(
        f"""
        const session = {state}
        localStorage.setItem('edumatrix_token', session.access_token)
        localStorage.setItem('edumatrix_username', session.username || 'lzz')
        localStorage.setItem('edumatrix_display_name', session.display_name || session.username || 'lzz')
        localStorage.setItem('edumatrix_role', session.role || 'student')
        localStorage.setItem('edumatrix_student_id', session.student_id || session.username || 'lzz')
        localStorage.setItem('edumatrix_onboarded', 'true')
        localStorage.setItem('edumatrix_course_id', '{COURSE_ID}')
        localStorage.setItem('edumatrix_course_title', '人工智能与机器学习工程')
        """
    )


def page_metrics(page: Page) -> dict:
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
            if (overlapW > 3 && overlapH > 3) collisions.push([
              (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 32),
              (b.innerText || b.getAttribute('aria-label') || '').trim().slice(0, 32),
            ])
          }
          const clipped = [...document.querySelectorAll('button,a[href],h1,h2,h3,strong,p,span,label')].filter((el) => {
            if (!visible(el)) return false
            const style = getComputedStyle(el), rect = el.getBoundingClientRect()
            if (style.textOverflow === 'ellipsis') return false
            if (rect.right > innerWidth + 1 || rect.left < -1) return true
            return el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap'
          }).map((el) => ({ tag: el.tagName, text: (el.innerText || '').trim().slice(0, 64) })).slice(0, 20)
          const smallText = [...document.querySelectorAll('body *')].filter(
            (el) => visible(el) && el.children.length === 0 && (el.innerText || '').trim() &&
              Number.parseFloat(getComputedStyle(el).fontSize) < 13.5
          ).map((el) => ({ text: el.innerText.trim().slice(0, 40), size: getComputedStyle(el).fontSize })).slice(0, 20)
          const canvas = document.querySelector('[data-testid="profile-knowledge-map"] canvas')
          let canvasPixels = 0
          if (canvas) {
            const ctx = canvas.getContext('2d', { willReadFrequently: true })
            const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data
            for (let i = 3; i < data.length; i += 4) if (data[i] > 0) canvasPixels += 1
          }
          const map = document.querySelector('.profile-map-layout')?.getBoundingClientRect()
          const graph = document.querySelector('.profile-map-canvas')?.getBoundingClientRect()
          const rail = document.querySelector('[data-testid="profile-node-evidence"]')?.getBoundingClientRect()
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            documentHeight: document.documentElement.scrollHeight,
            bodyTextLength: (document.body.innerText || '').trim().length,
            collisions, clipped, smallText, canvasPixels,
            layout: map && graph && rail ? {
              mapWidth: map.width, graphWidth: graph.width, railWidth: rail.width,
              graphRatio: graph.width / (graph.width + rail.width),
              overlap: Math.max(0, graph.right - rail.left),
            } : null,
          }
        }"""
    )


def capture_and_validate(page: Page, name: str, report: dict) -> dict:
    page.wait_for_timeout(700)
    metrics = page_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=False)
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    if metrics["documentWidth"] > metrics["viewport"][0]:
        raise AssertionError({"horizontal_overflow": metrics})
    if metrics["bodyTextLength"] < 500 or metrics["canvasPixels"] < 1_000:
        raise AssertionError({"blank_profile_or_graph": metrics})
    if metrics["collisions"] or metrics["clipped"] or metrics["smallText"]:
        raise AssertionError({"visual_defects": metrics})
    if not metrics["layout"] or metrics["layout"]["overlap"] > 1:
        raise AssertionError({"profile_columns_overlap": metrics})
    if not 0.68 <= metrics["layout"]["graphRatio"] <= 0.78:
        raise AssertionError({"profile_column_ratio": metrics})
    return metrics


def run_viewport(browser, viewport: tuple[int, int], session_payload: dict, report: dict) -> None:
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    page = context.new_page()
    install_session(page, session_payload)
    errors: list[dict] = []
    responses: list[dict] = []
    page.on("pageerror", lambda exc: errors.append({"type": "pageerror", "message": str(exc)}))
    page.on("console", lambda msg: errors.append({"type": "console", "message": msg.text}) if msg.type == "error" else None)
    page.on("requestfailed", lambda req: errors.append({"type": "requestfailed", "url": req.url, "message": str(req.failure)}))
    page.on("response", lambda response: responses.append({"url": response.url, "status": response.status}) if response.status >= 400 else None)
    suffix = f"{viewport[0]}x{viewport[1]}"
    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded", timeout=45_000)
        page.get_by_role("link", name="学习画像").wait_for(state="visible", timeout=45_000)
        errors.clear()
        responses.clear()
        with page.expect_response(
            lambda response: "/api/v1/m5/profile-summary" in response.url and response.status == 200,
            timeout=45_000,
        ) as summary_response:
            page.get_by_role("link", name="学习画像").click()
        page.wait_for_url(lambda url: "/profile/learning" in url, timeout=30_000)
        summary = summary_response.value.json()
        page.get_by_test_id("profile-knowledge-map").wait_for(state="visible", timeout=45_000)
        page.locator('[data-testid="profile-knowledge-map"] canvas').wait_for(state="visible", timeout=30_000)
        capture_and_validate(page, f"{suffix}-profile.png", report)

        graph = summary["knowledge_graph"]
        if graph["summary"]["nodeCount"] != 12 or not graph["edges"]:
            raise AssertionError({"incomplete_graph_payload": graph["summary"]})
        page.locator('[data-testid="profile-knowledge-map"] canvas').click(position={"x": 280, "y": 260})
        page.wait_for_timeout(300)
        evidence_text = page.get_by_test_id("profile-node-evidence").inner_text()
        if "下一步建议" not in evidence_text or "判断依据" not in evidence_text:
            raise AssertionError({"missing_evidence_rail": evidence_text})

        search = page.get_by_placeholder("检索知识点")
        search.fill(graph["nodes"][0]["name"])
        page.wait_for_timeout(250)
        if graph["nodes"][0]["name"] not in page.get_by_test_id("profile-node-evidence").inner_text():
            raise AssertionError("graph search did not select the matching knowledge node")
        page.get_by_role("button", name="重置视图").click()

        for label in ("概览", "数字孪生画像", "十维分析", "薄弱点归因", "成因分析", "教学建议"):
            tab = page.get_by_role("tab", name=label)
            tab.click()
            if tab.get_attribute("aria-selected") != "true":
                raise AssertionError(f"profile tab did not activate: {label}")
        page.get_by_role("tab", name="概览").click()
        page.get_by_role("button", name="编辑画像").click()
        page.get_by_role("heading", name="自定义编辑学情画像").wait_for(state="visible")
        page.get_by_role("button", name="取消").click()

        next_route = graph["nodes"][0]["nextAction"]["route"]
        search.fill(graph["nodes"][0]["name"])
        page.get_by_test_id("profile-node-evidence").get_by_role(
            "button", name=graph["nodes"][0]["nextAction"]["title"],
        ).click()
        page.wait_for_url(lambda url: url.removeprefix(BASE_URL) == next_route, timeout=30_000)
        report["checks"][f"{suffix}-interactions"] = {
            "selectedNode": graph["nodes"][0]["id"],
            "legacyTabs": 6,
            "editModal": "opened-and-closed",
            "nextRoute": next_route,
        }
        if errors or responses:
            raise AssertionError({"browser_errors": errors, "http_errors": responses})
    finally:
        report["browser_errors"].extend(errors)
        report["http_errors"].extend(responses)
        context.close()


def main() -> int:
    prepare_output()
    seed_fixture()
    before = learning_state_counts()
    report = {
        "schema_version": "f4-t02.profile-browser-e2e.v1",
        "result": "running",
        "viewport_contract": [[1440, 900], [1366, 768]],
        "database": str(DB_PATH),
        "screenshots": [], "checks": {}, "browser_errors": [], "http_errors": [],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    process = None
    try:
        env = os.environ.copy()
        with (OUTPUT_DIR / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                setup = browser.new_page()
                session_payload = login(setup)
                setup.close()
                for viewport in ((1440, 900), (1366, 768)):
                    run_viewport(browser, viewport, session_payload, report)
                browser.close()
        after = learning_state_counts()
        if before != after:
            raise AssertionError({"profile_browsing_mutated_learning_state": {"before": before, "after": after}})
        report["checks"]["read-only-database"] = {"before": before, "after": after}
        with sqlite3.connect(DB_PATH) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise AssertionError({"integrity_check": integrity})
        report["checks"]["database-integrity"] = integrity
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, text=True, timeout=20,
            )
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        try:
            wait_port(False, 15)
        except RuntimeError:
            pass
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
