from __future__ import annotations

import json

import pytest

import app.resource_bundles as resource_bundles


def test_deck_generation_does_not_require_hidden_practice_code_or_quiz():
    import asyncio
    payload={'summary':'比较训练与验证误差','learningGoal':'判断哪轮验证表现更好',
             'narrative':'依据验证误差比较，不能只看训练误差。' * 150,
             'slides':[{'title':'比较模型表现','body':'第一轮训练0.6、验证0.62；第二轮训练0.25、验证0.30。第二轮验证误差更低。'}]}
    calls=[]
    class Backend:
        async def generate(self,system,user,**kwargs):
            calls.append((system,user))
            return json.dumps(payload,ensure_ascii=False)
    snapshots=[{'source_ref_id':'src-b13','title':'误差比较','quote':'第二轮验证误差更低。'}]
    generated=asyncio.run(resource_bundles._real_model_payload_async(Backend(),resource_type='deck',
        item={'title':'误差比较'},manifest=_manifest(),source_snapshots=snapshots))
    content=json.loads(resource_bundles._llm_resource_content(resource_type='deck',item={'title':'误差比较'},
        manifest=_manifest(),source_snapshots=snapshots,linked_resource_ids=[],llm_payload=generated))
    assert len(calls)==1
    assert content['slides'][0]['body']==payload['slides'][0]['body']
    assert content['adaptationSummary']==payload['narrative']
    assert '来源引用只绑定实际支持的内容' in calls[0][0]
    assert '不给这些补充内容伪造课程事实、来源、页码或 source_ref' in calls[0][0]
    assert '本类型另外需要slides' in calls[0][0]


def test_long_training_body_and_steps_are_preserved_with_execution_checks():
    from app.training_tasks import parse_training_task_content
    payload = _payload()
    payload.update(environment=['浏览器内的课程实验'], data=['明确标注的教学样本'])
    payload['narrative'] = ('Explain the experiment, fixed assumptions, observations and next action. ' * 120).strip()
    payload['practiceSteps'][0]['instruction'] = ('Read the full conditions and record the observed values. ' * 170).strip()
    content = resource_bundles._llm_resource_content(resource_type='training_task', item={'title':'完整实训'},
        manifest=_manifest(), source_snapshots=[{'source_ref_id':'source','quote':'实验条件'}],
        linked_resource_ids=['code','experiment'],llm_payload=payload)
    parsed = parse_training_task_content(content)
    assert payload['narrative'] in parsed.objective
    assert parsed.steps[0].instruction == payload['practiceSteps'][0]['instruction']
    broken = json.loads(content)
    broken['checkpoints'][0]['afterStepId'] = 'missing-step'
    with pytest.raises(ValueError):
        parse_training_task_content(json.dumps(broken))


def test_mindmap_preserves_model_concept_hierarchy_instead_of_flattening_steps():
    payload = {
        "summary":"区分优化与正则化", "narrative":"按概念关系组织知识。", "learningGoal":"理解AdamW与暂退法",
        "rootNodeId":"training", "nodes":[
            {"nodeId":"training","parentNodeId":None,"label":"优化与正则化","summary":"区分降低训练损失与改善泛化。","relation":"主题","depth":0},
            {"nodeId":"reg","parentNodeId":"training","label":"正则化","summary":"控制模型拟合训练数据的程度。","relation":"组成","depth":1},
            {"nodeId":"dropout","parentNodeId":"reg","label":"暂退法","summary":"训练时随机屏蔽并缩放，推理时保持输入。","relation":"Regularisation method: random masking during training preserves inference inputs and changes expected activations only with the stated scaling.","depth":2},
        ],
    }
    def build(value):
        return json.loads(resource_bundles._llm_resource_content(resource_type="mind_map",item={"title":"教材选区"},
            manifest=_manifest(),source_snapshots=[{"source_ref_id":"source","quote":"暂退法是正则化的一种方法。"}],
            linked_resource_ids=[],llm_payload=value))
    content=build(payload)
    assert content["rootNodeId"]=="training"
    assert content["nodes"][0]["label"]=="优化与正则化"
    assert content["nodes"][2]["parentNodeId"]=="reg" and content["nodes"][2]["depth"]==2
    assert content["nodes"][2]["relation"]==payload["nodes"][2]["relation"]
    assert all(node["masteryBand"]=="unknown" and node["sourceRefs"]==["source"] for node in content["nodes"])
    import copy
    for bad in ("source", "cycle", "legacy_steps"):
        broken=copy.deepcopy(payload)
        if bad=="source": broken["nodes"][2]["sourceRefs"]=["unselected"]
        elif bad=="cycle": broken["nodes"][1]["parentNodeId"]="dropout"
        else: broken.pop("nodes");broken["practiceSteps"]=_payload()["practiceSteps"]
        with pytest.raises(resource_bundles.ResourceBundleError): build(broken)


def _manifest() -> dict:
    return {
        "course_id": "course-b13",
        "knowledge_point_id": "kp-b13",
        "context": {
            "course_title": "B13 课程",
            "knowledge_point_title": "模型训练边界",
            "learning_goal": "理解模型训练中的边界条件",
            "profile_adaptation": "按当前画像提供入门解释",
            "mastery_summary": "正在建立基础理解",
            "recent_learning_summary": "最近练习了梯度更新",
        },
    }


def _payload() -> dict:
    return {
        "summary": "MODEL_UNIQUE_SUMMARY_B13",
        "narrative": "MODEL_UNIQUE_NARRATIVE_B13 说明训练边界和验证步骤。",
        "learningGoal": "MODEL_UNIQUE_GOAL_B13",
        "estimatedMinutes": 40,
        "starterCode": "print('MODEL_UNIQUE_CODE_B13')\n",
        "practiceSteps": [
            {
                "title": "模型输入",
                "instruction": "检查模型输入",
                "expectedResult": "得到输入字段",
                "errorGuidance": "回查冻结来源",
            },
            {
                "title": "参数更新",
                "instruction": "观察参数更新",
                "expectedResult": "记录更新结果",
                "errorGuidance": "核对学习率",
            },
            {
                "title": "运行观察",
                "instruction": "运行一次实验",
                "expectedResult": "保存输出",
                "errorGuidance": "保留错误信息",
            },
            {
                "title": "边界验证",
                "instruction": "验证边界条件",
                "expectedResult": "写下适用范围",
                "errorGuidance": "回到课程来源",
            },
        ],
        "quizQuestions": [
            {
                "prompt": "MODEL_UNIQUE_QUESTION_B13",
                "options": {
                    "A": "核对输入条件并验证训练边界",
                    "B": "只看训练分数就确定适用范围",
                    "C": "忽略输入条件直接增加训练次数",
                    "D": "用测试结果反复选择训练参数",
                },
                "answer": "A",
                "explanation": "MODEL_UNIQUE_EXPLANATION_B13",
            }
        ],
    }


def test_live_resource_body_uses_model_payload_without_demo_generator(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(**_kwargs):
        raise AssertionError("live resource content must not call deterministic demo content")

    monkeypatch.setattr(resource_bundles, "_deterministic_demo_content", fail_if_called)
    content = resource_bundles._llm_resource_content(
        resource_type="handout",
        item={"type": "handout", "title": "B13 真实讲义"},
        manifest=_manifest(),
        source_snapshots=[
            {
                "source_ref_id": "src-b13",
                "title": "B13 课程来源",
                "quote": "训练边界需要依据课程来源验证。",
                "location_label": "第 1 章 / 第 2 页",
            }
        ],
        linked_resource_ids=[],
        llm_payload=_payload(),
    )

    parsed = json.loads(content)
    assert parsed["summary"] == "MODEL_UNIQUE_SUMMARY_B13"
    assert parsed["concepts"][0]["explanation"].endswith("MODEL_UNIQUE_NARRATIVE_B13 说明训练边界和验证步骤。")
    assert parsed["codeBlocks"][0]["code"].strip() == "print('MODEL_UNIQUE_CODE_B13')"
    assert parsed["miniQuiz"][0]["options"] == list(_payload()["quizQuestions"][0]["options"].values())
    assert parsed["miniQuiz"][0]["correctIndex"] == 0
    assert "MODEL_UNIQUE_SUMMARY_B13" in content
    assert "deterministic" not in content.lower()


def test_handout_preserves_teaching_order_review_and_code_content_without_dropping_conditions():
    payload = _payload()
    payload['starterCode'] = "```python\nprint(18)\n```"
    payload['handoutSections'] = [
        {'id': 'example', 'kind': 'example', 'title': '先算例子', 'content': '12+6=18'},
        {'id': 'code', 'kind': 'code', 'title': '可运行检查', 'code': 'print(12+6)', 'explanation': '输出18。'},
        {'id': 'principle', 'kind': 'concept', 'title': '机制', 'content': '共享参数累加。'},
        {'id': 'review', 'kind': 'review', 'title': '回顾', 'content': '说明各项来自哪里。'},
        {'id': 'read-code', 'kind': 'code', 'title': '阅读代码', 'content': '先预测结果：\n```python\nprint(18)\n```'},
    ]
    doc = json.loads(resource_bundles._llm_resource_content(resource_type='handout', item={'title': '梯度核对'},
        manifest=_manifest(), source_snapshots=[{'source_ref_id': 'src-b13', 'title': '资料', 'quote': '共享参数累加。'}],
        linked_resource_ids=[], llm_payload=payload))
    assert [item['title'] for item in doc['outline'][:5]] == ['先算例子', '可运行检查', '机制', '回顾', '阅读代码']
    assert any(item['explanation'] == '说明各项来自哪里。' for item in doc['concepts'])
    assert any('先预测结果' in item['explanation'] for item in doc['concepts'])
    assert doc['codeBlocks'][0]['code'] == 'print(18)'
    assert doc['counterExamples'][0]['body'].split('\n\n') == ['验证边界条件', '写下适用范围', '回到课程内容']
    assert '观察参数更新' not in doc['codeBlocks'][0]['explanation']


def test_explicit_neural_topic_is_not_overridden_by_retrieval_words_in_a_long_book():
    assert resource_bundles._practical_focus('多层感知机与反向传播', [{'quote': '整本教材含检索和分类，也包含反向传播。'}]) == '前向计算、梯度核对与参数更新验证'


def test_handout_retains_model_transfer_tasks_and_optional_hints_without_fabricating_answers():
    payload = _payload()
    payload['transferQuestions'] = ['把求和损失改为平均，比较梯度。', {
        'title': '独立参数对照', 'prompt': '参数相等时能否合并？',
        'hint': '先区分参数身份。', 'successCheck': '相同初值不代表参数共享。',
    }]
    doc = json.loads(resource_bundles._llm_resource_content(resource_type='handout', item={'title': '迁移'},
        manifest=_manifest(), source_snapshots=[{'source_ref_id':'src-b13','quote':'梯度取决于参数身份'}],
        linked_resource_ids=[], llm_payload=payload))
    assert [row['prompt'] for row in doc['transferTasks']] == ['把求和损失改为平均，比较梯度。', '参数相等时能否合并？']
    assert doc['transferTasks'][0]['hint'] == doc['transferTasks'][0]['successCheck'] == ''
    assert doc['transferTasks'][1]['successCheck'] == payload['transferQuestions'][1]['successCheck']
    assert [row['id'] for row in doc['outline'][-2:]] == [row['id'] for row in doc['transferTasks']]
    _, request = resource_bundles._real_model_prompt(resource_type='handout', item={'title': '迁移'},
        manifest=_manifest(), source_snapshots=[{'source_ref_id':'src-b13','quote':'梯度取决于参数身份'}])
    assert json.loads(request)['interactive_template'] is None


def test_handout_does_not_repeat_identical_starter_code_after_authored_code_section():
    payload = _payload()
    payload['handoutSections'] = [
        {'id': 'first-code', 'kind': 'code', 'title': '先读程序', 'code': payload['starterCode'], 'explanation': '从实际输出理解机制。'},
        {'id': 'concept', 'kind': 'concept', 'title': '再看原理', 'content': '核对条件。'},
    ]
    doc = json.loads(resource_bundles._llm_resource_content(resource_type='handout', item={'title': '代码先行'},
        manifest=_manifest(), source_snapshots=[{'source_ref_id': 'src-b13', 'quote': '核对条件。'}], linked_resource_ids=[], llm_payload=payload))
    assert len(doc['codeBlocks']) == 1
    assert doc['outline'][0]['id'] == doc['codeBlocks'][0]['id']
    assert doc['codeBlocks'][0]['explanation'] == '从实际输出理解机制。'


def test_complete_lesson_does_not_append_planning_steps_after_their_answers():
    payload = _payload()
    payload['handoutSections'] = [
        {'id': 'try', 'kind': 'example', 'title': '先判断', 'content': '先写出你的判断。'},
        {'id': 'limit', 'kind': 'counterexample', 'title': '再核对边界', 'content': '这里给出核对依据。'},
        {'id': 'review', 'kind': 'review', 'title': '回顾', 'content': '总结已经完成的判断。'},
    ]
    doc = json.loads(resource_bundles._llm_resource_content(resource_type='handout', item={'title': '完整讲义'},
        manifest=_manifest(), source_snapshots=[{'source_ref_id': 'src-b13', 'quote': '核对边界。'}],
        linked_resource_ids=[], llm_payload=payload))
    assert [item['title'] for item in doc['examples']] == ['先判断']
    assert [item['title'] for item in doc['counterExamples']] == ['再核对边界']
    assert [item['title'] for item in doc['concepts']] == ['回顾']
    assert [item['title'] for item in doc['outline'][:3]] == ['先判断', '再核对边界', '回顾']
    assert doc['codeBlocks'][0]['code'] == payload['starterCode'].strip()


def test_teaching_code_envelope_keeps_code_and_explanation_without_dictionary_text():
    original = _payload()
    code = original['starterCode']
    original['starterCode'] = {'code': code, 'explanation': '检查实际输出。', 'language': 'python'}
    normalized = resource_bundles._normalize_resource_code(original)
    assert normalized['starterCode'] == code
    assert normalized['codeExplanation'] == '检查实际输出。'
    assert isinstance(original['starterCode'], dict)
    doc = json.loads(resource_bundles._llm_resource_content(resource_type='handout', item={'title':'代码'},
        manifest=_manifest(), source_snapshots=[{'source_ref_id':'src-b13','quote':'检查输出'}], linked_resource_ids=[], llm_payload=normalized))
    assert doc['codeBlocks'][0]['code'] == code.strip()
    assert doc['codeBlocks'][0]['explanation'] == '检查实际输出。'


@pytest.mark.parametrize('starter', [None, ''])
def test_non_programming_handout_keeps_examples_without_inventing_code(starter):
    import asyncio
    from app.m5_resources import parse_handout_content

    payload = _payload()
    payload.pop('starterCode')
    if starter is not None:
        payload['starterCode'] = starter
    payload['quizQuestions'] *= 3
    # The actual asynchronous shape check expects option arrays.
    payload['quizQuestions'] = [{**q, 'options': list(q['options'].values())} for q in payload['quizQuestions']]
    payload['handoutSections'] = [
        {'id': 'exposure', 'kind': 'example', 'title': '记录曝光选择',
         'content': '快门从1/125秒缩短到1/250秒，保持光圈时感光器曝光量减半。记录运动清晰度与景深取舍。'}
    ]
    calls = []
    class Backend:
        async def generate(self, system, user, **kwargs):
            calls.append((system, user))
            return json.dumps(payload, ensure_ascii=False)
    manifest = _manifest()
    manifest['user_instruction'] = '摄影学习，不需要编程。'
    snapshots = [{'source_ref_id': 'src-b13', 'title': '曝光', 'quote': 'E与t成正比。'}]
    generated = asyncio.run(resource_bundles._real_model_payload_async(Backend(), resource_type='handout',
        item={'title': '曝光选择'}, manifest=manifest, source_snapshots=snapshots))
    doc = parse_handout_content(resource_bundles._llm_resource_content(resource_type='handout',
        item={'title': '曝光选择'}, manifest=manifest, source_snapshots=snapshots,
        linked_resource_ids=[], llm_payload=generated))
    assert len(calls) == 1
    assert doc.codeBlocks == []
    assert all(row.id != 'code-reading' for row in doc.outline)
    assert len(doc.miniQuiz) == 3
    assert doc.examples[0].body == payload['handoutSections'][0]['content']


def test_live_resource_body_rejects_missing_model_body_instead_of_fabricating(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        resource_bundles,
        "_deterministic_demo_content",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("demo path used")),
    )
    payload = _payload()
    payload["narrative"] = ""
    with pytest.raises(resource_bundles.ResourceBundleError) as exc_info:
        resource_bundles._llm_resource_content(
            resource_type="mind_map",
            item={"type": "mind_map", "title": "B13 真实导图"},
            manifest=_manifest(),
            source_snapshots=[{"source_ref_id": "src-b13", "title": "B13 来源", "quote": "边界"}],
            linked_resource_ids=[],
            llm_payload=payload,
        )
    assert exc_info.value.code == "resource_generation.model_output_invalid"


def test_training_report_and_rubric_include_later_experiment_and_reflection_steps():
    payload = _payload()
    payload.update(environment=["使用配套代码和实验"], data=["明确标注的合成数据"])
    payload["practiceSteps"].extend([
        {"title": "对照教学模拟", "instruction": "固定样本量，只改变复杂度。", "expectedResult": "记录峰值与泛化差距，明确为教学模拟。", "errorGuidance": "恢复基线后只改变一个参数。"},
        {"title": "整理完整报告", "instruction": "分别写代码实测、模拟观察和机制说明。", "expectedResult": "保存A至F六栏报告，区分模拟与实际运行。", "errorGuidance": "补齐缺少的观察。"},
    ])
    content = json.loads(resource_bundles._llm_resource_content(
        resource_type="training_task", item={"title": "训练与实验"}, manifest=_manifest(),
        source_snapshots=[{"source_ref_id": "src-b13", "title": "课程内容", "quote": "验证训练边界"}],
        linked_resource_ids=["code-b13", "lab-b13"], llm_payload=payload,
    ))
    assert len(content["steps"]) == len(content["checkpoints"]) == 6
    assert sum(item["points"] for item in content["rubric"]) == 100
    for step in payload["practiceSteps"]:
        assert any(item["description"] == step["instruction"] for item in content["deliverables"])
        assert any(item["evidence"] == step["instruction"] for item in content["rubric"])
        assert any(item["passCondition"] == step["expectedResult"] for item in content["checkpoints"])
    system, _ = resource_bundles._real_model_prompt(
        resource_type="training_task", item={"title": "训练与实验"}, manifest=_manifest(), source_snapshots=[],
    )
    assert "恰好 4 步" not in system and "四步 data/model/train/evaluate" not in system
    assert "交互实验对照" in system


def test_training_independent_answer_is_separate_from_report_requirements():
    import asyncio

    payload = _payload()
    payload.update(environment=["浏览器与纸笔"], data=["给定表与预测时点"])
    payload["practiceSteps"] = [{
        "title": "独立迁移", "instruction": "根据新表和预测时点选出可用输入，说明理由。",
        "submissionRequirement": "提交输入列及其在预测时是否已知的解释。",
        "expectedResult": "输入为学习分钟数、作业次数和是否通过，不含是否续报。",
        "errorGuidance": "逐列检查预测时是否已知。",
    }]
    class Backend:
        async def generate(self, system, user, **kwargs):
            return json.dumps(payload, ensure_ascii=False)
    snapshots = [{"source_ref_id": "src-b13", "quote": "预测时只能使用已知信息。"}]
    generated = asyncio.run(resource_bundles._real_model_payload_async(Backend(),
        resource_type="training_task", item={"title": "独立迁移"}, manifest=_manifest(), source_snapshots=snapshots))
    content = json.loads(resource_bundles._llm_resource_content(resource_type="training_task",
        item={"title": "独立迁移"}, manifest=_manifest(), source_snapshots=snapshots,
        linked_resource_ids=[], llm_payload=generated))
    assert len(content["steps"]) == 1
    assert content["estimatedMinutes"] == 40
    assert content["rubric"][0]["points"] == 100
    step = payload["practiceSteps"][0]
    assert content["deliverables"][0]["description"] == step["submissionRequirement"]
    assert content["rubric"][0]["evidence"] == step["submissionRequirement"]
    assert content["checkpoints"][0]["verification"] == step["submissionRequirement"]
    assert content["steps"][0]["expectedResult"] == step["expectedResult"]
    assert content["checkpoints"][0]["passCondition"] == step["expectedResult"]


def test_training_keeps_model_rubric_and_zero_point_optional_work():
    payload = _payload()
    payload.update(environment=["纸笔和配套实验"], data=["给定验证误差表"])
    payload["practiceSteps"][-1]["title"] = "可选拓展（0分）"
    payload["rubric"] = [
        {"id": f"rubric-{index + 1}", "criterion": step["title"],
         "evidence": f"独立核对第{index + 1}项的观察依据。", "points": points}
        for index, (step, points) in enumerate(zip(payload["practiceSteps"], [40, 35, 25, 0]))
    ]
    content = json.loads(resource_bundles._llm_resource_content(
        resource_type="training_task", item={"title": "核心任务与可选拓展"}, manifest=_manifest(),
        source_snapshots=[{"source_ref_id": "src-b13", "quote": "比较验证误差。"}],
        linked_resource_ids=["code-b13", "lab-b13"], llm_payload=payload,
    ))
    assert content["rubric"] == payload["rubric"]
    assert sum(item["points"] for item in content["rubric"][:-1]) == 100
    assert len(content["steps"]) == 4  # Optional work remains available.
    args = dict(item={"title": "核心任务与可选拓展"}, manifest=_manifest(),
                source_snapshots=[{"source_ref_id": "src-b13", "quote": "比较验证误差。"}],
                linked_resource_ids=["code-b13", "lab-b13"])
    legacy = json.loads(resource_bundles._llm_resource_content(
        resource_type="training_task", llm_payload={k: v for k, v in payload.items() if k != "rubric"}, **args))
    assert legacy["rubric"][-1]["points"] == 25
    assert resource_bundles._saved_training_rubric_payload(
        {"content": json.dumps(legacy)}, {"saved": payload}, **args) == payload
    assert resource_bundles._saved_training_rubric_payload(
        {"content": json.dumps(content)}, {"saved": payload}, **args) is None
    legacy["steps"][0]["instruction"] = "本次原稿已有其他变更，不得覆盖。"
    assert resource_bundles._saved_training_rubric_payload(
        {"content": json.dumps(legacy)}, {"saved": payload}, **args) is None


def test_training_does_not_replace_invalid_model_rubric_with_equal_points():
    payload = _payload()
    payload.update(environment=["纸笔"], data=["给定验证误差表"], rubric=[
        {"id": "rubric-1", "criterion": "比较依据", "evidence": "说明选择依据。", "points": 80}
    ])
    with pytest.raises(resource_bundles.ResourceBundleError, match="100"):
        resource_bundles._llm_resource_content(
            resource_type="training_task", item={"title": "实训"}, manifest=_manifest(),
            source_snapshots=[{"source_ref_id": "src-b13", "quote": "比较验证误差。"}],
            linked_resource_ids=[], llm_payload=payload,
        )


def test_handout_missing_duration_is_completed_instead_of_showing_fixed_24_minutes():
    import asyncio
    payload = _payload()
    payload.pop('estimatedMinutes')
    payload['quizQuestions'] = [
        {**payload['quizQuestions'][0], 'prompt': f'训练与验证检查 {index + 1}'}
        for index in range(3)
    ]
    calls = []
    class Backend:
        async def generate(self, system, user, **kwargs):
            calls.append((system, user))
            return json.dumps(payload if len(calls) == 1 else {'estimatedMinutes': 47, 'narrative': '不得采用这段重写'}, ensure_ascii=False)
    sources = [{'source_ref_id': 'src-b13', 'quote': '训练与验证需分开。'}]
    generated = asyncio.run(resource_bundles._real_model_payload_async(Backend(), resource_type='handout',
        item={'title': '完整讲义'}, manifest=_manifest(), source_snapshots=sources))
    content = json.loads(resource_bundles._llm_resource_content(resource_type='handout',
        item={'title': '完整讲义'}, manifest=_manifest(), source_snapshots=sources,
        linked_resource_ids=[], llm_payload=generated))
    assert len(calls) == 2
    assert 'estimatedMinutes' in calls[1][1]
    assert json.loads(calls[1][1])['completed_content'] == payload
    assert json.loads(calls[1][1])['return_fields'] == ['estimatedMinutes']
    assert content['estimatedMinutes'] == 47
    assert generated == {**payload, 'estimatedMinutes': 47}


@pytest.mark.parametrize('resource_type', ['handout', 'training_task'])
def test_duration_failure_resumes_estimation_without_regenerating_body(resource_type):
    import asyncio

    payload = _payload()
    payload.pop('estimatedMinutes')
    payload.update(environment=['浏览器'], data=['给定数据表'])
    payload['quizQuestions'] = [
        {**payload['quizQuestions'][0], 'prompt': f'检查 {index + 1}'} for index in range(3)
    ]
    calls = []
    saved = {}

    class Backend:
        async def generate(self, system, user, **kwargs):
            packet = json.loads(user)
            calls.append(packet)
            if 'completed_content' not in packet:
                return json.dumps(payload)
            assert packet['completed_content'] == payload
            if len(calls) == 2:
                raise RuntimeError('temporary connection failure')
            return '{"estimatedMinutes":47}'

    token = resource_bundles._RESOURCE_PARTS.set((saved, saved.__setitem__))
    try:
        def run():
            return asyncio.run(resource_bundles._real_model_payload_async(Backend(),
                resource_type=resource_type, item={'title': '已完成正文'},
                manifest=_manifest(), source_snapshots=[]))
        with pytest.raises(resource_bundles.ResourceBundleError, match='正文已保留'):
            run()
        assert run() == {**payload, 'estimatedMinutes': 47}
        assert len(calls) == 3
        assert sum('completed_content' not in packet for packet in calls) == 1
    finally:
        resource_bundles._RESOURCE_PARTS.reset(token)


def test_long_handout_keeps_later_sections_questions_and_full_outline():
    from app.m5_resources import parse_handout_content

    payload = _payload()
    payload["handoutSections"] = [
        {"id": f"section-{i}", "title": f"教学段落 {i}", "kind": "concept",
         "content": ("完整讲解。" * 2500 if i == 44 else f"第 {i} 段的完整学习内容。")}
        for i in range(45)
    ]
    payload["quizQuestions"] = [
        {**payload["quizQuestions"][0], "prompt": f"第 {i + 1} 道学习检查"}
        for i in range(25)
    ]
    content = resource_bundles._llm_resource_content(
        resource_type="handout", item={"title": "长单元讲义"}, manifest=_manifest(),
        source_snapshots=[{"source_ref_id": "src-b13", "title": "课程来源", "quote": "训练边界"}],
        linked_resource_ids=[], llm_payload=payload,
    )
    parsed = parse_handout_content(content)
    assert len(parsed.concepts) == 46
    assert parsed.concepts[-1].explanation == payload["handoutSections"][-1]["content"]
    assert len(parsed.miniQuiz) == 25
    assert parsed.miniQuiz[-1].question == "第 25 道学习检查"
    outline_ids = {item.id for item in parsed.outline}
    assert all(item.id in outline_ids for item in parsed.concepts + parsed.miniQuiz)
