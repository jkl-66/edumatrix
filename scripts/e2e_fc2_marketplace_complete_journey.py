from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path

from playwright.sync_api import sync_playwright

R = Path(__file__).resolve().parents[1]
O = R / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC2-EXIT" / "browser-e2e"
D = R / "outputs" / "_fc2_marketplace_complete_journey.db"
PORT = 8826
U = f"http://127.0.0.1:{PORT}"
PW = "MarketComplete-2026!"


def wait_port(expected: bool) -> None:
    for _ in range(300):
        with socket.socket() as sock: opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected: return
        time.sleep(0.2)
    raise RuntimeError("FC2 complete journey port timeout")


def auth(page, username: str, role: str) -> tuple[str, str]:
    result = page.request.post(U + "/api/auth/register", data={"username": username, "password": PW, "display_name": username})
    assert result.ok
    with sqlite3.connect(D) as db: db.execute("update users set role=? where username=?", (role, username)); db.commit()
    token = page.request.post(U + "/api/auth/login", form={"username": username, "password": PW}).json()["access_token"]
    return token, result.json()["user_id"]


def browser_state(page, token: str, username: str, role: str = "student") -> None:
    page.goto(U + "/login")
    page.evaluate("([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_onboarded','true')}", [token, username, role])


def insert_course(db, course_id: str, owner_id: str, stamp: str) -> None:
    manifest = json.dumps({"learning_objectives": ["可信训练", "证据治理"], "difficulty_band": "intermediate"}, ensure_ascii=False)
    db.execute("insert into courses(id,version,title,subject,description,content_origin,license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (course_id, "1.0", "AI 可信训练闭环", "人工智能", "公开市场完整旅程 v1", "https://example.invalid/fc2-complete", "CC BY 4.0", "private", "published", owner_id, "fc2-complete-v1", manifest))
    db.execute("insert into course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) values(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
        (f"cm-{stamp}", course_id, owner_id, "teacher", "active"))
    content = "可信训练需要来源、质量、版本和使用证据共同支撑。"
    db.execute("insert into course_documents(id,course_id,chapter_order,filename,file_type,file_size,title,content,tags,chunk_count,content_hash,source_path,license_text,status,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (f"doc-{stamp}", course_id, 1, "trust.md", "md", len(content.encode()), "可信训练", content, "[]", 1, hashlib.sha256(content.encode()).hexdigest(), "trust.md", "CC BY 4.0", "published"))
    db.execute("insert into source_documents(id,course_id,title,filename,file_format,content_hash,source_sha256,processed_sha256,file_size,source_url,source_path,license_text,parser_version,parser_metadata,parse_warnings,processing_error_code,processing_status,created_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
        (f"src-{stamp}", course_id, "可信训练来源", "trust.md", "md", "a" * 64, "b" * 64, "c" * 64, 128, "https://example.invalid/source", "trust.md", "CC BY 4.0", "fc2-exit", "{}", "[]", "", "ready"))


def publish(page, headers: dict[str, str], course_id: str, title: str, impact_kind: str | None = None) -> dict:
    row = page.request.post(U + "/api/v1/marketplace/listings", headers=headers, data={"course_id": course_id, "title": title,
        "summary": "来源许可可追溯的 AI 可信训练闭环课程", "category": "人工智能", "tags": ["AI", "可信训练", "中级"]}).json()
    for action in ("approve", "publish"):
        payload = {"action": action, "reason": "冻结合成课程来源许可并批准比赛演示", "expected_version": row["lock_version"]}
        if action == "publish" and impact_kind: payload["impact_kind"] = impact_kind
        response = page.request.post(U + f"/api/v1/marketplace/listings/{row['id']}/decisions", headers=headers, data=payload)
        assert response.ok, response.text(); row = response.json()
    return row


def main() -> int:
    O.mkdir(parents=True, exist_ok=True)
    for path in O.iterdir():
        if path.is_file(): path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(D) + suffix)
        if path.exists(): path.unlink()
    env = os.environ.copy(); env.update({"EDUMATRIX_DB_PATH": str(D), "EDUMATRIX_AUTH_SECRET_KEY": "fc2-complete",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "", "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0", "EDUMATRIX_PORT": str(PORT), "PYTHON_DOTENV_DISABLED": "1"})
    report = {"checks": {}, "screenshots": []}; process = None
    try:
        with (O / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=R, env=env, stdout=log, stderr=subprocess.STDOUT); wait_port(True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page(); stamp = str(int(time.time()))
                admin_name = f"fc2_exit_admin_{stamp}"; learner_name = f"fc2_exit_learner_{stamp}"; outsider_name = f"fc2_exit_outsider_{stamp}"
                admin_token, admin_id = auth(page, admin_name, "admin"); learner_token, learner_id = auth(page, learner_name, "student"); outsider_token, _ = auth(page, outsider_name, "student")
                ah = {"Authorization": "Bearer " + admin_token}; lh = {"Authorization": "Bearer " + learner_token}; oh = {"Authorization": "Bearer " + outsider_token}
                course_id = f"fc2-exit-course-{stamp}"
                with sqlite3.connect(D) as db:
                    insert_course(db, course_id, admin_id, stamp)
                    db.execute("insert into profile_snapshots(id,owner_public_id,legacy_student_id,profile_version,snapshot,content_hash,trace_id,created_at) values(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                        (f"ps-{stamp}", learner_id, learner_name, "fc2-exit-v1", json.dumps({"target_course": "AI 可信训练", "learning_goals": ["可信训练", "证据治理"], "knowledge_base": "中级"}, ensure_ascii=False), "d" * 64, f"trace-{stamp}")); db.commit()
                v1 = publish(page, ah, course_id, "AI 可信训练闭环 v1")

                browser_state(page, learner_token, learner_name); page.goto(U + "/marketplace")
                root = page.get_by_test_id("marketplace-workspace"); root.wait_for(timeout=30000)
                root.get_by_label("市场搜索").fill("可信训练"); root.get_by_role("button", name="筛选").click()
                card = root.get_by_test_id("market-card").filter(has_text="AI 可信训练闭环 v1"); card.wait_for()
                card.get_by_title("收藏当前版本").click(); root.get_by_text("已收藏当前市场版本", exact=False).wait_for()
                card = root.get_by_test_id("market-card").filter(has_text="AI 可信训练闭环 v1")
                card.get_by_title("查看版本评论").click(); comments = card.get_by_test_id("market-comments")
                comments.get_by_label("评论内容").fill("已核对当前冻结版本的来源、许可和课程结构。")
                comments.get_by_role("button", name="发布评论").click(); comments.get_by_text("已核对当前冻结版本", exact=False).wait_for()
                acquisition = page.request.post(U + f"/api/v1/marketplace/listings/{v1['id']}/acquisitions", headers=lh).json()
                with sqlite3.connect(D) as db:
                    db.execute("insert into learning_events(id,owner_public_id,course_id,event_type,schema_version,source,trace_id,object_type,object_id,payload,occurred_at,recorded_at) values(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                        (f"le-{stamp}", learner_id, acquisition["derived_course_id"], "course.resource.completed", "1.0", "browser-e2e", f"trace-use-{stamp}", "course", acquisition["derived_course_id"], "{}")); db.commit()
                review = page.request.put(U + f"/api/v1/marketplace/listings/{v1['id']}/review", headers=lh, data={"rating": 5, "body": "完成真实获取与学习事件后评价。"}); assert review.ok

                page.goto(U + "/marketplace/recommendations"); rec_root = page.get_by_test_id("marketplace-recommendations"); rec_root.wait_for()
                rec_root.get_by_role("button", name="生成并冻结推荐").click(); rec_root.get_by_text("已冻结推荐运行", exact=False).wait_for()
                rec = page.request.get(U + "/api/v1/marketplace/recommendations/latest", headers=lh).json(); assert rec["items"][0]["listing"]["id"] == v1["id"]

                page.goto(U + "/marketplace/forks"); fork_root = page.get_by_test_id("marketplace-fork-workspace"); fork_root.wait_for()
                fork_root.get_by_role("button", name="建立正式分叉").click(); fork_root.get_by_text("正式分叉已建立", exact=False).wait_for()
                fork_root.get_by_label("分叉修改摘要").fill("学习者本地实践版修改")
                fork_root.get_by_label("分叉课程标题").fill("AI 可信训练本地实践版")
                fork_root.get_by_label("分叉课程说明").fill("保留学习者本地实验与注释")
                fork_root.get_by_role("button", name="冻结新版本").click(); fork_root.get_by_text("本地修改已冻结", exact=False).wait_for()

                with sqlite3.connect(D) as db:
                    db.execute("update courses set version='2.0',title='AI 可信训练闭环上游 v2',description='上游重要修复',manifest_version='fc2-complete-v2' where id=?", (course_id,)); db.commit()
                v2 = publish(page, ah, course_id, "AI 可信训练闭环 v2", "severe_fix")
                page.goto(U + "/marketplace"); root = page.get_by_test_id("marketplace-workspace"); inbox = root.get_by_test_id("market-impact-inbox"); inbox.wait_for()
                inbox.get_by_text("市场课程发布重要修复", exact=True).wait_for(); page.screenshot(path=str(O / "01-update-notification.png"), full_page=True); report["screenshots"].append("01-update-notification.png")
                notice = page.request.get(U + "/api/v1/marketplace/impact-notifications", headers=lh).json()["items"][0]
                handled = page.request.post(U + f"/api/v1/marketplace/impact-notifications/{notice['id']}", headers=lh, data={"expected_version": notice["lock_version"], "action": "review_update"}); assert handled.ok

                page.goto(U + "/marketplace/forks"); fork_root = page.get_by_test_id("marketplace-fork-workspace"); diff = fork_root.get_by_test_id("fork-three-way-diff"); diff.wait_for()
                diff.get_by_text("course.title", exact=True).first.wait_for(); page.wait_for_timeout(500); page.screenshot(path=str(O / "02-three-way-decision.png"), full_page=True); report["screenshots"].append("02-three-way-decision.png")
                fork = page.request.get(U + "/api/v1/marketplace/forks", headers=lh).json()["forks"][0]
                denied_fork = page.request.post(U + f"/api/v1/marketplace/forks/{fork['id']}/versions", headers=oh, data={"expected_version": fork["lock_version"], "modification_summary": "外部账号越权修改", "patch": {"course": {"title": "越权标题"}}}); assert denied_fork.status == 403
                diff.get_by_role("button", name="保留全部本地").click(); fork_root.get_by_text("已切换新上游基线并保留全部本地内容", exact=True).wait_for()

                withdraw = page.request.post(U + f"/api/v1/marketplace/listings/{v1['id']}/decisions", headers=ah,
                    data={"action": "withdraw", "reason": "上游旧版本撤回并保留学习者历史副本", "expected_version": v1["lock_version"]}); assert withdraw.ok
                notices = page.request.get(U + "/api/v1/marketplace/impact-notifications", headers=lh).json()["items"]
                withdrawn = next(item for item in notices if item["type"] == "withdrawn")
                kept = page.request.post(U + f"/api/v1/marketplace/impact-notifications/{withdrawn['id']}", headers=lh,
                    data={"expected_version": withdrawn["lock_version"], "action": "keep_copy"}); assert kept.ok
                denied_rec = page.request.get(U + f"/api/v1/marketplace/recommendations/{rec['id']}", headers=oh); assert denied_rec.status == 403

                page.goto(U + "/marketplace/forks"); fork_root = page.get_by_test_id("marketplace-fork-workspace"); fork_root.get_by_text("AI 可信训练本地实践版", exact=True).first.wait_for()
                fork_root.get_by_text("当前没有待处理的上游版本", exact=True).wait_for(); page.reload(); fork_root = page.get_by_test_id("marketplace-fork-workspace"); fork_root.get_by_text("AI 可信训练本地实践版", exact=True).first.wait_for()
                page.wait_for_timeout(500)
                page.screenshot(path=str(O / "03-refresh-local-copy.png"), full_page=True); report["screenshots"].append("03-refresh-local-copy.png")
                page.set_viewport_size({"width": 390, "height": 844}); fork_root.get_by_text("独立版本历史", exact=True).scroll_into_view_if_needed(); page.wait_for_timeout(500)
                width = page.evaluate("document.documentElement.scrollWidth"); assert width <= 390
                page.screenshot(path=str(O / "04-mobile-local-copy.png"), full_page=True); report["screenshots"].append("04-mobile-local-copy.png")
                final_fork = page.request.get(U + "/api/v1/marketplace/forks", headers=lh).json()["forks"][0]
                with sqlite3.connect(D) as db:
                    derived = db.execute("select title,status from courses where id=?", (acquisition["derived_course_id"],)).fetchone()
                assert derived == ("AI 可信训练本地实践版", "published")
                report["checks"].update({"v1": v1["id"], "v2": v2["id"], "favorite": True, "comment": True, "verified_review": True,
                    "recommendation_run": rec["id"], "fork": final_fork["id"], "fork_versions": len(final_fork["versions"]),
                    "fork_decisions": len(final_fork["decisions"]), "notifications": len(notices), "withdraw_action": kept.json()["action"],
                    "derived_course": acquisition["derived_course_id"], "derived_status": derived[1], "outsider_fork": denied_fork.status,
                    "outsider_recommendation": denied_rec.status, "mobile_width": width})
                report["result"] = "passed"; context.close(); browser.close()
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True); process.wait(); wait_port(False)
        if D.exists():
            with sqlite3.connect(D) as source, sqlite3.connect(O / "fc2_complete_journey_evidence.db") as target:
                source.backup(target); report["checks"]["sqlite"] = target.execute("pragma integrity_check").fetchone()[0]
                for table in ("marketplace_comments", "marketplace_favorites", "marketplace_reviews", "marketplace_impact_notifications", "marketplace_forks", "marketplace_recommendation_runs"):
                    report["checks"][table] = target.execute(f"select count(*) from {table}").fetchone()[0]
                report["checks"]["migrations_042_046"] = target.execute("select count(*) from schema_migrations where version between '20260804_042' and '20260804_046'").fetchone()[0]
        (O / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
            for path in sorted(O.iterdir()) if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))]
        (O / "manifest.json").write_text(json.dumps({"files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
