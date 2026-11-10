import asyncio
from types import SimpleNamespace

import pytest

import stream_api
from llm_client import ModelOutputLimitError


@pytest.mark.parametrize('fail_twice', [False, True])
def test_exhausted_draft_only_retries_itself_with_more_room(monkeypatch, fail_twice):
    original = SimpleNamespace(max_tokens=16384, reasoning_effort='high')
    calls = []

    async def call(backend, **kwargs):
        calls.append((backend.max_tokens, kwargs))
        if len(calls) == 1 or fail_twice:
            raise ModelOutputLimitError('output exhausted')
        return '完整课程讲解'

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    work = stream_api._professional_draft_call(original,
        user_prompt='同一份冻结题目和原文', operation='chat_subject_expert',
        input_summary={'source_count': 2})
    if fail_twice:
        with pytest.raises(ModelOutputLimitError):
            asyncio.run(work)
    else:
        assert asyncio.run(work) == '完整课程讲解'
    assert [budget for budget, _ in calls] == [32768, 65536]
    assert len({kw['user_prompt'] for _, kw in calls}) == 1
    assert [kw['input_summary']['output_limit_recovery'] for _, kw in calls] == [False, True]
    assert original.max_tokens == 16384


def test_other_failures_do_not_start_an_extra_draft(monkeypatch):
    calls = []

    async def call(*args, **kwargs):
        calls.append(kwargs)
        raise ConnectionError('transport failed')

    monkeypatch.setattr(stream_api, 'audited_legacy_text_call', call)
    with pytest.raises(ConnectionError):
        asyncio.run(stream_api._professional_draft_call(SimpleNamespace(max_tokens=16384)))
    assert len(calls) == 1
