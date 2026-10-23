from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path

from playwright.sync_api import sync_playwright

R = Path(__file__).resolve().parents[1]
O = R / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC2-004" / "browser-e2e"
D = R / "outputs" / "_fc2_marketplace_fork_e2e.db"
PORT = 8824
U = f"http://127.0.0.1:{PORT}"
PW = "MarketFork-2026!"


def wait_port(expected: bool) -> None:
    for _ in range(300):
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected: return
        time.sleep(0.2)
    raise RuntimeError("fork E2E port state timeout")


def auth(page, username: str, role: str) -> tuple[str, str]:
    result = page.request.post(U + "/api/auth/register", data={"username": username, "password": PW, "display_name": username})
    assert result.ok
    with sqlite3.connect(D) as db:
        db.execute("update users set role=? where username=?", (role, username)); db.commit()
    token = page.request.post(U + "/api/auth/login", form={"username": username, "password": PW}).json()["access_token"]
    return token, result.json()["user_id"]


def browser_state(page, token: str, username: str, role: str) -> None:
    page.goto(U + "/login")
    page.evaluate("([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_onboarded','true')}", [token, username, role])


def create_course(db, course_id: str, teacher_id: str, stamp: str) -> None:
    db.execute("insert into courses(id,version,title,subject,description,content_origin,license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (course_id, "1.0", "AI 可信训练", "人工智能", "上游第一版描述", "https://example.invalid/fork-course", "CC BY 4.0", "private", "published", teacher_id, "fc2-fork-v1", "{}"))
    db.execute("insert into course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) values(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
        (f"cm-{stamp}", course_id, teacher_id, "teacher", "active"))
    db.execute("insert into course_documents(id,course_id,chapter_order,filename,file_type,file_size,title,content,tags,chunk_count,content_hash,source_path,license_text,status,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        (f"doc-{stamp}", course_id, 1, "intro.md", "md", 12, "导论", "上游正文", "[]", 1, hashlib.sha256("上游正文".encode()).hexdigest(), "intro.md", "CC BY 4.0", "published"))


def publish(page, headers: dict[str, str], course_id: str, title: str) -> dict:
    row = page.request.post(U + "/api/v1/marketplace/listings", headers=headers, data={"course_id": course_id, "title": title, "summary": "验证正式分叉与三方差异的公开课程", "category": "人工智能", "tags": ["AI", "分叉"]}).json()
    for action in ("approve", "publish"):
        row = page.request.post(U + f"/api/v1/marketplace/listings/{row['id']}/decisions", headers=headers,
            data={"action": action, "reason": "冻结课程来源许可证与版本后批准发布", "expected_version": row["lock_version"]}).json()
    return row


def main() -> int:
    O.mkdir(parents=True, exist_ok=True)
    for path in O.iterdir():
        if path.is_file(): path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(D) + suffix)
        if path.exists(): path.unlink()
    env = os.environ.copy(); env.update({"EDUMATRIX_DB_PATH": str(D), "EDUMATRIX_AUTH_SECRET_KEY": "fc2-fork",
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
                teacher = f"fc2_fork_teacher_{stamp}"; learner = f"fc2_fork_learner_{stamp}"; outsider = f"fc2_fork_outsider_{stamp}"
                teacher_token, teacher_id = auth(page, teacher, "admin")
                learner_token, _ = auth(page, learner, "student")
                outsider_token, _ = auth(page, outsider, "student")
                teacher_headers = {"Authorization": "Bearer " + teacher_token}; learner_headers = {"Authorization": "Bearer " + learner_token}
                course_id = f"fc2-fork-course-{stamp}"
                with sqlite3.connect(D) as db: create_course(db, course_id, teacher_id, stamp); db.commit()
                first = publish(page, teacher_headers, course_id, "AI 可信训练 v1")
                acquisition = page.request.post(U + f"/api/v1/marketplace/listings/{first['id']}/acquisitions", headers=learner_headers).json()

                browser_state(page, learner_token, learner, "student"); page.goto(U + "/marketplace/forks")
                page.get_by_test_id("marketplace-fork-workspace").wait_for(timeout=30000)
                page.get_by_text("可建立分叉的市场副本", exact=True).wait_for()
                page.get_by_role("button", name="建立正式分叉").click()
                page.get_by_text("正式分叉已建立", exact=False).wait_for()
                page.get_by_text("当前没有待处理的上游版本", exact=True).wait_for()
                page.get_by_label("分叉修改摘要").fill("本地改写课程标题和说明")
                page.get_by_label("分叉课程标题").fill("AI 可信训练本地实践版")
                page.get_by_label("分叉课程说明").fill("本地分叉描述")
                page.get_by_role("button", name="冻结新版本").click()
                page.get_by_text("本地修改已冻结为新的不可变分叉版本", exact=True).wait_for()
                page.get_by_text("fork v2", exact=True).first.wait_for()

                with sqlite3.connect(D) as db:
                    db.execute("update courses set version='2.0', title='AI 可信训练上游新版', description='上游第二版描述', manifest_version='fc2-fork-v2' where id=?", (course_id,)); db.commit()
                second = publish(page, teacher_headers, course_id, "AI 可信训练 v2")
                page.reload(); diff = page.get_by_test_id("fork-three-way-diff"); diff.wait_for(timeout=30000)
                diff.get_by_text("冲突 2", exact=True).wait_for()
                diff.get_by_text("course.title", exact=True).first.wait_for()
                diff.get_by_text("course.description", exact=True).first.wait_for()
                page.screenshot(path=str(O / "01-desktop-three-way-diff.png"), full_page=True)
                report["screenshots"].append("01-desktop-three-way-diff.png")

                forks = page.request.get(U + "/api/v1/marketplace/forks", headers=learner_headers).json()["forks"]
                fork = forks[0]
                denied = page.request.post(U + f"/api/v1/marketplace/forks/{fork['id']}/versions",
                    headers={"Authorization": "Bearer " + outsider_token}, data={"expected_version": fork["lock_version"], "modification_summary": "越权修改", "patch": {"course": {"title": "越权"}}})
                assert denied.status == 403
                report["checks"]["outsider_status"] = denied.status
                page.get_by_role("button", name="合并无冲突项").click()
                page.get_by_text("无冲突上游修改已合并", exact=False).wait_for()
                page.get_by_text("当前没有待处理的上游版本", exact=True).wait_for()
                page.reload(); page.get_by_text("AI 可信训练本地实践版", exact=True).first.wait_for()
                page.get_by_text("当前没有待处理的上游版本", exact=True).wait_for()
                page.screenshot(path=str(O / "02-desktop-merged-history.png"), full_page=True)
                report["screenshots"].append("02-desktop-merged-history.png")
                page.set_viewport_size({"width": 390, "height": 844}); page.get_by_text("独立版本历史", exact=True).scroll_into_view_if_needed(); page.wait_for_timeout(400)
                width = page.evaluate("document.documentElement.scrollWidth"); assert width <= 390
                page.screenshot(path=str(O / "03-mobile-fork-history.png"))
                report["screenshots"].append("03-mobile-fork-history.png")
                final = page.request.get(U + "/api/v1/marketplace/forks", headers=learner_headers).json()["forks"][0]
                assert final["current_version"]["course"]["title"] == "AI 可信训练本地实践版"
                assert final["current_version"]["course"]["description"] == "本地分叉描述"
                assert final["baseline_hash"] == second["snapshot_hash"] and final["update_preview"] is None
                report["checks"].update({"fork_versions": len(final["versions"]), "decisions": len(final["decisions"]),
                    "conflicts_preserved": ["course.title", "course.description"], "baseline_updated": second["snapshot_hash"],
                    "derived_course_id": acquisition["derived_course_id"], "mobile_width": width})
                report["result"] = "passed"; context.close(); browser.close()
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True); process.wait(); wait_port(False)
        if D.exists():
            with sqlite3.connect(D) as source, sqlite3.connect(O / "marketplace_fork_evidence.db") as target:
                source.backup(target); report["checks"]["sqlite"] = target.execute("pragma integrity_check").fetchone()[0]
                report["checks"]["fork_rows"] = target.execute("select count(*) from marketplace_forks").fetchone()[0]
                report["checks"]["fork_version_rows"] = target.execute("select count(*) from marketplace_fork_versions").fetchone()[0]
                report["checks"]["fork_decision_rows"] = target.execute("select count(*) from marketplace_fork_decisions").fetchone()[0]
                report["checks"]["migration"] = target.execute("select count(*) from schema_migrations where version='20260804_045'").fetchone()[0]
        (O / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
            for path in sorted(O.iterdir()) if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))]
        (O / "manifest.json").write_text(json.dumps({"files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
