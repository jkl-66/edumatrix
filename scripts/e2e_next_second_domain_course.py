from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR", ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-ECO-06" / "browser-e2e"))
DB_PATH = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_next_second_domain_e2e.db"))
PORT = 8804
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Edge-course-2026!"
COURSE_ID = "course-embedded-edge-intelligence-v1"
REVISION = "a3d5f9df06d0b6750d5227eb3e0359e9ffbbe1e6"


def wait_port(open_: bool, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError("backend_port_timeout")


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.glob("*"):
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(DB_PATH) + suffix)
        if path.exists():
            path.unlink()
    env = os.environ.copy()
    env.update(
        {
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "nc-eco-06-isolated",
            "EDUMATRIX_LLM_PROVIDER": "deterministic",
            "EDUMATRIX_LLM_MODEL": "deterministic",
            "EDUMATRIX_LLM_API_KEY": "",
            "EDUMATRIX_LLM_ENDPOINT": "",
            "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
            "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
            "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
            "EDUMATRIX_RELOAD": "0",
            "EDUMATRIX_HOST": "127.0.0.1",
            "EDUMATRIX_PORT": str(PORT),
            "PYTHONUNBUFFERED": "1",
            "PYTHON_DOTENV_DISABLED": "1",
        }
    )
    report = {
        "schema_version": "next.nc-eco-06-browser-e2e.v1",
        "checks": {},
        "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                username = f"eco06_student_{int(time.time())}"
                registration = page.request.post(
                    BASE_URL + "/api/auth/register",
                    data={"username": username, "password": PASSWORD, "display_name": "第二领域验收学生"},
                )
                assert registration.ok, registration.text()
                token = registration.json()["access_token"]
                headers = {"Authorization": "Bearer " + token}
                rows = page.request.get(
                    BASE_URL + f"/api/knowledge/list?student_id={username}", headers=headers
                )
                assert rows.ok, rows.text()
                edge_rows = [item for item in rows.json() if item.get("course_id") == COURSE_ID]
                assert len(edge_rows) == 8
                assert all(item["source_git_revision"] == REVISION for item in edge_rows)
                assert all(item["source_license_spdx"] == "CC-BY-NC-SA-4.0" for item in edge_rows)
                report["checks"]["api_chapters"] = len(edge_rows)
                report["checks"]["license_spdx"] = edge_rows[0]["source_license_spdx"]

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
                page.goto(BASE_URL + "/knowledge", wait_until="networkidle")
                group = page.locator("section.knowledge-group").filter(has_text="嵌入式边缘智能技能实践")
                group.get_by_role("heading", name="嵌入式边缘智能技能实践").wait_for(timeout=20_000)
                assert group.locator(".knowledge-card").count() == 8
                group.get_by_text("CC BY-NC-SA 4.0", exact=False).wait_for()
                heading = group.get_by_role("heading", name="嵌入式边缘智能技能实践")
                page.evaluate(
                    """el => {
                      let parent = el.parentElement;
                      while (parent && parent.scrollHeight <= parent.clientHeight) parent = parent.parentElement;
                      if (!parent) throw new Error('scroll_container_missing');
                      parent.scrollTop += el.getBoundingClientRect().top - 130;
                    }""",
                    heading.element_handle(),
                )
                page.wait_for_timeout(300)
                page.screenshot(path=str(OUTPUT / "01-desktop-second-domain-course.png"), full_page=False)
                report["screenshots"].append("01-desktop-second-domain-course.png")

                group.locator(".knowledge-card").first.click()
                page.get_by_text("预置课程文档", exact=True).wait_for()
                page.get_by_text(REVISION, exact=True).wait_for()
                page.get_by_text("CC BY-NC-SA 4.0", exact=False).last.wait_for()
                page.screenshot(path=str(OUTPUT / "02-desktop-provenance-detail.png"), full_page=False)
                report["screenshots"].append("02-desktop-provenance-detail.png")
                page.get_by_title("关闭 (Esc)").click()

                page.reload(wait_until="networkidle")
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(700)
                mobile_width = page.evaluate("document.documentElement.scrollWidth")
                assert mobile_width <= 390
                mobile_group = page.locator("section.knowledge-group").filter(has_text="嵌入式边缘智能技能实践")
                assert mobile_group.locator(".knowledge-card").count() == 8
                mobile_heading = mobile_group.get_by_role("heading", name="嵌入式边缘智能技能实践")
                page.evaluate(
                    """el => {
                      let parent = el.parentElement;
                      while (parent && parent.scrollHeight <= parent.clientHeight) parent = parent.parentElement;
                      if (!parent) throw new Error('scroll_container_missing');
                      parent.scrollTop += el.getBoundingClientRect().top - 90;
                    }""",
                    mobile_heading.element_handle(),
                )
                page.wait_for_timeout(300)
                page.screenshot(path=str(OUTPUT / "03-mobile-second-domain-course.png"), full_page=False)
                report["screenshots"].append("03-mobile-second-domain-course.png")
                report["checks"]["mobile_scroll_width"] = mobile_width
                context.close()
                browser.close()
                report["result"] = "passed"
    finally:
        if backend is not None and backend.poll() is None:
            subprocess.run(["taskkill", "/PID", str(backend.pid), "/T", "/F"], capture_output=True)
            backend.wait(timeout=10)
            wait_port(False, timeout=20)
        if DB_PATH.exists():
            evidence_db = OUTPUT / "second_domain_evidence.db"
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(evidence_db) as target:
                source.backup(target)
                report["checks"]["sqlite"] = target.execute("pragma integrity_check").fetchone()[0]
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        files = []
        for path in sorted(OUTPUT.glob("*")):
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm")):
                files.append(
                    {"file": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                )
        (OUTPUT / "manifest.json").write_text(
            json.dumps({"schema_version": "next.nc-eco-06-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
