"""F9-T01 lightweight marketplace E2E against an isolated SQLite database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f9_t01_marketplace"
DB_PATH = OUTPUT_DIR / "f9_t01_marketplace.sqlite3"
FIXTURE_PATH = OUTPUT_DIR / "fixture.json"
REPORT_PATH = OUTPUT_DIR / "report.json"
TEST_PASSWORD = "EduMatrix123!"
PORT = int(os.getenv("EDUMATRIX_F9_T01_PORT", "8991"))
VIEWPORTS = ((1440, 900), (1366, 768))
EXPECTED_NAV = ["首页", "个人中心", "学习画像", "学习空间", "智能对话", "知识库", "学习市场", "设置"]


def configure_runtime(db_path: Path, port: int) -> None:
    os.environ.update({
        "EDUMATRIX_DB_PATH": str(db_path),
        "EDUMATRIX_AUTH_SECRET_KEY": "f9-t01-isolated-browser-secret",
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


def clear_output() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)


def prepare_fixture() -> None:
    clear_output()
    configure_runtime(DB_PATH, PORT)
    sys.path.insert(0, str(ROOT))

    from fastapi.testclient import TestClient
    from app.main import app
    from tests.test_f9_t01_marketplace_service import _publish, _seed_marketplace_objects, _submit

    with TestClient(app) as client:
        seeded = _seed_marketplace_objects(client)
        headers = seeded["headers"]
        suffix = str(seeded["suffix"])
        resource = _publish(client, headers["admin"], _submit(
            client,
            headers["publisher"],
            suffix=suffix,
            item_type="resource",
            source_object_id=str(seeded["artifact_id"]),
            source_version_id=str(seeded["artifact_version_id"]),
        ))
        learning_path = _publish(client, headers["admin"], _submit(
            client,
            headers["publisher"],
            suffix=suffix,
            item_type="learning_path",
            source_object_id=str(seeded["path_id"]),
            source_version_id=str(seeded["path_version_id"]),
        ))

    fixture = {
        "suffix": suffix,
        "course_id": seeded["course_id"],
        "bundle_id": seeded["bundle_id"],
        "bundle_version_id": seeded["bundle_version_id"],
        "usernames": {
            role: f"f9_market_{role}_{suffix}"
            for role in ("publisher", "admin", "learner", "outsider")
        },
        "published_listings": {
            "resource": resource,
            "learning_path": learning_path,
        },
    }
    FIXTURE_PATH.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "prepared", "database": str(DB_PATH), "suffix": suffix}, ensure_ascii=False))


def api_login(request, base_url: str, username: str) -> dict:
    response = request.post(
        f"{base_url}/api/auth/login",
        form={"username": username, "password": TEST_PASSWORD},
    )
    assert response.ok, f"login failed for {username}: {response.status} {response.text()}"
    return response.json()


def auth_headers(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


def api_post(request, base_url: str, session: dict, path: str, body: dict, expected: int = 200) -> dict:
    response = request.post(f"{base_url}{path}", headers=auth_headers(session), data=body)
    assert response.status == expected, f"POST {path}: {response.status} {response.text()}"
    return response.json()


def add_session(context: BrowserContext, session: dict, fixture: dict) -> None:
    public_session = {
        "access_token": session["access_token"],
        "username": session.get("username") or "anonymous-student",
        "display_name": session.get("display_name") or session.get("username") or "匿名学生",
        "role": session.get("role") or "student",
        "student_id": session.get("student_id") or session.get("username") or "anonymous-student",
        "course_id": fixture["course_id"],
    }
    context.add_init_script(script=f"""
      const session = {json.dumps(public_session, ensure_ascii=False)};
      localStorage.setItem('edumatrix_token', session.access_token);
      localStorage.setItem('edumatrix_username', session.username);
      localStorage.setItem('edumatrix_display_name', session.display_name);
      localStorage.setItem('edumatrix_role', session.role);
      localStorage.setItem('edumatrix_student_id', session.student_id);
      localStorage.setItem('edumatrix_onboarded', 'true');
      localStorage.setItem('edumatrix_course_id', session.course_id);
      localStorage.setItem('edumatrix_course_title', '机器学习工程实践');
    """)


def browser_context(browser: Browser, base_url: str, username: str, fixture: dict, viewport: tuple[int, int]):
    context = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        locale="zh-CN",
        color_scheme="light",
    )
    session = api_login(context.request, base_url, username)
    add_session(context, session, fixture)
    page = context.new_page()
    return context, page, session


def attach_diagnostics(page: Page, report: dict) -> None:
    page_report = {
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "off_origin_requests": [],
        "request_lifecycle": [],
    }
    report["browser_pages"].append(page_report)
    pending_requests: dict[int, dict[str, object]] = {}

    def local_request_key(request) -> tuple[str, str] | None:
        parsed = urlparse(request.url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
            return None
        url = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return request.method, url

    def local_request_entry(request) -> dict[str, object] | None:
        key = local_request_key(request)
        if key is None:
            return None
        method, url = key
        return {"method": method, "url": url, "status": None, "pending": True}

    def pop_pending(request) -> dict[str, object] | None:
        entry = pending_requests.pop(id(request), None)
        if entry is not None:
            return entry
        key = local_request_key(request)
        if key is None:
            return None
        method, url = key
        matching_id = next(
            (
                request_id
                for request_id, candidate in pending_requests.items()
                if candidate["method"] == method and candidate["url"] == url
            ),
            None,
        )
        return pending_requests.pop(matching_id, None) if matching_id is not None else None

    def on_response(response) -> None:
        entry = pop_pending(response.request)
        if entry is not None:
            entry["status"] = response.status
            entry["pending"] = False
        if response.status >= 400:
            page_report["http_errors"].append({"status": response.status, "url": response.url})

    def on_request(request) -> None:
        parsed = urlparse(request.url)
        if parsed.scheme in {"http", "https"} and parsed.hostname not in {"127.0.0.1", "localhost"}:
            page_report["off_origin_requests"].append(request.url)
            return
        entry = local_request_entry(request)
        if entry is not None:
            page_report["request_lifecycle"].append(entry)
            pending_requests[id(request)] = entry

    def on_failed(request) -> None:
        entry = pop_pending(request)
        if entry is not None:
            entry["pending"] = False
        if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"}:
            page_report["failed_requests"].append({"url": request.url, "failure": request.failure})

    page.on("response", on_response)
    page.on("request", on_request)
    page.on("requestfailed", on_failed)
    page.on("pageerror", lambda error: page_report["page_errors"].append(str(error)))
    page.on("console", lambda message: page_report["console_errors"].append(message.text) if message.type == "error" else None)


def database_digest(db_path: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    with sqlite3.connect(db_path, timeout=20) as db:
        tables = [
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        for table in tables:
            rows = db.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            raw = json.dumps(rows, ensure_ascii=False, default=str, separators=(",", ":"))
            result[table] = {
                "count": len(rows),
                "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            }
    return result


def learning_state(db_path: Path) -> dict[str, dict[str, object]]:
    full = database_digest(db_path)
    return {name: full[name] for name in ("learning_events", "profile_snapshots")}


def database_audit(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=20) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        }


def visible_metrics(page: Page) -> dict:
    return page.evaluate("""() => {
      const visible = (el) => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1;
      };
      const controls = [...document.querySelectorAll('button,a[href],input,select,textarea')].filter(visible);
      const collisions = [];
      for (let i = 0; i < controls.length; i += 1) for (let j = i + 1; j < controls.length; j += 1) {
        const a = controls[i], b = controls[j];
        if (a.contains(b) || b.contains(a)) continue;
        const x = a.getBoundingClientRect(), y = b.getBoundingClientRect();
        const overlapW = Math.min(x.right, y.right) - Math.max(x.left, y.left);
        const overlapH = Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top);
        if (overlapW > 3 && overlapH > 3) collisions.push([
          (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 48),
          (b.innerText || b.getAttribute('aria-label') || '').trim().slice(0, 48),
        ]);
      }
      const textNodes = [...document.querySelectorAll('button,a[href],h1,h2,h3,strong,p,span,label,small')]
        .filter(visible).filter((el) => (el.innerText || '').trim());
      const clipped = textNodes.filter((el) => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        if (style.textOverflow === 'ellipsis') return false;
        return rect.right > innerWidth + 1 || rect.left < -1 ||
          (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap');
      }).map((el) => (el.innerText || '').trim().slice(0, 80)).slice(0, 20);
      const smallText = textNodes.filter((el) => Number.parseFloat(getComputedStyle(el).fontSize) < 13.5)
        .map((el) => ({ text: el.innerText.trim().slice(0, 48), size: getComputedStyle(el).fontSize })).slice(0, 20);
      const parseRgb = (value) => {
        const match = value.match(/[\d.]+/g);
        return match && match.length >= 3 ? match.slice(0, 3).map(Number) : null;
      };
      const luminance = (rgb) => {
        const values = rgb.map((value) => {
          const normalized = value / 255;
          return normalized <= .03928 ? normalized / 12.92 : ((normalized + .055) / 1.055) ** 2.4;
        });
        return .2126 * values[0] + .7152 * values[1] + .0722 * values[2];
      };
      const lowContrastPrimary = [...document.querySelectorAll('.primary-button,.publish-button')].filter(visible).map((el) => {
        const style = getComputedStyle(el), foreground = parseRgb(style.color), background = parseRgb(style.backgroundColor);
        if (!foreground || !background) return null;
        const high = Math.max(luminance(foreground), luminance(background));
        const low = Math.min(luminance(foreground), luminance(background));
        return { text: (el.innerText || '').trim().slice(0, 48), ratio: (high + .05) / (low + .05) };
      }).filter((item) => item && item.ratio < 4.5);
      const forbiddenEffects = [...document.querySelectorAll('body *')].filter(visible).filter((el) => {
        const style = getComputedStyle(el);
        return style.backgroundImage.includes('gradient') || (style.backdropFilter && style.backdropFilter !== 'none');
      }).map((el) => String(el.className).slice(0, 80)).slice(0, 20);
      const themedColorRegression = [...document.querySelectorAll('body *')].filter(visible).filter((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.width * rect.height < 3000) return false;
        const rgb = parseRgb(getComputedStyle(el).backgroundColor);
        if (!rgb) return false;
        const [r, g, b] = rgb.map((value) => value / 255);
        const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
        const light = (max + min) / 2;
        const saturation = delta === 0 ? 0 : delta / (1 - Math.abs(2 * light - 1));
        let hue = 0;
        if (delta) {
          if (max === r) hue = 60 * (((g - b) / delta) % 6);
          else if (max === g) hue = 60 * ((b - r) / delta + 2);
          else hue = 60 * ((r - g) / delta + 4);
          if (hue < 0) hue += 360;
        }
        const green = hue >= 70 && hue <= 170 && saturation > .2;
        const brown = hue >= 15 && hue <= 50 && saturation > .28 && light < .7;
        const lightBlue = hue > 170 && hue <= 220 && saturation > .22 && light > .62;
        const bluePurple = hue > 220 && hue <= 300 && saturation > .3;
        return green || brown || lightBlue || bluePurple;
      }).map((el) => ({ className: String(el.className).slice(0, 80), color: getComputedStyle(el).backgroundColor })).slice(0, 20);
      return {
        viewport: [innerWidth, innerHeight],
        documentWidth: document.documentElement.scrollWidth,
        bodyTextLength: (document.body.innerText || '').trim().length,
        collisions, clipped, smallText, lowContrastPrimary, forbiddenEffects, themedColorRegression,
      };
    }""")


def capture(page: Page, report: dict, name: str) -> None:
    page.evaluate("""() => {
      window.scrollTo(0, 0);
      const content = document.querySelector('.app-content');
      if (content) content.scrollTo(0, 0);
    }""")
    page.wait_for_timeout(300)
    metrics = visible_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["visual_checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] > 150, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["lowContrastPrimary"], metrics
    assert not metrics["forbiddenEffects"], metrics
    assert not metrics["themedColorRegression"], metrics


def goto(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        # EduMatrix keeps bounded background requests active; surface selectors
        # and loading-state checks below are the authoritative readiness gate.
        pass


def wait_market(page: Page) -> None:
    try:
        page.get_by_test_id("marketplace-workspace").wait_for(state="visible")
    except PlaywrightTimeoutError as exception:
        diagnostic = page.evaluate("""() => ({
          url: location.href,
          title: document.title,
          role: localStorage.getItem('edumatrix_role'),
          onboarded: localStorage.getItem('edumatrix_onboarded'),
          hasToken: Boolean(localStorage.getItem('edumatrix_token')),
          body: (document.body.innerText || '').trim().slice(0, 1200),
          testIds: [...document.querySelectorAll('[data-testid]')]
            .map((el) => el.getAttribute('data-testid')).filter(Boolean).slice(0, 80),
        })""")
        (OUTPUT_DIR / "mount_failure.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(OUTPUT_DIR / "mount_failure.png"), full_page=True, animations="disabled")
        raise AssertionError(json.dumps(diagnostic, ensure_ascii=False)) from exception
    page.locator(".loading-surface").wait_for(state="hidden")


def open_listing(page: Page, base_url: str, listing: dict) -> None:
    goto(page, f"{base_url}/marketplace/items/{listing['id']}")
    wait_market(page)
    page.get_by_test_id("marketplace-preview").get_by_role("heading", name=listing["title"]).wait_for(state="visible")


def run_publisher_journey(
    browser: Browser,
    base_url: str,
    fixture: dict,
    report: dict,
) -> tuple[dict, dict]:
    context, page, publisher_session = browser_context(
        browser, base_url, fixture["usernames"]["publisher"], fixture, VIEWPORTS[0]
    )
    attach_diagnostics(page, report)
    goto(page, f"{base_url}/marketplace/publish")
    wait_market(page)
    wizard = page.get_by_test_id("marketplace-publish-wizard")
    wizard.wait_for(state="visible")
    capture(page, report, "1440_01_publish_step_1.png")

    wizard.locator(".publish-type-grid label").filter(has_text="资源包").click()
    wizard.get_by_role("button", name="下一步").click()
    source = wizard.locator(".source-list button").filter(has_text="监督学习完整资源包")
    source.wait_for(state="visible")
    source.click()
    title = f"F9 浏览器资源包 {fixture['suffix']}"
    wizard.get_by_label("发布标题").fill(title)
    wizard.get_by_label("分类").fill("人工智能")
    wizard.get_by_label("标签").fill(f"F9,{fixture['suffix']},资源包")
    wizard.get_by_label("分享说明").fill("冻结来源的资源包，可预览、保存并从个人学习空间继续使用。")
    assert "来源信息完整" in wizard.inner_text()
    capture(page, report, "1440_02_publish_step_2.png")

    wizard.get_by_role("button", name="下一步").click()
    page.get_by_text("发布前确认", exact=True).wait_for(state="visible")
    review_text = wizard.inner_text()
    assert "CC BY 4.0" in review_text and "演示数据" in review_text
    capture(page, report, "1440_03_publish_step_3.png")

    with page.expect_response(lambda response: (
        response.request.method == "POST" and response.url.endswith("/api/v1/marketplace/listings")
    )) as response_info:
        wizard.get_by_role("button", name="提交公开审核").click()
    response = response_info.value
    assert response.status == 201, response.text()
    listing = response.json()
    page.get_by_role("heading", name="已提交公开审核").wait_for(state="visible")
    capture(page, report, "1440_04_publish_complete.png")

    page.get_by_role("button", name="查看我的发布").click()
    page.wait_for_url("**/marketplace/mine")
    page.get_by_test_id("marketplace-mine").wait_for(state="visible")
    page.get_by_role("button", name="我的发布").click()
    page.locator(".mine-row").filter(has_text=title).wait_for(state="visible")
    capture(page, report, "1440_05_publisher_mine.png")
    context.close()
    return listing, publisher_session


def publish_with_admin(request, base_url: str, fixture: dict, listing: dict) -> tuple[dict, dict]:
    admin_session = api_login(request, base_url, fixture["usernames"]["admin"])
    approved = api_post(
        request,
        base_url,
        admin_session,
        f"/api/v1/marketplace/listings/{listing['id']}/decisions",
        {
            "action": "approve",
            "reason": "冻结来源、许可证和公开预览已经通过浏览器专项审核",
            "expected_version": listing["lock_version"],
        },
    )
    published = api_post(
        request,
        base_url,
        admin_session,
        f"/api/v1/marketplace/listings/{listing['id']}/decisions",
        {
            "action": "publish",
            "reason": "批准在轻量学习市场中公开展示并保存个人副本",
            "expected_version": approved["lock_version"],
        },
    )
    return published, admin_session


def verify_navigation(page: Page) -> None:
    nav = page.locator(".app-nav .sidebar-item")
    assert nav.count() == 8, nav.all_inner_texts()
    actual = [" ".join(text.split()) for text in nav.all_inner_texts()]
    for expected, text in zip(EXPECTED_NAV, actual, strict=True):
        assert expected in text, actual
    market_item = nav.filter(has_text="学习市场")
    assert "active" in (market_item.get_attribute("class") or ""), market_item.get_attribute("class")


def exercise_read_only_market(page: Page, base_url: str, fixture: dict, report: dict) -> None:
    goto(page, f"{base_url}/marketplace")
    wait_market(page)
    verify_navigation(page)
    capture(page, report, "1440_06_market_discovery.png")
    before = database_digest(DB_PATH)

    search = page.get_by_label("搜索学习市场")
    search.fill(fixture["suffix"])
    search.press("Enter")
    page.locator(".market-row").first.wait_for(state="visible")
    category = page.get_by_label("课程分类")
    category.select_option(label="人工智能")
    page.locator(".market-row").first.wait_for(state="visible")

    expected = (
        ("单份资源", fixture["published_listings"]["resource"]),
        ("资源包", fixture["published_listings"]["resource_bundle"]),
        ("学习路径", fixture["published_listings"]["learning_path"]),
    )
    for label, listing in expected:
        page.get_by_role("button", name=label, exact=True).click()
        row = page.locator(".market-row").filter(has_text=listing["title"])
        row.wait_for(state="visible")
        row.click()
        page.wait_for_url(f"**/marketplace/items/{listing['id']}")
        preview = page.get_by_test_id("marketplace-preview")
        preview.get_by_role("heading", name=listing["title"]).wait_for(state="visible")
        text = preview.inner_text()
        assert "来源与许可" in text and "CC BY 4.0" in text
        goto(page, f"{base_url}/marketplace")
        wait_market(page)
        search = page.get_by_label("搜索学习市场")
        search.fill(fixture["suffix"])
        search.press("Enter")

    after = database_digest(DB_PATH)
    assert after == before, "ordinary marketplace discovery changed persisted business tables"
    report["ordinary_browse_database_unchanged"] = True


def save_and_open(page: Page, base_url: str, listing: dict, destination_test_id: str) -> dict:
    open_listing(page, base_url, listing)
    with page.expect_response(lambda response: (
        response.request.method == "POST"
        and response.url.endswith(f"/api/v1/marketplace/listings/{listing['id']}/acquisitions")
    )) as response_info:
        page.get_by_role("button", name="保存到学习空间").click()
    response = response_info.value
    assert response.status == 201, response.text()
    copy = response.json()
    page.get_by_role("button", name="打开个人副本").wait_for(state="visible")
    page.get_by_role("button", name="打开个人副本").click()
    page.get_by_test_id(destination_test_id).wait_for(state="visible", timeout=30_000)
    return copy


def run_learner_journey(
    browser: Browser,
    base_url: str,
    fixture: dict,
    report: dict,
    admin_session: dict,
) -> dict:
    context, page, learner_session = browser_context(
        browser, base_url, fixture["usernames"]["learner"], fixture, VIEWPORTS[0]
    )
    attach_diagnostics(page, report)
    learning_before = learning_state(DB_PATH)
    exercise_read_only_market(page, base_url, fixture, report)

    bundle_listing = fixture["published_listings"]["resource_bundle"]
    open_listing(page, base_url, bundle_listing)
    capture(page, report, "1440_07_bundle_preview.png")
    bundle_copy = save_and_open(page, base_url, bundle_listing, "resource-bundle-workspace")
    assert page.url.endswith(f"/workspace/resources/bundles/{bundle_copy['copy_object_id']}?mode=personal-copy")
    capture(page, report, "1440_08_bundle_personal_copy.png")

    path_listing = fixture["published_listings"]["learning_path"]
    path_copy = save_and_open(page, base_url, path_listing, "path-overview")
    assert f"path_id={path_copy['copy_object_id']}" in page.url
    assert "理解损失函数" in page.get_by_test_id("path-overview").inner_text()
    capture(page, report, "1440_09_path_personal_copy.png")

    withdrawn = api_post(
        context.request,
        base_url,
        admin_session,
        f"/api/v1/marketplace/listings/{bundle_listing['id']}/decisions",
        {
            "action": "withdraw",
            "reason": "验证上游下架后个人副本仍保持独立可用",
            "expected_version": bundle_listing["lock_version"],
        },
    )
    assert withdrawn["status"] == "withdrawn"

    outsider_session = api_login(context.request, base_url, fixture["usernames"]["outsider"])
    blocked = context.request.post(
        f"{base_url}/api/v1/marketplace/listings/{bundle_listing['id']}/acquisitions",
        headers=auth_headers(outsider_session),
        data={},
    )
    assert blocked.status == 422, f"withdrawn listing save was not blocked: {blocked.status}"

    goto(page, f"{base_url}/marketplace/mine")
    page.get_by_test_id("marketplace-mine").wait_for(state="visible")
    bundle_row = page.locator(".mine-row").filter(has_text=bundle_listing["title"])
    bundle_row.wait_for(state="visible")
    assert "来源已下架，个人副本仍可继续使用" in bundle_row.inner_text()
    capture(page, report, "1440_10_withdrawn_copy_available.png")
    bundle_row.get_by_role("button", name="打开个人副本").click()
    page.get_by_test_id("resource-bundle-workspace").wait_for(state="visible", timeout=30_000)

    learning_after = learning_state(DB_PATH)
    assert learning_after == learning_before, "publication or save changed learning events/profile snapshots"
    report["learning_state_unchanged_after_publish_and_save"] = True
    context.close()
    return {
        "learner_session": learner_session,
        "outsider_session": outsider_session,
        "bundle_copy": bundle_copy,
        "path_copy": path_copy,
    }


def run_outsider_path_check(browser: Browser, base_url: str, fixture: dict, report: dict, path_copy: dict) -> None:
    context, page, _ = browser_context(
        browser, base_url, fixture["usernames"]["outsider"], fixture, VIEWPORTS[0]
    )
    attach_diagnostics(page, report)
    goto(page, f"{base_url}/workspace/path?path_id={path_copy['copy_object_id']}")
    error = page.get_by_test_id("path-error")
    error.wait_for(state="visible", timeout=30_000)
    assert "这条个人学习路径不存在或不属于当前账号" in error.inner_text()
    capture(page, report, "1440_11_outsider_path_denied.png")
    context.close()


def run_compact_viewport_checks(browser: Browser, base_url: str, fixture: dict, report: dict, copies: dict) -> None:
    learner_context, learner_page, _ = browser_context(
        browser, base_url, fixture["usernames"]["learner"], fixture, VIEWPORTS[1]
    )
    attach_diagnostics(learner_page, report)
    open_listing(learner_page, base_url, fixture["published_listings"]["learning_path"])
    capture(learner_page, report, "1366_01_market_preview.png")
    goto(learner_page, f"{base_url}/marketplace/mine")
    learner_page.get_by_test_id("marketplace-mine").wait_for(state="visible")
    capture(learner_page, report, "1366_02_market_mine.png")
    goto(learner_page, f"{base_url}{copies['bundle_copy']['open_route']}")
    learner_page.get_by_test_id("resource-bundle-workspace").wait_for(state="visible")
    capture(learner_page, report, "1366_03_bundle_personal_copy.png")
    goto(learner_page, f"{base_url}{copies['path_copy']['open_route']}")
    learner_page.get_by_test_id("path-overview").wait_for(state="visible", timeout=30_000)
    capture(learner_page, report, "1366_04_path_personal_copy.png")
    learner_context.close()

    publisher_context, publisher_page, _ = browser_context(
        browser, base_url, fixture["usernames"]["publisher"], fixture, VIEWPORTS[1]
    )
    attach_diagnostics(publisher_page, report)
    goto(publisher_page, f"{base_url}/marketplace/publish")
    wait_market(publisher_page)
    wizard = publisher_page.get_by_test_id("marketplace-publish-wizard")
    wizard.locator(".publish-type-grid label").filter(has_text="资源包").click()
    wizard.get_by_role("button", name="下一步").click()
    wizard.locator(".source-list button").filter(has_text="监督学习完整资源包").click()
    wizard.get_by_label("发布标题").fill(f"F9 紧凑桌面预览 {fixture['suffix']}")
    wizard.get_by_label("分享说明").fill("紧凑桌面只验证布局与状态，不重复提交公开审核。")
    capture(publisher_page, report, "1366_05_publish_step_2.png")
    publisher_context.close()


def assert_browser_clean(report: dict) -> None:
    for page_report in report["browser_pages"]:
        assert not page_report["http_errors"], page_report
        assert not page_report["failed_requests"], page_report
        assert not page_report["page_errors"], page_report
        assert not page_report["console_errors"], page_report
        assert not page_report["off_origin_requests"], page_report


def write_manifest() -> None:
    files = []
    for path in sorted(OUTPUT_DIR.iterdir()):
        if not path.is_file() or path.name == "manifest.json":
            continue
        files.append({
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    (OUTPUT_DIR / "manifest.json").write_text(
        json.dumps({"files": files}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_e2e(playwright: Playwright, base_url: str) -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    report = {
        "task": "F9-T01",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "viewports": [list(item) for item in VIEWPORTS],
        "screenshots": [],
        "visual_checks": {},
        "browser_pages": [],
        "ordinary_browse_database_unchanged": False,
        "learning_state_unchanged_after_publish_and_save": False,
        "external_model_called": False,
    }
    browser = playwright.chromium.launch(headless=True)
    try:
        bundle_listing, _ = run_publisher_journey(browser, base_url, fixture, report)
        admin_context = browser.new_context()
        try:
            published_bundle, admin_session = publish_with_admin(
                admin_context.request, base_url, fixture, bundle_listing
            )
        finally:
            admin_context.close()
        fixture["published_listings"]["resource_bundle"] = published_bundle
        copies = run_learner_journey(browser, base_url, fixture, report, admin_session)
        run_outsider_path_check(browser, base_url, fixture, report, copies["path_copy"])
        run_compact_viewport_checks(browser, base_url, fixture, report, copies)
        assert_browser_clean(report)
        audit = database_audit(DB_PATH)
        assert audit["integrity"] == "ok", audit
        assert audit["foreign_key_violations"] == 0, audit
        report["database_audit"] = audit
        report["copies"] = {
            "bundle": {key: copies["bundle_copy"][key] for key in ("id", "copy_object_id", "copy_version_id", "open_route")},
            "learning_path": {key: copies["path_copy"][key] for key in ("id", "copy_object_id", "copy_version_id", "open_route")},
        }
        report["published_listing_ids"] = {
            key: value["id"] for key, value in fixture["published_listings"].items()
        }
        report["status"] = "passed"
    except Exception as exception:
        report["status"] = "failed"
        report["failure"] = {
            "type": type(exception).__name__,
            "message": str(exception),
        }
        raise
    finally:
        browser.close()
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        write_manifest()
    print(json.dumps({
        "status": report["status"],
        "screenshots": len(report["screenshots"]),
        "database": report.get("database_audit"),
        "external_model_called": report["external_model_called"],
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    configure_runtime(DB_PATH, args.port)
    if args.prepare:
        prepare_fixture()
        return
    base_url = f"http://127.0.0.1:{args.port}"
    with sync_playwright() as playwright:
        run_e2e(playwright, base_url)


if __name__ == "__main__":
    main()
