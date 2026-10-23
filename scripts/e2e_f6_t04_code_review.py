"""F6-T04 code-review desktop E2E on isolated SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

import e2e_f6_t03_code_sandbox as base


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f6_t04_code_review"
ERROR_CODE = "values = []\nprint(sum(values) / len(values))"


def seed_error_fixture(env: dict[str, str]) -> dict[str, str | int]:
    base.OUTPUT_DIR = OUTPUT_DIR
    fixture = base.seed_fixture(env)
    fixture_path = OUTPUT_DIR / "fixture.json"
    script = f'''
import json
from pathlib import Path
from app.database import DBArtifact, DBArtifactVersion, SessionLocal
from app.m5_resources import ResourceVersionCreateRequest, create_resource_version

db = SessionLocal()
try:
    artifact = db.get(DBArtifact, {fixture["resource_id"]!r})
    current = db.get(DBArtifactVersion, artifact.current_version_id)
    content = json.loads(current.content)
    entry_file = content["entryFile"]
    for item in content["files"]:
        if item["path"] == entry_file:
            item["content"] = {ERROR_CODE!r}
            break
    else:
        raise RuntimeError("entry file is missing")
    detail = create_resource_version(
        db,
        artifact=artifact,
        actor_public_id={fixture["owner_public_id"]!r},
        request=ResourceVersionCreateRequest(
            expected_lock_version=artifact.lock_version,
            source_version_id=current.id,
            content=json.dumps(content, ensure_ascii=False),
            content_format="json",
        ),
    )
    db.commit()
    payload = {json.dumps(fixture, ensure_ascii=False)}
    payload["current_version_id"] = detail["code_sandbox"]["current_version_id"]
    payload["initial_version_count"] = len(detail["code_sandbox"]["versions"])
    Path({str(fixture_path)!r}).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
finally:
    db.close()
'''
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True, timeout=120)
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def database_state(db_path: Path, fixture: dict[str, str | int]) -> dict[str, int | str]:
    with sqlite3.connect(db_path, timeout=10) as db:
        resource_id = str(fixture["resource_id"])
        owner = str(fixture["owner_public_id"])
        return {
            "completion_events": db.execute(
                "SELECT COUNT(*) FROM learning_events WHERE owner_public_id=? "
                "AND event_type='code_tests_passed' AND object_id=?",
                (owner, resource_id),
            ).fetchone()[0],
            "resource_versions": db.execute(
                "SELECT COUNT(*) FROM artifact_versions WHERE artifact_id=?",
                (resource_id,),
            ).fetchone()[0],
            "run_artifacts": db.execute(
                "SELECT COUNT(*) FROM artifacts WHERE owner_public_id=? AND artifact_type='code_sandbox_run'",
                (owner,),
            ).fetchone()[0],
            "review_artifacts": db.execute(
                "SELECT COUNT(*) FROM artifacts WHERE owner_public_id=? AND artifact_type='code_sandbox_review'",
                (owner,),
            ).fetchone()[0],
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def capture(page: Page, report: dict, filename: str) -> None:
    page.screenshot(path=OUTPUT_DIR / filename, full_page=True)
    report["screenshots"].append(filename)


def visual_contract(page: Page) -> dict:
    return page.evaluate("""
      () => {
        const visible = element => {
          const style = getComputedStyle(element)
          const box = element.getBoundingClientRect()
          return style.display !== 'none' && style.visibility !== 'hidden' && box.width > 0 && box.height > 0
        }
        const panels = ['.left-panel', '.editor-panel', '.result-panel'].map(selector => {
          const box = document.querySelector(selector).getBoundingClientRect()
          return { selector, left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width }
        })
        const textNodes = [...document.querySelectorAll(
          '.review-panel button, .review-panel textarea, .review-panel h3, .review-panel strong, '
          + '.review-panel p, .review-panel small, .review-panel span, .review-panel code, .review-panel li'
        )].filter(element => visible(element) && element.textContent.trim())
        const smallText = textNodes
          .filter(element => Number.parseFloat(getComputedStyle(element).fontSize) < 14)
          .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 80) }))
        const clippedText = textNodes
          .filter(element => {
            const style = getComputedStyle(element)
            if (['auto', 'scroll'].includes(style.overflowX) || ['auto', 'scroll'].includes(style.overflowY)) return false
            if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false
            return element.scrollWidth > element.clientWidth + 1 || element.scrollHeight > element.clientHeight + 1
          })
          .map(element => ({ tag: element.tagName, text: element.textContent.trim().slice(0, 80) }))
        return {
          documentOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
          panelOverlap: panels[0].right > panels[1].left + 1 || panels[1].right > panels[2].left + 1,
          panels,
          smallText,
          clippedText,
        }
      }
    """)


def assert_visual_contract(page: Page, report: dict, key: str) -> None:
    result = visual_contract(page)
    report["visual"][key] = result
    assert result["documentOverflow"] is False, result
    assert result["panelOverlap"] is False, result
    assert result["smallText"] == [], result
    assert result["clippedText"] == [], result


def run_error_review_apply_rerun(
    page: Page,
    base_url: str,
    fixture: dict[str, str | int],
    db_path: Path,
    report: dict,
) -> None:
    base.open_sandbox(page, base_url, str(fixture["resource_id"]))
    report["checks"]["grid_ratios_1440"] = base.assert_three_columns(page)
    assert database_state(db_path, fixture)["completion_events"] == 0

    page.get_by_role("button", name="运行代码", exact=True).click()
    page.locator(".result-summary").get_by_text("运行报错", exact=True).wait_for(
        state="visible", timeout=60_000,
    )
    page.get_by_role("button", name="错误", exact=False).click()
    page.get_by_text("ZeroDivisionError", exact=False).wait_for(state="visible")
    capture(page, report, "01-runtime-error-1440x900.png")

    page.get_by_role("button", name="AI 点评", exact=True).click()
    page.get_by_text("真实证据已就绪", exact=True).wait_for(state="visible")
    page.get_by_label("点评重点 可选").fill("重点检查空列表边界与运行错误")
    page.get_by_role("button", name="基于本次运行生成点评", exact=True).click()
    for heading in ("问题定位", "点评重点", "潜在风险", "改进代码", "应用建议"):
        page.get_by_role("heading", name=heading, exact=True).wait_for(state="visible")
    page.get_by_text("ZeroDivisionError", exact=False).first.wait_for(state="visible")
    page.get_by_text("else 0.0", exact=False).wait_for(state="visible")
    assert_visual_contract(page, report, "review_1440x900")
    capture(page, report, "02-review-complete-1440x900.png")

    page.get_by_role("button", name="应用建议并另存新版本", exact=True).click()
    page.locator(".applied-state strong").get_by_text("已另存为 v", exact=False).wait_for(state="visible")
    page.get_by_text("原版本和原运行记录仍保留", exact=False).wait_for(state="visible")
    assert database_state(db_path, fixture)["resource_versions"] == int(fixture["initial_version_count"]) + 1
    assert database_state(db_path, fixture)["completion_events"] == 0
    capture(page, report, "03-review-applied-1440x900.png")

    page.get_by_role("button", name="运行代码", exact=True).click()
    page.locator(".result-summary").get_by_text("运行成功", exact=True).wait_for(
        state="visible", timeout=60_000,
    )
    page.get_by_role("button", name="输出", exact=True).click()
    page.locator(".terminal-output").get_by_text("0.0", exact=True).wait_for(state="visible")
    assert database_state(db_path, fixture)["completion_events"] == 0

    history = page.locator(".run-history > button")
    assert history.count() == 2
    history.filter(has_text="运行报错").click()
    page.locator(".result-summary").get_by_text("运行报错", exact=True).wait_for(state="visible")
    history.filter(has_text="运行成功").click()
    page.locator(".result-summary").get_by_text("运行成功", exact=True).wait_for(state="visible")
    report["checks"]["history_compared"] = ["runtime_error", "success"]
    capture(page, report, "04-rerun-and-history-1440x900.png")


def verify_secondary_viewport(page: Page, base_url: str, fixture: dict[str, str | int], report: dict) -> None:
    base.open_sandbox(page, base_url, str(fixture["resource_id"]))
    report["checks"]["grid_ratios_1366"] = base.assert_three_columns(page)
    page.locator(".panel-tabs").first.get_by_role("button", name="运行历史", exact=False).click()
    page.locator(".run-history > button").filter(has_text="运行报错").click()
    page.get_by_role("button", name="AI 点评", exact=True).click()
    page.get_by_role("heading", name="问题定位", exact=True).wait_for(state="visible")
    assert_visual_contract(page, report, "review_1366x768")
    capture(page, report, "05-review-history-1366x768.png")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def run() -> dict:
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = 8994
    base.clear_output()
    db_path = OUTPUT_DIR / "f6_t04.sqlite3"
    port = base.free_port()
    env = base.runtime_env(db_path, port)
    fixture = seed_error_fixture(env)
    process: subprocess.Popen | None = None
    report = {
        "schema_version": "f6-t04.code-review-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "checks": {},
        "visual": {},
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "external_model_called": False,
    }
    try:
        process = base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page = context.new_page()
            base.page_diagnostics(page, report)
            base.login(page, base_url)
            run_error_review_apply_rerun(page, base_url, fixture, db_path, report)
            context.close()

            context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
            page = context.new_page()
            base.page_diagnostics(page, report)
            base.login(page, base_url)
            verify_secondary_viewport(page, base_url, fixture, report)
            context.close()
            browser.close()

        report["database"] = database_state(db_path, fixture)
        assert report["database"]["completion_events"] == 0
        assert report["database"]["resource_versions"] == int(fixture["initial_version_count"]) + 1
        assert report["database"]["run_artifacts"] == 2
        assert report["database"]["review_artifacts"] == 1
        assert report["database"]["integrity"] == "ok"
        assert report["database"]["foreign_key_violations"] == 0
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        base.stop_service(process, port)
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
            json.dumps(
                {"schema_version": "f6-t04.evidence-manifest.v1", "files": files},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
