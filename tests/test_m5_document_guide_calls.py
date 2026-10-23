import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBKnowledgeDocument, DBModelCall, DBStudentProfile
from knowledge_api import _generate_doc_guide_for_document


class Backend:
    model = "document-guide-test-model"

    def __init__(self, output=None, *, error=None):
        self.output = output
        self.error = error
        self.calls = 0

    async def generate(self, system_prompt, user_prompt, *, role):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.output


def _fixture(*, owner="guide-student"):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(DBStudentProfile(student_id=owner))
    session.add(DBKnowledgeDocument(
        id="guide-document", student_id=owner, filename="private.md",
        file_type="md", title="private title", content="private body",
    ))
    session.commit()

    async def database_runner(operation, *args):
        return operation(session, *args)

    return session, database_runner


def test_document_guide_success_is_owned_strict_and_private():
    session, runner = _fixture()
    output = json.dumps({
        "brief_summary": "core summary",
        "highlights": ["point one", "point two"],
        "faqs": [{"q": "question", "a": "answer"}],
    })
    backend = Backend(output)

    asyncio.run(_generate_doc_guide_for_document(
        "guide-document", "guide-student",
        text_content="private document content",
        owner_public_id="guide-owner-public", llm=backend, database_runner=runner,
    ))
    call = session.query(DBModelCall).one()
    document = session.query(DBKnowledgeDocument).one()

    assert call.owner_public_id == "guide-owner-public"
    assert call.trace_id.startswith("m5-doc-guide-")
    assert (call.status, call.error_code) == ("completed", "")
    assert document.multimodal_metadata["doc_guide"]["brief_summary"] == "core summary"
    summary = str(call.input_summary)
    assert "private document content" not in summary
    assert "private title" not in summary


def test_document_guide_invalid_output_is_failed_without_default_guide():
    session, runner = _fixture()
    backend = Backend('{"brief_summary":"missing fields"}')

    asyncio.run(_generate_doc_guide_for_document(
        "guide-document", "guide-student", text_content="private body",
        owner_public_id="guide-owner-public", llm=backend, database_runner=runner,
    ))
    call = session.query(DBModelCall).one()
    document = session.query(DBKnowledgeDocument).one()

    assert (call.status, call.error_code) == (
        "failed", "document_guide_output_invalid",
    )
    assert "doc_guide" not in (document.multimodal_metadata or {})


def test_document_guide_provider_failure_is_terminal():
    session, runner = _fixture()
    backend = Backend(error=RuntimeError("provider unavailable"))

    asyncio.run(_generate_doc_guide_for_document(
        "guide-document", "guide-student", text_content="private body",
        owner_public_id="guide-owner-public", llm=backend, database_runner=runner,
    ))
    call = session.query(DBModelCall).one()

    assert (call.status, call.error_code) == (
        "failed", "document_guide_provider_failed",
    )


def test_document_guide_rejects_missing_or_foreign_document_before_model():
    session, runner = _fixture(owner="actual-owner")
    backend = Backend("unused")

    asyncio.run(_generate_doc_guide_for_document(
        "guide-document", "wrong-owner", text_content="private body",
        owner_public_id="wrong-owner-public", llm=backend, database_runner=runner,
    ))

    assert backend.calls == 0
    assert session.query(DBModelCall).count() == 0


def test_document_guide_cancellation_is_terminal_and_propagates():
    session, runner = _fixture()
    backend = Backend(error=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_generate_doc_guide_for_document(
            "guide-document", "guide-student", text_content="private body",
            owner_public_id="guide-owner-public", llm=backend,
            database_runner=runner,
        ))

    call = session.query(DBModelCall).one()
    assert (call.status, call.error_code) == ("failed", "client_disconnected")
