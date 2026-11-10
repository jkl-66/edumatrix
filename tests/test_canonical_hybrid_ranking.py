"""Isolated synthetic ranking fixtures, not a real semantic quality evaluation."""
from dataclasses import dataclass

from app.retrieval_ranking import BM25Index, rank_chunks
from embedding_models import CachingEmbeddingBackend, HashEmbeddingBackend
from models import Evidence, EvidenceModality


def chunk(key, content):
    return Evidence(id=key, title=key, source='synthetic.md', content=content, modality=EvidenceModality.TEXT)


@dataclass
class SyntheticSemanticBackend:
    semantic_capable = True
    failed: bool = False

    def identity(self):
        return {'name': 'synthetic-test-only', 'model': str(self.failed), 'dim': 2}

    def embed_many(self, documents):
        if self.failed:
            raise RuntimeError('synthetic unavailable model')
        return [(0.0, 1.0), (1.0, 0.0)]

    def embed(self, query):
        return (1.0, 0.0)


def test_bm25_uses_body_frequency_and_penalizes_unrelated_length():
    index = BM25Index(['验证误差持续升高提示过拟合。', '验证误差。' + '天气温度。' * 100, '今天阳光充足。'])
    scores = index.scores('验证误差')
    assert scores[0] > scores[1] > scores[2] == 0


def test_bm25_finds_attribute_names_inside_qualified_code_names():
    index = BM25Index(['使用 model.feature_count_ 查看特征数量。', '查看数量。'])
    scores = index.scores('feature_count_')
    assert scores[0] > 0 and scores[1] == 0


def test_relation_question_keeps_complementary_passage_without_changing_lookup():
    from app.retrieval_ranking import _diversify_related_topics
    chunks = [chunk('a', '梯度下降学习率与参数更新。'),
              chunk('duplicate', '梯度下降学习率与参数更新。'),
              chunk('condition', '梯度下降受曲率和收敛条件约束。')]
    order = ['a', 'duplicate', 'condition']
    diagnostics = {key: {'lexical_score': score} for key, score in zip(order, [10, 9, 6])}
    selected, applied = _diversify_related_topics(order, diagnostics, chunks, '学习率与收敛条件如何关联？')
    assert applied and selected[:2] == ['a', 'condition']
    assert diagnostics['duplicate']['lexical_score'] == 9
    assert _diversify_related_topics(order, diagnostics, chunks, '梯度下降学习率') == (order, False)


def test_independent_semantic_and_lexical_ranks_are_not_copied():
    chunks = [chunk('lexical', '欠拟合的词语解释。'), chunk('semantic', '学习能力不足，连已有样本也预测不准。')]
    order, diagnostics, execution = rank_chunks(chunks, query='欠拟合', expanded_query='欠拟合', embeddings=SyntheticSemanticBackend())
    assert set(order) == {'lexical', 'semantic'}
    assert diagnostics['lexical']['lexical_rank'] == 1
    assert diagnostics['lexical']['semantic_rank'] == 2
    assert diagnostics['semantic']['semantic_rank'] == 1
    assert diagnostics['semantic']['lexical_rank'] is None
    assert execution['method'] == 'reciprocal-rank-fusion'


def test_hash_and_failed_model_do_not_claim_semantic_fusion(tmp_path):
    chunks = [chunk('a', '验证误差升高。'), chunk('b', '气温升高。')]
    for backend in [CachingEmbeddingBackend(HashEmbeddingBackend(), cache_path=str(tmp_path/'hash.db')),
                    SyntheticSemanticBackend(failed=True)]:
        order, diagnostics, execution = rank_chunks(chunks, query='验证误差', expanded_query='验证误差', embeddings=backend)
        assert order[0] == 'a'
        assert execution['method'] == 'bm25'
        assert not execution['semantic_executed']
        assert diagnostics['a']['semantic_rank'] is None
        assert diagnostics['a']['fused_score'] is None
    assert execution['semantic_error'] == 'RuntimeError'


def test_code_chunks_preserve_indentation_and_original_offsets():
    from document_parser import chunk_document
    body = '\n\n' + ('def example():\n    print("教学代码")\n\n' * 80)
    chunks = chunk_document(body, 'synthetic.py')
    assert len(chunks) > 1
    for item in chunks:
        assert body[item.metadata['char_start']:item.metadata['char_end']] == item.content


def test_source_sections_do_not_treat_unanswered_exercise_as_explanation():
    from app.canonical_retrieval import _cached_chunks
    body = '# 数据准备\n\n## 处理缺失值\n数值特征可用训练集均值填补。\n\n## 练习\n怎样处理缺失值？\n\n# 下一章\n解释模型评估。\n'
    chunks = _cached_chunks(body, 'synthetic.md')
    answer = next(item for item in chunks if '均值填补' in item.content)
    question = next(item for item in chunks if '怎样处理' in item.content)
    assert answer.metadata['evidence_kind'] == 'text'
    assert question.metadata['evidence_kind'] == 'exercise_prompt'
    assert next(item for item in chunks if '解释模型评估' in item.content).metadata['evidence_kind'] == 'text'
    assert answer.metadata['title_path'] == ['数据准备', '处理缺失值']
    for item in chunks:
        assert body[item.metadata['char_start']:item.metadata['char_end']] == item.content
        assert '练习' not in answer.metadata['parent_content']


def test_formula_introduction_and_conditions_remain_one_original_span():
    from document_parser import chunk_document
    context = '正则化强度为非负参数，目标如下：\n\n$$L(w)+\\lambda \\|w\\|^2$$\n\n当参数为零时恢复原目标；大于零时惩罚较大的权重。'
    body = '前面的其他解释。' * 65 + '\n\n' + context + '\n\n' + '后面的新知识。' * 65
    chunks = chunk_document(body, 'synthetic.md', chunk_size=120)
    assert any(context in item.content for item in chunks)
    for item in chunks:
        assert body[item.metadata['char_start']:item.metadata['char_end']] == item.content
        assert item.content.count('$$') % 2 == 0


def test_pdf_numbered_formulas_keep_complete_terms_and_nearby_definition():
    from document_parser import chunk_document
    context=('标准化将特征调整为零均值和单位方差．假设有N个样本，先计算均值和方差：\n'
             '𝜇 = 1\n𝑁\n𝑁\n∑\n𝑛=1\n𝑥(𝑛), (7.52)\n'
             '𝜎2 = 1\n𝑁\n𝑁\n∑\n𝑛=1\n(𝑥(𝑛)− 𝜇)2. (7.53)\n'
             '然后减均值、除标准差：\n̂ 𝑥(𝑛)= 𝑥(𝑛)− 𝜇\n𝜎 , (7.54)\n'
             '其中标准差不能为0．')
    body='前面的其他解释．'*60+'\n'+context+'\n后续另一方法．'*50
    chunks=chunk_document(body,'synthetic-pdf.md',chunk_size=90)
    assert any(context in item.content for item in chunks)
    for item in chunks:
        assert body[item.metadata['char_start']:item.metadata['char_end']]==item.content
    assert ''.join(item.content for item in chunks)==body


def test_numbered_plain_text_and_code_are_not_misread_as_pdf_formula_blocks():
    from document_parser import _protected_teaching_ranges
    plain='This is a long paragraph about a method.\nRead equation (7.52)\n下一段。\n'
    assert not _protected_teaching_ranges(plain)
    code='```python\nvalue = 1\nprint(7.52)\n```\n'
    assert _protected_teaching_ranges(code)==[(0,len(code))]


def test_pdf_formula_context_stops_at_page_and_section_boundaries():
    from document_parser import _protected_teaching_ranges
    for boundary in ['--- 第 2 页 ---', '## 下一节', '```python\nx = 1\n```']:
        body='上一节的解释。\n'+boundary+'\n本节定义：\ny = x\n+ 1 (2.3)\n其中x为输入。\n'+boundary+'\n后一节。'
        start=body.index('y = x'); end=body.index('其中x为输入。')+len('其中x为输入。')
        ranges=[(a,b) for a,b in _protected_teaching_ranges(body) if a<=start<b]
        assert len(ranges)==1
        a,b=ranges[0]
        assert a>=body.index('本节定义') and b>=end
        assert boundary not in body[a:b]


def test_teaching_retrieval_prefers_explanation_but_keeps_requested_outline_and_practice():
    from app.canonical_retrieval import _cached_chunks, _answer_passages
    body = ('# 特征处理\n\n> 上游来源：教材。\n> 许可证：MIT。\n\n'
            '## 本章目标\n理解标准化的目的。\n\n'
            '## 标准化\n\n### 原理\n用训练集均值和标准差变换特征。\n\n'
            '## 实训检查\n比较变换前后的尺度。\n')
    chunks = list(_cached_chunks(body, 'synthetic-outline.md'))
    answers, excluded = _answer_passages(chunks, '标准化怎样改变特征？')
    assert len(answers) == 1 and '训练集均值' in answers[0].content
    from app.retrieval_ranking import indexing_text
    assert '理解标准化的目的' in indexing_text(answers[0])
    assert '理解标准化的目的' not in answers[0].content
    assert excluded == {'heading_only': 1, 'course_outline': 1, 'exercise_prompt': 1, 'source_note': 1}
    assert any('本章目标' in c.content for c in _answer_passages(chunks, '课程大纲和学习目标')[0])
    assert any('实训检查' in c.content for c in _answer_passages(chunks, '实训有哪些检查要求')[0])
    assert any('许可证' in c.content for c in _answer_passages(chunks, '资料许可是什么')[0])
    for item in chunks:
        assert body[item.metadata['char_start']:item.metadata['char_end']] == item.content


def test_heading_context_is_searchable_but_never_fabricated_as_original_text(tmp_path):
    from dataclasses import replace
    from app.retrieval_ranking import indexing_text
    formula = replace(chunk('formula', '$$a+b=c$$'), metadata={'title_path': ['图论', '路径长度']})
    other = chunk('other', '这里讨论微积分。')
    backend = CachingEmbeddingBackend(HashEmbeddingBackend(), cache_path=str(tmp_path/'headings.db'))
    order, _, _ = rank_chunks([other, formula], query='路径长度', expanded_query='路径长度', embeddings=backend)
    assert order[0] == 'formula'
    assert indexing_text(formula).startswith('图论 > 路径长度')
    assert formula.content == '$$a+b=c$$'


def test_protected_formula_context_never_crosses_requested_source_scope():
    from types import SimpleNamespace
    from app.canonical_retrieval import _source_chunks
    body = '不可见的上一章。\n\n## 当前章\n这是公式。\n\n$$x+y=z$$\n\n这是解释。\n\n## 后一章\n不可见的结论。'
    start, end = body.index('## 当前章'), body.index('## 后一章')
    items = _source_chunks(body, 'scoped.md', [SimpleNamespace(char_start=start, char_end=end)], scoped=True)
    for item in items:
        assert start <= item.metadata['char_start'] < item.metadata['char_end'] <= end
        assert '不可见' not in item.content and '不可见' not in item.metadata['parent_content']
def test_relevance_tokens_keep_language_boundaries_and_ignore_english_question_filler():
    from app.canonical_retrieval import _terms
    assert '的与' not in _terms('VotingClassifier 的 hard voting 与 soft voting 如何聚合？')
    assert {'hard', 'voting', 'soft'} <= _terms('hard voting 与 soft voting')
    assert _terms('Why should training and validation datasets be separated?') == {'training', 'validation', 'datasets', 'separated'}
    assert _terms('聚类如何通过') == {'聚类', '通过'}
    assert _terms('方差是否收敛') == {'方差', '收敛'}

def test_non_topic_phrases_do_not_leave_neighbour_bigrams_as_evidence():
    from app.canonical_retrieval import _terms, _lexical_overlap
    assert _terms('课程提供的完整解释') == {'解释'}
    assert _lexical_overlap('课程提供的张量形状变换', '课程提供的天气预报说明') == 0
    assert {'张量', '形状', '变换'} <= _terms('课程提供的张量形状变换')


def test_relevance_cleanup_keeps_topic_terms_without_changing_default_ranking_tokens():
    from app.retrieval_ranking import retrieval_tokens
    from app.canonical_retrieval import _terms
    assert '供的' in retrieval_tokens('提供的讲解')
    assert '供的' not in _terms('提供的讲解')
    assert {'relu', 'dropout', '标准', '准化'} <= _terms('请提供ReLU、Dropout与标准化的解释')
    assert {'知识', '识图', '图谱'} <= set(retrieval_tokens('知识图谱'))
