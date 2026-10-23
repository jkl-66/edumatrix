"""Verify weak video watch and strong post-video assessment evidence in Chrome."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC1-006" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_fc1_video_practice_e2e.db"
VIDEO_ROOT = ROOT / "outputs" / "_fc1_video_practice_outputs"
PORT = 8816
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC1-video-practice-2026!"


def wait_port(open_: bool, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError("port state timeout")


def authenticate(page, token: str, username: str) -> None:
    page.goto(BASE_URL + "/login")
    page.evaluate(
        """([token, username]) => {
          localStorage.setItem('edumatrix_token', token);
          localStorage.setItem('edumatrix_role', 'student');
          localStorage.setItem('edumatrix_username', username);
          localStorage.setItem('edumatrix_student_id', username);
          localStorage.setItem('edumatrix_onboarded', 'true');
        }""",
        [token, username],
    )


def seed(env: dict[str, str], username: str) -> dict[str, str]:
    code = r'''
import hashlib, json
from app.database import (DBAssessmentQuestion,DBAssessmentQuestionVersion,DBChapter,DBChapterKnowledgePoint,DBCourse,DBKnowledgePoint,DBSourceDocument,DBSourceRef,DBUser,SessionLocal,init_db)
def sha(x): return hashlib.sha256(x.encode()).hexdigest()
init_db()
with SessionLocal() as db:
    user=db.query(DBUser).filter_by(username=USERNAME).one()
    course=DBCourse(id='fc1-browser-practice-course',version='1.0.0',title='边缘人工智能技能实训',subject='人工智能',description='FC1 冻结合成视频练习演示课程',domain_pack='edge-ai',language='zh-CN',content_origin='frozen_synthetic_demo',license_text='冻结合成演示材料',visibility='public',status='published',manifest_version='fc1-practice-v1',manifest_data={'chapters':[{'stable_key':'quantization','learning_objectives':['解释模型量化对部署资源的影响','依据课程来源判断量化收益与精度风险']}]})
    db.add(course);db.flush()
    doc=DBSourceDocument(id='fc1-browser-practice-source',course_id=course.id,title='边缘模型部署讲义',filename='edge-deployment.md',file_format='md',content_hash=sha('practice-doc'),source_sha256=sha('practice-source'),processed_sha256=sha('practice-processed'),file_size=512,source_url='https://example.invalid/frozen-demo',source_path='fixtures/edge-deployment.md',license_text='冻结合成演示材料',uploader_public_id=user.public_id,parser_version='fc1-browser-parser-v1',processing_status='ready')
    db.add(doc);db.flush()
    chapter=DBChapter(id='fc1-browser-practice-chapter',course_id=course.id,source_document_id=doc.id,stable_key='quantization',title='模型量化与部署',position=1,heading_level=1,char_start=0,char_end=180)
    db.add(chapter);db.flush()
    kp=DBKnowledgePoint(id='fc1-browser-practice-kp',domain_pack='edge-ai',code='edge-quantization-practice',version='1.0.0',title='模型量化',level='core',status='active')
    db.add(kp);db.flush()
    db.add(DBChapterKnowledgePoint(id='fc1-browser-practice-ckp',chapter_id=chapter.id,knowledge_point_id=kp.id,relation_type='teaches'))
    ref=DBSourceRef(id='fc1-browser-practice-ref',source_document_id=doc.id,chapter_id=chapter.id,parser_version='fc1-browser-parser-v1',char_start=0,char_end=118,location_kind='section',location_index=1,location_label='第 1 章 模型量化与部署',location_metadata={'demo':True},content_hash=sha('practice-quote'),quote='模型量化通过降低权重与激活值的数值精度，减少模型体积和推理资源开销；部署前必须验证精度损失。')
    db.add(ref);db.flush()
    question=DBAssessmentQuestion(id='fc1-browser-practice-question',course_id=course.id,owner_public_id=user.public_id,question_type='single_choice',origin='manual',status='approved')
    db.add(question);db.flush()
    version=DBAssessmentQuestionVersion(id='fc1-browser-practice-question-v1',question_id=question.id,version_number=1,prompt='关于模型量化，哪一项符合课程来源？',options=['A. 增加模型体积','B. 降低数值精度并验证精度损失'],answer_key={'choice':'B'},scoring_rule={'version':'objective-fc1-browser-v1','type':'exact'},explanation='依据冻结课程摘录判断。',misconception_tags=['concept_confusion'],primary_knowledge_point_id=kp.id,secondary_knowledge_point_ids=[],bloom_level='apply',expert_difficulty=0.45,irt_parameters={'alpha':1.0,'beta':0.0,'gamma':0.25},sample_size=0,source_ref_ids=[ref.id],content_hash=sha('practice-question-v1'),created_by_public_id=user.public_id)
    db.add(version);db.flush();question.current_version_id=version.id
    result={'course_id':course.id,'chapter_id':chapter.id,'question_version_id':version.id}
    db.commit()
print(json.dumps(result))
'''.replace("USERNAME", repr(username))
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    if VIDEO_ROOT.exists():
        shutil.rmtree(VIDEO_ROOT)
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH), "EDUMATRIX_VIDEO_OUTPUT_DIR": str(VIDEO_ROOT),
        "EDUMATRIX_AUTH_SECRET_KEY": "fc1-video-practice-e2e", "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic", "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "", "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash", "EDUMATRIX_RELOAD": "0", "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_PORT": str(PORT), "PYTHONUNBUFFERED": "1", "PYTHON_DOTENV_DISABLED": "1",
    })
    report = {"schema_version": "fc1-006.video-practice-browser-e2e.v1", "checks": {}, "screenshots": []}
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                stamp = str(int(time.time()))
                users = {}
                for role in ("owner", "outsider"):
                    username = f"fc1_practice_{role}_{stamp}"
                    response = page.request.post(BASE_URL + "/api/auth/register", data={"username": username, "password": PASSWORD, "display_name": role})
                    assert response.ok
                    users[role] = {"name": username, "token": response.json()["access_token"]}
                    users[role]["headers"] = {"Authorization": "Bearer " + users[role]["token"]}
                fixture = seed(env, users["owner"]["name"])
                authenticate(page, users["owner"]["token"], users["owner"]["name"])
                page.goto(BASE_URL + "/chapter-videos", wait_until="networkidle")
                root = page.get_by_test_id("chapter-video-workspace")
                root.get_by_label("选择课程").select_option(fixture["course_id"])
                root.get_by_label("选择章节").select_option(fixture["chapter_id"])
                root.get_by_role("button", name="生成章节脚本").click()
                root.get_by_text("已创建来源绑定的五段章节视频脚本。", exact=True).wait_for()
                root.get_by_role("button", name="生成 MP4 与字幕").click()
                video = root.get_by_test_id("chapter-rendered-video")
                video.wait_for(timeout=180_000)
                page.wait_for_function("el => el.readyState >= 1 && el.duration > 0", arg=video.element_handle(), timeout=60_000)
                support = page.evaluate("() => document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E\"')")
                duration = video.evaluate("el => el.duration")
                video.evaluate("el => el.play()")
                page.wait_for_timeout(1200)
                assert video.evaluate("el => el.currentTime") > 0
                practice = root.get_by_test_id("video-practice-workspace")
                expect(practice.get_by_text("关于模型量化，哪一项符合课程来源？")).to_be_visible()
                practice.locator("input[type=checkbox]").first.check()
                practice.get_by_test_id("save-video-practice-bindings").click()
                practice.get_by_text("练习 v1", exact=True).wait_for()

                links = page.request.get(BASE_URL + "/api/v1/chapter-videos", headers=users["owner"]["headers"]).json()["items"]
                link = links[0]
                before = page.request.get(BASE_URL + f"/api/v1/video-practices/{link['id']}", headers=users["owner"]["headers"]).json()["ability"]["response_count"]
                root.get_by_test_id("mark-watch-complete").click()
                root.get_by_text("观看完成已记录为弱证据，能力值未改变。", exact=True).wait_for()
                weak = page.request.get(BASE_URL + f"/api/v1/video-practices/{link['id']}", headers=users["owner"]["headers"]).json()
                assert weak["watch"]["completed"] is True and weak["watch"]["evidence_strength"] == "weak"
                assert weak["ability"]["response_count"] == before == 0
                report["checks"]["weak_watch"] = {"completed": True, "mastery_updated": False, "response_count": 0}

                practice.locator("input[type=radio][value=B]").check()
                practice.get_by_test_id("submit-video-practice").click()
                root.get_by_text("服务端评分 100%，已形成强证据；下一步：继续学习。", exact=True).wait_for()
                expect(practice.get_by_text("不可变强证据", exact=True)).to_be_visible()
                expect(practice.get_by_text("测评 100%", exact=True)).to_be_visible()
                strong = page.request.get(BASE_URL + f"/api/v1/video-practices/{link['id']}", headers=users["owner"]["headers"]).json()
                assert strong["ability"]["response_count"] == 1
                assert strong["attempt_links"][0]["evidence"]["evidence_strength"] == "strong"
                assert strong["attempt_links"][0]["next_action"] == "proceed"
                report["checks"]["strong_assessment"] = {"score": 1.0, "response_count": 1, "next_action": "proceed"}
                denied = page.request.get(BASE_URL + f"/api/v1/video-practices/{link['id']}", headers=users["outsider"]["headers"])
                assert denied.status == 403
                report["checks"]["owner_boundary"] = 403
                report["checks"]["chrome_media_support"] = support
                report["checks"]["playable_duration"] = duration
                page.screenshot(path=str(OUTPUT / "01-desktop-video-practice.png"), full_page=True)
                report["screenshots"].append("01-desktop-video-practice.png")

                page.reload(wait_until="networkidle")
                root = page.get_by_test_id("chapter-video-workspace")
                root.get_by_test_id("video-practice-workspace").get_by_text("测评 100%", exact=True).wait_for()
                expect(root.get_by_test_id("video-watch-proof").get_by_text("已完成 · 弱证据", exact=True)).to_be_visible()
                report["checks"]["refresh_recovery"] = True
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(400)
                width = page.evaluate("document.documentElement.scrollWidth")
                assert width <= 390
                report["checks"]["mobile_scroll_width"] = width
                page.screenshot(path=str(OUTPUT / "02-mobile-video-practice.png"), full_page=True)
                report["screenshots"].append("02-mobile-video-practice.png")
                mobile_practice = root.get_by_test_id("video-practice-workspace")
                mobile_practice.scroll_into_view_if_needed()
                page.wait_for_timeout(250)
                mobile_practice.screenshot(path=str(OUTPUT / "03-mobile-practice-detail.png"))
                report["screenshots"].append("03-mobile-practice-detail.png")
                context.close(); browser.close()
        report["result"] = "passed"
    finally:
        if backend and backend.poll() is None:
            subprocess.run(["taskkill", "/PID", str(backend.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
            backend.wait(timeout=10); wait_port(False, 20)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(OUTPUT / "video_practice_evidence.db") as evidence:
                source.backup(evidence)
                report["checks"]["sqlite"] = evidence.execute("PRAGMA integrity_check").fetchone()[0]
                report["checks"]["evidence_rows"] = {
                    "practice_versions": evidence.execute("SELECT COUNT(*) FROM video_practice_versions").fetchone()[0],
                    "attempt_links": evidence.execute("SELECT COUNT(*) FROM video_practice_attempt_links").fetchone()[0],
                    "watch_events": evidence.execute("SELECT COUNT(*) FROM learning_events WHERE event_type LIKE 'video.watch.%'").fetchone()[0],
                }
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{"file": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(OUTPUT.iterdir()) if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))]
        (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version": "fc1-006.video-practice-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
