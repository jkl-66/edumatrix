from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path

from playwright.sync_api import sync_playwright

R = Path(__file__).resolve().parents[1]
O = R / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC2-005" / "browser-e2e"
D = R / "outputs" / "_fc2_marketplace_recommendation_e2e.db"
PORT = 8825
U = f"http://127.0.0.1:{PORT}"
PW = "MarketRecommend-2026!"


def wait_port(expected: bool) -> None:
    for _ in range(300):
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected:
            return
        time.sleep(0.2)
    raise RuntimeError("recommendation E2E port state timeout")


def auth(page, username: str, role: str) -> tuple[str, str]:
    result = page.request.post(U + "/api/auth/register", data={"username": username, "password": PW, "display_name": username})
    assert result.ok
    with sqlite3.connect(D) as db:
        db.execute("update users set role=? where username=?", (role, username)); db.commit()
    token = page.request.post(U + "/api/auth/login", form={"username": username, "password": PW}).json()["access_token"]
    return token, result.json()["user_id"]


def browser_state(page, token: str, username: str) -> None:
    page.goto(U + "/login")
    page.evaluate("([t,n])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','student');localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_onboarded','true')}", [token, username])


def insert_course(db, course_id: str, teacher_id: str, stamp: str, *, title: str, license_text: str, source: bool) -> None:
    manifest = json.dumps({"learning_objectives": ["可信训练", "人工智能"], "difficulty_band": "intermediate"}, ensure_ascii=False)
    db.execute("insert into courses(id,version,title,subject,description,content_origin,license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (course_id, "1.0", title, "人工智能", "冻结合成课程用于推荐演示", "https://example.invalid/fc2-recommend" if source else "", license_text, "private", "published", teacher_id, "fc2-rec-v1", manifest))
    db.execute("insert into course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) values(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
        (f"cm-{course_id}", course_id, teacher_id, "teacher", "active"))
    body = "可信训练需要来源追踪、质量检查与难度适配。"
    db.execute("insert into course_documents(id,course_id,chapter_order,filename,file_type,file_size,title,content,tags,chunk_count,content_hash,source_path,license_text,status,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (f"doc-{course_id}", course_id, 1, "intro.md", "md", len(body.encode()), "可信训练导论", body, "[]", 1, hashlib.sha256(body.encode()).hexdigest(), "intro.md", license_text, "published"))
    if source:
        db.execute("insert into source_documents(id,course_id,title,filename,file_format,content_hash,source_sha256,processed_sha256,file_size,source_url,source_path,license_text,parser_version,parser_metadata,parse_warnings,processing_error_code,processing_status,created_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            (f"src-{course_id}", course_id, "可信训练导论", "intro.md", "md", "a" * 64, "b" * 64, "c" * 64, 128, "https://example.invalid/source", "intro.md", license_text, "fc2-e2e", "{}", "[]", "", "ready"))


def publish(page, headers: dict[str, str], course_id: str, title: str, tags: list[str]) -> dict:
    row = page.request.post(U + "/api/v1/marketplace/listings", headers=headers, data={"course_id": course_id, "title": title, "summary": "面向人工智能可信训练的来源可追溯课程", "category": "人工智能", "tags": tags}).json()
    for action in ("approve", "publish"):
        row = page.request.post(U + f"/api/v1/marketplace/listings/{row['id']}/decisions", headers=headers,
            data={"action": action, "reason": "冻结合成课程来源许可证并批准演示发布", "expected_version": row["lock_version"]}).json()
    return row


def main() -> int:
    O.mkdir(parents=True, exist_ok=True)
    for path in O.iterdir():
        if path.is_file(): path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(D) + suffix)
        if path.exists(): path.unlink()
    env = os.environ.copy(); env.update({"EDUMATRIX_DB_PATH": str(D), "EDUMATRIX_AUTH_SECRET_KEY": "fc2-recommendation",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "", "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0", "EDUMATRIX_PORT": str(PORT), "PYTHON_DOTENV_DISABLED": "1"})
    report = {"checks": {}, "screenshots": []}; process = None
    try:
        with (O / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "run.py"], cwd=R, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page(); stamp = str(int(time.time()))
                admin_name = f"fc2_rec_admin_{stamp}"; learner_name = f"fc2_rec_learner_{stamp}"; outsider_name = f"fc2_rec_outsider_{stamp}"
                admin_token, admin_id = auth(page, admin_name, "admin")
                learner_token, learner_id = auth(page, learner_name, "student")
                outsider_token, _ = auth(page, outsider_name, "student")
                admin_headers = {"Authorization": "Bearer " + admin_token}; learner_headers = {"Authorization": "Bearer " + learner_token}
                with sqlite3.connect(D) as db:
                    insert_course(db, f"fc2-rec-good-{stamp}", admin_id, stamp, title="AI 可信训练实战", license_text="CC BY 4.0", source=True)
                    insert_course(db, f"fc2-rec-limited-{stamp}", admin_id, stamp, title="通用办公基础", license_text="", source=False)
                    db.execute("insert into profile_snapshots(id,owner_public_id,legacy_student_id,profile_version,snapshot,content_hash,trace_id,created_at) values(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                        (f"ps-rec-{stamp}", learner_id, learner_name, "fc2-rec-v1", json.dumps({"target_course": "AI 可信训练", "learning_goals": ["可信训练", "人工智能"], "knowledge_base": "中级", "cognitive_load": 0.4}, ensure_ascii=False), "d" * 64, f"trace-rec-{stamp}"))
                    db.commit()
                good = publish(page, admin_headers, f"fc2-rec-good-{stamp}", "AI 可信训练实战", ["AI", "可信训练", "中级"])
                limited = publish(page, admin_headers, f"fc2-rec-limited-{stamp}", "通用办公基础", ["办公", "入门"])

                browser_state(page, learner_token, learner_name); page.goto(U + "/marketplace/recommendations")
                root = page.get_by_test_id("marketplace-recommendations"); root.wait_for(timeout=30000)
                root.get_by_role("button", name="生成并冻结推荐").click()
                root.get_by_text("已冻结推荐运行", exact=False).wait_for(timeout=30000)
                first_card = root.locator("article.result").first
                first_card.get_by_text("AI 可信训练实战", exact=True).wait_for()
                first_card.get_by_text("查看 7 项分数贡献与证据", exact=True).click()
                assert first_card.locator(".features article").count() == 7
                first_card.get_by_text("收藏热度（辅助）", exact=True).wait_for()
                root.get_by_text("暂不适用", exact=True).wait_for()
                run_id = page.request.get(U + "/api/v1/marketplace/recommendations/latest", headers=learner_headers).json()["id"]
                page.evaluate("scrollTo(0,0)"); page.wait_for_timeout(600)
                page.screenshot(path=str(O / "01-desktop-explainable-ranking.png"), full_page=True)
                report["screenshots"].append("01-desktop-explainable-ranking.png")

                first_card.get_by_role("button", name="获取课程副本").click()
                root.get_by_text("已获取课程副本", exact=False).wait_for()
                acquisition = page.request.post(U + f"/api/v1/marketplace/listings/{good['id']}/acquisitions", headers=learner_headers).json()
                with sqlite3.connect(D) as db:
                    db.execute("insert into learning_events(id,owner_public_id,course_id,event_type,schema_version,source,trace_id,object_type,object_id,payload,occurred_at,recorded_at) values(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                        (f"le-rec-{stamp}", learner_id, acquisition["derived_course_id"], "course.resource.completed", "1.0", "browser-e2e", f"trace-use-{stamp}", "course", acquisition["derived_course_id"], "{}")); db.commit()
                root.get_by_role("button", name="生成并冻结推荐").click(); root.get_by_text("已冻结推荐运行", exact=False).wait_for()
                latest = page.request.get(U + "/api/v1/marketplace/recommendations/latest", headers=learner_headers).json()
                assert latest["id"] != run_id
                top = next(item for item in latest["items"] if item["listing"]["id"] == good["id"])
                assert top["features"]["verified_use"]["evidence"]["learning_event_count"] == 1
                assert top["features"]["popularity"]["weight"] == 0.02
                denied = page.request.get(U + f"/api/v1/marketplace/recommendations/{latest['id']}", headers={"Authorization": "Bearer " + outsider_token})
                assert denied.status == 403
                page.reload(); root = page.get_by_test_id("marketplace-recommendations"); root.get_by_text(latest["id"], exact=False).wait_for(timeout=30000)
                root.get_by_text("AI 可信训练实战", exact=True).first.wait_for()
                page.evaluate("scrollTo(0,0)"); page.wait_for_timeout(800)
                page.screenshot(path=str(O / "02-desktop-refresh-evidence.png"), full_page=True)
                report["screenshots"].append("02-desktop-refresh-evidence.png")
                page.set_viewport_size({"width": 390, "height": 844}); root.locator("article.result").first.scroll_into_view_if_needed(); page.wait_for_timeout(500)
                width = page.evaluate("document.documentElement.scrollWidth"); assert width <= 390
                page.screenshot(path=str(O / "03-mobile-recommendation.png"), full_page=True)
                report["screenshots"].append("03-mobile-recommendation.png")
                report["checks"].update({"initial_run": run_id, "evidence_changed_run": latest["id"], "results": latest["result_count"],
                    "top_listing": top["listing"]["id"], "learning_event_count": 1, "feature_count": len(top["features"]),
                    "popularity_weight": top["features"]["popularity"]["weight"], "outsider_status": denied.status,
                    "not_applicable_listing": limited["id"], "mobile_width": width})
                report["result"] = "passed"; context.close(); browser.close()
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True); process.wait(); wait_port(False)
        if D.exists():
            with sqlite3.connect(D) as source, sqlite3.connect(O / "marketplace_recommendation_evidence.db") as target:
                source.backup(target); report["checks"]["sqlite"] = target.execute("pragma integrity_check").fetchone()[0]
                report["checks"]["runs"] = target.execute("select count(*) from marketplace_recommendation_runs").fetchone()[0]
                report["checks"]["result_rows"] = target.execute("select count(*) from marketplace_recommendation_results").fetchone()[0]
                report["checks"]["migration"] = target.execute("select count(*) from schema_migrations where version='20260804_046'").fetchone()[0]
                report["checks"]["triggers"] = target.execute("select count(*) from sqlite_master where type='trigger' and name like 'trg_marketplace_recommendation_%'").fetchone()[0]
        (O / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
            for path in sorted(O.iterdir()) if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))]
        (O / "manifest.json").write_text(json.dumps({"files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
