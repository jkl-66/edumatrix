from copy import deepcopy
from types import SimpleNamespace

from app.diagnostic_report import _learner_report_data
from app.learner_output import teacher_text
from app.learner_output import resource_failure_feedback
from app.path_draft import _node_projection


def test_resource_review_feedback_preserves_details_without_raw_fields():
    import json
    details = [{"resourceType": "code_sandbox", "severity": "blocking", "issue": "未展示分类结果。",
                "requiredFix": "请补充叶节点的预测。", "evidence": "internal trace"}]
    raw = "内容还需要调整。\n具体审核意见：" + json.dumps(details, ensure_ascii=False)
    assert resource_failure_feedback(raw) == "内容还需要调整。\n未展示分类结果。\n请补充叶节点的预测。"
    assert resource_failure_feedback(raw[:50]) == "内容还需要调整。"
    code = '```python\nprint({"severity": "blocking"})\n```'
    assert resource_failure_feedback(code) == code


def test_historical_report_projection_keeps_saved_evidence_and_scores():
    stored = {
        'evidence': [{
            'questionVersionId': 'qv-12345678', 'attemptId': 'attempt-12345678',
            'knowledgePoint': {'id': 'kp-list-index', 'title': '列表索引'},
            'sources': [{'id': 'ref-python-guide', 'title': 'Python入门讲义'}],
            'answer': {'code': 'correct = False'}, 'correct': False, 'score': 0,
            'gradingStatus': 'graded', 'judgmentBasis': 'correct=false，grading_status=graded。',
            'explanation': '请复习 kp-list-index，再阅读 ref-python-guide。',
            'evaluation': {'status': 'partially_supported', 'claim': 'correct=false，需要继续练习。'},
        }],
    }
    before = deepcopy(stored)
    visible = _learner_report_data(stored)
    item = visible['evidence'][0]
    assert item['judgmentBasis'] == '本题尚未答对，已完成评分。'
    assert '列表索引' in item['explanation'] and 'Python入门讲义' in item['explanation']
    assert 'kp-list-index' not in item['explanation']
    assert item['correct'] is False and item['score'] == 0
    assert item['gradingStatus'] == 'graded'
    assert item['questionVersionId'] == 'qv-12345678'
    assert item['answer'] == before['evidence'][0]['answer']
    assert stored == before


def test_diagnostic_explanation_preserves_teaching_prose_numbers_and_code():
    explanation = (
        '证据不足不能说明原假设为假。课程来源与画像快照是本题比较的对象。\n\n'
        '计算值为 123456789012345678901234。\n\n'
        '```python\ntrace_id = "trace-example"\nif True:\n    print(trace_id)\n```\n\n'
        '再查看 ref-python-guide。trace_id=trace-internal-12345678'
    )
    stored = {'evidence': [{'explanation': explanation, 'score': 0.82,
        'sources': [{'id': 'ref-python-guide', 'title': 'Python入门讲义'}]}]}
    before = deepcopy(stored)
    visible = _learner_report_data(stored)['evidence'][0]
    assert visible['explanation'] == explanation.replace('ref-python-guide', 'Python入门讲义').replace('trace_id=trace-internal-12345678', '')
    assert visible['score'] == 0.82 and stored == before


def test_review_locations_use_readable_names_without_rewriting_teaching_code():
    import json
    details = [{"issue": "content.concepts[0].explanation 中第一个实际输出应为5、4。",
                "fix": "请同步修改 content.quiz[1].explanation，保留正确答案。"}]
    original = deepcopy(details)
    raw = "内容还需要调整。具体审核意见：" + json.dumps(details, ensure_ascii=False)
    visible = resource_failure_feedback(raw)
    assert "第1项概念的讲解" in visible
    assert "第2项小测的讲解" in visible
    assert "content." not in visible
    assert "实际输出应为5、4" in visible
    assert details == original
    assert resource_failure_feedback('content.concepts[0].explanation中的输出有误。') == '第1项概念的讲解中的输出有误。'
    code = '```python\nprint(content.concepts[0].explanation)\n```'
    assert resource_failure_feedback(code) == code
    assert resource_failure_feedback('运行 `content.concepts[0].explanation`。') == '运行 `content.concepts[0].explanation`。'


def test_path_reason_uses_names_and_preserves_prerequisite_ids():
    chapter = SimpleNamespace(id='ch-python-list', title='列表与索引', position=1, source_document_id='src-python', course_id='course-python')
    knowledge = SimpleNamespace(id='kp-list-index', title='列表索引')
    facts = {'chapters': [chapter], 'sources': {}, 'ref_by_chapter': {}, 'kp_by_chapter': {chapter.id: [knowledge]}}
    node = {'target_object_id': chapter.id, 'rationale': '建议复习 kp-list-index。', 'prerequisites': ['ch-python-basics']}
    result = _node_projection(facts, node=node, reasons={}, weak_ids={knowledge.id})
    assert '列表索引' in result['reason']
    assert '先完成' in result['reason']
    assert 'ch-python-basics' not in result['reason']
    assert result['prerequisites'] == ['ch-python-basics']
    assert result['knowledge_points'][0]['id'] == knowledge.id


def test_feedback_does_not_turn_ungraded_or_wrong_answers_into_success():
    assert teacher_text('correct=null，status=pending。') == '本题尚未完成评分，等待处理。'
    assert teacher_text('correct=false，graded。') == '本题尚未答对，已完成评分。'


def test_natural_teaching_terms_are_not_replaced_as_internal_jargon():
    text = '依据验证结果选择树深度，说明数据来源与判断证据。比较确定性算法和随机算法，在约束条件下优化，并冻结预训练层。'
    assert teacher_text(text) == text


def test_teaching_code_keeps_fences_indentation_and_literal_values():
    code = '```python\ndef answer():\n    status = "pending"\n    correct = False\n    return {"source_ref_id": "ref-example", "correct": correct}\n```'
    text = f'correct=false。\n\n{code}\n\n再运行 `answer()` 核对结果。'
    cleaned = teacher_text(text)
    assert code in cleaned
    assert '`answer()`' in cleaned
    assert cleaned.startswith('本题尚未答对。')
    from app.resource_bundles import _handout_text
    nested = '```python\nclean_values = []\nfor value in values:\n    if value is not None:\n        clean_values.append(value)\nprint(clean_values)\n```'
    assert nested in _handout_text('JSON格式。\n' + nested)
    assert teacher_text('clean_values = []') == 'clean_values = []'


def test_version_comparison_describes_changes_without_exposing_serialized_content():
    import json
    from app.m5_resources import resource_change_summary
    before = {'title': '列表练习', 'starterCode': 'print(1)', 'trace_id': 'trace-internal'}
    after = {**before, 'starterCode': 'print(2)', 'trace_id': 'trace-new'}
    summary = resource_change_summary(json.dumps(before), json.dumps(after))
    assert '练习代码有调整。' in summary
    assert all('trace' not in item and 'print(' not in item for item in summary)
    assert resource_change_summary('相同正文', '相同正文') == []
    assert '正文内容有调整' in resource_change_summary('旧讲解', '新讲解')[0]
    assert before['starterCode'] == 'print(1)'
def test_named_steps_in_chinese_prose_keep_code_and_longer_identifiers():
    from app.learner_output import teacher_text, teaching_text
    original = '沿part-1的结果继续；part-10不替换，`part-1`保留。'
    expected = '沿第一步的结果继续；part-10不替换，`part-1`保留。'
    for project in (teacher_text, teaching_text):
        assert project(original, names={'part-1': '第一步'}) == expected

