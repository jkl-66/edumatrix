"""F5-T05 training-task desktop E2E on isolated SQLite."""

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
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f5_t05_training_task"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
PORT_START = int(os.getenv("EDUMATRIX_F5_T05_PORT", "8971"))
STRUCTURED_ID = "f5-t05-structured-training-task"
LEGACY_ID = "f5-t05-legacy-training-task"
INVALID_ID = "f5-t05-invalid-training-task"
SANDBOX_ID = "f5-t05-linked-sandbox"
MODEL_ID = "f5-t05-linked-model"
MISSING_MODEL_ID = "f5-t05-missing-model"
SOURCE_ID = "f5-t05-source"
SOURCE_REF_ID = "f5-t05-source-ref"


def training_task_content(*, version: str, linked_model_id: str) -> dict:
    historical = version == "v1"
    return {
        "schemaVersion": "f5.training-task.v1",
        "title": "梯度下降实训任务书",
        "objective": (
            "第一版：完成数据检查与基线训练。"
            if historical
            else "当前版：从数据处理、模型选择、训练评估到错误诊断完成一次可复现实训。"
        ),
        "difficulty": "入门到应用",
        "estimatedMinutes": 70,
        "prerequisites": ["理解梯度、学习率和训练集/验证集的区别", "能够阅读基础 Python 代码"],
        "environment": ["Python 3.11", "EduMatrix 代码沙盒", "本地确定性训练数据"],
        "data": ["预置二分类样本", "标签列 target", "固定随机种子 42"],
        "steps": [
            {
                "id": "step-data",
                "title": "检查数据与任务边界",
                "instruction": "核对字段、缺失值、标签分布和训练/验证划分，记录不能直接用于训练的异常。",
                "expectedResult": "形成字段、样本数、缺失值和划分比例检查清单。",
                "errorGuidance": "若标签缺失或划分泄漏，停止训练并先修正输入。",
                "sourceRefIds": [SOURCE_REF_ID],
            },
            {
                "id": "step-model",
                "title": "选择模型与评价指标",
                "instruction": "选择逻辑回归基线，说明准确率与 F1 的使用条件，并冻结随机种子。",
                "expectedResult": "记录模型、关键参数、指标和选择理由。",
                "errorGuidance": "若类别不平衡，不能只用准确率解释模型质量。",
                "sourceRefIds": [SOURCE_REF_ID],
            },
            {
                "id": "step-run",
                "title": "训练并保存真实结果",
                "instruction": "在关联代码沙盒中运行训练，保存代码、输入摘要、标准输出和指标。",
                "expectedResult": "得到可重复的训练输出或可定位的真实错误。",
                "errorGuidance": "出现形状、类型或收敛错误时，保留错误信息并从数据形状和学习率开始排查。",
                "sourceRefIds": [],
            },
            {
                "id": "step-debug",
                "title": "评估、诊断与改进",
                "instruction": "比较训练与验证结果，识别欠拟合、过拟合或数据问题，修改一项设置后重跑。",
                "expectedResult": "提交前后结果、错误原因或改进依据。",
                "errorGuidance": "改动后结果变差时恢复上一次可重现配置，并说明判断依据。",
                "sourceRefIds": [SOURCE_REF_ID],
            },
        ],
        "checkpoints": [
            {
                "id": "check-data",
                "afterStepId": "step-data",
                "title": "数据可进入训练",
                "verification": "逐项核对字段、标签、缺失值与数据划分。",
                "passCondition": "不存在未解释字段、标签缺失或数据泄漏。",
            },
            {
                "id": "check-run",
                "afterStepId": "step-run",
                "title": "运行结果可重现",
                "verification": "使用相同输入与随机种子再次运行。",
                "passCondition": "关键指标一致，或相同错误能够稳定复现。",
            },
            {
                "id": "check-analysis",
                "afterStepId": "step-debug",
                "title": "改进结论有证据",
                "verification": "对照修改前后输出和评价指标。",
                "passCondition": "每条结论都能回指真实运行结果。",
            },
        ],
        "deliverables": [
            {"id": "deliverable-code", "title": "可运行代码", "description": "包含数据检查、训练、评估和固定随机种子。", "format": "Python"},
            {"id": "deliverable-output", "title": "运行记录", "description": "保留标准输出、指标或完整错误。", "format": "沙盒运行记录"},
            {"id": "deliverable-report", "title": "实训报告", "description": "说明模型选择、结果解释、排错过程和改进。", "format": "Markdown"},
        ],
        "rubric": [
            {"id": "rubric-data", "criterion": "数据处理", "evidence": "字段、标签、缺失值和划分检查清单。", "points": 25},
            {"id": "rubric-model", "criterion": "模型与指标选择", "evidence": "模型、参数、指标和选择理由。", "points": 20},
            {"id": "rubric-run", "criterion": "真实训练与评估", "evidence": "代码、输入摘要、输出及可重复结果。", "points": 35},
            {"id": "rubric-debug", "criterion": "错误诊断与改进", "evidence": "错误、修改、重跑和结论的证据链。", "points": 20},
        ],
        "sourceRefs": [SOURCE_REF_ID],
        "linkedSandboxId": SANDBOX_ID,
        "linkedModelId": linked_model_id,
    }


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F5-T05 E2E port")


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
        "EDUMATRIX_AUTH_SECRET_KEY": "f5-t05-isolated-secret",
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
        "# 机器学习工程课程讲义\n\n"
        "## 梯度下降实训\n\n"
        "工程训练应先检查数据和划分，再选择模型与评价指标。\n\n"
        "训练结果必须可复现；出现错误时应保留真实输出并按数据、参数和收敛过程定位。\n"
    )
    source_path.write_text(source_text, encoding="utf-8")
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    historical = repr(json.dumps(training_task_content(version="v1", linked_model_id=MISSING_MODEL_ID), ensure_ascii=False))
    current = repr(json.dumps(training_task_content(version="v2", linked_model_id=MODEL_ID), ensure_ascii=False))
    legacy = repr(json.dumps({
        "artifact_type": "lab_guide",
        "schema_version": "m2.lab_guide.v1",
        "title": "旧版梯度下降实验说明",
        "objective": "运行逻辑回归基线并观察指标。",
        "environment": ["Python 3.11"],
        "safety_boundary": "只使用预置课程数据，不连接外部服务。",
        "steps": [{
            "step_number": 1,
            "title": "运行基线",
            "instruction": "执行训练脚本并记录输出。",
            "command_or_action": "python train.py",
            "expected_result": "输出训练指标。",
            "rollback": "恢复固定输入与随机种子。",
            "risk_level": "low",
            "source_ref_ids": [SOURCE_REF_ID],
        }],
        "acceptance_criteria": ["相同输入下结果可重现"],
        "failure_branches": [{"symptom": "无输出", "likely_cause": "输入缺失", "recovery_steps": ["检查输入"]}],
    }, ensure_ascii=False))
    invalid = repr(json.dumps({"schemaVersion": "f5.training-task.v1", "title": "损坏任务书"}, ensure_ascii=False))
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
        id={SOURCE_ID!r}, course_id=course.id, legacy_document_id="f5-t05-course-source",
        title="机器学习工程课程讲义", filename="course-source.md", file_format="markdown",
        file_size={len(source_path.read_bytes())}, source_path={str(source_path.relative_to(ROOT))!r},
        content_hash={source_hash!r}, source_sha256={source_hash!r}, processed_sha256={source_hash!r},
        parser_version="f5-t05-e2e-parser", parser_metadata={{"paragraph_count": 4}},
        license_text="isolated E2E fixture", processing_status="ready",
    )
    db.add(source)
    db.flush()
    source_ref = DBSourceRef(
        id={SOURCE_REF_ID!r}, source_document_id=source.id, parser_version="f5-t05-e2e-parser",
        location_kind="section", location_index=1, location_label="梯度下降实训",
        char_start=16, char_end=118, quote="工程训练应先检查数据和划分",
        content_hash={source_hash!r},
    )
    db.add(source_ref)
    db.flush()

    def add_resource(artifact_id, artifact_type, title, content, content_format, resource_type, metadata=None):
        artifact = DBArtifact(
            id=artifact_id, owner_public_id=owner.public_id, course_id=course.id,
            artifact_type=artifact_type, title=title, status="published",
        )
        db.add(artifact)
        db.flush()
        values = {{
            "resource_type": resource_type, "module": "第二章 优化算法",
            "knowledge_point_title": "梯度下降", "source_ref_ids": [source_ref.id],
            "completion_rule": "提交真实运行、检查点和规定提交物后完成",
        }}
        values.update(metadata or {{}})
        version = add_artifact_version(
            db, artifact=artifact, content=content, content_format=content_format,
            created_by_public_id=owner.public_id, metadata=values,
        )
        artifact.status = "published"
        return artifact, version

    add_resource(
        {SANDBOX_ID!r}, "code_sandbox", "梯度下降代码沙盒",
        "# 在 F6 中承载真实编辑、运行与调试。", "markdown", "code_sandbox",
    )
    add_resource(
        {MODEL_ID!r}, "interactive_model", "学习率可交互模型",
        "# 在 F6 中承载参数调节、图表与观察提交。", "markdown", "interactive_model",
    )
    structured, first = add_resource(
        {STRUCTURED_ID!r}, "training_task", "梯度下降实训任务书",
        {historical}, "json", "training_task",
        {{"completion_status": "partial", "completion_progress": 0.5}},
    )
    add_artifact_version(
        db, artifact=structured, content={current}, content_format="json",
        created_by_public_id=owner.public_id, metadata=first.metadata_json,
    )
    structured.status = "published"
    add_resource(
        {LEGACY_ID!r}, "lab_guide", "旧版梯度下降实验说明",
        {legacy}, "json", "lab_guide",
    )
    add_resource(
        {INVALID_ID!r}, "training_task", "损坏实训任务书",
        {invalid}, "json", "training_task",
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
            "training_task_versions": db.execute(
                "SELECT version_number,content_hash FROM artifact_versions WHERE artifact_id=? ORDER BY version_number",
                (STRUCTURED_ID,),
            ).fetchall(),
        }


def page_diagnostics(page: Page, report: dict) -> None:
    def record_response(response) -> None:
        if response.status < 400:
            return
        item = {"status": response.status, "url": response.url}
        if (
            response.status == 503
            and f"/api/v1/m5/resources/{STRUCTURED_ID}" in response.url
        ):
            report["expected_http_errors"].append(item)
        else:
            report["http_errors"].append(item)

    page.on("response", record_response)
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
    def record_console(message) -> None:
        if message.type != "error":
            return
        if "Failed to load resource" in message.text:
            report["expected_console_errors"].append(message.text)
        else:
            report["console_errors"].append(message.text)

    page.on("console", record_console)


def visible_metrics(page: Page) -> dict:
    return page.evaluate("""() => {
      const root = document.querySelector('[data-testid="training-task-workspace"]');
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
      return {
        viewport: [innerWidth, innerHeight],
        documentWidth: document.documentElement.scrollWidth,
        bodyTextLength: (root?.innerText || '').trim().length,
        collisions, clipped, smallText, forbiddenEffects,
      };
    }""")


def capture(page: Page, report: dict, name: str, minimum_text: int = 180) -> None:
    page.wait_for_timeout(350)
    metrics = visible_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] > minimum_text, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["forbiddenEffects"], metrics


def open_training_task(page: Page, base_url: str, resource_id: str) -> None:
    page.goto(
        f"{base_url}/workspace/resources/training-tasks/{resource_id}?course_id={COURSE_ID}",
        wait_until="networkidle", timeout=60_000,
    )
    page.get_by_test_id("training-task-workspace").wait_for(state="visible")


def exercise_structured(page: Page, base_url: str, report: dict) -> None:
    open_training_task(page, base_url, STRUCTURED_ID)
    page.get_by_role("heading", name="梯度下降实训任务书", exact=True).wait_for(state="visible")
    page.get_by_role(
        "heading",
        name="当前版：从数据处理、模型选择、训练评估到错误诊断完成一次可复现实训。",
        exact=True,
    ).wait_for(state="visible")
    page.get_by_text("步骤进行中", exact=True).wait_for(state="visible")
    assert page.locator(".step-list > li").count() == 4
    assert page.locator(".checkpoint-list > section").count() == 3
    assert page.locator(".deliverable-list > section").count() == 3
    assert page.locator(".rubric-row").count() == 4
    assert page.locator(".rubric-row b").all_inner_texts() == ["25", "20", "35", "20"]
    capture(page, report, "01-structured-current-1440x900.png")

    page.get_by_role("button", name="评分", exact=True).click()
    page.get_by_role("table", name="实训评分标准").wait_for(state="visible")
    capture(page, report, "02-rubric-1440x900.png")

    source_button = page.get_by_role("button", name="机器学习工程课程讲义", exact=False)
    source_button.click()
    page.wait_for_url(lambda url: "/knowledge/documents/" in url, timeout=30_000)
    assert f"canonical_source_id={SOURCE_ID}" in page.url
    assert f"focus_source_ref_id={SOURCE_REF_ID}" in page.url
    page.get_by_text("机器学习工程课程讲义", exact=True).last.wait_for(state="visible")
    report["source_deep_link"] = page.url
    page.go_back(wait_until="networkidle")
    page.get_by_test_id("training-task-workspace").wait_for(state="visible")

    sandbox_button = page.get_by_role("button", name="进入代码沙盒", exact=False)
    model_button = page.get_by_role("button", name="打开可交互模型", exact=False)
    styles = page.evaluate("""() => {
      const buttons = [...document.querySelectorAll('.tool-entry')];
      return buttons.map((button) => ({
        text: button.innerText.trim(),
        background: getComputedStyle(button).backgroundColor,
        color: getComputedStyle(button).color,
        disabled: button.disabled,
      }));
    }""")
    assert len(styles) == 2 and styles[0]["background"] != styles[1]["background"], styles
    report["linked_resource_visual_distinction"] = styles

    sandbox_button.click()
    page.wait_for_url(lambda url: f"/workspace/code/{SANDBOX_ID}" in url, timeout=30_000)
    page.locator("textarea[placeholder*='输入学习问题']").wait_for(state="visible")
    report["sandbox_link"] = page.url
    page.go_back(wait_until="networkidle")
    page.get_by_test_id("training-task-workspace").wait_for(state="visible")

    model_button = page.get_by_role("button", name="打开可交互模型", exact=False)
    model_button.click()
    page.wait_for_url(lambda url: f"/workspace/resources/models/{MODEL_ID}" in url, timeout=30_000)
    page.get_by_test_id("interactive-lab-workspace").wait_for(state="visible")
    report["model_link"] = page.url
    page.go_back(wait_until="networkidle")
    page.get_by_test_id("training-task-workspace").wait_for(state="visible")

    page.get_by_label("选择实训任务书版本").select_option(label="v1")
    page.get_by_role("heading", name="第一版：完成数据检查与基线训练。", exact=True).wait_for(state="visible")
    page.get_by_text("当前查看历史版本 v1", exact=False).wait_for(state="visible")
    historical_model = page.get_by_role("button", name="打开可交互模型", exact=False)
    assert historical_model.is_disabled()
    report["unavailable_link"] = {"version": "v1", "model_disabled": True}
    capture(page, report, "03-historical-unavailable-model-1440x900.png")


def exercise_fallbacks(page: Page, base_url: str, report: dict) -> None:
    open_training_task(page, base_url, LEGACY_ID)
    page.get_by_text("当前展示的是旧版实验说明", exact=False).wait_for(state="visible")
    page.get_by_role("heading", name="原有步骤", exact=True).wait_for(state="visible")
    page.get_by_text("相同输入下结果可重现", exact=True).wait_for(state="visible")
    capture(page, report, "04-legacy-lab-guide-1440x900.png")

    open_training_task(page, base_url, INVALID_ID)
    invalid_state = page.locator(".invalid-state")
    invalid_state.get_by_role("heading", name="任务书结构不完整", exact=True).wait_for(state="visible")
    invalid_state.get_by_text("当前实训任务书缺少环境、检查点、提交物或评分标准。", exact=True).wait_for(state="visible")
    capture(page, report, "05-invalid-structured-1440x900.png", minimum_text=100)

    failure_count = {"value": 0}

    def fail_once(route) -> None:
        if failure_count["value"] == 0:
            failure_count["value"] += 1
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": {"message": "隔离故障注入：任务书详情暂时不可用"}}, ensure_ascii=False),
            )
            return
        route.continue_()

    page.route(f"**/api/v1/m5/resources/{STRUCTURED_ID}", fail_once)
    open_training_task(page, base_url, STRUCTURED_ID)
    page.locator(".page-state--error strong").filter(has_text="实训任务书暂时无法打开").wait_for(state="visible")
    capture(page, report, "06-retryable-error-1440x900.png", minimum_text=30)
    page.get_by_role("button", name="重新加载", exact=True).click()
    page.get_by_role("heading", name="梯度下降实训任务书", exact=True).wait_for(state="visible")
    page.unroute(f"**/api/v1/m5/resources/{STRUCTURED_ID}", fail_once)
    report["retry_recovery"] = {"injected_failures": failure_count["value"], "recovered": True}
    capture(page, report, "07-recovered-current-1440x900.png")


def run() -> dict:
    clear_output()
    db_path = OUTPUT_DIR / "f5_t05.sqlite3"
    port = free_port()
    env = runtime_env(db_path, port)
    seed_fixture(env)
    before = learning_state(db_path)
    base_url = f"http://127.0.0.1:{port}"
    report = {
        "schema_version": "f5-t05.training-task-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "port": port,
        "screenshots": [], "checks": {},
        "source_deep_link": "", "sandbox_link": "", "model_link": "",
        "linked_resource_visual_distinction": [], "unavailable_link": {}, "retry_recovery": {},
        "right_panel_primary_action": {}, "database_audit": {},
        "learning_state_before": before, "learning_state_after": {},
        "http_errors": [], "expected_http_errors": [], "failed_requests": [],
        "write_requests": [], "unexpected_write_requests": [],
        "console_errors": [], "expected_console_errors": [], "page_errors": [], "process_cleanup": {}, "result": "failed",
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
                open_training_task(page, base_url, STRUCTURED_ID)
                page.get_by_role(
                    "heading",
                    name="当前版：从数据处理、模型选择、训练评估到错误诊断完成一次可复现实训。",
                    exact=True,
                ).wait_for(state="visible")
                capture(page, report, "08-structured-current-1366x768.png")

                primary_action = page.get_by_role("button", name="进入代码沙盒", exact=False)
                primary_action.scroll_into_view_if_needed()
                primary_action.wait_for(state="visible")
                action_box = primary_action.bounding_box()
                assert action_box
                assert action_box["y"] >= 0
                assert action_box["y"] + action_box["height"] <= 768
                primary_action.focus()
                assert primary_action.evaluate("element => document.activeElement === element")
                report["right_panel_primary_action"] = {
                    "viewport": [1366, 768], "visible_after_scroll": True, "keyboard_focusable": True,
                }
                capture(page, report, "09-primary-action-1366x768.png")
                primary_action.click()
                page.wait_for_url(lambda url: f"/workspace/code/{SANDBOX_ID}" in url, timeout=30_000)
                report["right_panel_primary_action"]["navigated_to_sandbox"] = True
                context.close()
            finally:
                browser.close()

        after = learning_state(db_path)
        report["learning_state_after"] = after
        assert after == before, {"before": before, "after": after}
        report["database_audit"] = database_audit(db_path)
        assert report["database_audit"]["integrity"] == "ok"
        assert report["database_audit"]["foreign_key_violations"] == 0
        assert len(report["database_audit"]["training_task_versions"]) == 2
        assert report["source_deep_link"]
        assert report["sandbox_link"] and report["model_link"]
        assert report["unavailable_link"] == {"version": "v1", "model_disabled": True}
        assert report["retry_recovery"] == {"injected_failures": 1, "recovered": True}
        assert len(report["expected_http_errors"]) == 1
        assert report["expected_console_errors"]
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
            "source_deep_link": bool(result["source_deep_link"]),
            "linked_resources": {"sandbox": bool(result["sandbox_link"]), "model": bool(result["model_link"])},
            "unavailable_link": result["unavailable_link"],
            "database_audit": result["database_audit"],
            "process_cleanup": result["process_cleanup"],
        }, ensure_ascii=False, indent=2))
    except Exception:
        traceback.print_exc()
        raise
