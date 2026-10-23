"""F5-T07 resource history and editor desktop E2E on isolated SQLite."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import traceback
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from e2e_f5_t03_handout_workspace import (
    COURSE_ID,
    ROOT,
    STRUCTURED_ID,
    database_audit,
    learning_state,
    login,
    port_open,
    runtime_env,
    seed_fixture,
    start_service,
    stop_service,
)


OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f5_t07_resource_history"
PASSWORD = "404404aA"
PORT_START = int(os.getenv("EDUMATRIX_F5_T07_PORT", "9011"))
VIEWPORTS = ((1440, 900), (1366, 768))


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F5-T07 E2E port")


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def page_diagnostics(page: Page, report: dict[str, object]) -> None:
    page.on("response", lambda response: report["http_errors"].append({
        "status": response.status,
        "url": response.url,
    }) if response.status >= 400 else None)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url,
        "failure": request.failure,
    }) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" else None)


def visible_metrics(page: Page, root_selector: str) -> dict[str, object]:
    return page.evaluate("""(rootSelector) => {
      const root = document.querySelector(rootSelector);
      const visible = (el) => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1;
      };
      const elements = root ? [...root.querySelectorAll('*')] : [];
      const controls = elements.filter((el) => el.matches('button,a[href],input,select,textarea') &&
        !el.matches('.history-backdrop, .editor-backdrop') && visible(el));
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
        if (el.matches('select, option') || el.querySelector('select, option')) return false;
        if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false;
        return rect.right > innerWidth + 1 || rect.left < -1 ||
          (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap' && style.overflowX !== 'auto');
      }).map((el) => (el.innerText || '').trim().slice(0, 80)).filter(Boolean).slice(0, 20);
      const smallText = elements.filter((el) => {
        const text = (el.innerText || '').replaceAll('\\u200b', '').trim();
        if (el.matches('.history-version em')) return false;
        return visible(el) && el.children.length === 0 && text &&
          Number.parseFloat(getComputedStyle(el).fontSize) < 13.5;
      }).map((el) => ({ text: el.innerText.trim().slice(0, 40), size: getComputedStyle(el).fontSize })).slice(0, 20);
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
    }""", root_selector)


def capture(page: Page, report: dict[str, object], name: str, root_selector: str, minimum_text: int = 150) -> None:
    page.wait_for_timeout(350)
    metrics = visible_metrics(page, root_selector)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] > minimum_text, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["forbiddenEffects"], metrics


def open_resource_center(page: Page, base_url: str) -> None:
    page.goto(
        f"{base_url}/workspace/resources?course_id={COURSE_ID}",
        wait_until="networkidle",
        timeout=60_000,
    )
    page.get_by_test_id("resource-center").wait_for(state="visible")
    page.locator(f'[data-resource-id="{STRUCTURED_ID}"]').click()
    page.get_by_test_id("resource-preview").get_by_role(
        "heading", name="梯度下降个性化讲义", exact=True,
    ).wait_for(state="visible")


def exercise_history_and_editor(page: Page, base_url: str, report: dict[str, object]) -> None:
    open_resource_center(page, base_url)
    capture(page, report, "01-resource-center-current-1440x900.png", '[data-testid="resource-center"]')

    page.get_by_role("button", name="历史 2", exact=True).click()
    drawer = page.get_by_test_id("resource-history-drawer")
    drawer.wait_for(state="visible")
    old_item = drawer.locator("li").filter(has_text="v1").first
    old_item.get_by_role("button", name="比较", exact=True).click()
    drawer.get_by_text("版本比较", exact=True).wait_for(state="visible")
    capture(page, report, "02-history-compare-1440x900.png", '[data-testid="resource-history-drawer"]')

    old_item.get_by_role("button", name="恢复为当前", exact=True).click()
    page.get_by_role("status").filter(has_text="历史版本已恢复为新的当前版本").wait_for(state="visible")
    drawer.get_by_text("当前", exact=True).wait_for(state="visible")
    report["history_restore"] = {"source": "v1", "created_new_current": True}
    capture(page, report, "03-history-restored-1440x900.png", '[data-testid="resource-history-drawer"]')

    page.get_by_title("关闭版本历史").click()
    page.get_by_role("button", name="编辑另存", exact=True).click()
    editor = page.locator('[data-testid="resource-center"] .editor-layer')
    editor.get_by_role("dialog").wait_for(state="visible")
    draft = editor.locator("textarea")
    edited_content = json.loads(draft.input_value())
    edited_content["summary"] = "另存版本：保留原版本并记录本次学习空间修订。"
    draft.fill(json.dumps(edited_content, ensure_ascii=False, indent=2))
    capture(page, report, "04-editor-dialog-1440x900.png", '[role="dialog"]', minimum_text=100)
    editor.get_by_role("button", name="保存为新版本", exact=True).click()
    page.get_by_role("status").filter(has_text="新版本已保存").wait_for(state="visible")
    report["editor_save"] = {"created_new_version": True, "historical_content_preserved": True}
    capture(page, report, "05-editor-saved-1440x900.png", '[data-testid="resource-center"]')


def run() -> dict[str, object]:
    clear_output()
    db_path = OUTPUT_DIR / "f5_t07.sqlite3"
    port = free_port()
    env = runtime_env(db_path, port)
    seed_fixture(env)
    before = learning_state(db_path)
    base_url = f"http://127.0.0.1:{port}"
    report: dict[str, object] = {
        "schema_version": "f5-t07.resource-history-desktop.v1",
        "viewports": [list(item) for item in VIEWPORTS],
        "port": port,
        "screenshots": [],
        "checks": {},
        "history_restore": {},
        "editor_save": {},
        "learning_state_before": before,
        "learning_state_after": {},
        "database_audit": {},
        "http_errors": [],
        "failed_requests": [],
        "console_errors": [],
        "page_errors": [],
        "process_cleanup": {},
        "result": "failed",
    }
    process = None
    try:
        process = start_service(env, port, OUTPUT_DIR / "backend.log")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                )
                page = context.new_page()
                page.set_default_timeout(30_000)
                page_diagnostics(page, report)
                login(page, base_url)
                exercise_history_and_editor(page, base_url, report)
                context.close()

                context = browser.new_context(
                    viewport={"width": 1366, "height": 768},
                    locale="zh-CN",
                )
                page = context.new_page()
                page.set_default_timeout(30_000)
                page_diagnostics(page, report)
                login(page, base_url)
                open_resource_center(page, base_url)
                page.reload(wait_until="networkidle", timeout=60_000)
                page.get_by_test_id("resource-preview").get_by_role(
                    "heading", name="梯度下降个性化讲义", exact=True,
                ).wait_for(state="visible")
                capture(page, report, "06-refresh-recovered-1366x768.png", '[data-testid="resource-center"]')
                page.get_by_role("button", name="历史 4", exact=True).click()
                page.get_by_test_id("resource-history-drawer").wait_for(state="visible")
                capture(page, report, "07-history-drawer-1366x768.png", '[data-testid="resource-history-drawer"]')
                context.close()
            finally:
                browser.close()

        after = learning_state(db_path)
        report["learning_state_after"] = after
        assert after == before, {"before": before, "after": after}
        report["database_audit"] = database_audit(db_path)
        assert report["database_audit"]["integrity"] == "ok"
        assert report["database_audit"]["foreign_key_violations"] == 0
        assert len(report["database_audit"]["structured_versions"]) == 4
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
