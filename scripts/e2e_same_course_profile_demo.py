from __future__ import annotations

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "profile_demo_accounts" / "browser"
OUT.mkdir(parents=True, exist_ok=True)
FRONTEND = "http://127.0.0.1:9016"
BACKEND = "http://127.0.0.1:8000"
COURSE_ID = "course-machine-learning-foundations-v1"

accounts = json.loads((ROOT / "outputs" / "profile_demo_accounts" / "accounts.json").read_text(encoding="utf-8"))["accounts"]


def safe_name(value: str) -> str:
    return value.replace("profile_demo_", "").replace(" ", "-")


report = {"task_id": "PROFILE-DEMO-ACCOUNTS-01", "viewport": {"width": 1920, "height": 1080}, "accounts": [], "errors": []}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for account in accounts:
        name = safe_name(account["username"])
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page = context.new_page()
        errors: list[str] = []
        page.on("console", lambda msg: errors.append(f"console:{msg.type}:{msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda err: errors.append(f"page:{err}"))
        page.on("requestfailed", lambda req: errors.append(f"request:{req.method}:{req.url}:{req.failure}"))
        row = {"username": account["username"], "screenshots": [], "routes": {}, "errors": errors}
        try:
            page.goto(FRONTEND + "/login", wait_until="networkidle", timeout=30_000)
            page.get_by_test_id("login-username").fill(account["username"])
            page.get_by_test_id("login-password").fill(account["password"])
            page.get_by_test_id("login-submit").click()
            page.wait_for_timeout(1800)
            row["routes"]["after_login"] = page.url
            page.goto(FRONTEND + f"/profile/learning?course_id={COURSE_ID}", wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(1000)
            body = page.locator("body").inner_text()
            row["routes"]["profile"] = {"url": page.url, "has_course": "机器学习基础与实践" in body, "has_major": account["profile"]["major"] in body, "text_excerpt": body[:2400]}
            path = OUT / f"{name}-profile-1920.png"
            page.screenshot(path=str(path), full_page=False)
            row["screenshots"].append(str(path.relative_to(ROOT)).replace("\\", "/"))

            page.goto(FRONTEND + f"/workspace/resources?course_id={COURSE_ID}", wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(1000)
            body = page.locator("body").inner_text()
            row["routes"]["resources"] = {"url": page.url, "resource_count_visible": body.count("个性化讲义") + body.count("思维导图"), "has_adaptation": any(k in body for k in ("入门巩固", "进阶迁移", "基础应用", "按你的学习情况")), "text_excerpt": body[:2600]}
            path = OUT / f"{name}-resources-1920.png"
            page.screenshot(path=str(path), full_page=False)
            row["screenshots"].append(str(path.relative_to(ROOT)).replace("\\", "/"))

            handout = next((rid for rid in account["resource_ids"] if rid.endswith("-resource-handout")), "")
            page.goto(FRONTEND + f"/workspace/resources/handouts/{handout}?course_id={COURSE_ID}", wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(1000)
            body = page.locator("body").inner_text()
            row["routes"]["handout"] = {"url": page.url, "has_title": "决策树分类" in body, "has_profile_effect": account["profile"]["adaptation"] in body or account["profile"]["style"] in body, "text_excerpt": body[:3000]}
            path = OUT / f"{name}-handout-1920.png"
            page.screenshot(path=str(path), full_page=False)
            row["screenshots"].append(str(path.relative_to(ROOT)).replace("\\", "/"))

            conversation = account["conversation_id"]
            page.goto(FRONTEND + f"/learn?conversation_id={conversation}", wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(1200)
            body = page.locator("body").inner_text()
            row["routes"]["chat"] = {"url": page.url, "has_question": "请结合《机器学习基础与实践》讲解决策树分类" in body, "has_answer": any(k in body for k in ("决策树分类可以这样理解", "if/else", "max_depth", "基尼不纯度")), "has_course": "机器学习基础与实践" in body, "text_excerpt": body[-4200:]}
            path = OUT / f"{name}-chat-1920.png"
            page.screenshot(path=str(path), full_page=False)
            row["screenshots"].append(str(path.relative_to(ROOT)).replace("\\", "/"))
        except Exception as exc:
            row["fatal_error"] = f"{type(exc).__name__}: {exc}"
            report["errors"].append(row["fatal_error"])
        finally:
            context.close()
        report["accounts"].append(row)
    browser.close()

report["status"] = "passed" if not report["errors"] and all(not row.get("fatal_error") for row in report["accounts"]) else "failed"
(OUT / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"status": report["status"], "accounts": len(report["accounts"]), "screenshots": sum(len(row["screenshots"]) for row in report["accounts"]), "errors": report["errors"]}, ensure_ascii=False, indent=2))
