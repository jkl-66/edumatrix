"""Verify four-format batch migration, provenance UI and owner isolation in Chromium."""

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

import nbformat
from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-CORE-05" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_core_document_migration_e2e.db"
EVIDENCE_DB = OUTPUT / "document_migration_evidence.db"
PORT = 8785
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-core-document-migration-2026!"


def wait_port(open_: bool, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} state timeout")


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
    wait_port(False, 15)


def notebook_bytes() -> bytes:
    notebook = nbformat.v4.new_notebook()
    notebook.cells = [
        nbformat.v4.new_markdown_cell("# 可追溯 Notebook 课程"),
        nbformat.v4.new_code_cell(
            "print('canonical notebook source')",
            execution_count=9,
            outputs=[nbformat.v4.new_output("stream", name="stdout", text="PRIVATE_OUTPUT\n")],
        ),
    ]
    return nbformat.writes(notebook).encode("utf-8")


def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path.name


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    if EVIDENCE_DB.exists():
        EVIDENCE_DB.unlink()

    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "next-core-document-migration-e2e-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHONUNBUFFERED": "1",
    })
    report: dict[str, Any] = {
        "schema_version": "next.document-migration-e2e.v1",
        "scope": "authenticated mixed batch, canonical provenance, precise notebook location and cross-owner denial",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
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
                    suffix = str(int(time.time()))
                    owner_name = f"document_owner_{suffix}"
                    other_name = f"document_other_{suffix}"
                    owner = page.request.post(f"{BASE_URL}/api/auth/register", data={
                        "username": owner_name, "password": PASSWORD, "display_name": "文档迁移验收用户",
                    })
                    other = page.request.post(f"{BASE_URL}/api/auth/register", data={
                        "username": other_name, "password": PASSWORD, "display_name": "隔离用户",
                    })
                    assert owner.ok and other.ok
                    owner_token = owner.json()["access_token"]
                    other_token = other.json()["access_token"]
                    owner_headers = {"Authorization": f"Bearer {owner_token}"}

                    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'student')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_display_name', '文档迁移验收用户')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [owner_token, owner_name],
                    )
                    page.goto(f"{BASE_URL}/knowledge", wait_until="domcontentloaded", timeout=30_000)
                    file_input = page.locator('input[type="file"]')
                    file_input.set_input_files([
                        {
                            "name": "training.ipynb",
                            "mimeType": "application/x-ipynb+json",
                            "buffer": notebook_bytes(),
                        },
                        {
                            "name": "broken.pdf",
                            "mimeType": "application/pdf",
                            "buffer": b"broken-pdf",
                        },
                    ])
                    batch = page.get_by_test_id("document-batch-results")
                    batch.wait_for(state="visible", timeout=30_000)
                    batch_text = batch.inner_text()
                    assert "training.ipynb" in batch_text and "broken.pdf" in batch_text
                    assert "1 个成功，1 个失败" in page.locator("body").inner_text()
                    report["checks"]["batch_isolation_ui"] = True
                    report["screenshots"].append(shot(page, "01-mixed-batch-result"))

                    card = page.locator(".knowledge-card").filter(has_text="training.ipynb").first
                    card.wait_for(state="visible", timeout=20_000)
                    card.click()
                    provenance = page.get_by_test_id("personal-source-provenance")
                    provenance.wait_for(state="visible", timeout=20_000)
                    provenance_text = provenance.inner_text()
                    assert "edumatrix-notebook-to-markdown-v2" in provenance_text
                    assert "已剥离输出 1" in provenance_text
                    assert "原文件 SHA-256" in provenance_text and "处理文本 SHA-256" in provenance_text
                    locations = page.get_by_test_id("source-location")
                    assert locations.count() == 2
                    locations.nth(1).click()
                    highlight = page.get_by_test_id("citation-highlight")
                    highlight.wait_for(state="visible", timeout=10_000)
                    assert "canonical notebook source" in highlight.inner_text()
                    assert "PRIVATE_OUTPUT" not in page.locator("body").inner_text()
                    report["checks"]["notebook_provenance_ui"] = {
                        "location_count": locations.count(),
                        "outputs_stripped": True,
                        "highlighted": True,
                    }
                    report["screenshots"].append(shot(page, "02-notebook-provenance-location"))

                    documents = page.request.get(
                        f"{BASE_URL}/api/knowledge/list?student_id={owner_name}", headers=owner_headers
                    )
                    assert documents.ok
                    notebook_row = next(item for item in documents.json() if item["filename"] == "training.ipynb")
                    detail = page.request.get(
                        f"{BASE_URL}/api/knowledge/{notebook_row['id']}?student_id={owner_name}",
                        headers=owner_headers,
                    )
                    assert detail.ok
                    detail_payload = detail.json()
                    source_ref_id = detail_payload["source_locations"][0]["source_ref_id"]
                    denied = page.request.get(
                        f"{BASE_URL}/api/v1/source-refs/{source_ref_id}",
                        headers={"Authorization": f"Bearer {other_token}"},
                    )
                    assert denied.status == 403
                    report["checks"]["cross_owner_denied"] = denied.status

                    page.reload(wait_until="domcontentloaded", timeout=30_000)
                    page.locator(".knowledge-card").filter(has_text="training.ipynb").first.wait_for(
                        state="visible", timeout=20_000
                    )
                    report["checks"]["refresh_recovery"] = True

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.locator(".knowledge-card").filter(has_text="training.ipynb").first.click()
                    mobile_panel = page.get_by_test_id("personal-source-provenance")
                    mobile_panel.wait_for(state="visible", timeout=20_000)
                    modal_box = page.locator(".knowledge-modal").bounding_box()
                    assert modal_box and modal_box["x"] >= 0 and modal_box["x"] + modal_box["width"] <= 391
                    report["checks"]["mobile_viewport"] = {"width": 390, "height": 844, "modal_visible": True}
                    report["screenshots"].append(shot(page, "03-mobile-provenance"))
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
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target)
                report["checks"]["sqlite_integrity"] = target.execute("PRAGMA integrity_check").fetchone()[0]
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT / "manifest.json").write_text(
            json.dumps({"schema_version": "next.document-migration-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
