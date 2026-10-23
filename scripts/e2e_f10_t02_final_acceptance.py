"""F10-T02 all-route desktop and continuous student-journey acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import e2e_f4_phase_journey as phase4  # noqa: E402
import e2e_f5_f8_total_acceptance as total  # noqa: E402
import e2e_f9_phase_acceptance as phase9  # noqa: E402


OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f10_t02_final_acceptance"
SCREENSHOT_DIR = OUTPUT_DIR / "screenshots"
JOURNEY_DIR = SCREENSHOT_DIR / "continuous-journey"
ROUTE_DIR = SCREENSHOT_DIR / "all-routes"
RUNTIME_DIR = OUTPUT_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "f10_t02_final_acceptance.sqlite3"
FIXTURE_PATH = RUNTIME_DIR / "fixture.json"
REPORT_PATH = OUTPUT_DIR / "final_acceptance_report.json"
SERVER_LOG = RUNTIME_DIR / "managed_server.log"
ROUTE_SPEC_PATH = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "target_product_spec" / "target_product_route_spec.json"
FORMAL_DB = ROOT / "edumatrix.db"
PORT = int(os.getenv("EDUMATRIX_F10_T02_PORT", "8996"))
VIEWPORTS = ((1440, 900), (1366, 768))
COURSE_ID = "demo-course-rag-trust-v1"
COURSE_TITLE = "RAG 应用开发与负责任评测实训"
READER_COURSE_ID = "course-machine-learning-foundations-v1"
JOURNEY_USERNAME = "f10-t02-learner"
JOURNEY_PASSWORD = "F10-t02-journey-2026!"
ONBOARDING_USERNAME = "f10-t02-onboarding"
PASSWORDS = {
    JOURNEY_USERNAME: JOURNEY_PASSWORD,
    ONBOARDING_USERNAME: JOURNEY_PASSWORD,
    "lzz": "404404aA",
    "teacher": "admin123",
    "demo-admin": "EduMatrix-Demo-2026",
}
RELATED_ATOMS = (
    "G01-R01", "G01-R02", "G01-R03", "G01-R04", "G01-R05", "G01-R06", "G01-R07",
    "G22-R01", "G22-R02", "G22-R03", "G22-R04", "G22-R05", "G22-R06", "G22-R07",
    "G22-R08", "G22-R09", "G22-R10", "G22-R11", "G22-R12", "G22-R13", "G22-R14",
    "G22-R15", "G22-R16",
)
_ACTIVE_SERVER_PROCESS: subprocess.Popen | None = None


def file_record(path: Path) -> dict[str, object]:
    return {
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "",
    }


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def reset_output() -> None:
    output = OUTPUT_DIR.resolve()
    root = ROOT.resolve()
    if root not in output.parents:
        raise RuntimeError(f"F10-T02 output escapes workspace: {output}")
    for path in (SCREENSHOT_DIR, RUNTIME_DIR):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
    for path in (REPORT_PATH,):
        if path.exists():
            path.unlink()
    JOURNEY_DIR.mkdir(parents=True)
    ROUTE_DIR.mkdir(parents=True)


def configure_environment(port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "f10-t02-isolated-browser-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_ONBOARDING_V2": "1",
        "EDUMATRIX_SANDBOX_MODE": "trusted_local",
        "EDUMATRIX_SANDBOX_TIMEOUT": "10",
        "EDUMATRIX_SANDBOX_MAX_OUTPUT_BYTES": "100000",
        "EDUMATRIX_UPLOAD_DIR": str(RUNTIME_DIR / "uploads"),
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(port),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    os.environ.update(env)
    return env


def configure_reused_harnesses(port: int) -> None:
    base_url = f"http://127.0.0.1:{port}"
    phase4.OUTPUT_DIR = JOURNEY_DIR / "f4"
    phase4.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    phase4.DB_PATH = DB_PATH
    phase4.PORT = port
    phase4.BASE_URL = base_url
    phase4.COURSE_ID = COURSE_ID
    phase4.PASSWORD = JOURNEY_PASSWORD

    total.OUTPUT_DIR = OUTPUT_DIR
    total.BROWSER_DIR = JOURNEY_DIR / "f5-f8"
    total.RUNTIME_DIR = RUNTIME_DIR
    total.DB_PATH = DB_PATH
    total.REPORT_PATH = RUNTIME_DIR / "reused-f5-f8-report.json"
    total.COURSE_ID = COURSE_ID
    total.USERNAME = JOURNEY_USERNAME
    total.PASSWORD = JOURNEY_PASSWORD
    total.FORMAL_DB = FORMAL_DB
    total.reader.COURSE_ID = READER_COURSE_ID

    helper_modules = (
        total.bundle, total.handout, total.mindmap, total.training, total.quiz, total.model,
        total.sandbox, total.code_review, total.feynman, total.formal, total.review, total.notes,
        total.feedback,
    )
    for module in helper_modules:
        if hasattr(module, "USERNAME"):
            module.USERNAME = JOURNEY_USERNAME
        if hasattr(module, "PASSWORD"):
            module.PASSWORD = JOURNEY_PASSWORD
        if hasattr(module, "COURSE_ID"):
            module.COURSE_ID = COURSE_ID
        if hasattr(module, "DB_PATH"):
            module.DB_PATH = DB_PATH
    total.configure_helpers()

    phase9.DB_PATH = DB_PATH
    phase9.RUNTIME_DIR = RUNTIME_DIR


def database_scalar(sql: str, params: tuple = ()) -> object:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        row = db.execute(sql, params).fetchone()
    return row[0] if row else None


def attach_course(username: str, course_id: str = COURSE_ID) -> None:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        owner = db.execute("SELECT public_id FROM users WHERE username=?", (username,)).fetchone()
        if owner is None:
            raise RuntimeError(f"missing route-smoke user: {username}")
        db.execute(
            """INSERT OR IGNORE INTO course_memberships
               (id, course_id, user_public_id, role, status, created_at, updated_at)
               VALUES (?, ?, ?, 'student', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (f"cm-f10-t02-{username}-{course_id}", course_id, owner[0]),
        )
        db.commit()


def align_image_document_owner(
    username: str,
    fixture: dict[str, object],
    env: dict[str, str],
) -> dict[str, object]:
    source_id = str(fixture["pdf_source_id"])
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        user = db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
        if user is None:
            raise RuntimeError(f"missing image document owner: {username}")
        row = db.execute(
            """SELECT sd.legacy_document_id,sd.parser_metadata,kd.student_id
               FROM source_documents sd
               JOIN knowledge_documents kd ON kd.id=sd.legacy_document_id
               WHERE sd.id=?""",
            (source_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"missing image document fixture: {source_id}")
        document_id, parser_metadata, previous_owner = row

    report = (json.loads(parser_metadata or "{}") or {}).get("ocr") or {}
    pages = report.get("pages") or []
    if not pages:
        raise RuntimeError(f"image document has no OCR pages: {source_id}")
    upload_root = Path(env["EDUMATRIX_UPLOAD_DIR"])
    copied_assets: list[str] = []
    for page in pages:
        asset_name = Path(str(page.get("asset_name") or "")).name
        expected_hash = str(page.get("redacted_image_sha256") or "")
        source_asset = upload_root / str(previous_owner) / str(document_id) / "ocr" / asset_name
        target_asset = upload_root / username / str(document_id) / "ocr" / asset_name
        if not asset_name or not source_asset.is_file():
            raise RuntimeError(f"missing image fixture asset: {source_asset}")
        if hashlib.sha256(source_asset.read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError(f"image fixture hash mismatch: {source_asset}")
        target_asset.parent.mkdir(parents=True, exist_ok=True)
        if source_asset.resolve() != target_asset.resolve():
            shutil.copy2(source_asset, target_asset)
        if hashlib.sha256(target_asset.read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError(f"copied image fixture hash mismatch: {target_asset}")
        copied_assets.append(str(target_asset.relative_to(ROOT)).replace("\\", "/"))

    with sqlite3.connect(DB_PATH, timeout=20) as db:
        cursor = db.execute(
            "UPDATE knowledge_documents SET student_id=? WHERE id=? AND student_id=?",
            (username, document_id, previous_owner),
        )
        if previous_owner != username and cursor.rowcount != 1:
            raise RuntimeError(f"image document owner update failed: {document_id}")
        db.commit()
    return {
        "source_id": source_id,
        "document_id": document_id,
        "previous_owner": previous_owner,
        "owner": username,
        "assets": copied_assets,
    }


def prepare_fixture(port: int) -> dict[str, object]:
    reset_output()
    env = configure_environment(port)
    configure_reused_harnesses(port)
    total.bundle.seed_fixture(env)
    document_fixture = total.reader.seed_fixture(env, initialize_demo=False)
    market_fixture = phase9.seed_marketplace()
    fixture = {
        "course_id": COURSE_ID,
        "course_title": COURSE_TITLE,
        "document": document_fixture,
        "market": market_fixture,
        "teacher_student_id": "lzz",
    }
    FIXTURE_PATH.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return fixture


def serve(port: int) -> None:
    configure_environment(port)
    configure_reused_harnesses(port)
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=False)


def wait_for_server(process: subprocess.Popen, port: int, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"managed F10-T02 server exited with {process.returncode}; see {SERVER_LOG}")
        if port_is_open(port):
            return
        time.sleep(0.25)
    raise TimeoutError(f"managed F10-T02 server did not open port {port}")


def stop_server(process: subprocess.Popen | None, port: int) -> None:
    total.bundle.stop_service(process, port)
    if port_is_open(port):
        raise RuntimeError(f"managed F10-T02 server left port {port} listening")


def digest_rows(rows: list[tuple]) -> dict[str, object]:
    encoded = json.dumps(rows, ensure_ascii=False, default=str, separators=(",", ":"))
    return {"rows": len(rows), "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}


def table_digest(tables: tuple[str, ...]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        for table in tables:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,),
            ).fetchone()
            if not exists:
                continue
            result[table] = digest_rows(db.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall())
    return result


def database_audit() -> dict[str, object]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "learning_events": db.execute("SELECT COUNT(*) FROM learning_events").fetchone()[0],
            "model_calls": db.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0],
        }


def api_login(context: BrowserContext, base_url: str, username: str) -> dict[str, object]:
    response = context.request.post(
        f"{base_url}/api/auth/login",
        form={"username": username, "password": PASSWORDS[username]},
    )
    if not response.ok:
        raise AssertionError(f"login failed for {username}: {response.status} {response.text()}")
    return response.json()


def add_session(
    context: BrowserContext,
    session: dict[str, object],
    *,
    onboarded: bool,
    course_id: str = COURSE_ID,
    course_title: str = COURSE_TITLE,
) -> None:
    state = json.dumps({
        "token": session["access_token"],
        "username": session["username"],
        "displayName": session.get("display_name") or session["username"],
        "role": session["role"],
        "studentId": session.get("student_id") or session["username"],
        "onboarded": "true" if onboarded else "false",
        "courseId": course_id,
        "courseTitle": course_title,
    }, ensure_ascii=False)
    context.add_init_script(f"""
      const state = {state};
      localStorage.setItem('edumatrix_token', state.token);
      localStorage.setItem('edumatrix_username', state.username);
      localStorage.setItem('edumatrix_display_name', state.displayName);
      localStorage.setItem('edumatrix_role', state.role);
      localStorage.setItem('edumatrix_student_id', state.studentId);
      localStorage.setItem('edumatrix_onboarded', state.onboarded);
      localStorage.setItem('edumatrix_course_id', state.courseId);
      localStorage.setItem('edumatrix_course_title', state.courseTitle);
    """)


def browser_diagnostics(page: Page, base_url: str, label: str, report: dict[str, object]) -> dict[str, object]:
    origin = urlparse(base_url).netloc
    diagnostics: dict[str, object] = {
        "label": label,
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "off_origin_requests": [],
    }
    report["browser_contexts"].append(diagnostics)
    page.on("response", lambda response: diagnostics["http_errors"].append({
        "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: diagnostics["failed_requests"].append({
        "url": request.url, "failure": request.failure,
    }))
    page.on("pageerror", lambda error: diagnostics["page_errors"].append(str(error)))
    page.on("console", lambda message: diagnostics["console_errors"].append(message.text)
            if message.type == "error" else None)
    page.on("request", lambda request: diagnostics["off_origin_requests"].append(request.url)
            if urlparse(request.url).scheme in {"http", "https"}
            and urlparse(request.url).netloc != origin else None)
    return diagnostics


def visible_metrics(page: Page) -> dict[str, object]:
    return page.evaluate("""() => {
      const visible = (el) => {
        const style = getComputedStyle(el), box = el.getBoundingClientRect();
        const closed = el.closest('details:not([open])');
        if (closed && !closed.querySelector(':scope > summary')?.contains(el)) return false;
        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) <= 0
            || box.width <= 1 || box.height <= 1) return false;
        let left = Math.max(box.left, 0), right = Math.min(box.right, innerWidth);
        let top = Math.max(box.top, 0), bottom = Math.min(box.bottom, innerHeight);
        if (right - left <= 1 || bottom - top <= 1) return false;
        const clippingOverflow = new Set(['hidden', 'clip', 'auto', 'scroll']);
        for (let ancestor = el.parentElement; ancestor; ancestor = ancestor.parentElement) {
          const ancestorStyle = getComputedStyle(ancestor);
          const clipsX = clippingOverflow.has(ancestorStyle.overflowX);
          const clipsY = clippingOverflow.has(ancestorStyle.overflowY);
          if (!clipsX && !clipsY) continue;
          const ancestorBox = ancestor.getBoundingClientRect();
          if (clipsX) {
            left = Math.max(left, ancestorBox.left);
            right = Math.min(right, ancestorBox.right);
          }
          if (clipsY) {
            top = Math.max(top, ancestorBox.top);
            bottom = Math.min(bottom, ancestorBox.bottom);
          }
          if (right - left <= 1 || bottom - top <= 1) return false;
        }
        return true;
      };
      const textNodes = [...document.querySelectorAll('button,a[href],h1,h2,h3,h4,p,span,strong,small,label,dt,dd,li,time')]
        .filter(el => visible(el) && (el.textContent || '').trim());
      const controls = [...document.querySelectorAll('button,a[href],input,select,textarea,[role="button"],[role="tab"]')]
        .filter(visible);
      const accessibilityControls = [...document.querySelectorAll('button,a[href],input,select,textarea,[role="button"],[role="tab"],[role="textbox"]')]
        .filter(visible)
        .filter(el => el.getAttribute('aria-hidden') !== 'true' || el.tabIndex >= 0);
      const collisions = [];
      for (let i = 0; i < controls.length; i += 1) {
        for (let j = i + 1; j < controls.length; j += 1) {
          const a = controls[i], b = controls[j];
          if (a.contains(b) || b.contains(a)) continue;
          const x = a.getBoundingClientRect(), y = b.getBoundingClientRect();
          const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left);
          const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top);
          if (overlapW > 4 && overlapH > 4) collisions.push([
            (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 48),
            (b.innerText || b.getAttribute('aria-label') || '').trim().slice(0, 48),
          ]);
        }
      }
      const clipped = textNodes.filter(el => {
        const style = getComputedStyle(el), box = el.getBoundingClientRect();
        if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false;
        if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false;
        const clippedX = ['hidden', 'clip'].includes(style.overflowX) && el.scrollWidth > el.clientWidth + 3;
        const clippedY = ['hidden', 'clip'].includes(style.overflowY) && el.scrollHeight > el.clientHeight + 6;
        return box.right > innerWidth + 1 || box.left < -1 ||
          clippedX || clippedY;
      }).map(el => (el.textContent || '').trim().slice(0, 80)).slice(0, 30);
      const smallText = textNodes.filter(el => Number.parseFloat(getComputedStyle(el).fontSize) < 13.9)
        .map(el => ({ text: el.textContent.trim().slice(0, 60), size: getComputedStyle(el).fontSize })).slice(0, 30);
      const hasAccessibleName = el => {
        const attribute = name => (el.getAttribute(name) || '').trim();
        const associatedLabel = el.labels && [...el.labels]
          .some(label => (label.textContent || '').trim());
        const placeholder = ['INPUT', 'TEXTAREA'].includes(el.tagName) && attribute('placeholder');
        return Boolean(
          (el.innerText || '').trim() || attribute('aria-label') || attribute('aria-labelledby') ||
          attribute('title') || associatedLabel || placeholder
        );
      };
      const inaccessibleControls = accessibilityControls.filter(el => !hasAccessibleName(el))
        .map(el => ({ tag: el.tagName, className: String(el.className).slice(0, 80) })).slice(0, 30);
      const gradients = [...document.querySelectorAll('body *')].filter(visible)
        .filter(el => getComputedStyle(el).backgroundImage.includes('gradient'))
        .map(el => String(el.className).slice(0, 80)).slice(0, 30);
      const backdrop = [...document.querySelectorAll('body *')].filter(visible)
        .filter(el => { const value = getComputedStyle(el).backdropFilter; return value && value !== 'none'; })
        .map(el => String(el.className).slice(0, 80)).slice(0, 30);
      const parseRgb = value => {
        const match = value.match(/[\d.]+/g);
        return match && match.length >= 3 ? match.slice(0, 3).map(Number) : null;
      };
      const luminance = rgb => {
        const values = rgb.map(value => {
          const normalized = value / 255;
          return normalized <= .03928 ? normalized / 12.92 : ((normalized + .055) / 1.055) ** 2.4;
        });
        return .2126 * values[0] + .7152 * values[1] + .0722 * values[2];
      };
      const primaryCandidates = [...document.querySelectorAll('.button-primary,.primary-button,.publish-button,[data-primary-action="true"]')]
        .filter(visible);
      const primary = primaryCandidates.filter(el =>
        !el.matches(':disabled') && (el.getAttribute('aria-disabled') || '').toLowerCase() !== 'true'
          && !el.classList.contains('secondary')
      );
      const lowContrastPrimary = primary.map(el => {
        const style = getComputedStyle(el), foreground = parseRgb(style.color), background = parseRgb(style.backgroundColor);
        if (!foreground || !background) return null;
        const high = Math.max(luminance(foreground), luminance(background));
        const low = Math.min(luminance(foreground), luminance(background));
        return { text: (el.innerText || '').trim().slice(0, 48), ratio: (high + .05) / (low + .05) };
      }).filter(item => item && item.ratio < 4.5);
      const themedColorRegression = [...document.querySelectorAll('body *')].filter(visible).filter(el => {
        const box = el.getBoundingClientRect();
        if (box.width * box.height < 3000) return false;
        const rgb = parseRgb(getComputedStyle(el).backgroundColor);
        if (!rgb) return false;
        const [r, g, b] = rgb.map(value => value / 255);
        const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
        const light = (max + min) / 2;
        const saturation = delta === 0 ? 0 : delta / (1 - Math.abs(2 * light - 1));
        let hue = 0;
        if (delta) {
          if (max === r) hue = 60 * (((g - b) / delta) % 6);
          else if (max === g) hue = 60 * ((b - r) / delta + 2);
          else hue = 60 * ((r - g) / delta + 4);
          if (hue < 0) hue += 360;
        }
        return (hue >= 70 && hue <= 170 && saturation > .2)
          || (hue >= 15 && hue <= 50 && saturation > .28 && light < .7)
          || (hue > 170 && hue <= 220 && saturation > .22 && light > .62)
          || (hue > 220 && hue <= 300 && saturation > .3);
      }).map(el => ({ className: String(el.className).slice(0, 80), color: getComputedStyle(el).backgroundColor })).slice(0, 30);
      const cardish = el => [...el.classList].some(name => /(^|[-_])card$/.test(name));
      const nestedCards = [...document.querySelectorAll('body *')].filter(el => visible(el) && cardish(el))
        .filter(el => { let parent = el.parentElement; while (parent) { if (cardish(parent)) return true; parent = parent.parentElement; } return false; })
        .map(el => String(el.className).slice(0, 100)).slice(0, 30);
      const headings = [...document.querySelectorAll('h1,h2,h3')].filter(visible)
        .map(el => el.innerText.trim()).filter(Boolean).slice(0, 8);
      const actionLabels = controls.map(el => (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim())
        .filter(Boolean).slice(0, 20);
      const primaryActionLabels = primary.map(el =>
        (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim()
      ).filter(Boolean).slice(0, 20);
      const bodyStyle = getComputedStyle(document.body);
      return {
        viewport: [innerWidth, innerHeight],
        documentWidth: document.documentElement.scrollWidth,
        bodyTextLength: (document.body.innerText || '').trim().length,
        headings, actionLabels,
        collisions, clipped, smallText, inaccessibleControls, gradients, backdrop,
        lowContrastPrimary, themedColorRegression, nestedCards,
        primaryActionCount: primary.length, primaryActionLabels,
        fontFamily: bodyStyle.fontFamily,
        letterSpacing: bodyStyle.letterSpacing,
      };
    }""")


def capture_route(
    page: Page,
    *,
    name: str,
    spec: dict[str, object],
    concrete_path: str,
    viewport: tuple[int, int],
    account: str,
    fixture_label: str,
) -> dict[str, object]:
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)
    metrics = visible_metrics(page)
    screenshot = ROUTE_DIR / f"{name}-{viewport[0]}x{viewport[1]}.png"
    page.screenshot(path=screenshot, full_page=False, animations="disabled")
    actual_path = urlparse(page.url).path
    result = {
        "route": spec["path"],
        "concrete_route": concrete_path,
        "viewport": list(viewport),
        "account": account,
        "dataFixture": fixture_label,
        "expectedState": {
            "label": spec["label"],
            "purpose": spec["purpose"],
            "primary_action": spec["primary_action"],
        },
        "actualEvidence": {"final_path": actual_path, **metrics},
        "screenshot": str(screenshot.relative_to(ROOT)).replace("\\", "/"),
        "result": "PASSED",
    }
    assert actual_path == urlparse(concrete_path).path, result
    assert actual_path != "/context-recovery", result
    assert metrics["documentWidth"] <= viewport[0], result
    assert metrics["bodyTextLength"] >= 80, result
    for key in (
        "collisions", "clipped", "smallText", "inaccessibleControls", "gradients", "backdrop",
        "lowContrastPrimary", "themedColorRegression", "nestedCards",
    ):
        assert metrics[key] == [], {"route": concrete_path, "metric": key, "value": metrics[key]}
    assert metrics["primaryActionCount"] <= 1, {"route": concrete_path, "primary": metrics["primaryActionLabels"]}
    assert metrics["letterSpacing"] in {"normal", "0px"}, {"route": concrete_path, "letterSpacing": metrics["letterSpacing"]}
    return result


def goto(page: Page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=12_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_function("() => (document.body.innerText || '').trim().length >= 80", timeout=45_000)


def register_onboarding_fixture(context: BrowserContext, base_url: str) -> None:
    response = context.request.post(
        f"{base_url}/api/auth/register",
        data={
            "username": ONBOARDING_USERNAME,
            "password": JOURNEY_PASSWORD,
            "display_name": "F10-T02 首次引导学生",
        },
    )
    if response.status not in {200, 201, 409}:
        raise AssertionError(f"onboarding fixture registration failed: {response.status} {response.text()}")
    attach_course(ONBOARDING_USERNAME)


def route_runtime(
    path: str,
    fixture: dict[str, object],
    resources: dict[str, str],
    job_id: str,
    exam_id: str,
) -> tuple[str, str, str]:
    account = "student"
    concrete = path
    label = "continuous-student"
    resource_routes = {
        "/workspace/resources/handouts/:resourceId": resources["handout"],
        "/workspace/resources/training-tasks/:resourceId": resources["training_task"],
        "/workspace/resources/mindmaps/:resourceId": resources["mind_map"],
        "/workspace/resources/videos/:resourceId": resources["video"],
        "/workspace/resources/decks/:resourceId": resources["deck"],
        "/workspace/resources/models/:resourceId": resources["interactive_model"],
        "/workspace/resources/quizzes/:resourceId": resources["quiz"],
        "/workspace/code/:resourceId": resources["code_sandbox"],
        "/workspace/feynman/:resourceId": resources["feynman"],
    }
    if path in {"/landing", "/login"}:
        return path, "public", "public"
    if path == "/onboarding":
        return path, "onboarding", "fresh-student-no-upload"
    if path.startswith("/teacher/"):
        account = "teacher"
        label = "competition-demo-teacher"
    elif path.startswith("/admin/"):
        account = "admin"
        label = "competition-demo-admin"
    if path in resource_routes:
        concrete = path.replace(":resourceId", resource_routes[path])
    elif path == "/workspace/resources/bundles/:bundleId":
        concrete = path.replace(":bundleId", job_id)
    elif path == "/workspace/assessment/exams/:examId":
        concrete = path.replace(":examId", exam_id)
    elif path == "/knowledge/documents/:documentId":
        concrete = path.replace(":documentId", str(fixture["document"]["source_id"]))
        concrete += "?" + urlencode({"course_id": str(fixture["document"]["course_id"])})
        account = "reader"
        label = "prebuilt-knowledge-document"
    elif path in {"/knowledge/courses/:courseId", "/knowledge/graph/:courseId", "/teacher/courses/:courseId"}:
        concrete = path.replace(":courseId", COURSE_ID)
    elif path == "/marketplace/items/:itemId":
        concrete = path.replace(":itemId", str(fixture["market"]["published_listings"]["resource"]["id"]))
        label = "published-marketplace-resource"
    elif path == "/teacher/students/:studentId":
        concrete = path.replace(":studentId", str(fixture["teacher_student_id"]))
    if path.startswith("/teacher/"):
        concrete += ("&" if "?" in concrete else "?") + urlencode({"courseId": COURSE_ID})
    elif path.startswith("/workspace/") or path in {"/", "/profile", "/profile/learning", "/profile/history", "/learn"}:
        concrete += ("&" if "?" in concrete else "?") + urlencode({"course_id": COURSE_ID})
    elif path.startswith("/knowledge") and ":documentId" not in path:
        concrete += ("&" if "?" in concrete else "?") + urlencode({"course_id": COURSE_ID})
    return concrete, account, label


def open_session_context(
    browser: Browser,
    base_url: str,
    viewport: tuple[int, int],
    account: str,
    report: dict[str, object],
    fixture: dict[str, object],
) -> tuple[BrowserContext, Page]:
    context = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        locale="zh-CN",
        color_scheme="light",
        accept_downloads=True,
    )
    if account != "public":
        username = {
            "student": JOURNEY_USERNAME,
            "onboarding": ONBOARDING_USERNAME,
            "reader": "lzz",
            "teacher": "teacher",
            "admin": "demo-admin",
        }[account]
        session = api_login(context, base_url, username)
        document = fixture["document"]
        add_session(
            context,
            session,
            onboarded=account != "onboarding",
            course_id=str(document["course_id"]) if account == "reader" else COURSE_ID,
            course_title="机器学习基础" if account == "reader" else COURSE_TITLE,
        )
    page = context.new_page()
    page.set_default_timeout(45_000)
    browser_diagnostics(page, base_url, f"route-{account}-{viewport[0]}x{viewport[1]}", report)
    return context, page


def run_all_routes(
    browser: Browser,
    base_url: str,
    fixture: dict[str, object],
    resources: dict[str, str],
    job_id: str,
    exam_id: str,
    report: dict[str, object],
) -> None:
    specs = json.loads(ROUTE_SPEC_PATH.read_text(encoding="utf-8"))
    assert len(specs) == 50
    protected_tables = (
        "learning_events", "profile_snapshots", "student_profiles", "learning_paths", "path_nodes",
        "wrong_questions", "review_plans", "notes", "assessment_attempts", "model_calls",
    )
    setup_context = browser.new_context()
    try:
        register_onboarding_fixture(setup_context, base_url)
    finally:
        setup_context.close()
    before = table_digest(protected_tables)
    for viewport in VIEWPORTS:
        contexts: dict[str, BrowserContext] = {}
        pages: dict[str, Page] = {}
        try:
            for account in ("public", "onboarding", "student", "reader", "teacher", "admin"):
                contexts[account], pages[account] = open_session_context(
                    browser, base_url, viewport, account, report, fixture,
                )
            for index, spec in enumerate(specs, start=1):
                concrete, account, fixture_label = route_runtime(
                    spec["path"], fixture, resources, job_id, exam_id,
                )
                page = pages[account]
                goto(page, base_url, concrete)
                result = capture_route(
                    page,
                    name=f"{index:02d}-{spec['label']}",
                    spec=spec,
                    concrete_path=concrete,
                    viewport=viewport,
                    account=account,
                    fixture_label=fixture_label,
                )
                report["route_results"].append(result)
        finally:
            for context in contexts.values():
                context.close()
    after = table_digest(protected_tables)
    report["ordinary_browse"] = {
        "before": before,
        "after": after,
        "unchanged": before == after,
    }
    assert before == after, report["ordinary_browse"]
    by_viewport = {
        f"{viewport[0]}x{viewport[1]}": sorted(
            item["route"] for item in report["route_results"] if item["viewport"] == list(viewport)
        )
        for viewport in VIEWPORTS
    }
    expected = sorted(spec["path"] for spec in specs)
    assert all(routes == expected for routes in by_viewport.values()), by_viewport
    report["route_coverage"] = {
        "source": str(ROUTE_SPEC_PATH.relative_to(ROOT)).replace("\\", "/"),
        "expected_routes": expected,
        "by_viewport": by_viewport,
        "records": len(report["route_results"]),
    }


def initial_total_report() -> dict[str, object]:
    return {
        "atoms": {},
        "checks": {},
        "database": {},
        "visual": {},
        "feedback_snapshots": {},
        "screenshots": [],
        "http_errors": [],
        "expected_http_errors": [],
        "failed_requests": [],
        "expected_network_errors": [],
        "page_errors": [],
        "console_errors": [],
        "expected_console_errors": [],
        "external_requests": [],
        "expected_injected_failures": [],
        "expected_injected_console": [],
    }


def run_continuous_journey(
    browser: Browser,
    base_url: str,
    env: dict[str, str],
    port: int,
    process: subprocess.Popen,
    fixture: dict[str, object],
    report: dict[str, object],
) -> tuple[subprocess.Popen, dict[str, object]]:
    global _ACTIVE_SERVER_PROCESS
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        color_scheme="light",
        accept_downloads=True,
    )
    page = context.new_page()
    page.set_default_timeout(45_000)
    f4_report: dict[str, object] = {
        "screenshots": [], "layout_checks": {}, "checks": {},
        "http_errors": [], "failed_requests": [], "page_errors": [], "console_errors": [],
    }
    total_report = initial_total_report()
    journey = {
        "username": JOURNEY_USERNAME,
        "course_id": COURSE_ID,
        "steps": ["landing", "login"],
        "f4": f4_report,
        "f5_f8": total_report,
    }
    report["journey"] = journey
    try:
        phase4.diagnostics(page, f4_report)
        page.goto(f"{base_url}/landing", wait_until="networkidle", timeout=60_000)
        phase4.capture(page, f4_report, "00-landing-1440x900.png")
        phase4.run_journey(page, f4_report, JOURNEY_USERNAME)
        phase4.validate_errors(f4_report)
        document_fixture = fixture["document"]
        journey["document_owner_alignment"] = align_image_document_owner(
            JOURNEY_USERNAME,
            document_fixture,
            env,
        )
        attach_course(JOURNEY_USERNAME, str(document_fixture["course_id"]))
        attach_course(JOURNEY_USERNAME, str(document_fixture["pdf_course_id"]))
        total_report["fixture"] = {
            "owner_public_id": total.owner_id(),
            "course_id": COURSE_ID,
        }
        journey["steps"].extend([
            "natural-language-onboarding", "entry-diagnostic", "diagnostic-report", "learning-profile",
            "total-path", "resource-bundle-partial-failure", "resource-bundle-recovery",
            "required-task-completion", "formal-exam-unlocked",
        ])
        token = str(page.evaluate("() => localStorage.getItem('edumatrix_token')") or "")
        if not token:
            raise AssertionError("continuous journey lost the authenticated student session")
        job_id = str(f4_report["checks"]["resource_job_idempotency"]["job_id"])
        response = page.request.get(
            f"{base_url}/api/v1/resource-bundles/generation-jobs/{job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.ok, response.text()
        job = response.json()
        resources = {item["type"]: item["resource"]["resource_id"] for item in job["items"]}
        assert set(resources) == set(total.RESOURCE_TYPES), resources
        journey["job_id"] = job_id
        journey["resources"] = resources

        fault: dict[str, object] = {"restart_active": False}
        total.attach_diagnostics(page, total_report, fault)
        total.inspect_resource_center(page, base_url, resources, total_report)
        total.inspect_f5_resources(page, base_url, resources, total_report)
        total.exercise_quiz(page, base_url, resources, total_report)
        total.exercise_model(page, base_url, env, resources, total_report)
        total.exercise_code(page, base_url, env, resources, total_report)
        total.exercise_feynman(page, base_url, resources, total_report)
        total.exercise_documents(page, base_url, document_fixture, total_report)
        journey["steps"].extend([
            "resource-center", "handout", "mind-map", "training-task", "video-recommendation",
            "web-deck", "quiz-resource", "interactive-model", "code-sandbox", "feynman",
            "knowledge-text-selection", "knowledge-image-selection",
        ])

        total.seed_formal_questions(env, job_id)
        exam_id, formal_event = total.complete_formal_exam(page, base_url, total_report)
        journey["exam_id"] = exam_id
        journey["formal_event_id"] = formal_event["event_id"]
        journey["steps"].extend(["formal-exam", "formal-exam-report"])
        process = total.exercise_feedback(
            page, base_url, env, port, process, formal_event, total_report, fault,
        )
        _ACTIVE_SERVER_PROCESS = process
        total.exercise_wrong_questions(page, base_url, total_report)
        plan = total.latest_review_plan()
        total.exercise_notes(page, base_url, resources, plan, total_report)
        total.exercise_review(page, base_url, plan, total_report)
        total.verify_protected_pages(page, base_url, total_report)
        journey["steps"].extend([
            "feedback-to-profile", "feedback-to-path", "wrong-questions", "review-calendar",
            "notes", "resource-history", "continue-deep-learning",
        ])
        for key in ("http_errors", "failed_requests", "page_errors", "console_errors", "external_requests"):
            assert total_report[key] == [], {key: total_report[key]}
        journey["status"] = "PASSED"
        return process, {
            "job_id": job_id,
            "resources": resources,
            "exam_id": exam_id,
            "formal_event": formal_event,
            "owner_public_id": total.owner_id(),
        }
    except Exception:
        journey["status"] = "FAILED"
        journey["traceback"] = traceback.format_exc()
        raise
    finally:
        context.close()


def build_atomic_evidence(report: dict[str, object]) -> dict[str, dict[str, object]]:
    route_evidence = "final_acceptance_report.json#route_results (50 routes x 2 desktop viewports)"
    journey_evidence = "final_acceptance_report.json#journey (one student, one isolated SQLite, one Chromium)"
    browse_evidence = "final_acceptance_report.json#ordinary_browse"
    evidence: dict[str, dict[str, object]] = {}
    meanings = {
        "G01-R01": "100 route records verify the frozen fog-white/white/ink-blue-gray palette and no large forbidden theme surface.",
        "G01-R02": "Every route rejects gradients and backdrop blur; screenshots provide full runtime evidence.",
        "G01-R03": "Every visible text sample is at least 14px and unclipped at both desktop sizes.",
        "G01-R04": "Every route records headings and visible actions; the continuous journey proves the next action at each learning step.",
        "G01-R05": "Every route rejects nested card containers, overlap and decorative panel regressions.",
        "G01-R06": "The same 50-route set is captured at exactly 1440x900 and 1366x768; no mobile claim is made.",
        "G01-R07": "Computed fonts, spacing, primary contrast, geometry and theme tokens are checked on every route.",
        "G22-R01": "The new student completes the formal entry diagnostic and reaches its report.",
        "G22-R02": "The same student continues from diagnostic evidence to profile and the total learning path.",
        "G22-R03": "One contextual job produces all nine resources for one course and knowledge point.",
        "G22-R04": "Only explicit trusted completion changes required path tasks; ordinary route browsing is byte-stable.",
        "G22-R05": "The journey captures the locked gate and its later unlock after required evidence.",
        "G22-R06": "A formal submission reaches report, profile, path, wrong-question and review projections.",
        "G22-R07": "Wrong questions, review, notes and resource history are exercised after the report.",
        "G22-R08": "The formal Chat route remains reachable as contextual help without owning full learning products.",
        "G22-R09": "All nine products have unique resource IDs and dedicated route evidence.",
        "G22-R10": "Resource center history and representative resource version/recovery flows are exercised.",
        "G22-R11": "The Chat route is checked without off-origin calls or prohibited private runtime leakage.",
        "G22-R12": "Quiz, sandbox and knowledge routes are each independently reachable at their unique formal destination.",
        "G22-R13": "The new student completes natural-language onboarding without uploading course material.",
        "G22-R14": "One path action creates one recoverable nine-item resource bundle with stable IDs.",
        "G22-R15": "The locked exam state names missing required work and later exposes the exam builder.",
        "G22-R16": "Diagnostic save, resource item, model, code, Feynman, note and feedback failures preserve state and recover.",
    }
    for atom in RELATED_ATOMS:
        references = [route_evidence, browse_evidence]
        if atom.startswith("G22"):
            references.append(journey_evidence)
        evidence[atom] = {
            "status": "COMPATIBILITY_VERIFIED",
            "verification_evidence": references,
            "compatibility_or_defer_rationale": meanings[atom],
        }
    return evidence


def validate_browser_diagnostics(report: dict[str, object]) -> None:
    for diagnostics in report["browser_contexts"]:
        for key in ("http_errors", "failed_requests", "page_errors", "console_errors", "off_origin_requests"):
            assert diagnostics[key] == [], {"context": diagnostics["label"], key: diagnostics[key]}


def run_e2e(
    playwright: Playwright,
    base_url: str,
    env: dict[str, str],
    port: int,
    process: subprocess.Popen,
) -> tuple[subprocess.Popen, dict[str, object]]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    report: dict[str, object] = {
        "schema_version": "f10-t02.final-acceptance.v1",
        "status": "RUNNING",
        "started_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "task": "F10-T02",
        "database": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
        "viewports": [list(item) for item in VIEWPORTS],
        "browser_instances": 1,
        "route_results": [],
        "browser_contexts": [],
        "formal_database_before": file_record(FORMAL_DB),
        "external_model_called": False,
    }
    initial_model_calls = database_audit()["model_calls"]
    assert initial_model_calls == 0, {"initial_model_calls": initial_model_calls}
    browser = playwright.chromium.launch(headless=True)
    try:
        process, journey_fixture = run_continuous_journey(browser, base_url, env, port, process, fixture, report)
        fixture["teacher_student_id"] = journey_fixture["owner_public_id"]
        run_all_routes(
            browser,
            base_url,
            fixture,
            journey_fixture["resources"],
            journey_fixture["job_id"],
            journey_fixture["exam_id"],
            report,
        )
        validate_browser_diagnostics(report)
        audit = database_audit()
        assert audit["integrity"] == "ok", audit
        assert audit["foreign_key_violations"] == 0, audit
        browse_model_calls = report["ordinary_browse"]["after"]["model_calls"]["rows"]
        assert audit["model_calls"] == browse_model_calls, {
            "after_browse": browse_model_calls,
            "after_acceptance": audit["model_calls"],
        }
        report["database_audit"] = audit
        report["external_model_evidence"] = {
            "provider": env["EDUMATRIX_LLM_PROVIDER"],
            "endpoint_configured": bool(env["EDUMATRIX_LLM_ENDPOINT"]),
            "model_calls_before_journey": initial_model_calls,
            "model_calls_before_browse": report["ordinary_browse"]["before"]["model_calls"]["rows"],
            "model_calls_after_browse": browse_model_calls,
            "ordinary_browse_model_calls_unchanged": (
                report["ordinary_browse"]["before"]["model_calls"]
                == report["ordinary_browse"]["after"]["model_calls"]
            ),
            "off_origin_requests": sum(
                len(item["off_origin_requests"]) for item in report["browser_contexts"]
            ),
        }
        report["external_model_called"] = False
        report["formal_database_after"] = file_record(FORMAL_DB)
        assert report["formal_database_before"] == report["formal_database_after"]
        report["atomic_evidence"] = build_atomic_evidence(report)
        assert set(report["atomic_evidence"]) == set(RELATED_ATOMS)
        report["status"] = "PASSED"
        return process, report
    except Exception as exc:
        report["status"] = "FAILED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        raise
    finally:
        report["completed_at"] = datetime.now(timezone.utc).astimezone().isoformat()
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        browser.close()


def managed_run(port: int) -> None:
    global _ACTIVE_SERVER_PROCESS
    if port_is_open(port):
        raise RuntimeError(f"port {port} is already in use before managed F10-T02 E2E")
    env = configure_environment(port)
    prepare_fixture(port)
    command = [sys.executable, str(Path(__file__).resolve()), "--serve", "--port", str(port)]
    process: subprocess.Popen | None = None
    report: dict[str, object] | None = None
    try:
        with SERVER_LOG.open("w", encoding="utf-8") as server_log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=server_log,
                stderr=subprocess.STDOUT,
                env=env,
            )
            _ACTIVE_SERVER_PROCESS = process
            wait_for_server(process, port)
            with sync_playwright() as playwright:
                process, report = run_e2e(
                    playwright, f"http://127.0.0.1:{port}", env, port, process,
                )
    finally:
        cleanup_error = ""
        active_process = _ACTIVE_SERVER_PROCESS or process
        try:
            stop_server(active_process, port)
        except Exception as exc:
            cleanup_error = f"{type(exc).__name__}: {exc}"
        _ACTIVE_SERVER_PROCESS = None
        if REPORT_PATH.exists():
            report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
            report["cleanup"] = {
                "server_stopped": active_process is None or active_process.poll() is not None,
                "port_closed": not port_is_open(port),
                "error": cleanup_error,
            }
            if cleanup_error and report.get("status") == "PASSED":
                report["status"] = "FAILED"
                report["error"] = cleanup_error
            REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if cleanup_error:
            raise RuntimeError(cleanup_error)
    print(json.dumps({
        "status": (report or {}).get("status"),
        "routes": len((report or {}).get("route_results") or []),
        "screenshots": len(list(SCREENSHOT_DIR.rglob("*.png"))),
        "database": (report or {}).get("database_audit"),
        "cleanup": (report or {}).get("cleanup"),
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--serve", action="store_true")
    group.add_argument("--managed-run", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    env = configure_environment(args.port)
    configure_reused_harnesses(args.port)
    if args.prepare:
        prepare_fixture(args.port)
    elif args.serve:
        serve(args.port)
    elif args.managed_run:
        managed_run(args.port)


if __name__ == "__main__":
    main()
