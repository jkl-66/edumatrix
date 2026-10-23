from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database import (
    DBQuizRecord,
    DBReviewPlan,
    DBWrongQuestion,
    DBWrongQuestionVideoLink,
    SessionLocal,
)
from app.main import app
from app.m1_object_service import OBJECT_SPECS
from tests.api_test_helpers import auth_headers


def _fixture(username: str) -> int:
    with SessionLocal() as db:
        quiz = DBQuizRecord(
            id=f"fc-wrong-video-{username}",
            student_id=username,
            question="边缘设备部署前为什么需要模型量化？",
            student_answer="量化会让模型更准确",
            correct_answer="量化主要降低模型体积与推理资源开销，并需验证精度损失。",
            accuracy_score=0.2,
            target_concept="边缘模型量化",
            feedback="混淆了部署效率与预测精度。",
            next_action="review",
            attempt_number=1,
        )
        db.add(quiz)
        db.flush()
        wrong = DBWrongQuestion(
            student_id=username,
            quiz_record_id=quiz.id,
            concept_name="边缘模型量化",
            wrong_reason_category="concept_confusion",
        )
        plan = DBReviewPlan(
            student_id=username,
            concept="边缘模型量化",
            interval_days=2,
            mastery=0.25,
            review_count=1,
        )
        db.add_all([wrong, plan])
        db.commit()
        return wrong.id


def test_generate_idempotent_script_backlink_and_owner_boundary():
    username = "fc_wrong_video_owner"
    with TestClient(app) as client:
        owner = auth_headers(client, username)
        outsider = auth_headers(client, "fc_wrong_video_outsider")
        wrong_id = _fixture(username)
        response = client.post(
            "/api/v1/wrong-question-videos",
            headers=owner,
            json={"student_id": username, "wrong_question_id": wrong_id},
        )
        assert response.status_code == 201, response.text
        row = response.json()
        assert row["idempotent"] is False
        assert row["wrong_question_id"] == wrong_id
        assert row["review_plan_id"] is not None
        assert row["evidence_refs"] == [f"legacy-quiz:fc-wrong-video-{username}"]
        assert "未宣称为可定位课程原文引用" in row["truth_boundary"]
        scenes = row["project"]["script"]["scenes"]
        assert len(scenes) == 5
        narration = "\n".join(item["narration"] for item in scenes)
        assert "边缘设备部署前为什么需要模型量化" in narration
        assert "量化主要降低模型体积" in narration
        assert "concept_confusion" in narration
        assert "当前间隔 2 天" in narration

        duplicate = client.post(
            "/api/v1/wrong-question-videos",
            headers=owner,
            json={"student_id": username, "wrong_question_id": wrong_id},
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] == row["id"]
        assert duplicate.json()["idempotent"] is True
        assert client.get(f"/api/v1/wrong-question-videos/{row['id']}", headers=outsider).status_code == 403
        assert client.post(
            "/api/v1/wrong-question-videos",
            headers=outsider,
            json={"student_id": username, "wrong_question_id": wrong_id},
        ).status_code == 403
        listing = client.get(
            "/api/v1/wrong-question-videos",
            params={"student_id": username, "wrong_question_id": wrong_id},
            headers=owner,
        )
        assert listing.status_code == 200 and len(listing.json()["items"]) == 1


def test_missing_facts_rejected_and_link_is_immutable():
    username = "fc_wrong_video_missing"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        with SessionLocal() as db:
            quiz = DBQuizRecord(
                id=f"fc-wrong-video-{username}", student_id=username,
                question="缺少参考答案的题目", correct_answer="",
                target_concept="不完整题目",
            )
            db.add(quiz); db.flush()
            wrong = DBWrongQuestion(
                student_id=username, quiz_record_id=quiz.id,
                concept_name="不完整题目",
            )
            db.add(wrong); db.commit(); wrong_id = wrong.id
        rejected = client.post(
            "/api/v1/wrong-question-videos", headers=headers,
            json={"student_id": username, "wrong_question_id": wrong_id},
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "wrong_video.required_fact_missing"

    with SessionLocal() as db:
        link = db.query(DBWrongQuestionVideoLink).first()
        assert link is not None
        with pytest.raises(DatabaseError, match="immutable"):
            db.execute(text("UPDATE wrong_question_video_links SET input_hash='tampered' WHERE id=:id"), {"id": link.id})
            db.commit()
        db.rollback()
    assert "wrong_question_video_link" in OBJECT_SPECS
