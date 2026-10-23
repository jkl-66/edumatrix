from __future__ import annotations

from copy import deepcopy

from app.database import DBChapter, DBSourceRef, SessionLocal
from course_catalog import CURATED_COURSE_MANIFESTS, load_versioned_course_bundle, upsert_course_bundle


def test_course_upsert_reuses_legacy_chapter_key_and_keeps_source_ref_idempotent():
    bundle = load_versioned_course_bundle(CURATED_COURSE_MANIFESTS[0])
    session = SessionLocal()
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
