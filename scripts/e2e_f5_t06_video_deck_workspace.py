"""F5-T06 video recommendation and deck desktop E2E on isolated SQLite."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Page, sync_playwright

from e2e_f5_t05_training_task_workspace import (
    login,
    port_open,
    start_service,
    stop_service,
    table_digest,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f5_t06_video_deck"
COURSE_ID = "demo-course-rag-trust-v1"
USERNAME = "lzz"
PORT_START = int(os.getenv("EDUMATRIX_F5_T06_PORT", "9001"))
VIDEO_ID = "f5-t06-video"
EMPTY_VIDEO_ID = "f5-t06-empty-video"
DECK_ID = "f5-t06-deck"
SOURCE_ID = "f5-t06-source"
SOURCE_REF_ID = "f5-t06-source-ref"
LOCAL_RECOMMENDATION_ID = "packaged-gradient-demo"
LOCAL_VIDEO_RELATIVE = "animations/梯度下降/Gradient Descent in 3 minutes_qg4PchTECck.mp4"


def external_video_content() -> dict:
    return {
        "schemaVersion": "f5.video-recommendation.v1",
        "title": "梯度下降视频推荐",
        "summary": "优先展示来源和许可边界明确的视频入口。",
        "learningGoal": "通过可信视频来源补充理解梯度下降的方向与步长。",
        "adaptationSummary": "当前画像需要先建立机制概览，再进入代码和实训。",
        "recommendations": [{
            "id": "external-gradient-course",
            "title": "公开课程视频页",
            "sourceKind": "external_url",
            "availability": "external_only",
            "url": "https://ml-course.github.io/master/",
            "localRef": None,
            "durationSeconds": None,
            "author": "ML Course 页面维护者",
            "language": "English",
            "licenseStatus": "reference_only_unverified",
            "licenseLabel": "仅提供来源页链接，不下载、不镜像、不分发视频。",
            "licenseUrl": "https://ml-course.github.io/master/",
            "reason": "与当前知识点和课程实训链路一致，适合先建立机制概览。",
            "segments": [],
            "sourceRefIds": [SOURCE_REF_ID],
            "alternatives": [{
                "id": "external-alternative",
                "title": "VU Machine Learning",
                "url": "https://mlvu.github.io/",
                "reason": "原来源不可访问时使用另一条已登记课程来源。",
            }],
        }],
    }


def current_video_content() -> dict:
    return {
        "schemaVersion": "f5.video-recommendation.v1",
        "title": "梯度下降视频推荐",
        "summary": "在许可边界内提供已登记演示片段，并保留失效来源的诚实状态。",
        "learningGoal": "观察梯度下降的方向和步长，再回到讲义或实训验证。",
        "adaptationSummary": "根据当前画像先提供短视频概览，不把观看行为当作掌握证据。",
        "recommendations": [
            {
                "id": LOCAL_RECOMMENDATION_ID,
                "title": "梯度下降本地演示素材",
                "sourceKind": "local_ref",
                "availability": "playable",
                "url": None,
                "localRef": f"/api/v1/m5/resources/{VIDEO_ID}/video-media/{LOCAL_RECOMMENDATION_ID}",
                "durationSeconds": 180,
                "author": "EduMatrix 隔离 E2E 夹具",
                "language": "中文说明 / 英文画面",
                "licenseStatus": "packaged_demo",
                "licenseLabel": "仅作为隔离浏览器测试的已登记演示素材，不宣称为原创课程视频。",
                "licenseUrl": None,
                "reason": "用于验证受控本地播放、分段跳转、笔记和来源边界。",
                "segments": [
                    {"id": "segment-direction", "title": "更新方向", "startSeconds": 12, "endSeconds": 28, "learningFocus": "观察负梯度方向。"},
                    {"id": "segment-step", "title": "步长影响", "startSeconds": 45, "endSeconds": 62, "learningFocus": "比较学习率对更新幅度的影响。"},
                ],
                "sourceRefIds": [SOURCE_REF_ID],
                "alternatives": [{
                    "id": "local-alternative",
                    "title": "公开课程视频页",
                    "url": "https://ml-course.github.io/master/",
                    "reason": "本地演示素材不可读取时查看已登记来源页。",
                }],
            },
            {
                "id": "unavailable-video",
                "title": "失效公开视频入口",
                "sourceKind": "external_url",
                "availability": "unavailable",
                "url": "https://mlvu.github.io/",
                "localRef": None,
                "durationSeconds": None,
                "author": "历史来源维护者",
                "language": "English",
                "licenseStatus": "platform_link_only",
                "licenseLabel": "当前只保留来源页和替代项，不声称可播放。",
                "licenseUrl": "https://mlvu.github.io/",
                "reason": "保留历史来源事实，并明确当前不可播放。",
                "segments": [],
                "sourceRefIds": [SOURCE_REF_ID],
                "alternatives": [{
                    "id": "unavailable-alternative",
                    "title": "ML Course 公开课程页",
                    "url": "https://ml-course.github.io/master/",
                    "reason": "当前来源失效时使用可访问的已登记替代来源。",
                }],
            },
        ],
    }


def empty_video_content() -> dict:
    return {
        "schemaVersion": "f5.video-recommendation.v1",
        "title": "暂无可核验视频",
        "summary": "当前没有满足来源和许可要求的视频。",
        "learningGoal": "改用讲义、思维导图或实训任务继续学习。",
        "adaptationSummary": "系统不为填充页面而伪造视频来源。",
        "recommendations": [],
    }


def deck_content(version: int) -> dict:
    historical = version == 1
    return {
        "schemaVersion": "f5.deck.v1",
        "title": "梯度下降课件" if historical else "梯度下降结构化课件",
        "summary": "第一版只建立基本概念。" if historical else "从问题、机制到下一步学习的结构化课件。",
        "learningGoal": "辨认梯度方向。" if historical else "解释梯度下降并辨认学习率的适用边界。",
        "adaptationSummary": "第一版保持低信息密度。" if historical else "按当前画像减少公式密度，保留来源、讲者备注和实践入口。",
        "slides": [
            {
                "id": "slide-title",
                "layout": "title",
                "title": "梯度下降",
                "subtitle": "从方向到步长",
                "body": "",
                "bullets": [],
                "speakerNotes": "说明课件来自冻结课程上下文。",
                "sourceRefIds": [SOURCE_REF_ID],
            },
            {
                "id": "slide-mechanism",
                "layout": "content",
                "title": "核心机制",
                "subtitle": "沿负梯度方向更新",
                "body": "梯度给出局部最陡上升方向，因此参数沿相反方向更新。",
                "bullets": ["确定方向", "控制步长", "检查收敛"],
                "speakerNotes": "结合课程来源解释更新式。",
                "sourceRefIds": [SOURCE_REF_ID],
            },
        ] + ([] if historical else [{
            "id": "slide-next",
            "layout": "closing",
            "title": "下一步学习",
            "subtitle": "回到实训验证",
            "body": "进入代码沙盒或实训任务书，用真实运行结果验证理解。",
            "bullets": ["先看任务书", "再运行代码", "最后提交证据"],
            "speakerNotes": "课件不代替实训或正式测评。",
            "sourceRefIds": [SOURCE_REF_ID],
        }]),
    }


def free_port() -> int:
    for port in range(PORT_START, PORT_START + 30):
        if not port_open(port):
            return port
    raise RuntimeError("no free F5-T06 E2E port")


def clear_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def runtime_env(db_path: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(db_path),
        "EDUMATRIX_AUTH_SECRET_KEY": "f5-t06-isolated-secret",
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
    return env


def seed_fixture(env: dict[str, str]) -> None:
    source_path = OUTPUT_DIR / "course-source.md"
    source_text = (
        "# 机器学习工程课程讲义\n\n"
        "## 梯度下降\n\n"
        "梯度给出局部最陡上升方向，参数沿相反方向更新。"
        "学习率控制每次更新幅度，应结合收敛过程判断。\n"
    )
    source_path.write_text(source_text, encoding="utf-8")
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    local_path = ROOT / "data" / Path(LOCAL_VIDEO_RELATIVE)
    if not local_path.is_file():
        raise RuntimeError(f"local video fixture is missing: {local_path}")
    payloads = {
        "video_v1": json.dumps(external_video_content(), ensure_ascii=False),
        "video_v2": json.dumps(current_video_content(), ensure_ascii=False),
        "empty_video": json.dumps(empty_video_content(), ensure_ascii=False),
        "deck_v1": json.dumps(deck_content(1), ensure_ascii=False),
        "deck_v2": json.dumps(deck_content(2), ensure_ascii=False),
    }
    encoded = {key: repr(value) for key, value in payloads.items()}
    script = f'''
from app.competition_demo_seed import seed_competition_demo
from app.database import DBArtifact, DBCourse, DBSourceDocument, DBSourceRef, DBUser, SessionLocal, init_db
from app.m1_repository import add_artifact_version

init_db()
db = SessionLocal()
try:
    seed_competition_demo(db)
    owner = db.query(DBUser).filter_by(username={USERNAME!r}).one()
    course = db.get(DBCourse, {COURSE_ID!r})
    if course is None:
        raise RuntimeError("demo course is missing")
    source = DBSourceDocument(
        id={SOURCE_ID!r}, course_id=course.id, legacy_document_id="f5-t06-course-source",
        title="优化算法课程讲义", filename="course-source.md", file_format="markdown",
        file_size={len(source_path.read_bytes())}, source_path={str(source_path.relative_to(ROOT))!r},
        content_hash={source_hash!r}, source_sha256={source_hash!r}, processed_sha256={source_hash!r},
        parser_version="f5-t06-e2e-parser", parser_metadata={{"paragraph_count": 3}},
        license_text="isolated E2E fixture", processing_status="ready",
    )
    db.add(source)
    db.flush()
    source_ref = DBSourceRef(
        id={SOURCE_REF_ID!r}, source_document_id=source.id, parser_version="f5-t06-e2e-parser",
        location_kind="section", location_index=1, location_label="第 2 章 梯度下降",
        char_start=16, char_end=90, quote="梯度给出局部最陡上升方向",
        content_hash={source_hash!r},
    )
    db.add(source_ref)
    db.flush()

    def add_resource(artifact_id, artifact_type, title, content, metadata):
        artifact = DBArtifact(
            id=artifact_id, owner_public_id=owner.public_id, course_id=course.id,
            artifact_type=artifact_type, title=title, status="published",
        )
        db.add(artifact)
        db.flush()
        version = add_artifact_version(
            db, artifact=artifact, content=content, content_format="json",
            created_by_public_id=owner.public_id, metadata=metadata,
        )
        artifact.status = "published"
        return artifact, version

    video, video_v1 = add_resource(
        {VIDEO_ID!r}, "video", "梯度下降视频推荐", {encoded['video_v1']},
        {{"resource_type": "video", "module": "第二章 优化算法", "knowledge_point_title": "梯度下降", "source_ref_ids": [{SOURCE_REF_ID!r}]}},
    )
    video_v2 = add_artifact_version(
        db, artifact=video, content={encoded['video_v2']}, content_format="json",
        created_by_public_id=owner.public_id,
        metadata={{"resource_type": "video", "module": "第二章 优化算法", "knowledge_point_title": "梯度下降", "source_ref_ids": [{SOURCE_REF_ID!r}], "local_video_files": {{{LOCAL_RECOMMENDATION_ID!r}: {LOCAL_VIDEO_RELATIVE!r}}}}},
    )
    video.status = "published"
    empty_video, empty_version = add_resource(
        {EMPTY_VIDEO_ID!r}, "video", "暂无可核验视频", {encoded['empty_video']},
        {{"resource_type": "video", "module": "第二章 优化算法", "knowledge_point_title": "梯度下降", "source_ref_ids": [{SOURCE_REF_ID!r}]}},
    )
    deck, deck_v1 = add_resource(
        {DECK_ID!r}, "deck", "梯度下降课件", {encoded['deck_v1']},
        {{"resource_type": "deck", "module": "第二章 优化算法", "knowledge_point_title": "梯度下降", "source_ref_ids": [{SOURCE_REF_ID!r}]}},
    )
    deck_v2 = add_artifact_version(
        db, artifact=deck, content={encoded['deck_v2']}, content_format="json",
        created_by_public_id=owner.public_id, metadata=deck_v1.metadata_json,
    )
    deck.status = "published"
    db.commit()
    print({{
        "video_v1": video_v1.id, "video_v2": video_v2.id,
        "empty_video": empty_version.id, "deck_v1": deck_v1.id, "deck_v2": deck_v2.id,
    }})
finally:
    db.close()
'''
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode:
        raise RuntimeError(f"fixture seed failed:\n{result.stdout}\n{result.stderr}")


def fixture_ids(db_path: Path) -> dict[str, str]:
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            "SELECT artifact_id,version_number,id FROM artifact_versions "
            "WHERE artifact_id IN (?,?,?) ORDER BY artifact_id,version_number",
            (VIDEO_ID, EMPTY_VIDEO_ID, DECK_ID),
        ).fetchall()
    return {
        f"{artifact_id}_{version_number}": version_id
        for artifact_id, version_number, version_id in rows
    }


def protected_state(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        owner = db.execute("SELECT public_id FROM users WHERE username=?", (USERNAME,)).fetchone()[0]
        return {
            "learning_events": table_digest(
                db, "SELECT id,event_type,evidence_status,evidence_strength,mastery_eligible,completion_effect,payload "
                "FROM learning_events WHERE owner_public_id=? ORDER BY id", (owner,),
            ),
            "profile_snapshots": table_digest(
                db, "SELECT id,profile_version,snapshot,content_hash FROM profile_snapshots "
                "WHERE owner_public_id=? ORDER BY id", (owner,),
            ),
            "path_nodes": table_digest(
                db, "SELECT n.id,n.status,n.actual_minutes FROM path_nodes n "
                "JOIN learning_paths p ON p.id=n.learning_path_id WHERE p.owner_public_id=? ORDER BY n.id", (owner,),
            ),
            "exam_gate_inputs": table_digest(
                db, "SELECT e.id,e.event_type,e.payload FROM task_events e JOIN generation_tasks t ON t.id=e.task_id "
                "WHERE t.owner_public_id=? AND e.payload LIKE '%exam_gate%' ORDER BY e.id", (owner,),
            ),
            "formal_exams": table_digest(
                db, "SELECT id,status,current_version_id,lock_version FROM assessment_exams "
                "WHERE owner_public_id=? ORDER BY id", (owner,),
            ),
        }


def database_audit(db_path: Path) -> dict[str, object]:
    with sqlite3.connect(db_path, timeout=10) as db:
        versions = db.execute(
            "SELECT artifact_id,version_number,content_hash FROM artifact_versions "
            "WHERE artifact_id IN (?,?) ORDER BY artifact_id,version_number",
            (VIDEO_ID, DECK_ID),
        ).fetchall()
        return {
            "integrity": db.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
            "versions": versions,
        }


def page_diagnostics(page: Page, report: dict, expected_conflict: dict[str, bool]) -> None:
    def record_response(response) -> None:
        if response.status < 400:
            return
        item = {"status": response.status, "url": response.url}
        if expected_conflict["active"] and response.status == 409 and f"/resources/{DECK_ID}/versions" in response.url:
            report["expected_http_errors"].append(item)
        else:
            report["http_errors"].append(item)

    def record_request(request) -> None:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        item = {"method": request.method, "url": request.url}
        report["write_requests"].append(item)
        if "/api/v1/m5/context/resolve" in request.url:
            item["context"] = (request.post_data_json or {}).get("context", {})
            report["infrastructure_writes"].append(item)
        elif request.method == "POST" and f"/api/v1/m5/resources/{DECK_ID}/versions" in request.url:
            report["business_writes"].append(item)
        else:
            report["unexpected_write_requests"].append(item)

    def record_console(message) -> None:
        if message.type != "error":
            return
        if expected_conflict["active"] and "Failed to load resource" in message.text:
            report["expected_console_errors"].append(message.text)
        else:
            report["console_errors"].append(message.text)

    page.on("response", record_response)
    page.on("request", record_request)
    page.on("requestfailed", lambda request: report["failed_requests"].append({
        "url": request.url, "failure": request.failure,
    }) if request.failure not in {"net::ERR_ABORTED", "net::ERR_CANCELED"} else None)
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", record_console)


def visible_metrics(page: Page, root_selector: str) -> dict:
    return page.evaluate("""(rootSelector) => {
      const root = document.querySelector(rootSelector);
      const visible = (el) => {
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          Number(style.opacity) > 0 && rect.width > 1 && rect.height > 1;
      };
      const elements = root ? [root, ...root.querySelectorAll('*')] : [];
      const controls = elements.filter((el) => el.matches('button,a[href],input,select,textarea') && visible(el));
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
        if (style.textOverflow === 'ellipsis' || style.webkitLineClamp !== 'none') return false;
        return rect.right > innerWidth + 1 || rect.left < -1 ||
          (el.scrollWidth > el.clientWidth + 4 && style.whiteSpace !== 'nowrap' && style.overflowX !== 'auto');
      }).map((el) => (el.innerText || '').trim().slice(0, 80)).filter(Boolean).slice(0, 20);
      const smallText = elements.filter((el) => {
        const text = (el.innerText || '').replaceAll('\u200b', '').trim();
        return visible(el) && el.children.length === 0 && text &&
          Number.parseFloat(getComputedStyle(el).fontSize) < 13.5;
      }).map((el) => ({ text: el.innerText.replaceAll('\u200b', '').trim().slice(0, 40), size: getComputedStyle(el).fontSize })).slice(0, 20);
      const forbiddenEffects = elements.filter(visible).filter((el) => {
        const style = getComputedStyle(el);
        return (style.backgroundImage || '').includes('gradient') ||
          !['none', ''].includes(style.backdropFilter || 'none');
      }).map((el) => el.className?.toString().slice(0, 80)).slice(0, 20);
      const rootStyle = root ? getComputedStyle(root) : null;
      const primary = root?.querySelector('.primary-button');
      return {
        viewport: [innerWidth, innerHeight],
        documentWidth: document.documentElement.scrollWidth,
        bodyTextLength: (root?.innerText || '').trim().length,
        pageBackground: rootStyle?.backgroundColor || '',
        primaryBackground: primary ? getComputedStyle(primary).backgroundColor : '',
        collisions, clipped, smallText, forbiddenEffects,
      };
    }""", root_selector)


def capture(page: Page, report: dict, name: str, root_selector: str, minimum_text: int = 120) -> None:
    page.wait_for_timeout(350)
    metrics = visible_metrics(page, root_selector)
    page.screenshot(path=str(OUTPUT_DIR / name), full_page=True, animations="disabled")
    report["screenshots"].append(name)
    report["checks"][name] = metrics
    assert metrics["documentWidth"] <= metrics["viewport"][0], metrics
    if metrics["bodyTextLength"] < minimum_text:
        raise AssertionError({
            "metrics": metrics,
            "url": page.url,
            "body_text": page.locator("body").inner_text()[:1200],
            "stored_context": page.evaluate(
                "JSON.parse(localStorage.getItem('edumatrix_context_ref') || '{}')"
            ),
        })
    assert metrics["pageBackground"] == "rgb(245, 247, 247)", metrics
    if metrics["primaryBackground"]:
        assert metrics["primaryBackground"] == "rgb(17, 33, 45)", metrics
    assert not metrics["collisions"], metrics
    assert not metrics["clipped"], metrics
    assert not metrics["smallText"], metrics
    assert not metrics["forbiddenEffects"], metrics


def assert_safe_context_url(url: str, allowed_keys: set[str]) -> dict[str, list[str]]:
    query = parse_qs(urlparse(url).query)
    assert set(query) <= allowed_keys, query
    serialized = json.dumps(query, ensure_ascii=False).lower()
    for forbidden in ("gold", "failure_branch", "api_key", "prompt", "password"):
        assert forbidden not in serialized, query
    return query


def open_video(page: Page, base_url: str, resource_id: str, return_to: str = "") -> None:
    suffix = f"?course_id={COURSE_ID}"
    if return_to:
        suffix += f"&return_to={return_to}"
    page.goto(f"{base_url}/workspace/resources/videos/{resource_id}{suffix}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("video-recommendation-workspace").wait_for(state="visible")


def open_deck(page: Page, base_url: str, return_to: str = "") -> None:
    suffix = f"?course_id={COURSE_ID}"
    if return_to:
        suffix += f"&return_to={return_to}"
    page.goto(f"{base_url}/workspace/resources/decks/{DECK_ID}{suffix}", wait_until="networkidle", timeout=60_000)
    page.get_by_test_id("web-deck-workspace").wait_for(state="visible")


def exercise_video(page: Page, base_url: str, ids: dict[str, str], report: dict) -> None:
    open_video(page, base_url, VIDEO_ID, f"/workspace/resources?course_id={COURSE_ID}")
    page.get_by_test_id("video-player").wait_for(state="visible", timeout=45_000)
    page.get_by_text("梯度下降本地演示素材", exact=True).last.wait_for(state="visible")
    page.get_by_text("学习目标", exact=True).wait_for(state="visible")
    page.get_by_text("适配依据", exact=True).wait_for(state="visible")
    capture(page, report, "01-video-local-1440x900.png", '[data-testid="video-recommendation-workspace"]')

    page.get_by_role("button", name="步长影响", exact=False).click()
    try:
        page.wait_for_function(
            """() => {
              const video = document.querySelector('[data-testid="video-player"]');
              return Boolean(video && video.currentTime >= 44);
            }""",
            timeout=10_000,
        )
    except Exception:
        media_state = page.get_by_test_id("video-player").evaluate(
            """video => ({
              currentTime: video.currentTime,
              duration: video.duration,
              readyState: video.readyState,
              networkState: video.networkState,
              error: video.error ? { code: video.error.code, message: video.error.message } : null,
            })"""
        )
        raise AssertionError(media_state)
    current_time = page.get_by_test_id("video-player").evaluate("video => video.currentTime")
    assert current_time >= 44, current_time
    report["segment_jump"] = {"target_seconds": 45, "actual_seconds": current_time}

    note = page.get_by_label("视频学习笔记草稿")
    note.fill("比较学习率过大与过小时的收敛表现。")
    page.get_by_role("button", name="保存草稿", exact=True).click()
    page.reload(wait_until="networkidle")
    page.get_by_test_id("video-player").wait_for(state="visible", timeout=45_000)
    assert page.get_by_label("视频学习笔记草稿").input_value() == "比较学习率过大与过小时的收敛表现。"
    report["note_refresh_restored"] = True

    source_button = page.get_by_role("button", name="优化算法课程讲义", exact=False).last
    source_button.click()
    page.wait_for_url(lambda url: "/knowledge/documents/" in url, timeout=30_000)
    report["video_source_link"] = assert_safe_context_url(
        page.url, {"canonical_source_id", "course_id", "focus_source_ref_id", "return_to", "version_id"},
    )
    page.go_back(wait_until="networkidle")
    page.get_by_test_id("video-recommendation-workspace").wait_for(state="visible")

    page.get_by_role("button", name="针对当前内容提问", exact=True).click()
    page.wait_for_url(lambda url: urlparse(url).path in {"/learn", "/chat"}, timeout=30_000)
    report["video_question_link"] = assert_safe_context_url(
        page.url, {"course_id", "resource_id", "version_id", "recommendation_id", "segment_id", "context", "return_to"},
    )
    page.go_back(wait_until="networkidle")
    page.get_by_test_id("video-recommendation-workspace").wait_for(state="visible")

    page.get_by_role("button", name="失效公开视频入口", exact=False).click()
    try:
        page.get_by_text("当前来源不可播放", exact=True).wait_for(state="visible")
    except Exception:
        raise AssertionError({
            "url": page.url,
            "body_text": page.locator("body").inner_text()[:1200],
            "stored_context": page.evaluate(
                "JSON.parse(localStorage.getItem('edumatrix_context_ref') || '{}')"
            ),
        })
    page.get_by_text("当前只保留来源页和替代项，不声称可播放。", exact=True).wait_for(state="visible")
    capture(page, report, "02-video-unavailable-1440x900.png", '[data-testid="video-recommendation-workspace"]')

    page.get_by_label("选择视频推荐版本").select_option(ids[f"{VIDEO_ID}_1"])
    page.wait_for_url(lambda url: f"version_id={ids[f'{VIDEO_ID}_1']}" in url, timeout=30_000)
    page.get_by_text("该来源仅支持外链观看", exact=True).wait_for(state="visible")
    page.get_by_text("VU Machine Learning", exact=True).wait_for(state="visible")
    capture(page, report, "03-video-external-history-1440x900.png", '[data-testid="video-recommendation-workspace"]')
    historical_url = page.url
    page.reload(wait_until="networkidle")
    page.get_by_text("该来源仅支持外链观看", exact=True).wait_for(state="visible")
    assert page.url == historical_url
    report["video_history_refresh_restored"] = True

    open_video(page, base_url, EMPTY_VIDEO_ID)
    page.get_by_text("暂无可核验的视频来源", exact=True).wait_for(state="visible")
    page.get_by_text("系统不会生成或伪造视频文件", exact=False).wait_for(state="visible")
    capture(page, report, "04-video-honest-empty-1440x900.png", '[data-testid="video-recommendation-workspace"]', 80)


def exercise_deck(page: Page, base_url: str, ids: dict[str, str], report: dict, expected_conflict: dict[str, bool]) -> None:
    open_deck(page, base_url, f"/workspace/resources?course_id={COURSE_ID}")
    assert page.locator(".outline-row").count() == 3
    page.get_by_text("学习目标与适配依据", exact=True).wait_for(state="visible")
    capture(page, report, "05-deck-current-1440x900.png", '[data-testid="web-deck-workspace"]')

    page.get_by_role("button", name="下一页", exact=True).click()
    page.get_by_role("heading", name="核心机制", exact=True).wait_for(state="visible")
    page.get_by_role("button", name="编辑当前版本", exact=True).click()
    page.get_by_label("课件标题").fill("梯度下降课件浏览器修订版")
    page.get_by_label("适配摘要").fill("从机制、边界和实践入口组织本次课件。")
    page.get_by_label("学习目标").fill("能够解释梯度方向并判断学习率过大或过小的风险。")
    page.get_by_label("适配依据").fill("根据当前画像先给直观解释，再保留来源和实训入口。")
    page.get_by_label("页面标题").fill("梯度下降更新机制")
    page.get_by_label("讲者备注").fill("先解释方向，再说明步长。")
    page.get_by_role("heading", name="梯度下降课件浏览器修订版", exact=True).wait_for(state="visible")
    page.get_by_role("heading", name="梯度下降更新机制", exact=True).wait_for(state="visible")
    capture(page, report, "06-deck-editing-1440x900.png", '[data-testid="web-deck-workspace"]')
    page.get_by_role("button", name="保存为新版本", exact=True).click()
    page.get_by_text("新版本已保存", exact=False).wait_for(state="visible")
    page.get_by_role("heading", name="梯度下降课件浏览器修订版", exact=True).wait_for(state="visible")
    assert page.get_by_label("选择课件版本").locator("option").count() == 3
    capture(page, report, "07-deck-saved-version-1440x900.png", '[data-testid="web-deck-workspace"]')

    page.get_by_role("button", name="针对此页提问", exact=True).click()
    page.wait_for_url(lambda url: urlparse(url).path in {"/learn", "/chat"}, timeout=30_000)
    report["deck_question_link"] = assert_safe_context_url(
        page.url, {"course_id", "resource_id", "version_id", "slide_id", "context", "return_to"},
    )
    page.go_back(wait_until="networkidle")
    page.get_by_test_id("web-deck-workspace").wait_for(state="visible")

    source_button = page.get_by_role("button", name="优化算法课程讲义", exact=False).last
    source_button.click()
    page.wait_for_url(lambda url: "/knowledge/documents/" in url, timeout=30_000)
    report["deck_source_link"] = assert_safe_context_url(
        page.url, {"canonical_source_id", "course_id", "focus_source_ref_id", "return_to", "version_id"},
    )
    page.go_back(wait_until="networkidle")
    page.get_by_test_id("web-deck-workspace").wait_for(state="visible")

    html_path = OUTPUT_DIR / "exported-deck.html"
    pptx_path = OUTPUT_DIR / "exported-deck.pptx"
    with page.expect_download(timeout=30_000) as download_info:
        page.get_by_role("button", name="导出 HTML", exact=True).click()
    download_info.value.save_as(html_path)
    with page.expect_download(timeout=30_000) as download_info:
        page.get_by_role("button", name="导出 PPTX", exact=True).click()
    download_info.value.save_as(pptx_path)
    assert html_path.stat().st_size > 500
    assert pptx_path.stat().st_size > 1_000
    report["exports"] = {"html_bytes": html_path.stat().st_size, "pptx_bytes": pptx_path.stat().st_size}

    def conflict_once(route) -> None:
        expected_conflict["active"] = True
        route.fulfill(
            status=409,
            content_type="application/json",
            body=json.dumps({"detail": {"code": "resource_version_conflict", "message": "隔离冲突注入"}}, ensure_ascii=False),
        )

    pattern = f"**/api/v1/m5/resources/{DECK_ID}/versions"
    page.route(pattern, conflict_once, times=1)
    page.get_by_role("button", name="编辑当前版本", exact=True).click()
    page.get_by_label("课件标题").fill("必须保留的冲突草稿")
    page.get_by_label("页面标题").fill("必须保留的冲突页面")
    page.get_by_role("button", name="保存为新版本", exact=True).click()
    page.get_by_text("你的草稿仍保留", exact=False).wait_for(state="visible")
    assert page.get_by_label("课件标题").input_value() == "必须保留的冲突草稿"
    assert page.get_by_label("页面标题").input_value() == "必须保留的冲突页面"
    page.get_by_role("heading", name="必须保留的冲突草稿", exact=True).wait_for(state="visible")
    capture(page, report, "08-deck-conflict-draft-preserved-1440x900.png", '[data-testid="web-deck-workspace"]')
    expected_conflict["active"] = False
    report["conflict_draft_preserved"] = True
    page.get_by_role("button", name="取消编辑", exact=True).click()

    page.get_by_label("选择课件版本").select_option(ids[f"{DECK_ID}_1"])
    page.wait_for_url(lambda url: f"version_id={ids[f'{DECK_ID}_1']}" in url, timeout=30_000)
    page.get_by_text("正在只读查看历史版本 v1", exact=False).wait_for(state="visible")
    assert page.get_by_role("button", name="编辑当前版本", exact=True).is_disabled()
    historical_url = page.url
    page.reload(wait_until="networkidle")
    page.get_by_text("正在只读查看历史版本 v1", exact=False).wait_for(state="visible")
    assert page.url == historical_url
    capture(page, report, "09-deck-history-readonly-1440x900.png", '[data-testid="web-deck-workspace"]')
    report["deck_history_refresh_restored"] = True

    page.get_by_role("button", name="返回资源中心重新生成", exact=True).click()
    page.wait_for_url(lambda url: urlparse(url).path == "/workspace/resources", timeout=30_000)
    report["safe_return_to"] = page.url


def compact_viewport_checks(page: Page, base_url: str, ids: dict[str, str], report: dict) -> None:
    open_video(page, base_url, VIDEO_ID)
    page.get_by_test_id("video-player").wait_for(state="visible", timeout=45_000)
    capture(page, report, "10-video-local-1366x768.png", '[data-testid="video-recommendation-workspace"]')
    open_deck(page, base_url)
    page.get_by_test_id("deck-stage").wait_for(state="visible")
    capture(page, report, "11-deck-current-1366x768.png", '[data-testid="web-deck-workspace"]')


def run() -> dict:
    clear_output()
    db_path = OUTPUT_DIR / "f5_t06.sqlite3"
    port = free_port()
    env = runtime_env(db_path, port)
    seed_fixture(env)
    ids = fixture_ids(db_path)
    before = protected_state(db_path)
    base_url = f"http://127.0.0.1:{port}"
    report = {
        "schema_version": "f5-t06.video-deck-desktop.v1",
        "viewports": [[1440, 900], [1366, 768]],
        "port": port,
        "fixture_note": "The packaged local video is an isolated E2E fixture, not a claim of original course content.",
        "screenshots": [], "checks": {}, "segment_jump": {}, "exports": {},
        "note_refresh_restored": False, "video_history_refresh_restored": False,
        "deck_history_refresh_restored": False, "conflict_draft_preserved": False,
        "video_source_link": {}, "video_question_link": {}, "deck_source_link": {}, "deck_question_link": {},
        "safe_return_to": "", "protected_state_before": before, "protected_state_after": {},
        "database_audit": {}, "http_errors": [], "expected_http_errors": [],
        "failed_requests": [], "write_requests": [], "infrastructure_writes": [],
        "business_writes": [], "unexpected_write_requests": [],
        "console_errors": [], "expected_console_errors": [], "page_errors": [],
        "process_cleanup": {}, "result": "failed",
    }
    expected_conflict = {"active": False}
    process: subprocess.Popen | None = None
    try:
        process = start_service(env, port, OUTPUT_DIR / "backend.log")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN", accept_downloads=True)
                page = context.new_page()
                page.set_default_timeout(30_000)
                login(page, base_url)
                page_diagnostics(page, report, expected_conflict)
                exercise_video(page, base_url, ids, report)
                exercise_deck(page, base_url, ids, report, expected_conflict)
                context.close()

                context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
                page = context.new_page()
                page.set_default_timeout(30_000)
                login(page, base_url)
                page_diagnostics(page, report, expected_conflict)
                compact_viewport_checks(page, base_url, ids, report)
                context.close()
            finally:
                browser.close()

        after = protected_state(db_path)
        report["protected_state_after"] = after
        assert after == before, {"before": before, "after": after}
        audit = database_audit(db_path)
        report["database_audit"] = audit
        assert audit["integrity"] == "ok"
        assert audit["foreign_key_violations"] == 0
        video_versions = [row for row in audit["versions"] if row[0] == VIDEO_ID]
        deck_versions = [row for row in audit["versions"] if row[0] == DECK_ID]
        assert len(video_versions) == 2
        assert len(deck_versions) == 3
        assert report["note_refresh_restored"]
        assert report["video_history_refresh_restored"]
        assert report["deck_history_refresh_restored"]
        assert report["conflict_draft_preserved"]
        assert report["exports"]["html_bytes"] > 500 and report["exports"]["pptx_bytes"] > 1_000
        assert len(report["expected_http_errors"]) == 1
        assert report["business_writes"] and all(
            item["method"] == "POST" and f"/resources/{DECK_ID}/versions" in item["url"]
            for item in report["business_writes"]
        )
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["unexpected_write_requests"], report["unexpected_write_requests"]
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
            "protected_state_unchanged": result["protected_state_before"] == result["protected_state_after"],
            "segment_jump": result["segment_jump"],
            "exports": result["exports"],
            "business_writes": len(result["business_writes"]),
            "database_audit": result["database_audit"],
            "process_cleanup": result["process_cleanup"],
        }, ensure_ascii=False, indent=2))
    except Exception:
        traceback.print_exc()
        raise
