"""Current readable course material works without legacy vector-index files."""
import hashlib
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

from app import database, m5_api, m8_preflight
from app.auth import get_current_user
from app.canonical_retrieval import canonical_sources_available, retrieve_canonical_sources
from app.database import DBCourseDocument, DBSourceDocument, DBSourceRef, DBTutorContextSession, DBUser
from app.main import app
from tests.test_m5_api import _catalog_session


@pytest.fixture
def catalog():
    db = _catalog_session()
    body = '# 模型验证\n训练集拟合模型，验证集选择参数，测试集用于最终评估。'
    digest = hashlib.sha256(body.encode()).hexdigest()
    for suffix in ('public', 'member'):
        source = db.get(DBSourceDocument, 'src-'+suffix)
        source.legacy_document_id = 'doc-'+suffix
        source.content_hash = source.processed_sha256 = digest
        db.add(DBCourseDocument(id='doc-'+suffix, course_id=suffix+'-course',
            filename='reading.md', chapter_order=1, content=body, content_hash=digest))
        db.add(DBSourceRef(id='ref-'+suffix, source_document_id=source.id,
            chapter_id='chapter-'+suffix, location_kind='chapter', parser_version=source.parser_version,
            char_start=0, char_end=len(body), quote=body, content_hash=digest))
    db.commit()
    yield db
    engine = db.get_bind()
    db.close()
    engine.dispose()


def test_readiness_matches_canonical_content_and_access_without_faiss(catalog, monkeypatch, tmp_path):
    db = catalog
    actor = DBUser(public_id='other', username='other', role='student', is_active=True)
    monkeypatch.setattr(database, 'SessionLocal', lambda: nullcontext(db))
    monkeypatch.setattr(m5_api, 'ROOT', tmp_path)
    assert m5_api.runtime_availability().retrieval
    assert canonical_sources_available(db, course_id='public-course', actor=actor)
    assert retrieve_canonical_sources(db, course_id='public-course', actor=actor,
        query='验证集选择参数')['items']
    assert not canonical_sources_available(db, course_id='member-course', actor=actor)
    assert not canonical_sources_available(db, course_id='hidden-course', actor=actor)
    source = db.get(DBSourceDocument, 'src-public')
    source.parser_metadata = {'replaced_by_source_id':'not-imported-yet'}
    db.flush()
    assert not canonical_sources_available(db, course_id='public-course', actor=actor)
    source.parser_metadata = {}
    source.processing_status = 'failed'
    db.flush()
    assert not canonical_sources_available(db, course_id='public-course', actor=actor)
    source.processing_status = 'ready'
    db.get(DBCourseDocument, 'doc-public').content = ' '
    db.flush()
    assert not canonical_sources_available(db, course_id='public-course', actor=actor)
    db.get(DBSourceDocument, 'src-member').processing_status = 'failed'
    db.flush()
    # A stale file alone does not make any readable current source available.
    folder = tmp_path/'data/faiss_indexes'
    folder.mkdir(parents=True)
    (folder/'stale.faiss').write_bytes(b'old-unused-index')
    assert not m5_api.runtime_availability().retrieval


def test_course_tutor_preflight_uses_its_own_readable_material(catalog, monkeypatch):
    db = catalog
    actor = DBUser(public_id='owner', username='owner', role='student', is_active=True)
    row = DBTutorContextSession(owner_public_id='owner', course_id='public-course',
        idempotency_key='canonical-readiness-test', context_mode='current_course',
        primary_object_type='chapter', primary_object_id='chapter-public', context_snapshot={})
    db.add(row)
    db.commit()
    async def run(operation):
        return operation(db)
    monkeypatch.setattr(m5_api, 'run_db_op', run)
    monkeypatch.setattr(database, 'SessionLocal', lambda: nullcontext(db))
    app.dependency_overrides[get_current_user] = lambda: actor
    try:
        client = TestClient(app)
        url = f'/api/v1/m5/tutor-contexts/{row.id}/preflight'
        ready = client.post(url, json={'question':'如何选择验证集？'})
        assert ready.status_code == 200
        assert ready.json()['ready'], ready.json()
        assert ready.json()['generation_started'] is False
        db.get(DBSourceDocument, 'src-public').processing_status = 'failed'
        db.commit()
        assert m5_api.runtime_availability().retrieval  # member-course still readable
        missing = client.post(url, json={'question':'如何选择验证集？'})
        assert missing.status_code == 200
        assert missing.json()['blockers'] == ['retrieval_unavailable']
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_preflight_reports_canonical_backend_and_separate_legacy_index(catalog, monkeypatch, tmp_path):
    db = catalog
    monkeypatch.setattr(database, 'SessionLocal', lambda: nullcontext(db))
    monkeypatch.setattr(m8_preflight, 'ROOT', tmp_path)
    retrieval = m8_preflight.deployment_preflight()['checks']['retrieval']
    assert retrieval['available']
    assert retrieval['backend'] == 'canonical'
    assert retrieval['faiss_available'] is False
