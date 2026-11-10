from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import course_catalog
from app.database import Base, DBChapter, DBCourse, DBCourseDocument, DBKnowledgePoint, DBSourceDocument, DBSourceRef
from course_catalog import (
    CURATED_COURSE_MANIFESTS,
    CourseManifestConflict,
    CourseUpdateApprovalRequired,
    apply_course_bundle_update,
    load_versioned_course_bundle,
    preflight_course_bundle_update,
    seed_default_courses,
    upsert_course_bundle,
)
from scripts.preflight_course_update import inspect_course_update


COURSE_ID = "course-machine-learning-foundations-v1"
VERSION_1 = "course-ml-foundations-1.0.0"
VERSION_2 = "course-ml-foundations-1.1.0"


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    value = factory()
    try:
        yield value
    finally:
        value.close()
        engine.dispose()


def _bundle():
    return load_versioned_course_bundle(CURATED_COURSE_MANIFESTS[0])


def _version_2(bundle):
    updated = deepcopy(bundle)
    updated["course"]["version"] = VERSION_2
    updated["course"]["manifest_version"] = VERSION_2
    updated["course"]["title"] = "机器学习基础与实践（修订版）"
    updated["course"]["manifest_data"]["manifest_version"] = VERSION_2
    updated["course"]["manifest_data"]["title"] = "机器学习基础与实践（修订版）"
    return updated


def test_course_preflight_is_read_only_and_idempotent(session):
    bundle = _bundle()

    first = preflight_course_bundle_update(session, bundle)
    second = preflight_course_bundle_update(session, bundle)

    assert first == second
    assert first["status"] == "new_course"
    assert first["requires_approval"] is False
    assert session.query(DBCourse).count() == 0
    assert session.query(DBCourseDocument).count() == 0

    upsert_course_bundle(session, bundle)
    replay = preflight_course_bundle_update(session, bundle)
    assert replay["status"] == "unchanged"
    assert replay["current_manifest_sha256"] == replay["incoming_manifest_sha256"]


def test_same_version_manifest_change_fails_before_database_mutation(session):
    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    original_title = session.get(DBCourse, COURSE_ID).title
    original_hashes = [
        row.content_hash
        for row in session.query(DBCourseDocument)
        .filter_by(course_id=COURSE_ID)
        .order_by(DBCourseDocument.chapter_order)
        .all()
    ]
    conflict = deepcopy(bundle)
    conflict["course"]["title"] = "同版本静默替换"
    conflict["course"]["manifest_data"]["title"] = "同版本静默替换"

    report = preflight_course_bundle_update(session, conflict)
    assert report["status"] == "same_version_conflict"
    assert report["requires_approval"] is True
    assert report["diff"]["metadata_changed"] is True
    with pytest.raises(CourseManifestConflict) as raised:
        upsert_course_bundle(session, conflict)
    assert raised.value.report == report
    assert session.get(DBCourse, COURSE_ID).title == original_title
    assert [
        row.content_hash
        for row in session.query(DBCourseDocument)
        .filter_by(course_id=COURSE_ID)
        .order_by(DBCourseDocument.chapter_order)
        .all()
    ] == original_hashes


def test_version_change_requires_compare_and_set_approval(session):
    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    updated = _version_2(bundle)

    report = preflight_course_bundle_update(session, updated)
    assert report["status"] == "update_available"
    assert report["current_version"] == VERSION_1
    assert report["incoming_version"] == VERSION_2
    assert report["diff"]["metadata_changed"] is True
    with pytest.raises(CourseUpdateApprovalRequired):
        upsert_course_bundle(session, updated)
    assert session.get(DBCourse, COURSE_ID).version == VERSION_1

    with pytest.raises(ValueError, match="approval_expectation_mismatch"):
        apply_course_bundle_update(
            session,
            updated,
            expected_current_version="wrong-current-version",
            expected_incoming_version=VERSION_2,
        )
    assert session.get(DBCourse, COURSE_ID).version == VERSION_1

    result = apply_course_bundle_update(
        session,
        updated,
        expected_current_version=VERSION_1,
        expected_incoming_version=VERSION_2,
    )
    assert result == {"inserted": 0, "updated": 12, "removed": 0}
    assert session.get(DBCourse, COURSE_ID).version == VERSION_2
    assert session.get(DBCourse, COURSE_ID).title == "机器学习基础与实践（修订版）"
    assert preflight_course_bundle_update(session, updated)["status"] == "unchanged"


def test_preflight_reports_file_provenance_order_and_knowledge_differences(session):
    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    updated = _version_2(bundle)
    manifest = updated["course"]["manifest_data"]
    manifest["files"][0]["sha256"] = "1" * 64
    manifest["files"][0]["source_sha256"] = "2" * 64
    manifest["files"][0]["git_revision"] = "3" * 40
    manifest["files"][0]["chapter_order"] = 1
    manifest["files"][1]["chapter_order"] = 0
    manifest["files"][0]["knowledge_point_codes"] = ["ML-KP-01", "ML-KP-02"]
    manifest["knowledge_points"][0]["title"] = "Python 编程基础（修订）"

    report = preflight_course_bundle_update(session, updated)

    first_path = manifest["files"][0]["path"]
    assert first_path in report["diff"]["content_changed"]
    assert first_path in report["diff"]["provenance_changed"]
    assert first_path in report["diff"]["reordered_files"]
    assert first_path in report["diff"]["knowledge_mapping_changed"]
    assert report["diff"]["knowledge_points_changed"] is True


def test_startup_reports_update_available_without_database_or_rag_overwrite(session, monkeypatch):
    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    updated = _version_2(bundle)
    original_title = session.get(DBCourse, COURSE_ID).title
    ingested: list[str] = []

    monkeypatch.setattr(course_catalog, "load_versioned_course_bundle", lambda _path: updated)
    monkeypatch.setattr(
        course_catalog,
        "ingest_course_bundle",
        lambda candidate: ingested.append(candidate["course"]["id"]) or 0,
    )

    result = seed_default_courses(session)

    course_result = next(item for item in result["courses"] if item["course_id"] == COURSE_ID)
    assert course_result["status"] == "update_available"
    assert course_result["preflight"]["current_version"] == VERSION_1
    assert course_result["preflight"]["incoming_version"] == VERSION_2
    assert COURSE_ID not in ingested
    assert session.get(DBCourse, COURSE_ID).version == VERSION_1
    assert session.get(DBCourse, COURSE_ID).title == original_title


def test_cli_inspection_helper_does_not_write(session):
    _bundle_value, report = inspect_course_update(session, CURATED_COURSE_MANIFESTS[0])

    assert report["status"] == "new_course"
    assert session.query(DBCourse).count() == 0
    assert session.query(DBCourseDocument).count() == 0


def _confirm_split_structure(session, bundle):
    from types import SimpleNamespace
    from app.course_structure import (read_course_structure, save_course_structure,
        confirm_course_structure, StructureSave, StructureConfirm)

    actor = SimpleNamespace(role='admin', public_id='synthetic-catalog-admin')
    state = read_course_structure(session, actor, COURSE_ID)
    first = state['structure']['chapters'][0]
    middle = (first['char_start'] + first['char_end']) // 2
    second = {**first, 'key': first['key'] + '-continuation', 'title': '继续完成实践', 'char_start': middle}
    first.update(title='从具体问题进入', char_end=middle)
    state['structure']['chapters'].insert(1, second)
    point_id = first['knowledge_point_ids'][0]
    next(p for p in state['structure']['concepts'] if p['id'] == point_id)['title'] = '已确认的具体学习概念'
    state['structure']['units'] = [{'key': 'confirmed-unit', 'title': '已确认单元',
        'goal': '解释数据并独立检查结论', 'knowledge_point_ids': [point_id]}]
    saved = save_course_structure(session, actor, COURSE_ID, StructureSave(**{
        key: state[key] for key in ('revision', 'source_fingerprint', 'structure')}))
    confirm_course_structure(session, actor, COURSE_ID, StructureConfirm(revision=saved['revision']))
    return actor, point_id


def test_restart_and_metadata_update_preserve_confirmed_structure_and_history(session):
    from app.course_structure import read_course_structure
    from app.source_refs import source_ref_teaching_text

    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    old_refs = {ref.id: source_ref_teaching_text(session, ref, max_chars=None)
                for ref in session.query(DBSourceRef)}
    actor, point_id = _confirm_split_structure(session, bundle)
    course = session.get(DBCourse, COURSE_ID)
    workspace = deepcopy(course.manifest_data['structure_workspace'])
    chapters = {ch.id: (ch.stable_key, ch.title, ch.char_start, ch.char_end)
                for ch in session.query(DBChapter)}
    current = read_course_structure(session, actor, COURSE_ID)
    assert not current['needs_confirmation']

    preflight = preflight_course_bundle_update(session, bundle)
    assert preflight['status'] == 'unchanged'
    assert not preflight['diff']['metadata_changed']
    upsert_course_bundle(session, bundle)
    updated = _version_2(bundle)
    apply_course_bundle_update(session, updated, expected_current_version=VERSION_1,
                               expected_incoming_version=VERSION_2)
    assert session.get(DBCourse, COURSE_ID).manifest_data['structure_workspace'] == workspace
    assert {ch.id: (ch.stable_key, ch.title, ch.char_start, ch.char_end)
            for ch in session.query(DBChapter)} == chapters
    assert session.get(DBKnowledgePoint, point_id).title == '已确认的具体学习概念'
    assert read_course_structure(session, actor, COURSE_ID)['structure'] == current['structure']
    assert not read_course_structure(session, actor, COURSE_ID)['needs_confirmation']
    assert {rid: source_ref_teaching_text(session, session.get(DBSourceRef, rid), max_chars=None)
            for rid in old_refs} == old_refs


def test_removing_bundle_source_keeps_confirmed_history_and_readable_original(session):
    from app.source_refs import current_source_clause, source_ref_teaching_text

    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    _confirm_split_structure(session, bundle)
    removed = bundle['documents'][0]
    source = session.query(DBSourceDocument).filter_by(legacy_document_id=removed['id']).one()
    refs = {ref.id: source_ref_teaching_text(session, ref, max_chars=None)
            for ref in session.query(DBSourceRef).filter_by(source_document_id=source.id)}
    updated = _version_2(bundle)
    updated['documents'] = updated['documents'][1:]
    updated['course']['manifest_data']['files'] = updated['course']['manifest_data']['files'][1:]
    apply_course_bundle_update(session, updated, expected_current_version=VERSION_1,
                               expected_incoming_version=VERSION_2)
    assert session.get(DBCourseDocument, removed['id']).content == removed['content']
    assert source.id not in {s.id for s in session.query(DBSourceDocument).filter(current_source_clause())}
    assert {rid: source_ref_teaching_text(session, session.get(DBSourceRef, rid), max_chars=None)
            for rid in refs} == refs


def test_bundle_sync_keeps_unrelated_uploaded_material(session):
    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    session.add(DBCourseDocument(id='teacher-extra', course_id=COURSE_ID, title='教师补充',
        filename='extra.md', chapter_order=99, file_type='md', content='课程中的个人补充资料', content_hash='extra'))
    session.flush()
    session.add(DBSourceDocument(id='teacher-source', course_id=COURSE_ID, legacy_document_id='teacher-extra',
        title='教师补充', filename='extra.md', file_format='md', content_hash='extra', processing_status='ready',
        parser_metadata={'origin': 'user_upload'}))
    session.commit()
    upsert_course_bundle(session, bundle)
    assert session.get(DBCourseDocument, 'teacher-extra').content == '课程中的个人补充资料'
    assert session.get(DBSourceDocument, 'teacher-source').processing_status == 'ready'


@pytest.mark.parametrize('autoflush', [True, False])
def test_source_erratum_keeps_frozen_body_and_rebases_confirmed_sections(session, autoflush):
    import hashlib
    from app.course_structure import read_course_structure
    from app.source_refs import current_source_clause, project_source_ref, source_ref_teaching_text

    session.autoflush = autoflush
    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    actor, _ = _confirm_split_structure(session, bundle)
    before = read_course_structure(session, actor, COURSE_ID)
    first = bundle['documents'][0]
    old_source = session.query(DBSourceDocument).filter_by(legacy_document_id=first['id']).one()
    old_content = session.get(DBCourseDocument, first['id']).content
    refs = {ref.id: (source_ref_teaching_text(session, ref, max_chars=None),
                    project_source_ref(session, ref.id))
            for ref in session.query(DBSourceRef).filter_by(source_document_id=old_source.id)}
    updated = _version_2(bundle)
    corrected = updated['documents'][0]
    insertion = '\n教学勘误：依据公式核对术语。\n'
    corrected['content'] = old_content[:50] + insertion + old_content[50:]
    corrected['content_hash'] = hashlib.sha256(corrected['content'].encode()).hexdigest()
    corrected['parser_version'] += '-corrected'
    updated['course']['manifest_data']['files'][0]['sha256'] = corrected['content_hash']
    apply_course_bundle_update(session, updated, expected_current_version=VERSION_1,
                               expected_incoming_version=VERSION_2)
    new_source = session.query(DBSourceDocument).filter_by(legacy_document_id=first['id']).one()
    assert old_source.id != new_source.id
    assert old_source.parser_metadata['replaced_by_source_id'] == new_source.id
    assert new_source.parser_metadata['previous_source_id'] == old_source.id
    assert session.get(DBCourseDocument, old_source.legacy_document_id).content == old_content
    assert old_source.id not in {s.id for s in session.query(DBSourceDocument).filter(current_source_clause())}
    assert corrected['canonical_source_document_id'] == new_source.id
    from app.m5_source_locator import resolve_course_evidence_location
    from document_parser import chunk_document
    evidence = chunk_document(corrected['content'], source=COURSE_ID+'/'+corrected['filename'])[0]
    located_document, location = resolve_course_evidence_location(session,
        source_ref=session.get(DBSourceRef, corrected['canonical_source_ref_id']), evidence_id=evidence.id)
    assert located_document.id == first['id'] and location.char_end > location.char_start
    for rid, (text, frozen) in refs.items():
        assert text and source_ref_teaching_text(session, session.get(DBSourceRef, rid), max_chars=None) == text
        assert project_source_ref(session, rid, frozen=frozen)['available']
    after = read_course_structure(session, actor, COURSE_ID)
    assert not after['issues'] and not after['needs_confirmation']
    old_sections = [ch for ch in before['structure']['chapters'] if ch['source_document_id'] == old_source.id]
    new_sections = [ch for ch in after['structure']['chapters'] if ch['source_document_id'] == new_source.id]
    assert len(old_sections) == len(new_sections) == 2
    for old, new in zip(old_sections, new_sections):
        assert old['title'] == new['title'] and old['knowledge_point_ids'] == new['knowledge_point_ids']
        assert new['char_start'] == old['char_start'] + (len(insertion) if old['char_start'] > 50 else 0)
        assert new['char_end'] == old['char_end'] + len(insertion)
    new_refs = session.query(DBSourceRef).filter_by(source_document_id=new_source.id).all()
    assert all(source_ref_teaching_text(session, ref, max_chars=None) for ref in new_refs)
    assert after['structure']['units'] == before['structure']['units']
    counts = (session.query(DBSourceDocument).count(), session.query(DBSourceRef).count(), session.query(DBChapter).count())
    upsert_course_bundle(session, updated)
    assert counts == (session.query(DBSourceDocument).count(), session.query(DBSourceRef).count(), session.query(DBChapter).count())


def test_source_update_preserves_pending_structure_edits_and_primary_links(session):
    from app.course_structure import read_course_structure, save_course_structure, StructureSave
    bundle = _bundle()
    upsert_course_bundle(session, bundle)
    actor, _ = _confirm_split_structure(session, bundle)
    state = read_course_structure(session, actor, COURSE_ID)
    state['structure']['chapters'][0]['title'] = '尚未确认的教师编辑'
    state['structure']['units'][0]['primary_chapter_keys'] = [state['structure']['chapters'][0]['key']]
    save_course_structure(session, actor, COURSE_ID, StructureSave(**{
        key: state[key] for key in ('revision', 'source_fingerprint', 'structure')}))
    updated = _version_2(bundle)
    updated['documents'][0]['content'] = '新增来源说明\n' + updated['documents'][0]['content']
    apply_course_bundle_update(session, updated, expected_current_version=VERSION_1, expected_incoming_version=VERSION_2)
    after = read_course_structure(session, actor, COURSE_ID)
    assert after['draft_saved'] and not after['stale'] and not after['issues']
    assert after['structure']['chapters'][0]['title'] == '尚未确认的教师编辑'
    assert after['structure']['units'][0]['primary_chapter_keys'] == [after['structure']['chapters'][0]['key']]


def test_errata_positions_cover_insert_delete_replace_and_unicode():
    from app.course_source_updates import revised_text_positions
    before = '标题\n甲😀乙\n保留本段\n末尾'
    after = '新版标题\n甲😀修订乙\n保留本段\n'
    position = revised_text_positions(before, after)
    start = before.index('保留本段')
    end = start + len('保留本段')
    assert after[position(start):position(end, end=True)] == '保留本段'
    assert position(0) == 0
    assert position(len(before), end=True) == len(after)
