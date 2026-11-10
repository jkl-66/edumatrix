from __future__ import annotations

from copy import deepcopy
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base, DBChapter, DBSourceRef
from course_catalog import CURATED_COURSE_MANIFESTS, load_versioned_course_bundle, upsert_course_bundle


def test_primary_ai_diagnostic_has_body_evidence_for_evaluation_and_recurrent_networks():
    from types import SimpleNamespace
    from app.database import DBCourse, DBKnowledgePoint
    from app.diagnostic_generation import _generation_scope
    from course_catalog import MASTER_COURSE_ID

    bundle = load_versioned_course_bundle(CURATED_COURSE_MANIFESTS[3])
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        upsert_course_bundle(session, bundle)
        scope = _generation_scope(session, course=session.get(DBCourse, MASTER_COURSE_ID),
            profile=SimpleNamespace(snapshot={}), question_count=15, stage_id='learning-foundations')
        assert not scope['missingEvidencePointIds']
        points = {p.code: p.id for p in session.query(DBKnowledgePoint).all()}
        evidence = {point: source for source in scope['sources'] for point in source['knowledgePointIds']}
        evaluation = evidence[points['AI-KP-05-02']]['knowledgePointQuotes'][points['AI-KP-05-02']]
        assert 'D2L' in evidence[points['AI-KP-05-02']]['title']
        assert points['AI-KP-02-04'] not in evidence
        neural = _generation_scope(session, course=session.get(DBCourse, MASTER_COURSE_ID),
            profile=SimpleNamespace(snapshot={}), question_count=15, stage_id='neural-training')
        assert not neural['missingEvidencePointIds']
        neural_evidence = {point: source for source in neural['sources'] for point in source['knowledgePointIds']}
        assert '验证' in evaluation and '测试' in evaluation and '交叉验证' in evaluation
        # The current course splits the old broad sequence topic into four
        # independently sourced teaching units. Require all four, not its
        # retained historical parent identity.
        for code in ('AI-KP-09-01', 'AI-KP-09-02', 'AI-KP-09-03', 'AI-KP-09-04'):
            assert neural_evidence[points[code]]['knowledgePointQuotes'][points[code]]
        recurrent = neural_evidence[points['AI-KP-09-02']]
        assert '案例与实践' not in recurrent['title']
        recurrent_text = recurrent['knowledgePointQuotes'][points['AI-KP-09-02']]
        assert '隐藏状态' in recurrent_text or '隐状态' in recurrent_text
    engine.dispose()


def test_course_upsert_reuses_legacy_chapter_key_and_keeps_source_ref_idempotent():
    bundle = load_versioned_course_bundle(CURATED_COURSE_MANIFESTS[0])
    # This exercises migration from a legacy-only catalog. Other API tests
    # already seed current chapters in the shared database, which is a
    # different starting state and must not change this migration scenario.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        legacy_bundle = deepcopy(bundle)
        for item in legacy_bundle["documents"]:
            item.pop("chapter_key", None)

        upsert_course_bundle(session, legacy_bundle)
        legacy_chapter_ids = {
            item["id"]: session.query(DBChapter).filter_by(
                course_id=bundle["course"]["id"],
                stable_key=f"document:{item['id']}",
            ).one().id
            for item in bundle["documents"]
        }

        upsert_course_bundle(session, bundle)
        assert session.query(DBChapter).filter_by(course_id=bundle["course"]["id"]).count() == len(bundle["documents"])
        assert all(
            session.query(DBChapter).filter_by(
                course_id=bundle["course"]["id"],
                stable_key=item["chapter_key"],
            ).one().id == legacy_chapter_ids[item["id"]]
            for item in bundle["documents"]
        )
        assert session.query(DBSourceRef).join(
            DBChapter, DBChapter.id == DBSourceRef.chapter_id
        ).filter(DBChapter.course_id == bundle["course"]["id"]).count() == len(bundle["documents"])

        before_ids = {
            ref.chapter_id: ref.id
            for ref in session.query(DBSourceRef).join(
                DBChapter, DBChapter.id == DBSourceRef.chapter_id
            ).filter(DBChapter.course_id == bundle["course"]["id"])
        }
        upsert_course_bundle(session, bundle)
        after_ids = {
            ref.chapter_id: ref.id
            for ref in session.query(DBSourceRef).join(
                DBChapter, DBChapter.id == DBSourceRef.chapter_id
            ).filter(DBChapter.course_id == bundle["course"]["id"])
        }
        assert after_ids == before_ids
    finally:
        session.close()
        engine.dispose()
