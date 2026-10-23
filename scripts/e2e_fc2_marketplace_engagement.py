from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path

from playwright.sync_api import sync_playwright

R = Path(__file__).resolve().parents[1]
O = R / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC2-002" / "browser-e2e"
D = R / "outputs" / "_fc2_marketplace_engagement_e2e.db"
PORT = 8822
U = f"http://127.0.0.1:{PORT}"
PW = "MarketEngagement-2026!"


def wait_port(opened: bool) -> None:
    for _ in range(300):
        with socket.socket() as sock:
            current = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if current is opened:
            return
        time.sleep(0.2)
    raise RuntimeError("marketplace engagement E2E port did not reach expected state")


def auth(page, username: str, role: str) -> tuple[str, str]:
    registered = page.request.post(U + "/api/auth/register", data={"username": username, "password": PW, "display_name": username})
    assert registered.ok
    with sqlite3.connect(D) as db:
        db.execute("update users set role=? where username=?", (role, username))
        db.commit()
    login = page.request.post(U + "/api/auth/login", form={"username": username, "password": PW})
    return login.json()["access_token"], registered.json()["user_id"]


def browser_state(page, token: str, username: str, role: str) -> None:
    page.goto(U + "/login")
    page.evaluate(
        "([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_onboarded','true')}",
        [token, username, role],
    )


def main() -> int:
    O.mkdir(parents=True, exist_ok=True)
    for path in O.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(D) + suffix)
        if path.exists():
            path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(D), "EDUMATRIX_AUTH_SECRET_KEY": "fc2-engagement",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_PORT": str(PORT), "PYTHON_DOTENV_DISABLED": "1",
    })
    report = {"checks": {}, "screenshots": []}
    process = None
    try:
        with (O / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=R, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                stamp = str(int(time.time()))
                teacher = f"fc2_eng_teacher_{stamp}"
                learner = f"fc2_eng_learner_{stamp}"
                teacher_token, teacher_id = auth(page, teacher, "teacher")
                learner_token, learner_id = auth(page, learner, "student")
                reviewer_credentials = [auth(page, f"fc2_eng_reviewer_{index}_{stamp}", "student") for index in range(2)]
                course_id = f"fc2-engagement-course-{stamp}"
                with sqlite3.connect(D) as db:
                    db.execute(
                        "insert into courses(id,version,title,subject,description,content_origin,license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                        (course_id, "1.0", "AI 可信训练评价版", "人工智能", "使用后评价演示", "https://example.invalid", "CC BY 4.0", "private", "published", teacher_id, "fc2-eng-v1", "{}"),
                    )
                    db.execute(
                        "insert into course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) values(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                        (f"cm-{stamp}", course_id, teacher_id, "teacher", "active"),
                    )
                    db.commit()
                teacher_headers = {"Authorization": "Bearer " + teacher_token}
                learner_headers = {"Authorization": "Bearer " + learner_token}
                listing = page.request.post(U + "/api/v1/marketplace/listings", headers=teacher_headers, data={
                    "course_id": course_id, "title": "AI 可信训练使用后评价版", "summary": "验证收藏与有证据评价分离",
                    "category": "人工智能", "tags": ["AI", "评价"],
                }).json()
                with sqlite3.connect(D) as db:
                    db.execute("update users set role='admin' where public_id=?", (teacher_id,))
                    db.commit()
                teacher_token = page.request.post(U + "/api/auth/login", form={"username": teacher, "password": PW}).json()["access_token"]
                teacher_headers = {"Authorization": "Bearer " + teacher_token}
                for action in ("approve", "publish"):
                    listing = page.request.post(
                        U + f"/api/v1/marketplace/listings/{listing['id']}/decisions", headers=teacher_headers,
                        data={"action": action, "reason": "冻结内容与许可证审核通过并批准发布", "expected_version": listing["lock_version"]},
                    ).json()

                browser_state(page, learner_token, learner, "student")
                page.goto(U + "/marketplace")
                card = page.get_by_test_id("market-card").filter(has_text="AI 可信训练使用后评价版")
                card.wait_for(timeout=30000)
                card.get_by_title("收藏当前版本").click()
                page.get_by_text("已收藏当前市场版本", exact=False).wait_for()
                card = page.get_by_test_id("market-card").filter(has_text="AI 可信训练使用后评价版")
                card.get_by_title("已验证使用后评价").click()
                engagement = card.get_by_test_id("market-engagement")
                engagement.get_by_text("请先获取当前版本课程副本", exact=True).wait_for()
                denied = page.request.put(
                    U + f"/api/v1/marketplace/listings/{listing['id']}/review", headers=learner_headers,
                    data={"rating": 5, "body": "无使用证据的评价"},
                )
                assert denied.status == 422
                acquisition = page.request.post(U + f"/api/v1/marketplace/listings/{listing['id']}/acquisitions", headers=learner_headers).json()
                with sqlite3.connect(D) as db:
                    db.execute(
                        "insert into learning_events(id,owner_public_id,course_id,event_type,schema_version,source,trace_id,object_type,object_id,payload,occurred_at,recorded_at) values(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                        (f"le-{stamp}", learner_id, acquisition["derived_course_id"], "course.resource.opened", "1.0", "browser-e2e", f"trace-{stamp}", "course", acquisition["derived_course_id"], "{}"),
                    )
                    db.commit()
                page.reload()
                card = page.get_by_test_id("market-card").filter(has_text="AI 可信训练使用后评价版")
                card.get_by_title("已验证使用后评价").click()
                engagement = card.get_by_test_id("market-engagement")
                engagement.get_by_text("已获取当前版本课程副本", exact=True).wait_for()
                engagement.get_by_label("使用后评分").select_option("4")
                engagement.get_by_label("使用后评价").fill("已导入并打开课程资源，结构清晰。")
                engagement.get_by_role("button", name="提交评价").click()
                engagement.get_by_text("学习事件 1", exact=False).wait_for()
                engagement.get_by_label("使用后评分").select_option("5")
                engagement.get_by_label("使用后评价").fill("完成浏览后更新为五星，来源清晰。")
                engagement.get_by_role("button", name="更新评价").click()
                engagement.get_by_text("评价修订 2", exact=False).wait_for()

                for index, ((token, _), rating) in enumerate(zip(reviewer_credentials, (4, 3))):
                    headers = {"Authorization": "Bearer " + token}
                    page.request.post(U + f"/api/v1/marketplace/listings/{listing['id']}/acquisitions", headers=headers)
                    saved = page.request.put(
                        U + f"/api/v1/marketplace/listings/{listing['id']}/review", headers=headers,
                        data={"rating": rating, "body": f"第 {index + 2} 位已验证使用者评价"},
                    )
                    assert saved.ok
                page.reload()
                card = page.get_by_test_id("market-card").filter(has_text="AI 可信训练使用后评价版")
                card.get_by_text("4 / 5", exact=True).wait_for()
                card.get_by_title("已验证使用后评价").click()
                engagement = card.get_by_test_id("market-engagement")
                engagement.get_by_text("当前 3 个", exact=False).wait_for()
                engagement.get_by_text("评价修订 2", exact=False).wait_for()
                page.screenshot(path=str(O / "01-verified-rating-threshold.png"), full_page=True)
                report["screenshots"].append("01-verified-rating-threshold.png")
                report["checks"].update({"review_without_use": 422, "learning_event_count": 1, "review_history": 2, "review_count": 3, "average_rating": 4.0})

                page.set_viewport_size({"width": 390, "height": 844})
                engagement.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                width = page.evaluate("document.documentElement.scrollWidth")
                assert width <= 390
                page.screenshot(path=str(O / "02-mobile-verified-rating.png"))
                report["screenshots"].append("02-mobile-verified-rating.png")
                report["checks"]["mobile_width"] = width
                report["result"] = "passed"
                context.close()
                browser.close()
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            process.wait()
            wait_port(False)
        if D.exists():
            with sqlite3.connect(D) as source, sqlite3.connect(O / "marketplace_engagement_evidence.db") as target:
                source.backup(target)
                report["checks"]["sqlite"] = target.execute("pragma integrity_check").fetchone()[0]
                report["checks"]["favorites"] = target.execute("select count(*) from marketplace_favorites where status='active'").fetchone()[0]
                report["checks"]["reviews"] = target.execute("select count(*) from marketplace_reviews").fetchone()[0]
                report["checks"]["review_events"] = target.execute("select count(*) from marketplace_review_events").fetchone()[0]
        (O / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [
            {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
            for path in sorted(O.iterdir()) if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (O / "manifest.json").write_text(json.dumps({"files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
