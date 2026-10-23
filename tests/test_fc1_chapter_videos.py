from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBChapterVideoLink,
    DBCourse,
    DBKnowledgePoint,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
    SessionLocal,
)
from app.main import app
from app.m1_object_service import OBJECT_SPECS
from tests.api_test_helpers import auth_headers


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fixture(username: str, *, private: bool = False, with_source: bool = True) -> dict[str, str]:
    with SessionLocal() as db:
        user = db.query(DBUser).filter_by(username=username).one()
        suffix = username[-24:]
        course = DBCourse(
            id=f"fc-chapter-course-{suffix}", version="1.0.0",
            title="边缘人工智能实训", subject="人工智能",
            description="用于 FC1 章节视频自动验收的冻结合成课程。",
            domain_pack="edge-ai", language="zh-CN",
            content_origin="frozen_synthetic_test_fixture",
            license_text="测试数据；不对外发布",
            visibility="private" if private else "public", status="published",
            owner_public_id=user.public_id if private else None,
            manifest_version="fc1-test-v1", manifest_data={
                "chapters": [{
                    "stable_key": "quantization",
                    "title": "模型量化与部署",
                    "learning_objectives": ["解释量化对模型体积和推理资源的影响"],
                }],
            },
        )
        db.add(course)
        db.flush()
        document = DBSourceDocument(
            id=f"src-fc-chapter-{suffix}", course_id=course.id,
            title="边缘模型部署讲义", filename="edge-deployment.md", file_format="md",
            content_hash=_sha("document" + suffix), source_sha256=_sha("source" + suffix),
            processed_sha256=_sha("processed" + suffix), file_size=512,
            source_url="https://example.invalid/edge-deployment",
            source_path=f"fixtures/{suffix}/edge-deployment.md",
            license_text="冻结合成教学材料", uploader_public_id=user.public_id,
            parser_version="fc1-test-parser-v1", processing_status="ready",
        )
        db.add(document)
        db.flush()
        chapter = DBChapter(
            id=f"ch-fc-chapter-{suffix}", course_id=course.id,
            source_document_id=document.id, stable_key="quantization",
            title="模型量化与部署", position=1, heading_level=1,
            char_start=0, char_end=180,
        )
        db.add(chapter)
        db.flush()
        point = DBKnowledgePoint(
            id=f"kp-fc-chapter-{suffix}", domain_pack="edge-ai",
            code=f"quant-{suffix}", version="1.0.0", title="模型量化",
            level="core", status="active",
        )
        db.add(point)
        db.flush()
        db.add(DBChapterKnowledgePoint(
            id=f"ckp-fc-chapter-{suffix}", chapter_id=chapter.id,
            knowledge_point_id=point.id, relation_type="teaches",
        ))
        if with_source:
            db.add(DBSourceRef(
                id=f"ref-fc-chapter-{suffix}", source_document_id=document.id,
                chapter_id=chapter.id, parser_version="fc1-test-parser-v1",
                char_start=0, char_end=118, location_kind="section",
                location_index=1, location_label="第 1 章 模型量化与部署",
                location_metadata={"fixture": True}, content_hash=_sha("quote" + suffix),
                quote="模型量化通过降低权重与激活值的数值精度，减少模型体积和推理资源开销；部署前必须验证精度损失。",
            ))
        profile = DBProfileSnapshot(
            id=f"ps-fc-chapter-{suffix}", owner_public_id=user.public_id,
            legacy_student_id=username, profile_version="1",
            snapshot={
                "cognitive_style": "视觉+代码导向",
                "interaction_preferences": ["代码示例", "流程图"],
                "cognitive_load": 0.72,
            },
            content_hash=_sha("profile" + suffix), trace_id=f"trace-fc-chapter-{suffix}",
        )
        db.add(profile)
        db.commit()
        return {
            "course_id": course.id, "chapter_id": chapter.id,
            "source_ref_id": f"ref-fc-chapter-{suffix}",
            "knowledge_point_id": point.id, "profile_id": profile.id,
        }


def test_generate_source_bound_personalized_idempotent_chapter_video():
    username = "fc_chapter_video_owner"
    with TestClient(app) as client:
        owner = auth_headers(client, username)
        outsider = auth_headers(client, "fc_chapter_video_outsider")
        fixture = _fixture(username)

        context = client.get("/api/v1/chapter-videos/context", headers=owner)
        assert context.status_code == 200, context.text
        course = next(item for item in context.json()["courses"] if item["id"] == fixture["course_id"])
        assert course["chapters"] == [{"id": fixture["chapter_id"], "title": "模型量化与部署", "position": 1}]

        generated = client.post("/api/v1/chapter-videos", headers=owner, json={
            "course_id": fixture["course_id"], "chapter_id": fixture["chapter_id"],
            "profile_snapshot_id": fixture["profile_id"],
        })
        assert generated.status_code == 201, generated.text
        row = generated.json()
        assert row["idempotent"] is False
        assert row["source_ref_ids"] == [fixture["source_ref_id"]]
        assert row["knowledge_point_ids"] == [fixture["knowledge_point_id"]]
        assert row["learning_objectives"] == ["解释量化对模型体积和推理资源的影响"]
        assert row["personalization"]["mode"] == "frozen_profile_snapshot"
        assert row["personalization"]["example_density"] == "high"
        assert row["quality"]["source_bound"] is True
        assert row["quality"]["objective_origin"] == "course_manifest"
        assert "画像只调整呈现策略" in row["truth_boundary"]
        scenes = row["project"]["script"]["scenes"]
        assert len(scenes) == 5
        narration = "\n".join(item["narration"] for item in scenes)
        assert "降低权重与激活值的数值精度" in narration
        assert "模型量化" in narration
        assert "事实标准保持一致" in scenes[3]["bullets"]

        duplicate = client.post("/api/v1/chapter-videos", headers=owner, json={
            "course_id": fixture["course_id"], "chapter_id": fixture["chapter_id"],
            "profile_snapshot_id": fixture["profile_id"],
        })
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] == row["id"]
        assert duplicate.json()["idempotent"] is True
        assert client.get(f"/api/v1/chapter-videos/{row['id']}", headers=outsider).status_code == 403


def test_rejects_unbound_video_and_enforces_course_chapter_profile_boundaries():
    owner_name = "fc_chapter_video_boundaries"
    other_name = "fc_chapter_video_other"
    with TestClient(app) as client:
        owner = auth_headers(client, owner_name)
        other = auth_headers(client, other_name)
        missing = _fixture(owner_name, with_source=False)
        other_fixture = _fixture(other_name, private=True)

        no_source = client.post("/api/v1/chapter-videos", headers=owner, json={
            "course_id": missing["course_id"], "chapter_id": missing["chapter_id"],
        })
        assert no_source.status_code == 422
        assert no_source.json()["detail"]["code"] == "chapter_video.source_refs_missing"

        forbidden = client.post("/api/v1/chapter-videos", headers=owner, json={
            "course_id": other_fixture["course_id"], "chapter_id": other_fixture["chapter_id"],
        })
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"]["code"] == "chapter_video.course_forbidden"

        mismatch = client.post("/api/v1/chapter-videos", headers=other, json={
            "course_id": other_fixture["course_id"], "chapter_id": missing["chapter_id"],
        })
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == "chapter_video.chapter_course_mismatch"

        profile_forbidden = client.post("/api/v1/chapter-videos", headers=other, json={
            "course_id": other_fixture["course_id"], "chapter_id": other_fixture["chapter_id"],
            "profile_snapshot_id": missing["profile_id"],
        })
        assert profile_forbidden.status_code == 403
        assert profile_forbidden.json()["detail"]["code"] == "chapter_video.profile_forbidden"


def test_chapter_video_link_is_immutable_and_registered():
    username = "fc_chapter_video_immutable"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        fixture = _fixture(username)
        response = client.post("/api/v1/chapter-videos", headers=headers, json={
            "course_id": fixture["course_id"], "chapter_id": fixture["chapter_id"],
        })
        assert response.status_code == 201, response.text
        link_id = response.json()["id"]

    with SessionLocal() as db:
        row = db.get(DBChapterVideoLink, link_id)
        assert row is not None
        with pytest.raises(DatabaseError, match="immutable"):
            db.execute(text("UPDATE chapter_video_links SET input_hash='tampered' WHERE id=:id"), {"id": link_id})
            db.commit()
        db.rollback()
    assert "chapter_video_link" in OBJECT_SPECS
