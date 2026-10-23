"""Desktop browser acceptance for F2-T01 unified learning context identity."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("EDUMATRIX_E2E_BASE_URL", "http://127.0.0.1:8892").rstrip("/")
OUTPUT_DIR = Path(
    os.getenv(
        "EDUMATRIX_E2E_OUTPUT_DIR",
        str(
            ROOT
            / "outputs"
            / "原系统融合重构执行"
            / "evidence"
            / "f2_t01_browser_e2e"
        ),
    )
).resolve()
DB_PATH = Path(os.environ["EDUMATRIX_DB_PATH"]).resolve()
COURSE_ID = "demo-course-rag-trust-v1"
COURSE_TITLE = "人工智能与机器学习工程"
PASSWORD = "F2-context-acceptance-2026!"
VIEWPORTS = ((1440, 900), (1366, 768))


def ensure_workspace_path(path: Path) -> None:
    root = ROOT.resolve()
    if path != root and root not in path.parents:
        raise RuntimeError(f"Refusing to modify evidence outside workspace: {path}")


def reset_evidence() -> None:
    ensure_workspace_path(OUTPUT_DIR)
    ensure_workspace_path(DB_PATH)
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def register_admin(page: Page, username: str) -> dict[str, Any]:
    response = page.request.post(
        f"{BASE_URL}/api/auth/register",
        data={
            "username": username,
            "password": PASSWORD,
            "display_name": "F2 上下文验收管理员",
        },
    )
    if not response.ok:
        raise AssertionError(f"register admin failed: {response.status} {response.text()}")
    deadline = time.monotonic() + 20
    while True:
        try:
            with sqlite3.connect(DB_PATH) as database:
                table = database.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
                ).fetchone()
                user = (
                    database.execute(
                        "SELECT public_id FROM users WHERE username=?", (username,)
                    ).fetchone()
                    if table
                    else None
                )
                if user:
                    database.execute(
                        "UPDATE users SET role='admin' WHERE username=?", (username,)
                    )
                    database.commit()
                    break
        except sqlite3.OperationalError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"registered admin did not appear in isolated database: {DB_PATH}"
            )
        time.sleep(0.2)
    return login(page, username, PASSWORD)


def login(page: Page, username: str, password: str) -> dict[str, Any]:
    response = page.request.post(
        f"{BASE_URL}/api/auth/login",
        form={"username": username, "password": password},
    )
    if not response.ok:
        raise AssertionError(f"login failed: {response.status} {response.text()}")
    payload = response.json()
    token = payload["access_token"]
    identity_response = page.request.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    if not identity_response.ok:
        raise AssertionError(
            f"identity failed: {identity_response.status} {identity_response.text()}"
        )
    identity = identity_response.json()
    return {
        "token": token,
        "username": identity["username"],
        "role": identity["role"],
        "public_id": identity.get("public_id") or identity["user_id"],
    }


def initialize_demo(page: Page, admin: dict[str, Any]) -> dict[str, Any]:
    response = page.request.post(
        f"{BASE_URL}/api/v1/competition-demo/initialize",
        headers={"Authorization": f"Bearer {admin['token']}"},
    )
    if not response.ok:
        raise AssertionError(
            f"competition demo initialization failed: {response.status} {response.text()}"
        )
    return response.json()


def context_ref(**overrides: Any) -> dict[str, Any]:
    value = {
        "userId": None,
        "courseId": COURSE_ID,
        "chapterId": None,
        "knowledgePointId": None,
        "taskId": None,
        "resourceId": None,
        "sourceRefId": None,
        "attemptId": None,
        "version": None,
    }
    value.update(overrides)
    return value


def add_browser_state(page: Page, user: dict[str, Any], stored_context: dict[str, Any]) -> None:
    payload = json.dumps(
        {
            "token": user["token"],
            "username": user["username"],
            "role": user["role"],
            "context": stored_context,
        },
        ensure_ascii=False,
    )
    page.add_init_script(
        f"""
        const state = {payload};
        if (!sessionStorage.getItem('edumatrix_e2e_seeded')) {{
          localStorage.setItem('edumatrix_token', state.token);
          localStorage.setItem('edumatrix_username', state.username);
          localStorage.setItem('edumatrix_display_name', state.username);
          localStorage.setItem('edumatrix_role', state.role);
          localStorage.setItem('edumatrix_student_id', state.username);
          localStorage.setItem('edumatrix_onboarded', 'true');
          localStorage.setItem('edumatrix_course_id', state.context.courseId || '');
          localStorage.setItem('edumatrix_course_title', {json.dumps(COURSE_TITLE, ensure_ascii=False)});
          localStorage.setItem('edumatrix_context_ref', JSON.stringify(state.context));
          sessionStorage.setItem('edumatrix_e2e_seeded', 'true');
        }}
        """
    )


def settle(page: Page) -> None:
    page.locator("#app").wait_for(state="visible", timeout=20_000)
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(450)


def stored_context(page: Page) -> dict[str, Any]:
    return page.evaluate(
        "() => JSON.parse(localStorage.getItem('edumatrix_context_ref') || '{}')"
    )


def visual_metrics(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const visible = (el) => {
            const style = getComputedStyle(el), rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' &&
              Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1 &&
              rect.right > 0 && rect.bottom > 0 && rect.left < innerWidth && rect.top < innerHeight;
          };
          const textNodes = [...document.querySelectorAll('body *')]
            .filter((el) => visible(el) && el.children.length === 0 && (el.innerText || '').trim());
          return {
            viewport: [innerWidth, innerHeight],
            documentWidth: document.documentElement.scrollWidth,
            bodyTextLength: (document.body.innerText || '').trim().length,
            smallText: textNodes
              .filter((el) => Number.parseFloat(getComputedStyle(el).fontSize) < 13.5)
              .map((el) => ({
                tag: el.tagName,
                text: (el.innerText || '').trim().slice(0, 48),
                size: getComputedStyle(el).fontSize,
              }))
              .slice(0, 20),
          };
        }"""
    )


def capture(page: Page, name: str, report: dict[str, Any]) -> None:
    settle(page)
    metrics = visual_metrics(page)
    screenshot = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(screenshot), full_page=True)
    if metrics["documentWidth"] > metrics["viewport"][0]:
        raise AssertionError(f"horizontal overflow at {name}: {metrics}")
    if metrics["bodyTextLength"] < 60:
        raise AssertionError(f"blank page at {name}: {metrics}")
    if metrics["smallText"]:
        raise AssertionError(f"visible text below 14px at {name}: {metrics['smallText']}")
    report["screenshots"].append(screenshot.name)
    report["visual_checks"][name] = metrics


def quick_screenshot(page: Page, name: str, report: dict[str, Any]) -> None:
    page.locator("#app").wait_for(state="visible", timeout=20_000)
    page.wait_for_timeout(250)
    screenshot = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(screenshot), full_page=True)
    report["screenshots"].append(screenshot.name)


def new_page(
    browser: Browser,
    viewport: tuple[int, int],
    user: dict[str, Any],
    initial_context: dict[str, Any],
) -> tuple[Any, Page, list[dict[str, str]]]:
    browser_context = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        locale="zh-CN",
    )
    page = browser_context.new_page()
    errors: list[dict[str, str]] = []
    page.on(
        "pageerror",
        lambda error: errors.append({"type": "pageerror", "message": str(error)}),
    )
    page.on(
        "console",
        lambda message: errors.append(
            {"type": f"console:{message.type}", "message": message.text}
        )
        if message.type == "error"
        else None,
    )
    add_browser_state(page, user, initial_context)
    return browser_context, page, errors


def mock_resolution(
    user: dict[str, Any],
    requests: list[dict[str, Any]],
    *,
    preserve_version: bool = False,
) -> Callable[[Any], None]:
    def handler(route: Any) -> None:
        request_context = route.request.post_data_json["context"]
        requests.append(request_context)
        course_id = request_context.get("courseId") or COURSE_ID
        response_values = dict(request_context)
        response_values.update(
            userId=user["public_id"],
            courseId=course_id,
            version=(
                request_context.get("version")
                if preserve_version
                else f"ctx-mock-{course_id}"
            ),
        )
        response_context = context_ref(**response_values)
        response = {
            "schema_version": "edumatrix.context-resolution.v1",
            "context": response_context,
            "course": {
                "objectType": "course",
                "id": course_id,
                "title": "切换后的课程",
                "courseId": course_id,
                "ownerUserId": None,
                "version": "course-v1",
                "status": "published",
            },
            "chapter": None,
            "knowledgePoint": None,
            "task": None,
            "resource": None,
            "sourceRef": None,
            "attempt": None,
            "fallback": "none",
        }
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(response, ensure_ascii=False),
        )

    return handler


def mock_context_error(code: str, message: str, status: int) -> Callable[[Any], None]:
    def handler(route: Any) -> None:
        detail: Any = (
            "Unauthorized"
            if code == "plain_unauthorized"
            else {"code": code, "message": message, "field": None}
        )
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps({"detail": detail}, ensure_ascii=False),
        )

    return handler


def isolate_context_requests(
    page: Page,
    context_handler: Callable[[Any], None] | None = None,
    *,
    allow_legacy_course: bool = False,
) -> None:
    def dispatch(route: Any) -> None:
        path = urlparse(route.request.url).path
        if path == "/api/auth/me":
            route.continue_()
        elif path == "/api/v1/m5/context/resolve":
            (context_handler or (lambda item: item.continue_()))(route)
        elif allow_legacy_course and path == f"/api/v1/courses/{COURSE_ID}":
            route.continue_()
        else:
            route.abort()

    page.route("**/api/**", dispatch)


def scenario_success(
    browser: Browser,
    viewport: tuple[int, int],
    user: dict[str, Any],
    report: dict[str, Any],
) -> None:
    suffix = f"{viewport[0]}x{viewport[1]}"
    browser_context, page, errors = new_page(
        browser, viewport, user, user["resolved_context"]
    )
    isolate_context_requests(page)
    try:
        with page.expect_response(re.compile(r"/api/v1/m5/context/resolve$")) as response:
            page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
        if not response.value.ok:
            raise AssertionError(
                f"real context resolution failed: {response.value.status} {response.value.text()}"
            )
        page.locator("#app").wait_for(state="visible", timeout=20_000)
        page.wait_for_timeout(200)
        first = stored_context(page)
        assert first == user["resolved_context"]
        quick_screenshot(page, f"{suffix}-context-success", report)
        report["checks"][f"{suffix}:success"] = {
            "version": first["version"],
            "page_errors": errors,
        }
        if any(item["type"] == "pageerror" for item in errors):
            raise AssertionError(f"page error during successful recovery: {errors}")
    finally:
        browser_context.close()


def scenario_reopen_cross_route(
    browser: Browser,
    viewport: tuple[int, int],
    user: dict[str, Any],
    report: dict[str, Any],
) -> None:
    suffix = f"{viewport[0]}x{viewport[1]}"
    browser_context, page, errors = new_page(
        browser, viewport, user, user["resolved_context"]
    )
    isolate_context_requests(page)
    try:
        with page.expect_response(re.compile(r"/api/v1/m5/context/resolve$")) as response:
            page.goto(
                f"{BASE_URL}/workspace/assessment",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
        assert response.value.ok, response.value.status
        page.locator("#app").wait_for(state="visible", timeout=20_000)
        page.wait_for_timeout(200)
        assert re.search(r"/workspace/assessment(?:\?|$)", page.url), page.url
        assert stored_context(page) == user["resolved_context"]
        report["checks"][f"{suffix}:reopen-cross-route"] = {
            "refresh_preserved": True,
            "cross_route_preserved": True,
            "page_errors": errors,
        }
    finally:
        browser_context.close()


def scenario_course_switch(
    browser: Browser,
    viewport: tuple[int, int],
    user: dict[str, Any],
    report: dict[str, Any],
) -> None:
    suffix = f"{viewport[0]}x{viewport[1]}"
    old = context_ref(
        userId=user["public_id"],
        chapterId="chapter-old",
        knowledgePointId="kp-old",
        taskId="task-old",
        resourceId="resource-old",
        sourceRefId="source-old",
        attemptId="attempt-old",
        version="ctx-old",
    )
    browser_context, page, errors = new_page(browser, viewport, user, old)
    requests: list[dict[str, Any]] = []
    isolate_context_requests(page, mock_resolution(user, requests))
    try:
        page.goto(
            f"{BASE_URL}/workspace?course_id=course-b&knowledge_point_id=kp-b",
            wait_until="domcontentloaded",
        )
        page.locator("#app").wait_for(state="visible", timeout=20_000)
        page.wait_for_function(
            "() => JSON.parse(localStorage.getItem('edumatrix_context_ref') || '{}').courseId === 'course-b'",
            timeout=15_000,
        )
        assert len(requests) == 1
        requested = requests[0]
        assert requested["courseId"] == "course-b"
        assert requested["knowledgePointId"] == "kp-b"
        for key in ("chapterId", "taskId", "resourceId", "sourceRefId", "attemptId"):
            assert requested[key] is None, (key, requested)
        assert requested["version"] is None
        saved = stored_context(page)
        assert saved["courseId"] == "course-b"
        assert saved["knowledgePointId"] == "kp-b"
        assert saved["resourceId"] is None
        report["checks"][f"{suffix}:course-switch"] = {
            "request": requested,
            "stored": saved,
            "page_errors": errors,
        }
    finally:
        browser_context.close()


def scenario_forbidden_and_safe_exit(
    browser: Browser,
    viewport: tuple[int, int],
    user: dict[str, Any],
    report: dict[str, Any],
) -> None:
    suffix = f"{viewport[0]}x{viewport[1]}"
    initial = context_ref(userId=user["public_id"], resourceId="foreign-resource")
    browser_context, page, errors = new_page(browser, viewport, user, initial)
    isolate_context_requests(
        page,
        mock_context_error(
            "context_cross_user",
            "该学习对象属于其他用户，禁止跨用户读取",
            403,
        ),
    )
    try:
        page.goto(
            f"{BASE_URL}/workspace/resources/handouts/foreign-resource?course_id={COURSE_ID}",
            wait_until="domcontentloaded",
        )
        page.wait_for_url(re.compile(r"/context-recovery"), timeout=15_000)
        page.get_by_role("heading", name="这不是当前账号的学习对象").wait_for(
            state="visible"
        )
        capture(page, f"{suffix}-context-cross-user", report)
        page.get_by_role("button", name="返回首页").click()
        page.wait_for_url(re.compile(r"/$"), timeout=15_000)
        settle(page)
        cleared = stored_context(page)
        assert all(not value for value in cleared.values()), cleared
        assert "/context-recovery" not in page.url
        report["checks"][f"{suffix}:cross-user"] = {
            "recovery_route": True,
            "safe_exit_cleared_context": True,
            "page_errors": errors,
        }
    finally:
        browser_context.close()


def scenario_stale_version(
    browser: Browser,
    viewport: tuple[int, int],
    user: dict[str, Any],
    report: dict[str, Any],
) -> None:
    suffix = f"{viewport[0]}x{viewport[1]}"
    browser_context, page, errors = new_page(
        browser,
        viewport,
        user,
        context_ref(userId=user["public_id"], version="ctx-stale"),
    )
    isolate_context_requests(
        page,
        mock_context_error(
            "context_version_stale",
            "学习上下文已经更新，请从最近保存位置继续",
            409,
        ),
    )
    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
        page.wait_for_url(re.compile(r"/context-recovery"), timeout=15_000)
        page.get_by_role("heading", name="学习内容已有新版本").wait_for(state="visible")
        capture(page, f"{suffix}-context-version-stale", report)
        report["checks"][f"{suffix}:version-stale"] = {
            "recovery_route": True,
            "page_errors": errors,
        }
    finally:
        browser_context.close()


def scenario_plain_401(
    browser: Browser,
    viewport: tuple[int, int],
    user: dict[str, Any],
    report: dict[str, Any],
) -> None:
    suffix = f"{viewport[0]}x{viewport[1]}"
    browser_context, page, errors = new_page(
        browser, viewport, user, context_ref(userId=user["public_id"])
    )
    isolate_context_requests(
        page,
        mock_context_error("plain_unauthorized", "Unauthorized", 401),
    )
    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
        page.wait_for_url(re.compile(r"/login"), timeout=15_000)
        page.wait_for_timeout(300)
        assert urlparse(page.url).path == "/login", page.url
        assert "/context-recovery" not in page.url
        report["checks"][f"{suffix}:plain-401"] = {
            "login_route": True,
            "context_recovery_route": False,
            "page_errors": errors,
        }
    finally:
        browser_context.close()


def scenario_service_fallback(
    browser: Browser,
    viewport: tuple[int, int],
    user: dict[str, Any],
    report: dict[str, Any],
) -> None:
    suffix = f"{viewport[0]}x{viewport[1]}"
    browser_context, page, errors = new_page(
        browser,
        viewport,
        user,
        context_ref(userId=user["public_id"], version="ctx-before-outage"),
    )
    isolate_context_requests(
        page,
        mock_context_error("service_failure", "temporary outage", 503),
        allow_legacy_course=True,
    )
    try:
        with page.expect_response(
            re.compile(rf"/api/v1/courses/{re.escape(COURSE_ID)}$")
        ) as legacy_response:
            page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
        assert legacy_response.value.ok, legacy_response.value.status
        settle(page)
        assert "/context-recovery" not in page.url
        saved = stored_context(page)
        assert saved["courseId"] == COURSE_ID
        assert saved["version"] is None
        capture(page, f"{suffix}-context-legacy-fallback", report)
        report["checks"][f"{suffix}:service-fallback"] = {
            "legacy_course_status": legacy_response.value.status,
            "stored": saved,
            "page_errors": errors,
        }
    finally:
        browser_context.close()


def main() -> int:
    reset_evidence()
    report: dict[str, Any] = {
        "schema_version": "fusion-f2-t01-browser-e2e.v1",
        "base_url": BASE_URL,
        "viewport_contract": [list(item) for item in VIEWPORTS],
        "database": str(DB_PATH),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {},
        "visual_checks": {},
        "screenshots": [],
    }
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            setup_context = browser.new_context(
                viewport={"width": 1440, "height": 900}, locale="zh-CN"
            )
            setup_page = setup_context.new_page()
            admin = register_admin(setup_page, f"f2_admin_{int(time.time())}")
            initialized = initialize_demo(setup_page, admin)
            student = login(setup_page, "lzz", "404404aA")
            resolved = setup_page.request.post(
                f"{BASE_URL}/api/v1/m5/context/resolve",
                headers={"Authorization": f"Bearer {student['token']}"},
                data={"context": context_ref(userId=student["public_id"])},
            )
            if not resolved.ok:
                raise AssertionError(
                    f"setup context resolution failed: {resolved.status} {resolved.text()}"
                )
            student["resolved_context"] = resolved.json()["context"]
            report["setup"] = {
                "demo_status": initialized.get("status", {}).get("status"),
                "student": student["username"],
                "course_id": COURSE_ID,
                "context_version": student["resolved_context"]["version"],
            }
            setup_context.close()

            scenarios = (
                scenario_success,
                scenario_reopen_cross_route,
                scenario_course_switch,
                scenario_forbidden_and_safe_exit,
                scenario_stale_version,
                scenario_plain_401,
                scenario_service_fallback,
            )
            for viewport in VIEWPORTS:
                for scenario in scenarios:
                    scenario(browser, viewport, student, report)
            browser.close()
        report["result"] = "passed"
    except Exception as error:
        report["result"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
