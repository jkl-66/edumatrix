"""Verify wrong-question evidence to a playable local explanation video in Chrome."""

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
OUTPUT = ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC1-004" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_fc1_wrong_video_e2e.db"
VIDEO_ROOT = ROOT / "outputs" / "_fc1_wrong_video_outputs"
PORT = 8814
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC1-wrong-video-2026!"


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


def seed(env: dict[str, str], username: str) -> None:
    code = """
from app.database import DBQuizRecord, DBReviewPlan, DBWrongQuestion, SessionLocal, init_db
init_db()
with SessionLocal() as db:
    quiz=DBQuizRecord(id='fc1-browser-wrong',student_id=USERNAME,question='边缘设备部署前为什么需要模型量化？',student_answer='量化会让模型更准确',correct_answer='量化主要降低模型体积与推理资源开销，并需验证精度损失。',accuracy_score=0.2,target_concept='边缘模型量化',feedback='混淆了部署效率与预测精度。',next_action='review',attempt_number=1)
    db.add(quiz);db.flush()
    db.add(DBWrongQuestion(student_id=USERNAME,quiz_record_id=quiz.id,concept_name='边缘模型量化',wrong_reason_category='concept_confusion',pinned=True))
    db.add(DBReviewPlan(student_id=USERNAME,concept='边缘模型量化',interval_days=2,mastery=0.25,review_count=1))
    db.commit()
""".replace("USERNAME", repr(username))
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)


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
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_VIDEO_OUTPUT_DIR": str(VIDEO_ROOT),
        "EDUMATRIX_AUTH_SECRET_KEY": "fc1-wrong-video-e2e",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
        "PYTHON_DOTENV_DISABLED": "1",
    })
    report = {"schema_version": "fc1-004.wrong-question-video-browser-e2e.v1", "checks": {}, "screenshots": []}
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN", accept_downloads=True)
                page = context.new_page()
                stamp = str(int(time.time()))
                users = {}
                for role in ("owner", "outsider"):
                    username = f"fc1_wrong_{role}_{stamp}"
                    result = page.request.post(BASE_URL + "/api/auth/register", data={"username": username, "password": PASSWORD, "display_name": role})
                    assert result.ok
                    users[role] = {"name": username, "token": result.json()["access_token"]}
                    users[role]["headers"] = {"Authorization": "Bearer " + users[role]["token"]}
                seed(env, users["owner"]["name"])
                authenticate(page, users["owner"]["token"], users["owner"]["name"])
                page.goto(BASE_URL + "/wrong-questions", wait_until="networkidle")
                page.get_by_role("heading", name="错题本", level=2).wait_for()
                wrong_card = page.locator(".card").filter(has=page.get_by_title("删除错题")).filter(has_text="边缘模型量化")
                expect(wrong_card).to_have_count(1)
                wrong_card.get_by_text("边缘模型量化", exact=True).click()
                panel = page.get_by_test_id("wrong-question-video-panel")
                panel.get_by_text("错题讲解视频", exact=True).wait_for()
                panel.get_by_role("button", name="生成边缘模型量化错题讲解视频").click()
                preview = panel.get_by_test_id("wrong-question-video-preview")
                preview.wait_for(timeout=180_000)
                page.wait_for_function("el => el.readyState >= 1 && el.duration > 0", arg=preview.element_handle(), timeout=60_000)
                preview.evaluate("el => { el.currentTime = Math.min(1, el.duration / 2) }")
                page.wait_for_function("el => el.readyState >= 2", arg=preview.element_handle(), timeout=30_000)
                report["checks"]["chrome_media_support"] = page.evaluate(
                    "() => document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E\"')"
                )
                expect(panel.get_by_text("旧题记录追溯；未宣称为可定位课程原文引用", exact=True)).to_be_visible()
                expect(panel.get_by_text("script v1", exact=True)).to_be_visible()
                report["checks"]["playable_duration"] = preview.evaluate("el => el.duration")
                page.screenshot(path=str(OUTPUT / "01-desktop-wrong-video.png"), full_page=True)
                report["screenshots"].append("01-desktop-wrong-video.png")
                panel.screenshot(path=str(OUTPUT / "02-desktop-video-panel.png"))
                report["screenshots"].append("02-desktop-video-panel.png")

                links = page.request.get(BASE_URL + "/api/v1/wrong-question-videos", params={"student_id": users["owner"]["name"]}, headers=users["owner"]["headers"]).json()["items"]
                assert len(links) == 1
                link = links[0]
                assert len(link["project"]["script"]["scenes"]) == 5
                denied = page.request.get(BASE_URL + f"/api/v1/wrong-question-videos/{link['id']}", headers=users["outsider"]["headers"])
                assert denied.status == 403
                report["checks"]["backlink_and_owner"] = {"link_id": link["id"], "scenes": 5, "outsider": 403}

                with page.expect_download() as download_info:
                    panel.get_by_role("button", name="SRT", exact=True).click()
                subtitle = OUTPUT / "wrong-video.srt"
                download_info.value.save_as(subtitle)
                assert "量化主要降低模型体积" in subtitle.read_text(encoding="utf-8")
                report["checks"]["subtitle_sha256"] = hashlib.sha256(subtitle.read_bytes()).hexdigest()

                page.reload(wait_until="networkidle")
                wrong_card = page.locator(".card").filter(has=page.get_by_title("删除错题")).filter(has_text="边缘模型量化")
                wrong_card.get_by_text("边缘模型量化", exact=True).click()
                panel = page.get_by_test_id("wrong-question-video-panel")
                panel.get_by_role("button", name="打开已生成边缘模型量化错题讲解视频").wait_for()
                panel.get_by_role("button", name="加载视频预览").click()
                preview = panel.get_by_test_id("wrong-question-video-preview")
                preview.wait_for(timeout=30_000)
                page.wait_for_function("el => el.readyState >= 1 && el.duration > 0", arg=preview.element_handle(), timeout=30_000)
                preview.evaluate("el => { el.currentTime = Math.min(1, el.duration / 2) }")
                page.wait_for_function("el => el.readyState >= 2", arg=preview.element_handle(), timeout=30_000)
                report["checks"]["refresh_recovery"] = True
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(400)
                width = page.evaluate("document.documentElement.scrollWidth")
                assert width <= 390
                report["checks"]["mobile_scroll_width"] = width
                page.screenshot(path=str(OUTPUT / "03-mobile-wrong-video.png"), full_page=True)
                report["screenshots"].append("03-mobile-wrong-video.png")
                panel.screenshot(path=str(OUTPUT / "04-mobile-video-panel.png"))
                report["screenshots"].append("04-mobile-video-panel.png")
                context.close(); browser.close()
        report["result"] = "passed"
    finally:
        if backend and backend.poll() is None:
            subprocess.run(["taskkill", "/PID", str(backend.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
            backend.wait(timeout=10); wait_port(False, 20)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(OUTPUT / "wrong_video_evidence.db") as evidence:
                source.backup(evidence)
                report["checks"]["sqlite"] = evidence.execute("PRAGMA integrity_check").fetchone()[0]
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        files = [{"file": p.name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name != "manifest.json" and not p.name.endswith(("-wal", "-shm"))]
        (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version": "fc1-004.wrong-question-video-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
