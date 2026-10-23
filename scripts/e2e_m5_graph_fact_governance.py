"""Browser evidence for verified graph facts versus unreviewed candidates."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "M5_完全体核心学习平台" / "evidence" / "graph-fact-governance-e2e-20260803"
DB_PATH = ROOT / "outputs" / "_m5_graph_fact_governance_e2e_runtime.db"
EVIDENCE_DB = OUTPUT / "m5_graph_fact_governance_evidence.db"
PORT = 8771
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "M5-graph-governance-e2e-2026!"


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


def shot(page: Page, name: str, *, full_page: bool = False) -> str:
    path = OUTPUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full_page)
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
            {"schema_version": "m5.graph-fact-governance-e2e-manifest.v1", "files": files},
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
            "EDUMATRIX_AUTH_SECRET_KEY": "m5-graph-governance-isolated-secret-2026",
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
        "scope": "M5 typed graph fact provenance, candidate isolation, desktop and mobile semantics",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "isolated_database": str(EVIDENCE_DB.relative_to(ROOT)).replace("\\", "/"),
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
                    username = f"m5_graph_governance_{int(time.time())}"
                    registration = page.request.post(
                        f"{BASE_URL}/api/auth/register",
                        data={"username": username, "password": PASSWORD, "display_name": "M5 图谱治理验收学生"},
                    )
                    assert registration.ok, registration.text()
                    token = registration.json()["access_token"]
                    headers = {"Authorization": f"Bearer {token}"}

                    before = page.request.get(f"{BASE_URL}/api/knowledge/graph/stats").json()
                    assert before["governance"]["verified_facts"] == 101
                    assert before["governance"]["canonical_course_facts"] == 57
                    assert before["canonical_seed"] == {
                        "written_facts": 57,
                        "skipped_external_prerequisites": 2,
                        "rejected_facts": 0,
                    }

                    upload = page.request.post(
                        f"{BASE_URL}/api/knowledge/upload?student_id={username}",
                        headers=headers,
                        multipart={
                            "file": {
                                "name": "未审核图谱候选.md",
                                "mimeType": "text/markdown",
                                "buffer": "损失函数是梯度下降的基础。".encode("utf-8"),
                            }
                        },
                    )
                    assert upload.ok, upload.text()
                    upload_payload = upload.json()
                    assert upload_payload["graph_triplets_extracted"] >= 1
                    assert upload_payload["graph_candidate_relations"] >= 1
                    assert upload_payload["graph_edges_written"] == 0

                    after = page.request.get(f"{BASE_URL}/api/knowledge/graph/stats").json()
                    assert after["governance"]["verified_facts"] == before["governance"]["verified_facts"]
                    assert after["governance"]["candidate_relations"] >= 1
                    report["checks"]["fact_candidate_isolation"] = {
                        "verified_before": before["governance"]["verified_facts"],
                        "verified_after": after["governance"]["verified_facts"],
                        "canonical_course_facts": after["governance"]["canonical_course_facts"],
                        "candidate_relations": after["governance"]["candidate_relations"],
                        "upload_written_edges": upload_payload["graph_edges_written"],
                    }

                    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                    page.evaluate(
                        """([token, username]) => {
                          localStorage.setItem('edumatrix_token', token)
                          localStorage.setItem('edumatrix_role', 'student')
                          localStorage.setItem('edumatrix_username', username)
                          localStorage.setItem('edumatrix_student_id', username)
                          localStorage.setItem('edumatrix_display_name', 'M5 图谱治理验收学生')
                          localStorage.setItem('edumatrix_onboarded', 'true')
                        }""",
                        [token, username],
                    )
                    page.goto(f"{BASE_URL}/knowledge", wait_until="networkidle")
                    page.get_by_text(re.compile(r"101\s*条已验证事实\s*/\s*1\s*条候选")).wait_for(
                        state="visible", timeout=20_000
                    )
                    report["screenshots"].append(shot(page, "01-desktop-governance-status"))
                    derived_note = page.get_by_text(
                        "文档标签与共现仅用于浏览，不计入已验证课程前置事实。", exact=True
                    )
                    derived_note.scroll_into_view_if_needed()
                    derived_note.wait_for(state="visible")
                    chart_canvas = page.locator(".knowledge-graph canvas").first
                    chart_canvas.wait_for(state="visible")
                    canvas_check = chart_canvas.evaluate(
                        """canvas => {
                          const context = canvas.getContext('2d')
                          const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
                          const colors = new Set()
                          const stride = Math.max(4, Math.floor(pixels.length / 4000 / 4) * 4)
                          for (let index = 0; index < pixels.length; index += stride) {
                            if (pixels[index + 3] === 0) continue
                            colors.add(`${pixels[index]},${pixels[index + 1]},${pixels[index + 2]},${pixels[index + 3]}`)
                            if (colors.size >= 8) break
                          }
                          return {
                            width: canvas.width,
                            height: canvas.height,
                            sampled_colors: colors.size,
                          }
                        }"""
                    )
                    assert canvas_check["width"] > 0 and canvas_check["height"] > 0
                    assert canvas_check["sampled_colors"] >= 8, canvas_check
                    report["checks"]["derived_association_canvas"] = canvas_check
                    report["screenshots"].append(shot(page, "02-desktop-derived-associations"))

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.reload(wait_until="networkidle")
                    page.get_by_text(re.compile(r"101\s*条已验证事实\s*/\s*1\s*条候选")).wait_for(
                        state="visible", timeout=20_000
                    )
                    report["checks"]["mobile_viewport"] = {"width": 390, "height": 844, "governance_visible": True}
                    report["screenshots"].append(shot(page, "03-mobile-governance-status"))
                    report["result"] = "passed"
                except Exception:
                    try:
                        report["screenshots"].append(shot(page, "error", full_page=True))
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
