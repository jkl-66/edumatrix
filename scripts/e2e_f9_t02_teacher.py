"""F9-T02 teacher workspace E2E against an isolated SQLite database."""

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

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f9_t02_teacher"
DB_PATH = OUTPUT_DIR / "f9_t02_teacher.sqlite3"
FIXTURE_PATH = OUTPUT_DIR / "fixture.json"
REPORT_PATH = OUTPUT_DIR / "report.json"
TEST_PASSWORD = "F9Teacher123!"
PORT = int(os.getenv("EDUMATRIX_F9_T02_PORT", "8992"))
VIEWPORTS = ((1440, 900), (1366, 768))
SENSITIVE_TERMS = (
    "system_prompt",
    "api_key",
    "chain_of_thought",
    "raw_log",
    "private-trace-never-return",
)


def configure_runtime(db_path: Path, port: int) -> None:
    os.environ.update({
        "EDUMATRIX_DB_PATH": str(db_path),
        "EDUMATRIX_AUTH_SECRET_KEY": "f9-t02-isolated-browser-secret",
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

    from app.agent_audit import AGENT_AUDIT_EVENT
    from app.auth import get_password_hash
    from app.database import (
        DBArtifact,
        DBChapter,
        DBChapterKnowledgePoint,
        DBCourse,
        DBCourseMembership,
        DBGenerationTask,
        DBKnowledgePoint,
        DBLearningEvent,
        DBLearningPath,
        DBPathNode,
        DBPlanDraft,
        DBPlanVersion,
        DBProfileSnapshot,
        DBSourceDocument,
        DBStudentProfile,
        DBTaskEvent,
        DBTeachingClass,
        DBTeachingClassMember,
        DBTeachingTask,
        DBUser,
        SessionLocal,
        engine,
        init_db,
    )

    init_db()
    db = SessionLocal()
    try:
        users = {
            "teacher": DBUser(
                public_id="f9-teacher",
                username="f9-teacher",
                hashed_password=get_password_hash(TEST_PASSWORD),
                role="teacher",
                display_name="林老师",
            ),
            "other_teacher": DBUser(
                public_id="f9-other-teacher",
                username="f9-other-teacher",
                hashed_password=get_password_hash(TEST_PASSWORD),
                role="teacher",
                display_name="外部教师",
            ),
            "empty_teacher": DBUser(
                public_id="f9-empty-teacher",
                username="f9-empty-teacher",
                hashed_password=get_password_hash(TEST_PASSWORD),
                role="teacher",
                display_name="暂无课程教师",
            ),
            "assistant": DBUser(
                public_id="f9-assistant",
                username="f9-assistant",
                hashed_password=get_password_hash(TEST_PASSWORD),
                role="assistant",
                display_name="历史助教",
            ),
            "admin": DBUser(
                public_id="f9-admin",
                username="f9-admin",
                hashed_password=get_password_hash(TEST_PASSWORD),
                role="admin",
                display_name="管理员",
            ),
            "learner_1": DBUser(
                public_id="f9-learner-1",
                username="f9-learner-1",
                hashed_password=get_password_hash(TEST_PASSWORD),
                role="student",
                display_name="学员一",
            ),
            "learner_2": DBUser(
                public_id="f9-learner-2",
                username="f9-learner-2",
                hashed_password=get_password_hash(TEST_PASSWORD),
                role="student",
                display_name="学员二",
            ),
        }
        db.add_all(list(users.values()))
        db.flush()

        courses = {
            "primary": DBCourse(
                id="f9-course",
                version="1",
                title="可信 RAG 工程",
                subject="人工智能",
                description="从混合检索到引用校验的工程课程",
                visibility="private",
                status="published",
                manifest_version="1",
                owner_public_id=users["teacher"].public_id,
            ),
            "secondary": DBCourse(
                id="f9-course-2",
                version="1",
                title="第二门视觉模型课程",
                subject="计算机视觉",
                description="用于验证教师授权课程切换",
                visibility="private",
                status="published",
                manifest_version="1",
                owner_public_id=users["teacher"].public_id,
            ),
            "other": DBCourse(
                id="f9-other-course",
                version="1",
                title="未授权外部课程",
                subject="电子信息",
                visibility="private",
                status="published",
                manifest_version="1",
                owner_public_id=users["other_teacher"].public_id,
            ),
        }
        db.add_all(list(courses.values()))
        db.flush()

        source = DBSourceDocument(
            id="f9-source",
            course_id=courses["primary"].id,
            title="可信检索课程讲义",
            filename="retrieval.md",
            file_format="md",
            content_hash="a" * 64,
            processing_status="ready",
            license_text="CC BY 4.0",
        )
        db.add(source)
        db.flush()
        chapters = [
            DBChapter(
                id=f"f9-chapter-{index}",
                course_id=courses["primary"].id,
                source_document_id=source.id,
                stable_key=f"chapter-{index}",
                title=title,
                position=index,
            )
            for index, title in ((1, "混合检索"), (2, "引用校验"))
        ]
        points = [
            DBKnowledgePoint(
                id="f9-kp-retrieval",
                domain_pack="f9-rag",
                code="RAG-01",
                version="1",
                title="混合检索与重排",
            ),
            DBKnowledgePoint(
                id="f9-kp-citation",
                domain_pack="f9-rag",
                code="RAG-02",
                version="1",
                title="引用约束",
                prerequisites=["f9-kp-retrieval"],
            ),
        ]
        db.add_all([*chapters, *points])
        db.flush()
        db.add_all([
            DBChapterKnowledgePoint(chapter_id=chapters[0].id, knowledge_point_id=points[0].id),
            DBChapterKnowledgePoint(chapter_id=chapters[1].id, knowledge_point_id=points[1].id),
            DBCourseMembership(
                course_id=courses["primary"].id,
                user_public_id=users["teacher"].public_id,
                role="teacher",
                status="active",
            ),
            DBCourseMembership(
                course_id=courses["secondary"].id,
                user_public_id=users["teacher"].public_id,
                role="teacher",
                status="active",
            ),
            DBCourseMembership(
                course_id=courses["other"].id,
                user_public_id=users["other_teacher"].public_id,
                role="teacher",
                status="active",
            ),
            DBCourseMembership(
                course_id=courses["primary"].id,
                user_public_id=users["assistant"].public_id,
                role="assistant",
                status="active",
            ),
            *[
                DBCourseMembership(
                    course_id=courses["primary"].id,
                    user_public_id=users[key].public_id,
                    role="student",
                    status="active",
                )
                for key in ("learner_1", "learner_2")
            ],
        ])

        classroom = DBTeachingClass(
            id="f9-class",
            course_id=courses["primary"].id,
            title="RAG 实训班",
            term="2026",
            owner_public_id=users["teacher"].public_id,
        )
        db.add(classroom)
        db.flush()
        db.add_all([
            *[
                DBTeachingClassMember(
                    class_id=classroom.id,
                    user_public_id=users[key].public_id,
                    role="student",
                )
                for key in ("learner_1", "learner_2")
            ],
            DBTeachingTask(
                id="f9-task",
                class_id=classroom.id,
                title="检查本周学习证据",
                idempotency_key="f9-task-001",
                status="draft",
                created_by_public_id=users["teacher"].public_id,
            ),
            DBArtifact(
                id="f9-resource",
                owner_public_id=users["learner_1"].public_id,
                course_id=courses["primary"].id,
                artifact_type="handout",
                title="个性化检索讲义",
                status="published",
            ),
            DBStudentProfile(
                student_id=users["learner_1"].username,
                concept_mastery={"混合检索与重排": 0.28, "引用约束": 0.71},
            ),
            DBStudentProfile(
                student_id=users["learner_2"].username,
                concept_mastery={"混合检索与重排": 0.76, "引用约束": 0.31},
            ),
        ])

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for key, weak_id, mastered_id, event_id in (
            ("learner_1", points[0].id, points[1].id, "f9-event-1"),
            ("learner_2", points[1].id, points[0].id, "f9-event-2"),
        ):
            learner = users[key]
            db.add(DBProfileSnapshot(
                id=f"f9-snapshot-{learner.public_id}",
                owner_public_id=learner.public_id,
                legacy_student_id=learner.username,
                profile_version="1",
                snapshot={
                    "course_id": courses["primary"].id,
                    "mastery": 0.5,
                    "weak_knowledge_point_ids": [weak_id],
                    "mastered_knowledge_point_ids": [mastered_id],
                },
                content_hash="b" * 64,
                trace_id=f"trace-{learner.public_id}",
            ))
            db.add(DBLearningEvent(
                id=event_id,
                owner_public_id=learner.public_id,
                course_id=courses["primary"].id,
                event_type="assessment_submitted",
                trace_id=f"trace-{event_id}",
                object_type="knowledge_point",
                object_id=weak_id,
                evidence_status="accepted",
                evidence_strength=0.8,
                mastery_eligible=True,
                evidence_reason="正式测验证据",
                occurred_at=now,
            ))

        plan = DBPlanDraft(
            id="f9-plan",
            owner_public_id=users["learner_1"].public_id,
            course_id=courses["primary"].id,
            title="既有路径",
            status="confirmed",
            idempotency_key="f9-plan-001",
        )
        db.add(plan)
        db.flush()
        version = DBPlanVersion(
            id="f9-plan-version",
            plan_draft_id=plan.id,
            version_number=1,
            content={"goal": "完成可信检索", "nodes": []},
            content_hash="c" * 64,
            created_by_public_id=users["teacher"].public_id,
        )
        db.add(version)
        db.flush()
        path = DBLearningPath(
            id="f9-path",
            owner_public_id=users["learner_1"].public_id,
            course_id=courses["primary"].id,
            source_plan_version_id=version.id,
        )
        db.add(path)
        db.flush()
        db.add_all([
            DBPathNode(
                id="f9-node-1",
                learning_path_id=path.id,
                node_key="f9-node-1",
                sequence=1,
                node_type="chapter",
                target_object_id=chapters[0].id,
                title="完成混合检索练习",
                status="completed",
                estimate_min_minutes=20,
                estimate_max_minutes=30,
            ),
            DBPathNode(
                id="f9-node-2",
                learning_path_id=path.id,
                node_key="f9-node-2",
                sequence=2,
                node_type="chapter",
                target_object_id=chapters[1].id,
                title="完成引用校验练习",
                status="pending",
                estimate_min_minutes=20,
                estimate_max_minutes=40,
            ),
        ])
        generation = DBGenerationTask(
            id="f9-generation",
            owner_public_id=users["learner_1"].public_id,
            course_id=courses["primary"].id,
            trace_id="private-trace-never-return",
            capability="resource_generation",
            idempotency_key="f9-generation-001",
            status="completed",
            progress=1.0,
        )
        db.add(generation)
        db.flush()
        db.add(DBTaskEvent(
            id="f9-agent-event",
            task_id=generation.id,
            sequence=1,
            event_type=AGENT_AUDIT_EVENT,
            payload={
                "runId": "f9-public-run",
                "role": "validation",
                "inputRefs": [points[0].id, source.id],
                "candidateSummary": "建议先完成混合检索对比实验",
                "disagreement": "候选难度存在分歧",
                "validation": "来源与学习事件一致",
                "revision": "降低任务跨度并补充引用检查",
                "decisionSummary": "发布针对性练习",
                "status": "completed",
                "system_prompt": "must be removed",
                "api_key": "must be removed",
            },
        ))
        db.commit()
        fixture = {
            "course_id": courses["primary"].id,
            "secondary_course_id": courses["secondary"].id,
            "other_course_id": courses["other"].id,
            "learner_id": users["learner_1"].public_id,
            "usernames": {key: user.username for key, user in users.items()},
        }
        FIXTURE_PATH.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        db.close()
        engine.dispose()
    print(json.dumps({"status": "prepared", "database": str(DB_PATH)}, ensure_ascii=False))


def api_login(request, base_url: str, username: str) -> dict:
    response = request.post(
        f"{base_url}/api/auth/login",
        form={"username": username, "password": TEST_PASSWORD},
    )
    assert response.ok, f"login failed for {username}: {response.status} {response.text()}"
    return response.json()


def auth_headers(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


def add_session(context: BrowserContext, session: dict, fixture: dict) -> None:
    public_session = {
        "access_token": session["access_token"],
        "username": session.get("username") or "anonymous",
        "display_name": session.get("display_name") or session.get("username") or "匿名用户",
        "role": session.get("role") or "student",
        "student_id": session.get("student_id") or session.get("username") or "anonymous",
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
      localStorage.setItem('edumatrix_course_title', '可信 RAG 工程');
    """)


def attach_diagnostics(page: Page, report: dict) -> dict:
    page_report = {
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
        "off_origin_requests": [],
    }
    report["browser_pages"].append(page_report)

    def on_response(response) -> None:
        if response.status >= 400:
            page_report["http_errors"].append({"status": response.status, "url": response.url})

    def on_request(request) -> None:
        parsed = urlparse(request.url)
        if parsed.scheme in {"http", "https"} and parsed.hostname not in {"127.0.0.1", "localhost"}:
            page_report["off_origin_requests"].append(request.url)

    def on_failed(request) -> None:
        if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"}:
            page_report["failed_requests"].append({"url": request.url, "failure": request.failure})

    page.on("response", on_response)
    page.on("request", on_request)
    page.on("requestfailed", on_failed)
    page.on("pageerror", lambda error: page_report["page_errors"].append(str(error)))
    page.on(
        "console",
        lambda message: page_report["console_errors"].append(message.text)
        if message.type == "error" else None,
    )
    return page_report


def consume_expected_http_error(
    page_report: dict,
    report: dict,
    *,
    status: int,
    path: str,
) -> None:
    matches = [
        item for item in page_report["http_errors"]
        if item["status"] == status and urlparse(item["url"]).path == path
    ]
    assert len(matches) == 1, page_report["http_errors"]
    page_report["http_errors"].remove(matches[0])
    report["expected_http_errors"].append(matches[0])

    console_matches = [
        message for message in page_report["console_errors"]
        if f"status of {status}" in message
    ]
    assert len(console_matches) <= 1, page_report["console_errors"]
    if console_matches:
        page_report["console_errors"].remove(console_matches[0])


def table_digest(db_path: Path, tables: tuple[str, ...]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    with sqlite3.connect(db_path, timeout=20) as db:
        for table in tables:
            rows = db.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            raw = json.dumps(rows, ensure_ascii=False, default=str, separators=(",", ":"))
            result[table] = {
                "count": len(rows),
                "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            }
    return result


def learning_state(db_path: Path) -> dict[str, dict[str, object]]:
    return table_digest(db_path, (
        "learning_events",
        "profile_snapshots",
        "learning_paths",
        "path_nodes",
        "plan_drafts",
        "plan_versions",
        "student_profiles",
    ))


def mastery_digest(db_path: Path) -> str:
    with sqlite3.connect(db_path, timeout=20) as db:
        rows = db.execute(
            "SELECT student_id, concept_mastery FROM student_profiles ORDER BY student_id"
        ).fetchall()
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


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
      const controls = [...document.querySelectorAll('button,a[href],input,select,textarea,summary')].filter(visible);
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
      const textNodes = [...document.querySelectorAll('button,a[href],h1,h2,h3,strong,p,span,label,small,summary')]
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
      const lowContrastPrimary = [...document.querySelectorAll('.primary-action,.login-submit')].filter(visible).map((el) => {
        const style = getComputedStyle(el), foreground = parseRgb(style.color), background = parseRgb(style.backgroundColor);
        if (!foreground || !background) return null;
        const high = Math.max(luminance(foreground), luminance(background));
        const low = Math.min(luminance(foreground), luminance(background));
        return { text: (el.innerText || '').trim().slice(0, 48), ratio: (high + .05) / (low + .05) };
      }).filter((item) => item && item.ratio < 4.5);
      const forbiddenEffects = [...document.querySelectorAll('.teacher-workspace *')].filter(visible).filter((el) => {
        const style = getComputedStyle(el);
        return style.backgroundImage.includes('gradient') || (style.backdropFilter && style.backdropFilter !== 'none');
      }).map((el) => String(el.className).slice(0, 80)).slice(0, 20);
      const themedColorRegression = [...document.querySelectorAll('.teacher-workspace *')].filter(visible).filter((el) => {
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


def capture(page: Page, report: dict, name: str, *, min_body_text: int = 150) -> None:
    page.evaluate("""() => {
      window.scrollTo(0, 0);
      const content = document.querySelector('.app-content');
      if (content) content.scrollTo(0, 0);
    }""")
    page.wait_for_timeout(250)
    metrics = visible_metrics(page)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["visual_checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    assert metrics["bodyTextLength"] > min_body_text, metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["lowContrastPrimary"], metrics
    assert not metrics["forbiddenEffects"], metrics
    assert not metrics["themedColorRegression"], metrics


def goto_teacher(page: Page, base_url: str, path: str, heading: str) -> None:
    page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=60_000)
    workspace = page.locator('[data-testid="teacher-workspace"]')
    workspace.wait_for(state="visible", timeout=30_000)
    workspace.get_by_role("heading", name=heading, exact=True, level=1).wait_for(
        state="visible", timeout=30_000
    )
    page.locator(".state-panel").filter(has_text="正在读取教学数据").wait_for(
        state="hidden", timeout=30_000
    )


def wait_query(page: Page, key: str, value: str) -> None:
    page.wait_for_function(
        "({ key, value }) => new URL(location.href).searchParams.get(key) === value",
        arg={"key": key, "value": value},
        timeout=30_000,
    )


def login_through_ui(page: Page, base_url: str, fixture: dict, report: dict) -> dict:
    page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=60_000)
    page.get_by_role("button", name="进入系统", exact=True).first.wait_for(state="visible", timeout=20_000)
    assert urlparse(page.url).path == "/landing", page.url
    page.get_by_role("button", name="进入系统", exact=True).first.click()
    page.locator('[data-testid="login-role-student"]').wait_for(state="visible", timeout=20_000)
    assert urlparse(page.url).path == "/login", page.url
    role_labels = page.locator('[data-testid^="login-role-"]').all_inner_texts()
    assert role_labels == ["学生", "教师", "管理员"], role_labels
    page.locator('[data-testid="login-role-teacher"]').click()
    page.locator('[data-testid="login-username"]').fill(fixture["usernames"]["teacher"])
    page.locator('[data-testid="login-password"]').fill(TEST_PASSWORD)
    page.locator('[data-testid="login-submit"]').click()
    page.wait_for_url("**/teacher/overview", timeout=30_000)
    page.locator('[data-testid="teacher-workspace"]').get_by_role(
        "heading", name="教学总览", exact=True, level=1
    ).wait_for(state="visible", timeout=30_000)
    session = page.evaluate("""() => ({
      access_token: localStorage.getItem('edumatrix_token'),
      username: localStorage.getItem('edumatrix_username'),
      display_name: localStorage.getItem('edumatrix_display_name'),
      role: localStorage.getItem('edumatrix_role'),
    })""")
    assert session["role"] == "teacher", session
    report["entry_order"] = ["/landing", "/login", "/teacher/overview"]
    return session


def run_teacher_journey(
    browser: Browser,
    base_url: str,
    fixture: dict,
    report: dict,
) -> dict:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        color_scheme="light",
    )
    page = context.new_page()
    page_report = attach_diagnostics(page, report)
    intervention_payloads: list[dict] = []

    def record_intervention(request) -> None:
        if request.method == "POST" and urlparse(request.url).path == "/api/v1/teacher/interventions":
            intervention_payloads.append(request.post_data_json)

    page.on("request", record_intervention)
    try:
        session = login_through_ui(page, base_url, fixture, report)
        page.locator(".state-panel").filter(has_text="正在读取教学数据").wait_for(
            state="hidden", timeout=30_000
        )
        course_select = page.locator("#overview-course")
        course_select.wait_for(state="visible", timeout=30_000)
        assert course_select.input_value() == fixture["course_id"]
        course_options = course_select.locator("option").all_inner_texts()
        assert course_options == ["可信 RAG 工程", "第二门视觉模型课程"], course_options
        capture(page, report, "1440x900_01_teacher_overview.png")

        page.locator("#overview-course").select_option(fixture["secondary_course_id"])
        wait_query(page, "courseId", fixture["secondary_course_id"])
        page.locator("#overview-course").select_option(fixture["course_id"])
        wait_query(page, "courseId", fixture["course_id"])

        goto_teacher(page, base_url, "/teacher/courses", "课程与资源")
        page.get_by_placeholder("搜索课程、方向或简介").fill("第二门")
        page.get_by_role("heading", name="第二门视觉模型课程", exact=True).wait_for(state="visible")
        assert page.locator(".course-row").count() == 1
        page.get_by_placeholder("搜索课程、方向或简介").fill("")
        assert page.locator(".course-row").count() == 2
        capture(page, report, "1440x900_02_teacher_courses.png")

        goto_teacher(
            page,
            base_url,
            f"/teacher/courses/{fixture['course_id']}",
            "可信 RAG 工程",
        )
        for tab in ("章节", "来源", "资源", "班级与任务"):
            page.get_by_role("tab", name=tab, exact=True).click()
            page.locator(".course-detail-section").wait_for(state="visible")
        page.get_by_role("tab", name="章节", exact=True).click()
        capture(page, report, "1440x900_03_teacher_course_detail.png")

        goto_teacher(
            page,
            base_url,
            f"/teacher/students?courseId={fixture['course_id']}",
            "学生学情",
        )
        page.get_by_placeholder("搜索姓名或账号").fill("学员一")
        page.get_by_role("button", name="查找", exact=True).click()
        wait_query(page, "q", "学员一")
        student_rows = page.locator(".student-row:not(.student-row--header)")
        page.wait_for_function(
            "() => document.querySelectorAll('.student-row:not(.student-row--header)').length === 1",
            timeout=30_000,
        )
        page.get_by_text("学员一", exact=True).wait_for(state="visible")
        assert student_rows.count() == 1
        student_row_text = student_rows.first.inner_text()
        assert "完成引用校验练习" in student_row_text
        assert '{"title"' not in student_row_text
        assert "/workspace?" not in student_row_text
        capture(page, report, "1440x900_04_teacher_students.png")

        browse_before = learning_state(DB_PATH)
        mastery_before = mastery_digest(DB_PATH)
        goto_teacher(
            page,
            base_url,
            f"/teacher/students/{fixture['learner_id']}?courseId={fixture['course_id']}",
            "学员一",
        )
        assert page.get_by_text("掌握度只读", exact=True).is_visible()
        assert page.get_by_text("混合检索与重排", exact=True).is_visible()
        page.locator(".weak-list details").first.locator("summary").click()
        weak_detail_text = page.locator(".weak-detail").first.inner_text()
        assert "建议动作：开始针对性学习" in weak_detail_text
        assert "建议理由：根据当前掌握区间进入对应强度的下一项学习任务。" in weak_detail_text
        assert '{"title"' not in weak_detail_text
        assert "/workspace?" not in weak_detail_text
        page.locator(".timeline details").first.locator("summary").click()
        page.locator(".agent-audit > summary").click()
        page.locator(".agent-list p").filter(
            has_text="分歧：候选难度存在分歧"
        ).wait_for(state="visible")
        body_text = page.locator("body").inner_text().lower()
        for forbidden in SENSITIVE_TERMS:
            assert forbidden not in body_text
        capture(page, report, "1440x900_05_teacher_student_detail.png")
        assert learning_state(DB_PATH) == browse_before
        report["ordinary_browse_database_unchanged"] = True

        page.route(
            "**/api/v1/teacher/students/f9-learner-1?*",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "isolated refresh failure"}),
            ),
            times=1,
        )
        page.get_by_role("button", name="刷新当前教学数据", exact=True).click()
        page.get_by_text("已保留上一次读取结果。", exact=False).wait_for(state="visible")
        assert page.get_by_text("混合检索与重排", exact=True).is_visible()
        page.get_by_role("button", name="重试", exact=True).click()
        page.get_by_text("已保留上一次读取结果。", exact=False).wait_for(state="hidden")
        report["refresh_failure_preserved_and_recovered"] = True

        page.get_by_role("button", name="创建学习干预", exact=True).click()
        page.get_by_text("干预任务已加入学生路径", exact=False).wait_for(state="visible", timeout=30_000)
        assert len(intervention_payloads) == 1, intervention_payloads
        replay = context.request.post(
            f"{base_url}/api/v1/teacher/interventions",
            headers=auth_headers(session),
            data=intervention_payloads[0],
        )
        assert replay.status == 201, replay.text()
        assert replay.json()["created"] is False, replay.json()

        after = learning_state(DB_PATH)
        assert after["learning_events"] == browse_before["learning_events"]
        assert after["profile_snapshots"] == browse_before["profile_snapshots"]
        assert after["student_profiles"] == browse_before["student_profiles"]
        assert after["learning_paths"]["count"] == browse_before["learning_paths"]["count"] + 1
        assert after["path_nodes"]["count"] == browse_before["path_nodes"]["count"] + 1
        assert after["plan_drafts"]["count"] == browse_before["plan_drafts"]["count"] + 1
        assert after["plan_versions"]["count"] == browse_before["plan_versions"]["count"] + 1
        assert mastery_digest(DB_PATH) == mastery_before
        report["intervention_idempotent"] = True
        report["mastery_unchanged"] = True
        report["intervention_payload"] = {
            "course_id": intervention_payloads[0]["course_id"],
            "learner_public_id": intervention_payloads[0]["learner_public_id"],
            "idempotency_key_present": bool(intervention_payloads[0].get("idempotency_key")),
        }

        consume_expected_http_error(
            page_report,
            report,
            status=503,
            path="/api/v1/teacher/students/f9-learner-1",
        )
        return session
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
        for role in ("learner_1", "assistant"):
            session = api_login(request_context.request, base_url, fixture["usernames"][role])
            response = request_context.request.get(
                f"{base_url}/api/v1/teacher/courses",
                headers=auth_headers(session),
            )
            assert response.status == 403, (role, response.status, response.text())
    finally:
        request_context.close()

    for role in ("learner_1", "assistant"):
        context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
        session = api_login(context.request, base_url, fixture["usernames"][role])
        add_session(context, session, fixture)
        page = context.new_page()
        page_report = attach_diagnostics(page, report)
        try:
            page.goto(f"{base_url}/teacher/overview", wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(1200)
            assert urlparse(page.url).path != "/teacher/overview", (role, page.url)
            assert not page.locator('[data-testid="teacher-workspace"]').is_visible()
            if role == "learner_1" and page_report["http_errors"]:
                consume_expected_http_error(
                    page_report,
                    report,
                    status=403,
                    path="/api/v1/competition-demo/context",
                )
            assert not page_report["page_errors"], page_report
        finally:
            context.close()

    context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
    session = api_login(context.request, base_url, fixture["usernames"]["empty_teacher"])
    add_session(context, session, fixture)
    page = context.new_page()
    attach_diagnostics(page, report)
    try:
        goto_teacher(page, base_url, "/teacher/overview", "教学总览")
        page.get_by_text("暂无可查看课程", exact=True).wait_for(state="visible")
        capture(page, report, "1366x768_06_teacher_empty.png", min_body_text=100)
    finally:
        context.close()


def run_compact_teacher(
    browser: Browser,
    base_url: str,
    fixture: dict,
    report: dict,
) -> None:
    context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
    session = api_login(context.request, base_url, fixture["usernames"]["teacher"])
    add_session(context, session, fixture)
    page = context.new_page()
    attach_diagnostics(page, report)
    try:
        goto_teacher(page, base_url, "/teacher/overview", "教学总览")
        capture(page, report, "1366x768_07_teacher_overview.png")
        goto_teacher(
            page,
            base_url,
            f"/teacher/students/{fixture['learner_id']}?courseId={fixture['course_id']}",
            "学员一",
        )
        capture(page, report, "1366x768_08_teacher_student_detail.png")
    finally:
        context.close()


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
        "task": "F9-T02",
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "viewports": [list(item) for item in VIEWPORTS],
        "screenshots": [],
        "visual_checks": {},
        "browser_pages": [],
        "expected_http_errors": [],
        "ordinary_browse_database_unchanged": False,
        "refresh_failure_preserved_and_recovered": False,
        "intervention_idempotent": False,
        "mastery_unchanged": False,
        "external_model_called": False,
    }
    browser = playwright.chromium.launch(headless=True)
    try:
        run_teacher_journey(browser, base_url, fixture, report)
        run_role_boundaries(browser, base_url, fixture, report)
        run_compact_teacher(browser, base_url, fixture, report)
        assert_browser_clean(report)
        audit = database_audit(DB_PATH)
        assert audit["integrity"] == "ok", audit
        assert audit["foreign_key_violations"] == 0, audit
        report["database_audit"] = audit
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
