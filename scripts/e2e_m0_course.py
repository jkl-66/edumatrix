"""Focused browser acceptance for the M0 preloaded RAG course.

This deliberately avoids chat, external providers, code execution, and all pages
outside the knowledge-base workflow so a slow external dependency cannot obscure
the course acceptance result.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:5173"
OUTPUT_DIR = ROOT / "outputs" / "e2e_course"
COURSE_TITLE = "RAG 应用开发与幻觉评测实训课"
EXPECTED_DOCUMENTS = 9


def screenshot(page: Page, name: str) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT)).replace("\\", "/")


def click_button(page: Page, pattern: str) -> None:
    page.get_by_role("button", name=re.compile(pattern)).click()


def complete_onboarding(page: Page) -> None:
    page.wait_for_url(re.compile(r"/onboarding$"), timeout=15_000)
    click_button(page, "期末复习冲刺")
    click_button(page, "下一步")
    click_button(page, "下一步")
    click_button(page, "具体例子")
    click_button(page, "进入我的学习矩阵")
    page.wait_for_url(re.compile(r"/$"), timeout=20_000)


def main() -> int:
    report: dict[str, object] = {
        "base_url": BASE_URL,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "screenshots": [],
        "checks": {},
    }
    report_path = OUTPUT_DIR / "report.json"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = context.new_page()
        try:
            health = page.request.get(f"{BASE_URL}/api/health")
            assert health.ok and health.json().get("status") == "ok", health.text()
            report["checks"]["health"] = health.json()

            page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            report["screenshots"].append(screenshot(page, "01-login"))
            assert page.get_by_text("EduMatrix 智教矩阵").is_visible()

            click_button(page, "没有账号？立即注册")
            username = f"m0_course_{int(time.time())}"
            page.get_by_placeholder("设置用户名").fill(username)
            page.get_by_placeholder("输入展示的昵称").fill("M0 课程验收学生")
            page.get_by_placeholder("设置登录密码").fill("EduMatrix123!")
            page.get_by_placeholder("再次输入密码").fill("EduMatrix123!")
            click_button(page, "创建并启动学习")
            complete_onboarding(page)

            page.goto(f"{BASE_URL}/knowledge", wait_until="networkidle")
            course_group = page.locator("section.knowledge-group").filter(has_text=COURSE_TITLE)
            course_group.locator("h3").first.wait_for(state="visible", timeout=15_000)
            assert course_group.locator("h3").first.inner_text() == COURSE_TITLE

            document_count = course_group.locator(".knowledge-card").count()
            readonly_count = course_group.locator('[title="公共课程为只读内容"]').count()
            source_count = course_group.get_by_text("来源：", exact=False).count()
            license_count = course_group.get_by_text("许可：", exact=False).count()
            assert document_count == EXPECTED_DOCUMENTS, document_count
            assert readonly_count == EXPECTED_DOCUMENTS, readonly_count
            assert source_count >= 1, source_count
            assert license_count >= 1, license_count

            report["checks"]["course_group"] = {
                "title_visible": True,
                "document_count": document_count,
                "readonly_count": readonly_count,
                "source_visible": source_count >= 1,
                "license_visible": license_count >= 1,
            }
            report["screenshots"].append(screenshot(page, "02-knowledge-course"))

            first_card = course_group.locator(".knowledge-card").first
            first_title = first_card.locator("h3").inner_text()
            first_card.click()
            modal = page.locator(".knowledge-modal")
            modal.wait_for(state="visible", timeout=10_000)
            modal.get_by_text("预置课程文档", exact=True).wait_for(state="visible")
            modal.get_by_text(COURSE_TITLE, exact=True).wait_for(state="visible")
            modal.get_by_text("文件哈希", exact=True).wait_for(state="visible")
            modal.get_by_text("许可", exact=True).wait_for(state="visible")
            hash_text = modal.locator("dd.font-mono").inner_text()
            assert re.fullmatch(r"[0-9A-Fa-f]{64}", hash_text.strip()), hash_text
            report["checks"]["course_detail"] = {
                "first_document_title": first_title,
                "hash_is_sha256": True,
                "source_and_license_visible": True,
            }
            report["screenshots"].append(screenshot(page, "03-course-detail"))

            report["checks"]["scope"] = {
                "chat_or_external_llm_called": False,
                "pages_visited": ["/login", "/onboarding", "/knowledge"],
            }
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
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            context.close()
            browser.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
