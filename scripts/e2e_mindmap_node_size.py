"""Focused Chromium evidence for enlarged mindmap resource nodes."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/原系统融合重构执行/evidence/custom_tasks/MINDMAP-NODE-SIZE-01/browser"
BASE_URL = "http://127.0.0.1:5173"
RESOURCE_ID = "art-f8f45054e057445d8a41531e5da9dec3"
COURSE_ID = "course-machine-learning-foundations-v1"


def node_geometry(page, scope: str) -> dict[str, object]:
    boxes = page.locator(f"{scope} .mindmap-node__rect").evaluate_all(
        """elements => elements.map(element => {
          const box = element.getBoundingClientRect();
          return { left: box.left, right: box.right, top: box.top, bottom: box.bottom,
                   width: box.width, height: box.height };
        })"""
    )
    overlaps = 0
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            if (
                first["left"] < second["right"]
                and first["right"] > second["left"]
                and first["top"] < second["bottom"]
                and first["bottom"] > second["top"]
            ):
                overlaps += 1
    return {"count": len(boxes), "boxes": boxes, "overlaps": overlaps}


def login(page) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
    page.get_by_test_id("login-username").fill("lzz")
    page.get_by_test_id("login-password").fill("404404aA")
    page.get_by_role("button", name="登录", exact=True).click()
    page.wait_for_url(lambda url: "/login" not in url, timeout=20_000)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"taskId": "MINDMAP-NODE-SIZE-01", "viewports": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
                page = context.new_page()
                page_errors: list[str] = []
                failed_requests: list[dict[str, str | None]] = []
                http_errors: list[dict[str, object]] = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.on(
                    "requestfailed",
                    lambda request: failed_requests.append(
                        {"url": request.url, "failure": request.failure}
                    ),
                )
                page.on(
                    "response",
                    lambda response: http_errors.append(
                        {"url": response.url, "status": response.status}
                    )
                    if response.status >= 400
                    else None,
                )
                login(page)
                page.wait_for_load_state("networkidle")
                # Ignore requests cancelled by the post-login navigation itself; the
                # acceptance scope starts when the mindmap resource route is opened.
                page_errors.clear()
                failed_requests.clear()
                http_errors.clear()
                page.goto(
                    f"{BASE_URL}/workspace/resources/mindmaps/{RESOURCE_ID}?course_id={COURSE_ID}",
                    wait_until="networkidle",
                )
                page.get_by_test_id("mindmap-workspace").wait_for(state="visible", timeout=20_000)
                page.locator(".mindmap-node").first.wait_for(state="visible")
                page.locator(".mindmap-toolbar").get_by_role("button", name="展开", exact=True).click()
                page.wait_for_timeout(400)

                embedded = node_geometry(page, ".mindmap-card")
                assert embedded["count"] >= 2
                assert embedded["overlaps"] == 0, embedded
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                embedded_path = OUTPUT / f"{width}x{height}-embedded.png"
                page.screenshot(path=embedded_path, full_page=True, animations="disabled")

                page.get_by_role("button", name="放大/全屏", exact=True).click()
                page.locator(".mindmap-modal").wait_for(state="visible")
                page.wait_for_timeout(400)
                fullscreen = node_geometry(page, ".mindmap-modal")
                assert fullscreen["count"] == embedded["count"]
                assert fullscreen["overlaps"] == 0, fullscreen
                fullscreen_path = OUTPUT / f"{width}x{height}-fullscreen.png"
                page.screenshot(path=fullscreen_path, full_page=True, animations="disabled")

                unexpected_failures = [
                    item for item in failed_requests if item["failure"] != "net::ERR_ABORTED"
                ]

                report["viewports"].append(
                    {
                        "viewport": f"{width}x{height}",
                        "embedded": embedded,
                        "fullscreen": fullscreen,
                        "pageErrors": page_errors,
                        "failedRequests": failed_requests,
                        "httpErrors": http_errors,
                        "screenshots": [embedded_path.name, fullscreen_path.name],
                    }
                )
                assert not page_errors, page_errors
                assert not unexpected_failures, unexpected_failures
                assert not http_errors, http_errors
                context.close()
        finally:
            browser.close()
    (OUTPUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
