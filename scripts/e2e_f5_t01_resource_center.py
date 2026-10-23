"""F5-T01 resource-center desktop E2E with isolated SQLite evidence."""

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
import traceback
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f5_t01_resource_center"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
PORT_START = int(os.getenv("EDUMATRIX_F5_T01_PORT", "8911"))
VIEWPORTS = ((1440, 900), (1366, 768))
RESOURCE_TYPES = (
    "handout", "mind_map", "quiz", "training_task", "code_sandbox",
    "video", "deck", "interactive_model", "feynman",
)
RESOURCE_IDS = {kind: f"a-f5-t01-{index:02d}-{kind}" for index, kind in enumerate(RESOURCE_TYPES, 1)}
DEEP_LINK_ID = "z-f5-t01-deep-handout"


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F5-T01 E2E port")


def wait_port(port: int, expected: bool, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(port) is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {port} did not reach expected state: {expected}")


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def runtime_env(db_path: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(db_path),
        "EDUMATRIX_AUTH_SECRET_KEY": "f5-t01-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(port),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def seed_fixture(env: dict[str, str]) -> None:
    script = f'''from hashlib import sha256
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBArtifact, DBArtifactVersion, DBChapter, DBKnowledgePoint,
    DBSourceDocument, DBSourceRef, DBUser, SessionLocal, init_db,
)

COURSE_ID = {COURSE_ID!r}
RESOURCE_TYPES = {RESOURCE_TYPES!r}
RESOURCE_IDS = {RESOURCE_IDS!r}
DEEP_LINK_ID = {DEEP_LINK_ID!r}

def add_resource(db, *, resource_id, owner_id, kind, title, content, metadata):
    artifact = DBArtifact(
        id=resource_id, owner_public_id=owner_id, course_id=COURSE_ID,
        artifact_type=kind, title=title, status="approved",
    )
    db.add(artifact)
    db.flush()
    version = DBArtifactVersion(
        id=f"{{resource_id}}-v1", artifact_id=artifact.id, version_number=1,
        content=content, content_format="markdown",
        content_hash=sha256(content.encode("utf-8")).hexdigest(),
        metadata_json=metadata, created_by_public_id=owner_id,
    )
    db.add(version)
    db.flush()
    artifact.current_version_id = version.id

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    owner = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    point = db.query(DBKnowledgePoint).filter_by(domain_pack="rag").first()
    if point is None:
        point = db.query(DBKnowledgePoint).first()
    ready_ref = (
        db.query(DBSourceRef)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .filter(DBSourceDocument.course_id == COURSE_ID, DBSourceDocument.processing_status == "ready")
        .first()
    )
    failed_source = DBSourceDocument(
        id="f5-t01-failed-source", course_id=COURSE_ID, title="失效来源示例",
        filename="failed-source.md", file_format="md", content_hash="d" * 64,
        processing_status="failed",
    )
    db.add(failed_source)
    db.flush()
    failed_chapter = DBChapter(
        id="f5-t01-failed-chapter", course_id=COURSE_ID,
        source_document_id=failed_source.id, stable_key="f5-t01-failed",
        title="失效来源章节", position=99,
    )
    db.add(failed_chapter)
    db.flush()
    failed_ref = DBSourceRef(
        id="f5-t01-failed-ref", source_document_id=failed_source.id,
        chapter_id=failed_chapter.id, parser_version="f5-t01-parser-v1",
        location_kind="section", location_label="失效来源章节",
        content_hash="e" * 64, quote="该来源用于验证诚实失效状态。",
    )
    db.add(failed_ref)
    db.flush()

    labels = {{
        "handout": "梯度下降个性化讲义", "mind_map": "优化算法思维导图",
        "quiz": "梯度下降测验题", "training_task": "优化器实训任务书",
        "code_sandbox": "梯度下降代码沙盒", "video": "优化算法视频推荐",
        "deck": "梯度下降网页课件", "interactive_model": "学习率可交互模型",
        "feynman": "梯度下降费曼复述",
    }}
    source_modes = {{
        "handout": [ready_ref.id], "mind_map": [failed_ref.id], "quiz": [],
        "training_task": [ready_ref.id], "code_sandbox": [], "video": [ready_ref.id],
        "deck": [failed_ref.id], "interactive_model": [ready_ref.id], "feynman": [],
    }}
    for kind in RESOURCE_TYPES:
        add_resource(
            db, resource_id=RESOURCE_IDS[kind], owner_id=owner.public_id,
            kind=kind, title=labels[kind],
            content=f"# {{labels[kind]}}\\n\\n本资源围绕梯度下降、学习率与优化器展开。",
            metadata={{
                "resource_type": kind, "module": "第二章 优化算法",
                "tags": ["学习率", "优化器", kind],
                "knowledge_point_id": point.id if point else None,
                "knowledge_point_title": point.title if point else "梯度下降",
                "source_ref_ids": source_modes[kind],
                "completion_rule": f"完成 {{labels[kind]}} 的规定学习动作",
            }},
        )

    for index in range(100):
        add_resource(
            db, resource_id=f"m-f5-t01-filler-{{index:03d}}", owner_id=owner.public_id,
            kind="handout", title=f"目录容量样本 {{index + 1:03d}}",
            content=f"# 目录容量样本 {{index + 1:03d}}",
            metadata={{"resource_type": "handout", "module": "容量验证"}},
        )
    add_resource(
        db, resource_id=DEEP_LINK_ID, owner_id=owner.public_id,
        kind="handout", title="目录窗口外的深链讲义",
        content="# 目录窗口外的深链讲义\\n\\n刷新专用 URL 后仍应恢复此资源。",
        metadata={{
            "resource_type": "handout", "module": "深链恢复",
            "tags": ["深链", "刷新恢复"],
            "knowledge_point_id": point.id if point else None,
            "source_ref_ids": [ready_ref.id],
        }},
    )
    db.commit()
finally:
    db.close()
'''
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode:
        raise RuntimeError(f"fixture seed failed:\n{result.stdout}\n{result.stderr}")


def login(page: Page, base_url: str) -> dict[str, str]:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": USERNAME, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    payload = response.json()
    state = json.dumps(payload, ensure_ascii=False)
    context = json.dumps({
        "userId": payload.get("public_id") or payload.get("user_id"),
        "courseId": COURSE_ID,
        "chapterId": None, "knowledgePointId": None, "taskId": None,
        "resourceId": None, "sourceRefId": None, "attemptId": None, "version": None,
    }, ensure_ascii=False)
    page.add_init_script(f"""
      const session = {state};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_display_name', session.display_name || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_role', session.role || 'student');
      localStorage.setItem('edumatrix_student_id', session.student_id || session.username || '{USERNAME}');
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', '{COURSE_ID}');
      localStorage.setItem('edumatrix_course_title', '人工智能与机器学习工程');
      localStorage.setItem('edumatrix_context_ref', JSON.stringify({context}));
    """)
    return payload


def table_digest(db: sqlite3.Connection, sql: str, params: tuple = ()) -> dict[str, object]:
    rows = db.execute(sql, params).fetchall()
    serialized = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return {"count": len(rows), "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest()}


def learning_state(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        owner = db.execute("SELECT public_id FROM users WHERE username=?", (USERNAME,)).fetchone()[0]
        return {
            "learning_events": table_digest(
                db, "SELECT id,event_type,evidence_status,evidence_strength,mastery_eligible,completion_effect,payload "
                "FROM learning_events WHERE owner_public_id=? ORDER BY id", (owner,),
            ),
            "profile_snapshots": table_digest(
                db, "SELECT id,profile_version,snapshot,content_hash FROM profile_snapshots "
                "WHERE owner_public_id=? ORDER BY id", (owner,),
            ),
            "path_nodes": table_digest(
                db, "SELECT n.id,n.status,n.actual_minutes FROM path_nodes n "
                "JOIN learning_paths p ON p.id=n.learning_path_id WHERE p.owner_public_id=? ORDER BY n.id", (owner,),
            ),
            "exam_gate_events": table_digest(
                db, "SELECT e.id,e.event_type,e.payload FROM task_events e JOIN generation_tasks t ON t.id=e.task_id "
                "WHERE t.owner_public_id=? AND e.payload LIKE '%exam_gate%' ORDER BY e.id", (owner,),
            ),
        }


def database_audit(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def page_diagnostics(page: Page, report: dict, expected_failure: dict[str, bool]) -> None:
    def response_handler(response) -> None:
        if response.status < 400:
            return
        entry = {"status": response.status, "url": response.url}
        target = report["expected_preview_failure_url"]
        if expected_failure["active"] and target in response.url:
            report["expected_http_errors"].append(entry)
        else:
            report["http_errors"].append(entry)

    page.on("response", response_handler)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url, "failure": request.failure,
    }) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: (
        report["expected_console_errors"] if expected_failure["active"] else report["console_errors"]
    ).append(message.text) if message.type == "error" else None)


def visible_metrics(page: Page) -> dict:
    return page.evaluate("""() => {
      const visible = (el) => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1;
      };
      const controls = [...document.querySelectorAll('button,a[href],input,select,textarea')].filter(visible);
      const collisions = [];
      for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
        const a = controls[i], b = controls[j];
        if (a.contains(b) || b.contains(a)) continue;
        const x = a.getBoundingClientRect(), y = b.getBoundingClientRect();
        const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left);
        const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top);
        if (overlapW > 3 && overlapH > 3) collisions.push([
          (a.innerText || a.getAttribute('aria-label') || a.title || '').trim().slice(0, 48),
          (b.innerText || b.getAttribute('aria-label') || b.title || '').trim().slice(0, 48),
        ]);
      }
      const clipped = [...document.querySelectorAll('button,a[href],h1,h2,h3,strong,p,span,label,dd,dt')]
        .filter(visible).filter((el) => {
          const style = getComputedStyle(el), rect = el.getBoundingClientRect();
          if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false;
          return rect.right > innerWidth + 1 || rect.left < -1 ||
            (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap');
        }).map((el) => (el.innerText || '').trim().slice(0, 80)).filter(Boolean).slice(0, 20);
      const smallText = [...document.querySelectorAll('body *')].filter((el) => {
        return visible(el) && el.children.length === 0 && (el.innerText || '').trim() &&
          Number.parseFloat(getComputedStyle(el).fontSize) < 13.5;
      }).map((el) => ({ text: el.innerText.trim().slice(0, 40), size: getComputedStyle(el).fontSize })).slice(0, 20);
      const forbiddenEffects = [...document.querySelectorAll('[data-testid="resource-center"] *')]
        .filter(visible).filter((el) => {
          const style = getComputedStyle(el);
          return (style.backgroundImage || '').includes('gradient') ||
            !['none', ''].includes(style.backdropFilter || 'none');
        }).map((el) => el.className || el.tagName).slice(0, 20);
      return {
        viewport: [innerWidth, innerHeight],
        documentWidth: document.documentElement.scrollWidth,
        bodyTextLength: (document.body.innerText || '').trim().length,
        collisions, clipped, smallText, forbiddenEffects,
      };
    }""")


def capture(page: Page, report: dict, name: str) -> None:
    page.wait_for_timeout(450)
    metrics = visible_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] > 200, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["forbiddenEffects"], metrics


def wait_catalog(page: Page) -> None:
    root = page.get_by_test_id("resource-center")
    root.wait_for(state="visible", timeout=30_000)
    root.locator(".resource-item").first.wait_for(state="visible", timeout=30_000)
    page.get_by_test_id("resource-preview").wait_for(state="visible")


def set_search(page: Page, text: str) -> None:
    field = page.get_by_placeholder("搜索标题、模块、标签或知识点")
    field.fill(text)
    page.wait_for_timeout(500)


def exercise_catalog(page: Page, base_url: str, report: dict, expected_failure: dict[str, bool]) -> None:
    page.goto(f"{base_url}/workspace/resources?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
    wait_catalog(page)
    root = page.get_by_test_id("resource-center")
    type_buttons = root.locator(".type-option[data-resource-type]:not([data-resource-type='all'])")
    assert type_buttons.count() == 9
    counts = {}
    for index in range(type_buttons.count()):
        button = type_buttons.nth(index)
        kind = button.get_attribute("data-resource-type")
        counts[kind] = int(button.locator("strong").inner_text())
    assert set(counts) == set(RESOURCE_TYPES) and all(value >= 1 for value in counts.values()), counts
    report["category_counts"] = counts
    capture(page, report, "01-resource-grid-1440x900.png")

    for query in ("梯度下降个性化讲义", "第二章 优化算法", "学习率"):
        set_search(page, query)
        root.locator(f"[data-resource-id='{RESOURCE_IDS['handout']}']").wait_for(state="visible")
    set_search(page, "")

    page.get_by_title("列表视图").click()
    root.locator(".resource-results.mode-list").wait_for(state="visible")
    assert "view=list" in page.url
    page.reload(wait_until="networkidle")
    root.locator(".resource-results.mode-list").wait_for(state="visible")
    capture(page, report, "02-resource-list-1440x900.png")

    source_select = page.get_by_label("来源状态")
    source_select.select_option("available")
    root.locator(f"[data-resource-id='{RESOURCE_IDS['handout']}']").wait_for(state="visible")
    source_select.select_option("unavailable")
    root.locator(f"[data-resource-id='{RESOURCE_IDS['mind_map']}']").wait_for(state="visible")
    source_select.select_option("not_recorded")
    root.locator(f"[data-resource-id='{RESOURCE_IDS['quiz']}']").wait_for(state="visible")
    source_select.select_option("")

    failure_id = RESOURCE_IDS["mind_map"]
    failure_url = f"/api/v1/m5/resources/{failure_id}"
    report["expected_preview_failure_url"] = failure_url
    page.route(f"**{failure_url}", lambda route: route.fulfill(
        status=503, content_type="application/json",
        body=json.dumps({"detail": {"message": "专项验收注入的预览失败"}}, ensure_ascii=False),
    ))
    expected_failure["active"] = True
    root.locator(f"[data-resource-id='{failure_id}']").click()
    page.get_by_text("预览暂时不可用", exact=True).wait_for(state="visible")
    capture(page, report, "03-preview-failure-1440x900.png")
    page.unroute(f"**{failure_url}")
    page.get_by_role("button", name="重新加载").click()
    page.get_by_test_id("resource-preview").get_by_role(
        "heading", name="优化算法思维导图", exact=True,
    ).wait_for(state="visible")
    page.get_by_text("预览暂时不可用", exact=True).wait_for(state="hidden")
    expected_failure["active"] = False

    root.locator(f"[data-resource-id='{RESOURCE_IDS['handout']}']").click()
    page.get_by_test_id("resource-preview").get_by_role(
        "heading", name="梯度下降个性化讲义", exact=True,
    ).wait_for(state="visible")
    with page.expect_download() as download_info:
        page.get_by_title("下载当前版本").click()
    download = download_info.value
    assert download.suggested_filename.endswith(".json")
    report["download"] = {"filename": download.suggested_filename, "failure": download.failure()}

    set_search(page, "绝不存在的资源标题")
    page.get_by_text("没有符合条件的资源", exact=True).wait_for(state="visible")
    capture(page, report, "04-empty-state-1440x900.png")
    page.get_by_role("button", name="清除筛选").click()
    wait_catalog(page)

    page.goto(
        f"{base_url}/workspace/resources/handouts/{DEEP_LINK_ID}?course_id={COURSE_ID}",
        wait_until="networkidle", timeout=60_000,
    )
    page.get_by_text("目录窗口外的深链讲义", exact=True).wait_for(state="visible")
    page.reload(wait_until="networkidle")
    page.get_by_text("目录窗口外的深链讲义", exact=True).wait_for(state="visible")
    report["deep_link"] = {"resource_id": DEEP_LINK_ID, "restored_after_reload": True}


def run() -> dict:
    clear_output()
    db_path = OUTPUT_DIR / "f5_t01.sqlite3"
    port = free_port()
    env = runtime_env(db_path, port)
    seed_fixture(env)
    before = learning_state(db_path)
    base_url = f"http://127.0.0.1:{port}"
    report = {
        "schema_version": "f5-t01.resource-center-desktop.v1",
        "viewports": [list(item) for item in VIEWPORTS],
        "port": port,
        "screenshots": [], "checks": {}, "category_counts": {},
        "download": {}, "deep_link": {}, "database_audit": {},
        "learning_state_before": before, "learning_state_after": {},
        "expected_preview_failure_url": "",
        "expected_http_errors": [], "expected_console_errors": [],
        "http_errors": [], "failed_requests": [], "console_errors": [], "page_errors": [],
        "process_cleanup": {}, "result": "failed",
    }
    process = None
    try:
        with (OUTPUT_DIR / "backend.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            wait_port(port, True)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                try:
                    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN", accept_downloads=True)
                    page = context.new_page()
                    page.set_default_timeout(30_000)
                    expected_failure = {"active": False}
                    page_diagnostics(page, report, expected_failure)
                    login(page, base_url)
                    exercise_catalog(page, base_url, report, expected_failure)
                    context.close()

                    context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
                    page = context.new_page()
                    page.set_default_timeout(30_000)
                    expected_failure = {"active": False}
                    page_diagnostics(page, report, expected_failure)
                    login(page, base_url)
                    page.goto(f"{base_url}/workspace/resources?course_id={COURSE_ID}", wait_until="networkidle", timeout=60_000)
                    wait_catalog(page)
                    capture(page, report, "05-resource-grid-1366x768.png")
                    page.get_by_title("列表视图").click()
                    capture(page, report, "06-resource-list-1366x768.png")
                    context.close()
                finally:
                    browser.close()

        after = learning_state(db_path)
        report["learning_state_after"] = after
        assert after == before, {"before": before, "after": after}
        report["database_audit"] = database_audit(db_path)
        assert report["database_audit"] == {"integrity": "ok", "foreign_key_violations": 0}
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["page_errors"], report["page_errors"]
        assert report["expected_http_errors"], "preview failure branch was not exercised"
        report["result"] = "passed"
        return report
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, timeout=20,
            )
        try:
            wait_port(port, False, timeout=20)
            report["process_cleanup"] = {"backend_stopped": True, "port_closed": True}
        except Exception as exc:
            report["process_cleanup"] = {"backend_stopped": False, "port_closed": False, "error": str(exc)}
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    try:
        result = run()
        print(json.dumps({
            "result": result["result"],
            "screenshots": len(result["screenshots"]),
            "category_counts": result["category_counts"],
            "learning_state_unchanged": result["learning_state_before"] == result["learning_state_after"],
            "database_audit": result["database_audit"],
            "process_cleanup": result["process_cleanup"],
        }, ensure_ascii=False, indent=2))
    except Exception:
        traceback.print_exc()
        raise
