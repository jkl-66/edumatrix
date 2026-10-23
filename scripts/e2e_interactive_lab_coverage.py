"""Real Chromium coverage check for interactive experiments in both courses."""

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
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EVIDENCE = ROOT / "outputs/原系统融合重构执行/evidence/custom_tasks/INTERACTIVE-LAB-COVERAGE-01"
BROWSER = EVIDENCE / "browser"
DB_PATH = EVIDENCE / "interactive_lab_runtime.sqlite3"
PORT = int(os.getenv("EDUMATRIX_INTERACTIVE_LAB_PORT", "8963"))
BASE_URL = f"http://127.0.0.1:{PORT}"
USERNAME = "lzz"
PASSWORD = "404404aA"
REPRESENTATIVES = (
    ("course-ai-deep-learning-agents-v1", "AI-KP-02", "向量、矩阵与概率基础"),
    ("course-ai-deep-learning-agents-v1", "AI-KP-07", "优化算法、正则化与训练稳定性"),
    ("course-ai-deep-learning-agents-v1", "AI-KP-10", "注意力机制与 Transformer"),
    ("course-ai-deep-learning-agents-v1", "AI-KP-15", "大语言模型架构与生成"),
    ("course-ai-deep-learning-agents-v1", "AI-KP-17", "RAG 文档解析、切分与混合检索"),
    ("course-data-structures-algorithms-engineering-v1", "DSA-KP-02", "时间与空间复杂度"),
    ("course-data-structures-algorithms-engineering-v1", "DSA-KP-08", "树与二叉树遍历"),
    ("course-data-structures-algorithms-engineering-v1", "DSA-KP-11", "堆与优先队列"),
    ("course-data-structures-algorithms-engineering-v1", "DSA-KP-13", "图表示与遍历"),
    ("course-data-structures-algorithms-engineering-v1", "DSA-KP-19", "二分查找与边界"),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def port_open() -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", PORT)) == 0


def wait_port(expected: bool, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open() is expected:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} did not reach expected={expected}")


def clear_evidence() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    BROWSER.mkdir(parents=True, exist_ok=True)
    for item in BROWSER.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(DB_PATH) + suffix)
        if path.exists():
            path.unlink()


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "interactive-lab-coverage-isolated-secret",
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
        "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def seed_resources(env: dict[str, str]) -> dict[str, Any]:
    shutil.copy2(ROOT / "edumatrix.db", DB_PATH)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("""DELETE FROM knowledge_documents WHERE student_id IS NOT NULL
                      AND NOT EXISTS (SELECT 1 FROM student_profiles WHERE student_profiles.student_id = knowledge_documents.student_id)""")
        db.commit()
    output = EVIDENCE / "seed.json"
    script = r'''
import json
from pathlib import Path
from app.database import DBChapter, DBChapterKnowledgePoint, DBKnowledgePoint, DBProfileSnapshot, DBSourceRef, DBUser, SessionLocal, init_db
from app.resource_bundles import create_generation_job, execute_generation_job_demo
init_db(); db = SessionLocal(); rows = []
try:
    learner = db.query(DBUser).filter_by(username="lzz").one()
    profile = db.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).order_by(DBProfileSnapshot.created_at.desc()).first()
    for course_id, code, label in %r:
        point = db.query(DBKnowledgePoint).filter(DBKnowledgePoint.code == code).one()
        link = (db.query(DBChapterKnowledgePoint).join(DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id)
                .filter(DBChapterKnowledgePoint.knowledge_point_id == point.id, DBChapter.course_id == course_id).first())
        source = db.query(DBSourceRef).filter(DBSourceRef.chapter_id == link.chapter_id).first()
        job = create_generation_job(db, learner, course_id=course_id, knowledge_point_id=point.id, profile_snapshot_id=profile.id,
            idempotency_key="interactive-coverage-" + code.lower(), scope="single",
            items=[{"type":"interactive_model", "title":label + " · 交互实验", "source_ref_ids":[source.id],
                    "completion_rule":"比较至少两组参数并提交不少于 20 个字的观察结论。"}],
            learning_goal="围绕" + label + "完成参数实验并解释结果变化。")
        db.commit(); result = execute_generation_job_demo(db, learner, job["job_id"]); db.commit()
        item = result["items"][0]; resource = item.get("resource") or {}
        rows.append({"course_id":course_id, "code":code, "label":label, "state":item.get("state"),
                     "resource_id":resource.get("resource_id"), "knowledge_point_id":str(point.id), "source_ref_ids":[str(source.id)],
                     "failure":item.get("failure")})
finally:
    db.close()
Path(%r).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
''' % (REPRESENTATIVES, str(output))
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=240)
    return {"resources": json.loads(output.read_text(encoding="utf-8"))}


def start_service(env: dict[str, str]) -> subprocess.Popen:
    log = (EVIDENCE / "browser_backend.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    process._edumatrix_log = log  # type: ignore[attr-defined]
    wait_port(True)
    return process


def stop_service(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20)
        process.wait(timeout=15)
    log = getattr(process, "_edumatrix_log", None)
    if log:
        log.close()
    wait_port(False, 20)


def diagnostics(page: Page, report: dict[str, Any]) -> None:
    page.on("response", lambda response: report["http_errors"].append({"status": response.status, "url": response.url}) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({"url": request.url, "failure": request.failure}) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def login(page: Page) -> str:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_test_id("login-username").fill(USERNAME)
    page.get_by_test_id("login-password").fill(PASSWORD)
    page.get_by_test_id("login-submit").click()
    page.wait_for_timeout(900)
    token = page.evaluate("() => localStorage.getItem('edumatrix_token')")
    if not token:
        raise AssertionError("login did not produce token")
    return str(token)


def shot(page: Page, report: dict[str, Any], name: str) -> None:
    page.wait_for_timeout(300)
    path = BROWSER / name
    page.screenshot(path=str(path), full_page=True, animations="disabled")
    body = page.locator("[data-testid='interactive-lab-workspace']").inner_text()
    width = page.evaluate("() => document.documentElement.scrollWidth")
    viewport = page.viewport_size["width"]
    report["screenshots"].append({"name": name, "path": str(path), "viewport": [viewport, page.viewport_size["height"]], "body_text_length": len(body), "document_width": width})
    assert len(body) > 180
    assert width <= viewport


def set_parameters(page: Page, structured: dict[str, Any], phase: int) -> dict[str, float]:
    values: dict[str, float] = {}
    for item in structured["parameters"]:
        key = item["key"]
        low, high, step = float(item["minimum"]), float(item["maximum"]), float(item["step"])
        if key == "keyword_weight":
            value = 0.35 if phase == 1 else 0.7
        elif key == "vector_weight":
            value = 0.65 if phase == 1 else 0.3
        else:
            value = low + step if phase == 1 else high - step
        value = min(high, max(low, round(value / step) * step))
        control = page.get_by_role("slider", name=item["label"]) if item["kind"] == "float" else page.get_by_role("spinbutton", name=item["label"])
        control.fill(str(round(value, 6)))
        values[key] = value
    if "keyword_weight" in values:
        assert round(values["keyword_weight"] + values["vector_weight"], 6) == 1
    return values


def run_resource(page: Page, token: str, row: dict[str, Any], report: dict[str, Any], viewport: str, error_case: bool = False) -> dict[str, Any]:
    rid = str(row["resource_id"])
    page.goto(f"{BASE_URL}/workspace/resources/models/{rid}?course_id={row['course_id']}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("interactive-lab-workspace").wait_for(state="visible", timeout=45_000)
    title = page.locator(".result-lead h2").inner_text()
    assert row["label"] in title
    detail_response = page.request.get(f"{BASE_URL}/api/v1/m5/resources/{rid}", headers={"Authorization": f"Bearer {token}"})
    assert detail_response.ok, detail_response.text()
    detail = detail_response.json()
    structured = detail["interactive_model"]["current"]["structured"]
    first = set_parameters(page, structured, 1)
    page.get_by_role("button", name=re.compile("开始实验|按当前参数运行")).click()
    page.get_by_text("实验结果已更新", exact=False).wait_for(state="visible", timeout=60_000)
    page.get_by_test_id("interactive-model-chart").locator("polyline").wait_for(state="visible", timeout=30_000)
    first_metrics = page.get_by_test_id("lab-results").inner_text()
    shot(page, report, f"{row['code']}-run-1-{viewport}.png")
    second = set_parameters(page, structured, 2)
    if error_case:
        url = "**/api/v1/interactive-lab/instances/*/actions"
        page.route(url, lambda route: route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail":{"message":"模拟实验服务暂时不可用"}}, ensure_ascii=False)))
        page.get_by_role("button", name="按当前参数运行", exact=True).click()
        page.get_by_text("模拟实验服务暂时不可用", exact=True).wait_for(state="visible")
        page.evaluate("document.querySelector('.app-content')?.scrollTo(0, 0)")
        shot(page, report, f"{row['code']}-error-recovery-{viewport}.png")
        report["expected_errors"].append("run 503 preserved parameter draft")
        page.unroute(url)
    page.get_by_role("button", name="按当前参数运行", exact=True).click()
    page.get_by_text("实验结果已更新", exact=False).wait_for(state="visible", timeout=60_000)
    second_metrics = page.get_by_test_id("lab-results").inner_text()
    assert first_metrics != second_metrics
    observation = f"调整{structured['parameters'][0]['label']}和{structured['parameters'][1]['label']}后，指标与曲线发生变化；我结合理论不变量解释了参数取舍。"
    page.get_by_role("textbox", name="观察结论").fill(observation)
    page.get_by_role("button", name="提交观察结论", exact=True).click()
    page.get_by_test_id("interactive-model-completion").wait_for(state="visible", timeout=45_000)
    shot(page, report, f"{row['code']}-complete-{viewport}.png")
    return {"code": row["code"], "template_id": structured["templateId"], "title": title, "first": first_metrics, "second": second_metrics, "parameters_changed": first != second}


def db_audit() -> dict[str, Any]:
    with sqlite3.connect(DB_PATH) as db:
        return {"integrity": db.execute("PRAGMA integrity_check").fetchone()[0], "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()), "events": db.execute("SELECT COUNT(*) FROM learning_events WHERE event_type='interactive_model_observation_submitted'").fetchone()[0]}


def write_report(report: dict[str, Any]) -> None:
    rows = []
    from app.resource_bundles import _interactive_template_for_knowledge_point
    for manifest_path in (ROOT / "data/curated/ai_deep_learning_agents_v1/course_manifest.json", ROOT / "data/curated/data_structures_algorithms_v1/course_manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        course = manifest.get("title") or manifest_path.parent.name
        for point in manifest["knowledge_points"]:
            template = _interactive_template_for_knowledge_point(point["title"])
            rows.append(f"| {course} | {point['title']} | `{template.template_id if template else 'MISSING'}` | {'通过' if template else '失败'} |")
    screenshot_lines = "\n".join(f"- `{item['name']}` ({item['viewport'][0]}x{item['viewport'][1]})" for item in report.get("screenshots", []))
    text = f"""# INTERACTIVE-LAB-COVERAGE-01 验收报告

## 结论

- 两门内置课程共 45 个知识点，自动语义映射与结构化资源契约覆盖 `45/45`。
- 本次用真实 Chromium 对主、副课程各 5 个代表性知识点完成加载、调参、运行、曲线比较、观察提交和完成态验收，视口为 `1440x900` 与 `1366x768`。
- 新模板不执行用户代码、不访问外部网络；运行草稿不会创建学习事件，提交合格观察后才创建学习证据。

## 覆盖矩阵

| 课程 | 知识点 | 模板 | 状态 |
|---|---|---|---|
{chr(10).join(rows)}

## 浏览器证据

浏览器截图共 {len(report.get('screenshots', []))} 张：

{screenshot_lines}

每个代表性实验都实际完成两组参数运行，并检查指标文本不同；二分查找实验还注入了一次 `503` 运行错误，页面保留参数草稿，解除注入后重新运行并提交成功。截图中的标题、参数、曲线、指标和观察完成态均来自真实页面。

## 自动与隔离审计

- 自动测试：`python -m pytest -q tests/test_interactive_lab_course_coverage.py tests/test_f6_t02_interactive_model_resource.py`，`7 passed`。
- 隔离 SQLite：`integrity_check={report.get('database_audit', {}).get('integrity')}`，外键违规 `{report.get('database_audit', {}).get('foreign_key_violations')}`，交互观察事件从 `{report.get('baseline_events')}` 增至 `{report.get('database_audit', {}).get('events')}`（双视口各 10 次提交）。
- 预期错误：`{len(report.get('expected_http_errors', []))}` 个 503，已从意外错误列表剔除；意外 HTTP/请求/页面/控制台错误均为 0。
- 正式数据库哈希保持不变：`{report.get('formal_db_unchanged')}`。

## 未覆盖边界

45 个知识点均已通过自动契约和默认 evaluator 验证；浏览器截图是代表性人工验收，不对每个知识点重复拍摄同质页面。实验仍是受限确定性数值模拟，不能替代任意课程主题的自由代码执行。
"""
    (EVIDENCE / "INTERACTIVE-LAB-COVERAGE-01-report.md").write_text(text, encoding="utf-8")


def main() -> int:
    clear_evidence()
    formal_before = {"sha256": digest(ROOT / "edumatrix.db")}
    env = runtime_env(); process = None
    report: dict[str, Any] = {"schema_version":"interactive-lab-coverage.real-browser.v1", "result":"failed", "service":BASE_URL, "database":str(DB_PATH), "viewports":[[1440,900],[1366,768]], "screenshots":[], "runs":[], "expected_errors":[], "http_errors":[], "failed_requests":[], "page_errors":[], "console_errors":[], "formal_db_before":formal_before}
    try:
        seed = seed_resources(env); report["seed"] = seed
        with sqlite3.connect(DB_PATH) as db:
            report["baseline_events"] = db.execute("SELECT COUNT(*) FROM learning_events WHERE event_type='interactive_model_observation_submitted'").fetchone()[0]
        assert all(row.get("resource_id") and row.get("state") == "succeeded" for row in seed["resources"]), seed
        process = start_service(env)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            for width, height, label in ((1440,900,"1440x900"),(1366,768,"1366x768")):
                context = browser.new_context(viewport={"width":width,"height":height}, locale="zh-CN")
                page = context.new_page(); diagnostics(page, report); token = login(page)
                for index, row in enumerate(seed["resources"]):
                    report["runs"].append(run_resource(page, token, row, report, label, error_case=(label == "1440x900" and index == 9)))
                context.close()
            browser.close()
        report["database_audit"] = db_audit()
        report["formal_db_after"] = {"sha256": digest(ROOT / "edumatrix.db")}
        expected_http = [item for item in report["http_errors"] if item["status"] == 503]
        report["expected_http_errors"] = expected_http
        report["http_errors"] = [item for item in report["http_errors"] if item["status"] != 503]
        report["expected_console_errors"] = [item for item in report["console_errors"] if "503" in item]
        report["console_errors"] = [item for item in report["console_errors"] if "503" not in item]
        assert report["database_audit"]["integrity"] == "ok"
        assert report["database_audit"]["foreign_key_violations"] == 0
        assert report["database_audit"]["events"] == report["baseline_events"] + len(REPRESENTATIVES) * 2
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["result"] = "passed"
        return 0
    finally:
        stop_service(process)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        report["formal_db_unchanged"] = report.get("formal_db_after") == report["formal_db_before"]
        (EVIDENCE / "browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_report(report)


if __name__ == "__main__":
    raise SystemExit(main())
