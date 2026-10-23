from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBModelCall, DBUser
from document_parser import _describe_image_with_multimodal_llm
import config
import document_parser
import requests


class Response:
    def __init__(self, content="教材页面介绍了池化层的定义、作用和一个公式示例。", *, error=None):
        self.content = content
        self.error = error

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


def _fixture(monkeypatch, response=None, *, error=None):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    session.add(DBUser(
        public_id="pdf-owner-public",
        username="pdf-owner",
        hashed_password="test",
        role="student",
        is_active=True,
    ))
    session.commit()
    monkeypatch.setattr(document_parser, "_check_vision_llm", lambda: True)
    monkeypatch.setattr(config, "CONFIG", SimpleNamespace(
        multimodal_llm_endpoint="https://vision.example/v1/chat/completions",
        multimodal_llm_api_key="test-key",
        multimodal_llm_model="vision-test-model",
    ))
    calls = []

    def fake_post(endpoint, *, json, headers, timeout):
        calls.append((endpoint, json, headers, timeout))
        if error is not None:
            raise error
        return Response(response) if response is not None else Response()

    monkeypatch.setattr(requests, "post", fake_post)
    return session, factory, calls


def _run(factory, *, owner="pdf-owner-public"):
    return _describe_image_with_multimodal_llm(
        "PRIVATE_BASE64_IMAGE",
        3,
        "PRIVATE_FILENAME.pdf",
        owner_public_id=owner,
        model_call_context={
            "trace_id": "m5-pdf-visual-trace",
            "session_factory": factory,
        },
    )


def test_pdf_visual_call_records_owner_trace_and_minimal_summary(monkeypatch):
    session, factory, calls = _fixture(monkeypatch)

    result = _run(factory)
    row = session.query(DBModelCall).one()

    assert result.startswith("教材页面")
    assert len(calls) == 1
    assert row.owner_public_id == "pdf-owner-public"
    assert row.trace_id == "m5-pdf-visual-trace"
    assert row.provider == "multimodal-openai-compatible"
    assert (row.status, row.error_code) == ("completed", "")
    summary = str(row.input_summary)
    assert "PRIVATE_BASE64_IMAGE" not in summary
    assert "PRIVATE_FILENAME" not in summary
    assert row.input_summary["image_payload_included"] is False


def test_pdf_visual_empty_output_is_failed_and_falls_back(monkeypatch):
    session, factory, _ = _fixture(monkeypatch, response="")

    result = _run(factory)
    row = session.query(DBModelCall).one()

    assert result is None
    assert (row.status, row.error_code) == (
        "failed",
        "pdf_visual_description_output_invalid",
    )


def test_pdf_visual_provider_failure_is_terminal_and_falls_back(monkeypatch):
    session, factory, _ = _fixture(monkeypatch, error=RuntimeError("provider unavailable"))

    result = _run(factory)
    row = session.query(DBModelCall).one()

    assert result is None
    assert (row.status, row.error_code) == (
        "failed",
        "pdf_visual_description_provider_failed",
    )


def test_unowned_pdf_visual_does_not_call_external_endpoint(monkeypatch):
    _, factory, calls = _fixture(monkeypatch)

    result = _run(factory, owner=None)

    assert result is None
    assert calls == []
