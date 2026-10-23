"""F9-T03 teacher and administrator E2E against an isolated SQLite database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

import e2e_f9_t02_teacher as teacher_base


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f9_t03_admin_teacher"
DB_PATH = OUTPUT_DIR / "f9_t03_admin_teacher.sqlite3"
FIXTURE_PATH = OUTPUT_DIR / "fixture.json"
REPORT_PATH = OUTPUT_DIR / "report.json"
TEST_PASSWORD = "F9Teacher123!"
PORT = int(os.getenv("EDUMATRIX_F9_T03_PORT", "8993"))
VIEWPORTS = ((1440, 900), (1366, 768))
SENSITIVE_TERMS = (
    "system_prompt",
    "api_key",
    "chain_of_thought",
    "raw_log",
    "private-trace",
    "private-prompt",
    "secret-provider",
    "secret-model",
    "internal-only-rationale",
    "do-not-expose",
    "lease-token",
    "private provider response",
)


def configure_runtime(port: int) -> None:
    teacher_base.OUTPUT_DIR = OUTPUT_DIR
    teacher_base.DB_PATH = DB_PATH
    teacher_base.FIXTURE_PATH = FIXTURE_PATH
    teacher_base.REPORT_PATH = REPORT_PATH
    teacher_base.PORT = port
    teacher_base.VIEWPORTS = VIEWPORTS
    teacher_base.SENSITIVE_TERMS = SENSITIVE_TERMS
    teacher_base.configure_runtime(DB_PATH, port)
    os.environ["EDUMATRIX_AUTH_SECRET_KEY"] = "f9-t03-isolated-browser-secret"


def prepare_fixture(port: int) -> None:
    configure_runtime(port)
    teacher_base.prepare_fixture()
    (OUTPUT_DIR / ".gitkeep").write_text(
        "F9-T03 B06 isolated browser evidence directory.\n", encoding="utf-8"
    )

    from app.auth import get_password_hash
    from app.content_review import submit_review
    from app.database import (
        DBArtifact,
        DBArtifactVersion,
        DBAuditLog,
        DBClaimCheck,
        DBCourseMembership,
        DBGenerationTask,
        DBModelCall,
        DBQualityCheck,
        DBSourceRef,
        DBTaskStep,
        DBUser,
        SessionLocal,
        engine,
    )
    from app.m5_assessment_core import QuestionVersionInput, create_question_version

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    db = SessionLocal()
    try:
        assistant = db.query(DBUser).filter_by(username="f9-assistant").first()
        if assistant is not None:
            db.query(DBCourseMembership).filter_by(user_public_id=assistant.public_id).delete()
            db.delete(assistant)

        source_ref = DBSourceRef(
            id="f9-t03-source-ref",
            source_document_id="f9-source",
            chapter_id="f9-chapter-1",
            parser_version="parser-v1",
            page_number=12,
            location_kind="page",
            location_label="第 12 页 · 混合检索评测",
            quote="混合检索需要同时核对召回覆盖和引用定位。",
            content_hash="d" * 64,
        )
        db.add(source_ref)
        db.flush()
        question, question_version = create_question_version(
            db,
            owner_public_id="f9-teacher",
            course_id=fixture["course_id"],
            question_type="single_choice",
            origin="manual",
            version=QuestionVersionInput(
                prompt="哪一种做法能同时提高召回覆盖并保留来源定位？",
                options=("A. 只使用固定关键词", "B. 混合检索并保留引用"),
                answer_key={"choice": "B"},
                scoring_rule={"type": "exact", "version": "objective-v1"},
                explanation="混合检索负责覆盖，来源引用负责可追溯。",
                misconception_tags=("只关注召回而忽略来源",),
                primary_knowledge_point_id="f9-kp-retrieval",
                expert_difficulty=0.45,
                source_ref_ids=(source_ref.id,),
            ),
        )
        question.status = "approved"

        review_content = (
            "# 可信检索实训讲义\n\n"
            "本讲义要求学习者比较关键词检索、向量检索与混合检索，"
            "并为结论保留可定位来源。"
        )
        review_version = DBArtifactVersion(
            id="f9-t03-review-version",
            artifact_id="f9-t03-review-artifact",
            version_number=1,
            content=review_content,
            content_hash=hashlib.sha256(review_content.encode("utf-8")).hexdigest(),
            content_format="markdown",
            created_by_public_id=fixture["learner_id"],
        )
        review_artifact = DBArtifact(
            id="f9-t03-review-artifact",
            owner_public_id=fixture["learner_id"],
            course_id=fixture["course_id"],
            artifact_type="lesson",
            title="可信检索实训讲义",
            status="draft",
            current_version_id=review_version.id,
        )
        db.add(review_artifact)
        db.flush()
        db.add(review_version)
        db.flush()
        db.add_all([
            DBQualityCheck(
                id="f9-t03-quality-check",
                artifact_version_id=review_version.id,
                trace_id="private-trace-quality",
                check_type="citation",
                checker_version="1",
                status="passed",
                score=0.93,
                details={"private_note": "do-not-expose"},
                source_ref_ids=[source_ref.id],
            ),
            DBClaimCheck(
                id="f9-t03-claim-check",
                artifact_version_id=review_version.id,
                trace_id="private-trace-claim",
                atomic_claim="混合检索能够提高证据覆盖",
                source_ref_id=source_ref.id,
                support_status="supported",
                verdict="supported",
                rationale="internal-only-rationale",
            ),
        ])
        db.flush()
        learner = db.query(DBUser).filter_by(public_id=fixture["learner_id"]).one()
        review_case = submit_review(
            db,
            actor=learner,
            artifact_id=review_artifact.id,
            version_id=review_version.id,
            submission_note="提交带来源定位的可信检索实训讲义",
        )

        failed_task = DBGenerationTask(
            id="f9-t03-failed-task",
            owner_public_id=fixture["learner_id"],
            course_id=fixture["course_id"],
            trace_id="private-trace-failed-task",
            capability="lecture.generate_verified",
            idempotency_key="f9-t03-failed-task",
            status="failed",
            progress=0.5,
            failure_code="provider_timeout",
            failure_reason="private provider response",
        )
        db.add(failed_task)
        db.flush()
        db.add_all([
            DBTaskStep(
                task_id=failed_task.id,
                sequence=1,
                attempt=1,
                agent_role="generator",
                tool_name="lecture",
                status="completed",
                input_summary="content_included=false",
            ),
            DBTaskStep(
                task_id=failed_task.id,
                sequence=2,
                attempt=1,
                agent_role="reviewer",
                tool_name="review",
                status="failed",
                input_summary="content_included=false",
                error_code="provider_timeout",
            ),
            DBArtifact(
                id="f9-t03-existing-result",
                owner_public_id=fixture["learner_id"],
                course_id=fixture["course_id"],
                artifact_type="lesson",
                title="已完成的讲义部分",
                status="draft",
                creating_task_id=failed_task.id,
            ),
        ])

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add_all([
            DBModelCall(
                trace_id="private-trace-auth",
                owner_public_id=fixture["learner_id"],
                capability="quiz",
                prompt_version="private-prompt-auth",
                provider="secret-provider",
                model="secret-model",
                status="failed",
                error_code="invalid_api_key",
                created_at=now - timedelta(seconds=2),
                completed_at=now - timedelta(seconds=1),
            ),
            DBModelCall(
                trace_id="private-trace-capacity",
                owner_public_id=fixture["learner_id"],
                capability="report",
                prompt_version="private-prompt-capacity",
                provider="secret-provider",
                model="secret-model",
                status="failed",
                error_code="model_capacity",
                created_at=now,
                completed_at=now,
            ),
        ])
        db.commit()

        fixture["usernames"].pop("assistant", None)
        fixture.update({
            "admin_username": "f9-admin",
            "teacher_username": "f9-teacher",
            "student_username": "f9-learner-1",
            "question_version_id": question_version.id,
            "review_case_id": review_case.id,
            "failed_task_id": failed_task.id,
        })
        FIXTURE_PATH.write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert db.query(DBUser).filter_by(role="assistant").count() == 0
        audit_rows = db.query(DBAuditLog).all()
        assert len(audit_rows) == 2
        assert {
            (row.actor_public_id, row.action, row.object_type, row.object_id, row.outcome)
            for row in audit_rows
        } == {
            (
                "f9-teacher",
                "assessment.question.create",
                "assessment_question",
                question.id,
                "success",
            ),
            (
                fixture["learner_id"],
                "content_review.submit",
                "content_review_case",
                review_case.id,
                "success",
            ),
        }
    finally:
        db.close()
        engine.dispose()
    print(json.dumps({"status": "prepared", "database": str(DB_PATH)}, ensure_ascii=False))


def auth_headers(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


def api_login(context: BrowserContext, base_url: str, username: str) -> dict:
    response = context.request.post(
        f"{base_url}/api/auth/login",
        form={"username": username, "password": TEST_PASSWORD},
    )
    assert response.ok, (username, response.status, response.text())
    return response.json()


def login_through_ui(
    page: Page,
    base_url: str,
    *,
    role: str,
    username: str,
    expected_path: str,
) -> dict:
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle")
    assert urlparse(page.url).path == "/landing", page.url
    page.get_by_role("button", name="进入系统", exact=True).first.click()
    page.locator('[data-testid="login-role-student"]').wait_for(state="visible", timeout=20_000)
    assert urlparse(page.url).path == "/login", page.url
    assert page.locator('[data-testid^="login-role-"]').all_inner_texts() == ["学生", "教师", "管理员"]
    page.locator(f'[data-testid="login-role-{role}"]').click()
    page.locator('[data-testid="login-username"]').fill(username)
    page.locator('[data-testid="login-password"]').fill(TEST_PASSWORD)
    page.locator('[data-testid="login-submit"]').click()
    page.wait_for_url(f"**{expected_path}", timeout=30_000)
    page.wait_for_load_state("networkidle")
    session = page.evaluate("""() => ({
      access_token: localStorage.getItem('edumatrix_token'),
      username: localStorage.getItem('edumatrix_username'),
      display_name: localStorage.getItem('edumatrix_display_name'),
      role: localStorage.getItem('edumatrix_role'),
    })""")
    assert session["role"] == role, session
    return session


def scan_sensitive(value: object) -> None:
    serialized = (
        value if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, default=str)
    ).lower()
    for forbidden in SENSITIVE_TERMS:
        assert forbidden not in serialized, (forbidden, serialized[:800])


def goto_target(page: Page, base_url: str, path: str, test_id: str, heading: str) -> None:
    page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_load_state("networkidle")
    root = page.locator(f'[data-testid="{test_id}"]')
    root.wait_for(state="visible", timeout=30_000)
    root.get_by_role("heading", name=heading, exact=True, level=1).wait_for(
        state="visible", timeout=30_000
    )


def visual_extras(page: Page) -> dict:
    return page.evaluate("""() => {
      const visible = (el) => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1;
      };
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
      const primary = [...document.querySelectorAll('.primary-action,.primary-button,.save-button,.login-submit')]
        .filter(visible).map((el) => {
          const style = getComputedStyle(el), foreground = parseRgb(style.color), background = parseRgb(style.backgroundColor);
          if (!foreground || !background) return null;
          const high = Math.max(luminance(foreground), luminance(background));
          const low = Math.min(luminance(foreground), luminance(background));
          return { text: (el.innerText || '').trim().slice(0, 48), ratio: (high + .05) / (low + .05) };
        }).filter((item) => item && item.ratio < 4.5);
      const effects = [...document.querySelectorAll('main *')].filter(visible).filter((el) => {
        const style = getComputedStyle(el);
        return style.backgroundImage.includes('gradient') ||
          (style.backdropFilter && style.backdropFilter !== 'none');
      }).map((el) => String(el.className).slice(0, 80)).slice(0, 20);
      const theme = [...document.querySelectorAll('main *')].filter(visible).filter((el) => {
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
      return { lowContrastPrimary: primary, forbiddenEffects: effects, themedColorRegression: theme };
    }""")


def capture(page: Page, report: dict, name: str, *, min_body_text: int = 120) -> None:
    page.evaluate("""() => {
      window.scrollTo(0, 0);
      const content = document.querySelector('.app-content');
      if (content) content.scrollTo(0, 0);
    }""")
    page.wait_for_timeout(200)
    metrics = teacher_base.visible_metrics(page)
    metrics.update(visual_extras(page))
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["visual_checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] >= min_body_text, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["lowContrastPrimary"], metrics
    assert not metrics["forbiddenEffects"], metrics
    assert not metrics["themedColorRegression"], metrics
    scan_sensitive(page.locator("body").inner_text())


def run_teacher_journey(
    browser: Browser,
    base_url: str,
    fixture: dict,
    report: dict,
) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900}, locale="zh-CN", color_scheme="light"
    )
    page = context.new_page()
    teacher_base.attach_diagnostics(page, report)
    try:
        login_through_ui(
            page,
            base_url,
            role="teacher",
            username=fixture["teacher_username"],
            expected_path="/teacher/overview",
        )
        report["teacher_entry_order"] = ["/landing", "/login", "/teacher/overview"]
        browse_before = teacher_base.learning_state(DB_PATH)

        goto_target(
            page,
            base_url,
            f"/teacher/assessment?course_id={fixture['course_id']}",
            "formal-exam-workspace",
            "试卷管理",
        )
        page.locator(".question-picker input[type=checkbox]").first.wait_for(state="visible")
        capture(page, report, "1440x900_01_teacher_assessment_ready.png")

        goto_target(
            page,
            base_url,
            "/teacher/interventions",
            "teacher-interventions-page",
            "干预任务",
        )
        page.locator(".student-row").first.wait_for(state="visible", timeout=30_000)
        page.locator(".student-row").first.click()
        page.locator(".agent-audit > summary").wait_for(state="visible", timeout=30_000)
        page.locator(".agent-audit > summary").click()
        page.get_by_text("分歧：候选难度存在分歧", exact=False).wait_for(state="visible")
        capture(page, report, "1440x900_02_teacher_intervention_evidence.png")
        assert teacher_base.learning_state(DB_PATH) == browse_before
        report["ordinary_browse_database_unchanged"] = True

        page.get_by_role("button", name="发布干预任务", exact=True).click()
        page.get_by_text("干预任务已加入学生路径", exact=False).wait_for(
            state="visible", timeout=30_000
        )
        report["teacher_intervention_published"] = True
        mastery_after_intervention = teacher_base.mastery_digest(DB_PATH)

        goto_target(
            page,
            base_url,
            f"/teacher/assessment?course_id={fixture['course_id']}",
            "formal-exam-workspace",
            "试卷管理",
        )
        page.locator('input[aria-label="课程 ID"]').fill(fixture["course_id"])
        page.locator('input[aria-label="考试名称"]').fill("F9 可信检索阶段测评")
        page.locator(".question-picker input[type=checkbox]").first.check()
        page.get_by_role("button", name="建立试卷", exact=True).click()
        page.get_by_text("试卷草稿已创建", exact=False).wait_for(state="visible", timeout=30_000)
        page.get_by_role("button", name="发布", exact=True).click()
        page.get_by_text("考试已切换为 published", exact=False).wait_for(
            state="visible", timeout=30_000
        )
        capture(page, report, "1440x900_03_teacher_assessment_published.png")
        assert teacher_base.mastery_digest(DB_PATH) == mastery_after_intervention
        report["teacher_exam_published"] = True
        report["mastery_unchanged_by_teacher_actions"] = True
    finally:
        context.close()


def run_admin_journey(
    browser: Browser,
    base_url: str,
    fixture: dict,
    report: dict,
) -> None:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900}, locale="zh-CN", color_scheme="light"
    )
    page = context.new_page()
    teacher_base.attach_diagnostics(page, report)
    try:
        session = login_through_ui(
            page,
            base_url,
            role="admin",
            username=fixture["admin_username"],
            expected_path="/admin/system",
        )
        report["admin_entry_order"] = ["/landing", "/login", "/admin/system"]
        goto_target(page, base_url, "/admin/accounts", "admin-accounts-page", "账号权限")
        page.locator('[data-testid="admin-accounts-page"]').wait_for(state="visible")
        page.get_by_placeholder("搜索账号或显示名").fill(fixture["student_username"])
        page.get_by_role("button", name=f"编辑 {fixture['student_username']}", exact=True).click()
        role_select = page.get_by_role("combobox", name=f"编辑 {fixture['student_username']} 的角色")
        assert role_select.locator("option").all_inner_texts() == ["学生", "教师", "管理员"]
        page.get_by_role("button", name="取消编辑", exact=True).click()
        page.get_by_placeholder("搜索账号或显示名").fill("")
        accounts_payload = context.request.get(
            f"{base_url}/api/v1/admin/accounts", headers=auth_headers(session)
        ).json()
        assert {item["role"] for item in accounts_payload["items"]} == {"student", "teacher", "admin"}
        scan_sensitive(accounts_payload)
        capture(page, report, "1440x900_04_admin_accounts.png")
        report["admin_accounts_checked"] = True

        goto_target(page, base_url, "/admin/models", "admin-models-page", "模型配置")
        model_text = page.locator("body").inner_text()
        for label in ("能力配置", "近期可用性", "认证", "容量", "限流", "超时"):
            assert label in model_text, (label, model_text)
        models_payload = context.request.get(
            f"{base_url}/api/v1/admin/models", headers=auth_headers(session)
        ).json()
        scan_sensitive(models_payload)
        capture(page, report, "1440x900_05_admin_models.png")
        report["admin_models_checked"] = True

        goto_target(
            page,
            base_url,
            "/admin/content-review",
            "content-review-page",
            "内容审核",
        )
        page.locator('[data-testid="review-case"]').first.wait_for(state="visible", timeout=30_000)
        page.get_by_text("混合检索需要同时核对召回覆盖和引用定位", exact=False).wait_for(
            state="visible", timeout=30_000
        )
        page.locator(".agent-audit > summary").click()
        page.get_by_text("交叉校验", exact=True).wait_for(state="visible")
        page.get_by_placeholder("例如：来源可定位，声明支持与质量检查均已核对。").fill(
            "来源定位、声明支持和质量检查均已核对。"
        )
        page.get_by_role("button", name="批准内容", exact=True).click()
        page.get_by_text("审核决定已保存", exact=False).wait_for(state="visible", timeout=30_000)
        page.get_by_role("button", name="发布内容", exact=True).wait_for(state="visible")
        capture(page, report, "1440x900_06_admin_content_review_approved.png")
        report["content_review_approved"] = True

        goto_target(page, base_url, "/admin/system", "admin-system-page", "系统状态")
        page.get_by_text("任务等待超时，可从当前任务重试", exact=True).wait_for(
            state="visible", timeout=30_000
        )
        page.get_by_role("button", name="重试失败步骤", exact=True).click()
        page.get_by_text("已从失败步骤重新排队", exact=False).wait_for(
            state="visible", timeout=30_000
        )
        capture(page, report, "1440x900_07_admin_system_recovered.png")
        report["failed_task_recovered"] = True
    finally:
        context.close()


def run_role_boundaries(
    browser: Browser,
    base_url: str,
    fixture: dict,
    report: dict,
) -> None:
    request_context = browser.new_context()
    try:
        student = api_login(request_context, base_url, fixture["student_username"])
        teacher = api_login(request_context, base_url, fixture["teacher_username"])
        for path in ("/api/v1/teacher/courses", "/api/v1/admin/accounts", "/api/v1/admin/system"):
            response = request_context.request.get(f"{base_url}{path}", headers=auth_headers(student))
            assert response.status == 403, (path, response.status, response.text())
        for path in ("/api/v1/admin/accounts", "/api/v1/admin/models", "/api/v1/admin/system"):
            response = request_context.request.get(f"{base_url}{path}", headers=auth_headers(teacher))
            assert response.status == 403, (path, response.status, response.text())
        response = request_context.request.post(
            f"{base_url}/api/v1/content-review/cases/{fixture['review_case_id']}/decisions",
            headers=auth_headers(student),
            data={"action": "publish", "reason": "student forbidden action", "expected_version": 2},
        )
        assert response.status == 403, (response.status, response.text())
    finally:
        request_context.close()

    for role_key, blocked_path, blocked_test_id in (
        ("student_username", "/teacher/assessment", "formal-exam-workspace"),
        ("student_username", "/admin/accounts", "admin-accounts-page"),
        ("teacher_username", "/admin/system", "admin-system-page"),
    ):
        context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
        session = api_login(context, base_url, fixture[role_key])
        teacher_base.add_session(context, session, fixture)
        page = context.new_page()
        try:
            page.goto(f"{base_url}{blocked_path}", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_load_state("networkidle")
            assert urlparse(page.url).path != blocked_path, (role_key, page.url)
            assert not page.locator(f'[data-testid="{blocked_test_id}"]').is_visible()
        finally:
            context.close()
    report["role_boundaries_verified"] = True


def run_compact_routes(
    browser: Browser,
    base_url: str,
    fixture: dict,
    report: dict,
) -> None:
    routes = (
        ("teacher_username", "/teacher/assessment", "formal-exam-workspace", "试卷管理", "08_teacher_assessment"),
        ("teacher_username", "/teacher/interventions", "teacher-interventions-page", "干预任务", "09_teacher_interventions"),
        ("admin_username", "/admin/accounts", "admin-accounts-page", "账号权限", "10_admin_accounts"),
        ("admin_username", "/admin/models", "admin-models-page", "模型配置", "11_admin_models"),
        ("admin_username", "/admin/content-review", "content-review-page", "内容审核", "12_admin_content_review"),
        ("admin_username", "/admin/system", "admin-system-page", "系统状态", "13_admin_system"),
    )
    contexts: dict[str, BrowserContext] = {}
    try:
        for role_key in ("teacher_username", "admin_username"):
            context = browser.new_context(
                viewport={"width": 1366, "height": 768}, locale="zh-CN", color_scheme="light"
            )
            session = api_login(context, base_url, fixture[role_key])
            teacher_base.add_session(context, session, fixture)
            contexts[role_key] = context
        for role_key, path, test_id, heading, name in routes:
            page = contexts[role_key].new_page()
            teacher_base.attach_diagnostics(page, report)
            try:
                suffix = f"?course_id={fixture['course_id']}" if path == "/teacher/assessment" else ""
                goto_target(page, base_url, f"{path}{suffix}", test_id, heading)
                capture(page, report, f"1366x768_{name}.png")
            finally:
                page.close()
    finally:
        for context in contexts.values():
            context.close()


def database_audit() -> dict[str, object]:
    with sqlite3.connect(DB_PATH, timeout=20) as db:
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "published_exams": db.execute(
                "SELECT COUNT(*) FROM assessment_exams WHERE status='published'"
            ).fetchone()[0],
            "approved_review_cases": db.execute(
                "SELECT COUNT(*) FROM content_review_cases WHERE status='approved'"
            ).fetchone()[0],
            "retried_task_status": db.execute(
                "SELECT status FROM generation_tasks WHERE id='f9-t03-failed-task'"
            ).fetchone()[0],
            "admin_retry_audits": db.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE action='admin.task.retry'"
            ).fetchone()[0],
        }


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
        "task": "F9-T03",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "viewports": [list(item) for item in VIEWPORTS],
        "screenshots": [],
        "visual_checks": {},
        "browser_pages": [],
        "ordinary_browse_database_unchanged": False,
        "teacher_exam_published": False,
        "teacher_intervention_published": False,
        "admin_accounts_checked": False,
        "admin_models_checked": False,
        "content_review_approved": False,
        "failed_task_recovered": False,
        "role_boundaries_verified": False,
        "mastery_unchanged_by_teacher_actions": False,
        "external_model_called": False,
    }
    browser = playwright.chromium.launch(headless=True)
    try:
        run_teacher_journey(browser, base_url, fixture, report)
        run_admin_journey(browser, base_url, fixture, report)
        run_role_boundaries(browser, base_url, fixture, report)
        run_compact_routes(browser, base_url, fixture, report)
        assert_browser_clean(report)
        audit = database_audit()
        assert audit["integrity"] == "ok", audit
        assert audit["foreign_key_violations"] == 0, audit
        assert audit["published_exams"] == 1, audit
        assert audit["approved_review_cases"] == 1, audit
        assert audit["retried_task_status"] == "queued", audit
        assert audit["admin_retry_audits"] == 1, audit
        report["database_audit"] = audit
        scan_sensitive(report)
        report["status"] = "passed"
    except Exception as exception:
        report["status"] = "failed"
        report["failure"] = {"type": type(exception).__name__, "message": str(exception)}
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


def serve(port: int) -> None:
    configure_runtime(port)
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=False, log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--serve", action="store_true")
    group.add_argument("--run", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    configure_runtime(args.port)
    if args.prepare:
        prepare_fixture(args.port)
    elif args.serve:
        serve(args.port)
    else:
        base_url = f"http://127.0.0.1:{args.port}"
        with sync_playwright() as playwright:
            run_e2e(playwright, base_url)


if __name__ == "__main__":
    main()
