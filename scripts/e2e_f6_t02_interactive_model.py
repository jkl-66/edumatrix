"""F6-T02 canonical interactive-model desktop E2E on isolated SQLite."""

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
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f6_t02_interactive_model"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PASSWORD = "404404aA"
PORT_START = int(os.getenv("EDUMATRIX_F6_T02_PORT", "8992"))


def port_open(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F6-T02 E2E port")


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
        "EDUMATRIX_AUTH_SECRET_KEY": "f6-t02-isolated-secret",
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


def seed_fixture(env: dict[str, str]) -> dict[str, str | int]:
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import json
from pathlib import Path
from app.competition_demo_seed import seed_competition_demo
from app.database import DBArtifact, DBArtifactVersion, DBProfileSnapshot, DBSourceRef, DBUser, SessionLocal, init_db
from app.m5_resources import ResourceVersionCreateRequest, create_resource_version
from app.resource_bundles import create_generation_job, execute_generation_job_demo

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    learner = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    profile = db.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
    source = db.get(DBSourceRef, "demo-ref-07")
    if profile is None or source is None:
        raise RuntimeError("competition demo profile or source is missing")
    job = create_generation_job(
        db,
        learner,
        course_id={COURSE_ID!r},
        knowledge_point_id="demo-kp-07",
        profile_snapshot_id=profile.id,
        idempotency_key="f6-t02-browser-fixture-001",
        scope="single",
        items=[{{
            "type": "interactive_model",
            "title": "混合检索参数实验",
            "source_ref_ids": [source.id],
            "completion_rule": "运行实验并提交不少于 20 个字的观察结论",
        }}],
        learning_goal="解释混合检索参数对召回、排序质量和延迟的影响",
    )
    db.commit()
    result = execute_generation_job_demo(db, learner, job["job_id"])
    db.commit()
    resource_id = result["items"][0]["resource"]["resource_id"]
    artifact = db.get(DBArtifact, resource_id)
    original = db.get(DBArtifactVersion, artifact.current_version_id)
    revised = json.loads(original.content)
    revised["summary"] = "比较关键词与向量权重，观察召回质量、排序质量和延迟之间的平衡。"
    detail = create_resource_version(
        db,
        artifact=artifact,
        actor_public_id=learner.public_id,
        request=ResourceVersionCreateRequest(
            expected_lock_version=artifact.lock_version,
            source_version_id=original.id,
            content=json.dumps(revised, ensure_ascii=False),
            content_format="json",
        ),
    )
    db.commit()
    payload = {{
        "resource_id": resource_id,
        "original_version_id": original.id,
        "current_version_id": detail["interactive_model"]["current_version_id"],
        "owner_public_id": learner.public_id,
        "source_ref_id": source.id,
        "initial_version_count": len(detail["interactive_model"]["versions"]),
    }}
    Path({str(fixture_path)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=120)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def start_service(env: dict[str, str], port: int) -> subprocess.Popen:
    log = (OUTPUT_DIR / "server.log").open("a", encoding="utf-8")
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


def database_state(db_path: Path, fixture: dict[str, str | int]) -> dict[str, int | str]:
    with sqlite3.connect(db_path, timeout=10) as db:
        resource_id = str(fixture["resource_id"])
        owner = str(fixture["owner_public_id"])
        return {
            "observation_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=? AND event_type='interactive_model_observation_submitted' AND object_id=?",
                (owner, resource_id),
            ).fetchone()[0],
            "resource_versions": db.execute(
                "SELECT COUNT(*) FROM artifact_versions WHERE artifact_id=?",
                (resource_id,),
            ).fetchone()[0],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
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


def visible_metrics(page: Page, root_selector: str) -> dict:
    return page.evaluate("""(selector) => {
      const root = document.querySelector(selector);
      const visible = (el) => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1;
      };
      const rgb = (value) => {
        const match = String(value).match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
        return match ? match.slice(1).map(Number) : null;
      };
      const saturatedLightColor = (value) => {
        const color = rgb(value);
        if (!color) return false;
        const [r, g, b] = color.map(item => item / 255);
        const max = Math.max(r, g, b), min = Math.min(r, g, b);
        const lightness = (max + min) / 2;
        const saturation = max === min ? 0 : (max - min) / (1 - Math.abs(2 * lightness - 1));
        return saturation > .28 && lightness > .22;
      };
      const elements = root ? [root, ...root.querySelectorAll('*')] : [];
      const controls = elements.filter((el) => el.matches('button,a[href],input,select,textarea') &&
        visible(el) && !el.classList.contains('history-backdrop'));
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
        const text = (el.innerText || '').replaceAll('\\u200b', '').trim();
        return visible(el) && el.children.length === 0 && text &&
          Number.parseFloat(getComputedStyle(el).fontSize) < 13.5;
      }).map((el) => ({ text: el.innerText.trim().slice(0, 40), size: getComputedStyle(el).fontSize })).slice(0, 20);
      const forbiddenEffects = elements.filter(visible).filter((el) => {
        const style = getComputedStyle(el);
        return (style.backgroundImage || '').includes('gradient') ||
          !['none', ''].includes(style.backdropFilter || 'none');
      }).map((el) => el.className?.toString().slice(0, 80)).slice(0, 20);
      const forbiddenColors = elements.filter(visible).flatMap((el) => {
        const style = getComputedStyle(el);
        return [style.color, style.backgroundColor, style.borderTopColor]
          .filter(saturatedLightColor)
          .map(value => ({ value, element: el.className?.toString().slice(0, 64) || el.tagName }));
      }).slice(0, 20);
      return {
        viewport: [innerWidth, innerHeight],
        documentWidth: document.documentElement.scrollWidth,
        bodyTextLength: (root?.innerText || '').trim().length,
        collisions, clipped, smallText, forbiddenEffects, forbiddenColors,
      };
    }""", root_selector)


def capture(page: Page, report: dict, name: str, root_selector: str, minimum_text: int = 120) -> None:
    page.wait_for_timeout(300)
    metrics = visible_metrics(page, root_selector)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] >= minimum_text, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["forbiddenEffects"], metrics
    assert not metrics["forbiddenColors"], metrics


def open_model(page: Page, base_url: str, resource_id: str) -> None:
    page.goto(
        f"{base_url}/workspace/resources/models/{resource_id}?course_id={COURSE_ID}",
        wait_until="networkidle", timeout=60_000,
    )
    page.get_by_test_id("interactive-lab-workspace").wait_for(state="visible")
    page.locator(".model-layout").wait_for(state="visible")


def exercise_primary_flow(
    page: Page,
    base_url: str,
    fixture: dict[str, str | int],
    db_path: Path,
    report: dict,
) -> None:
    resource_id = str(fixture["resource_id"])
    open_model(page, base_url, resource_id)
    assert database_state(db_path, fixture)["observation_events"] == 0
    assert page.locator(".parameter-control").count() == 4
    assert page.get_by_text("冻结数据集", exact=True).is_visible()
    assert page.get_by_text("课程来源", exact=True).is_visible()
    capture(page, report, "01-model-ready-1440x900.png", '[data-testid="interactive-lab-workspace"]')

    keyword = page.get_by_role("slider", name="关键词权重")
    vector = page.get_by_role("slider", name="向量权重")
    keyword.fill("0.35")
    vector.fill("0.65")
    assert keyword.input_value() == "0.35"
    assert vector.input_value() == "0.65"
    assert database_state(db_path, fixture)["observation_events"] == 0
    page.get_by_role("button", name="开始实验", exact=True).click()
    page.get_by_text("实验结果已更新。调参和运行不会写入学习证据。", exact=True).wait_for(state="visible")
    page.get_by_test_id("interactive-model-chart").locator("polyline").wait_for(state="visible")
    assert page.get_by_test_id("lab-results").locator('[role="row"]').count() == 3
    assert database_state(db_path, fixture)["observation_events"] == 0
    capture(page, report, "02-model-result-1440x900.png", '[data-testid="interactive-lab-workspace"]')

    page.get_by_role("button", name="查看提示", exact=True).click()
    page.get_by_text("提示已加入运行反馈；只有提交观察结论才会形成学习证据。", exact=True).wait_for(state="visible")
    assert database_state(db_path, fixture)["observation_events"] == 0

    keyword.fill("0.4")
    vector.fill("0.6")
    action_url = "**/api/v1/interactive-lab/instances/*/actions"
    page.route(action_url, lambda route: route.fulfill(
        status=503,
        content_type="application/json",
        body=json.dumps({"detail": {"message": "模拟实验服务暂时不可用"}}, ensure_ascii=False),
    ))
    page.get_by_role("button", name="按当前参数运行", exact=True).click()
    page.get_by_text("模拟实验服务暂时不可用", exact=True).wait_for(state="visible")
    assert keyword.input_value() == "0.4"
    assert vector.input_value() == "0.6"
    assert database_state(db_path, fixture)["observation_events"] == 0
    page.unroute(action_url)
    report["expected_run_failure"] = {"parameter_draft_preserved": True, "value": "0.4"}
    report["expected_http_errors"].extend([
        item for item in report["http_errors"]
        if item["status"] == 503 and "/api/v1/interactive-lab/instances/" in item["url"]
    ])
    report["http_errors"] = [item for item in report["http_errors"] if item["status"] != 503]
    report["expected_console_errors"].extend([
        item for item in report["console_errors"] if "status of 503" in item
    ])
    report["console_errors"] = [item for item in report["console_errors"] if "status of 503" not in item]

    page.get_by_role("button", name="按当前参数运行", exact=True).click()
    page.get_by_text("实验结果已更新。调参和运行不会写入学习证据。", exact=True).wait_for(state="visible")
    observation = "提高关键词权重后排序质量有所变化，但召回和延迟仍需结合当前课程目标一起权衡。"
    field = page.get_by_role("textbox", name="观察结论")
    field.fill(observation)
    page.route(action_url, lambda route: route.fulfill(
        status=503,
        content_type="application/json",
        body=json.dumps({"detail": {"message": "模拟观察提交暂时不可用"}}, ensure_ascii=False),
    ))
    page.get_by_role("button", name="提交观察结论", exact=True).click()
    page.get_by_text("模拟观察提交暂时不可用", exact=True).wait_for(state="visible")
    assert field.input_value() == observation
    assert database_state(db_path, fixture)["observation_events"] == 0
    page.unroute(action_url)
    report["expected_submit_failure"] = {"observation_draft_preserved": True}
    report["expected_http_errors"].extend([
        item for item in report["http_errors"]
        if item["status"] == 503 and "/api/v1/interactive-lab/instances/" in item["url"]
    ])
    report["http_errors"] = [item for item in report["http_errors"] if item["status"] != 503]
    report["expected_console_errors"].extend([
        item for item in report["console_errors"] if "status of 503" in item
    ])
    report["console_errors"] = [item for item in report["console_errors"] if "status of 503" not in item]

    page.get_by_role("button", name="提交观察结论", exact=True).click()
    page.get_by_test_id("interactive-model-completion").wait_for(state="visible")
    assert database_state(db_path, fixture)["observation_events"] == 1
    capture(page, report, "03-observation-complete-1440x900.png", '[data-testid="interactive-lab-workspace"]')

    page.reload(wait_until="networkidle")
    page.get_by_test_id("interactive-model-completion").wait_for(state="visible")
    assert page.get_by_role("textbox", name="观察结论").input_value() == observation
    assert database_state(db_path, fixture)["observation_events"] == 1
    capture(page, report, "04-refresh-restored-1440x900.png", '[data-testid="interactive-lab-workspace"]')

    page.get_by_test_id("resource-toolbar").get_by_role("button", name="版本历史", exact=False).click()
    drawer = page.get_by_test_id("resource-history-drawer")
    drawer.wait_for(state="visible")
    assert drawer.locator(".history-list li").count() == int(fixture["initial_version_count"])
    capture(page, report, "05-version-history-1440x900.png", '[data-testid="resource-history-drawer"]', 60)
    original_item = drawer.locator(".history-list li").filter(has_text="v1")
    original_item.get_by_role("button", name="恢复为当前", exact=True).click()
    drawer.wait_for(state="hidden")
    version_line = page.get_by_test_id("resource-toolbar").locator(".toolbar-identity p")
    version_line.wait_for(state="visible")
    assert "v3" in version_line.inner_text()
    assert database_state(db_path, fixture)["resource_versions"] == 3
    report["history_restore"] = {"created_new_version": True, "version_count": 3}


def exercise_secondary_viewport(
    page: Page,
    base_url: str,
    fixture: dict[str, str | int],
    report: dict,
) -> None:
    open_model(page, base_url, str(fixture["resource_id"]))
    capture(page, report, "06-model-restored-1366x768.png", '[data-testid="interactive-lab-workspace"]')
    page.goto(f"{base_url}/interactive-lab", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("lab-template-list").wait_for(state="visible")
    assert page.get_by_test_id("lab-template-list").locator("button").count() == 2
    assert page.get_by_role("button", name="创建实验", exact=True).is_visible()
    capture(page, report, "07-legacy-route-1366x768.png", '[data-testid="interactive-lab-workspace"]')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def run() -> dict:
    clear_output()
    db_path = OUTPUT_DIR / "f6_t02.sqlite3"
    port = free_port()
    env = runtime_env(db_path, port)
    fixture = seed_fixture(env)
    process: subprocess.Popen | None = None
    report = {
        "schema_version": "f6-t02.interactive-model-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [], "checks": {},
        "http_errors": [], "failed_requests": [], "page_errors": [], "console_errors": [],
        "expected_http_errors": [], "expected_console_errors": [],
        "expected_run_failure": {}, "expected_submit_failure": {}, "history_restore": {},
        "external_model_called": False,
    }
    try:
        process = start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            login(page, base_url)
            exercise_primary_flow(page, base_url, fixture, db_path, report)
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            page_diagnostics(page, report)
            login(page, base_url)
            exercise_secondary_viewport(page, base_url, fixture, report)
            context.close()
            browser.close()
        report["database"] = database_state(db_path, fixture)
        assert report["database"]["observation_events"] == 1
        assert report["database"]["resource_versions"] == 3
        assert report["database"]["integrity"] == "ok"
        assert report["database"]["foreign_key_violations"] == 0
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        stop_service(process, port)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT_DIR.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT_DIR / "manifest.json").write_text(
            json.dumps({"schema_version": "f6-t02.evidence-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
