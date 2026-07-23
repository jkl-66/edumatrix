"""Browser acceptance for the default no-Docker competition mode.

The script deliberately uses a temporary student account and the deterministic
LLM path so it can run on a clean evaluator machine without external services.
It writes screenshots and a JSON report under ``outputs/e2e_no_docker``.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:5173"
OUTPUT_DIR = ROOT / "outputs" / "e2e_no_docker"
EXPECTED_SANDBOX_MODE = os.getenv("EDUMATRIX_E2E_SANDBOX_MODE", "disabled").strip().lower()


def screenshot(page: Page, name: str) -> str:
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT)).replace("\\", "/")


def click_button(page: Page, name: str) -> None:
    page.get_by_role("button", name=re.compile(name)).click()


def complete_onboarding(page: Page) -> None:
    page.wait_for_url(re.compile(r"/onboarding$"), timeout=15_000)
    click_button(page, "期末复习冲刺")
    click_button(page, "下一步")
    click_button(page, "下一步")
    click_button(page, "具体例子")
    click_button(page, "进入我的学习矩阵")
    page.wait_for_url(re.compile(r"/$"), timeout=20_000)


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Do not leave a failed-run screenshot beside the final evidence set.
    stale_error = OUTPUT_DIR / "error.png"
    if stale_error.exists():
        stale_error.unlink()
    report: dict[str, object] = {
        "mode": EXPECTED_SANDBOX_MODE,
        "base_url": BASE_URL,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "screenshots": [],
        "checks": {},
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="zh-CN",
            extra_http_headers={"X-EduMatrix-LLM-Mode": "deterministic"},
        )
        page = context.new_page()

        try:
            health = page.request.get(f"{BASE_URL}/api/health")
            status = page.request.get(f"{BASE_URL}/api/code/status")
            health_json = health.json()
            status_json = status.json()
            assert health.ok and health_json.get("status") == "ok", health_json
            assert status.ok and status_json.get("mode") == EXPECTED_SANDBOX_MODE, status_json
            if EXPECTED_SANDBOX_MODE == "trusted_local":
                assert status_json.get("execution_enabled") is True, status_json
                assert status_json.get("isolation") == "trusted_local_child_process", status_json
            else:
                assert status_json.get("execution_enabled") is False, status_json
            report["checks"].update({
                "health": health_json,
                "sandbox_status": status_json,
                "llm_mode": "deterministic",
            })

            page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            report["screenshots"].append(screenshot(page, "01-login"))
            assert page.get_by_text("EduMatrix 智教矩阵").is_visible()

            click_button(page, "没有账号？立即注册")
            username = f"e2e_{int(time.time())}"
            page.get_by_placeholder("设置用户名").fill(username)
            page.get_by_placeholder("输入展示的昵称").fill("无 Docker 验收学生")
            page.get_by_placeholder("设置登录密码").fill("EduMatrix123!")
            page.get_by_placeholder("再次输入密码").fill("EduMatrix123!")
            click_button(page, "创建并启动学习")
            complete_onboarding(page)

            report["checks"]["temporary_student"] = username
            page.locator('[aria-label="正在加载仪表盘"]').wait_for(state="detached", timeout=45_000)
            page.wait_for_timeout(500)
            report["screenshots"].append(screenshot(page, "02-dashboard"))
            assert page.get_by_text("学习仪表盘").first.is_visible()

            page.goto(f"{BASE_URL}/learn", wait_until="networkidle")
            page.get_by_text("智能对话").first.wait_for(state="visible", timeout=15_000)
            report["screenshots"].append(screenshot(page, "03-chat-empty"))

            question = "解释 accuracy 和 recall 的区别，用一个混淆矩阵例子。"
            composer = page.locator("textarea[placeholder^='输入学习问题']")
            composer.fill(question)
            page.locator("button.btn.btn-primary").last.click()
            page.locator(".chat-card-assistant").last.wait_for(state="visible", timeout=45_000)
            try:
                page.get_by_text(re.compile("正在组织回复")).first.wait_for(
                    state="detached", timeout=45_000
                )
            except PlaywrightTimeoutError:
                # The response is still useful evidence, but record the timeout
                # instead of hiding a slow deterministic pipeline.
                report["checks"]["chat_stream_warning"] = "Agent progress remained visible after 45 seconds"
            page.wait_for_timeout(500)
            report["checks"]["chat_response"] = {
                "question": question,
                "assistant_cards": page.locator(".chat-card-assistant").count(),
            }
            report["screenshots"].append(screenshot(page, "04-chat-response"))

            # The sandbox is a right-side tool while the main tab remains chat.
            # The separate main "代码" tab is a code editor for quiz resources.
            click_button(page, "沙箱")
            if EXPECTED_SANDBOX_MODE == "trusted_local":
                page.get_by_text("本地可信研究模式", exact=False).first.wait_for(
                    state="visible", timeout=15_000
                )
                editor = page.get_by_placeholder("在此输入 Python 代码...")
                editor.fill("print(6 * 7)")
                run_button = page.get_by_role("button", name="运行", exact=True).last
                assert run_button.is_enabled(), "trusted-local run button must be enabled"
                run_button.click()
                page.get_by_text("42", exact=True).first.wait_for(state="visible", timeout=30_000)
                report["checks"]["frontend_sandbox_execution"] = {
                    "mode": "trusted_local",
                    "run_button_enabled": True,
                    "output_contains_42": True,
                    "security_level": status_json.get("security_level"),
                }
                report["screenshots"].append(
                    screenshot(page, "05-code-sandbox-trusted-local")
                )
            else:
                # The final UI uses "代码执行未启用"; keep the older wording as a
                # compatibility fallback for evaluator branches that still show it.
                page.get_by_text(re.compile("代码(?:执行|沙箱)未启用"), exact=False).first.wait_for(
                    state="visible", timeout=15_000
                )
                run_button = page.get_by_role("button", name=re.compile("沙箱未启用"))
                assert run_button.is_disabled(), "code run must be disabled in no-Docker mode"
                report["checks"]["frontend_sandbox_guard"] = {
                    "message_visible": True,
                    "run_button_disabled": run_button.is_disabled(),
                }
                report["screenshots"].append(screenshot(page, "05-code-sandbox-disabled"))

            page.goto(f"{BASE_URL}/learning-path", wait_until="networkidle")
            page.wait_for_timeout(1_000)
            report["screenshots"].append(screenshot(page, "06-learning-path"))

            page.goto(f"{BASE_URL}/knowledge", wait_until="networkidle")
            page.wait_for_timeout(1_000)
            baseline_course_title = "RAG 应用开发与幻觉评测实训课"
            page.get_by_text(baseline_course_title, exact=True).wait_for(
                state="visible", timeout=15_000
            )
            baseline_course = page.locator("section.knowledge-group").filter(
                has_text=baseline_course_title
            )
            baseline_document_count = baseline_course.locator(".knowledge-card").count()
            baseline_readonly_count = baseline_course.locator(
                '[title="公共课程为只读内容"]'
            ).count()
            assert baseline_document_count == 9, baseline_document_count
            assert baseline_readonly_count == 9, baseline_readonly_count
            report["checks"]["knowledge_page"] = {
                "loaded": page.url.endswith("/knowledge"),
                "course_text_visible": True,
                "baseline_course_title": baseline_course_title,
                "baseline_course_documents": baseline_document_count,
                "baseline_course_readonly_documents": baseline_readonly_count,
                "source_visible": baseline_course.get_by_text("来源：", exact=False).count() > 0,
            }
            report["screenshots"].append(screenshot(page, "07-knowledge"))

            page.goto(f"{BASE_URL}/student-analysis", wait_until="networkidle")
            page.wait_for_timeout(1_000)
            report["checks"]["profile_analysis_page"] = {
                "loaded": page.url.endswith("/student-analysis"),
                "analysis_text_visible": page.get_by_text(re.compile("画像|分析|掌握")).count() > 0,
            }
            report["screenshots"].append(screenshot(page, "08-student-analysis"))

            page.goto(f"{BASE_URL}/settings", wait_until="networkidle")
            page.wait_for_timeout(800)
            report["checks"]["settings_page"] = {
                "loaded": page.url.endswith("/settings"),
                "multimodal_text_visible": page.get_by_text(re.compile("多模态|视觉")).count() > 0,
            }
            report["screenshots"].append(screenshot(page, "09-settings-multimodal"))

            report["result"] = "passed"
        except Exception as exc:
            report["result"] = "failed"
            report["error"] = f"{type(exc).__name__}: {exc}"
            try:
                report["screenshots"].append(screenshot(page, "error"))
            except Exception:
                pass
            raise
        finally:
            report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            (OUTPUT_DIR / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            context.close()
            browser.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
