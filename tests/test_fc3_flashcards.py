from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DatabaseError

from app.crud import load_student_profile
from app.database import DBFlashcard, DBFlashcardVersion, DBQuizRecord, DBReviewPlan, SessionLocal
from app.main import app
from app.m1_object_service import OBJECT_SPECS
from tests.api_test_helpers import auth_headers
import llm_client
import flashcard_api


@pytest.fixture(autouse=True)
def configured_review_model(monkeypatch):
    class FakeReviewModel:
        provider = "openai"
        model = "deepseek-v4-flash"
        thinking_mode = "max"
        reasoning_effort = "max"

        async def generate(self, system_prompt, user_prompt, *, role):
            return (
                '{"answer":"真实模型生成的课程回答：先说明核心机制，再给出适用边界和一个最小例子。",'
                '"explanation":"用生活化类比先理解核心关系，再做一个最小练习。",'
                '"mermaid":"mindmap\\n  root((概念))\\n    关系\\n    误区"}'
            )

    fake = FakeReviewModel()
    monkeypatch.setattr(llm_client, "DEFAULT_ASYNC_LLM", fake)

    async def fake_generate_review_model_json(**kwargs):
        return {
            "answer": "真实模型生成的课程回答：先说明核心机制，再给出适用边界和一个最小例子。",
        }, fake.model, fake.provider

    monkeypatch.setattr(flashcard_api, "generate_review_model_json", fake_generate_review_model_json)


def _student_id(username: str) -> str:
    with SessionLocal() as db:
        load_student_profile(db, username)
        db.commit()
    return username


def _seed_plan(student_id: str, concept: str = "梯度下降") -> None:
    with SessionLocal() as db:
        if not db.query(DBReviewPlan).filter_by(student_id=student_id, concept=concept).first():
            db.add(DBReviewPlan(
                student_id=student_id, concept=concept, interval_days=1,
                mastery=0.3, review_count=0, easiness_factor=2.5,
                last_quality=0, priority=1.0,
            ))
            db.commit()


def test_flashcard_is_canonical_idempotent_and_restorable():
    username = "fc3_flashcard_owner"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        student_id = _student_id(username)
        _seed_plan(student_id)

        first = client.get("/api/flashcard/all", headers=headers, params={"student_id": student_id})
        assert first.status_code == 200, first.text
        card = first.json()["cards"][0]
        assert card["id"].startswith("card-")
        assert card["version_id"].startswith("cardv-")
        assert len(card["content_hash"]) == 64
        assert card["source_snapshot"]["source_type"] == "review_plan"

        replay = client.get("/api/flashcard/all", headers=headers, params={"student_id": student_id})
        assert replay.status_code == 200
        restored = replay.json()["cards"][0]
        assert restored["id"] == card["id"]
        assert restored["version_id"] == card["version_id"]
        assert restored["front"] == card["front"]
        assert restored["back"] == card["back"]

        reviewed = client.post("/api/flashcard/review", headers=headers, json={
            "student_id": student_id, "concept": card["concept"],
            "card_id": card["id"], "quality": 4,
        })
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["flashcard"]["version_id"] == card["version_id"]
        assert reviewed.json()["flashcard"]["review_count"] == 1

        legacy = client.post("/api/flashcard/review", headers=headers, json={
            "student_id": student_id, "concept": card["concept"], "quality": 5,
        })
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["flashcard"]["id"] == card["id"]

    assert OBJECT_SPECS["flashcard"].model.__tablename__ == "flashcards"
    assert OBJECT_SPECS["flashcard_version"].model.__tablename__ == "flashcard_versions"
    with SessionLocal() as db:
        row = db.get(DBFlashcard, card["id"])
        assert row is not None and row.lock_version == 1
        assert db.query(DBFlashcardVersion).filter_by(flashcard_id=card["id"]).count() == 1
        version = db.get(DBFlashcardVersion, card["version_id"])
        version.front = "tampered"
        with pytest.raises(DatabaseError, match="immutable"):
            db.commit()
        db.rollback()


def test_flashcard_owner_scope_and_card_concept_conflict():
    owner_name = "fc3_flashcard_boundary_owner"
    outsider_name = "fc3_flashcard_boundary_other"
    with TestClient(app) as client:
        owner = auth_headers(client, owner_name)
        outsider = auth_headers(client, outsider_name)
        student_id = _student_id(owner_name)
        outsider_id = _student_id(outsider_name)
        _seed_plan(student_id, "支持向量机")
        card = client.get("/api/flashcard/all", headers=owner, params={"student_id": student_id}).json()["cards"][0]

        forbidden = client.post("/api/flashcard/review", headers=outsider, json={
            "student_id": outsider_id, "concept": card["concept"],
            "card_id": card["id"], "quality": 4,
        })
        assert forbidden.status_code == 403

        conflict = client.post("/api/flashcard/review", headers=owner, json={
            "student_id": student_id, "concept": "错误概念",
            "card_id": card["id"], "quality": 4,
        })
        assert conflict.status_code == 409


def test_quiz_flashcard_freezes_recorded_answer_snapshot_and_recovers():
    username = "fc3_flashcard_quiz_owner"
    quiz_id = "fc3-flashcard-quiz-record"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        student_id = _student_id(username)
        with SessionLocal() as db:
            db.add(DBQuizRecord(
                id=quiz_id, student_id=student_id, question="学习率过大有什么风险？",
                student_answer="一定更快收敛", correct_answer="可能越过最优点并震荡",
                accuracy_score=0.2, target_concept="学习率稳定性",
            ))
            db.commit()

        created = client.post("/api/flashcard/generate", headers=headers, json={
            "student_id": student_id, "quiz_id": quiz_id,
        })
        assert created.status_code == 200, created.text
        card = created.json()["flashcard"]
        assert card["source_quiz_id"] == quiz_id
        assert card["source_snapshot"] == {
            "source_type": "quiz_record", "quiz_record_id": quiz_id,
            "concept": "学习率稳定性", "accuracy": 0.2,
            "truth_boundary": "model_generated_review_answer",
            "model": "deepseek-v4-flash", "provider": "openai",
            "thinking": "enabled", "reasoning_effort": "max", "allow_fallback": False,
        }
        assert "真实模型生成的课程回答" in card["back"]

        recovered = client.get("/api/flashcard/all", headers=headers, params={"student_id": student_id})
        assert recovered.status_code == 200
        same = next(item for item in recovered.json()["cards"] if item["id"] == card["id"])
        assert same["version_id"] == card["version_id"]
        assert same["back"] == card["back"]
