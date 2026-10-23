"""F5-T04 mind-map desktop E2E on isolated SQLite."""

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
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f5_t04_mindmap"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
PORT_START = int(os.getenv("EDUMATRIX_F5_T04_PORT", "8961"))
STRUCTURED_ID = "f5-t04-structured-mindmap"
LEGACY_ID = "f5-t04-legacy-mindmap"
INVALID_ID = "f5-t04-invalid-mindmap"
HANDOUT_ID = "f5-t04-linked-handout"
SOURCE_ID = "f5-t04-source"
SOURCE_REF_ID = "f5-t04-source-ref"


def mindmap_content(*, summary: str) -> dict:
    return {
        "schemaVersion": "f5.mindmap.v1",
        "title": "梯度下降思维导图",
        "summary": summary,
        "learningGoal": "解释梯度方向、学习率和收敛检查之间的关系。",
        "rootNodeId": "root",
        "nodes": [
            {
                "nodeId": "root", "parentNodeId": None, "label": "梯度下降",
                "summary": "沿负梯度方向迭代更新参数。", "relation": "主题", "depth": 0,
                "sourceRefs": [SOURCE_REF_ID], "masteryBand": "developing",
                "linkedResourceIds": [HANDOUT_ID],
            },
            {
                "nodeId": "gradient", "parentNodeId": "root", "label": "负梯度方向",
                "summary": "梯度给出局部上升最快方向，更新时取相反方向。", "relation": "组成", "depth": 1,
                "sourceRefs": [SOURCE_REF_ID], "masteryBand": "secure",
                "linkedResourceIds": [HANDOUT_ID],
            },
            {
                "nodeId": "rate", "parentNodeId": "root", "label": "学习率",
                "summary": "学习率控制单次参数更新步长。", "relation": "组成", "depth": 1,
                "sourceRefs": [SOURCE_REF_ID], "masteryBand": "needs_work",
                "linkedResourceIds": [],
            },
            {
                "nodeId": "check", "parentNodeId": "rate", "label": "收敛检查",
                "summary": "观察损失变化并识别振荡或发散。", "relation": "验证", "depth": 2,
                "sourceRefs": [SOURCE_REF_ID], "masteryBand": "unknown",
                "linkedResourceIds": [],
            },
            {
                "nodeId": "application", "parentNodeId": "gradient", "label": "工程应用",
                "summary": "把更新机制用于模型训练与参数优化。", "relation": "应用", "depth": 2,
                "sourceRefs": [SOURCE_REF_ID], "masteryBand": "developing",
                "linkedResourceIds": [],
            },
        ],
    }


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F5-T04 E2E port")


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
        "EDUMATRIX_AUTH_SECRET_KEY": "f5-t04-isolated-secret",
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
    source_path = OUTPUT_DIR / "course-source.md"
    source_text = (
        "# 机器学习基础课程讲义\n\n"
        "## 梯度下降\n\n"
        "梯度表示目标函数局部上升最快方向，参数沿负梯度方向更新。\n\n"
        "学习率控制更新步长；过大可能振荡或发散，过小会降低收敛速度。\n"
    )
    source_path.write_text(source_text, encoding="utf-8")
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    first = repr(json.dumps(mindmap_content(summary="第一版：先认识梯度方向与学习率。"), ensure_ascii=False))
    current = repr(json.dumps(mindmap_content(summary="当前版：从机制、参数、检查和应用形成可导航知识结构。"), ensure_ascii=False))
    script = f'''
from app.competition_demo_seed import seed_competition_demo
from app.database import DBArtifact, DBCourse, DBSourceDocument, DBSourceRef, DBUser, SessionLocal, init_db
from app.m1_repository import add_artifact_version

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    owner = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    course = db.get(DBCourse, {COURSE_ID!r})
    if course is None:
        raise RuntimeError("demo course is missing")

    source = DBSourceDocument(
        id={SOURCE_ID!r}, course_id=course.id, legacy_document_id="f5-t04-course-source",
        title="机器学习基础课程讲义", filename="course-source.md", file_format="markdown",
        file_size={len(source_path.read_bytes())}, source_path={str(source_path.relative_to(ROOT))!r},
        content_hash={source_hash!r}, source_sha256={source_hash!r}, processed_sha256={source_hash!r},
        parser_version="f5-t04-e2e-parser", parser_metadata={{"paragraph_count": 4}},
        license_text="isolated E2E fixture", processing_status="ready",
    )
    db.add(source)
    db.flush()
    source_ref = DBSourceRef(
        id={SOURCE_REF_ID!r}, source_document_id=source.id, parser_version="f5-t04-e2e-parser",
        location_kind="section", location_index=1, location_label="梯度下降",
        char_start=12, char_end=94, quote="梯度表示目标函数局部上升最快方向",
        content_hash={source_hash!r},
    )
    db.add(source_ref)
    db.flush()

    def add_resource(artifact_id, artifact_type, title, content, content_format, resource_type):
        artifact = DBArtifact(
            id=artifact_id, owner_public_id=owner.public_id, course_id=course.id,
            artifact_type=artifact_type, title=title, status="published",
        )
        db.add(artifact)
        db.flush()
        version = add_artifact_version(
            db, artifact=artifact, content=content, content_format=content_format,
            created_by_public_id=owner.public_id,
            metadata={{
                "resource_type": resource_type, "module": "第二章 优化算法",
                "knowledge_point_title": "梯度下降", "source_ref_ids": [source_ref.id],
                "completion_rule": "按今日任务要求提交可验证学习证据",
            }},
        )
        artifact.status = "published"
        return artifact, version

    add_resource(
        {HANDOUT_ID!r}, "handout", "梯度下降个性化讲义",
        "# 梯度下降个性化讲义\\n\\n## 关键概念\\n\\n沿负梯度方向更新参数。\\n\\n## 反例\\n\\n学习率过大可能振荡或发散。",
        "markdown", "handout",
    )
    structured, v1 = add_resource(
        {STRUCTURED_ID!r}, "mind_map", "梯度下降思维导图", {first}, "json", "mind_map",
    )
    add_artifact_version(
        db, artifact=structured, content={current}, content_format="json",
        created_by_public_id=owner.public_id, metadata=v1.metadata_json,
    )
    structured.status = "published"
    add_resource(
        {LEGACY_ID!r}, "mindmap", "旧版优化算法导图",
        "# 旧版优化算法导图\\n- 梯度下降\\n  - 负梯度方向\\n  - 学习率",
        "markdown", "mind_map",
    )
    add_resource(
        {INVALID_ID!r}, "mind_map", "待修复优化算法导图",
        '{{"schemaVersion":"f5.mindmap.v1","title":"待修复优化算法导图"}}',
        "json", "mind_map",
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


def start_service(env: dict[str, str], port: int, log_path: Path) -> subprocess.Popen:
    log = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "run.py"], cwd=ROOT, env=env,
        stdout=log, stderr=subprocess.STDOUT,
    )
    process._edumatrix_log = log  # type: ignore[attr-defined]
    wait_port(port, True)
    return process


def stop_service(process: subprocess.Popen | None, port: int) -> None:
    if process is None:
        return
    if process.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, timeout=20,
        )
        process.wait(timeout=10)
    log = getattr(process, "_edumatrix_log", None)
    if log is not None:
        log.close()
    wait_port(port, False, timeout=20)


def login(page: Page, base_url: str) -> None:
    response = page.request.post(
        f"{base_url}/api/auth/login",
        form={"username": USERNAME, "password": PASSWORD},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    payload = response.json()
    state = json.dumps(payload, ensure_ascii=False)
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
    """)


def table_digest(db: sqlite3.Connection, sql: str, params: tuple = ()) -> dict[str, object]:
    rows = db.execute(sql, params).fetchall()
    serialized = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return {"count": len(rows), "sha256": hashlib.sha256(serialized.encode()).hexdigest()}


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
            "resources": table_digest(
                db, "SELECT id,status,current_version_id,lock_version FROM artifacts "
                "WHERE owner_public_id=? ORDER BY id", (owner,),
            ),
            "resource_versions": table_digest(
                db, "SELECT v.id,v.artifact_id,v.version_number,v.content_hash FROM artifact_versions v "
                "JOIN artifacts a ON a.id=v.artifact_id WHERE a.owner_public_id=? ORDER BY v.id", (owner,),
            ),
        }


def database_audit(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "mindmap_versions": db.execute(
                "SELECT version_number,content_hash FROM artifact_versions WHERE artifact_id=? ORDER BY version_number",
                (STRUCTURED_ID,),
            ).fetchall(),
        }


def page_diagnostics(page: Page, report: dict) -> None:
    page.on("response", lambda response: report["http_errors"].append({
        "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url, "failure": request.failure,
    }) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    def record_write_request(request) -> None:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        item = {"method": request.method, "url": request.url}
        report["write_requests"].append(item)
        if "/api/v1/m5/context/resolve" not in request.url:
            report["unexpected_write_requests"].append(item)

    page.on("request", record_write_request)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def visible_metrics(page: Page) -> dict:
    return page.evaluate("""() => {
      const root = document.querySelector('[data-testid="mindmap-workspace"]');
      const visible = (el) => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1;
      };
      const elements = root ? [...root.querySelectorAll('*')] : [];
      const controls = elements.filter((el) => el.matches('button,a[href],input,select,textarea') && visible(el));
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
      const clipped = elements.filter(visible).filter((el) => {
        if (el.closest('.mindmap-svg')) return false;
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false;
        return rect.right > innerWidth + 1 || rect.left < -1 ||
          (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap' && style.overflowX !== 'auto');
      }).map((el) => (el.innerText || '').trim().slice(0, 80)).filter(Boolean).slice(0, 20);
      const smallText = elements.filter((el) => {
        const text = (el.innerText || '').replaceAll('\u200b', '').trim();
        return visible(el) && el.children.length === 0 && text &&
          Number.parseFloat(getComputedStyle(el).fontSize) < 13.5;
      }).map((el) => ({ text: el.innerText.replaceAll('\u200b', '').trim().slice(0, 40), size: getComputedStyle(el).fontSize })).slice(0, 20);
      const forbiddenEffects = elements.filter(visible).filter((el) => {
        const style = getComputedStyle(el);
        return (style.backgroundImage || '').includes('gradient') ||
          !['none', ''].includes(style.backdropFilter || 'none');
      }).map((el) => el.className?.toString().slice(0, 80)).slice(0, 20);
      return {
        viewport: [innerWidth, innerHeight],
        documentWidth: document.documentElement.scrollWidth,
        bodyTextLength: (root?.innerText || '').trim().length,
        collisions, clipped, smallText, forbiddenEffects,
      };
    }""")


def capture(page: Page, report: dict, name: str) -> None:
    page.wait_for_timeout(350)
    metrics = visible_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] > 180, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["forbiddenEffects"], metrics


def open_mindmap(page: Page, base_url: str, resource_id: str) -> None:
    page.goto(
        f"{base_url}/workspace/resources/mindmaps/{resource_id}?course_id={COURSE_ID}",
        wait_until="networkidle", timeout=60_000,
    )
    page.get_by_test_id("mindmap-workspace").wait_for(state="visible")


def exercise_structured(page: Page, base_url: str, report: dict) -> None:
    open_mindmap(page, base_url, STRUCTURED_ID)
    page.get_by_role("heading", name="梯度下降思维导图", exact=True).wait_for(state="visible")
    page.get_by_text("当前版：从机制、参数、检查和应用形成可导航知识结构。", exact=True).wait_for(state="visible")
    assert page.locator(".mindmap-node").count() == 5
    capture(page, report, "01-structured-current-1440x900.png")

    search = page.get_by_label("搜索思维导图节点")
    search.fill("学习率")
    page.locator(".search-results button").filter(has_text="学习率").click()
    page.locator(".node-panel h2").filter(has_text="学习率").wait_for(state="visible")
    page.get_by_role("button", name="折叠全部分支").click()
    page.get_by_role("button", name="放大导图").click()
    capture(page, report, "02-search-fold-1440x900.png")

    page.reload(wait_until="networkidle")
    page.get_by_test_id("mindmap-workspace").wait_for(state="visible")
    page.locator(".node-panel h2").filter(has_text="学习率").wait_for(state="visible")
    report["view_restoration"]["current_version_node"] = True

    search = page.get_by_label("搜索思维导图节点")
    search.fill("梯度下降")
    page.locator(".search-results button").filter(has_text="梯度下降").click()
    page.get_by_role("button", name="机器学习基础课程讲义").click()
    page.wait_for_url(lambda url: "/knowledge/documents/" in url, timeout=30_000)
    assert "canonical_source_id=f5-t04-source" in page.url
    assert "focus_source_ref_id=f5-t04-source-ref" in page.url
    page.get_by_text("机器学习基础课程讲义", exact=True).last.wait_for(state="visible")
    page.get_by_text("梯度表示目标函数局部上升最快方向", exact=False).wait_for(state="visible")
    assert not page.get_by_text("引用链接不完整", exact=False).count()
    report["source_deep_link"] = page.url
    page.goto(
        f"{base_url}/workspace/resources/mindmaps/{STRUCTURED_ID}?course_id={COURSE_ID}",
        wait_until="networkidle", timeout=60_000,
    )
    page.get_by_test_id("mindmap-workspace").wait_for(state="visible")

    page.get_by_role("button", name="梯度下降个性化讲义").click()
    page.wait_for_url(lambda url: f"/handouts/{HANDOUT_ID}" in url, timeout=30_000)
    page.get_by_test_id("handout-workspace").wait_for(state="visible")
    page.get_by_role("heading", name="梯度下降个性化讲义", exact=True).last.wait_for(state="visible")
    report["linked_handout_url"] = page.url
    page.go_back(wait_until="networkidle")
    page.get_by_test_id("mindmap-workspace").wait_for(state="visible")

    page.get_by_label("选择思维导图版本").select_option(label="v1")
    page.get_by_text("第一版：先认识梯度方向与学习率。", exact=True).wait_for(state="visible")
    search = page.get_by_label("搜索思维导图节点")
    search.fill("负梯度方向")
    page.locator(".search-results button").filter(has_text="负梯度方向").click()
    page.get_by_role("button", name="折叠全部分支").click()
    page.reload(wait_until="networkidle")
    page.get_by_text("第一版：先认识梯度方向与学习率。", exact=True).wait_for(state="visible")
    page.locator(".node-panel h2").filter(has_text="负梯度方向").wait_for(state="visible")
    report["view_restoration"]["historical_version_node"] = True
    capture(page, report, "03-historical-restored-1440x900.png")


def exercise_fallbacks(page: Page, base_url: str, report: dict) -> None:
    open_mindmap(page, base_url, LEGACY_ID)
    page.get_by_test_id("mindmap-hierarchy-fallback").wait_for(state="visible")
    page.get_by_text("这是旧版 Markdown 导图的兼容视图", exact=False).wait_for(state="visible")
    capture(page, report, "04-legacy-hierarchy-1440x900.png")

    open_mindmap(page, base_url, INVALID_ID)
    page.get_by_test_id("mindmap-hierarchy-fallback").wait_for(state="visible")
    page.get_by_text("当前思维导图的节点层级或关系不完整", exact=False).wait_for(state="visible")
    capture(page, report, "05-invalid-hierarchy-1440x900.png")


def run() -> dict:
    clear_output()
    db_path = OUTPUT_DIR / "f5_t04.sqlite3"
    port = free_port()
    env = runtime_env(db_path, port)
    seed_fixture(env)
    before = learning_state(db_path)
    base_url = f"http://127.0.0.1:{port}"
    report = {
        "schema_version": "f5-t04.mindmap-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "port": port,
        "screenshots": [], "checks": {}, "view_restoration": {},
        "source_deep_link": "", "linked_handout_url": "",
        "database_audit": {}, "learning_state_before": before, "learning_state_after": {},
        "http_errors": [], "failed_requests": [], "write_requests": [], "unexpected_write_requests": [],
        "console_errors": [], "page_errors": [], "process_cleanup": {}, "result": "failed",
    }
    process: subprocess.Popen | None = None
    try:
        process = start_service(env, port, OUTPUT_DIR / "backend.log")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
                page = context.new_page()
                page.set_default_timeout(30_000)
                login(page, base_url)
                page_diagnostics(page, report)
                exercise_structured(page, base_url, report)
                exercise_fallbacks(page, base_url, report)
                context.close()

                context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
                page = context.new_page()
                page.set_default_timeout(30_000)
                login(page, base_url)
                page_diagnostics(page, report)
                open_mindmap(page, base_url, STRUCTURED_ID)
                page.get_by_text("当前版：从机制、参数、检查和应用形成可导航知识结构。", exact=True).wait_for(state="visible")
                capture(page, report, "06-structured-current-1366x768.png")

                node_panel = page.get_by_label("节点详情")
                primary_action = node_panel.get_by_role("button", name="打开关联资源", exact=True)
                node_panel.evaluate("element => { element.scrollTop = element.scrollHeight }")
                primary_action.scroll_into_view_if_needed()
                primary_action.wait_for(state="visible")
                panel_box = node_panel.bounding_box()
                action_box = primary_action.bounding_box()
                assert panel_box and action_box
                assert action_box["y"] >= panel_box["y"]
                assert action_box["y"] + action_box["height"] <= panel_box["y"] + panel_box["height"]
                primary_action.focus()
                assert primary_action.evaluate("element => document.activeElement === element")
                report["right_panel_primary_action"] = {
                    "viewport": [1366, 768],
                    "visible_after_scroll": True,
                    "keyboard_focusable": True,
                }
                capture(page, report, "07-detail-primary-action-1366x768.png")
                primary_action.click()
                page.wait_for_url(lambda url: f"/handouts/{HANDOUT_ID}" in url, timeout=30_000)
                page.get_by_test_id("handout-workspace").wait_for(state="visible")
                report["right_panel_primary_action"]["navigated_to_linked_resource"] = True
                page.go_back(wait_until="networkidle")
                page.get_by_test_id("mindmap-workspace").wait_for(state="visible")
                context.close()
            finally:
                browser.close()

        after = learning_state(db_path)
        report["learning_state_after"] = after
        assert after == before, {"before": before, "after": after}
        report["database_audit"] = database_audit(db_path)
        assert report["database_audit"]["integrity"] == "ok"
        assert report["database_audit"]["foreign_key_violations"] == 0
        assert len(report["database_audit"]["mindmap_versions"]) == 2
        assert report["view_restoration"] == {
            "current_version_node": True,
            "historical_version_node": True,
        }
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["unexpected_write_requests"], report["unexpected_write_requests"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["page_errors"], report["page_errors"]
        report["result"] = "passed"
        return report
    finally:
        try:
            stop_service(process, port)
            report["process_cleanup"] = {"backend_stopped": True, "port_closed": True}
        except Exception as exc:
            report["process_cleanup"] = {
                "backend_stopped": False, "port_closed": False, "error": str(exc),
            }
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
            "learning_state_unchanged": result["learning_state_before"] == result["learning_state_after"],
            "view_restoration": result["view_restoration"],
            "database_audit": result["database_audit"],
            "process_cleanup": result["process_cleanup"],
        }, ensure_ascii=False, indent=2))
    except Exception:
        traceback.print_exc()
        raise
