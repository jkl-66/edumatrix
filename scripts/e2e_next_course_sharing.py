"""Verify immutable course sharing and explicit upstream updates in Chromium."""

from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR", ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-ECO-01" / "browser-e2e"))
DB_PATH = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_next_course_sharing_e2e.db"))
EVIDENCE_DB = OUTPUT / "course_sharing_evidence.db"
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-course-sharing-2026!"


def wait_port(open_: bool, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock: available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_: return
        time.sleep(.2)
    raise RuntimeError("course sharing E2E port timeout")


def stop(process) -> None:
    if process is None or process.poll() is not None: return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15)
    process.wait(timeout=10); wait_port(False, 15)


def login_state(page, token: str, username: str, role: str) -> None:
    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.evaluate("""([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_student_id',n);localStorage.setItem('edumatrix_display_name',n);localStorage.setItem('edumatrix_onboarded','true')}""", [token, username, role])


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file(): path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(DB_PATH) + suffix)
        if path.exists(): path.unlink()
    env = os.environ.copy(); env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH), "EDUMATRIX_AUTH_SECRET_KEY": "next-course-sharing-e2e",
        "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0", "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT), "PYTHONUNBUFFERED": "1",
        "PYTHON_DOTENV_DISABLED": "1",
    })
    report = {"schema_version": "next.nc-eco-01-browser-e2e.v1", "checks": {}, "screenshots": []}
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page(); stamp = str(int(time.time()))
                names = {key: f"eco01_{key}_{stamp}" for key in ("teacher", "learner", "outsider")}; tokens = {}; ids = {}
                for key, name in names.items():
                    response = page.request.post(BASE + "/api/auth/register", data={"username": name, "password": PASSWORD, "display_name": key})
                    assert response.ok; ids[key] = response.json()["user_id"]
                course_id, class_id = f"eco-course-{stamp}", f"eco-class-{stamp}"
                with sqlite3.connect(DB_PATH) as db:
                    db.execute("update users set role='teacher' where public_id=?", (ids["teacher"],))
                    db.execute("insert into courses(id,version,title,subject,description,content_origin,license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                        (course_id, "1.0", "可信机器学习", "人工智能", "上游初始说明", "https://example.invalid/ml", "CC BY 4.0", "private", "published", ids["teacher"], "manifest-v1", '{"commit":"abc"}'))
                    db.execute("insert into course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) values(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)", (f"cm-{stamp}", course_id, ids["teacher"], "teacher", "active"))
                    db.execute("insert into teaching_classes(id,course_id,title,term,owner_public_id,status,lock_version,created_at,updated_at) values(?,?,?,?,?,'active',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)", (class_id, course_id, "2026 AI 实训班", "2026", ids["teacher"]))
                    db.execute("insert into teaching_class_members(id,class_id,user_public_id,role,status,lock_version,joined_at,updated_at) values(?,?,?,'student','active',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)", (f"tcm-{stamp}", class_id, ids["learner"]))
                    db.execute("insert into course_documents(id,course_id,chapter_order,filename,file_type,file_size,title,content,tags,chunk_count,content_hash,source_path,license_text,status,created_at,updated_at) values(?,?,1,'chapter.md','md',10,'第一章','版本一正文','[]',1,'hash-v1','repo/chapter.md','CC BY 4.0','published',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)", (f"doc-{stamp}", course_id))
                    db.execute("insert into source_documents(id,course_id,title,filename,file_format,content_hash,source_sha256,processed_sha256,file_size,source_url,source_path,license_text,uploader_public_id,parser_version,parser_metadata,parse_warnings,processing_error_code,processing_status,created_at,updated_at) values(?,?,'第一章','chapter.md','md','hash-v1','source-v1','processed-v1',10,'https://example.invalid/chapter','repo/chapter.md','CC BY 4.0',?,'e2e-v1','{}','[]','','ready',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)", (f"src-{stamp}", course_id, ids["teacher"]))
                    db.commit()
                for key, name in names.items():
                    response = page.request.post(BASE + "/api/auth/login", form={"username": name, "password": PASSWORD}); assert response.ok
                    tokens[key] = response.json()["access_token"]
                headers = {key: {"Authorization": "Bearer " + value} for key, value in tokens.items()}

                login_state(page, tokens["teacher"], names["teacher"], "teacher")
                page.goto(BASE + "/course-sharing", wait_until="domcontentloaded"); page.locator(".sharing-page h2", has_text="课程分享与上游更新").wait_for(timeout=30000)
                page.get_by_label("待分享课程").select_option(course_id); page.get_by_label("分享目标").select_option(class_id)
                page.get_by_label("发布标题").fill("可信机器学习共享版")
                page.get_by_role("button", name="发布不可变快照").click(); page.get_by_text("可信机器学习共享版", exact=True).wait_for(timeout=30000)
                release = page.request.get(BASE + "/api/v1/course-sharing/workspace", headers=headers["teacher"]).json()["releases"][0]

                login_state(page, tokens["learner"], names["learner"], "student")
                page.goto(BASE + "/course-sharing", wait_until="domcontentloaded"); page.locator(".sharing-page h2", has_text="课程分享与上游更新").wait_for(timeout=30000)
                page.get_by_title("创建派生副本").click(); page.get_by_text("可信机器学习（派生副本）", exact=True).first.wait_for(timeout=30000)
                assert "CC BY 4.0" in page.locator(".license").inner_text()
                copy = page.request.get(BASE + "/api/v1/course-sharing/workspace", headers=headers["learner"]).json()["copies"][0]
                denied = page.request.post(BASE + f"/api/v1/course-sharing/releases/{release['id']}/copies", headers=headers["outsider"])
                assert denied.status == 403; report["checks"]["outsider_copy_forbidden"] = 403

                with sqlite3.connect(DB_PATH) as db:
                    db.execute("update courses set version='2.0',description='上游新版说明',manifest_version='manifest-v2' where id=?", (course_id,))
                    db.execute("update courses set description='接收方本地说明' where id=?", (copy["derived_course"]["id"],))
                    db.execute("update course_documents set content='版本二正文',content_hash='hash-v2' where course_id=?", (course_id,)); db.commit()
                new_release = page.request.post(BASE + "/api/v1/course-sharing/releases", headers=headers["teacher"], data={"course_id": course_id, "target_type": "class", "target_id": class_id, "title": "可信机器学习 2.0"})
                assert new_release.ok
                page.reload(wait_until="domcontentloaded"); page.get_by_text("发现上游 2.0", exact=True).wait_for(timeout=30000)
                page.get_by_text("course.description", exact=True).wait_for(); page.screenshot(path=str(OUTPUT / "01-three-way-conflict.png"), full_page=True); report["screenshots"].append("01-three-way-conflict.png")
                page.get_by_role("button", name="接受并保留审计").click(); page.get_by_text("当前版本").wait_for(timeout=30000)
                page.reload(wait_until="domcontentloaded"); page.get_by_text("2.0", exact=True).first.wait_for(timeout=30000)
                page.wait_for_timeout(900)
                page.screenshot(path=str(OUTPUT / "02-accepted-derived-copy.png"), full_page=True); report["screenshots"].append("02-accepted-derived-copy.png")

                withdrawal = page.request.post(BASE + f"/api/v1/course-governance/courses/{course_id}/withdraw", headers=headers["teacher"], data={"reason": "上游来源撤回但保留接收方历史", "expected_status": "published"})
                assert withdrawal.ok
                propagated = page.request.post(BASE + "/api/v1/course-sharing/withdrawals/propagate", headers=headers["teacher"]); assert propagated.ok
                assert propagated.json()["historical_copies_deleted"] == 0
                page.reload(wait_until="domcontentloaded"); page.get_by_text("withdrawn", exact=True).first.wait_for(timeout=30000)
                page.wait_for_timeout(900)
                page.set_viewport_size({"width": 390, "height": 844}); page.wait_for_timeout(500)
                width = page.evaluate("document.documentElement.scrollWidth"); assert width <= 390
                page.screenshot(path=str(OUTPUT / "03-mobile-withdrawn-history.png"), full_page=True); report["screenshots"].append("03-mobile-withdrawn-history.png")
                with sqlite3.connect(DB_PATH) as db:
                    derived = db.execute("select status from courses where id=?", (copy["derived_course"]["id"],)).fetchone()[0]
                    decisions = db.execute("select count(*) from course_share_decisions where derived_copy_id=?", (copy["id"],)).fetchone()[0]
                    docs = db.execute("select count(*) from course_documents where course_id=?", (copy["derived_course"]["id"],)).fetchone()[0]
                assert (derived, decisions, docs) == ("published", 1, 1)
                report["checks"].update({"conflict_count": 1, "accepted_version": "2.0", "decision_count": decisions,
                    "withdrawal_history": {"derived_status": derived, "document_count": docs, **propagated.json()}, "mobile_scroll_width": width})
                context.close(); browser.close(); report["result"] = "passed"
    finally:
        stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target); report["checks"]["sqlite"] = target.execute("pragma integrity_check").fetchone()[0]
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        files = []
        for path in sorted(OUTPUT.iterdir()):
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm")):
                files.append({"file": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version": "next.nc-eco-01-manifest.v1", "files": files}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False)); return 0


if __name__ == "__main__": raise SystemExit(main())
