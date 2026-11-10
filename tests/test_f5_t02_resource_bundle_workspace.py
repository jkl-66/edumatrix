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
        full_rule = '核对每个例子的计算、图表和适用条件。' * 40 + '最后独立解释一次参数变化。'
        payload['items'][0]['completion_rule'] = full_rule
        response = client.post("/api/v1/resource-bundles/generation-jobs", headers=headers, json=payload)
        assert response.status_code == 201, response.text
        result = response.json()
        assert result['items'][0]['completion_rule'] == full_rule
        from app.m5_api import ResourceCompletionRequest
        assert ResourceCompletionRequest(idempotency_key='full-completion-rule',
            resource_version_id='example-version', completion_rule=full_rule).completion_rule == full_rule
        context = result["context"]
        assert {key: context[key] for key in (
            "course_title", "knowledge_point_title", "learning_goal", "recent_learning_summary", "source_count",
        )} == {
            "course_title": "机器学习资源协议课程",
            "knowledge_point_title": "梯度下降",
            "learning_goal": payload["learning_goal"],
            "recent_learning_summary": "近期有 1 条与此知识点相关的有效学习记录。",
            "source_count": 1,
        }
        assert "42%" in context["mastery_summary"]
        assert "梯度下降" in context["profile_adaptation"]
        assert context["profile_adaptation_plan"]["point_mastery"] == 0.42
        assert context["profile_adaptation_plan"]["difficulty_band"] == "foundation"
        assert context["profile_context"] == context["profile_adaptation_plan"]
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
    template = workspace.split("<template>", 1)[1].rsplit("</template>", 1)[0]
    for forbidden in ("锁版本", "内容哈希", "冻结合成画像", "原工作台", "resource_version_id"):
        assert forbidden not in template
    assert "retryGenerationItem" in workspace
    assert "recoverGenerationJob" in workspace
    assert "离开页面不会丢失进度" not in template
    assert "重新核对" in template
    assert "openResourceGenerationChat(task)" in path
    assert "path: '/chat'" in path
    assert "intent: 'path_bundle'" in path
    assert "source_ref_ids: sourceRefIds.length" in path
    assert "learning_goal:" in path
    assert "router.push" in path


def test_teaching_revision_route_keeps_owner_and_request_identity():
    from app.resource_bundles import execute_generation_job_demo
    with TestClient(app) as client:
        owner_headers = auth_headers(client, 'teaching_revision_owner')
        other_headers = auth_headers(client, 'teaching_revision_other')
        seed = _seed('teaching_revision_owner', 'revision-route')
        created = client.post('/api/v1/resource-bundles/generation-jobs', headers=owner_headers,
            json=_payload(seed, 'teaching-revision-route-original'))
        assert created.status_code == 201
        task_id = created.json()['job_id']
        with SessionLocal() as db:
            execute_generation_job_demo(db, _user(db, 'teaching_revision_owner'), task_id)
            db.commit()
        request = {'feedback': '先看数据表，再比较结果。', 'resource_types': ['handout'],
                   'idempotency_key': 'teaching-revision-route-one'}
        url = f'/api/v1/resource-bundles/generation-jobs/{task_id}/revise'
        assert client.post(url, headers=other_headers, json=request).status_code == 403
        response = client.post(url, headers=owner_headers, json=request)
        assert response.status_code == 200, response.text
        assert response.json()['job_id'] == task_id
        assert response.json()['planner']['status'] == 'pending'
        again = client.post(url, headers=owner_headers, json=request)
        assert again.status_code == 200
        assert [item['attempt'] for item in again.json()['items']] == [item['attempt'] for item in response.json()['items']]
        assert client.post(url, headers=owner_headers, json={**request, 'feedback': '不同内容'}).status_code == 409
