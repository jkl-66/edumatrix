from __future__ import annotations

import json
import pytest

from app.competition_demo_seed import seed_competition_demo
from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBLearningEvent,
    DBProfileSnapshot,
    DBSourceRef,
    DBUser,
)
from app.m5_resources import parse_code_sandbox_content, parse_interactive_model_content
from app.resource_bundles import (
    _deterministic_demo_content,
    _source_semantic_anchor,
    _version_generation_metadata,
    create_generation_job,
    execute_generation_job_demo,
    generation_job_payload,
    execute_generation_job,
)
from tests.test_f6_t03_code_sandbox_resource import _session


@pytest.mark.parametrize('explicit', [False, True])
def test_current_planner_responsibilities_reach_review_without_reviving_retired_requirements(explicit):
    import asyncio
    import app.resource_bundles as bundles

    current = {'learning_goal': '比较模型误差', 'shared': ['解释依据，不限句数'],
               'by_resource': {'interactive_model': ['只做阈值对照']}}
    class Planner:
        async def generate(self, system, user, *, role):
            return json.dumps({'plan': '讲义解释，实验做对照', 'resourceBriefs': [
                {'type': 'handout', 'goal': '解释误差', 'qualityChecks': ['给出完整示例']},
                {'type': 'interactive_model', 'goal': '观察阈值', 'qualityChecks': ['记录翻转行']}]})
    manifest = {'selected_resource_types': ['handout', 'interactive_model'],
                'context': {'learning_goal': '比较模型误差'},
                **({'requirements_explicit': True, 'active_requirements': current} if explicit else {})}
    plan = asyncio.run(bundles._shared_semantic_plan_async(Planner(), manifest=manifest, source_snapshots=[]))
    requirements = plan['active_requirements']
    if explicit:
        assert requirements == current
    else:
        assert requirements['by_resource'] == {
            'handout': ['解释误差', '给出完整示例'], 'interactive_model': ['观察阈值', '记录翻转行']}
        assert bundles.requirements_for({'active_requirements': requirements}, ['interactive_model'])['by_resource'] == {
            'interactive_model': ['观察阈值', '记录翻转行']}


@pytest.fixture(autouse=True)
def _fake_web_video_search(monkeypatch):
    async def fake_search(query, max_results=5):
        return [{
            "title": f"{query} · 课程视频候选",
            "url": "https://www.bilibili.com/video/BV1test123",
            "source": "B站视频",
            "description": "测试用真实网页来源",
        }]

    import web_search_api
    monkeypatch.setattr(web_search_api, "search_videos", fake_search)


def _manifest(
    *, knowledge_point: str, profile: str, mastery: str,
    source_hash: str = "source-hash", profile_plan: dict | None = None,
) -> dict:
    return {
        "knowledge_point_id": "kp-pr01",
        "profile_snapshot_id": "profile-pr01",
        "context": {
            "course_title": "PR-01 课程",
            "knowledge_point_title": knowledge_point,
            "learning_goal": f"掌握 {knowledge_point} 并能完成实践验证",
            "profile_adaptation": profile,
            "mastery_summary": mastery,
            "recent_learning_summary": "最近完成一次来源核对。",
            "profile_adaptation_plan": profile_plan or {},
        },
        "input_snapshot": {
            "profile_snapshot_hash": f"profile-{profile}",
            "recent_event_cursor": "event-cursor-pr01",
            "input_snapshot_hash": f"input-{profile}",
            "source_snapshot_hashes": {"training_task": source_hash},
        },
    }


def _source(*, source_ref_id: str, title: str, quote: str) -> dict:
    return {
        "source_ref_id": source_ref_id,
        "title": title,
        "location_label": "第 2 章 / 实验段",
        "location_kind": "section",
        "quote": quote,
        "available": True,
        "reason_code": "",
        "reason": "",
    }


def test_public_source_anchor_keeps_teaching_content_without_repository_metadata():
    anchor = _source_semantic_anchor([_source(
        source_ref_id="src-public-anchor",
        title="优化算法课程章节",
        quote=(
            "上游仓库：d2l-zh（固定版本 e6b18dbde18b491201110fde7323312a848c26e8）\n"
            "文件路径：chapter_optimization/sgd.md\n"
            "学习率过大会使损失振荡，正则化用于约束模型复杂度。"
        ),
    )])

    assert "学习率过大会使损失振荡" in anchor
    for internal in ("上游仓库", "固定版本", "e6b18dbde18b491201110fde7323312a848c26e8", "文件路径"):
        assert internal not in anchor


def test_same_knowledge_point_changes_content_for_profile_and_source_inputs():
    classification = [_source(
        source_ref_id="src-classifier",
        title="分类课程章节",
        quote="分类阈值、混淆矩阵、precision 和 recall 的取舍。",
    )]
    retrieval = [_source(
        source_ref_id="src-retrieval",
        title="检索课程章节",
        quote="向量 embedding、top-k 召回和重排阈值决定检索质量。",
    )]
    base = _manifest(knowledge_point="模型评估", profile="需要分步脚手架", mastery="掌握度仍在发展")
    advanced = _manifest(knowledge_point="模型评估", profile="可以直接比较边界条件", mastery="已掌握基础")

    handout_base = _deterministic_demo_content(
        resource_type="handout", item={"title": "讲义", "id": "handout", "label": "来源"},
        manifest=base, source_snapshots=classification,
    )
    handout_profile = _deterministic_demo_content(
        resource_type="handout", item={"title": "讲义", "id": "handout", "label": "来源"},
        manifest=advanced, source_snapshots=classification,
    )
    handout_source = _deterministic_demo_content(
        resource_type="handout", item={"title": "讲义", "id": "handout", "label": "来源"},
        manifest=base, source_snapshots=retrieval,
    )

    assert handout_base != handout_profile
    assert handout_base != handout_source
    assert "需要分步脚手架" in handout_base
    assert "可以直接比较边界条件" in handout_profile
    assert '模型评估的实践与结果解释' in json.loads(handout_base)['summary']
    assert '模型评估的实践与结果解释' in json.loads(handout_source)['summary']
    assert json.loads(handout_source)['footnotes'][0]['title'] == retrieval[0]['title']
    assert 'src-retrieval' in handout_source and 'src-classifier' not in handout_source
    assert "deterministic_fallback" not in json.loads(handout_base)


def test_unrelated_profile_focus_cannot_replace_the_current_resource_topic():
    manifest = _manifest(
        knowledge_point="优化算法、正则化与训练稳定性",
        profile="需要更多迁移练习",
        mastery="掌握度仍在发展",
        profile_plan={
            "difficulty_band": "transfer",
            "content_focus": "召回率、精确率、向量检索和关键词检索的边界",
            "example_context": "混合检索重排项目",
        },
    )
    sources = [_source(
        source_ref_id="src-optimization",
        title="优化课程章节",
        quote="学习率、正则化强度与早停共同影响训练稳定性和泛化能力。",
    )]

    handout = _deterministic_demo_content(
        resource_type="handout", item={"title": "优化讲义", "id": "handout", "label": "来源"},
        manifest=manifest, source_snapshots=sources,
    )
    mind_map = _deterministic_demo_content(
        resource_type="mind_map", item={"title": "优化导图", "id": "mindmap", "label": "来源"},
        manifest=manifest, source_snapshots=sources,
    )

    for content in (handout, mind_map):
        assert "优化算法、正则化与训练稳定性" in content
        assert "混合检索重排项目" not in content
        assert "向量检索和关键词检索" not in content


def test_ai_ml_workspaces_share_semantics_but_keep_distinct_responsibilities():
    source = [_source(
        source_ref_id="src-retrieval",
        title="检索课程章节",
        quote="向量 embedding、top-k 召回和重排阈值决定检索质量。",
    )]
    manifest = _manifest(knowledge_point="混合检索", profile="先完成基线再调参", mastery="需要巩固")
    item = {"title": "AI/ML 实训", "id": "training", "label": "来源", "completion_rule": "完成真实运行并提交观察。"}
    training = json.loads(_deterministic_demo_content(
        resource_type="training_task", item=item, manifest=manifest, source_snapshots=source,
        linked_resource_ids=["sandbox-1", "model-1"],
    ))
    sandbox = json.loads(_deterministic_demo_content(
        resource_type="code_sandbox", item=item, manifest=manifest, source_snapshots=source,
    ))
    model_content = _deterministic_demo_content(
        resource_type="interactive_model", item=item, manifest=manifest, source_snapshots=source,
    )
    model = json.loads(model_content)

    assert [step["id"] for step in training["steps"]] == ["step-data", "step-model", "step-run", "step-evaluate"]
    assert all(step["sourceRefIds"] == ["src-retrieval"] for step in training["steps"])
    assert training["linkedSandboxId"] == "sandbox-1"
    assert training["linkedModelId"] == "model-1"
    assert training["semanticContext"]["practical_focus"] == "混合检索与证据质量评估"
    assert sandbox["semanticContext"]["source_ref_ids"] == ["src-retrieval"]
    assert model["semanticContext"]["source_ref_ids"] == ["src-retrieval"]
    assert sandbox["entryFile"] == "main.py"
    assert model["parameters"]
    assert training["semanticContext"]["semantic_input_fingerprint"] == sandbox["semanticContext"]["semantic_input_fingerprint"] == model["semanticContext"]["semantic_input_fingerprint"]
    assert parse_code_sandbox_content(json.dumps(sandbox)).schemaVersion == "f6.code-sandbox.v1"
    assert parse_interactive_model_content(model_content).schemaVersion == "f6.interactive-model.v1"


def test_generation_versions_share_fingerprints_and_do_not_write_learning_events():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        assert profile is not None and source is not None
        before = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()
        job = create_generation_job(
            session, learner, course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id, idempotency_key="pr01-single-metadata-001", scope="single",
            items=[{"type": "code_sandbox", "title": "语义沙盒", "source_ref_ids": [source.id], "completion_rule": "完成运行。"}],
            learning_goal="验证来源驱动的检索实践",
        )
        result = execute_generation_job_demo(session, learner, job["job_id"])
        after = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()
        assert before == after
        item = result["items"][0]
        artifact = session.get(DBArtifact, item["resource"]["resource_id"])
        version = session.get(DBArtifactVersion, artifact.current_version_id)
        assert version is not None
        metadata = version.metadata_json
        assert metadata["generation_mode"] == "deterministic_fallback"
        assert metadata["input_snapshot_hash"]
        assert metadata["source_snapshot_hash"]
        assert metadata["profile_snapshot_hash"]
        assert metadata["recent_event_cursor"]
        assert metadata["semantic_input_fingerprint"]
        assert metadata["content_semantic_fingerprint"]
        assert item["resource"]["generation"]["mode"] == "deterministic_fallback"
        assert item["resource"]["generation"]["input_snapshot_hash"] == metadata["input_snapshot_hash"]
        assert parse_code_sandbox_content(version.content).schemaVersion == "f6.code-sandbox.v1"
    finally:
        session.close()
        engine.dispose()


def test_nine_resource_versions_share_one_frozen_input_snapshot():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        assert profile is not None and source is not None
        resource_types = ["handout", "mind_map", "quiz", "training_task", "code_sandbox", "video", "deck", "interactive_model", "feynman"]
        job = create_generation_job(
            session, learner, course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id, idempotency_key="pr01-bundle-fingerprint-001", scope="bundle",
            items=[{"type": resource_type, "title": resource_type, "source_ref_ids": [source.id]} for resource_type in resource_types],
            learning_goal="验证九类资源共享同一课程语义",
        )
        result = execute_generation_job_demo(session, learner, job["job_id"])
        assert result["status"] == "succeeded"
        versions = []
        for item in result["items"]:
            assert item["state"] == "succeeded"
            artifact = session.get(DBArtifact, item["resource"]["resource_id"])
            versions.append(session.get(DBArtifactVersion, artifact.current_version_id))
        keys = ["input_snapshot_hash", "source_snapshot_hash", "profile_snapshot_hash", "recent_event_cursor", "semantic_input_fingerprint"]
        for key in keys:
            assert len({version.metadata_json[key] for version in versions}) == 1, key
        assert {version.metadata_json["generation_mode"] for version in versions} == {"deterministic_fallback"}
        assert all(version.metadata_json["source_ref_ids"] == [source.id] for version in versions)
    finally:
        session.close()
        engine.dispose()


class _FakeLiveBackend:
    model = "deepseek-v4-flash"
    provider = "openai"

    async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
        if role == "resource_reviewer":
            assert "JSON" in system_prompt and "approved" in system_prompt and "findings" in system_prompt
            return json.dumps({"approved": True, "summary": "模拟结构核对通过", "findings": [], "rejectedTypes": [],
                "conditionReview": [{"claimId":claim["id"],"status":"valid",
                    "reason":"合成数据仅用于生成与审核编排回归。","fix":""}
                    for claim in json.loads(user_prompt).get("condition_claims",[])]})
        assert "只输出一个 JSON 对象" in system_prompt
        return json.dumps({
            "summary": "模型生成的课程摘要",
            "selectedVideoIds": [item['id'] for item in json.loads(user_prompt).get('video_candidates', [])],
            "learningGoal": "模型生成的学习目标",
            "narrative": "模型依据冻结来源生成的正文，包含条件、机制和验证边界。",
            "rootNodeId": "topic",
            "nodes": [
                {"nodeId":"topic","parentNodeId":None,"label":"课程主题","summary":"模型依据课程说明知识联系。","relation":"主题","depth":0},
                {"nodeId":"condition","parentNodeId":"topic","label":"适用条件","summary":"先核对方法适用的条件。","relation":"前提","depth":1},
            ],
            "practiceSteps": [
                {"title": "数据", "instruction": "模型生成的数据检查步骤", "expectedResult": "字段清单", "errorGuidance": "记录缺失"},
                {"title": "模型", "instruction": "模型生成的模型选择步骤", "expectedResult": "基线方案", "errorGuidance": "回查来源"},
                {"title": "训练", "instruction": "模型生成的训练步骤", "expectedResult": "可复现输出", "errorGuidance": "保留错误"},
                {"title": "评估", "instruction": "模型生成的评估步骤", "expectedResult": "证据结论", "errorGuidance": "检查指标"},
            ],
            "starterCode": "print('model-generated')\n",
            "requiredChecks": [
                {"id": "stdout", "label": "输出", "kind": "stdout_contains", "expectedText": "model-generated"},
            ],
            "environment": ["Python 3"],
            "estimatedMinutes": 35,
            "data": ["冻结课程示例数据"],
            "parameters": (json.loads(user_prompt).get("interactive_template") or {}).get("parameters", []),
            "constraints": [{"id": "range", "title": "范围约束", "description": "学习率必须大于 0 且不超过 1。"}],
            "dataset": {"id": "course-demo-dataset", "title": "课程示例数据", "summary": "用于观察参数变化的课程示例数据。", "sampleCount": 1},
            "chart": {"kind": "line", "xAxisLabel": "训练步", "yAxisLabel": "损失", "series": [{"key": "loss", "label": "损失", "unit": "", "higherIsBetter": False}]},
            "observationPrompt": "模型生成的参数观察提示",
            "quizQuestions": [
                {"prompt": "模型题一", "options": ["A1", "B1", "C1", "D1"], "answer": "A", "explanation": "题一解析", "bloom": "remember", "difficulty": 0.3},
                {"prompt": "模型题二", "options": ["A2", "B2", "C2", "D2"], "answer": "B", "explanation": "题二解析", "bloom": "understand", "difficulty": 0.5},
                {"prompt": "模型题三", "options": ["A3", "B3", "C3", "D3"], "answer": "C", "explanation": "题三解析", "bloom": "apply", "difficulty": 0.7},
            ],
            "slides": [
                {"layout": "title", "title": "课程主题", "subtitle": "模型生成"},
                {"layout": "content", "title": "机制", "body": "依据冻结来源解释机制。", "speakerNotes": "回查课程来源。"},
            ],
        }, ensure_ascii=False)


def test_video_generation_requeries_rejected_candidates_and_keeps_real_selection(monkeypatch):
    import app.resource_bundles as bundles
    from app.database import DBTaskEvent
    queries_seen, candidates_seen = [], []

    async def search(*, manifest):
        queries_seen.append(manifest.get('video_search_queries'))
        suffix = 'advanced' if len(queries_seen) == 1 else 'intro'
        return [{'id': suffix, 'title': suffix, 'url': f'https://example.org/{suffix}',
                 'sourceKind': 'external_url',
                 'availability': 'external_only', 'sourceRefIds': ['demo-ref-07'],
                 'author': '合成检索测试', 'language': '中文', 'licenseStatus': 'platform_link_only',
                 'licenseLabel': '平台链接', 'reason': '本节概念介绍', 'segments': [], 'alternatives': []}]

    class Backend(_FakeLiveBackend):
        async def generate(self, system_prompt, user_prompt, *, role):
            payload = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            if role == 'resource_generator':
                candidates = json.loads(user_prompt)['video_candidates']
                candidates_seen.append(candidates)
                if len(candidates_seen) == 1:
                    payload.update(selectedVideoIds=[], searchQueries=['训练标签和预测输入 入门'])
            return json.dumps(payload, ensure_ascii=False)

    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username='lzz').one()
        monkeypatch.setattr(bundles, '_real_model_backend', lambda: Backend())
        monkeypatch.setattr(bundles, '_live_video_recommendations', search)
        job = create_generation_job(session, learner, course_id='demo-course-rag-trust-v1',
            knowledge_point_id='demo-kp-07', profile_snapshot_id='demo-profile-lzz-v1',
            idempotency_key='video-requery-candidates', scope='single',
            items=[{'type': 'video', 'title': '当前知识点视频', 'source_ref_ids': ['demo-ref-07']}])
        result = execute_generation_job(session, learner, job['job_id'])
        assert result['status'] == 'succeeded', {key: result.get(key) for key in ('failure_reason', 'items', 'review_gate')}
        assert len(candidates_seen) == 2
        assert queries_seen[1] == ['训练标签和预测输入 入门']
        artifact = session.get(DBArtifact, result['items'][0]['resource']['resource_id'])
        content = session.get(DBArtifactVersion, artifact.current_version_id).content
        assert 'https://example.org/intro' in content
        assert 'https://example.org/advanced' not in content
        searches = session.query(DBTaskEvent).filter_by(task_id=job['job_id'],
            event_type='resource_generation.video_search').all()
        assert len(searches) == 2
        assert {event.payload['candidates'][0]['id'] for event in searches} == {'advanced', 'intro'}
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize('code', ['video_selection_invalid', 'video_topic_mismatch', 'model_call_failed'])
def test_video_content_failure_changes_retry_input_but_network_failure_preserves_it(code):
    from app.database import DBTaskStep
    from app.resource_bundles import _generation_retry_input
    previous = DBTaskStep(input_summary=json.dumps({'type': 'video', 'revision_feedback': '旧意见'}),
        error_code='resource_generation.' + code, error_message='候选不符合本节先修')
    retried = _generation_retry_input(previous)
    assert retried['revision_feedback'] == ('旧意见' if code == 'model_call_failed' else '候选不符合本节先修')


def test_live_generation_uses_real_model_and_preserves_resource_protocol(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        assert profile is not None and source is not None
        monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: _FakeLiveBackend())
        job = create_generation_job(
            session, learner, course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id, idempotency_key="pr01-live-model-001", scope="single",
            items=[{"type": "code_sandbox", "title": "模型沙盒", "source_ref_ids": [source.id], "completion_rule": "完成运行。"}],
            learning_goal="验证真实模型资源生成",
        )
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "succeeded"
        item = result["items"][0]
        version = session.get(DBArtifactVersion, session.get(DBArtifact, item["resource"]["resource_id"]).current_version_id)
        assert version.metadata_json["generation_mode"] == "llm"
        assert version.metadata_json["model"] == "deepseek-v4-flash"
        assert version.metadata_json["reasoning_effort"] == "max"
        assert "model-generated" in version.content
        assert parse_code_sandbox_content(version.content).instructions == "模型依据冻结来源生成的正文，包含条件、机制和验证边界。"
        assert "deterministic_fallback" not in version.content
    finally:
        session.close()
        engine.dispose()


def test_live_generation_failure_is_explicit_and_creates_no_success_version(monkeypatch):
    class _FailingBackend(_FakeLiveBackend):
        async def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
            raise RuntimeError("provider unavailable")

    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        assert profile is not None and source is not None
        monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: _FailingBackend())
        job = create_generation_job(
            session, learner, course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id, idempotency_key="pr01-live-failure-001", scope="single",
            items=[{"type": "handout", "title": "失败讲义", "source_ref_ids": [source.id]}],
            learning_goal="验证失败状态",
        )
        result = execute_generation_job(session, learner, job["job_id"])
        assert result["status"] == "failed"
        assert result["items"][0]["state"] == "failed"
        assert result["items"][0]["resource"] is None
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize('explicit_at_revision', [False, True])
def test_planning_failure_with_saved_content_is_terminal_and_explicit_review_reuses_it(monkeypatch, explicit_at_revision):
    import app.resource_bundles as bundles
    calls = []
    fail_planner = False

    class Backend(_FakeLiveBackend):
        async def generate(self, system_prompt, user_prompt, *, role):
            calls.append(role)
            if role == 'resource_planner' and fail_planner:
                raise RuntimeError('planner unavailable')
            return await super().generate(system_prompt, user_prompt, role=role)

    engine, session = _session()
    try:
        seed_competition_demo(session)
        actor = session.query(DBUser).filter_by(username='lzz').one()
        monkeypatch.setattr(bundles, '_real_model_backend', lambda: Backend())
        job = create_generation_job(session, actor, course_id='demo-course-rag-trust-v1',
            knowledge_point_id='demo-kp-07', profile_snapshot_id='demo-profile-lzz-v1',
            idempotency_key='authored-correction-resume', scope='single',
            items=[{'type':'handout','title':'学习讲义','source_ref_ids':['demo-ref-07']}])
        original = execute_generation_job(session, actor, job['job_id'])
        version = session.get(DBArtifactVersion, original['items'][0]['resource']['version']['id'])
        requirements = bundles._generation_manifest(session, job['job_id'])['active_requirements']
        bundles.revise_generation_job(session, actor, job['job_id'], feedback='局部解析已核对',
            resource_types=['handout'], idempotency_key='local-explanation-correction',
            active_requirements=requirements if explicit_at_revision else None)
        bundles.complete_generation_item(session, actor, job['job_id'], 'handout',
            content=version.content, content_format=version.content_format,
            generation_mode='agent_revision', model='codex')
        fail_planner = True
        boundary = len(calls)
        if explicit_at_revision:
            final = execute_generation_job(session, actor, job['job_id'])
            assert final['status'] == 'succeeded'
            assert calls[boundary:] and all(role == 'resource_reviewer' for role in calls[boundary:])
            return
        failed = execute_generation_job(session, actor, job['job_id'])
        assert failed['status'] == 'failed'
        assert failed['items'][0]['state'] == 'succeeded'
        retained = failed['items'][0]['resource']['version']['id']
        bundles.revise_generation_job(session, actor, job['job_id'], feedback='正文已修改，按当前要求核对。',
            resource_types=[], idempotency_key='explicit-current-requirements', active_requirements=requirements)
        boundary = len(calls)
        final = execute_generation_job(session, actor, job['job_id'])
        assert final['status'] == 'succeeded'
        assert final['items'][0]['resource']['version']['id'] == retained
        assert calls[boundary:] and all(role == 'resource_reviewer' for role in calls[boundary:])
    finally:
        session.close()
        engine.dispose()


def test_review_premise_correction_reuses_generation_and_unaffected_reviews(monkeypatch):
    import app.resource_bundles as bundles
    from app.database import DBTaskEvent, DBTaskStep
    calls = []
    current = {'learning_goal': '观察数据并解释', 'shared': [],
               'by_resource': {'deck': ['必须恰好两句话']}}

    class Backend(_FakeLiveBackend):
        async def generate(self, system_prompt, user_prompt, *, role):
            data = json.loads(user_prompt)
            calls.append((role, data))
            result = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            if role == 'resource_planner':
                result['activeRequirements'] = current
            if role == 'resource_reviewer' and len(data['candidates']) == 1 and data['candidates'][0]['type'] == 'deck':
                rejected = data['active_requirements']['by_resource']['deck'] == ['必须恰好两句话']
                result.update(approved=not rejected, rejectedTypes=['deck'] if rejected else [],
                    findings=[{'resourceType': 'deck', 'issue': '不满足旧句数要求', 'fix': '调整句数'}] if rejected else [])
            return json.dumps(result, ensure_ascii=False)

    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username='lzz').one()
        monkeypatch.setattr(bundles, '_real_model_backend', lambda: Backend())
        job = create_generation_job(session, learner, course_id='demo-course-rag-trust-v1',
            knowledge_point_id='demo-kp-07', profile_snapshot_id='demo-profile-lzz-v1',
            idempotency_key='review-premise-original', scope='bundle',
            items=[{'type': kind, 'title': kind, 'source_ref_ids': ['demo-ref-07']} for kind in ['handout', 'deck']])
        first = execute_generation_job(session, learner, job['job_id'])
        assert first['review_gate']['status'] == 'failed'
        versions = {item['type']: item['resource']['version']['id'] for item in first['items']}
        original_events = [(row.id, json.dumps(row.payload, sort_keys=True)) for row in
            session.query(DBTaskEvent).filter_by(task_id=job['job_id']).all()]
        attempts = session.query(DBTaskStep).filter_by(task_id=job['job_id']).count()
        corrected = {**current, 'by_resource': {'deck': ['按内容完整性评价，不限句数']}}
        args = dict(feedback='旧句数要求已取消，保留正文，仅修正审核前提。', resource_types=[],
                    idempotency_key='review-premise-correction', active_requirements=corrected)
        revised = bundles.revise_generation_job(session, learner, job['job_id'], **args)
        assert revised['review_gate']['status'] == 'pending'
        assert bundles._generation_plan(session, job['job_id'])['active_requirements'] == corrected
        assert bundles._generation_manifest(session, job['job_id'])['active_requirements'] == corrected
        bundles.revise_generation_job(session, learner, job['job_id'], **args)
        assert session.query(DBTaskStep).filter_by(task_id=job['job_id']).count() == attempts
        assert session.query(DBTaskEvent).filter_by(task_id=job['job_id'], event_type='resource_generation.review.amended').count() == 1
        for row_id, payload in original_events:
            assert json.dumps(session.get(DBTaskEvent, row_id).payload, sort_keys=True) == payload
        boundary = len(calls)
        final = execute_generation_job(session, learner, job['job_id'])
        assert final['status'] == 'succeeded', final.get('failure_reason')
        assert {i['type']: i['resource']['version']['id'] for i in final['items']} == versions
        resumed = calls[boundary:]
        assert all(role == 'resource_reviewer' for role, _ in resumed)
        assert [[c['type'] for c in data['candidates']] for _, data in resumed] == [['deck'], ['handout', 'deck']]
    finally:
        session.close()
        engine.dispose()


def test_teaching_revision_replans_selected_resources_preserves_history_and_rechecks(monkeypatch):
    import app.resource_bundles as bundles
    from app.database import DBTaskEvent, DBTaskStep
    plan_inputs, generated, model_inputs = [], [], []

    class Backend(_FakeLiveBackend):
        async def generate(self, system_prompt, user_prompt, *, role):
            data = json.loads(user_prompt)
            model_inputs.append((role, data))
            result = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            if role == 'resource_planner':
                plan_inputs.append(data)
                result['sharedExample'] = {'rows': [[1, 0], [2, 1]], 'prediction_time': '结果公布前'}
                result['activeRequirements'] = data.get('active_requirements') or {'learning_goal':'观察并解释数据','shared':[], 'by_resource':{}}
                if (data.get('teaching_revision') or {}).get('feedback','').startswith('先观察数据'):
                    result['activeRequirements']['shared'] = ['先观察数据再运行代码']
                    result['sharedRequirementsChanged'] = True
                    result['sharedChangeReason'] = '本次明确调整教学顺序'
            elif role == 'resource_generator':
                generated.append(data['resource_type'])
                assert '结果公布前' in user_prompt
            return json.dumps(result, ensure_ascii=False)

    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username='lzz').one()
        monkeypatch.setattr(bundles, '_real_model_backend', lambda: Backend())
        authored_requirement = '逐项核对来源、例子、结论和适用条件。' * 40 + '保留最后一项独立解释。'
        job = create_generation_job(session, learner, course_id='demo-course-rag-trust-v1',
            knowledge_point_id='demo-kp-07', profile_snapshot_id='demo-profile-lzz-v1',
            idempotency_key='teaching-revision-original', scope='bundle',
            items=[{'type': kind, 'title': kind, 'source_ref_ids': ['demo-ref-07'],
                    'completion_rule': '完成代码沙盒并做一次简短回顾。' if kind == 'code_sandbox' else authored_requirement}
                   for kind in ['code_sandbox', 'deck']])
        with pytest.raises(bundles.ResourceBundleError, match='处理中'):
            bundles.revise_generation_job(session, learner, job['job_id'], feedback='先观察数据',
                resource_types=['code_sandbox'], idempotency_key='revision-before-complete')
        first = execute_generation_job(session, learner, job['job_id'])
        assert first['status'] == 'succeeded', first.get('failure_reason')
        assert next(item for item in first['items'] if item['type'] == 'deck')['completion_rule'] == authored_requirement
        original_event = session.query(DBTaskEvent).filter_by(task_id=job['job_id'],
            event_type='resource_generation.requested').one()
        original_manifest = json.dumps(original_event.payload, sort_keys=True)
        old_versions = {item['type']: item['resource']['version']['id'] for item in first['items']}
        old_text = {kind: session.get(DBArtifactVersion, version).content for kind, version in old_versions.items()}
        before_learning = session.query(DBLearningEvent).count()
        revision_args = dict(feedback='先观察数据再运行代码，保留正确课件和共同案例。',
            resource_types=['code_sandbox'], idempotency_key='teaching-revision-first')
        revised = bundles.revise_generation_job(session, learner, job['job_id'], **revision_args)
        assert revised['review_gate']['status'] == 'pending'
        assert not bundles._publish_gate_done(session, job['job_id'])
        assert bundles._generation_plan(session, job['job_id']) == {}
        assert json.dumps(original_event.payload, sort_keys=True) == original_manifest
        assert revised['profile_snapshot_id'] == first['profile_snapshot_id']
        revised_code = next(item for item in revised['items'] if item['type'] == 'code_sandbox')
        code_spec = next(item for item in bundles._generation_manifest(session, job['job_id'])['items']
                         if item['type'] == 'code_sandbox')
        assert revised_code['input']['completion_rule'] == code_spec['completion_rule']
        assert '必需检查' in revised_code['completion_rule']
        assert next(item for item in first['items'] if item['type'] == 'code_sandbox')['completion_rule'] == '完成代码沙盒并做一次简短回顾。'
        assert next(item for item in revised['items'] if item['type'] == 'deck')['completion_rule'] == authored_requirement
        from app.m5_resources import resource_generation_blocker
        old_deck = session.get(DBArtifactVersion, old_versions['deck'])
        assert not resource_generation_blocker(session, session.get(DBArtifact, old_deck.artifact_id), old_deck.id)
        attempts = session.query(DBTaskStep).filter_by(task_id=job['job_id']).count()
        bundles.revise_generation_job(session, learner, job['job_id'], **revision_args)
        assert session.query(DBTaskStep).filter_by(task_id=job['job_id']).count() == attempts
        second = execute_generation_job(session, learner, job['job_id'])
        assert second['status'] == 'succeeded', second.get('failure_reason')
        assert generated.count('code_sandbox') == 2 and generated.count('deck') == 1
        assert len(plan_inputs) == 2
        revision_context = plan_inputs[-1]['teaching_revision']
        assert revision_context['feedback'] == revision_args['feedback']
        assert 'previous_plan' not in revision_context
        assert plan_inputs[-1]['retained_resources'][0]['version_id'] == old_versions['deck']
        new_versions = {item['type']: item['resource']['version']['id'] for item in second['items']}
        assert new_versions['deck'] == old_versions['deck']
        assert new_versions['code_sandbox'] != old_versions['code_sandbox']
        assert all(session.get(DBArtifactVersion, version).content == old_text[kind] for kind, version in old_versions.items())
        assert session.query(DBLearningEvent).count() == before_learning
        assert session.query(DBTaskEvent).filter_by(task_id=job['job_id'], event_type='publish.completed').count() == 2
        first_revision_event = session.query(DBTaskEvent).filter_by(task_id=job['job_id'],
            event_type='resource_generation.revision.requested').one()
        # Simulate an already saved task from before the ordered history field.
        legacy_payload = json.loads(json.dumps(first_revision_event.payload))
        legacy_payload['manifest'].pop('teaching_revision_history', None)
        first_revision_event.payload = legacy_payload
        session.flush()
        prior_payload = json.dumps(first_revision_event.payload, sort_keys=True)
        followup_feedback = '课件只调整末页，不撤销先观察再运行的安排。'
        bundles.revise_generation_job(session, learner, job['job_id'], feedback=followup_feedback,
            resource_types=['deck'], idempotency_key='teaching-revision-second')
        start = len(model_inputs)
        third = execute_generation_job(session, learner, job['job_id'])
        assert third['status'] == 'succeeded'
        calls = model_inputs[start:]
        assert {role for role, _ in calls} >= {'resource_planner','resource_generator','resource_reviewer'}
        for _, data in calls:
            assert 'teaching_revision_history' not in data
            assert '先观察数据再运行代码' in data['active_requirements']['shared']
        assert json.dumps(first_revision_event.payload, sort_keys=True) == prior_payload
        assert json.dumps(original_event.payload, sort_keys=True) == original_manifest
        assert session.query(DBLearningEvent).count() == before_learning
    finally:
        session.close()
        engine.dispose()


def test_candidate_is_saved_before_slow_sibling_finishes(monkeypatch):
    import asyncio
    from app.database import DBTaskEvent
    saved = None
    class Backend(_FakeLiveBackend):
        async def generate(self, system_prompt, user_prompt, *, role):
            nonlocal saved
            if role == 'resource_generator':
                kind = json.loads(user_prompt)['resource_type']
                if saved is None:
                    saved = asyncio.Event()
                if kind == 'deck':
                    await asyncio.wait_for(saved.wait(), timeout=1)
            return await super().generate(system_prompt, user_prompt, role=role)
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username='lzz').one()
        monkeypatch.setattr('app.resource_bundles._real_model_backend', lambda: Backend())
        job = create_generation_job(session, learner, course_id='demo-course-rag-trust-v1',
            knowledge_point_id='demo-kp-07', profile_snapshot_id='demo-profile-lzz-v1',
            idempotency_key='candidate-progress-before-sibling', scope='bundle', learning_goal='逐项保存',
            items=[{'type': kind, 'title': kind, 'source_ref_ids': ['demo-ref-07']}
                   for kind in ('deck', 'code_sandbox')])
        def progress(event):
            if event['event_type'] == 'resource.item.completed' and event['resource_type'] == 'code_sandbox':
                assert session.query(DBTaskEvent).filter_by(task_id=job['job_id'],
                    event_type='resource_generation.item.succeeded').count() == 1
                saved.set()
        result = execute_generation_job(session, learner, job['job_id'], event_callback=progress)
        assert result['status'] == 'succeeded', result.get('failure_reason')
    finally:
        session.close(); engine.dispose()


def test_live_bundle_keeps_one_model_loop_and_completes_all_nine_resources(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.get(DBProfileSnapshot, "demo-profile-lzz-v1")
        source = session.get(DBSourceRef, "demo-ref-07")
        assert profile is not None and source is not None
        monkeypatch.setattr("app.resource_bundles._real_model_backend", lambda: _FakeLiveBackend())
        resource_types = ["handout", "mind_map", "quiz", "training_task", "code_sandbox", "video", "deck", "interactive_model", "feynman"]
        job = create_generation_job(
            session, learner, course_id="demo-course-rag-trust-v1", knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id, idempotency_key="pr01-live-bundle-001", scope="bundle",
            items=[{"type": resource_type, "title": resource_type, "source_ref_ids": [source.id]} for resource_type in resource_types],
            learning_goal="验证整包真实模型生成",
        )
        result = execute_generation_job(session, learner, job["job_id"])
        if result["status"] != "succeeded":
            print(json.dumps([{"event": event.get("event_type"), "summary": event.get("summary")} for event in result["events"] if "review" in event.get("event_type", "")],ensure_ascii=False))
        assert result["status"] == "succeeded", {"failure": result.get("failure_reason"), "items": [
            {"type": item["type"], "state": item["state"], "failure": item.get("failure")} for item in result["items"]]}
        assert all(item["state"] == "succeeded" for item in result["items"])
        assert all(item["resource"]["generation"]["mode"] == "llm" for item in result["items"])
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize("step_count", [1, 2])
def test_short_handout_preserves_real_steps_through_generation_and_publication(step_count):
    import asyncio
    import app.resource_bundles as bundles
    from app.m5_resources import parse_handout_content

    class ShortBackend(_FakeLiveBackend):
        calls = 0
        async def generate(self, system_prompt, user_prompt, *, role):
            self.calls += 1
            payload = json.loads(await super().generate(system_prompt, user_prompt, role=role))
            payload["practiceSteps"] = payload["practiceSteps"][:step_count]
            return json.dumps(payload, ensure_ascii=False)

    backend = ShortBackend()
    manifest = _manifest(knowledge_point="模型选择", profile="已会比较，练习新条件", mastery="已掌握")
    sources = [_source(source_ref_id="src-short", title="验证", quote="模型按验证误差选择。")]
    payload = asyncio.run(bundles._real_model_payload_async(backend, resource_type="handout",
        item={"title": "新条件下选择模型"}, manifest=manifest, source_snapshots=sources))
    assert backend.calls == 1
    content = bundles._llm_resource_content(resource_type="handout", item={"title": "新条件下选择模型"},
        manifest=manifest, source_snapshots=sources, linked_resource_ids=[], llm_payload=payload)
    published = parse_handout_content(content)
    assert len(published.miniQuiz) == len(payload["quizQuestions"])
    assert published.profileAdaptation.scaffolding[1:] == [step["instruction"] for step in payload["practiceSteps"]]

    payload["practiceSteps"] = []
    with pytest.raises(bundles.ResourceBundleError, match="完整学习步骤"):
        bundles._llm_resource_content(resource_type="handout", item={"title": "未完成讲义"},
            manifest=manifest, source_snapshots=sources, linked_resource_ids=[], llm_payload=payload)


@pytest.mark.parametrize('task_first', [True, False])
def test_independent_handout_task_keeps_authored_position_and_separate_answer(task_first):
    import asyncio
    import app.resource_bundles as bundles
    from app.m5_resources import parse_handout_content

    class TaskBackend(_FakeLiveBackend):
        async def generate(self, system, user, *, role):
            payload = json.loads(await super().generate(system, user, role=role))
            task = {'id':'new-choice', 'title':'比较新候选', 'kind':'task',
                'content':'甲乙验证误差为0.12和0.08，按相同规则选择并解释。',
                'hint':'比较同一列误差。', 'successCheck':'选择乙；其验证误差0.08较低。',
                'sourceRefIds':['src-selection']}
            method = {'id':'method', 'title':'需要时回看方法', 'kind':'concept',
                'content':'验证误差衡量留出数据上的损失，按预定规则比较候选。'}
            payload['handoutSections'] = [task, method] if task_first else [method, task]
            payload['transferQuestions'] = [{'title':'检查数据角色', 'prompt':'若同一验证分数又用来选模型，能当最终测试吗？',
                                             'successCheck':'它已参与选择，需要另留测试。'}]
            return json.dumps(payload,ensure_ascii=False)

    manifest = _manifest(knowledge_point='验证选模', profile='已会比较', mastery='已掌握')
    sources = [_source(source_ref_id='src-selection', title='验证选模', quote='用验证误差比较。')]
    payload = asyncio.run(bundles._real_model_payload_async(TaskBackend(), resource_type='handout',
        item={'title':'新条件下的比较'}, manifest=manifest, source_snapshots=sources))
    content = bundles._llm_resource_content(resource_type='handout', item={'title':'新条件下的比较'},
        manifest=manifest, source_snapshots=sources, linked_resource_ids=[], llm_payload=payload)
    published = parse_handout_content(content)
    expected = ['legacy-new-choice','legacy-method'] if task_first else ['legacy-method','legacy-new-choice']
    assert [s.id for s in published.outline][:2] == expected
    assert len(published.transferTasks) == 2
    task = next(t for t in published.transferTasks if t.id == 'legacy-new-choice')
    assert task.successCheck == '选择乙；其验证误差0.08较低。'
    assert task.hint == '比较同一列误差。'
    assert task.sourceRefIds == ['src-selection']
    visible = [task.prompt, *[c.explanation for c in published.concepts],
               *[e.body for e in published.examples]]
    assert all(task.successCheck not in s for s in visible)
    assert len(published.miniQuiz) == 3
    assert sum(s.id == task.id for s in published.outline) == 1

    next(s for s in payload['handoutSections'] if s['kind']=='task').pop('successCheck')
    with pytest.raises(bundles.ResourceBundleError, match='核对内容'):
        bundles._llm_resource_content(resource_type='handout', item={'title':'新条件下的比较'},
            manifest=manifest, source_snapshots=sources, linked_resource_ids=[], llm_payload=payload)
