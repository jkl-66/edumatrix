"""F5-T03 personalized handout desktop E2E on isolated SQLite."""

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
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f5_t03_handout"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
PORT_START = int(os.getenv("EDUMATRIX_F5_T03_PORT", "8951"))
STRUCTURED_ID = "f5-t03-structured-handout"
LEGACY_ID = "f5-t03-legacy-handout"
INVALID_ID = "f5-t03-invalid-handout"
UNAVAILABLE_ID = "f5-t03-unavailable-handout"
READY_REF_ID = "f5-t03-ready-ref"
UNAVAILABLE_REF_ID = "f5-t03-unavailable-ref"


def handout_content(source_ref_id: str, summary: str) -> dict:
    return {
        "schemaVersion": "f5.handout.v1",
        "title": "梯度下降个性化讲义",
        "summary": summary,
        "learningGoal": "解释负梯度方向、学习率与收敛行为之间的关系。",
        "estimatedMinutes": 24,
        "outline": [
            {"id": "concept", "title": "关键概念"},
            {"id": "formula", "title": "参数更新公式"},
            {"id": "example", "title": "应用示例"},
            {"id": "counter", "title": "边界与反例"},
            {"id": "code", "title": "代码阅读"},
            {"id": "quiz", "title": "学习检查"},
            {"id": "footnote", "title": "来源脚注"},
        ],
        "concepts": [{
            "id": "concept",
            "title": "负梯度方向",
            "explanation": "梯度指向目标函数增长最快的方向，因此参数沿负梯度方向更新，逐步寻找更小的目标函数值。",
            "sourceRefIds": [source_ref_id],
        }],
        "figures": [{
            "id": "formula",
            "title": "参数更新公式",
            "kind": "formula",
            "content": r"\theta_{t+1}=\theta_t-\eta\nabla J(\theta_t)",
            "caption": "学习率 eta 决定每次更新的步长；方向来自当前位置的梯度。",
            "sourceRefIds": [source_ref_id],
        }],
        "examples": [{
            "id": "example",
            "title": "二次函数上的逐步逼近",
            "body": "从任意初始点出发，先计算当前位置斜率，再按负斜率方向移动。合理的学习率会让参数逐步接近极小值。",
            "sourceRefIds": [source_ref_id],
        }],
        "counterExamples": [{
            "id": "counter",
            "title": "学习率过大导致振荡",
            "body": "如果每一步跨越极小值的距离过大，参数会在两侧反复跳动，甚至离最优点越来越远。",
            "sourceRefIds": [source_ref_id],
        }],
        "codeBlocks": [{
            "id": "code",
            "title": "一次参数更新",
            "language": "python",
            "code": "gradient = compute_gradient(theta)\ntheta = theta - learning_rate * gradient\n",
            "explanation": "代码只用于理解结构；真实编辑、运行、报错和绘图在代码沙盒中完成。",
        }],
        "miniQuiz": [{
            "id": "quiz",
            "question": "学习率过大时，训练过程最可能出现什么现象？",
            "options": ["每一步都稳定接近极小值", "发生振荡或发散", "梯度自动变为零", "不再需要计算梯度"],
            "correctIndex": 1,
            "explanation": "过大的更新步长可能反复越过极小值，造成振荡或发散。",
            "required": True,
        }],
        "footnotes": [{
            "id": "footnote",
            "sourceRefId": source_ref_id,
            "label": "[1]",
            "title": "机器学习基础课程讲义",
            "location": "第 2 章 优化算法 / 梯度下降",
        }],
        "profileAdaptation": {
            "summary": "依据当前画像，先用公式和机制图解建立直觉，再通过反例与代码连接工程判断。",
            "difficulty": "基础到应用",
            "scaffolding": [
                "先理解负梯度方向，再观察学习率的影响。",
                "阅读反例时说明方法失效的具体条件。",
                "完成小测后再进入代码沙盒验证。",
            ],
        },
    }


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F5-T03 E2E port")


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
        "EDUMATRIX_AUTH_SECRET_KEY": "f5-t03-isolated-secret",
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
    v1 = repr(json.dumps(handout_content(READY_REF_ID, "第一版：先建立梯度与更新方向的基础认识。"), ensure_ascii=False))
    v2 = repr(json.dumps(handout_content(READY_REF_ID, "当前版：从机制、例子、反例、代码和小测形成完整阅读路径。"), ensure_ascii=False))
    unavailable = repr(json.dumps(handout_content(UNAVAILABLE_REF_ID, "来源已撤回的讲义仍可阅读，但不能作为可发布版本。"), ensure_ascii=False))
    script = f'''
import json
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

    ready_source = DBSourceDocument(
        id="f5-t03-ready-source", course_id=course.id, legacy_document_id="f5-t03-ready",
        title="机器学习基础课程讲义", filename="f5-t03-ready.md", file_format="markdown",
        content_hash="a" * 64, source_sha256="b" * 64, processed_sha256="c" * 64,
        license_text="isolated E2E fixture", processing_status="ready",
    )
    unavailable_source = DBSourceDocument(
        id="f5-t03-unavailable-source", course_id=course.id, legacy_document_id="f5-t03-unavailable",
        title="已撤回课程来源", filename="f5-t03-unavailable.md", file_format="markdown",
        content_hash="d" * 64, source_sha256="e" * 64, processed_sha256="f" * 64,
        license_text="isolated E2E fixture", processing_status="failed",
    )
    db.add_all([ready_source, unavailable_source])
    db.flush()
    ready_ref = DBSourceRef(
        id={READY_REF_ID!r}, source_document_id=ready_source.id, parser_version="f5-t03-ready-parser",
        location_kind="section", location_label="第 2 章 优化算法 / 梯度下降", content_hash="1" * 64,
    )
    unavailable_ref = DBSourceRef(
        id={UNAVAILABLE_REF_ID!r}, source_document_id=unavailable_source.id, parser_version="f5-t03-unavailable-parser",
        location_kind="section", location_label="原第 2 章", content_hash="2" * 64,
    )
    db.add_all([ready_ref, unavailable_ref])
    db.flush()

    def add_artifact(artifact_id, artifact_type, title, content, content_format, source_ref_ids):
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
                "resource_type": "handout", "module": "第二章 优化算法",
                "knowledge_point_title": "梯度下降", "source_ref_ids": source_ref_ids,
                "completion_rule": "阅读关键概念、反例并完成小测",
            }},
        )
        artifact.status = "published"
        return artifact, version

    structured, first = add_artifact(
        {STRUCTURED_ID!r}, "handout", "梯度下降个性化讲义", {v1}, "json", [ready_ref.id],
    )
    add_artifact_version(
        db, artifact=structured, content={v2}, content_format="json",
        created_by_public_id=owner.public_id, metadata=first.metadata_json,
    )
    structured.status = "published"
    add_artifact(
        {LEGACY_ID!r}, "lesson", "旧版梯度下降讲义",
        "# 旧版梯度下降讲义\\n\\n这是一份真实保留的 Markdown 讲义。\\n\\n## 更新规则\\n\\n编辑时按原格式另存新版本，不补造缺失章节。",
        "markdown", [],
    )
    add_artifact(
        {INVALID_ID!r}, "handout", "待修复结构化讲义",
        json.dumps({{"schemaVersion": "f5.handout.v1", "title": "待修复结构化讲义"}}, ensure_ascii=False),
        "json", [ready_ref.id],
    )
    add_artifact(
        {UNAVAILABLE_ID!r}, "handout", "来源已撤回的讲义",
        {unavailable}, "json", [unavailable_ref.id],
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


def login(page: Page, base_url: str) -> dict[str, str]:
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
    return payload


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
        }


def database_audit(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        versions = db.execute(
            "SELECT version_number,content_hash FROM artifact_versions WHERE artifact_id=? ORDER BY version_number",
            (STRUCTURED_ID,),
        ).fetchall()
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "structured_versions": versions,
        }


def page_diagnostics(page: Page, report: dict) -> None:
    page.on("response", lambda response: report["http_errors"].append({
        "status": response.status, "url": response.url,
    }) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url, "failure": request.failure,
    }) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def visible_metrics(page: Page) -> dict:
    return page.evaluate("""() => {
      const root = document.querySelector('[data-testid="handout-workspace"]');
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
      const largeSurfaces = [root, ...elements].filter(Boolean).filter(visible).map((el) => {
        const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
        return { area: Math.round(rect.width * rect.height), background: style.backgroundColor, className: el.className?.toString().slice(0, 80) };
      }).filter((item) => item.area > 50000 && item.background !== 'rgba(0, 0, 0, 0)').slice(0, 20);
      return {
        viewport: [innerWidth, innerHeight],
        documentWidth: document.documentElement.scrollWidth,
        bodyTextLength: (root?.innerText || '').trim().length,
        collisions, clipped, smallText, forbiddenEffects, largeSurfaces,
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


def open_handout(page: Page, base_url: str, resource_id: str) -> None:
    page.goto(
        f"{base_url}/workspace/resources/handouts/{resource_id}?course_id={COURSE_ID}",
        wait_until="networkidle", timeout=60_000,
    )
    page.get_by_test_id("handout-workspace").wait_for(state="visible")


def exercise_structured(page: Page, base_url: str, report: dict) -> None:
    open_handout(page, base_url, STRUCTURED_ID)
    page.get_by_role("heading", name="梯度下降个性化讲义", exact=True).first.wait_for(state="visible")
    assert page.locator(".outline-panel nav button").count() == 7
    assert page.get_by_text("来源完整，可进入发布检查。", exact=True).is_visible()
    capture(page, report, "01-structured-current-1440x900.png")

    page.locator(".outline-panel nav button").filter(has_text="参数更新公式").click()
    page.get_by_text("学习率过大时，训练过程最可能出现什么现象？", exact=True).scroll_into_view_if_needed()
    page.locator(".quiz-option").filter(has_text="发生振荡或发散").click()
    page.get_by_role("button", name="检查答案").click()
    page.get_by_text("回答正确", exact=True).wait_for(state="visible")
    capture(page, report, "02-structured-quiz-1440x900.png")

    with page.expect_download() as download_info:
        page.get_by_role("button", name="导出 HTML").click()
    download = download_info.value
    export_path = OUTPUT_DIR / "exported-handout.html"
    download.save_as(str(export_path))
    exported = export_path.read_text(encoding="utf-8")
    for expected in ("学习目标", "画像适配", "学习检查", "来源脚注", "梯度下降"):
        assert expected in exported
    report["html_export"] = {
        "filename": download.suggested_filename,
        "bytes": export_path.stat().st_size,
        "sha256": hashlib.sha256(export_path.read_bytes()).hexdigest(),
    }

    page.get_by_label("讲义版本").select_option(label="v1 · 历史")
    page.get_by_text("正在只读查看 v1。编辑会另存为新版本，不覆盖历史。", exact=True).wait_for(state="visible")
    page.get_by_role("button", name="与当前版本比较").click()
    page.get_by_text("所选版本与当前版本存在内容差异。", exact=True).wait_for(state="visible")
    capture(page, report, "03-historical-version-1440x900.png")

    page.get_by_role("button", name="从此版本继续编辑").click()
    summary = page.get_by_label("适配摘要")
    summary.fill("从第一版继续修订：先理解更新方向，再用反例检查学习率边界。")
    page.get_by_role("button", name="保存为新版本").click()
    page.get_by_text("新版本已保存，原版本仍可在历史中查看。", exact=True).wait_for(state="visible")
    assert page.get_by_label("讲义版本").input_value()
    capture(page, report, "04-new-version-from-history-1440x900.png")


def exercise_compatibility_states(page: Page, base_url: str, report: dict) -> None:
    open_handout(page, base_url, LEGACY_ID)
    page.get_by_text("这是旧版 Markdown 讲义的兼容视图，系统不会补造缺失章节或来源。", exact=True).wait_for(state="visible")
    page.get_by_role("heading", name="旧版梯度下降讲义", exact=True).last.wait_for(state="visible")
    capture(page, report, "05-legacy-markdown-1440x900.png")

    open_handout(page, base_url, INVALID_ID)
    page.get_by_role("heading", name="讲义结构需要修复", exact=True).wait_for(state="visible")
    page.get_by_role("button", name="修复并另存新版本").wait_for(state="visible")
    capture(page, report, "06-invalid-structured-1440x900.png")

    open_handout(page, base_url, UNAVAILABLE_ID)
    page.get_by_text("来源已失效，请恢复来源后再发布。", exact=True).wait_for(state="visible")
    capture(page, report, "07-source-unavailable-1440x900.png")


def run() -> dict:
    clear_output()
    db_path = OUTPUT_DIR / "f5_t03.sqlite3"
    port = free_port()
    env = runtime_env(db_path, port)
    seed_fixture(env)
    before = learning_state(db_path)
    base_url = f"http://127.0.0.1:{port}"
    report = {
        "schema_version": "f5-t03.handout-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "port": port,
        "screenshots": [], "checks": {}, "html_export": {},
        "database_audit": {}, "learning_state_before": before, "learning_state_after": {},
        "http_errors": [], "failed_requests": [], "console_errors": [], "page_errors": [],
        "process_cleanup": {}, "result": "failed",
    }
    process: subprocess.Popen | None = None
    try:
        process = start_service(env, port, OUTPUT_DIR / "backend.log")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900}, locale="zh-CN", accept_downloads=True,
                )
                page = context.new_page()
                page.set_default_timeout(30_000)
                page_diagnostics(page, report)
                login(page, base_url)
                exercise_structured(page, base_url, report)
                exercise_compatibility_states(page, base_url, report)
                context.close()

                context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
                page = context.new_page()
                page.set_default_timeout(30_000)
                page_diagnostics(page, report)
                login(page, base_url)
                open_handout(page, base_url, STRUCTURED_ID)
                capture(page, report, "08-structured-current-1366x768.png")
                context.close()
            finally:
                browser.close()

        after = learning_state(db_path)
        report["learning_state_after"] = after
        assert after == before, {"before": before, "after": after}
        report["database_audit"] = database_audit(db_path)
        assert report["database_audit"]["integrity"] == "ok"
        assert report["database_audit"]["foreign_key_violations"] == 0
        assert len(report["database_audit"]["structured_versions"]) == 3
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["console_errors"], report["console_errors"]
        assert not report["page_errors"], report["page_errors"]
        report["result"] = "passed"
        return report
    finally:
        try:
            stop_service(process, port)
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
            "learning_state_unchanged": result["learning_state_before"] == result["learning_state_after"],
            "database_audit": result["database_audit"],
            "process_cleanup": result["process_cleanup"],
        }, ensure_ascii=False, indent=2))
    except Exception:
        traceback.print_exc()
        raise
