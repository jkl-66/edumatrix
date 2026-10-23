"""Verify trusted course citation deep links in a real headless browser."""

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
from urllib.parse import urlencode

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from course_catalog import CURATED_COURSE_MANIFESTS, load_versioned_course_bundle


OUTPUT = ROOT / "outputs" / "M5_完全体核心学习平台" / "evidence" / "source-evidence-jump-e2e-20260802"
DB_PATH = ROOT / "outputs" / "_m5_source_evidence_jump_e2e_runtime.db"
EVIDENCE_DB = OUTPUT / "m5_source_evidence_jump_evidence.db"
PORT = 8770
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "M5-source-evidence-e2e-2026!"


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
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, timeout=15)


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
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
        json.dumps(
            {"schema_version": "m5.source-evidence-jump-e2e-manifest.v1", "files": files},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def unlink(path: Path) -> None:
    if path.exists():
        path.unlink()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        unlink(Path(f"{DB_PATH}{suffix}"))

    env = os.environ.copy()
    env.update(
        {
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "m5-source-evidence-e2e-isolated-secret-2026",
            "EDUMATRIX_LLM_PROVIDER": "deterministic",
            "EDUMATRIX_LLM_MODEL": "deterministic",
            "EDUMATRIX_LLM_API_KEY": "",
            "EDUMATRIX_LLM_ENDPOINT": "",
            "EDUMATRIX_RELOAD": "0",
            "EDUMATRIX_SANDBOX_MODE": "disabled",
            "EDUMATRIX_HOST": "127.0.0.1",
            "EDUMATRIX_PORT": str(PORT),
            "PYTHONUNBUFFERED": "1",
        }
    )
    report: dict[str, Any] = {
        "scope": "M5 trusted source_ref/evidence deep link, refresh recovery, fail-closed error, desktop and mobile UI",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "isolated_database": str(EVIDENCE_DB.relative_to(ROOT)).replace("\\", "/"),
        "checks": {},
        "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen(
                [sys.executable, "run.py"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    username = f"m5_source_jump_{int(time.time())}"
                    registration = page.request.post(
                        f"{BASE_URL}/api/auth/register",
                        data={"username": username, "password": PASSWORD, "display_name": "M5 引用回跳验收学生"},
                    )
                    assert registration.ok, registration.text()
                    token = registration.json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}
                    listed = page.request.get(
                        f"{BASE_URL}/api/knowledge/list?student_id={username}", headers=headers
                    )
                    assert listed.ok, listed.text()

                    bundle = load_versioned_course_bundle(CURATED_COURSE_MANIFESTS[0])
                    document = bundle["documents"][0]
                    evidence = document["chunks"][0]
                    row = next(item for item in listed.json() if item["id"] == document["id"])
                    query = urlencode(
                        {
                            "course_id": row["course_id"],
                            "document_id": row["id"],
                            "source_ref_id": row["source_ref_id"],
                            "evidence_id": evidence.id,
                        }
                    )
                    deep_link = f"{BASE_URL}/knowledge?{query}"

                    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                    page.evaluate(
                        """([token, username, courseId]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'student')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_display_name', 'M5 引用回跳验收学生')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                          localStorage.setItem('edumatrix_course_id', courseId)
                        }""",
                        [token, username, row["course_id"]],
                    )
                    page.goto(deep_link, wait_until="networkidle")
                    highlight = page.get_by_test_id("citation-highlight")
                    highlight.wait_for(state="visible", timeout=20_000)
                    assert evidence.metadata["parent_content"][:120] in highlight.inner_text()
                    box = highlight.bounding_box()
                    assert box and box["y"] < 1000 and box["y"] + min(box["height"], 40) > 0
                    report["screenshots"].append(shot(page, "01-desktop-trusted-highlight"))

                    location = page.request.get(
                        f"{BASE_URL}/api/v1/source-refs/{row['source_ref_id']}/evidence/{evidence.id}",
                        headers=headers,
                    )
                    assert location.ok, location.text()
                    location_payload = location.json()
                    report["checks"]["trusted_location"] = {
                        "schema_version": location_payload["schema_version"],
                        "course_id": location_payload["course_id"],
                        "knowledge_document_id": location_payload["knowledge_document_id"],
                        "char_start": location_payload["char_start"],
                        "char_end": location_payload["char_end"],
                        "fragment_hash": location_payload["fragment_hash"],
                    }

                    page.reload(wait_until="networkidle")
                    page.get_by_test_id("citation-highlight").wait_for(state="visible", timeout=20_000)
                    report["checks"]["refresh_recovery"] = True
                    report["screenshots"].append(shot(page, "02-refresh-recovered-highlight"))

                    invalid_query = urlencode(
                        {
                            "course_id": row["course_id"],
                            "document_id": row["id"],
                            "source_ref_id": row["source_ref_id"],
                            "evidence_id": "evidence-does-not-exist",
                        }
                    )
                    page.goto(f"{BASE_URL}/knowledge?{invalid_query}", wait_until="networkidle")
                    error = page.get_by_test_id("citation-error")
                    error.wait_for(state="visible", timeout=20_000)
                    assert "证据不属于该来源引用" in error.inner_text()
                    assert page.get_by_test_id("citation-highlight").count() == 0
                    report["checks"]["invalid_evidence_fail_closed"] = True
                    report["screenshots"].append(shot(page, "03-invalid-evidence-rejected"))

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.goto(deep_link, wait_until="networkidle")
                    mobile_highlight = page.get_by_test_id("citation-highlight")
                    mobile_highlight.wait_for(state="visible", timeout=20_000)
                    mobile_box = mobile_highlight.bounding_box()
                    assert mobile_box and mobile_box["x"] >= 0 and mobile_box["x"] < 390
                    report["checks"]["mobile_viewport"] = {"width": 390, "height": 844, "highlight_visible": True}
                    report["screenshots"].append(shot(page, "04-mobile-trusted-highlight"))
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
