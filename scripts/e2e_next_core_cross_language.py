"""Verify NEXT cross-language course retrieval and canonical source jump in Chromium."""

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
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-CORE-01" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_core_cross_language_e2e.db"
EVIDENCE_DB = OUTPUT / "cross_language_evidence.db"
PORT = 8781
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-core-cross-language-2026!"
QUERY = "训练前为什么要处理缺失值、类别变量和数值尺度"


def wait_port(open_: bool, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not become {'open' if open_ else 'closed'}")


def stop(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, timeout=15)


def unlink(path: Path) -> None:
    if path.exists():
        path.unlink()


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path.name


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_manifest() -> None:
    files = [
        {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
        for path in sorted(OUTPUT.iterdir())
        if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
    ]
    (OUTPUT / "manifest.json").write_text(
        json.dumps({"schema_version": "next.cross-language-e2e-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        unlink(Path(f"{DB_PATH}{suffix}"))
    unlink(EVIDENCE_DB)

    env = os.environ.copy()
    env.update(
        {
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "next-core-cross-language-e2e-secret-2026",
            "EDUMATRIX_LLM_PROVIDER": "deterministic",
            "EDUMATRIX_LLM_MODEL": "deterministic",
            "EDUMATRIX_LLM_API_KEY": "",
            "EDUMATRIX_LLM_ENDPOINT": "",
            "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
            "EDUMATRIX_RELOAD": "0",
            "EDUMATRIX_SANDBOX_MODE": "disabled",
            "EDUMATRIX_HOST": "127.0.0.1",
            "EDUMATRIX_PORT": str(PORT),
            "PYTHONUNBUFFERED": "1",
        }
    )
    report: dict[str, Any] = {
        "schema_version": "next.cross-language-course-e2e.v1",
        "scope": "authenticated Chinese query to persisted English body, strategy diagnostics and canonical highlight",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "query": QUERY,
        "checks": {},
        "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    username = f"next_cross_language_{int(time.time())}"
                    registration = page.request.post(
                        f"{BASE_URL}/api/auth/register",
                        data={"username": username, "password": PASSWORD, "display_name": "跨语言检索验收学生"},
                    )
                    assert registration.ok, registration.text()
                    token = registration.json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}
                    listed = page.request.get(f"{BASE_URL}/api/knowledge/list?student_id={username}", headers=headers)
                    assert listed.ok, listed.text()
                    courses = {item["course_id"] for item in listed.json() if item.get("course_id")}
                    assert "course-machine-learning-foundations-v1" in courses

                    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'student')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_display_name', '跨语言检索验收学生')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                          localStorage.setItem('edumatrix_course_id', 'course-machine-learning-foundations-v1')
                        }""",
                        [token, username],
                    )
                    page.goto(f"{BASE_URL}/knowledge", wait_until="networkidle")
                    page.get_by_test_id("cross-language-search").wait_for(state="visible", timeout=20_000)
                    page.get_by_label("检索课程").select_option("course-machine-learning-foundations-v1")
                    page.get_by_test_id("cross-language-query").fill(QUERY)
                    page.get_by_test_id("cross-language-submit").click()
                    results = page.get_by_test_id("cross-language-results")
                    results.wait_for(state="visible", timeout=20_000)
                    assert "hybrid-glossary-v1" in results.inner_text()
                    assert "数据准备" in results.inner_text()
                    report["screenshots"].append(shot(page, "01-cross-language-results"))

                    api = page.request.get(
                        f"{BASE_URL}/api/v1/next/core/courses/course-machine-learning-foundations-v1/cross-language-search",
                        params={"q": QUERY, "top_k": 5},
                        headers=headers,
                    )
                    assert api.ok, api.text()
                    payload = api.json()
                    target = next(item for item in payload["items"] if item["filename"] == "04_数据准备概览.md")
                    assert target["locatable"] is True
                    assert target["tfidf_rank"] == 1
                    report["checks"]["authenticated_api"] = {
                        "strategy": payload["strategy"],
                        "metadata_excluded": payload["metadata_excluded"],
                        "matched_concepts": payload["matched_concepts"],
                        "target_rank": payload["items"].index(target) + 1,
                        "target_tfidf_rank": target["tfidf_rank"],
                    }

                    result_rows = page.locator('[data-testid="cross-language-results"] article')
                    target_row = result_rows.filter(has_text="数据准备").first
                    target_row.get_by_role("button", name="定位来源").click()
                    highlight = page.get_by_test_id("citation-highlight")
                    highlight.wait_for(state="visible", timeout=20_000)
                    assert "missing values" in highlight.inner_text().lower()
                    report["checks"]["canonical_highlight"] = True
                    report["screenshots"].append(shot(page, "02-canonical-source-highlight"))

                    page.reload(wait_until="networkidle")
                    page.get_by_test_id("cross-language-search").wait_for(state="visible", timeout=20_000)
                    report["checks"]["refresh_recovery"] = True

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.get_by_label("检索课程").select_option("course-machine-learning-foundations-v1")
                    page.get_by_test_id("cross-language-query").fill(QUERY)
                    page.get_by_test_id("cross-language-submit").click()
                    mobile_results = page.get_by_test_id("cross-language-results")
                    mobile_results.wait_for(state="visible", timeout=20_000)
                    box = page.get_by_test_id("cross-language-search").bounding_box()
                    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 391
                    report["checks"]["mobile_viewport"] = {"width": 390, "height": 844, "results_visible": True}
                    report["screenshots"].append(shot(page, "03-mobile-results"))
                    report["result"] = "passed"
                except Exception:
                    try:
                        report["screenshots"].append(shot(page, "error"))
                    except Exception:
                        pass
                    raise
                finally:
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
                report["checks"]["sqlite_integrity"] = destination.execute("PRAGMA integrity_check").fetchone()[0]
        (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_manifest()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
