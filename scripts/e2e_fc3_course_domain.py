"""Verify FC3-01A course, retrieval, citation, graph and second-domain UI."""

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
OUTPUT = ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC3-01A" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_fc3_course_domain_e2e.db"
EVIDENCE_DB = OUTPUT / "fc3_course_domain_evidence.db"
PORT = 8827
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC3-course-domain-2026!"
ML_COURSE = "course-machine-learning-foundations-v1"
EDGE_COURSE = "course-embedded-edge-intelligence-v1"
QUERY = "训练前为什么要处理缺失值、类别变量和数值尺度"


def wait_port(expected_open: bool, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            opened = probe.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected_open:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not become {'open' if expected_open else 'closed'}")


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    process.wait(timeout=10)
    wait_port(False, 20)


def unlink_runtime_database() -> None:
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        for attempt in range(20):
            if not path.exists():
                break
            try:
                path.unlink()
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.25)


def write_manifest() -> None:
    files = []
    for path in sorted(OUTPUT.iterdir()):
        if not path.is_file() or path.name == "manifest.json" or path.name.endswith(("-wal", "-shm")):
            continue
        files.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (OUTPUT / "manifest.json").write_text(
        json.dumps({"schema_version": "edumatrix.fc3-course-domain-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    unlink_runtime_database()

    env = os.environ.copy()
    env.update(
        {
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "fc3-course-domain-e2e-secret",
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
        "schema_version": "edumatrix.fc3-course-domain-e2e.v1",
        "work_package": "FC3-01A",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {},
        "screenshots": [],
    }
    backend = None
    page_errors: list[str] = []
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
                page.on("pageerror", lambda error: page_errors.append(f"pageerror:{error}"))
                page.on(
                    "response",
                    lambda response: page_errors.append(f"http_{response.status}:{response.url}")
                    if response.status >= 500
                    else None,
                )

                username = f"fc3_course_{int(time.time())}"
                registration = page.request.post(
                    f"{BASE_URL}/api/auth/register",
                    data={"username": username, "password": PASSWORD, "display_name": "FC3 课程域验收学生"},
                )
                assert registration.ok, registration.text()
                token = registration.json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}
                listing = page.request.get(
                    f"{BASE_URL}/api/knowledge/list?student_id={username}", headers=headers
                )
                assert listing.ok, listing.text()
                rows = listing.json()
                courses = {row.get("course_id") for row in rows if row.get("course_id")}
                assert {ML_COURSE, EDGE_COURSE}.issubset(courses)
                edge_rows = [row for row in rows if row.get("course_id") == EDGE_COURSE]
                assert len(edge_rows) == 8
                assert all(row.get("source_license_spdx") == "CC-BY-NC-SA-4.0" for row in edge_rows)

                graph = page.request.get(f"{BASE_URL}/api/knowledge/graph/stats", headers=headers)
                assert graph.ok, graph.text()
                graph_payload = graph.json()
                assert graph_payload["governance"]["verified_facts"] > 0

                page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                page.evaluate(
                    """([token, username]) => {
                      localStorage.setItem('edumatrix_token', token)
                      localStorage.setItem('edumatrix_role', 'student')
                      localStorage.setItem('edumatrix_username', username)
                      localStorage.setItem('edumatrix_student_id', username)
                      localStorage.setItem('edumatrix_onboarded', 'true')
                      localStorage.setItem('edumatrix_course_id', 'course-machine-learning-foundations-v1')
                    }""",
                    [token, username],
                )
                page.goto(f"{BASE_URL}/knowledge", wait_until="networkidle")
                search = page.get_by_test_id("cross-language-search")
                search.wait_for(state="visible", timeout=20_000)
                body = page.locator("body").inner_text()
                assert "机器学习基础" in body
                assert "嵌入式边缘智能" in body
                assert "已验证事实" in body

                page.get_by_label("检索课程").select_option(ML_COURSE)
                page.get_by_test_id("cross-language-query").fill(QUERY)
                page.get_by_test_id("cross-language-submit").click()
                results = page.get_by_test_id("cross-language-results")
                results.wait_for(state="visible", timeout=20_000)
                assert "数据准备" in results.inner_text()
                page.screenshot(path=str(OUTPUT / "01-desktop-two-domains-and-retrieval.png"), full_page=True)
                report["screenshots"].append("01-desktop-two-domains-and-retrieval.png")

                result_rows = page.locator('[data-testid="cross-language-results"] article')
                result_rows.filter(has_text="数据准备").first.get_by_role("button", name="定位来源").click()
                highlight = page.get_by_test_id("citation-highlight")
                highlight.wait_for(state="visible", timeout=20_000)
                assert "missing values" in highlight.inner_text().lower()
                page.screenshot(path=str(OUTPUT / "02-canonical-source-highlight.png"), full_page=True)
                report["screenshots"].append("02-canonical-source-highlight.png")

                page.reload(wait_until="networkidle")
                search.wait_for(state="visible", timeout=20_000)
                assert "嵌入式边缘智能" in page.locator("body").inner_text()

                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_timeout(500)
                sidebar_box = page.locator(".app-sidebar").bounding_box()
                assert sidebar_box and sidebar_box["x"] + sidebar_box["width"] <= 1
                page.get_by_label("检索课程").select_option(EDGE_COURSE)
                page.get_by_test_id("cross-language-query").fill("如何在嵌入式设备部署量化模型")
                page.get_by_test_id("cross-language-submit").click()
                page.get_by_test_id("cross-language-results").wait_for(state="visible", timeout=20_000)
                assert page.evaluate("document.documentElement.scrollWidth") <= 390
                page.screenshot(path=str(OUTPUT / "03-mobile-second-domain.png"), full_page=True)
                report["screenshots"].append("03-mobile-second-domain.png")
                assert not page_errors, page_errors

                report["checks"].update(
                    {
                        "course_ids": sorted(courses),
                        "second_domain_chapters": len(edge_rows),
                        "second_domain_license": "CC-BY-NC-SA-4.0",
                        "graph_governance": graph_payload["governance"],
                        "cross_language_result": "数据准备",
                        "canonical_highlight": True,
                        "refresh_recovery": True,
                        "mobile_width": 390,
                        "mobile_sidebar_hidden": True,
                        "page_or_http_5xx_errors": page_errors,
                        "dotenv_isolated": True,
                    }
                )
                report["result"] = "passed"
                context.close()
                browser.close()
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as destination:
                source.backup(destination)
                report["checks"]["sqlite_integrity"] = destination.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
