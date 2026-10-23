from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database import (
    DBAssessmentAttempt,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBLearningEvent,
    DBUser,
    DBVideoPracticeAttemptLink,
    DBVideoPracticeLabLink,
    DBVideoPracticeVersion,
    SessionLocal,
)
from app.main import app
from app.m1_object_service import OBJECT_SPECS
from app.m5_assessment_core import AttemptInput, persist_code_grading, record_attempt
from tests.api_test_helpers import auth_headers
from tests.test_fc1_chapter_videos import _fixture as chapter_fixture


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _video(client: TestClient, headers: dict[str, str], username: str):
    fixture = chapter_fixture(username)
    response = client.post("/api/v1/chapter-videos", headers=headers, json={
        "course_id": fixture["course_id"], "chapter_id": fixture["chapter_id"],
    })
    assert response.status_code == 201, response.text
    return fixture, response.json()


def _question(fixture: dict[str, str], username: str, *, owner_username: str | None = None,
              question_type: str = "single_choice",
              status: str = "approved", current: bool = True, course_id: str | None = None,
              source_ref_ids: list[str] | None = None, knowledge_point_id: str | None = "__fixture__"):
    suffix = _sha(f"{username}:{question_type}:{status}:{current}:{course_id}")[:18]
    with SessionLocal() as db:
        user = db.query(DBUser).filter_by(username=owner_username or username).one()
        question = DBAssessmentQuestion(
            id=f"aq-fc1-006-{suffix}", course_id=course_id or fixture["course_id"],
            owner_public_id=user.public_id, question_type=question_type,
            origin="manual", status=status,
        )
        db.add(question)
        db.flush()
        if question_type == "code":
            answer_key = {
                "entrypoint": "double", "hidden_tests": [
                    {"args": [2], "expected": 4}, {"args": [-1], "expected": -2},
                ],
            }
            scoring_rule = {"version": "hidden-tests-fc1-v1", "correct_threshold": 1.0}
            options = []
            prompt = "编写 double(value) 返回输入的两倍。"
        else:
            answer_key = {"choice": "B"}
            scoring_rule = {"version": "objective-fc1-v1", "type": "exact"}
            options = ["A. 增加模型体积", "B. 降低数值精度并验证精度损失"]
            prompt = "关于模型量化，哪一项符合课程来源？"
        version = DBAssessmentQuestionVersion(
            id=f"aqv-fc1-006-{suffix}", question_id=question.id, version_number=1,
            prompt=prompt, options=options, answer_key=answer_key,
            scoring_rule=scoring_rule, explanation="依据冻结课程摘录判断。",
            misconception_tags=["concept_confusion"],
            primary_knowledge_point_id=(fixture["knowledge_point_id"] if knowledge_point_id == "__fixture__" else knowledge_point_id),
            secondary_knowledge_point_ids=[], bloom_level="apply", expert_difficulty=0.45,
            measured_difficulty=None, irt_parameters={"alpha": 1.0, "beta": 0.0, "gamma": 0.25},
            sample_size=0,
            source_ref_ids=source_ref_ids if source_ref_ids is not None else [fixture["source_ref_id"]],
            content_hash=_sha(f"question:{suffix}"), created_by_public_id=user.public_id,
        )
        db.add(version)
        db.flush()
        question.current_version_id = version.id if current else "aqv-non-current-placeholder"
        db.commit()
        return {"question_id": question.id, "version_id": version.id}


def _bind(client: TestClient, headers: dict[str, str], video_id: str, question_ids=None, lab_ids=None,
          lock_version=0):
    return client.put(f"/api/v1/video-practices/{video_id}/bindings", headers=headers, json={
        "question_version_ids": question_ids or [], "lab_instance_ids": lab_ids or [],
        "expected_lock_version": lock_version,
    })


def _lab_params():
    return {"decision_threshold": 0.55, "abstain_margin": 0.1, "calibration_bins": 12}


def _lab_action(client, headers, instance, action, key):
    response = client.post(
        f"/api/v1/interactive-lab/instances/{instance['instance_id']}/actions",
        headers=headers,
        json={"action": action, "parameters": None,
              "expected_version": instance["version_number"], "idempotency_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_watch_is_weak_objective_attempt_is_strong_and_refresh_recovers():
    username = "fc1_006_objective_owner"
    with TestClient(app) as client:
        owner = auth_headers(client, username)
        fixture, video = _video(client, owner, username)
        question = _question(fixture, username)

        context = client.get(f"/api/v1/video-practices/context/{video['id']}", headers=owner)
        assert context.status_code == 200, context.text
        assert [item["id"] for item in context.json()["questions"]] == [question["version_id"]]

        bound = _bind(client, owner, video["id"], [question["version_id"]])
        assert bound.status_code == 200, bound.text
        state = bound.json()
        assert state["binding_created"] is True
        assert state["practice_version"]["version_number"] == 1
        assert state["questions"][0]["question_type"] == "single_choice"
        assert "answer_key" not in state["questions"][0]
        assert state["ability"]["response_count"] == 0

        watched = client.put(f"/api/v1/video-practices/{video['id']}/watch-progress", headers=owner, json={
            "watched_seconds": 29, "duration_seconds": 29, "completed": True,
            "expected_lock_version": 0,
        })
        assert watched.status_code == 200, watched.text
        assert watched.json()["watch"] == {
            "watched_seconds": 29.0, "duration_seconds": 29.0, "completed": True,
            "lock_version": 1, "evidence_strength": "weak", "mastery_updated": False,
        }
        assert watched.json()["ability"]["response_count"] == 0

        submitted = client.post(f"/api/v1/video-practices/{video['id']}/attempts", headers=owner, json={
            "question_version_id": question["version_id"],
            "idempotency_key": "fc1-006-objective-attempt-001",
            "mode": "practice", "answer": {"choice": "B"},
            "confidence": 0.8, "duration_seconds": 12,
        })
        assert submitted.status_code == 201, submitted.text
        result = submitted.json()
        assert result["created"] is True
        assert result["ability_before"]["response_count"] == 0
        assert result["ability_after"]["response_count"] == 1
        assert result["evidence_link"]["grading"]["grader_type"] == "deterministic"
        assert result["evidence_link"]["grading"]["score"] == 1
        assert result["evidence_link"]["evidence"]["evidence_strength"] == "strong"
        assert result["evidence_link"]["evidence"]["mastery_updated_by"] == "assessment_core"
        assert result["evidence_link"]["next_action"] == "proceed"

        replay = client.post(f"/api/v1/video-practices/{video['id']}/attempts", headers=owner, json={
            "question_version_id": question["version_id"],
            "idempotency_key": "fc1-006-objective-attempt-001",
            "mode": "practice", "answer": {"choice": "B"},
            "confidence": 0.8, "duration_seconds": 12,
        })
        assert replay.status_code == 201
        assert replay.json()["created"] is False
        assert replay.json()["ability_after"]["response_count"] == 1
        assert replay.json()["evidence_link"]["id"] == result["evidence_link"]["id"]

        restored = client.get(f"/api/v1/video-practices/{video['id']}", headers=owner)
        assert restored.status_code == 200
        assert restored.json()["watch"]["completed"] is True
        assert restored.json()["ability"]["response_count"] == 1
        assert len(restored.json()["attempt_links"]) == 1
        assert restored.json()["attempt_links"][0]["learning_event"]["event_type"] == "video.practice.assessment.completed"

    with SessionLocal() as db:
        watch_event = db.query(DBLearningEvent).filter_by(
            object_id=video["id"], event_type="video.watch.completed",
        ).one()
        assert watch_event.payload["evidence_strength"] == "weak"
        assert watch_event.payload["mastery_updated"] is False


def test_binding_validation_optimistic_conflict_and_owner_boundary():
    username = "fc1_006_binding_owner"
    with TestClient(app) as client:
        owner = auth_headers(client, username)
        outsider = auth_headers(client, "fc1_006_binding_outsider")
        fixture, video = _video(client, owner, username)
        valid = _question(fixture, username)
        draft = _question(fixture, username + "-draft", owner_username=username, status="draft")
        non_current = _question(fixture, username + "-old", owner_username=username, current=False)
        no_source = _question(fixture, username + "-source", owner_username=username, source_ref_ids=["ref-unrelated"])
        no_point = _question(fixture, username + "-point", owner_username=username, knowledge_point_id=None,
                             source_ref_ids=[fixture["source_ref_id"]])
        cases = [
            (draft, "video_practice.question_not_approved"),
            (non_current, "video_practice.question_not_current"),
            (no_source, "video_practice.question_source_mismatch"),
            (no_point, "video_practice.question_knowledge_mismatch"),
        ]
        for row, code in cases:
            response = _bind(client, owner, video["id"], [row["version_id"]])
            assert response.status_code == 422, response.text
            assert response.json()["detail"]["code"] == code

        first = _bind(client, owner, video["id"], [valid["version_id"]])
        assert first.status_code == 200
        replay = _bind(client, owner, video["id"], [valid["version_id"]], lock_version=1)
        assert replay.status_code == 200 and replay.json()["binding_created"] is False
        stale = _bind(client, owner, video["id"], [valid["version_id"]], lock_version=0)
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "video_practice.version_conflict"
        assert client.get(f"/api/v1/video-practices/{video['id']}", headers=outsider).status_code == 403
        assert _bind(client, outsider, video["id"], [valid["version_id"]]).status_code == 403

        first_watch = client.put(f"/api/v1/video-practices/{video['id']}/watch-progress", headers=owner, json={
            "watched_seconds": 5, "duration_seconds": 29, "completed": False,
            "expected_lock_version": 0,
        })
        assert first_watch.status_code == 200
        stale_watch = client.put(f"/api/v1/video-practices/{video['id']}/watch-progress", headers=owner, json={
            "watched_seconds": 10, "duration_seconds": 29, "completed": False,
            "expected_lock_version": 0,
        })
        assert stale_watch.status_code == 409


def test_code_grading_and_passed_lab_form_strong_backlinks_only_after_acceptance():
    username = "fc1_006_code_lab_owner"
    with TestClient(app) as client:
        owner = auth_headers(client, username)
        fixture, video = _video(client, owner, username)
        code_question = _question(fixture, username, question_type="code")
        lab = client.post("/api/v1/interactive-lab/instances", headers=owner, json={
            "template_id": "classifier-threshold-calibration", "title": "视频后阈值校准实验",
            "parameters": _lab_params(), "linked_media_resource_id": None,
            "idempotency_key": "fc1-006-lab-create-001",
        })
        assert lab.status_code == 201, lab.text
        lab_state = lab.json()
        bound = _bind(client, owner, video["id"], [code_question["version_id"]], [lab_state["instance_id"]])
        assert bound.status_code == 200, bound.text

        direct = client.post(f"/api/v1/video-practices/{video['id']}/attempts", headers=owner, json={
            "question_version_id": code_question["version_id"], "idempotency_key": "fc1-006-code-direct",
            "mode": "practice", "answer": {"code": "def double(value): return value * 2"},
        })
        assert direct.status_code == 422
        assert direct.json()["detail"]["code"] == "video_practice.external_grading_required"

        with SessionLocal() as db:
            user = db.query(DBUser).filter_by(username=username).one()
            attempt, _ = record_attempt(db, owner_public_id=user.public_id, attempt=AttemptInput(
                question_version_id=code_question["version_id"], idempotency_key="fc1-006-code-canonical",
                answer={"code": "def double(value): return value * 2"},
            ))
            attempt_id = attempt.id
            db.commit()
        ungraded = client.post(f"/api/v1/video-practices/{video['id']}/attempt-links", headers=owner,
                               json={"attempt_id": attempt_id})
        assert ungraded.status_code == 422
        assert ungraded.json()["detail"]["code"] == "video_practice.grading_incomplete"

        with SessionLocal() as db:
            persist_code_grading(db, attempt_id=attempt_id, result={
                "score": 1.0, "correct": True, "confidence": 1.0,
                "criterion_results": [{"criterion_id": "hidden_tests", "score": 1.0,
                                       "evidence": ["隐藏测试通过 2/2"], "justification": "冻结测试通过", "improvement": ""}],
                "evidence": {"suite_hash": _sha("fc1-006-suite"), "test_scope": "hidden",
                             "passed_count": 2, "total_count": 2, "hidden_inputs_included": False,
                             "hidden_expected_included": False},
                "feedback": "隐藏测试通过 2/2。", "improvement_advice": [],
            }, trace_id="trace-fc1-006-code")
            db.commit()
        code_link = client.post(f"/api/v1/video-practices/{video['id']}/attempt-links", headers=owner,
                                json={"attempt_id": attempt_id})
        assert code_link.status_code == 201, code_link.text
        assert code_link.json()["grading"]["grader_type"] == "code"
        assert code_link.json()["evidence"]["evidence_strength"] == "strong"

        premature = client.post(f"/api/v1/video-practices/{video['id']}/lab-links", headers=owner,
                                json={"lab_instance_id": lab_state["instance_id"]})
        assert premature.status_code == 422
        assert premature.json()["detail"]["code"] == "video_practice.lab_not_passed"
        evaluated = _lab_action(client, owner, lab_state, "run", "fc1-006-lab-run")
        passed = _lab_action(client, owner, evaluated, "submit", "fc1-006-lab-submit")
        assert passed["status"] == "passed" and passed["hidden_acceptance"]["passed"] is True
        lab_link = client.post(f"/api/v1/video-practices/{video['id']}/lab-links", headers=owner,
                               json={"lab_instance_id": lab_state["instance_id"]})
        assert lab_link.status_code == 201, lab_link.text
        assert lab_link.json()["evidence"]["hidden_acceptance_passed"] is True
        replay = client.post(f"/api/v1/video-practices/{video['id']}/lab-links", headers=owner,
                             json={"lab_instance_id": lab_state["instance_id"]})
        assert replay.status_code == 201
        assert replay.json()["id"] == lab_link.json()["id"]


def test_video_practice_evidence_tables_are_immutable_and_registered():
    username = "fc1_006_immutable_owner"
    with TestClient(app) as client:
        owner = auth_headers(client, username)
        fixture, video = _video(client, owner, username)
        question = _question(fixture, username)
        assert _bind(client, owner, video["id"], [question["version_id"]]).status_code == 200
        submitted = client.post(f"/api/v1/video-practices/{video['id']}/attempts", headers=owner, json={
            "question_version_id": question["version_id"], "idempotency_key": "fc1-006-immutable-attempt",
            "mode": "practice", "answer": {"choice": "A"},
        })
        assert submitted.status_code == 201, submitted.text

    with SessionLocal() as db:
        version = db.query(DBVideoPracticeVersion).filter_by(id=submitted.json()["evidence_link"]["practice_version_id"]).one()
        attempt_link = db.query(DBVideoPracticeAttemptLink).filter_by(id=submitted.json()["evidence_link"]["id"]).one()
        with pytest.raises(DatabaseError, match="immutable"):
            db.execute(text("UPDATE video_practice_versions SET content_hash='tampered' WHERE id=:id"), {"id": version.id})
            db.commit()
        db.rollback()
        with pytest.raises(DatabaseError, match="immutable"):
            db.execute(text("DELETE FROM video_practice_attempt_links WHERE id=:id"), {"id": attempt_link.id})
            db.commit()
        db.rollback()
    assert {"video_practice_set", "video_practice_version", "video_watch_progress",
            "video_practice_attempt_link", "video_practice_lab_link"} <= set(OBJECT_SPECS)
