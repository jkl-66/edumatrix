from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.database import DBChapter, DBCourse, DBCourseDocument, DBSourceDocument, SessionLocal
from course_catalog import CURATED_COURSE_MANIFESTS, load_versioned_course_bundle, upsert_course_bundle


MANIFEST_PATH = Path("data/curated/embedded_machine_learning_engineering_v2/course_manifest.json")
COURSE_ID = "course-embedded-machine-learning-engineering-v2"


def test_post_data_course_manifest_has_real_multiformat_materials_and_licenses() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    formats = {Path(item["path"]).suffix.lower() for item in manifest["files"]}

    assert manifest["course_id"] == COURSE_ID
    assert len(manifest["knowledge_points"]) == 8
    assert len(manifest["files"]) == 26
    assert formats == {".md", ".pdf", ".docx", ".pptx", ".mp4"}
    assert [item["chapter_order"] for item in manifest["files"]] == list(range(26))
    assert all(item["license_spdx"] == "CC-BY-NC-SA-4.0" for item in manifest["files"])
    assert all(item["git_revision"] == "a3d5f9df06d0b6750d5227eb3e0359e9ffbbe1e6" for item in manifest["files"])
    assert all((MANIFEST_PATH.parent / item["path"]).is_file() for item in manifest["files"])
    assert all(
        hashlib.sha256((MANIFEST_PATH.parent / item["path"]).read_bytes()).hexdigest() == item["sha256"]
        for item in manifest["files"]
    )
    assert sum(bool(item.get("parent_chapter_key")) for item in manifest["files"]) == 17
    assert manifest["external_material_policy"].startswith("No standard-license YouTube")


def test_post_data_course_bundle_uses_prebuilt_pdf_pages_and_video_index_text() -> None:
    bundle = load_versioned_course_bundle(MANIFEST_PATH)
    documents = bundle["documents"]
    pdf = next(item for item in documents if item["file_type"] == "pdf")
    video = next(item for item in documents if item["file_type"] == "mp4")

    assert len(pdf["reader_pages"]) == 28
    assert all(page["regions"] for page in pdf["reader_pages"])
    assert "从数据到设备的完整工程闭环" in pdf["content"]
    assert video["media"]["kind"] == "video"
    assert video["media"]["transcript_status"] == "team_authored_visual_description"
    assert "本地视频为 EduMatrix 团队制作" in video["content"]
    assert video["index_text_path"].endswith("课程导览_转写与画面说明.md")


def test_post_data_course_upsert_is_idempotent_and_keeps_module_material_hierarchy() -> None:
    bundle = load_versioned_course_bundle(CURATED_COURSE_MANIFESTS[2])
    session = SessionLocal()
    try:
        first = upsert_course_bundle(session, bundle)
        second = upsert_course_bundle(session, bundle)

        assert first["inserted"] in {0, 26}
        assert second == {"inserted": 0, "updated": 26, "removed": 0}
        assert session.query(DBCourse).filter_by(id=COURSE_ID).count() == 1
        assert session.query(DBCourseDocument).filter_by(course_id=COURSE_ID).count() == 26
        assert session.query(DBSourceDocument).filter_by(course_id=COURSE_ID).count() == 26
        chapters = session.query(DBChapter).filter_by(course_id=COURSE_ID).all()
        assert len(chapters) == 26
        assert sum(chapter.parent_id is None for chapter in chapters) == 9
        assert sum(chapter.parent_id is not None for chapter in chapters) == 17
        pdf_source = session.query(DBSourceDocument).filter_by(course_id=COURSE_ID, file_format="pdf").one()
        assert len(pdf_source.parser_metadata["ocr"]["pages"]) == 28
        video_source = session.query(DBSourceDocument).filter_by(course_id=COURSE_ID, file_format="mp4").one()
        assert video_source.parser_metadata["media"]["kind"] == "video"
        assert video_source.parser_metadata["index_text_path"].endswith("课程导览_转写与画面说明.md")
    finally:
        session.close()
