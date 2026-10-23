from __future__ import annotations

import asyncio
import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.chat_api import _context_source_refs
from app.canonical_retrieval import list_canonical_source_refs, retrieve_canonical_sources
from app.database import (
    Base,
    DBChapter,
    DBChatAttachment,
    DBChatConversation,
    DBCourse,
    DBCourseDocument,
    DBKnowledgeDocument,
    DBSourceDocument,
    DBSourceRef,
    DBStudentProfile,
    DBUser,
)
from app.next_core_retrieval import search_persisted_course_documents
from document_parser import chunk_document, parse_document
from ingestion import DocumentIngestionPipeline
from knowledge_api import _index_canonical_chunks
import knowledge_api
from models import EvidenceModality
from rag_engine import hybrid_rag
from stream_api import _verified_tutor_sources


@pytest.fixture()
def canonical_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'noc-t03.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    owner = DBUser(
        public_id="noc-owner",
        username="noc-owner",
        hashed_password="x",
        role="student",
        is_active=True,
    )
    outsider = DBUser(
        public_id="noc-outsider",
        username="noc-outsider",
        hashed_password="x",
        role="student",
        is_active=True,
    )
    session.add_all([
        owner,
        outsider,
        DBStudentProfile(student_id="noc-owner"),
    ])
    course = DBCourse(
        id="noc-course",
        version="1",
        title="统一知识库课程",
        visibility="public",
        status="published",
        owner_public_id=owner.public_id,
        manifest_version="noc-t03-v1",
    )
    session.add(course)
    session.flush()

    ready_text = "梯度下降沿损失函数的负梯度方向更新参数。学习率决定每次参数更新的步长。"
    failed_text = "这份资料的结构抽取失败，不得作为课程证据。"
    for key, text, status in (
        ("ready", ready_text, "ready"),
        ("failed", failed_text, "failed"),
    ):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        document_id = f"noc-doc-{key}"
        source_id = f"noc-source-{key}"
        chapter_id = f"noc-chapter-{key}"
        ref_id = f"noc-ref-{key}"
        session.add(DBCourseDocument(
            id=document_id,
            course_id=course.id,
            chapter_order=1 if key == "ready" else 2,
            filename=f"{key}.md",
            file_type="md",
            title=f"{key} 资料",
            content=text,
            content_hash=digest,
            status="published",
        ))
        session.add(DBSourceDocument(
            id=source_id,
            course_id=course.id,
            legacy_document_id=document_id,
            title=f"{key} 资料",
            filename=f"{key}.md",
            file_format="md",
            content_hash=digest,
            source_sha256=digest,
            processed_sha256=digest,
            parser_version="noc-parser-v1",
            processing_status=status,
            processing_error_code="structure_failed" if status == "failed" else "",
        ))
        session.add(DBChapter(
            id=chapter_id,
            course_id=course.id,
            source_document_id=source_id,
            stable_key=key,
            title=f"{key} 章节",
            position=1 if key == "ready" else 2,
            char_start=0,
            char_end=len(text),
        ))
        session.add(DBSourceRef(
            id=ref_id,
            source_document_id=source_id,
            chapter_id=chapter_id,
            parser_version="noc-parser-v1",
            page_number=1,
            char_start=0,
            char_end=len(text),
            location_kind="page",
            location_index=1,
            location_label="第 1 页",
            content_hash=digest,
            quote=text,
        ))
    session.commit()
    try:
        yield session, owner, outsider, course
    finally:
        session.close()
        engine.dispose()


def test_parser_ingestion_and_faiss_adapter_share_chunk_semantics(tmp_path):
    text = (
        "# 梯度下降\n\n"
        "梯度下降沿损失函数的负梯度方向更新参数。学习率决定步长。\n\n"
        "# 反向传播\n\n"
        "反向传播使用链式法则计算每个参数的梯度，并把结果传回网络。"
    )
    parser_chunks = chunk_document(text, source="fixture.md")
    ingestion_chunks = DocumentIngestionPipeline(
        index=__import__("vector_store").InMemoryVectorIndex("noc")
    ).chunk_text(text, source="fixture.md", title="fixture")

    from scripts.ingest_to_faiss import chunk_text as faiss_chunk_text

    faiss_contents = faiss_chunk_text(text, source="fixture.md")
    assert parser_chunks
    assert [item.content for item in ingestion_chunks] == [item.content for item in parser_chunks]
    assert [item.metadata.get("parent_content") for item in ingestion_chunks] == [
        item.metadata.get("parent_content") for item in parser_chunks
    ]
    assert faiss_contents == [item.content for item in parser_chunks]


def test_faiss_special_formats_use_canonical_parser(tmp_path):
    from scripts.ingest_to_faiss import extract_csv, extract_epub, extract_ipynb, extract_tex

    csv_path = tmp_path / "dataset.csv"
    csv_path.write_text("name,value\nalpha,1\nbeta,2\n", encoding="utf-8")
    tex_path = tmp_path / "notes.tex"
    tex_path.write_text(r"\\section{梯度下降} 梯度下降沿负梯度更新参数。", encoding="utf-8")
    ipynb_path = tmp_path / "lesson.ipynb"
    ipynb_path.write_text(json.dumps({
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": "梯度下降沿负梯度方向更新参数，学习率决定每一步的步长。"},
            {"cell_type": "code", "execution_count": 1, "metadata": {}, "outputs": [], "source": "x = 1\nfor step in range(3):\n    x -= 0.1 * step\nprint(x)"},
        ],
    }), encoding="utf-8")
    epub_path = tmp_path / "book.epub"
    with zipfile.ZipFile(epub_path, "w") as archive:
        archive.writestr("chapter1.xhtml", "<h1>梯度下降课程章节</h1><p>梯度下降沿负梯度方向更新参数，学习率决定每一步的步长。</p>")

    assert extract_csv(csv_path) and "alpha" in extract_csv(csv_path)[0]["content"]
    assert extract_tex(tex_path) and "梯度下降" in extract_tex(tex_path)[0]["content"]
    notebook_chunks = extract_ipynb(ipynb_path)
    assert notebook_chunks and any("```python" in item["content"] for item in notebook_chunks)
    assert extract_epub(epub_path) and "负梯度" in extract_epub(epub_path)[0]["content"]


def test_canonical_retrieval_returns_only_ready_sources_with_locators(canonical_session):
    session, owner, _, course = canonical_session
    result = retrieve_canonical_sources(
        session,
        course_id=course.id,
        query="梯度下降负梯度学习率",
        actor=owner,
    )
    assert result["low_confidence"] is False
    assert result["items"]
    assert {item["source"].id for item in result["items"]} == {"noc-source-ready"}
    evidence = result["items"][0]["evidence"]
    projection = result["items"][0]["source_ref"]
    assert evidence.metadata["source_document_id"] == "noc-source-ready"
    assert evidence.metadata["source_ref_id"] == "noc-ref-ready"
    assert projection["location_label"] == "第 1 页"
    assert projection["route"].startswith("/knowledge/documents/noc-source-ready")


def test_failed_source_is_not_indexed_and_ready_index_keeps_provenance(monkeypatch):
    from document_parser import chunk_document

    chunks = chunk_document("梯度下降使用负梯度更新参数。", source="ready.md")
    calls = []

    def capture(items, *, owner_id):
        calls.append((items, owner_id))

    monkeypatch.setattr(hybrid_rag, "ingest_user_documents", capture)
    assert _index_canonical_chunks(
        chunks,
        source_document_id="src-ready",
        source_ref_ids=["ref-ready"],
        source_status="ready",
        owner_id="noc-owner",
    ) == []
    assert calls and calls[0][1] == "noc-owner"
    assert all(item.metadata["canonical_source"] for item in calls[0][0])
    assert all(item.metadata["source_ref_id"] == "ref-ready" for item in calls[0][0])

    calls.clear()
    assert _index_canonical_chunks(
        chunks,
        source_document_id="src-failed",
        source_ref_ids=["ref-failed"],
        source_status="failed",
        owner_id="noc-owner",
    ) == ["rag_index_skipped_source_unavailable"]
    assert calls == []


def test_web_import_uses_canonical_source_registration(monkeypatch, tmp_path, canonical_session):
    session, owner, _, course = canonical_session

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    async def fake_text_call(*args, **kwargs):
        return "# 网页资料\n\n梯度下降沿负梯度方向更新参数。"

    async def fake_structure(*args, **kwargs):
        parsed = args[0]
        return {
            "status": "ready",
            "chapter_strategy": "llm_semantic_sections",
            "model": {"provider": "test", "model": "test"},
            "chapters": [{
                "title": "网页资料",
                "char_start": 0,
                "char_end": len(parsed.text),
                "heading_level": 1,
                "knowledge_points": [{"code": "KP-001", "title": "梯度下降"}],
                "position": 1,
            }],
            "knowledge_point_count": 1,
            "error": None,
        }

    class Request:
        headers = {}

        async def json(self):
            return {
                "student_id": owner.username,
                "course_id": course.id,
                "query": "梯度下降",
                "title": "网页梯度下降资料",
                "url": "https://example.com/gradient",
                "snippet": "梯度下降沿负梯度方向更新参数。",
            }

    monkeypatch.setattr(knowledge_api, "run_db_op", fake_run_db_op)
    monkeypatch.setattr(knowledge_api, "UPLOAD_DIR", Path(tmp_path))
    monkeypatch.setattr(knowledge_api, "audited_legacy_text_call", fake_text_call)
    monkeypatch.setattr(knowledge_api, "_extract_resource_structure", fake_structure)
    monkeypatch.setattr(knowledge_api, "build_swarm_from_headers", lambda headers: SimpleNamespace(llm=object()))
    monkeypatch.setattr(knowledge_api, "_index_canonical_chunks", lambda *args, **kwargs: [])

    result = asyncio.run(knowledge_api.add_web_source(Request(), __import__("fastapi").BackgroundTasks(), owner))
    assert result["status"] == "success"
    source = session.get(DBSourceDocument, result["source_document_id"])
    assert source is not None and source.processing_status == "ready"
    assert source.source_url == "https://example.com/gradient"
    refs = session.query(DBSourceRef).filter_by(source_document_id=source.id).all()
    assert refs and refs[0].quote


def test_chat_next_core_and_legacy_stream_share_ready_boundary(canonical_session):
    session, owner, _, course = canonical_session
    conversation = DBChatConversation(
        id="noc-chat",
        owner_public_id=owner.public_id,
        course_id=course.id,
        title="统一检索对话",
    )
    session.add(conversation)
    session.flush()
    projections = list_canonical_source_refs(session, course_id=course.id, actor=owner)
    assert [item["source_ref_id"] for item in projections] == ["noc-ref-ready"]
    chat_refs = _context_source_refs(
        session,
        owner,
        conversation,
        [{"course": {"id": course.id}}],
    )
    assert [item["sourceRefId"] for item in chat_refs] == ["noc-ref-ready"]

    next_core = search_persisted_course_documents(
        session,
        course_id=course.id,
        query="梯度下降负梯度",
        actor=owner,
    )
    assert [item["source_ref_id"] for item in next_core["items"]] == ["noc-ref-ready"]
    assert _verified_tutor_sources({"context": {
        "sources": [
            {"source_ref_id": "noc-ref-ready", "quote": "可用引用", "available": True, "processing_status": "ready"},
            {"source_ref_id": "noc-ref-failed", "quote": "失败引用", "available": False, "processing_status": "failed"},
        ],
    }}) == [{"source_ref_id": "noc-ref-ready", "quote": "可用引用", "available": True, "processing_status": "ready"}]


def test_permission_and_attachment_boundaries_are_preserved(canonical_session):
    session, owner, outsider, course = canonical_session
    course.visibility = "private"
    session.commit()
    denied = retrieve_canonical_sources(
        session,
        course_id=course.id,
        query="梯度下降",
        actor=outsider,
    )
    assert denied["items"] == []
    assert denied["low_confidence"] is True

    conversation = DBChatConversation(
        id="noc-attachment-chat",
        owner_public_id=owner.public_id,
        course_id=course.id,
        title="附件边界",
    )
    session.add(conversation)
    session.flush()
    attachment = DBChatAttachment(
        id="noc-attachment",
        conversation_id=conversation.id,
        owner_public_id=owner.public_id,
        filename="question.txt",
        file_format="txt",
        mime_type="text/plain",
        file_size=12,
        source_sha256="a" * 64,
        raw_bytes=b"question text",
        parsed_text="question text",
        parser_version="edumatrix-text-v1",
        status="ready",
        stage="ready",
        progress=1.0,
        parse_version=1,
        idempotency_key="noc-attachment-key",
    )
    session.add(attachment)
    session.commit()
    assert session.query(DBSourceDocument).filter_by(legacy_document_id=attachment.id).count() == 0
    assert session.query(DBKnowledgeDocument).filter_by(id=attachment.id).count() == 0


def test_embedding_and_pdf_visual_configuration_are_not_replaced():
    import config
    import embedding_models

    assert hasattr(config.CONFIG, "embedding_provider")
    assert hasattr(config.CONFIG, "multimodal_llm_model")
    assert hasattr(embedding_models, "EMBEDDINGS")
    assert callable(knowledge_api.parse_pdf_visually)
