"""Verify offline OCR, redacted page overlays and owner isolation in Chromium."""

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
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Page, sync_playwright
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-MEDIA-01" / "browser-e2e"
DB_PATH = ROOT / "outputs" / "_next_media_ocr_e2e.db"
UPLOAD_ROOT = ROOT / "outputs" / "_next_media_ocr_e2e_uploads"
EVIDENCE_DB = OUTPUT / "media_ocr_evidence.db"
PORT = 8789
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-media-ocr-2026!"


def wait_port(open_: bool, timeout: float = 60.0) -> None:
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


def scanned_pdf_bytes() -> bytes:
    image = Image.new("RGB", (1400, 620), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path(r"C:\Windows\Fonts\arial.ttf")
    font = ImageFont.truetype(str(font_path), 50) if font_path.exists() else ImageFont.load_default()
    draw.text((70, 65), "EduMatrix Offline OCR", font=font, fill="black")
    draw.text((70, 180), "score = 95 + 3", font=font, fill="black")
    draw.text((70, 295), "student@example.com", font=font, fill="black")
    buffer = BytesIO()
    output = canvas.Canvas(buffer, pagesize=(700, 310))
    output.drawImage(ImageReader(image), 0, 0, width=700, height=310)
    output.save()
    return buffer.getvalue()


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
    if UPLOAD_ROOT.exists():
        assert UPLOAD_ROOT.resolve().is_relative_to((ROOT / "outputs").resolve())
        shutil.rmtree(UPLOAD_ROOT)
    if EVIDENCE_DB.exists():
        EVIDENCE_DB.unlink()

    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_UPLOAD_DIR": str(UPLOAD_ROOT),
        "EDUMATRIX_AUTH_SECRET_KEY": "next-media-ocr-e2e-secret",
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
        "schema_version": "next.media-ocr-e2e.v1",
        "scope": "real offline OCR, redacted overlay, refresh, owner 403 and mobile geometry",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {},
        "screenshots": [],
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                page = context.new_page()
                try:
                    suffix = str(int(time.time()))
                    owner_name = f"ocr_owner_{suffix}"
                    other_name = f"ocr_other_{suffix}"
                    owner = page.request.post(f"{BASE_URL}/api/auth/register", data={
                        "username": owner_name, "password": PASSWORD, "display_name": "OCR 验收用户",
                    })
                    other = page.request.post(f"{BASE_URL}/api/auth/register", data={
                        "username": other_name, "password": PASSWORD, "display_name": "OCR 隔离用户",
                    })
                    assert owner.ok and other.ok
                    owner_token = owner.json()["access_token"]
                    other_token = other.json()["access_token"]
                    owner_headers = {"Authorization": f"Bearer {owner_token}"}
                    other_headers = {"Authorization": f"Bearer {other_token}"}

                    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30_000)
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'student')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_display_name', 'OCR 验收用户')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [owner_token, owner_name],
                    )
                    page.goto(f"{BASE_URL}/knowledge", wait_until="domcontentloaded", timeout=30_000)
                    page.locator('input[type="file"]').set_input_files({
                        "name": "scan-private.pdf",
                        "mimeType": "application/pdf",
                        "buffer": scanned_pdf_bytes(),
                    })
                    card = page.locator(".knowledge-card").filter(has_text="scan-private.pdf").first
                    card.wait_for(state="visible", timeout=60_000)
                    card.click()
                    workspace = page.get_by_test_id("ocr-region-workspace")
                    workspace.wait_for(state="visible", timeout=30_000)
                    page.get_by_test_id("ocr-redacted-page").wait_for(state="visible", timeout=30_000)
                    overlays = page.get_by_test_id("ocr-region-overlay")
                    assert overlays.count() >= 3
                    formula = overlays.filter(has=page.locator(".sr-only", has_text="公式候选")).first
                    if formula.count():
                        formula.click()
                        assert "公式候选" in page.get_by_test_id("ocr-region-detail").inner_text()
                    body_text = page.locator("body").inner_text()
                    assert "student@example.com" not in body_text
                    assert "已遮盖" in workspace.inner_text()
                    report["checks"]["desktop_overlay"] = {
                        "region_count": overlays.count(),
                        "raw_sensitive_text_visible": False,
                    }
                    report["screenshots"].append(shot(page, "01-desktop-redacted-overlay"))

                    documents = page.request.get(
                        f"{BASE_URL}/api/knowledge/list?student_id={owner_name}", headers=owner_headers,
                    )
                    assert documents.ok
                    document = next(item for item in documents.json() if item["filename"] == "scan-private.pdf")
                    doc_id = document["id"]
                    ocr = page.request.get(
                        f"{BASE_URL}/api/knowledge/{doc_id}/ocr?student_id={owner_name}",
                        headers=owner_headers,
                    )
                    assert ocr.ok
                    ocr_payload = ocr.json()
                    assert ocr_payload["status"] == "ready"
                    assert ocr_payload["sensitive_region_count"] >= 1
                    assert "student@example.com" not in ocr.text()
                    gate = page.request.get(
                        f"{BASE_URL}/api/knowledge/{doc_id}/ocr/externalization-check?student_id={owner_name}",
                        headers=owner_headers,
                    )
                    assert gate.ok and gate.json()["raw_page_allowed"] is False
                    assert gate.json()["redacted_page_allowed"] is True
                    denied_report = page.request.get(
                        f"{BASE_URL}/api/knowledge/{doc_id}/ocr?student_id={owner_name}",
                        headers=other_headers,
                    )
                    denied_page = page.request.get(
                        f"{BASE_URL}/api/knowledge/{doc_id}/ocr/pages/1?student_id={owner_name}",
                        headers=other_headers,
                    )
                    assert denied_report.status == denied_page.status == 403
                    report["checks"]["privacy_and_authorization"] = {
                        "sensitive_regions": ocr_payload["sensitive_region_count"],
                        "raw_page_allowed": False,
                        "redacted_page_allowed": True,
                        "cross_owner_report": denied_report.status,
                        "cross_owner_page": denied_page.status,
                    }

                    page.reload(wait_until="domcontentloaded", timeout=30_000)
                    card = page.locator(".knowledge-card").filter(has_text="scan-private.pdf").first
                    card.wait_for(state="visible", timeout=30_000)
                    card.click()
                    page.get_by_test_id("ocr-redacted-page").wait_for(state="visible", timeout=30_000)
                    report["checks"]["refresh_recovery"] = True

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_timeout(300)
                    workspace.scroll_into_view_if_needed()
                    page.get_by_test_id("ocr-redacted-page").wait_for(state="visible")
                    geometry = page.evaluate(
                        """() => ({
                          viewport: window.innerWidth,
                          documentWidth: document.documentElement.scrollWidth,
                          panel: (() => {
                            const box = document.querySelector('[data-testid="ocr-region-workspace"]')?.getBoundingClientRect()
                            return box ? { x: box.x, width: box.width, right: box.right } : null
                          })()
                        })"""
                    )
                    assert geometry["documentWidth"] <= geometry["viewport"] + 1
                    assert geometry["panel"] and geometry["panel"]["x"] >= 0 and geometry["panel"]["right"] <= 391
                    report["checks"]["mobile_viewport"] = geometry
                    report["screenshots"].append(shot(page, "02-mobile-redacted-overlay"))
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
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT / "manifest.json").write_text(
            json.dumps({"schema_version": "next.media-ocr-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
