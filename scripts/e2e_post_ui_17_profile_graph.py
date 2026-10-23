"""POST-UI-17 isolated desktop check for the sparse profile knowledge graph."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PORT = 8899
BASE_URL = f"http://127.0.0.1:{PORT}"
COURSE_ID = "demo-course-rag-trust-v1"
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "post_ui_fixes" / "POST-UI-17_browser"
DB_PATH = OUTPUT_DIR / "runtime.db"


def seed_database() -> None:
    os.environ.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "post-ui-17-isolated-secret",
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
    sys.path.insert(0, str(ROOT))
    from app.competition_demo_seed import seed_competition_demo
    from app.database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        seed_competition_demo(db)
    finally:
        db.close()


def session_payload(page: Page) -> dict:
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
        const session = {state};
        localStorage.setItem('edumatrix_token', session.access_token);
        localStorage.setItem('edumatrix_username', session.username || 'lzz');
        localStorage.setItem('edumatrix_display_name', session.display_name || 'lzz');
        localStorage.setItem('edumatrix_role', session.role || 'student');
        localStorage.setItem('edumatrix_student_id', session.student_id || 'lzz');
        localStorage.setItem('edumatrix_onboarded', 'true');
        localStorage.setItem('edumatrix_course_id', '{COURSE_ID}');
        """
    )


def graph_metrics(page: Page) -> dict:
    return page.evaluate(
        """() => {
          const root = document.querySelector('[data-testid="profile-knowledge-map"]');
          const canvas = root?.querySelector('canvas');
          const layout = document.querySelector('.profile-map-layout')?.getBoundingClientRect();
          const graph = document.querySelector('.profile-map-canvas')?.getBoundingClientRect();
          const rail = document.querySelector('[data-testid="profile-node-evidence"]')?.getBoundingClientRect();
          let pixels = 0;
          if (canvas) {
            const ctx = canvas.getContext('2d', { willReadFrequently: true });
            const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
            for (let i = 3; i < data.length; i += 4) if (data[i] > 0) pixels += 1;
          }
          return {
            canvas: canvas ? { width: canvas.width, height: canvas.height } : null,
            canvasPixels: pixels,
            documentWidth: document.documentElement.scrollWidth,
            viewportWidth: innerWidth,
            layout: layout && graph && rail ? {
              mapWidth: layout.width,
              graphWidth: graph.width,
              railWidth: rail.width,
              graphRailOverlap: Math.max(0, graph.right - rail.left),
            } : null,
            graphText: root?.innerText || '',
            scrollables: [...document.querySelectorAll('*')]
              .filter((element) => element.scrollHeight > element.clientHeight + 20 && ['auto', 'scroll'].includes(getComputedStyle(element).overflowY))
              .map((element) => ({ tag: element.tagName, className: element.className?.toString?.() || '', scrollHeight: element.scrollHeight, clientHeight: element.clientHeight }))
              .slice(0, 8),
          };
        }"""
    )


def run_viewport(browser, viewport: tuple[int, int], payload: dict, report: dict) -> None:
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, locale="zh-CN")
    page = context.new_page()
    page.set_default_timeout(45_000)
    install_session(page, payload)
    errors: list[str] = []
    http_errors: list[dict] = []
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on("console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" else None)
    page.on("requestfailed", lambda request: errors.append(f"requestfailed: {request.url} {request.failure}"))
    page.on("response", lambda response: http_errors.append({"url": response.url, "status": response.status}) if response.status >= 400 else None)
    suffix = f"{viewport[0]}x{viewport[1]}"
    try:
        page.goto(f"{BASE_URL}/profile/learning?student_id=lzz&course_id={COURSE_ID}", wait_until="domcontentloaded")
        page.get_by_test_id("profile-knowledge-map").wait_for(state="visible")
        page.locator('[data-testid="profile-knowledge-map"] canvas').wait_for(state="visible")
        page.wait_for_timeout(900)
        first = graph_metrics(page)
        page.screenshot(path=str(OUTPUT_DIR / f"{suffix}-before.png"), full_page=True)
        if not first["canvas"] or first["canvasPixels"] < 1000:
            raise AssertionError({"blank_graph": first})
        if first["documentWidth"] > first["viewportWidth"]:
            raise AssertionError({"horizontal_overflow": first})
        if not first["layout"] or first["layout"]["graphRailOverlap"] > 1:
            raise AssertionError({"graph_evidence_overlap": first})

        bottom_scroll = page.evaluate(
            """() => {
              const candidates = [...document.querySelectorAll('*')]
                .filter((element) => element.scrollHeight > element.clientHeight + 20 && ['auto', 'scroll'].includes(getComputedStyle(element).overflowY))
                .sort((left, right) => right.scrollHeight - left.scrollHeight)
              const target = candidates[0]
              if (target) target.scrollTop = target.scrollHeight
              return target ? { tag: target.tagName, className: target.className?.toString?.() || '', scrollTop: target.scrollTop, scrollHeight: target.scrollHeight } : null
            }"""
        )
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUTPUT_DIR / f"{suffix}-bottom.png"), full_page=False)

        summary_response = page.request.get(
            f"{BASE_URL}/api/v1/m5/profile-summary?course_id={COURSE_ID}",
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        if not summary_response.ok:
            raise AssertionError({"profile_summary_status": summary_response.status})
        graph_nodes = summary_response.json().get("knowledge_graph", {}).get("nodes", [])
        if not graph_nodes:
            raise AssertionError("profile summary returned no graph nodes")
        search = page.get_by_placeholder("检索知识点")
        search.fill(str(graph_nodes[0].get("name") or ""))
        page.wait_for_timeout(300)
        selected_text = page.get_by_test_id("profile-node-evidence").inner_text()
        if str(graph_nodes[0].get("name") or "") not in selected_text:
            raise AssertionError({"search_selection_failed": selected_text})
        page.screenshot(path=str(OUTPUT_DIR / f"{suffix}-selected.png"), full_page=True)
        search.fill("")
        page.get_by_role("button", name="重置视图").click()
        page.wait_for_timeout(250)
        second = graph_metrics(page)
        if second["canvas"] != first["canvas"]:
            raise AssertionError({"canvas_geometry_changed_after_reset": {"before": first, "after": second}})
        if errors or http_errors:
            raise AssertionError({"browser_errors": errors, "http_errors": http_errors})
        report["viewports"][suffix] = {"before": first, "bottomScroll": bottom_scroll, "afterReset": second, "errors": errors, "httpErrors": http_errors}
    finally:
        context.close()


def main() -> int:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    seed_database()
    report = {"result": "running", "viewports": {}, "database": str(DB_PATH)}
    process = None
    try:
        env = os.environ.copy()
        log_path = OUTPUT_DIR / "backend.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    import urllib.request
                    with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except Exception:
                    time.sleep(0.25)
            else:
                raise RuntimeError("backend health check timed out")
            with sync_playwright() as playwright:
                setup = playwright.chromium.launch(headless=True)
                page = setup.new_page()
                payload = session_payload(page)
                page.close()
                for viewport in ((1440, 900), (1366, 768)):
                    run_viewport(setup, viewport, payload, report)
                setup.close()
        with sqlite3.connect(DB_PATH) as db:
            report["databaseIntegrity"] = db.execute("PRAGMA integrity_check").fetchone()[0]
            report["foreignKeyViolations"] = len(db.execute("PRAGMA foreign_key_check").fetchall())
        if report["databaseIntegrity"] != "ok" or report["foreignKeyViolations"]:
            raise AssertionError(report)
        report["result"] = "passed"
        return 0
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=20)
        report["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
