"""R3-09 complete student golden loop through visible UI only."""
from __future__ import annotations
import json, os, socket, subprocess, sys, time, traceback, sqlite3
from pathlib import Path
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/竞品融合重构执行/evidence/R3-09"
DB = OUTPUT / "r3_09_runtime.db"
PORT = int(os.environ.get("EDUMATRIX_R3_09_PORT", "8900"))
BASE = f"http://127.0.0.1:{PORT}"
COURSE_ID = "demo-course-rag-trust-v1"

def wait_port(expected, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened == expected: return
        time.sleep(.2)
    raise RuntimeError(f"port {PORT} state mismatch")

def diagnostics(page, report, scope):
    page.on("response", lambda r: report["http_errors"].append({"scope": scope, "status": r.status, "url": r.url}) if r.status >= 400 else None)
    page.on("requestfailed", lambda r: report["failed_requests"].append({"scope": scope, "url": r.url, "failure": r.failure}) if r.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda e: report["page_errors"].append({"scope": scope, "error": str(e)}))
    page.on("console", lambda m: report["console_errors"].append({"scope": scope, "text": m.text}) if m.type == "error" else None)

def login(page: Page, index: int, landing: str):
    page.goto(BASE + "/login", wait_until="domcontentloaded", timeout=60000)
    buttons = page.locator(".grid.grid-cols-2.gap-2 button")
    buttons.nth(index).wait_for(state="visible", timeout=30000)
    buttons.nth(index).click()
    page.locator("button.w-full").first.click()
    page.wait_for_function("p => location.pathname === p", arg=landing, timeout=30000)

def shot(page, report, name):
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUTPUT / name), full_page=True)
    report["screenshots"].append(name)

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for p in OUTPUT.iterdir():
        if p.is_file(): p.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB), "EDUMATRIX_AUTH_SECRET_KEY": "r3-09-isolated-auth-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_SANDBOX_MODE": "trusted_local",
        "EDUMATRIX_DEMO_MODE": "1", "EDUMATRIX_RELOAD": "0", "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT), "PYTHON_DOTENV_DISABLED": "1", "PYTHONUNBUFFERED": "1",
    })
    report = {"schema_version": "r3-09.student-golden-loop-ui-only.v1", "screenshots": [], "http_errors": [], "failed_requests": [], "console_errors": [], "page_errors": []}
    process = browser = None
    code = 1
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                admin_ctx = browser.new_context(viewport={"width":1440,"height":1000}, locale="zh-CN")
                admin = admin_ctx.new_page(); diagnostics(admin, report, "admin")
                login(admin, 2, "/competition-showcase")
                admin.get_by_role("button", name="一键初始化演示数据").click()
                admin.get_by_text("3 / 3", exact=True).wait_for(timeout=30000)
                admin_ctx.close()
                ctx = browser.new_context(viewport={"width":1440,"height":1000}, locale="zh-CN")
                page = ctx.new_page(); page.set_default_timeout(20000); diagnostics(page, report, "student-desktop")
                login(page, 1, "/")
                # Diagnostic through course -> resources -> formal assessment.
                page.get_by_test_id("competition-demo-context-dashboard").get_by_role("button", name="查看主课程与来源").click()
                page.wait_for_function("location.pathname === '/knowledge'", timeout=30000)
                page.get_by_test_id("competition-demo-sources").get_by_test_id("open-demo-diagnostic").click()
                page.get_by_test_id("assessment-workspace").wait_for(timeout=30000)
                page.get_by_test_id("cat-next").click()
                stage = page.get_by_test_id("assessment-question"); stage.wait_for(timeout=30000)
                option = stage.locator("input[type=radio]").first
                if option.count(): option.check()
                else: stage.get_by_role("button").filter(has_text="正确").first.click()
                page.get_by_test_id("assessment-submit").click()
                page.get_by_test_id("profile-summary").wait_for(timeout=30000)
                report["diagnostic"] = {"submitted": True, "profile_summary_visible": True}
                shot(page, report, "01-diagnostic-profile.png")
                # Path draft and confirmation through visible navigation.
                page.get_by_role("link", name="学习路径", exact=True).first.click()
                page.wait_for_function("location.pathname === '/learning-path'", timeout=30000)
                path_panel = page.get_by_test_id("textbook-path-draft"); path_panel.wait_for(timeout=30000)
                if path_panel.get_by_test_id("generate-textbook-path-draft").count():
                    path_panel.get_by_test_id("generate-textbook-path-draft").click()
                    path_panel.get_by_test_id("confirm-textbook-path-draft").wait_for(timeout=30000)
                    path_panel.get_by_test_id("confirm-textbook-path-draft").click()
                path_panel.get_by_text("正式版本", exact=True).wait_for(timeout=30000)
                report["path"] = {"confirmed": True}
                shot(page, report, "02-confirmed-learning-path.png")
                # Continue the first task and submit the visible strong-evidence action.
                page.get_by_role("link", name="首页", exact=True).first.click()
                page.get_by_test_id("dashboard-today-tasks").wait_for(timeout=30000)
                page.get_by_test_id("dashboard-today-tasks").get_by_role("button", name="继续当前任务").click()
                page.wait_for_function("location.pathname === '/workspace'", timeout=30000)
                page.get_by_test_id("workspace-today-task-0").get_by_role("button", name="继续").click()
                # The confirmed path may be replanned, so locate the first visible
                # active node that still exposes the strong-evidence action.
                pending_node = page.locator("article[id^='workspace-node-']").filter(
                    has=page.get_by_role("button", name="提交复测通过")
                ).first
                pending_node.wait_for(state="visible", timeout=30000)
                with page.expect_response(
                    lambda response: "/api/v1/m5/learning-events" in response.url
                    and response.status == 201,
                    timeout=30000,
                ):
                    pending_node.get_by_role("button", name="提交复测通过").click()
                page.get_by_text("强证据已提交，路径状态已重新计算。", exact=True).wait_for(timeout=30000)
                report["learning_task"] = {"completed": True}
                # Wrong answer, feedback, learner misconception confirmation, then queue.
                exercise_tab = page.get_by_test_id("learning-object-tab-exercise")
                exercise_tab.wait_for(state="visible", timeout=30000)
                exercise_tab.click()
                exercise = page.get_by_test_id("learning-object-exercise"); exercise.wait_for(timeout=30000)
                # The seeded judgment item presents the incorrect answer as the
                # final visible option; select it through the rendered form.
                exercise.locator("input[type=radio]").last.check()
                page.get_by_test_id("workspace-exercise-submit").click()
                decision = page.get_by_test_id("workspace-misconception-decision"); decision.wait_for(timeout=30000)
                decision.get_by_test_id("workspace-misconception-accept").click()
                page.get_by_text("错因决定已记录", exact=False).wait_for(timeout=30000)
                report["feedback"] = {"wrong_answer": True, "misconception_confirmed": True}
                page.get_by_role("link", name="学习画像", exact=True).first.click()
                profile_summary = page.get_by_test_id("profile-summary")
                profile_summary.wait_for(timeout=30000)
                report["profile"] = {
                    "summary_visible": True,
                    "summary_text": profile_summary.inner_text()[:2000],
                }
                shot(page, report, "03-feedback-profile-return.png")
                page.get_by_role("link", name="复习中心", exact=True).first.click()
                page.wait_for_function("location.pathname === '/review'", timeout=30000)
                page.wait_for_timeout(1000)
                report["review_debug"] = {
                    "url": page.url,
                    "visible_text": page.locator("body").inner_text()[:4000],
                    "main_html": page.locator("main").first.inner_html()[:4000]
                    if page.locator("main").count() else "",
                }
                shot(page, report, "04-review-arrival.png")
                queue = page.locator(".unified-queue")
                queue.wait_for(state="visible", timeout=30000)
                queue.get_by_text("已确认错因", exact=True).wait_for(timeout=30000)
                report["review"] = {"confirmed_item_visible": True}
                page.reload(wait_until="domcontentloaded", timeout=60000)
                page.wait_for_function("location.pathname === '/review'", timeout=30000)
                page.locator(".unified-queue").wait_for(state="visible", timeout=30000)
                report["refresh"] = {"review_restored": True}
                ctx.close(); browser.close(); browser = None
                mobile_ctx = pw.chromium.launch(channel="chrome", headless=True).new_context(viewport={"width":390,"height":844}, locale="zh-CN")
                mobile = mobile_ctx.new_page(); diagnostics(mobile, report, "student-mobile"); login(mobile, 1, "/")
                mobile.goto(BASE + "/review", wait_until="domcontentloaded", timeout=60000)
                mobile.wait_for_function("location.pathname === '/review'", timeout=30000)
                mobile_queue = mobile.locator(".unified-queue")
                mobile_queue.wait_for(state="visible", timeout=30000)
                overflow = mobile.evaluate("document.documentElement.scrollWidth > innerWidth")
                assert not overflow
                bounds = mobile_queue.evaluate("element => { const r=element.getBoundingClientRect(); return {left:r.left,right:r.right,viewport:innerWidth} }")
                assert bounds["left"] >= 0 and bounds["right"] <= bounds["viewport"]
                report["mobile"] = {"viewport": [390, 844], "horizontal_overflow": overflow, "bounds": bounds}
                shot(mobile, report, "05-mobile-review.png")
                mobile_ctx.close()
            with sqlite3.connect(DB) as conn:
                report["database_audit"] = {"integrity": conn.execute("pragma integrity_check").fetchone()[0], "foreign_key_violations": len(conn.execute("pragma foreign_key_check").fetchall())}
            assert report["database_audit"] == {"integrity":"ok", "foreign_key_violations":0}
            assert not report["http_errors"] and not report["failed_requests"] and not report["console_errors"] and not report["page_errors"]
            report["result"] = "passed"; code = 0
    except Exception as exc:
        report["result"] = "failed"; report["failure"] = repr(exc); report["traceback"] = traceback.format_exc()
    finally:
        if browser is not None:
            try: browser.close()
            except Exception: pass
        if process is not None and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20); process.wait(timeout=5)
            wait_port(False, 15)
        for suffix in ("-wal", "-shm"):
            try: DB.with_name(DB.name + suffix).unlink(missing_ok=True)
            except PermissionError: pass
        report["process_cleanup"] = {"service_stopped": process is None or process.poll() is not None, "port_released": socket.socket().connect_ex(("127.0.0.1", PORT)) != 0}
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"result":report.get("result"),"failure":report.get("failure"),"cleanup":report.get("process_cleanup")}, ensure_ascii=True)); return code

if __name__ == "__main__": raise SystemExit(main())
