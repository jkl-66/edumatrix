from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "post_ui_fixes" / "POST-UI-14_browser"
EVIDENCE.mkdir(parents=True, exist_ok=True)


def check_landing(page, viewport, screenshot_name):
    console_errors = []
    page_errors = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.set_viewport_size(viewport)
    page.goto("http://127.0.0.1:5173/landing", wait_until="networkidle")
    page.locator(".landing-page").wait_for()

    assert page.get_by_text("查看闭环依据", exact=True).count() == 0
    assert page.locator(".landing-page section").count() >= 8
    assert page.locator('button:has-text("开启学习旅程")').count() == 1
    assert page.locator(".landing-page").evaluate("element => element.scrollHeight > window.innerHeight * 2")
    assert page.locator(".landing-page").evaluate("element => element.scrollWidth <= element.clientWidth + 1")

    page.locator('button:has-text("开启学习旅程")').click()
    page.wait_for_url("**/login")
    assert page.url.endswith("/login")
    page.goto("http://127.0.0.1:5173/landing", wait_until="networkidle")
    page.locator('.landing-header__entry').focus()
    assert page.locator('.landing-header__entry:focus-visible').count() == 1
    page.screenshot(path=str(EVIDENCE / screenshot_name), full_page=True)
    page.locator('.landing-page').evaluate("element => element.scrollTo(0, Math.floor(element.scrollHeight * 0.42))")
    page.wait_for_timeout(700)
    assert page.locator('.landing-page').evaluate("element => element.scrollTop > 0")
    page.screenshot(path=str(EVIDENCE / screenshot_name.replace('.png', '-scroll.png')))

    assert not console_errors, f"console errors: {console_errors}"
    assert not page_errors, f"page errors: {page_errors}"


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    check_landing(page, {"width": 1440, "height": 900}, "landing-1440x900.png")
    check_landing(page, {"width": 1366, "height": 768}, "landing-1366x768.png")
    browser.close()

print("POST-UI-14 landing browser checks passed")
