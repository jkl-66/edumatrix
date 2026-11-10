from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DatabaseError

from app.crud import load_student_profile
from app.database import DBFlashcard, DBFlashcardVersion, DBLearningEvent, DBQuizRecord, DBReviewPlan, DBUser, SessionLocal
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
            "explanation": "先用一个生活化的最小例子解释核心关系，再验证理解。",
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
    _seed_completion(student_id, concept)


def _seed_completion(student_id: str, concept: str) -> None:
    with SessionLocal() as db:
        owner = db.query(DBUser).filter_by(username=student_id).one()
        db.add(DBLearningEvent(
            owner_public_id=owner.public_id, legacy_student_id=student_id,
            event_type="quiz_answered", trace_id=f"fc3-complete-{student_id}",
            object_type="knowledge_point", object_id=concept,
            evidence_status="accepted", evidence_strength=1.0,
            mastery_eligible=True, completion_effect="complete",
            payload={"concept": concept, "score": 0.8},
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


def test_difficult_flashcard_explanation_survives_reload_and_preserves_old_version(monkeypatch):
    contexts = []
    async def explain(*args, **kwargs):
        contexts.append(kwargs.get("card_context"))
        return {"triggered": True, "simplified_explanation": "先用一个小例子理解梯度下降，再自己判断下一步方向。", "mermaid": "mindmap\n  root((梯度下降))\n    方向"}
    monkeypatch.setattr(flashcard_api, "build_review_adaptation_payload", explain)
    with TestClient(app) as client:
        name = "fc3_difficult_restore"
        headers = auth_headers(client, name)
        student_id = _student_id(name)
        _seed_plan(student_id)
        card = client.get("/api/flashcard/all", headers=headers, params={"student_id": student_id}).json()["cards"][0]
        response = client.post("/api/flashcard/review", headers=headers, json={"student_id": student_id, "concept": card["concept"], "card_id": card["id"], "quality": 2})
        assert response.status_code == 200, response.text
        current = response.json()["flashcard"]
        assert contexts == [{"question": card["front"], "answer": card["back"]}]
        assert current["version_id"] != card["version_id"]
        assert current["front"] == card["front"]
        assert current["back"] == current["adaptive_review"]["simplified_explanation"]
        restored = client.get("/api/flashcard/all", headers=headers, params={"student_id": student_id}).json()["cards"][0]
        assert restored["adaptive_review"] == current["adaptive_review"]
        assert restored["version_id"] == current["version_id"]
        with SessionLocal() as db:
            assert db.get(DBFlashcardVersion, card["version_id"]).back == card["back"]


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

        _seed_completion(student_id, "学习率稳定性")
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
            "explanation_generated": True,
        }
        assert "真实模型生成的课程回答" in card["back"]

        recovered = client.get("/api/flashcard/all", headers=headers, params={"student_id": student_id})
        assert recovered.status_code == 200
        same = next(item for item in recovered.json()["cards"] if item["id"] == card["id"])
        assert same["version_id"] == card["version_id"]
        assert same["back"] == card["back"]


def test_legacy_review_model_failure_does_not_write_learning_feedback(monkeypatch):
    username = "fc3_review_generation_failure"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        student_id = _student_id(username)
        _seed_plan(student_id)
        with SessionLocal() as db:
            owner_id = db.query(DBUser).filter_by(username=username).one().public_id
            events_before = db.query(DBLearningEvent).filter_by(owner_public_id=owner_id).count()

        async def fail_answer(**kwargs):
            raise flashcard_api.ReviewModelError("model_unavailable", "模型不可用")

        monkeypatch.setattr(flashcard_api, "_generate_flashcard_answer", fail_answer)
        response = client.post("/api/flashcard/review", headers=headers, json={
            "student_id": student_id, "concept": "梯度下降", "quality": 4,
        })
        assert response.status_code == 502, response.text
        assert response.json()["detail"]["code"] == "model_unavailable"
        with SessionLocal() as db:
            plan = db.query(DBReviewPlan).filter_by(student_id=student_id, concept="梯度下降").one()
            assert plan.review_count == 0
            assert plan.mastery == 0.3
            assert db.query(DBFlashcard).filter_by(owner_public_id=owner_id).count() == 0
            assert db.query(DBLearningEvent).filter_by(owner_public_id=owner_id).count() == events_before
def test_flashcard_keeps_short_exact_answer_with_substantial_explanation(monkeypatch):
    import asyncio
    async def generated(**kwargs):
        assert "降维解释" not in kwargs["system_prompt"] + kwargs["user_prompt"]
        parsed = kwargs["response_validator"]('{"answer":"B：9和80.8","explanation":"先过滤缺失的第二条记录，后面的索引会前移，再计算第三条有效数据的分数。"}')
        return parsed, "deepseek-v4-flash", "openai"
    monkeypatch.setattr(flashcard_api, "generate_review_model_json", generated)
    answer, _ = asyncio.run(flashcard_api._generate_flashcard_answer(concept="列表索引", owner_public_id="owner"))
    assert "B：9和80.8" in answer and "索引会前移" in answer



def test_new_flashcard_failure_keeps_existing_cards_and_can_retry(monkeypatch):
    username = "fc3_partial_generation"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        student = _student_id(username)
        _seed_plan(student, "已准备的知识点")
        original = client.get("/api/flashcard/all", headers=headers, params={"student_id": student}).json()["cards"][0]
        _seed_plan(student, "新知识点")
        real_generate = flashcard_api._generate_flashcard_answer

        async def fail_answer(**kwargs):
            raise flashcard_api.ReviewModelError("model_unavailable", "模型不可用")

        monkeypatch.setattr(flashcard_api, "_generate_flashcard_answer", fail_answer)
        partial = client.get("/api/flashcard/all", headers=headers, params={"student_id": student})
        assert partial.status_code == 200
        assert [card["id"] for card in partial.json()["cards"]] == [original["id"]]
        assert partial.json()["failures"][0]["concept"] == "新知识点"
        assert partial.json()["failures"][0]["retryable"] is True
        monkeypatch.setattr(flashcard_api, "_generate_flashcard_answer", real_generate)
        recovered = client.get("/api/flashcard/all", headers=headers, params={"student_id": student}).json()
        assert recovered["failures"] == []
        assert recovered["total"] == 2
        assert next(card for card in recovered["cards"] if card["id"] == original["id"])["version_id"] == original["version_id"]


def test_flashcard_regeneration_retains_prior_version_and_uses_checked_answer(monkeypatch):
    from types import SimpleNamespace
    import asyncio
    operations=[]
    async def model(**kwargs):
        operations.append(kwargs["operation"])
        value={"answer":"9和80.8", "explanation":"按过滤后的索引取值，对应原始第四条记录，39.8加41等于80.8。"}
        if kwargs["operation"]=="review_flashcard_answer":
            value["explanation"]="待核对的例子中可能存在下标错误，需要独立计算。"
        return value,"deepseek-v4-flash","openai"
    monkeypatch.setattr(flashcard_api,"generate_review_model_json",model)
    record=SimpleNamespace(question="过滤后第3项？",options=[],correct_answer="80.8",student_answer="76.2",feedback="过滤后重新编号",accuracy_score=0)
    result,_=asyncio.run(flashcard_api._generate_flashcard_answer(concept="索引",owner_public_id="test",record=record))
    assert operations==["review_flashcard_answer","review_flashcard_check"]
    assert "待核对" not in result and "39.8加41" in result
    with TestClient(app) as client:
        username="fc3_regenerate"
        headers=auth_headers(client,username)
        student=_student_id(username);_seed_plan(student)
        with SessionLocal() as db:
            owner=db.query(DBUser).filter_by(username=username).one()
            plan=db.query(DBReviewPlan).filter_by(student_id=student).one()
            card,old=flashcard_api._ensure_card(db,owner_public_id=owner.public_id,student_id=student,concept=plan.concept,review_plan=plan,generated_answer="第一份讲解")
            db.commit();old_id=old.id
            updated,new=flashcard_api._ensure_card(db,owner_public_id=owner.public_id,student_id=student,concept=plan.concept,review_plan=plan,generated_answer=result,regenerate=True)
            db.commit()
            assert updated.id==card.id and new.version_number==2
            assert db.get(DBFlashcardVersion,old_id).back=="第一份讲解"

def test_plan_feedback_updates_the_selected_course_when_topic_names_match():
    username = 'flashcard-plan-course-check'
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        _student_id(username)
        with SessionLocal() as db:
            plans = [DBReviewPlan(student_id=username, concept='共享参数', course_id=cid, mastery=.5, review_count=0)
                     for cid in ['course-a', 'course-b']]
            db.add_all(plans); db.commit()
            first_id, second_id = [p.id for p in plans]
        for pid in [first_id, second_id]:
            response = client.post('/api/flashcard/review', headers=headers,
                                   json={'student_id':username,'concept':'共享参数','quality':4,'plan_id':pid})
            assert response.status_code == 200, response.text
            assert response.json()['review_plan']['id'] == pid
        with SessionLocal() as db:
            assert db.get(DBReviewPlan, first_id).review_count == 1
            assert db.get(DBReviewPlan, second_id).review_count == 1
            assert db.query(DBFlashcard).filter_by(student_id=username).count() == 2
