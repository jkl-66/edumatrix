from types import SimpleNamespace
import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBChapter, DBCourse, DBModelCall, DBSourceDocument, DBSourceRef, DBUser
from app.m5_workspace import TutorContextSpec, archive_tutor_context, create_tutor_context
import stream_api
from llm_client import DeterministicEducationLLM
from app.auth import get_current_user
from app.main import app


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        DBUser(
            public_id="stream-owner", username="stream-owner", hashed_password="test",
            role="student", is_active=True,
        ),
        DBUser(
            public_id="stream-other", username="stream-other", hashed_password="test",
            role="student", is_active=True,
        ),
        DBCourse(
            id="stream-course", version="1", title="Stream course", visibility="public",
            manifest_version="1",
        ),
        DBSourceDocument(
            id="stream-source", course_id="stream-course", title="Stream source",
            filename="stream.md", file_format="md", content_hash="a" * 64,
        ),
        DBChapter(
            id="stream-chapter", course_id="stream-course", source_document_id="stream-source",
            stable_key="stream-chapter", title="Bound stream chapter",
        ),
        DBSourceRef(
            id="stream-ref", source_document_id="stream-source", chapter_id="stream-chapter",
            parser_version="stream-parser-v1", page_number=7, char_start=12, char_end=48,
            quote="Frozen citation for the legacy stream", content_hash="b" * 64,
        ),
    ])
    session.flush()
    row, _ = create_tutor_context(
        session,
        current_user=SimpleNamespace(public_id="stream-owner", role="student"),
        spec=TutorContextSpec(
            idempotency_key="stream-context-key",
            course_id="stream-course",
            context_mode="current_resource",
            primary_object_type="chapter",
            primary_object_id="stream-chapter",
            selected_source_ref_ids=("stream-ref",),
            teaching_style="close_reading",
            explanation_depth="deep",
            guidance_mode="socratic",
        ),
    )
    session.commit()
    return session, row


def test_legacy_stream_resolves_owned_canonical_context_without_generation(monkeypatch):
    session, row = _session()

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(stream_api, "run_db_op", fake_run_db_op)
    envelope, filenames, instruction = asyncio.run(
        stream_api._resolve_legacy_tutor_context(
            row.id, owner_public_id="stream-owner", question="Explain this source",
        )
    )

    assert envelope["generation_started"] is False
    assert envelope["teaching"] == {
        "style": "close_reading", "depth": "deep", "guidance_mode": "socratic",
    }
    assert filenames == ["stream.md"]
    assert "Frozen citation for the legacy stream" in instruction
    assert "page=7" in instruction
    assert f"hash={'b' * 64}" in instruction


def test_verified_tutor_sources_drive_cited_deterministic_answer():
    context = {
        "context": {
            "sources": [{
                "source_ref_id": "stream-ref",
                "source_document_id": "stream-source",
                "chapter_id": "stream-chapter",
                "quote": "关键词检索与向量检索先合并候选，再统一重排。",
                "content_hash": "b" * 64,
            }],
        },
    }
    sources = stream_api._verified_tutor_sources(context)
    evidence = stream_api._tutor_source_context(sources)
    resources = stream_api._tutor_source_resources(sources)
    answer = DeterministicEducationLLM().generate(
        "【已验证的 M5 学习上下文】只能使用冻结引用。",
        f"学生当前提问：为什么更稳定？\n背景知识库匹配证据：\n{evidence}",
        role="自适应助教",
    )

    assert "[stream-ref]" in answer
    assert "Recall@K" in answer
    assert resources[0]["citations"][0]["source_ref_id"] == "stream-ref"
    assert resources[0]["content"] == sources[0]["quote"]


def test_legacy_stream_rejects_cross_owner_and_archived_context(monkeypatch):
    session, row = _session()

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(stream_api, "run_db_op", fake_run_db_op)
    with pytest.raises(HTTPException) as forbidden:
        asyncio.run(
            stream_api._resolve_legacy_tutor_context(
                row.id, owner_public_id="stream-other", question="Steal context",
            )
        )
    assert forbidden.value.status_code == 403

    archive_tutor_context(
        session, row=row, owner_public_id="stream-owner", expected_lock_version=1,
    )
    session.commit()
    with pytest.raises(HTTPException) as archived:
        asyncio.run(
            stream_api._resolve_legacy_tutor_context(
                row.id, owner_public_id="stream-owner", question="Use archived context",
            )
        )
    assert archived.value.status_code == 409


def test_legacy_stream_http_rejects_cross_owner_before_sse_generation(monkeypatch):
    session, row = _session()

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(stream_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: DBUser(
        public_id="stream-other", username="stream-other", hashed_password="test",
        role="student", is_active=True,
    )
    try:
        response = TestClient(app).post("/api/stream/chat", json={
            "message": "Attempt to use another learner context",
            "student_id": "stream-other",
            "mode": "chat",
            "context_session_id": row.id,
        })
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "tutor_context_forbidden"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


class _IntentBackend:
    model = "intent-test-model"

    def __init__(self, output):
        self.output = output

    async def generate(self, system_prompt, user_prompt, *, role):
        return self.output


def test_intent_classification_uses_gateway_and_omits_raw_message(monkeypatch):
    session, _ = _session()
    monkeypatch.setattr("app.database.SessionLocal", lambda: session)
    result = asyncio.run(stream_api._classify_academic_intent(
        _IntentBackend('{"is_academic":false,"reason":"casual","reply":"## 智能答疑 / 系统说明\\n\\nredirect"}'),
        "private casual message",
        owner_public_id="stream-owner",
        course_id="stream-course",
    ))
    row = session.query(DBModelCall).one()
    assert result == {
        "is_academic": False,
        "reason": "casual",
        "reply": "## 智能答疑 / 系统说明\n\nredirect",
    }
    assert (row.status, row.error_code) == ("completed", "")
    assert row.prompt_version == "legacy_intent_classification:1.0"
    assert row.course_id == "stream-course"
    assert "private casual message" not in str(row.input_summary)


def test_intent_classification_records_invalid_schema_and_safely_allows(monkeypatch):
    session, _ = _session()
    monkeypatch.setattr("app.database.SessionLocal", lambda: session)
    result = asyncio.run(stream_api._classify_academic_intent(
        _IntentBackend('{"is_academic":"not-a-boolean"}'),
        "private malformed classification",
        owner_public_id="stream-owner",
        course_id="stream-course",
    ))
    row = session.query(DBModelCall).one()
    assert result["is_academic"] is True
    assert result["reason"] == "分类器异常放行"
    assert (row.status, row.error_code) == ("failed", "structured_output_invalid")


class _VisionBackend:
    model = "vision-test-model"

    def __init__(self, *, fail=False):
        self.fail = fail
        self.external_vision_backend = self

    async def generate_stream(self, system_prompt, user_prompt, *, role, images):
        if self.fail:
            raise RuntimeError("vision provider unavailable")
        yield "formula x squared"


@pytest.mark.parametrize("fail", [False, True])
def test_ocr_stream_records_terminal_state_without_base64(monkeypatch, fail):
    session, _ = _session()

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(stream_api, "run_db_op", fake_run_db_op)
    encoded_image = "data:image/png;base64,private-image-payload"
    result = asyncio.run(stream_api._ocr_multimodal_describer(
        "private image question",
        [encoded_image],
        _VisionBackend(fail=fail),
        owner_public_id="stream-owner",
        course_id="stream-course",
    ))
    row = session.query(DBModelCall).one()
    expected = ("failed", "vision_provider_failed") if fail else ("completed", "")
    assert (row.status, row.error_code) == expected
    assert row.prompt_version == "legacy_multimodal_ocr:1.0"
    assert row.input_summary["image_count"] == 1
    assert row.input_summary["image_encoded_chars"] == len(encoded_image)
    assert "private-image-payload" not in str(row.input_summary)
    assert "private image question" not in str(row.input_summary)
    if fail:
        assert result.startswith("【OCR/多模态图片解析失败】")
        assert "提取成功" not in result
    else:
        assert result.startswith("【OCR/多模态图片提取成功】")


def test_deterministic_ocr_never_fabricates_image_contents():
    from llm_client import AsyncDeterministicEducationLLM

    result = asyncio.run(stream_api._ocr_multimodal_describer(
        "计算这个池化层输出",
        ["data:image/png;base64,not-read-in-deterministic-mode"],
        AsyncDeterministicEducationLLM(),
    ))

    assert result.startswith("【OCR/多模态图片解析不可用】")
    assert "4x4" not in result
    assert "提取成功" not in result


class _SuggestedLLM:
    model = "suggested-test-model"

    def __init__(self, *, fail=False):
        self.fail = fail

    async def generate(self, system_prompt, user_prompt, *, role):
        if self.fail:
            raise RuntimeError("suggestion provider unavailable")
        return "1. 原理如何推导？\n2. 如何编写示例？\n3. 常见错误是什么？"


@pytest.mark.parametrize("fail", [False, True])
def test_suggested_questions_records_actual_model_call(monkeypatch, fail):
    session, _ = _session()

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(stream_api, "run_db_op", fake_run_db_op)
    result = asyncio.run(stream_api._generate_suggested_questions(
        SimpleNamespace(llm=_SuggestedLLM(fail=fail)),
        "private concept",
        None,
        owner_public_id="stream-owner",
        course_id="stream-course",
    ))
    row = session.query(DBModelCall).one()
    expected = ("failed", "provider_call_failed") if fail else ("completed", "")
    assert (row.status, row.error_code) == expected
    assert row.prompt_version == "legacy_suggested_questions:1.0"
    assert "private concept" not in str(row.input_summary)
    assert len(result) == 3


def test_suggested_questions_static_default_has_no_model_call(monkeypatch):
    session, _ = _session()
    result = asyncio.run(stream_api._generate_suggested_questions(
        SimpleNamespace(llm=_SuggestedLLM()), "", None,
    ))
    assert session.query(DBModelCall).count() == 0
    assert len(result) == 3


class _PeerBackend:
    model = "peer-test-model"

    def __init__(self, output=None, *, fail=False):
        self.output = output
        self.fail = fail

    async def generate(self, system_prompt, user_prompt, *, role):
        if self.fail:
            raise RuntimeError("peer provider unavailable")
        return self.output


@pytest.mark.parametrize(
    ("backend", "expected_status", "expected_error"),
    [
        (
            _PeerBackend(
                '{"wrong_code":"x = 1","wrong_reason":"hidden bug",'
                '"correction_instructions":"replace x"}'
            ),
            "completed",
            "",
        ),
        (_PeerBackend("not-json"), "failed", "structured_output_invalid"),
        (_PeerBackend(fail=True), "failed", "provider_call_failed"),
    ],
)
def test_peer_challenge_records_strict_terminal_state(
    monkeypatch, backend, expected_status, expected_error,
):
    session, _ = _session()

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(stream_api, "run_db_op", fake_run_db_op)
    if expected_status == "completed":
        result = asyncio.run(stream_api._generate_peer_challenge(
            backend,
            concept="private concept",
            recent_history="private conversation history",
            owner_public_id="stream-owner",
            course_id="stream-course",
        ))
        assert result["wrong_code"] == "x = 1"
    else:
        with pytest.raises(Exception):
            asyncio.run(stream_api._generate_peer_challenge(
                backend,
                concept="private concept",
                recent_history="private conversation history",
                owner_public_id="stream-owner",
                course_id="stream-course",
            ))
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == (expected_status, expected_error)
    assert row.prompt_version == "legacy_peer_challenge:1.0"
    assert "private concept" not in str(row.input_summary)
    assert "private conversation history" not in str(row.input_summary)
