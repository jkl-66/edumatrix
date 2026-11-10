from __future__ import annotations

import json
import asyncio
from types import SimpleNamespace
from pathlib import Path

from app.profile_adaptation import (
    build_profile_adaptation,
    profile_answer_instruction,
    profile_prompt_context,
)
from app.resource_bundles import _deterministic_demo_content, _real_model_prompt
import stream_api
from stream_api import (
    _adaptation_boundary_note,
    _adaptation_reply_note,
    _canonical_chat_prompts,
    _generate_suggested_questions,
    _legacy_profile_adaptation,
    _socratic_adaptation_instruction,
    _socratic_fallback,
)


POINT = {"id": "kp-rag", "title": "混合检索", "code": "RAG-01"}


def _profile(**overrides):
    values = {
        "major": "计算机科学与技术",
        "target_course": "机器学习与检索",
        "knowledge_base": "有 Python 基础，但刚接触向量检索",
        "cognitive_style": "分步推导",
        "motivation_type": "岗位实践",
        "focus_level": 0.7,
        "cognitive_load": 0.4,
        "frustration_index": 0.2,
        "learning_goals": ["完成检索工程实训"],
        "weak_points": ["混合检索"],
        "interaction_preferences": ["分步讲解", "代码实操"],
        "misconception_patterns": {},
        "dimension_states": {
            "knowledge_mastery": {"score": 0.35, "summary": "当前知识点仍需巩固"},
            "understanding_fluency_transfer": {"score": 0.35, "summary": "需要更多迁移练习"},
        },
        "concept_mastery": {"kp-rag": 0.35},
        "knowledge_traces": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_three_complete_profiles_have_observable_adaptation_differences():
    profiles = [
        _profile(
            major="软件工程",
            knowledge_base="零基础，第一次学习 RAG",
            cognitive_style="分步讲解",
            interaction_preferences=["例子", "分步讲解"],
            concept_mastery={"kp-rag": 0.2},
            dimension_states={"cognitive_load": {"score": 0.8, "summary": "一次处理的信息不宜过多"}},
        ),
        _profile(
            major="数据科学与大数据技术",
            knowledge_base="熟悉 Python、向量库和评估指标",
            cognitive_style="代码实操",
            interaction_preferences=["项目实践"],
            concept_mastery={"kp-rag": 0.86},
            weak_points=[],
            dimension_states={"understanding_fluency_transfer": {"score": 0.9, "summary": "能迁移到新数据"}},
        ),
        _profile(
            major="人工智能",
            knowledge_base="理论基础较强，但混合检索的权重选择容易混淆",
            cognitive_style="公式推导",
            interaction_preferences=["推导", "反例"],
            concept_mastery={"kp-rag": 0.58},
            misconception_patterns={"权重无需归一化": 0.8},
        ),
    ]
    plans = [build_profile_adaptation(None, profile=profile, knowledge_point=POINT) for profile in profiles]

    assert [plan["difficulty_band"] for plan in plans] == ["foundation", "transfer", "scaffolded"]
    assert len({plan["difficulty_label"] for plan in plans}) == 3
    assert len({plan["explanation_style"] for plan in plans}) == 3
    assert len({plan["practice_strategy"] for plan in plans}) == 3
    assert plans[0]["scaffolding_level"] == "high"
    assert plans[1]["scaffolding_level"] == "light"
    assert plans[2]["content_focus"] == "混合检索"
    assert plans[0]["registration_profile"]["major"] == "软件工程"


def test_current_topic_does_not_inherit_an_unrelated_global_weakness():
    profile = _profile(weak_points=["scikit-learn 训练与推理接口", "混合检索的权重选择"])
    plan = build_profile_adaptation(None, profile=profile, knowledge_point={"id": "eda", "title": "探索性数据分析"})
    assert plan["content_focus"] == "探索性数据分析的核心概念、条件和应用"
    assert "scikit-learn" not in plan["summary"]
    assert profile.weak_points == ["scikit-learn 训练与推理接口", "混合检索的权重选择"]
    related = build_profile_adaptation(None, profile=profile, knowledge_point=POINT)
    assert related["content_focus"] == "混合检索的权重选择"


def test_zero_mastery_is_kept_and_reported_weakness_does_not_create_a_score():
    for mastery in (0, {"mastery": 0, "score": 0.9}):
        plan = build_profile_adaptation({"concept_mastery": {"kp-rag": mastery}}, knowledge_point=POINT)
        assert plan["point_mastery"] == 0
        assert plan["difficulty_band"] == "foundation"
    overall = build_profile_adaptation({"course_mastery": 0, "overall_mastery": 0.9})
    assert overall["point_mastery"] == 0
    weak = build_profile_adaptation({"weak_points": [POINT["title"]]}, knowledge_point=POINT)
    assert weak["difficulty_band"] == "foundation"
    assert weak["point_mastery"] is None
    assert "35%" not in weak["summary"]
    assert weak["difficulty_evidence"]["kind"] == "reported_weakness"


def test_preference_changes_teaching_but_not_ability_and_basis_changes_task_level():
    plans = [build_profile_adaptation(None, profile=_profile(
        cognitive_style=style, concept_mastery={POINT["id"]: 0.58},
    ), knowledge_point=POINT) for style in ("直观图示", "代码实践", "理论推导")]
    assert len({plan["explanation_style"] for plan in plans}) == 3
    assert {plan["difficulty_band"] for plan in plans} == {"scaffolded"}
    assert all(plan["assessment_target"] == plans[0]["assessment_target"] for plan in plans)
    levels = [build_profile_adaptation(None, profile=_profile(
        cognitive_style="代码实践", concept_mastery={POINT["id"]: score},
    ), knowledge_point=POINT) for score in (0.2, 0.58, 0.86)]
    assert len({plan["assessment_target"]["task"] for plan in levels}) == 3
    assert len({plan["explanation_style"] for plan in levels}) == 1
    assert profile_prompt_context(levels[0])["assessment_target"] == levels[0]["assessment_target"]


def test_confirmed_teaching_order_and_negation_survive_the_shared_prompt():
    for style in (
        "先用直观小例子和两行手算，再介绍公式，每个符号说明含义",
        "先看最小可运行例子、输入输出和验证办法，再理解机制",
        "不喜欢公式推导",
        "从定义、假设和目标函数推导，再用反例检查边界",
    ):
        snapshot = {"cognitive_style": style, "concept_mastery": {POINT['id']: 0.58}}
        plan = profile_prompt_context(build_profile_adaptation(snapshot, knowledge_point=POINT))
        assert plan['explanation_style'] == style
        assert plan['point_mastery'] == 0.58
        assert plan['difficulty_band'] == 'scaffolded'
    preferences = ['先看例子', '逐步解释', '先不讲公式', '每次一步', '卡住再提示', '最后再给反例']
    plan = profile_prompt_context(build_profile_adaptation({'interaction_preferences': preferences}, knowledge_point=POINT))
    assert all(item in plan['explanation_style'] for item in preferences)
    assert plan['interaction_mode'] == plan['explanation_style']
    from app.profile_adaptation import profile_answer_instruction
    assert plan['explanation_style'] in profile_answer_instruction(plan, for_question=True)


def test_reported_gap_in_current_topic_adds_support_without_inventing_mastery():
    snapshot = {'knowledge_base': '会Python列表和平方；尚未系统学过导数、矩阵运算与反向传播；不是测验成绩'}
    point = {'id': 'backprop', 'title': '多层感知机与反向传播'}
    plan = build_profile_adaptation(snapshot, knowledge_point=point)
    assert plan['point_mastery'] is None
    assert plan['difficulty_band'] == 'foundation'
    assert plan['scaffolding_level'] == 'high'
    unrelated = build_profile_adaptation(snapshot, knowledge_point={'id': 'python', 'title': '列表和循环'})
    assert unrelated['difficulty_band'] == 'scaffolded'
    recorded = build_profile_adaptation({**snapshot, 'concept_mastery': {'backprop': 0.86}}, knowledge_point=point)
    assert recorded['point_mastery'] == 0.86
    assert recorded['difficulty_band'] == 'transfer'


def test_resource_prompt_contains_machine_actionable_profile_plan():
    profile = _profile(
        knowledge_base="零基础，第一次学习 RAG",
        concept_mastery={"kp-rag": 0.2},
    )
    adaptation = profile_prompt_context(build_profile_adaptation(None, profile=profile, knowledge_point=POINT))
    manifest = {
        "knowledge_point_id": "kp-rag",
        "user_instruction": "重点比较关键词检索与向量检索的适用条件，并给一个反例。",
        "context": {
            "course_title": "机器学习与检索",
            "knowledge_point_title": "混合检索",
            "learning_goal": "完成一次检索评估",
            "profile_adaptation": "难度：入门巩固",
            "profile_adaptation_plan": adaptation,
            "profile_context": adaptation,
            "mastery_summary": "当前掌握度约 20%",
            "recent_learning_summary": "暂无近期记录",
        },
    }
    system, user = _real_model_prompt(
        resource_type="handout",
        item={"title": "入门讲义"},
        manifest=manifest,
        source_snapshots=[{"source_ref_id": "src-1", "title": "检索章节", "location_label": "第 1 章", "quote": "关键词和向量检索可以组合。"}],
    )
    payload = json.loads(user)
    assert payload["learner_adaptation"]["difficulty_band"] == "foundation"
    assert "必须把 learner_adaptation" in system
    assert "三级提示" in payload["learner_adaptation"]["hint_policy"]
    assert payload["user_instruction"] == manifest["user_instruction"]


def test_full_ten_dimension_projection_is_preserved():
    dimension_keys = {
        "knowledge_mastery",
        "misconception_profile",
        "understanding_fluency_transfer",
        "cognitive_processing",
        "learning_strategy",
        "metacognition",
        "motivation_and_purpose",
        "affect_resilience",
        "interaction_preference",
        "learning_context",
    }
    profile = _profile(
        dimension_states={
            key: {"score": 0.5, "summary": f"{key} 已记录"}
            for key in dimension_keys
        }
    )
    plan = build_profile_adaptation(None, profile=profile, knowledge_point=POINT)
    assert set(plan["dimensions"]) == dimension_keys
    assert set(profile_prompt_context(plan)["dimensions"]) == dimension_keys


def test_canonical_chat_prompt_exposes_profile_plan_without_private_fields():
    adaptation = profile_prompt_context(build_profile_adaptation(None, profile=_profile(concept_mastery={"kp-rag": 0.86}), knowledge_point=POINT))
    user_message = SimpleNamespace(content="如何调节混合检索权重？")
    assistant = SimpleNamespace(content="")
    system, user, _ = _canonical_chat_prompts(
        {
            "history": [],
            "attachments": [],
            "source_materials": [],
            "context_snapshot": {
                "profile_adaptation_plan": adaptation,
                "profile_adaptation_summary": "难度：进阶迁移；支架：轻量",
            },
            "assistant_message": assistant,
            "user_message": user_message,
        },
        "",
    )
    assert "进阶迁移" in user
    assert "减少铺垫并增加迁移比较" in system
    assert "reasoning_content" in system


def test_shared_answer_instruction_changes_the_required_teaching_move_by_profile():
    foundation = profile_prompt_context(
        build_profile_adaptation(None, profile=_profile(concept_mastery={"kp-rag": 0.2}), knowledge_point=POINT)
    )
    scaffolded = profile_prompt_context(
        build_profile_adaptation(None, profile=_profile(concept_mastery={"kp-rag": 0.58}), knowledge_point=POINT)
    )
    transfer = profile_prompt_context(
        build_profile_adaptation(None, profile=_profile(concept_mastery={"kp-rag": 0.86}, weak_points=[]), knowledge_point=POINT)
    )
    instructions = [
        profile_answer_instruction(plan)
        for plan in (foundation, scaffolded, transfer)
    ]
    assert len(set(instructions)) == 3
    assert "前置概念" in instructions[0]
    assert "基线例子" in instructions[1]
    assert "边界" in instructions[2]
    assert all("十维 dimensions" in instruction for instruction in instructions)


def test_empty_registration_profile_keeps_legacy_answers_neutral():
    # Registration creates a storage row with numeric defaults.  That row is
    # not learner evidence, so legacy academic and non-academic prompts must
    # remain neutral until the user has supplied a real signal.
    empty_profile = SimpleNamespace(
        major="",
        target_course="",
        knowledge_base="",
        cognitive_style="",
        motivation_type="",
        focus_level=0.72,
        cognitive_load=0.45,
        frustration_index=0.0,
        learning_goals=[],
        weak_points=[],
        interaction_preferences=[],
        misconception_patterns={},
        dimension_states={},
        concept_mastery={},
        knowledge_traces={},
    )
    assert _legacy_profile_adaptation(empty_profile, knowledge_point="混合检索") == {}
    assert "不要猜测学生背景" in profile_answer_instruction({})


def test_canonical_answer_prompt_contains_profile_specific_action_for_each_band():
    prompts = []
    for mastery in (0.2, 0.58, 0.86):
        plan = profile_prompt_context(
            build_profile_adaptation(
                None,
                profile=_profile(concept_mastery={"kp-rag": mastery}, weak_points=[] if mastery > 0.8 else ["混合检索"]),
                knowledge_point=POINT,
            )
        )
        _, user, _ = _canonical_chat_prompts(
            {
                "history": [],
                "attachments": [],
                "source_materials": [],
                "context_snapshot": {"profile_adaptation_plan": plan},
                "assistant_message": SimpleNamespace(content=""),
                "user_message": SimpleNamespace(content="解释混合检索"),
            },
            "",
        )
        prompts.append(user)
    assert "解释必要术语" in prompts[0]
    assert "基线例子" in prompts[1]
    assert "说明适用边界" in prompts[2]
    assert len(set(prompts)) == 3
    assert all("不强加练习或学习安排" in prompt for prompt in prompts)


def test_suggested_questions_consume_full_plan_and_profile_fallback_varies(monkeypatch):
    captured = []

    class Lifecycle:
        call_id = "test-call"

        async def start(self):
            return self.call_id

        async def complete(self, _output):
            return None

        async def fail(self, _error):
            return None

    class FailingLLM:
        model = "deepseek-v4-flash"

        async def generate(self, _system_prompt, user_prompt, *, role):
            captured.append(user_prompt)
            raise RuntimeError("test provider failure")

    monkeypatch.setattr(stream_api, "StreamingModelCallLifecycle", lambda **_kwargs: Lifecycle())
    beginner = asyncio.run(_generate_suggested_questions(
        SimpleNamespace(llm=FailingLLM()),
        "混合检索",
        _profile(concept_mastery={"kp-rag": 0.2}),
    ))
    transfer = asyncio.run(_generate_suggested_questions(
        SimpleNamespace(llm=FailingLLM()),
        "混合检索",
        _profile(concept_mastery={"kp-rag": 0.86}, weak_points=[]),
    ))
    assert beginner != transfer
    assert "learner_adaptation" in captured[0]
    assert "point_mastery" in captured[0]
    assert "dimensions" in captured[0]
    assert "foundation" in captured[0]
    assert "transfer" in captured[1]


def test_legacy_socratic_consultant_and_teacher_receive_profile_actions(monkeypatch):
    profile = _profile(
        knowledge_base="零基础，第一次学习 RAG",
        concept_mastery={"kp-rag": 0.2},
    )
    captured = {}

    class Backend:
        pass

    class Swarm:
        profile_store = {"socratic-owner": profile}
        async_generator = SimpleNamespace(llm=Backend())

    async def fake_plan(llm, **kwargs):
        captured["consultant"] = kwargs
        return {"pedagogical_move": "HINT_LADDER", "focus_concept": "混合检索"}

    async def fake_teacher(llm, **kwargs):
        captured["teacher"] = kwargs
        return "先检查检索词。"

    monkeypatch.setattr(stream_api, "build_swarm_from_headers", lambda headers: Swarm())
    monkeypatch.setattr(stream_api, "_plan_socratic_move", fake_plan)
    monkeypatch.setattr(stream_api, "_generate_socratic_teacher", fake_teacher)

    class RequestStub:
        headers = {}

        async def json(self):
            return {
                "student_id": "socratic-owner",
                "target_text": "混合检索的权重",
            }

    user = SimpleNamespace(
        public_id="socratic-public-id", username="socratic-owner", role="student"
    )
    result = asyncio.run(stream_api.socratic_explain(RequestStub(), user))

    assert result["status"] == "success"
    assert "learner_adaptation" in captured["consultant"]["user_prompt"]
    assert "foundation" in captured["consultant"]["user_prompt"]
    assert "foundation/high 支架" in captured["consultant"]["system_prompt"]
    assert "learner_adaptation" in captured["teacher"]["user_prompt"]
    assert "foundation/high 支架" in captured["teacher"]["system_prompt"]
    assert result["agent_trace"]["adaptation_note"]


def test_legacy_socratic_fallback_and_boundary_next_step_follow_profile():
    foundation = profile_prompt_context(
        build_profile_adaptation(None, profile=_profile(concept_mastery={"kp-rag": 0.2}), knowledge_point=POINT)
    )
    transfer = profile_prompt_context(
        build_profile_adaptation(None, profile=_profile(concept_mastery={"kp-rag": 0.86}, weak_points=[]), knowledge_point=POINT)
    )

    foundation_fallback = _socratic_fallback("混合检索", False, False, foundation)
    transfer_fallback = _socratic_fallback("混合检索", False, False, transfer)
    assert foundation_fallback != transfer_fallback
    assert "前置概念" in foundation_fallback
    assert "迁移" in transfer_fallback
    assert "最小例子" in _adaptation_boundary_note(foundation)
    assert "新数据" in _adaptation_boundary_note(transfer)
    assert "foundation/high 支架" in _socratic_adaptation_instruction(foundation)


def test_legacy_resource_completion_note_changes_with_profile_plan():
    beginner = profile_prompt_context(
        build_profile_adaptation(
            None,
            profile=_profile(concept_mastery={"kp-rag": 0.2}),
            knowledge_point=POINT,
        )
    )
    advanced = profile_prompt_context(
        build_profile_adaptation(
            None,
            profile=_profile(concept_mastery={"kp-rag": 0.86}, weak_points=[]),
            knowledge_point=POINT,
        )
    )
    assert _adaptation_reply_note(beginner) != _adaptation_reply_note(advanced)
    assert "入门巩固" in _adaptation_reply_note(beginner)
    assert "进阶迁移" in _adaptation_reply_note(advanced)


def test_resource_details_keep_teaching_strategy_out_of_page_chrome():
    for name in (
        "HandoutWorkspace.vue", "MindmapWorkspace.vue", "QuizResourceWorkspace.vue",
        "TrainingTaskWorkspace.vue", "CodeSandboxWorkspace.vue", "VideoRecommendationWorkspace.vue",
        "WebDeckWorkspace.vue", "InteractiveLabWorkspace.vue", "FeynmanWorkspace.vue",
    ):
        view = Path("frontend/src/views", name).read_text(encoding="utf-8")
        assert "ResourceProfileAdaptation" not in view
        assert "本次学习建议" not in view
    feynman_view = Path("frontend/src/views/FeynmanWorkspace.vue").read_text(encoding="utf-8")
    assert '<small>{{ session.adaptation_note }}</small>' not in feynman_view
    assert '<dt>画像版本</dt>' not in feynman_view
    assert '<dt>动态关注</dt>' not in feynman_view

    # Adaptation belongs in teaching content, not in repeated planning prose.
    handout_view = Path("frontend/src/views/HandoutWorkspace.vue").read_text(encoding="utf-8")
    assert "structured.profileAdaptation.summary" not in handout_view
    assert "<strong>学习支架</strong>" not in handout_view
    interactive_view = Path("frontend/src/views/InteractiveLabWorkspace.vue").read_text(encoding="utf-8")
    assert "structured.adaptation.profileSummary" not in interactive_view
    assert "adaptation-list" not in interactive_view
    deck_view = Path("frontend/src/views/WebDeckWorkspace.vue").read_text(encoding="utf-8")
    assert "学习目标与适配依据" not in deck_view
    assert "<dt>适配依据</dt>" not in deck_view
    video_view = Path("frontend/src/views/VideoRecommendationWorkspace.vue").read_text(encoding="utf-8")
    assert "<dt>适配依据</dt>" not in video_view
    bundle_view = Path("frontend/src/views/ResourceBundleWorkspace.vue").read_text(encoding="utf-8")
    assert "adaptation-band" not in bundle_view
    assert "本轮按画像调整" not in bundle_view
    assert "adaptationPlan" not in bundle_view


def _demo_manifest(profile_plan: dict) -> dict:
    return {
        "knowledge_point_id": "kp-rag",
        "context": {
            "knowledge_point_title": "混合检索",
            "learning_goal": "完成一次检索评估",
            "profile_adaptation": profile_plan["difficulty_label"],
            "profile_adaptation_plan": profile_plan,
            "mastery_summary": f"当前掌握度约为 {round(profile_plan['point_mastery'] * 100)}%",
            "recent_learning_summary": "暂无近期有效记录",
        },
    }


def test_deterministic_resource_body_changes_with_profile_not_only_metadata():
    source = [{"source_ref_id": "src-rag", "title": "检索章节", "location_label": "第 4 章", "quote": "关键词、向量和混合检索用于评估召回。"}]
    beginner = profile_prompt_context(build_profile_adaptation(None, profile=_profile(concept_mastery={"kp-rag": 0.2}), knowledge_point=POINT))
    advanced = profile_prompt_context(build_profile_adaptation(None, profile=_profile(concept_mastery={"kp-rag": 0.86}, weak_points=[], cognitive_style="代码实操"), knowledge_point=POINT))
    beginner_body = json.loads(_deterministic_demo_content(resource_type="handout", item={"title": "入门讲义"}, manifest=_demo_manifest(beginner), source_snapshots=source))
    advanced_body = json.loads(_deterministic_demo_content(resource_type="handout", item={"title": "进阶讲义"}, manifest=_demo_manifest(advanced), source_snapshots=source))
    assert beginner_body["estimatedMinutes"] != advanced_body["estimatedMinutes"]
    assert beginner_body["outline"] != advanced_body["outline"]
    assert beginner_body["concepts"][0]["explanation"] != advanced_body["concepts"][0]["explanation"]
    assert beginner_body["examples"] != advanced_body["examples"]


def test_deterministic_mind_map_and_code_use_profile_variant():
    source = [{"source_ref_id": "src-rag", "title": "检索章节", "location_label": "第 4 章", "quote": "关键词、向量和混合检索用于评估召回。"}]
    beginner = profile_prompt_context(build_profile_adaptation(None, profile=_profile(concept_mastery={"kp-rag": 0.2}), knowledge_point=POINT))
    advanced = profile_prompt_context(build_profile_adaptation(None, profile=_profile(concept_mastery={"kp-rag": 0.86}, weak_points=[]), knowledge_point=POINT))
    beginner_map = json.loads(_deterministic_demo_content(resource_type="mind_map", item={"title": "入门导图"}, manifest=_demo_manifest(beginner), source_snapshots=source))
    advanced_map = json.loads(_deterministic_demo_content(resource_type="mind_map", item={"title": "进阶导图"}, manifest=_demo_manifest(advanced), source_snapshots=source))
    assert {node["label"] for node in beginner_map["nodes"]} != {node["label"] for node in advanced_map["nodes"]}
    assert beginner_map["nodes"][0]["summary"] != advanced_map["nodes"][0]["summary"]
    beginner_code = json.loads(_deterministic_demo_content(resource_type="code_sandbox", item={"title": "入门实验"}, manifest=_demo_manifest(beginner), source_snapshots=source))
    advanced_code = json.loads(_deterministic_demo_content(resource_type="code_sandbox", item={"title": "进阶实验"}, manifest=_demo_manifest(advanced), source_snapshots=source))
    assert beginner_code["standardInput"] != advanced_code["standardInput"]
