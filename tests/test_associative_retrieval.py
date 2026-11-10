"""Scope and version boundaries for the optional real HippoRAG adapter."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.associative_retrieval import scope_identity
from app.canonical_retrieval import retrieve_canonical_sources
from app.database import DBSourceRef, DBUser
from tests.test_canonical_readiness import catalog


def test_graph_receives_only_current_authorized_selection(catalog, monkeypatch):
    import app.associative_retrieval as graph
    db = catalog
    ref = db.get(DBSourceRef, 'ref-public')
    ref.char_start = 7
    ref.char_end = 14
    db.flush()
    captured = []
    def rank(chunks, **kwargs):
        captured.extend(chunks)
        return [c.id for c in chunks], {c.id: {'semantic_score': .9} for c in chunks}, {'method': 'hipporag2'}
    monkeypatch.setattr(graph, 'rank_associative_chunks', rank)
    actor = DBUser(public_id='other', username='other', role='student', is_active=True)
    result = retrieve_canonical_sources(db, course_id='public-course', actor=actor,
        source_ref_ids=['ref-public', 'ref-member'], query='训练', retrieval_mode='hipporag2')
    assert captured
    assert all(c.metadata['char_start'] >= 7 and c.metadata['char_end'] <= 14 for c in captured)
    assert {item['source_ref']['source_ref_id'] for item in result['items']} == {'ref-public'}
    captured.clear()
    denied = retrieve_canonical_sources(db, course_id='member-course', actor=actor,
        source_ref_ids=['ref-member'], query='训练', retrieval_mode='hipporag2')
    assert not denied['items'] and not captured


def test_scope_changes_for_body_version_embedding_and_course():
    from models import Evidence, EvidenceModality
    chunk = Evidence(id='source/version/chunk', title='x', source='x', content='训练资料', modality=EvidenceModality.TEXT)
    options = {'course_id': 'course-a', 'embedding_identity': {'model': 'BGE'}, 'model': 'strong-api'}
    baseline = scope_identity([chunk], **options)
    assert scope_identity([replace(chunk, content='更新后的训练资料')], **options) != baseline
    assert scope_identity([chunk], **{**options, 'course_id': 'course-b'}) != baseline
    assert scope_identity([chunk], **{**options, 'embedding_identity': {'model': 'different'}}) != baseline
    second = replace(chunk, id='second')
    assert scope_identity([chunk, second], **options) == scope_identity([second, chunk], **options)


def test_chat_freezes_graph_trace_and_exact_source_projection(catalog, monkeypatch):
    from app.chat_api import _context_source_refs
    from app.database import DBChatConversation
    import app.associative_retrieval as graph
    trace = {'scope_key': 'scope', 'graph_used': True, 'fact_filter': {'facts_after_rerank': [['训练集','用于','拟合']]}}
    def rank(chunks, **kwargs):
        return [c.id for c in chunks], {c.id: {'semantic_score': .9} for c in chunks}, {'hipporag2': trace}
    monkeypatch.setattr(graph, 'rank_associative_chunks', rank)
    actor = DBUser(public_id='other', username='other', role='student', is_active=True)
    refs = _context_source_refs(catalog, actor, DBChatConversation(course_id='public-course'),
        [{'sourceRef': {'id': 'ref-public', 'courseId': 'public-course'}}],
        question='训练集如何使用？', retrieval_mode='hipporag2')
    assert refs and refs[0]['sourceRefId'] == 'ref-public'
    assert refs[0]['retrieval_evidence']['hipporag2'] == trace
    assert refs[0]['route'].startswith('/knowledge/documents/src-public?')
    assert '训练集拟合模型' in refs[0]['quote']


def test_sync_bridge_preserves_templates_and_detects_output_exhaustion(monkeypatch):
    import requests
    from llm_client import OpenAIChatLLM
    sent = []
    finish = ['stop']
    def post(endpoint, **kwargs):
        sent.append(kwargs['json'])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            'choices': [{'finish_reason': finish[0], 'message': {'content': '{"named_entities": ["训练集"]}'}}],
            'usage': {'total_tokens': 12}, 'model': 'served-model'})
    monkeypatch.setattr(requests, 'post', post)
    backend = OpenAIChatLLM('https://example.invalid', 'test', thinking_mode='enabled', reasoning_effort='low')
    messages = [{'role': 'system', 'content': 'Extract'}, {'role': 'user', 'content': 'one'},
                {'role': 'assistant', 'content': 'demo'}, {'role': 'user', 'content': 'two'}]
    text, metadata = backend.infer_messages(messages, response_format={'type': 'json_object'})
    assert sent[0]['messages'] == messages and sent[0]['reasoning_effort'] == 'low'
    assert sent[0]['response_format'] == {'type': 'json_object'}
    assert metadata['total_tokens'] == 12 and metadata['model'] == 'served-model'
    finish[0] = 'length'
    with pytest.raises(RuntimeError, match='模型输出尚未完成'):
        backend.infer_messages(messages)
