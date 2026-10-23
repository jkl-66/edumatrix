from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import (
    Base,
    DBChapter,
    DBCourse,
    DBCourseDocument,
    DBCourseMembership,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.main import app
import app.next_core_api as next_core_api


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            DBCourse(
                id="public-ml",
                version="1",
                title="Public ML",
                visibility="public",
                status="published",
                manifest_version="1",
            ),
            DBCourse(
                id="private-ml",
                version="1",
                title="Private ML",
                visibility="private",
                status="published",
                manifest_version="1",
            ),
        ]
    )
    documents = {
        "preparation": "Handle missing values, encode categorical features, and standardize numeric features before model training.",
        "tree": "A decision tree recursively splits samples to reduce impurity.",
    }
    for order, (key, content) in enumerate(documents.items(), 1):
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        document_id = f"doc-{key}"
        source_id = f"src-{key}"
        chapter_id = f"chapter-{key}"
        session.add(
            DBCourseDocument(
                id=document_id,
                course_id="public-ml",
                chapter_order=order,
                filename=f"{key}.md",
                file_type="md",
                title=key,
                content=content,
                content_hash=digest,
                status="published",
            )
        )
        session.add(
            DBSourceDocument(
                id=source_id,
                course_id="public-ml",
                legacy_document_id=document_id,
                title=key,
                filename=f"{key}.md",
                file_format="md",
                content_hash=digest,
                parser_version="test-v1",
            )
        )
        session.add(
            DBChapter(
                id=chapter_id,
                course_id="public-ml",
                source_document_id=source_id,
                stable_key=key,
                title=key,
                position=order,
                char_start=0,
                char_end=len(content),
            )
        )
        session.add(
            DBSourceRef(
                id=f"ref-{key}",
                source_document_id=source_id,
                chapter_id=chapter_id,
                parser_version="test-v1",
                char_start=0,
                char_end=len(content),
                content_hash=digest,
            )
        )
    session.commit()
    return session


def test_cross_language_api_uses_persisted_body_and_returns_locatable_evidence(monkeypatch):
    session = _session()

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(next_core_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: DBUser(
        public_id="learner", username="learner", role="student", is_active=True
    )
    client = TestClient(app)
    try:
        response = client.get(
            "/api/v1/next/core/courses/public-ml/cross-language-search",
            params={"q": "训练前为什么要处理缺失值、类别变量和数值尺度", "top_k": 2},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["strategy"] == "hybrid-glossary-v1"
        assert payload["metadata_excluded"] is True
        assert payload["low_confidence"] is False
        assert payload["items"][0]["document_id"] == "doc-preparation"
        assert payload["items"][0]["locatable"] is True
        assert payload["items"][0]["source_ref_id"] == "ref-preparation"
        assert payload["items"][0]["evidence_id"]
        assert payload["fusion"]["tfidf_weight"] == 2.0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()


def test_cross_language_api_rejects_unrelated_private_course(monkeypatch):
    session = _session()

    async def fake_run_db_op(operation):
        return operation(session)

    monkeypatch.setattr(next_core_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: DBUser(
        public_id="learner", username="learner", role="student", is_active=True
    )
    client = TestClient(app)
    try:
        response = client.get(
            "/api/v1/next/core/courses/private-ml/cross-language-search",
            params={"q": "缺失值处理"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        session.close()


def test_tfidf_single_document_and_empty_vocabulary_fail_closed():
    from app.cross_language_retrieval import expand_ml_query, tfidf_document_scores

    expansion = expand_ml_query("缺失值处理")
    assert tfidf_document_scores(expansion, {"one": "missing values"})["one"] > 0
    assert tfidf_document_scores(expansion, {"one": "123", "two": "456"}) == {
        "one": 0.0,
        "two": 0.0,
    }

