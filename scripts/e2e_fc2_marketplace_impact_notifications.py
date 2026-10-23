from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path

from playwright.sync_api import sync_playwright

R = Path(__file__).resolve().parents[1]
O = R / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC2-003" / "browser-e2e"
D = R / "outputs" / "_fc2_marketplace_impact_e2e.db"
PORT = 8823
U = f"http://127.0.0.1:{PORT}"
PW = "MarketImpact-2026!"


def wait_port(expected: bool) -> None:
    for _ in range(300):
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError("impact E2E port state timeout")


def auth(page, username: str, role: str) -> tuple[str, str]:
    result = page.request.post(U + "/api/auth/register", data={"username": username, "password": PW, "display_name": username})
    assert result.ok
    with sqlite3.connect(D) as db:
        db.execute("update users set role=? where username=?", (role, username))
        db.commit()
    token = page.request.post(U + "/api/auth/login", form={"username": username, "password": PW}).json()["access_token"]
    return token, result.json()["user_id"]


def browser_state(page, token: str, username: str, role: str) -> None:
    page.goto(U + "/login")
    page.evaluate(
        "([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_onboarded','true')}",
        [token, username, role],
    )


def create_course(db, course_id: str, teacher_id: str, version: str, license_text: str, stamp: str) -> None:
    db.execute(
        "insert into courses(id,version,title,subject,description,content_origin,license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (course_id, version, "AI 可信训练通知版", "人工智能", f"市场影响通知课程 {version}", "https://example.invalid", license_text, "private", "published", teacher_id, f"fc2-impact-{version}", "{}"),
    )
    db.execute(
        "insert into course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) values(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
        (f"cm-{stamp}", course_id, teacher_id, "teacher", "active"),
    )


def main() -> int:
    O.mkdir(parents=True, exist_ok=True)
    for path in O.iterdir():
        if path.is_file(): path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(D) + suffix)
        if path.exists(): path.unlink()
    env = os.environ.copy()
    env.update({"EDUMATRIX_DB_PATH": str(D), "EDUMATRIX_AUTH_SECRET_KEY": "fc2-impact",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_PORT": str(PORT), "PYTHON_DOTENV_DISABLED": "1"})
    report = {"checks": {}, "screenshots": []}; process = None
    try:
        with (O / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=R, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page(); stamp = str(int(time.time()))
                teacher = f"fc2_impact_teacher_{stamp}"; learner = f"fc2_impact_learner_{stamp}"; outsider = f"fc2_impact_outsider_{stamp}"
                teacher_token, teacher_id = auth(page, teacher, "teacher")
                learner_token, learner_id = auth(page, learner, "student")
                outsider_token, _ = auth(page, outsider, "student")
                teacher_headers = {"Authorization": "Bearer " + teacher_token}; learner_headers = {"Authorization": "Bearer " + learner_token}
                course_id = f"fc2-impact-course-{stamp}"
                with sqlite3.connect(D) as db:
                    create_course(db, course_id, teacher_id, "1.0", "CC BY 4.0", stamp)
                    db.commit()
                first = page.request.post(U + "/api/v1/marketplace/listings", headers=teacher_headers, data={
                    "course_id": course_id, "title": "AI 可信训练影响通知 v1", "summary": "验证新版本与撤回影响通知",
                    "category": "人工智能", "tags": ["AI", "通知"],
                }).json()
                with sqlite3.connect(D) as db:
                    db.execute("update users set role='admin' where public_id=?", (teacher_id,)); db.commit()
                teacher_token = page.request.post(U + "/api/auth/login", form={"username": teacher, "password": PW}).json()["access_token"]
                teacher_headers = {"Authorization": "Bearer " + teacher_token}
                for action in ("approve", "publish"):
                    first = page.request.post(U + f"/api/v1/marketplace/listings/{first['id']}/decisions", headers=teacher_headers,
                        data={"action": action, "reason": "冻结课程和许可证审核通过并发布", "expected_version": first["lock_version"]}).json()
                acquisition = page.request.post(U + f"/api/v1/marketplace/listings/{first['id']}/acquisitions", headers=learner_headers).json()

                with sqlite3.connect(D) as db:
                    db.execute("update courses set version='2.0', description='修复重要错误后的课程版本' where id=?", (course_id,)); db.commit()
                second = page.request.post(U + "/api/v1/marketplace/listings", headers=teacher_headers, data={
                    "course_id": course_id, "title": "AI 可信训练影响通知 v2", "summary": "重要修复后的新版本",
                    "category": "人工智能", "tags": ["AI", "修复"],
                }).json()
                second = page.request.post(U + f"/api/v1/marketplace/listings/{second['id']}/decisions", headers=teacher_headers,
                    data={"action": "approve", "reason": "重要修复版本审核通过", "expected_version": second["lock_version"]}).json()
                second = page.request.post(U + f"/api/v1/marketplace/listings/{second['id']}/decisions", headers=teacher_headers,
                    data={"action": "publish", "reason": "重要错误已修复，请已获取用户检查更新", "expected_version": second["lock_version"], "impact_kind": "severe_fix"}).json()

                browser_state(page, learner_token, learner, "student")
                page.goto(U + "/marketplace")
                inbox = page.get_by_test_id("market-impact-inbox")
                inbox.get_by_text("受影响通知 · 未读 1", exact=False).wait_for(timeout=30000)
                inbox.get_by_text("市场课程发布重要修复", exact=True).wait_for()
                inbox.get_by_role("button", name="检查更新").click()
                page.get_by_text("已记录检查更新动作", exact=False).wait_for()
                inbox = page.get_by_test_id("market-impact-inbox")
                inbox.get_by_text("severe_fix · actioned · 本地收件箱", exact=True).wait_for()
                page.reload()
                page.get_by_test_id("market-impact-inbox").get_by_text("severe_fix · actioned · 本地收件箱", exact=True).wait_for()
                page.screenshot(path=str(O / "01-actioned-update-notification.png"), full_page=True)
                report["screenshots"].append("01-actioned-update-notification.png")

                withdrawn = page.request.post(U + f"/api/v1/marketplace/listings/{first['id']}/decisions", headers=teacher_headers,
                    data={"action": "withdraw", "reason": "旧版本来源撤回，历史副本继续保留", "expected_version": first["lock_version"]})
                assert withdrawn.ok
                page.reload(); inbox = page.get_by_test_id("market-impact-inbox")
                inbox.get_by_text("受影响通知 · 未读 1", exact=False).wait_for()
                inbox.get_by_text("已获取的市场课程来源已撤回", exact=True).wait_for()
                inbox.get_by_role("button", name="保留副本").click()
                page.get_by_text("已确认保留历史副本", exact=False).wait_for()
                inbox = page.get_by_test_id("market-impact-inbox")
                inbox.get_by_text("withdrawn · actioned · 本地收件箱", exact=True).wait_for()
                report["checks"].update({"new_version_action": "review_update", "withdrawal_action": "keep_copy", "notifications": 2})

                outsider_inbox = page.request.get(U + "/api/v1/marketplace/impact-notifications", headers={"Authorization": "Bearer " + outsider_token}).json()
                assert outsider_inbox["items"] == []
                report["checks"]["outsider_notifications"] = 0
                page.set_viewport_size({"width": 390, "height": 844}); inbox.scroll_into_view_if_needed(); page.wait_for_timeout(500)
                width = page.evaluate("document.documentElement.scrollWidth"); assert width <= 390
                page.screenshot(path=str(O / "02-mobile-impact-inbox.png"))
                report["screenshots"].append("02-mobile-impact-inbox.png"); report["checks"]["mobile_width"] = width
                with sqlite3.connect(D) as db:
                    assert db.execute("select status from courses where id=?", (acquisition["derived_course_id"],)).fetchone()[0] == "published"
                report["checks"]["historical_copy_status"] = "published"; report["result"] = "passed"
                context.close(); browser.close()
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True); process.wait(); wait_port(False)
        if D.exists():
            with sqlite3.connect(D) as source, sqlite3.connect(O / "marketplace_impact_evidence.db") as target:
                source.backup(target); report["checks"]["sqlite"] = target.execute("pragma integrity_check").fetchone()[0]
                report["checks"]["impact_events"] = target.execute("select count(*) from marketplace_impact_events").fetchone()[0]
                report["checks"]["impact_notices"] = target.execute("select count(*) from marketplace_impact_notifications").fetchone()[0]
        (O / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
            for path in sorted(O.iterdir()) if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))]
        (O / "manifest.json").write_text(json.dumps({"files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
