import asyncio
import json

import pytest

import app.feynman as feynman_module
import llm_client
from app.feynman import (
    FeynmanContextSnapshot,
    FeynmanError,
    FeynmanState,
    SourceSnapshot,
    _live_answer_question,
    _live_evaluate,
    _model_json,
)
from tests.test_f6_t05_feynman import ROUND1, _action, _resource, _session
from app.competition_demo_seed import seed_competition_demo
from app.database import DBArtifactVersion, DBLearningEvent


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Client:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0
        self.requests = []

    async def post(self, *args, **kwargs):
        self.calls += 1
        self.requests.append(kwargs)
        payload = self.payloads[min(self.calls - 1, len(self.payloads) - 1)]
        return _Response(payload)


def _completion(content, **message_fields):
    return {"choices": [{"message": {"content": content, **message_fields}}]}


def _run(awaitable):
    return asyncio.run(awaitable)


def test_openai_content_extraction_accepts_string_and_text_blocks_but_not_reasoning():
    assert llm_client.extract_openai_message_content({"content": '{"ok": true}'}) == '{"ok": true}'
    assert llm_client.extract_openai_message_content({
        "content": [
            {"type": "text", "text": '{"ok": '},
            {"type": "text", "text": "true}"},
        ],
        "reasoning_content": "private reasoning",
    }) == '{"ok": true}'
    assert llm_client.extract_openai_message_content({
        "content": {"type": "text", "text": '{"ok": true}'},
    }) == '{"ok": true}'
    assert llm_client.extract_openai_message_content({
        "content": "",
        "reasoning_content": '{"ok": true}',
    }) == ""


def test_async_openai_structured_call_accepts_text_blocks(monkeypatch):
    client = _Client([_completion([
        {"type": "text", "text": '{"score": '},
        {"type": "text", "text": "1}"},
    ])])

    async def get_client():
        return client

    monkeypatch.setattr(llm_client, "_get_httpx_client", get_client)
    backend = llm_client.AsyncOpenAIChatLLM(
        endpoint="https://example.test/v1/chat/completions",
        api_key="test-key",
        model="deepseek-v4-flash",
        thinking_mode="max",
        reasoning_effort="max",
    )
    assert _run(backend.generate("只输出 JSON 对象", "评价", role="feynman_evaluator")) == '{"score": 1}'
    assert client.calls == 1
    assert client.requests[0]["json"]["response_format"] == {"type": "json_object"}


def test_async_openai_empty_public_content_retries_without_using_reasoning(monkeypatch):
    client = _Client([_completion("", reasoning_content="private reasoning")])

    async def get_client():
        return client

    async def immediate_retry(factory, max_attempts=3, **kwargs):
        last = None
        for _ in range(max_attempts):
            try:
                return await factory()
            except Exception as exc:  # noqa: PERF203 - this is the retry contract under test
                last = exc
        raise RuntimeError(f"重试 {max_attempts} 次后仍然失败: {last}") from last

    monkeypatch.setattr(llm_client, "_get_httpx_client", get_client)
    monkeypatch.setattr(llm_client, "retry_with_backoff", immediate_retry)
    backend = llm_client.AsyncOpenAIChatLLM(
        endpoint="https://example.test/v1/chat/completions",
        api_key="test-key",
        model="deepseek-v4-flash",
        thinking_mode="max",
        reasoning_effort="max",
    )
    with pytest.raises(RuntimeError) as exc_info:
        _run(backend.generate("只输出 JSON 对象", "评价", role="feynman_evaluator"))
    assert client.calls == 3
    assert "reasoning" not in str(exc_info.value).lower()
    assert "模型未返回可用的结构化正文" in str(exc_info.value)


def test_async_openai_empty_first_attempt_recovers_with_next_attempt(monkeypatch):
    client = _Client([
        _completion("", reasoning_content="private reasoning"),
        _completion('{"score": 1}'),
    ])

    async def get_client():
        return client

    async def immediate_retry(factory, max_attempts=3, **kwargs):
        last = None
        for _ in range(max_attempts):
            try:
                return await factory()
            except Exception as exc:  # noqa: PERF203 - this is the retry contract under test
                last = exc
        raise RuntimeError(f"重试 {max_attempts} 次后仍然失败: {last}") from last

    monkeypatch.setattr(llm_client, "_get_httpx_client", get_client)
    monkeypatch.setattr(llm_client, "retry_with_backoff", immediate_retry)
    backend = llm_client.AsyncOpenAIChatLLM(
        endpoint="https://example.test/v1/chat/completions",
        api_key="test-key",
        model="deepseek-v4-flash",
        thinking_mode="max",
        reasoning_effort="max",
    )
    assert _run(backend.generate("只输出 JSON 对象", "评价", role="feynman_evaluator")) == '{"score": 1}'
    assert client.calls == 2


def _live_state():
    context = FeynmanContextSnapshot(
        course_id="course-live",
        course_title="机器学习导论",
        knowledge_point_id="kp-live",
        knowledge_point_title="梯度下降",
        source_ref_ids=("ref-live",),
        context_fingerprint="fingerprint-live",
        generation_mode="llm",
    )
    return FeynmanState(
        session_id="session-live",
        owner_public_id="owner-live",
        source_resource_id="resource-live",
        source_resource_version_id="version-live",
        source_resource_content_sha256="a" * 64,
        title="梯度下降 · 费曼复述",
        course_id="course-live",
        course_title="机器学习导论",
        knowledge_point_id="kp-live",
        knowledge_point_title="梯度下降",
        source_refs=(SourceSnapshot(
            source_ref_id="ref-live",
            title="课程教材",
            location_label="第1节",
            quote="梯度下降沿负梯度方向更新参数。",
        ),),
        task_prompt="解释梯度下降",
        adaptation_note="关注成立条件",
        context_snapshot=context,
    )


def _valid_evaluation_payload():
    return {
        "score": 82,
        "dimensions": [
            {"key": "core_meaning", "label": "核心含义", "score": 21, "evidence": "说明了概念用途。"},
            {"key": "mechanism", "label": "机制与步骤", "score": 21, "evidence": "说明了主要步骤。"},
            {"key": "conditions", "label": "成立条件", "score": 16, "evidence": "提到成立前提。"},
            {"key": "example", "label": "适用例子", "score": 12, "evidence": "给出了课程场景。"},
            {"key": "boundary", "label": "边界与反例", "score": 12, "evidence": "指出了限制。"},
        ],
        "strengths": ["机制表达清楚"],
        "gaps": ["还可补充边界条件"],
        "omissions": [],
    }


def test_feynman_model_json_exposes_stable_retryable_error_without_provider_details(monkeypatch):
    class EmptyBackend:
        async def generate(self, system, user, *, role):
            raise RuntimeError("重试 3 次后仍然失败: 模型未返回可用的结构化正文") from llm_client.StructuredModelContentError(
                "模型未返回可用的结构化正文"
            )

    monkeypatch.setattr(feynman_module, "_live_model_backend", lambda: EmptyBackend())
    with pytest.raises(FeynmanError) as exc_info:
        _model_json(system="只输出 JSON 对象", user={"text": "复述"}, role="feynman_evaluator")
    assert exc_info.value.code == "feynman_model_call_failed"
    assert str(exc_info.value) == "真实模型评价失败，请重试：模型未返回可用的结构化内容。"
    assert "structured model" not in str(exc_info.value).lower()
    assert "reasoning_content" not in str(exc_info.value)


def test_live_evaluation_keeps_strict_five_dimension_contract(monkeypatch):
    systems = []

    class ValidBackend:
        async def generate(self, system, user, *, role):
            systems.append((role, system))
            return json.dumps(_valid_evaluation_payload(), ensure_ascii=False)

    monkeypatch.setattr(feynman_module, "_live_model_backend", lambda: ValidBackend())
    evaluation = _live_evaluate(
        "梯度下降通过梯度更新参数，并说明条件、例子和边界。",
        _live_state(),
        round_number=1,
    )
    assert evaluation.evaluation_mode == "llm"
    assert evaluation.score == 82
    assert {item.key for item in evaluation.dimensions} == {
        "core_meaning", "mechanism", "conditions", "example", "boundary",
    }
    assert "必须把最终 JSON 放在公开 content 字段返回" in systems[0][1]


def test_live_evaluation_accepts_keyed_dimension_object(monkeypatch):
    payload = _valid_evaluation_payload()
    payload["dimensions"] = {
        item["key"]: {key: value for key, value in item.items() if key != "key"}
        for item in payload["dimensions"]
    }

    class ValidBackend:
        async def generate(self, system, user, *, role):
            return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(feynman_module, "_live_model_backend", lambda: ValidBackend())
    evaluation = _live_evaluate(
        "梯度下降通过梯度更新参数，并说明条件、例子和边界。",
        _live_state(),
        round_number=1,
    )
    assert evaluation.evaluation_mode == "llm"
    assert evaluation.score == 82
    assert len(evaluation.dimensions) == 5


def test_live_evaluation_accepts_translated_dimension_labels(monkeypatch):
    payload = _valid_evaluation_payload()
    labels = ("核心含义", "机制与步骤", "成立条件", "适用例子", "边界与反例")
    payload["dimensions"] = {
        label: {key: value for key, value in item.items() if key != "key"}
        for label, item in zip(labels, payload["dimensions"])
    }

    class ValidBackend:
        async def generate(self, system, user, *, role):
            return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(feynman_module, "_live_model_backend", lambda: ValidBackend())
    evaluation = _live_evaluate(
        "梯度下降通过梯度更新参数，并说明条件、例子和边界。",
        _live_state(),
        round_number=1,
    )
    assert evaluation.evaluation_mode == "llm"
    assert evaluation.score == 82
    assert [item.key for item in evaluation.dimensions] == [
        "core_meaning", "mechanism", "conditions", "example", "boundary",
    ]


def test_feynman_question_prompt_also_requires_public_content(monkeypatch):
    systems = []

    class TutorBackend:
        async def generate(self, system, user, *, role):
            systems.append((role, system))
            return json.dumps({"answer": "依据课程来源，先确认前提，再解释机制。"}, ensure_ascii=False)

    monkeypatch.setattr(feynman_module, "_live_model_backend", lambda: TutorBackend())
    answer = _live_answer_question(_live_state(), "为什么要先确认前提？")
    assert answer.answer_mode == "llm_grounded"
    assert "必须把最终 JSON 放在公开 content 字段返回" in systems[0][1]
    assert answer.answer == "从学习内容来看，先确认前提，再解释机制。"
    assert all(marker not in answer.answer for marker in ("依据", "来源", "上下文", "确定性"))


@pytest.mark.parametrize("payload", [
    {**_valid_evaluation_payload(), "dimensions": _valid_evaluation_payload()["dimensions"][:-1]},
    {**_valid_evaluation_payload(), "score": 81},
])
def test_live_evaluation_rejects_incomplete_or_inconsistent_payload(monkeypatch, payload):
    class InvalidBackend:
        async def generate(self, system, user, *, role):
            return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(feynman_module, "_live_model_backend", lambda: InvalidBackend())
    with pytest.raises(FeynmanError) as exc_info:
        _live_evaluate("梯度下降通过梯度更新参数，并说明条件、例子和边界。", _live_state(), round_number=1)
    assert exc_info.value.code == "feynman_model_output_invalid"


def test_empty_evaluation_keeps_submitted_text_and_version_retryable(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(__import__("app.database", fromlist=["DBUser"]).DBUser).filter_by(username="lzz").one()
        resource = _resource(session, learner, "noc-t20-empty-recovery-resource")
        _, version, state, _ = feynman_module.create_session(
            session,
            owner=learner.public_id,
            source_resource_id=resource.id,
            idempotency_key="noc-t20-empty-recovery-session",
        )
        llm_context = state.context_snapshot.model_copy(update={"generation_mode": "llm"})
        state = state.model_copy(update={"context_snapshot": llm_context})
        version.content = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        session.commit()
        payload = feynman_module.get_session(session, state.session_id, learner.public_id)
        payload = _action(session, learner, payload, "submit_round1", "noc-t20-empty-submit", ROUND1)
        current_version_id = payload["version_id"]
        version_count = session.query(DBArtifactVersion).filter_by(artifact_id=state.session_id).count()

        class EmptyBackend:
            async def generate(self, system, user, *, role):
                raise llm_client.StructuredModelContentError("模型未返回可用的结构化正文")

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(feynman_module, "_live_model_backend", lambda: EmptyBackend())
        try:
            with pytest.raises(FeynmanError) as exc_info:
                _action(session, learner, payload, "evaluate_round1", "noc-t20-empty-eval", None)
        finally:
            monkeypatch.undo()
        assert exc_info.value.code == "feynman_model_call_failed"
        assert "请重试" in str(exc_info.value)
        assert feynman_module.get_session(session, state.session_id, learner.public_id)["version_id"] == current_version_id
        assert session.query(DBArtifactVersion).filter_by(artifact_id=state.session_id).count() == version_count
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id, event_type="feynman_submitted").count() == 0
    finally:
        session.close()
        engine.dispose()
