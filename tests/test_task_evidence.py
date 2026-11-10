"""Synthetic evidence assembly checks; no remote model quality claims."""
from app.task_evidence import assemble_task_evidence, task_requirements
from models import Evidence, EvidenceModality
import pytest


@pytest.fixture(autouse=True)
def synthetic_supplemental_ranking(monkeypatch):
    # These unit cases specify their candidate order. Real lexical/semantic
    # ranking is exercised separately by the fixed retrieval datasets.
    def rank(candidates, **kwargs):
        order = [item.id for item in candidates]
        return order, ranks(order), {'method': 'synthetic-only'}
    monkeypatch.setattr('app.task_evidence.rank_chunks', rank)


def passage(key, body, title=''):
    return Evidence(id=key, title=title, content=body, source='test.md', modality=EvidenceModality.TEXT,
                    metadata={'title_path': [title] if title else [], 'char_start': 0, 'char_end': len(body)})


def ranks(order):
    return {key: {'lexical_rank': i+1, 'lexical_score': 3, 'semantic_rank': None,
                  'semantic_score': None, 'fused_score': None} for i, key in enumerate(order)}


def test_same_topic_cannot_displace_the_other_side_of_a_comparison():
    items=[passage('a1','协变量偏移是指输入分布变化。'),passage('a2','协变量偏移还有其他条件。'),
           passage('a3','协变量偏移的例子。'),passage('b','标签偏移是指标签分布变化。')]
    order=[c.id for c in items]
    selected, diagnostics, assembly=assemble_task_evidence(items,order,ranks(order),query='比较协变量偏移与标签偏移',
        embeddings=None,concept_titles=['偏移','协变量偏移','标签偏移'],top_k=2)
    assert selected==['a1','b']
    assert diagnostics['b']['lexical_rank']==4
    assert not assembly['missing_hints'] and not assembly['supplemental_queries']
    assert assembly['requirements']['topics']==['协变量偏移','标签偏移']


def test_formula_and_assumptions_keep_original_spans_and_not_only_introduction():
    items=[passage('intro','正则化控制模型复杂度。'),passage('repeat','正则化能缓解过拟合。'),
           passage('eq','$$L(w)+\\lambda \\|w\\|^2$$\n其中系数非负，为零时恢复原目标。')]
    order=[c.id for c in items]
    selected, _, assembly=assemble_task_evidence(items,order,ranks(order),query='解释正则化公式与变量',embeddings=None,top_k=2)
    assert selected==['intro','eq'] and not assembly['missing_hints']
    assert items[2].content.endswith('为零时恢复原目标。')


def test_one_supplemental_round_uses_only_supplied_scope_and_reports_missing(monkeypatch):
    import app.task_evidence as module
    items=[passage('selected','这是本章的直观介绍。')]
    calls=[]
    def rank(candidates,**kwargs):
        calls.append(kwargs['query']);assert candidates==items
        return ['selected'],ranks(['selected']),{'method':'synthetic-only'}
    monkeypatch.setattr(module,'rank_chunks',rank)
    selected, detail, assembly=assemble_task_evidence(items,['selected'],ranks(['selected']),query='推导目标公式',embeddings=None)
    assert selected==['selected'] and len(calls)==1
    assert {n['role'] for n in assembly['missing_hints']}=={'formula','condition'}
    assert detail['selected']['lexical_rank']==1


def test_supplemental_ranking_is_not_misreported_as_original_rank(monkeypatch):
    import app.task_evidence as module
    items=[passage('a','协变量偏移是指输入分布变化。'),passage('b','标签偏移是指标签分布变化。')]
    monkeypatch.setattr(module,'rank_chunks',lambda *args,**kwargs:(['b'],ranks(['b']),{'method':'synthetic-only'}))
    selected, detail, assembly=assemble_task_evidence(items,['a'],ranks(['a']),query='分别解释协变量偏移和标签偏移',
        embeddings=None,concept_titles=['协变量偏移','标签偏移'],top_k=2)
    assert selected==['a','b'] and not assembly['missing_hints']
    assert detail['b']['lexical_rank'] is None
    assert detail['b']['supplemental_rankings'][0]['lexical_rank']==1


def test_budget_does_not_cut_a_formula_or_count_duplicate_sources_twice():
    text='$$x^2+y^2=z^2$$\n其中各变量为直角三角形边长。'
    items=[passage('a',text),passage('copy',text),passage('b','其他的公式解释。'*30)]
    selected,_,assembly=assemble_task_evidence(items,['a','copy','b'],ranks(['a','copy','b']),
        query='解释公式和变量',embeddings=None,token_budget=10)
    assert selected==['a'] and items[0].content==text
    assert assembly['whole_passage_exceeds_budget']


def test_general_question_keeps_the_existing_order_and_does_not_guess_topics():
    selected,_,assembly=assemble_task_evidence([passage('a','正文')],['a'],ranks(['a']),query='继续讲讲',embeddings=None)
    assert selected==['a'] and assembly['applied'] is False
    assert task_requirements('比较两种情况', ['概率'])['topics']==[]
    assert 'formula' not in task_requirements('协变量偏移的含义是什么')['roles']


@pytest.mark.parametrize('heading', ['5.2 谱聚类（Spectral clustering）',
                                     '5.2 谱聚类 (Spectral clustering)',
                                     '[**5.2 谱聚类 (Spectral clustering)**]'])
def test_bilingual_numbered_headings_keep_each_compared_method(heading):
    items = [passage('overview', '两种方法用于不同的结构。', '概览'),
             passage('spectral', '谱聚类公式为 $L=D-W$，其中W为邻接矩阵。', heading),
             passage('density', '密度聚类通过邻域密度识别簇。', '6.1 密度聚类（DBSCAN）')]
    selected, _, assembly = assemble_task_evidence(items, ['overview', 'spectral'],
        ranks(['overview', 'spectral']), query='谱聚类和密度聚类分别怎样划分样本？',
        embeddings=None, top_k=3)
    assert set(selected) == {'overview', 'spectral', 'density'}
    assert assembly['requirements']['topics'] == ['谱聚类', '密度聚类']
    assert not assembly['missing_hints']


def test_compared_loss_objectives_retain_formulas_and_conditions():
    items = [passage('summary', '甲方法和乙方法都限制模型复杂度。'),
             passage('a', '甲方法的目标为 $L+q$，其中q非负。', '甲方法'),
             passage('b', '乙方法的目标为 $L+r$，其中r非负。', '乙方法')]
    selected, _, assembly = assemble_task_evidence(items, ['summary'], ranks(['summary']),
        query='甲方法和乙方法分别在损失目标上如何限制复杂度？', embeddings=None, top_k=3)
    assert set(selected) == {'summary', 'a', 'b'}
    assert assembly['requirements']['roles'] == ['formula', 'condition']


def test_explicit_comparison_subjects_are_not_expanded_to_every_parameter_topic():
    query = '甲方法和乙方法分别怎样控制误差？请写出公式并计算概率和缩放结果。'
    requirements = task_requirements(query, ['甲方法', '乙方法', '概率', '缩放'])
    assert requirements['topics'] == ['甲方法', '乙方法']
    assert requirements['roles'] == ['formula', 'condition']


def test_separate_followup_topic_is_retained_beside_comparison():
    requirements = task_requirements('甲方法和乙方法分别怎样工作？另外解释概率的定义。',
                                     ['甲方法', '乙方法', '概率'])
    assert requirements['topics'] == ['甲方法', '乙方法', '概率']


def test_chart_observation_keeps_actual_data_beside_named_theory():
    items = [passage('rule', '性能退化是指后续表现下降。当比较条件一致时，可对照误差变化。', '性能退化'),
             passage('example', '性能退化例如环境变化引起误差。', '性能退化'),
             passage('chart', '柱状图：验证误差\n| 轮次 | 误差 |\n|---|---|\n| 4 | 0.12 |\n| 5 | 0.28 |')]
    selected, _, assembly = assemble_task_evidence(items, ['rule', 'example'], ranks(['rule', 'example']),
        query='观察柱状图第4至5轮，结合性能退化的定义解释变化。', embeddings=None,
        concept_titles=['性能退化'], top_k=3)
    assert 'chart' in selected
    assert not assembly['missing_hints']
    assert items[2].content.endswith('| 5 | 0.28 |')


def test_chart_mention_without_numeric_observations_remains_missing():
    items = [passage('intro', '柱状图例如能显示指标对比，但本段没有实际数值。')]
    _, _, assembly = assemble_task_evidence(items, ['intro'], ranks(['intro']),
        query='根据柱状图分析指标变化。', embeddings=None)
    assert {'topic': '', 'role': 'chart_data'} in assembly['missing_hints']


def test_method_subsection_formula_is_not_displaced_by_introductory_algebra():
    from dataclasses import replace
    items = [passage('overview', '本节研究甲方法。'),
             replace(passage('method', '甲方法的变换为 $y=x/m$，其中m为尺度。'),
                     metadata={'title_path': ['甲方法', '计算规则']}),
             passage('intro', '背景例子为 $z=x+y$，其中x和y是计数。', '甲方法')]
    selected, _, _ = assemble_task_evidence(items, ['overview', 'method', 'intro'],
        ranks(['overview', 'method', 'intro']), query='甲方法的公式是什么？', embeddings=None, top_k=2)
    assert selected == ['overview', 'method']


def test_equivalent_course_names_retrieve_both_methods_without_rewriting_sources():
    items=[passage('z', '标准化公式为 $z=(x-m)/s$，其中s为标准差。', '标准化'),
           passage('minmax', '最小最大值规范化公式为 $z=(x-a)/(b-a)$，其中a和b是最小最大值。', '数据预处理'),
           passage('other', '缩放图像后输出像素。', '图像处理')]
    original=[item.content for item in items]
    selected,_,assembly=assemble_task_evidence(items,['z'],ranks(['z']),
        query='比较最小最大归一化与Z值规范化的公式',embeddings=None,top_k=2)
    assert set(selected)=={'minmax','z'}
    assert assembly['requirements']['topics']==['最小最大归一化','Z值规范化']
    assert not assembly['missing_hints']
    assert [item.content for item in items]==original


def test_related_glossary_terms_are_not_equivalent_course_names():
    items=[passage('z','标准化公式为 $z=(x-m)/s$，其中s为标准差。','标准化'),
           passage('shape','数组形状表示各轴长度。','数组')]
    _,_,assembly=assemble_task_evidence(items,['z','shape'],ranks(['z','shape']),
        query='最小最大归一化的公式是什么？',embeddings=None)
    assert '最小最大归一化' not in assembly['requirements']['topics']
    assert 'standardization' not in assembly.get('topic_aliases',{}).get('最小最大归一化',[])


def test_softmax_name_in_pdf_body_remains_a_topic_beside_generic_probability():
    items = [passage('base', 'Softmax定义为 $p_i=exp(z_i)/sum(exp(z))$，其中各分数为实数。', '分类模型'),
             passage('temperature', '带温度的softmax公式为 $p_i=exp(z_i/T)/sum(exp(z/T))$，其中T为温度。', '语言模型'),
             passage('probability', '概率的定义可由投骰子的事件说明。', '概率')]
    selected, _, assembly = assemble_task_evidence(items, ['base', 'probability'],
        ranks(['base', 'probability']), query='解释Softmax怎样变成概率，给出温度T=2时的公式。',
        embeddings=None, top_k=3)
    assert 'Softmax' in assembly['requirements']['topics']
    assert 'temperature' in selected


def test_plain_pdf_body_is_not_excluded_by_another_documents_named_sections():
    from dataclasses import replace
    base = passage('base', 'Softmax公式为 $p_i=exp(z_i)/sum(exp(z))$。', 'Softmax')
    pdf = replace(passage('pdf', '带温度的softmax公式为 $p_i=exp(z_i/T)/sum(exp(z/T))$，其中T为正温度。'),
                  source='book.pdf', metadata={'title_path': ['完整电子书', '教材正文'],
                                               'document_context': '完整电子书\n课程目标'})
    selected, _, assembly = assemble_task_evidence([base,pdf], ['base'], ranks(['base']),
        query='Softmax的温度公式是什么？', embeddings=None, top_k=2)
    assert selected == ['base', 'pdf']
    assert not assembly['missing_hints']


def test_parameter_question_keeps_temperature_with_the_named_method():
    items = [passage('base', 'Softmax定义为概率归一化，公式为 $p_i=exp(z_i)/sum(exp(z))$，其中z为实数。'),
             passage('physics', '玻尔兹曼概率公式为 $p=exp(-E/T)/Z$，其中T为温度。'),
             passage('temperature', '带温度的Softmax为 $p_i=exp(z_i/T)/sum(exp(z/T))$，其中T为正温度。')]
    selected, _, assembly = assemble_task_evidence(items, ['base', 'physics'],
        ranks(['base', 'physics']), query='解释Softmax怎样变成概率，分别计算温度T=1和T=2时的公式。',
        embeddings=None, concept_titles=['概率'], top_k=2)
    assert assembly['requirements']['topics'] == ['Softmax', '概率', '温度']
    assert selected == ['base', 'temperature']


@pytest.mark.parametrize('negative_instruction', ['不用代码', '不需要提供代码', '不要编写Python', '不用Python代码', '无需编程'])
def test_explicit_no_code_task_does_not_prioritize_implementation(negative_instruction):
    result=task_requirements('解释标准化公式，'+negative_instruction, ['标准化'])
    assert result['roles']==['formula','condition']
    assert 'procedure' in task_requirements('不用代码解释原理，再用Python演示另一例。')['roles']


def test_generic_comparison_and_prediction_headings_do_not_become_the_task_topics():
    items = [passage('loss', '均方误差按样本数平均。$$L=\\sum e_i^2/n$$', '损失函数'),
             passage('compare', '比较两个机器翻译模型的输出。', '比较'),
             passage('predict', '调用目标检测网络输出预测。', '预测')]
    order = [c.id for c in items]
    selected, _, assembly = assemble_task_evidence(items, order, ranks(order),
        query='用Python比较同一组预测的普通均方误差和加权均方误差，说明分母为什么不同。',
        embeddings=None, top_k=2)
    assert assembly['requirements']['topics'] == ['均方误差']
    assert 'formula' in assembly['requirements']['roles']
    assert 'loss' in selected
    # Confirmed course concepts are still meaningful, even with a short name.
    assert task_requirements('说明预测的公式', ['预测'])['topics'] == ['预测']


def test_example_data_does_not_add_an_unrelated_data_section_to_method_comparison():
    items = [passage('data', '数据表示多个设备上需要并行计算的样本。', '数据'),
             passage('minmax', '最小最大值规范化定义为 $y=(x-a)/(b-a)$，其中a和b为训练极值。', '数据预处理'),
             passage('z', '标准化定义为 $z=(x-m)/s$，其中m和s是均值与标准差。', '标准化')]
    selected, _, assembly = assemble_task_evidence(items, ['minmax', 'data', 'z'],
        ranks(['minmax', 'data', 'z']),
        query='按课程定义比较最小最大值归一化与Z分数标准化，训练数据为[2,4,8]。',
        embeddings=None, top_k=2)
    assert assembly['requirements']['topics'] == ['最小最大值归一化', 'Z分数标准化']
    assert set(selected) == {'minmax', 'z'}
    # A confirmed course concept may still deliberately have this broad name.
    assert task_requirements('解释数据的定义', ['数据'])['topics'] == ['数据']


def test_shared_comparison_term_must_exist_in_allowed_body_and_does_not_hide_a_missing_side():
    assert task_requirements('比较普通均方误差和加权均方误差', ['均方误差'])['topics'] == ['均方误差']
    assert task_requirements('比较均方误差和其他损失', ['均方误差'])['topics'] == []
    items = [passage('a', '本章只有分类准确率。', '比较'), passage('b', '其他操作。', '预测')]
    _, _, assembly = assemble_task_evidence(items, ['a','b'], ranks(['a','b']),
        query='用Python比较普通均方误差和加权均方误差的分母。', embeddings=None)
    assert assembly['requirements']['topics'] == []


def test_request_for_code_keeps_actual_implementation_even_when_prose_mentions_output():
    items = [passage('overview', '均方误差用于比较预测输出，例如分类结果。'),
             passage('formula', '均方误差公式。$$L=\\sum e_i^2/n$$ 其中n为样本数。'),
             passage('code', '均方误差返回所有样本损失的平均值。\n```python\nloss = MSELoss()\n```')]
    selected, _, _ = assemble_task_evidence(items, ['overview','formula'], ranks(['overview','formula']),
        query='用Python比较普通均方误差与加权均方误差，打印结果并说明分母。', embeddings=None, top_k=3)
    assert 'code' in selected and 'formula' in selected


def test_focused_topic_search_preserves_the_original_specific_condition(monkeypatch):
    import app.task_evidence as module
    items = [passage('overview', '动量法累积过去的梯度。', '动量法'),
             passage('range', '递推为 $v=bv+g$，其中系数取值为 $0<b<1$。', '动量法'),
             passage('generic', '应用公式为 $x=x-av$。其中a为学习率。', '动量法')]
    def rank(*args, **kwargs):
        # A generic topic search retrieves applications first. The specific
        # coefficient request must survive into the supplemental search.
        order = ['range', 'generic'] if '系数的范围' in kwargs['query'] else ['generic', 'range']
        return order, ranks(order), {'method': 'synthetic-only'}
    monkeypatch.setattr(module, 'rank_chunks', rank)
    selected, _, _ = assemble_task_evidence(items, ['overview', 'range'], ranks(['overview', 'range']),
        query='动量法如何累积过去的梯度？请给出更新公式和动量系数的范围。',
        embeddings=None, top_k=2)
    assert selected == ['overview', 'range']


def test_relationship_query_retrieves_each_explicit_part_from_same_candidates(monkeypatch):
    import app.task_evidence as module
    items = [passage('main', '检索参数的选择。'), passage('repeat', '其他检索参数。'),
             passage('citation', '核对引文支持哪些结论。'), passage('evaluation', '指标须固定测试范围。')]
    lookups = {'检索参数': 'main', '引用质量': 'citation', '评价范围': 'evaluation'}
    def rank(candidates, **kwargs):
        assert candidates == items
        key = lookups[kwargs['query']]
        return [key], ranks([key]), {'method': 'synthetic-only'}
    monkeypatch.setattr(module, 'rank_chunks', rank)
    selected, diagnostics, assembly = assemble_task_evidence(items, ['main', 'repeat'], ranks(['main', 'repeat']),
        query='检索参数如何与引用质量、评价范围关联？', embeddings=None, top_k=3)
    assert selected == ['main', 'citation', 'evaluation']
    assert not assembly['missing_relationship_parts']
    assert diagnostics['citation']['lexical_rank'] is None
    assert diagnostics['citation']['supplemental_rankings'][0]['query'] == '引用质量'
    assert module._relation_facets('什么是调和平均？') == []
    assert module._relation_facets('x=y+z与误差有什么关系？') == []


def test_relationship_parts_accept_semantic_only_candidates_without_numeric_lexical_score(monkeypatch):
    import app.task_evidence as module
    items = [passage('a', '甲项说明。'), passage('b', '乙项说明。')]
    def rank(candidates, **kwargs):
        key = 'a' if kwargs['query'] == '甲项' else 'b'
        return [key], {key: {'lexical_score': None, 'semantic_score': .8}}, {'method': 'synthetic-only'}
    monkeypatch.setattr(module, 'rank_chunks', rank)
    selected, _, assembly = assemble_task_evidence(items, ['a'], ranks(['a']),
        query='甲项与乙项如何关联？', embeddings=None, top_k=2)
    assert selected == ['a', 'b'] and not assembly['missing_relationship_parts']


def test_function_comparison_keeps_every_requested_call_and_not_name_substrings():
    items = [passage('train', '调用 `prepare(data)` 训练。'),
             passage('repeat', 'prepare 有其他参数。'),
             passage('infer', '调用 `infer(data)` 预测。'),
             passage('split', '调用 `split_samples(data)` 划分数据。')]
    order = [item.id for item in items]
    selected, _, assembly = assemble_task_evidence(items, order, ranks(order),
        query='prepare、infer 和 split_samples 分别做什么？', embeddings=None, top_k=3)
    assert selected == ['train', 'infer', 'split']
    assert assembly['requirements']['topics'] == ['prepare', 'infer', 'split_samples']
    assert task_requirements('比较 benefits 和 fitting', ['fit'])['topics'] == []


def test_implementation_request_keeps_the_rule_and_working_code_not_only_an_introduction():
    items = [passage('intro', '加权平均用于累计观测。', '加权平均'),
             passage('other', '图像显示的例子。\n```python\nprint(image)\n```', '演示'),
             passage('rule', '公式为 $m=am+(1-a)x$，其中a在零到一之间。', '加权平均'),
             passage('code', '例如依次输入数据。\n```python\nfor x in values:\n    m = a*m + (1-a)*x\n```', '加权平均')]
    order=[item.id for item in items]
    selected, _, assembly = assemble_task_evidence(items, order, ranks(order),
        query='用Python演示加权平均，打印每一步的值', embeddings=None, top_k=3)
    assert selected == ['intro','rule','code']
    assert not assembly['missing_hints']
    assert 'procedure' in task_requirements('给出Python代码')['roles']


def test_single_concept_formula_cannot_be_filled_with_another_topics_formula():
    items = [passage('intro', '朴素贝叶斯用于根据观察判断类别。'),
             passage('wrong', '支持向量机的间隔目标为 $L=1/2\\|w\\|^2$，其中w为权重。'),
             passage('right', '朴素贝叶斯假设特征在给定类别后条件独立，公式为 $P(c|x)\\propto P(c)\\prod_jP(x_j|c)$。')]
    order = [item.id for item in items]
    selected, _, assembly = assemble_task_evidence(items, order, ranks(order),
        query='解释朴素贝叶斯的公式与适用条件', embeddings=None,
        concept_titles=['朴素贝叶斯', '支持向量机'], top_k=2)
    assert selected == ['intro', 'right']
    assert not assembly['missing_hints']


def test_comparison_keeps_every_explicit_concept_instead_of_only_the_first_two():
    items = [passage('accuracy', '准确率定义为全部预测中正确预测的比例。'),
             passage('accuracy-more', '准确率用于说明整体预测表现。'),
             passage('precision', '精确率定义为预测为正的样本中实际正例的比例。'),
             passage('recall', '召回率定义为实际正例中被找到的比例。')]
    order = [item.id for item in items]
    selected, _, assembly = assemble_task_evidence(items, order, ranks(order),
        query='比较准确率、精确率与召回率', embeddings=None,
        concept_titles=['准确率', '精确率', '召回率'], top_k=3)
    assert assembly['requirements']['topics'] == ['准确率', '精确率', '召回率']
    assert selected == ['accuracy', 'precision', 'recall']


def test_source_headings_supply_the_specific_topic_without_rewriting_evidence():
    items = [passage('intro', '这一机制适合序列任务。', '[**加性注意力**]'),
             passage('other', '公式为 $x+y=z$，其中x是输入。', '缩放点积注意力'),
             passage('right', '公式为 $v^T\\tanh(W_q q+W_k k)$，其中两矩阵映射查询与键。', '[**加性注意力**]')]
    original = [item.content for item in items]
    order = [item.id for item in items]
    selected, _, assembly = assemble_task_evidence(items, order, ranks(order),
        query='解释加性注意力的公式', embeddings=None, concept_titles=['注意力机制与 Transformer'], top_k=2)
    assert selected == ['intro', 'right']
    assert assembly['requirements']['topics'] == ['加性注意力']
    assert [item.content for item in items] == original
    assert task_requirements('比较随机梯度下降与梯度下降', ['梯度下降', '随机梯度下降'])['topics'] == ['随机梯度下降', '梯度下降']


def test_code_assignments_and_variable_mentions_are_not_mathematical_formula_evidence():
    from app.task_evidence import evidence_roles
    roles = evidence_roles('梯度下降的参数为$w$。\n```python\nw = w - lr * grad\n```')
    assert 'procedure' in roles and 'formula' not in roles
    assert 'formula' in evidence_roles('参数更新公式为 $w=w-\\eta g$。')


@pytest.mark.parametrize('text', [
    '现在[**定义训练函数**]。',
    '接下来定义评估函数。\n```python\ndef evaluate(values):\n    return sum(values)\n```',
    '下面定义一个字典，用于保存结果。',
])
def test_program_construction_intro_is_not_a_concept_definition(text):
    from app.task_evidence import evidence_roles
    assert 'definition' not in evidence_roles(text)


@pytest.mark.parametrize('text', [
    '精确率定义为预测为正的样本中实际正例的比例。',
    '欠拟合是指模型不能充分拟合训练数据。',
    '映射f的定义如下：每个输入对应唯一输出。',
    '函数定义是描述输入与输出之间关系的一种方式。',
])
def test_actual_concept_definition_keeps_its_evidence_role(text):
    from app.task_evidence import evidence_roles
    assert 'definition' in evidence_roles(text)


def test_concept_rule_is_not_displaced_by_high_ranked_code_introductions(monkeypatch):
    import app.task_evidence as module
    items = [passage('data', '|轮次|训练误差|验证误差|\n|2|0.25|0.30|\n|3|0.08|0.47|', '观测记录'),
             passage('code-intro', '现在定义评估函数。', '模型判断'),
             passage('rule', '泛化差距定义为验证误差与训练误差的差。差距大于零时，验证误差更高。', '模型判断')]
    order = [item.id for item in items]
    monkeypatch.setattr(module, 'rank_chunks', lambda *args, **kwargs:
                        (['code-intro', 'rule'], ranks(['code-intro', 'rule']), {'method': 'synthetic-only'}))
    selected, _, assembly = assemble_task_evidence(items, order, ranks(order),
        query='根据表格说明模型判断的规则。', embeddings=None, top_k=2)
    assert selected == ['data', 'rule']
    assert not assembly['missing_hints']


def test_overlapping_source_paragraphs_leave_room_for_new_evidence(monkeypatch):
    import app.task_evidence as module
    items = [passage('overview', '模型用于描述输入与输出。判断前应保留独立样本。', '模型判断'),
             passage('definition', '误差差距定义为验证误差与训练误差的差。', '模型判断'),
             passage('overlap', '## 另一版本的章节标题\n\n判断前应保留独立样本。\n误差差距定义为验证误差与训练误差的差。', '模型判断'),
             passage('new-rule', '阈值定义为允许的最大误差差距。', '模型判断')]
    order = [item.id for item in items]
    monkeypatch.setattr(module, 'rank_chunks', lambda *args, **kwargs:
                        (order, ranks(order), {'method': 'synthetic-only'}))
    original = [item.content for item in items]
    selected, _, _ = assemble_task_evidence(items, order, ranks(order),
        query='解释模型判断的定义。', embeddings=None, top_k=3)
    assert selected == ['overview', 'definition', 'new-rule']
    assert [item.content for item in items] == original


def test_similar_evidence_keeps_new_conditions_numbers_and_code():
    items = [passage('first', '阈值定义为2。只有相同测量单位才可以比较。'),
             passage('new-condition', '阈值定义为2。不适用于单位不同的输入。'),
             passage('new-number', '阈值定义为3。只有相同测量单位才可以比较。'),
             passage('code-a', '```python\nthreshold = 2\n```'),
             passage('code-b', '```python\nthreshold = 3\n```')]
    order = [item.id for item in items]
    selected, _, _ = assemble_task_evidence(items, order, ranks(order),
        query='说明规则与代码。', embeddings=None, top_k=5)
    assert set(selected) == set(order)


def test_identical_words_under_distinct_named_concepts_keep_their_context():
    body = '它非负，零表示预测与观测相同。'
    items = [passage('absolute', body, '绝对误差'), passage('squared', body, '平方误差')]
    order = [item.id for item in items]
    selected, _, assembly = assemble_task_evidence(items, order, ranks(order),
        query='比较绝对误差与平方误差的定义。', embeddings=None, top_k=2)
    assert selected == order
    assert not assembly['missing_hints']


def test_emphasis_between_math_variables_is_not_an_equation():
    from app.task_evidence import evidence_roles
    assert 'formula' not in evidence_roles('输入$x$采用*拉伸参数*$g$和*偏移参数*$b$。')
    assert 'formula' in evidence_roles('更新为 $x \\leftarrow x-\\eta g$。')


def test_formula_reference_retrieves_its_exact_source_equation_without_crossing_documents():
    from dataclasses import replace
    items = [passage('explanation', '变换的比例见 :eqref:`eq_transform`，统计量为 $$m=\\frac{1}{n}\\sum_i x_i$$。其中n为样本数。', '标准化'),
             passage('equation', '变换为 $$z=(x-m)/s$$。\n:eqlabel:`eq_transform`', '标准化'),
             replace(passage('other-document', '$$z=x+m$$\n:eqlabel:`eq_transform`', '标准化'), source='other.md')]
    selected, detail, assembly = assemble_task_evidence(items, ['explanation'], ranks(['explanation']),
        query='标准化的公式是什么？', embeddings=None, top_k=2)
    assert selected == ['explanation', 'equation']
    assert detail['equation']['lexical_rank'] is None
    assert detail['equation']['equation_referenced_by'] == ['explanation']
    assert not assembly['unresolved_equation_references']
    selected, detail, assembly = assemble_task_evidence([items[0], items[2]], ['explanation'], ranks(['explanation']),
        query='标准化的公式是什么？', embeddings=None, top_k=2)
    # A second allowed source can still be retrieved independently for the
    # same topic; its coincident label must not resolve this document's link.
    assert selected == ['explanation', 'other-document']
    assert 'equation_referenced_by' not in detail['other-document']
    assert assembly['unresolved_equation_references'] == ['eq_transform']


def test_equation_dependencies_keep_the_token_budget_and_report_omitted_reference():
    items = [passage('brief', '公式为 $z=x+y$。其中细节见 :eqref:`long_equation`。'),
             passage('long', '$$x=1+2$$\n:eqlabel:`long_equation`\n' + '说明较长。'*100)]
    selected, _, assembly = assemble_task_evidence(items, ['brief'], ranks(['brief']),
        query='解释公式', embeddings=None, token_budget=100)
    assert selected == ['brief']
    assert assembly['unresolved_equation_references'] == ['long_equation']


def test_nested_names_and_other_method_mentions_do_not_fill_all_comparison_requirements(monkeypatch):
    import app.task_evidence as module
    items = [passage('summary', '随机梯度下降与梯度下降可以比较。', '随机梯度下降'),
             passage('sgd', '与梯度下降相比，更新为 $w=w-\\eta g_i$。其中g_i来自均匀抽取的单个样本。', '随机梯度下降'),
             passage('gd', '更新为 $w=w-\\eta g$。其中g为完整训练集的梯度。', '梯度下降')]
    calls = []
    def rank(candidates, **kwargs):
        calls.append([item.id for item in candidates])
        keys = [item.id for item in candidates]
        assert keys in [['summary','sgd'],['gd']]
        return keys, ranks(keys), {'method':'synthetic-only'}
    monkeypatch.setattr(module, 'rank_chunks', rank)
    selected, _, assembly = assemble_task_evidence(items, ['summary','sgd'], ranks(['summary','sgd']),
        query='比较随机梯度下降与梯度下降的公式', embeddings=None, top_k=3)
    assert 'gd' in selected and ['gd'] in calls
    assert assembly['requirements']['topics'] == ['随机梯度下降', '梯度下降']


def test_incidental_comparison_in_another_section_cannot_replace_both_own_formulas(monkeypatch):
    import app.task_evidence as module
    items = [passage('other', '甲方法与乙方法不同；本节的公式为 $z=x+y$，其中x是输入。', '丙方法'),
             passage('a', '更新为 $a=a-2g$，其中g为甲方法的方向。', '甲方法'),
             passage('b', '更新为 $b=b+g$，其中g为乙方法的方向。', '乙方法')]
    calls=[]
    def rank(candidates, **kwargs):
        keys=[item.id for item in candidates]; calls.append(keys)
        return keys,ranks(keys),{'method':'synthetic-only'}
    monkeypatch.setattr(module, 'rank_chunks', rank)
    selected, _, assembly = assemble_task_evidence(items, ['other'], ranks(['other']),
        query='比较甲方法和乙方法的公式', embeddings=None, top_k=3)
    assert selected == ['other','a','b']
    assert calls == [['a'],['b']] and not assembly['missing_hints']


def test_method_definition_precedes_nested_variant_and_keeps_comparison_balanced(monkeypatch):
    from dataclasses import replace
    import app.task_evidence as module
    items = [passage('intro', '比较两个方法。'),
             replace(passage('variant', '变体公式为 $x=x-2g$。其中g为梯度。'), metadata={'title_path': ['甲方法', '扩展', '预处理']}),
             passage('a', '甲方法定义为 $x=x-g$。其中g为梯度。', '甲方法'),
             passage('a-update', '甲方法的更新公式为 $y=x-g$。', '甲方法'),
             passage('b', '乙方法定义为 $u=u+h$。其中h为方向。', '乙方法'),
             passage('b-update', '乙方法的更新公式为 $v=u+h$。', '乙方法')]
    def rank(candidates, **kwargs):
        keys = [item.id for item in candidates]
        return keys, ranks(keys), {'method': 'synthetic-only'}
    monkeypatch.setattr(module, 'rank_chunks', rank)
    order = [item.id for item in items]
    selected, _, _ = assemble_task_evidence(items, order, ranks(order),
        query='比较甲方法与乙方法的公式', embeddings=None, top_k=5)
    assert selected == ['intro', 'a', 'b', 'a-update', 'b-update']


def test_repeated_method_name_in_subheading_does_not_hide_its_actual_depth():
    from dataclasses import replace
    items = [passage('overview', '先说明本方法。'),
             replace(passage('application', '应用公式为 $h=F(z)$。其中z为输入。'),
                     metadata={'title_path': ['甲方法', '甲方法层', '输出层']}),
             replace(passage('definition', '变换公式为 $z=(x-m)/s$。其中s为尺度。'),
                     metadata={'title_path': ['甲方法', '基本原理']})]
    selected, _, _ = assemble_task_evidence(items, ['overview', 'application', 'definition'],
        ranks(['overview', 'application', 'definition']), query='甲方法的公式是什么？', embeddings=None, top_k=2)
    assert selected == ['overview', 'definition']
