"""Capture user-visible NOC-T23 profile adaptation evidence from the built SPA.

The browser harness uses API fixtures shaped like the canonical Chat and
resource-bundle responses.  It exercises the actual Vue components and writes
screenshots only under the NOC-T23 evidence directory; no production data is
changed.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"
OUT = ROOT / "outputs" / "新意见重构执行" / "evidence" / "noc_t23"
OUT.mkdir(parents=True, exist_ok=True)

try:
    from scripts.run_noc_t23_profile_evaluation import PROFILES, _profile_object
    from app.profile_adaptation import build_profile_adaptation, profile_prompt_context
except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT))
    from scripts.run_noc_t23_profile_evaluation import PROFILES, _profile_object
    from app.profile_adaptation import build_profile_adaptation, profile_prompt_context


@contextmanager
def frontend_server():
    class SpaHandler(SimpleHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            requested = DIST / parsed.path.lstrip("/")
            if not requested.is_file():
                self.path = "/index.html"
            super().do_GET()

        def log_message(self, _format, *_args):
            return

    def handler(*args, **kwargs):
        return SpaHandler(*args, directory=str(DIST), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def _profile_payload(raw: dict) -> tuple[dict, dict]:
    profile = _profile_object(raw)
    point = {"id": "kp-rag", "title": "混合检索", "code": "RAG-01"}
    # Keep the full adaptation projection for the fixture so the visible
    # summary and the machine-actionable plan are both present.  The real
    # application still exposes only the public projection to the model.
    adaptation = build_profile_adaptation(None, profile=profile, knowledge_point=point)
    return profile, adaptation


def _source() -> dict:
    return {
        "sourceRefId": "src-rag-industry-01",
        "source_ref_id": "src-rag-industry-01",
        "id": "src-rag-industry-01",
        "title": "检索工程课程：混合检索与评估",
        "locationLabel": "第 2 章 / 第 3 节",
        "location_label": "第 2 章 / 第 3 节",
        "quote": "关键词检索擅长精确术语、代码和 ID；向量检索通过 embedding 发现语义相似文本；混合检索需要统一排序并用 Recall@K 等指标评估。",
        "available": True,
    }


def _run_events(profile_id: str) -> list[dict]:
    return [
        {"eventId": f"run-{profile_id}", "eventType": "run.started", "status": "completed", "publicStatus": "completed", "owner": "Chat Orchestrator", "summary": "已接收问题并建立本轮运行。", "progress": 0.05},
        {"eventId": f"context-{profile_id}", "eventType": "stage.completed", "status": "completed", "publicStatus": "completed", "owner": "Context Builder", "stageId": "context_check", "summary": "已冻结课程、学习画像和来源。", "progress": 0.2},
        {"eventId": f"retrieval-{profile_id}", "eventType": "stage.started", "status": "running", "publicStatus": "running", "owner": "Retrieval", "stageId": "retrieval", "summary": "正在按当前课程范围检索证据。", "inputRefs": ["profile:" + profile_id], "progress": 0.45},
        {"eventId": f"pedagogy-{profile_id}", "eventType": "stage.started", "status": "running", "publicStatus": "running", "owner": "Pedagogical Agent", "stageId": "pedagogical", "summary": "正在按画像安排解释层次和下一步任务。", "inputRefs": ["profile:" + profile_id], "progress": 0.72},
    ]


def _conversation(profile_id: str, adaptation: dict) -> dict:
    source = _source()
    assistant = {
        "id": f"assistant-{profile_id}",
        "role": "assistant",
        "status": "completed",
        "sequence": 2,
        "content": (
            f"本轮按你的画像采用“{adaptation['difficulty_label']}”难度，"
            f"{adaptation['explanation_style']}。\n\n"
            "关键词检索适合精确术语、代码和 ID，向量检索补足同义表达；工程上先分别召回，再统一排序并用 Recall@K 验证效果。[S1]\n\n"
            f"练习安排：{adaptation['practice_strategy']}。"
        ),
        "createdAt": "2026-08-31T03:20:00+08:00",
        "updatedAt": "2026-08-31T03:20:00+08:00",
        "sourceRefs": [source],
        "contextRefs": [{"courseId": "course-rag-industry-v1", "knowledgePointId": "kp-rag", "title": "检索工程与评估 · 混合检索", "status": "可用"}],
        "contextSnapshot": {"profile_adaptation_plan": adaptation, "profile_adaptation_summary": adaptation["summary"]},
        "streamCheckpoint": {"receivedCharacters": 390, "contextSnapshot": {"profile_adaptation_plan": adaptation, "profile_adaptation_summary": adaptation["summary"]}},
        "runEvents": _run_events(profile_id),
        "agentAudit": {"runId": f"chat-run-{profile_id}", "mode": "live", "status": "running", "events": _run_events(profile_id)},
    }
    return {
        "id": f"conversation-{profile_id}",
        "title": "画像适配：混合检索岗位问题",
        "status": "active",
        "lockVersion": 1,
        "courseId": "course-rag-industry-v1",
        "courseIds": ["course-rag-industry-v1"],
        "courses": [{"id": "course-rag-industry-v1", "title": "检索工程与评估", "subject": "人工智能工程"}],
        "messages": [
            {"id": f"user-{profile_id}", "role": "user", "status": "completed", "sequence": 1, "content": "如何组合关键词和语义搜索，才能在岗位项目中提高检索质量？", "createdAt": "2026-08-31T03:19:00+08:00"},
            assistant,
        ],
        "attachments": [],
    }


def _bundle(profile_id: str, adaptation: dict) -> dict:
    labels = {
        "handout": "个性化讲义", "mind_map": "思维导图", "quiz": "测验题资源",
        "training_task": "实训任务书", "code_sandbox": "代码沙盒任务", "video": "视频推荐",
        "deck": "PPT / 网页课件", "interactive_model": "可交互模型", "feynman": "费曼复述任务",
    }
    items = []
    for index, (kind, label) in enumerate(labels.items(), start=1):
        route_prefix = {
            "handout": "handouts", "mind_map": "mindmaps", "quiz": "quizzes", "training_task": "training-tasks",
            "code_sandbox": "code-sandboxes", "video": "videos", "deck": "decks", "interactive_model": "models", "feynman": "feynman",
        }[kind]
        items.append({"type": kind, "label": label, "purpose": "按当前画像安排的课程资源", "completion_rule": "打开资源并完成页面要求", "state": "succeeded", "resource": {"route": f"/workspace/resources/{route_prefix}/resource-{profile_id}-{index}"}})
    return {
        "job_id": f"bundle-{profile_id}", "course_id": "course-rag-industry-v1", "knowledge_point_id": "kp-rag", "status": "succeeded", "items": items,
        "context": {
            "course_title": "检索工程与评估", "knowledge_point_title": "混合检索", "learning_goal": "掌握关键词与向量检索的组合、重排和 Recall@K 评估",
            "profile_adaptation": adaptation["summary"], "profile_adaptation_plan": adaptation, "profile_context": adaptation,
            "mastery_summary": f"当前知识点掌握度：{int((adaptation.get('point_mastery') or 0) * 100)}%", "recent_learning_summary": "本轮按画像快照组织资源", "source_count": 1,
        },
    }


def _resource_protocol(resource_id: str, resource_type: str, adaptation: dict, source: dict) -> dict:
    return {
        "schema_version": "f2.resource.v1",
        "resource_id": resource_id,
        "type": resource_type,
        "course_id": "course-rag-industry-v1",
        "knowledge_point_id": "kp-rag",
        "source_refs": [source],
        "profile_adaptation": adaptation["summary"],
        "profile_adaptation_plan": adaptation,
        "profile_context": adaptation,
        "mastery_summary": f"当前知识点掌握度：{int((adaptation.get('point_mastery') or 0) * 100)}%",
        "recent_learning_summary": "本轮按画像快照组织资源",
        "version": {"id": f"{resource_id}-v1", "number": 1, "content_hash": "evidence"},
        "status": "available",
        "generation_state": "succeeded",
    }


def _resource_detail(resource_id: str, resource_type: str, adaptation: dict) -> dict:
    """Build a small, production-shaped detail payload for visual evidence."""
    source = _source()
    title = {
        "handout": "画像适配讲义 · 混合检索",
        "mind_map": "画像适配思维导图 · 混合检索",
        "quiz": "画像适配测验 · 混合检索",
        "training_task": "画像适配实训 · 混合检索",
        "deck": "画像适配课件 · 混合检索",
    }[resource_type]
    version_id = f"{resource_id}-v1"
    resource = _resource_protocol(resource_id, resource_type, adaptation, source)
    catalog = {
        "type": resource_type,
        "title": title,
        "course": {"id": "course-rag-industry-v1", "title": "检索工程与评估"},
        "knowledge_point": {"id": "kp-rag", "title": "混合检索"},
        "completion": {"status": "not_recorded", "progress": None, "rule": ""},
    }
    history = {"items": [{"id": version_id, "number": 1, "is_current": True, "source_status": "available"}]}

    if resource_type == "handout":
        structured = {
            "schemaVersion": "f5.handout.v1", "title": title,
            "summary": f"{adaptation['difficulty_label']}：根据当前画像安排解释顺序、岗位例子和练习支架。",
            "learningGoal": "掌握关键词与向量检索的组合、重排和 Recall@K 评估。", "estimatedMinutes": {"foundation": 30, "scaffolded": 24, "transfer": 18}.get(adaptation.get("difficulty_band"), 24),
            "outline": [{"id": "concept", "title": "关键概念"}, {"id": "example", "title": "岗位例子"}, {"id": "quiz", "title": "学习检查"}, {"id": "footnote", "title": "来源"}],
            "concepts": [{"id": "concept", "title": "混合检索", "explanation": "关键词检索擅长精确术语，向量检索补足语义表达；混合检索需要统一排序。", "sourceRefIds": [source["source_ref_id"]]}],
            "figures": [{"id": "figure", "title": "统一排序", "kind": "formula", "content": "score = α·keyword + (1-α)·vector", "caption": "权重需要在验证集上比较。", "sourceRefIds": [source["source_ref_id"]]}],
            "examples": [{"id": "example", "title": "岗位情境：代码库检索", "body": f"以{adaptation.get('example_context') or '课程实践场景'}为例，对比精确函数名与同义描述的召回。", "sourceRefIds": [source["source_ref_id"]]}],
            "counterExamples": [{"id": "counter", "title": "边界提醒", "body": "不能把两个检索结果直接拼接，必须统一排序并用 Recall@K 验证。", "sourceRefIds": [source["source_ref_id"]]}],
            "codeBlocks": [{"id": "code", "title": "最小融合骨架", "language": "python", "code": "hybrid = merge(keyword_hits, vector_hits)", "explanation": "先得到两路候选，再统一排序。"}],
            "miniQuiz": [{"id": "quiz", "question": "混合检索为什么要统一排序？", "options": ["处理两路分数尺度差异", "只保留关键词结果"], "correctIndex": 0, "explanation": "统一排序才能公平比较两路结果。", "required": True}],
            "footnotes": [{"id": "footnote", "sourceRefId": source["source_ref_id"], "label": "[S1]", "title": source["title"], "location": source["location_label"]}],
            "profileAdaptation": {"summary": adaptation["summary"], "difficulty": adaptation["difficulty_label"], "scaffolding": [adaptation["hint_policy"], adaptation["practice_strategy"]]},
        }
        projection = {"mode": "structured", "structured": structured, "source_refs": [source], "source_readiness": {"publishable": True, "reason": "课程来源完整，可继续学习。"}, "warnings": []}
        payload = {"handout": {"current_version_id": version_id, "current": projection, "versions": [{"id": version_id, "number": 1, "projection": projection}]}}
    elif resource_type == "mind_map":
        variant_node = ({"nodeId": "profile-focus", "parentNodeId": "root", "label": "前置概念与最小案例", "summary": "先确认查询、候选和排序三个基本对象。", "relation": "学习支架", "depth": 1, "sourceRefs": [source["source_ref_id"]], "masteryBand": "needs_work", "linkedResourceIds": []} if adaptation.get("difficulty_band") == "foundation" else {"nodeId": "profile-focus", "parentNodeId": "root", "label": "迁移挑战与边界", "summary": "比较不同权重和新情境下的 Recall@K 变化。", "relation": "迁移应用", "depth": 1, "sourceRefs": [source["source_ref_id"]], "masteryBand": "secure", "linkedResourceIds": []})
        structured = {"schemaVersion": "f5.mindmap.v1", "title": title, "summary": f"{adaptation['difficulty_label']}：按当前掌握度聚焦混合检索的核心关系。", "learningGoal": "看清关键词、向量和统一排序的关系。", "rootNodeId": "root", "nodes": [
            {"nodeId": "root", "parentNodeId": None, "label": "混合检索", "summary": f"统一关键词与向量检索；{variant_node['summary']}", "relation": "核心概念", "depth": 0, "sourceRefs": [source["source_ref_id"]], "masteryBand": "developing", "linkedResourceIds": []},
            {"nodeId": "keyword", "parentNodeId": "root", "label": "关键词检索", "summary": "擅长精确术语、代码和 ID。", "relation": "组成", "depth": 1, "sourceRefs": [source["source_ref_id"]], "masteryBand": "needs_work", "linkedResourceIds": []},
            {"nodeId": "vector", "parentNodeId": "root", "label": "向量检索", "summary": "通过 embedding 发现语义相似文本。", "relation": "组成", "depth": 1, "sourceRefs": [source["source_ref_id"]], "masteryBand": "secure", "linkedResourceIds": []},
            variant_node,
        ]}
        projection = {"mode": "structured", "structured": structured, "source_refs": [source], "source_readiness": {"publishable": True, "reason": "来源完整，可进入导图学习。"}, "warnings": []}
        payload = {"mindmap": {"current_version_id": version_id, "current": projection, "versions": [{"id": version_id, "number": 1, "projection": projection}]}}
    elif resource_type == "quiz":
        prompt = "先识别关键条件：混合检索的关键步骤是什么？" if adaptation.get("difficulty_band") == "foundation" else "在新查询和不同权重下比较：混合检索的关键步骤是什么？"
        structured = {"schemaVersion": "f6.quiz-resource.v1", "title": title, "summary": f"{adaptation['difficulty_label']}：按当前掌握度递进安排题目和提示。", "courseTitle": "检索工程与评估", "knowledgePoint": {"id": "kp-rag", "title": "混合检索"}, "adaptation": {"learningGoal": "验证混合检索理解。", "profileSummary": adaptation["summary"], "masterySummary": resource["mastery_summary"], "recentLearningSummary": resource["recent_learning_summary"]}, "semanticContext": {}, "sourceRefIds": [source["source_ref_id"]], "questions": [{"questionVersionId": f"{resource_id}-q1", "position": 1, "required": True}], "requiredQuestionCount": 1}
        questions = [{"id": f"{resource_id}-q1", "position": 1, "required": True, "status": "available", "question_type": "single_choice", "prompt": prompt, "options": ["统一排序两路结果", "只运行关键词检索"], "source_ref_ids": [source["source_ref_id"]], "attempts": [], "latest_attempt": None}]
        projection = {"mode": "structured", "structured": structured, "questions": questions, "source_refs": [source], "progress": {"question_count": 1, "attempted_count": 0, "correct_count": 0, "required_count": 1, "required_correct_count": 0, "completed": False}, "warnings": []}
        payload = {"quiz": {"current_version_id": version_id, "current": projection, "versions": [{"id": version_id, "number": 1, "projection": projection}]}}
    elif resource_type == "training_task":
        training_step = "先记录两路召回，再比较统一排序的 Recall@K。" if adaptation.get("difficulty_band") == "foundation" else "改变融合权重并解释新查询下的 Recall@K 取舍。"
        structured = {"schemaVersion": "f5.training-task.v1", "title": title, "objective": "在岗位检索场景中完成一次混合召回对比。", "difficulty": adaptation["difficulty_label"], "estimatedMinutes": {"foundation": 35, "scaffolded": 30, "transfer": 22}.get(adaptation.get("difficulty_band"), 30), "prerequisites": ["理解关键词检索与向量检索"], "environment": ["Python 3"], "data": ["课程冻结样例"], "steps": [{"id": "step1", "title": "建立两路基线", "instruction": "分别运行关键词和向量检索。", "expectedResult": "得到两组候选。", "errorGuidance": "检查查询与输入。"}, {"id": "step2", "title": "画像对应的练习", "instruction": training_step, "expectedResult": "得到可解释的混合排名。", "errorGuidance": "检查分数尺度和评估集。"}], "checkpoints": [{"id": "cp1", "title": "结果可比较", "verification": "记录两路和混合结果。", "passCondition": "包含 Recall@K。"}], "deliverables": [{"id": "d1", "title": "评估记录", "description": "提交结果与分析。", "format": "Markdown"}], "rubric": [{"id": "r1", "criterion": "证据完整", "evidence": "保留来源和 Recall@K。", "points": 100}], "sourceRefIds": [source["source_ref_id"]], "linkedSandboxId": None, "linkedModelId": None}
        projection = {"mode": "structured", "structured": structured, "source_refs": [source], "linked_resources": [], "source_readiness": {"publishable": True, "reason": "课程来源完整，可开始实训。"}, "warnings": []}
        payload = {"training_task": {"current_version_id": version_id, "current": projection, "versions": [{"id": version_id, "number": 1, "projection": projection}]}}
    else:  # deck
        structured = {"schemaVersion": "f5.deck.v1", "title": title, "summary": f"{adaptation['difficulty_label']}：按当前画像控制课件信息密度和练习顺序。", "learningGoal": "掌握混合检索的组合与评估。", "adaptationSummary": adaptation["summary"], "slides": [{"id": "slide1", "layout": "title", "title": "混合检索", "subtitle": adaptation["difficulty_label"], "body": "关键词 + 向量 + 统一排序", "bullets": [], "speakerNotes": "", "sourceRefIds": [source["source_ref_id"]]}, {"id": "slide2", "layout": "content", "title": "岗位例子", "subtitle": "", "body": "比较精确函数名与同义描述的召回。", "bullets": ["关键词检索", "向量检索", "Recall@K"], "speakerNotes": "", "sourceRefIds": [source["source_ref_id"]]}]}
        projection = {"mode": "structured", "structured": structured, "source_refs": [source], "source_readiness": {"publishable": True, "reason": "课程来源完整，可预览课件。"}, "warnings": []}
        payload = {"deck": {"current_version_id": version_id, "current": projection, "versions": [{"id": version_id, "number": 1, "projection": projection}]}}
    return {"id": resource_id, "course_id": "course-rag-industry-v1", "artifact_type": resource_type, "title": title, "status": "active", "current_version_id": version_id, "lock_version": 1, "catalog": catalog, "resource": resource, "history": history, **payload}
def capture() -> dict:
    from playwright.sync_api import sync_playwright

    if not (DIST / "index.html").is_file():
        raise SystemExit("frontend/dist/index.html 不存在，请先 npm run build")
    results = []
    with frontend_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for raw in PROFILES:
                profile_id = raw["id"]
                _, adaptation = _profile_payload(raw)
                resource_ids = {
                    kind: f"resource-{profile_id}-{index}"
                    for index, kind in enumerate(("handout", "mind_map", "quiz", "training_task", "code_sandbox", "video", "deck", "interactive_model", "feynman"), start=1)
                }
                detail_fixtures = {
                    kind: _resource_detail(resource_id, kind, adaptation)
                    for kind, resource_id in resource_ids.items()
                    if kind in {"handout", "mind_map", "quiz", "training_task", "deck"}
                }
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                page.add_init_script("localStorage.setItem('edumatrix_token','noc-t23-evidence'); localStorage.setItem('edumatrix_role','student'); localStorage.setItem('edumatrix_onboarded','true');")

                def respond(route, payload, status=200):
                    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))

                def handle(route):
                    parsed = urlparse(route.request.url)
                    path = parsed.path
                    if path.endswith("/api/auth/me"):
                        respond(route, {"public_id": "noc-t23-evidence", "username": "noc-t23", "display_name": "NOC-T23 证据", "role": "student"})
                    elif path.endswith("/api/health"):
                        respond(route, {"status": "ok"})
                    elif path.endswith("/api/v1/chat/courses"):
                        respond(route, {"courses": [{"id": "course-rag-industry-v1", "title": "检索工程与评估", "subject": "人工智能工程", "status": "active", "visibility": "public"}]})
                    elif path.endswith("/api/v1/chat/conversations"):
                        respond(route, {"items": [{"id": f"conversation-{profile_id}", "title": "画像适配：混合检索岗位问题", "courseId": "course-rag-industry-v1", "courseIds": ["course-rag-industry-v1"], "courses": [{"id": "course-rag-industry-v1", "title": "检索工程与评估"}], "status": "active", "lockVersion": 1}]})
                    elif f"/api/v1/chat/conversations/conversation-{profile_id}" in path:
                        respond(route, _conversation(profile_id, adaptation))
                    elif path.startswith("/api/v1/m5/resources/"):
                        resource_id = path.rsplit("/", 1)[-1]
                        if resource_id in {item["id"] for item in detail_fixtures.values()}:
                            respond(route, next(item for item in detail_fixtures.values() if item["id"] == resource_id))
                        else:
                            respond(route, {})
                    elif "/api/v1/resource-bundles/generation-jobs/" in path:
                        respond(route, _bundle(profile_id, adaptation))
                    else:
                        respond(route, {})

                page.route("**/api/**", handle)
                page.goto(f"{base_url}/learn?profile={profile_id}&course_id=course-rag-industry-v1", wait_until="networkidle")
                page.get_by_test_id("chat-profile-adaptation").wait_for(timeout=15000)
                workflow = page.locator("details.message-workflow").first
                if workflow.count():
                    workflow.evaluate("el => { el.open = true }")
                chat_path = OUT / f"chat-{profile_id}.png"
                page.screenshot(path=str(chat_path), full_page=True)

                page.goto(f"{base_url}/workspace/resources/bundles/bundle-{profile_id}?course_id=course-rag-industry-v1", wait_until="networkidle")
                page.get_by_test_id("resource-bundle-profile-adaptation").wait_for(timeout=15000)
                bundle_path = OUT / f"resource-{profile_id}.png"
                page.screenshot(path=str(bundle_path), full_page=True)
                detail_screenshots = []
                for kind, detail_fixture in detail_fixtures.items():
                    route_prefix = {"handout": "handouts", "mind_map": "mindmaps", "quiz": "quizzes", "training_task": "training-tasks", "deck": "decks"}[kind]
                    page.goto(f"{base_url}/workspace/resources/{route_prefix}/{detail_fixture['id']}?course_id=course-rag-industry-v1", wait_until="networkidle")
                    page.get_by_test_id("resource-profile-adaptation").wait_for(timeout=15000)
                    detail_path = OUT / f"resource-{profile_id}-{kind}.png"
                    page.screenshot(path=str(detail_path), full_page=True)
                    detail_screenshots.append({"resource_type": kind, "screenshot": str(detail_path), "compact_adaptation_sentence": True, "profile_card": False, "applied_effect": False})
                results.append({"profile_id": profile_id, "difficulty": adaptation["difficulty_label"], "chat_screenshot": str(chat_path), "resource_screenshot": str(bundle_path), "resource_detail_screenshots": detail_screenshots, "chat_profile_card": True, "resource_profile_card": False, "compact_adaptation_sentence": True})
                page.close()
        finally:
            browser.close()
    payload = {"task_id": "NOC-T23", "status": "passed", "viewports": [{"width": 1600, "height": 1000}], "profiles": results}
    (OUT / "browser-evidence.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(capture(), ensure_ascii=False, indent=2))
