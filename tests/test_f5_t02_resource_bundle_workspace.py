from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.database import DBLearningEvent, DBProfileSnapshot, DBTaskEvent, SessionLocal
from app.main import app
from tests.api_test_helpers import auth_headers
from tests.test_f2_resource_generation_protocol import _payload, _seed, _user


ROOT = Path(__file__).resolve().parents[1]


def test_generation_job_freezes_student_safe_context_and_hides_event_ids():
    with TestClient(app) as client:
        headers = auth_headers(client, "f5_t02_context_owner")
        seed = _seed("f5_t02_context_owner", "f5-context")
        with SessionLocal() as db:
            profile = db.get(DBProfileSnapshot, seed["profile_snapshot_id"])
            profile.snapshot = {
                **profile.snapshot,
                "concept_mastery": {seed["knowledge_point_id"]: 0.42},
                "weak_points": ["梯度下降"],
            }
            event = DBLearningEvent(
                owner_public_id=seed["owner_public_id"],
                legacy_student_id="f5_t02_context_owner",
                course_id=seed["course_id"],
                event_type="quiz.submitted",
                source="test",
                trace_id="f5-t02-context-trace",
                object_type="knowledge_point",
                object_id=seed["knowledge_point_id"],
                action="submit",
                context_ref={"knowledgePointId": seed["knowledge_point_id"]},
                evidence_strength=0.8,
                evidence_status="accepted",
                evidence_reason="测试证据",
                mastery_eligible=True,
                completion_effect="progress",
                payload={"knowledge_point_id": seed["knowledge_point_id"]},
            )
            db.add(event)
            db.commit()
            event_id = event.id

        payload = _payload(seed, "f5-t02-context-0001")
        payload["learning_goal"] = "理解梯度下降，并能解释学习率对收敛的影响。"
        response = client.post("/api/v1/resource-bundles/generation-jobs", headers=headers, json=payload)
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["context"] == {
            "course_title": "机器学习资源协议课程",
            "knowledge_point_title": "梯度下降",
            "learning_goal": payload["learning_goal"],
            "profile_adaptation": "偏好图文与实操；重点巩固梯度下降",
            "mastery_summary": "画像记录的当前掌握度约为 42%，当前仍需重点巩固。",
            "recent_learning_summary": "近期有 1 条与此知识点相关的有效学习记录。",
            "source_count": 1,
        }
        assert "recent_event_ids" not in result["context"]
        assert len(result["items"]) == 9
        assert all(item["title"] and item["completion_rule"] for item in result["items"])

        with SessionLocal() as db:
            requested = db.query(DBTaskEvent).filter_by(
                task_id=result["job_id"], event_type="resource_generation.requested",
            ).one()
            context = requested.payload["manifest"]["context"]
            assert context["recent_event_ids"] == [event_id]
            assert context["learning_goal"] == payload["learning_goal"]

        replay = client.post("/api/v1/resource-bundles/generation-jobs", headers=headers, json=payload)
        assert replay.status_code == 201
        assert replay.json()["created"] is False
        assert replay.json()["job_id"] == result["job_id"]

        changed_goal = {**payload, "learning_goal": "另一个学习目标"}
        conflict = client.post("/api/v1/resource-bundles/generation-jobs", headers=headers, json=changed_goal)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "resource_generation.idempotency_conflict"


def test_generation_context_ignores_non_evidence_browsing_events():
    with TestClient(app) as client:
        headers = auth_headers(client, "f5_t02_browse_owner")
        seed = _seed("f5_t02_browse_owner", "f5-browse")
        with SessionLocal() as db:
            db.add(DBLearningEvent(
                owner_public_id=seed["owner_public_id"],
                legacy_student_id="f5_t02_browse_owner",
                course_id=seed["course_id"],
                event_type="resource.viewed",
                source="test",
                trace_id="f5-t02-browse-trace",
                object_type="knowledge_point",
                object_id=seed["knowledge_point_id"],
                action="view",
                context_ref={"knowledgePointId": seed["knowledge_point_id"]},
                evidence_strength=0.0,
                evidence_status="none",
                evidence_reason="普通浏览",
                mastery_eligible=False,
                completion_effect="none",
                payload={"knowledge_point_id": seed["knowledge_point_id"]},
            ))
            db.commit()
        response = client.post(
            "/api/v1/resource-bundles/generation-jobs",
            headers=headers,
            json=_payload(seed, "f5-t02-browse-0001"),
        )
        assert response.status_code == 201, response.text
        assert response.json()["context"]["recent_learning_summary"] == "近期没有与此知识点直接相关的学习记录。"


def test_student_workspace_contract_uses_nine_items_and_no_engineering_metadata():
    workspace = (ROOT / "frontend/src/views/ResourceBundleWorkspace.vue").read_text(encoding="utf-8")
    path = (ROOT / "frontend/src/views/LearningPathGraph.vue").read_text(encoding="utf-8")
    for label in (
        "个性化讲义", "思维导图", "测验题资源", "实训任务书", "代码沙盒任务",
        "视频推荐", "PPT / 网页课件", "可交互模型", "费曼复述任务",
    ):
        assert label in workspace
    for forbidden in ("锁版本", "内容哈希", "冻结合成画像", "原工作台", "resource_version_id"):
        assert forbidden not in workspace
    assert "retryGenerationItem" in workspace
    assert "recoverGenerationJob" in workspace
    assert "离开页面不会丢失进度" in workspace
    assert "name: 'ResourceBundle'" in path
    assert "learning_goal:" in path
    assert "router.push" in path
