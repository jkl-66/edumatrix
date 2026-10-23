from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from config import CONFIG

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseMembership,
    DBLearningEvent,
    DBKnowledgePoint,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBTaskStep,
    DBUser,
    SessionLocal,
)
from app.main import app
from app.m5_capabilities import M5CapabilityError
from app.m5_resources import ResourceVersionCreateRequest, ResourceVersionRestoreRequest
from app.m5_resources import create_resource_version, resource_detail, restore_resource_version
from app.resource_bundles import (
    GENERATION_RESOURCE_TYPES,
    ResourceBundleError,
    complete_generation_item,
    execute_generation_job_demo,
    fail_generation_item,
    mark_generation_item_running,
)
from tests.api_test_helpers import auth_headers


def _user(db, username: str) -> DBUser:
    return db.query(DBUser).filter_by(username=username).one()


def _seed(username: str, suffix: str) -> dict[str, str]:
    with SessionLocal() as db:
        user = _user(db, username)
        course = DBCourse(
            id=f"f2-resource-course-{suffix}",
            version="1",
            title="机器学习资源协议课程",
            subject="人工智能",
            domain_pack="ml",
            visibility="private",
            status="published",
            owner_public_id=user.public_id,
            manifest_version="f2-resource-v1",
            manifest_data={"demo": True},
        )
        source = DBSourceDocument(
            course_id=course.id,
            title="梯度下降课程讲义",
            filename="gradient-descent.md",
            file_format="markdown",
            content_hash="d" * 64,
            source_sha256="d" * 64,
            processed_sha256="e" * 64,
            processing_status="ready",
        )
        point = DBKnowledgePoint(
            domain_pack="ml",
            code=f"f2-resource-gradient-{suffix}",
            version="1",
            title="梯度下降",
        )
        db.add_all([course, source, point])
        db.flush()
        chapter = DBChapter(
            course_id=course.id,
            source_document_id=source.id,
            stable_key=f"gradient-{suffix}",
            title="梯度下降",
            position=1,
            char_start=0,
            char_end=100,
        )
        db.add(chapter)
        db.flush()
        db.add_all([
            DBCourseMembership(
                course_id=course.id,
                user_public_id=user.public_id,
                role="student",
                status="active",
            ),
            DBChapterKnowledgePoint(
                chapter_id=chapter.id,
                knowledge_point_id=point.id,
                relation_type="covers",
            ),
        ])
        source_ref = DBSourceRef(
            source_document_id=source.id,
            chapter_id=chapter.id,
            parser_version="f2-parser-v1",
            location_kind="section",
            location_index=1,
            location_label="梯度下降定义",
            content_hash="f" * 64,
            quote="梯度下降通过负梯度方向迭代优化。",
        )
        snapshot_body = {"goal": "掌握梯度下降", "preference": "图文与实操"}
        profile = DBProfileSnapshot(
            owner_public_id=user.public_id,
            legacy_student_id=username,
            profile_version="1",
            snapshot=snapshot_body,
            content_hash=hashlib.sha256(str(snapshot_body).encode()).hexdigest(),
            trace_id=f"trace-{suffix}",
        )
        db.add_all([source_ref, profile])
        db.commit()
        return {
            "owner_public_id": user.public_id,
            "course_id": course.id,
            "knowledge_point_id": point.id,
            "profile_snapshot_id": profile.id,
            "source_ref_id": source_ref.id,
            "source_document_id": source.id,
        }


def _payload(seed: dict[str, str], key: str) -> dict:
    return {
        "course_id": seed["course_id"],
        "knowledge_point_id": seed["knowledge_point_id"],
        "profile_snapshot_id": seed["profile_snapshot_id"],
        "idempotency_key": key,
        "items": [
            {
                "type": resource_type,
                "title": f"梯度下降 {resource_type}",
                "source_ref_ids": [seed["source_ref_id"]],
                "completion_rule": f"完成 {resource_type} 的学习证据",
            }
            for resource_type in GENERATION_RESOURCE_TYPES
        ],
    }


def test_nine_type_job_idempotency_partial_retry_and_owner_boundary():
    with TestClient(app) as client:
        owner_headers = auth_headers(client, "f2_resource_owner")
        other_headers = auth_headers(client, "f2_resource_other")
        seed = _seed("f2_resource_owner", "flow")
        payload = _payload(seed, "f2-resource-flow-0001")

        created = client.post("/api/v1/resource-bundles/generation-jobs", headers=owner_headers, json=payload)
        assert created.status_code == 201, created.text
        job = created.json()
        assert job["created"] is True
        assert job["status"] == "queued"
        assert [item["type"] for item in job["items"]] == list(GENERATION_RESOURCE_TYPES)
        assert len({item["idempotency_key"] for item in job["items"]}) == 9

        replay = client.post("/api/v1/resource-bundles/generation-jobs", headers=owner_headers, json=payload)
        assert replay.status_code == 201
        assert replay.json()["created"] is False
        assert replay.json()["job_id"] == job["job_id"]

        changed = _payload(seed, "f2-resource-flow-0001")
        changed["items"][0]["title"] = "不同讲义"
        conflict = client.post("/api/v1/resource-bundles/generation-jobs", headers=owner_headers, json=changed)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "resource_generation.idempotency_conflict"

        with SessionLocal() as db:
            owner = _user(db, "f2_resource_owner")
            first = complete_generation_item(
                db,
                owner,
                job["job_id"],
                "handout",
                content="# 梯度下降讲义\n\n这是可追溯讲义。",
            )
            second = fail_generation_item(
                db,
                owner,
                job["job_id"],
                "mind_map",
                error_code="model_capacity",
                error_message="模型暂时不可用",
            )
            db.commit()
        assert first["status"] == "partial_success"
        assert second["status"] == "partial_success"
        handout = next(item for item in second["items"] if item["type"] == "handout")
        failed = next(item for item in second["items"] if item["type"] == "mind_map")
        assert handout["resource"]["status"] == "available"
        assert handout["resource"]["generation_state"] == "succeeded"
        assert handout["resource"]["source_refs"][0]["source_ref_id"] == seed["source_ref_id"]
        assert handout["resource"]["profile_snapshot_id"] == seed["profile_snapshot_id"]
        assert failed["failure"]["code"] == "model_capacity"

        retry = client.post(
            f"/api/v1/resource-bundles/generation-jobs/{job['job_id']}/items/mind_map/retry",
            headers=owner_headers,
        )
        assert retry.status_code == 200, retry.text
        failed = next(item for item in retry.json()["items"] if item["type"] == "mind_map")
        assert failed["state"] == "queued"
        assert failed["attempt"] == 2
        assert len(failed["attempt_history"]) == 2

        detail = client.get(f"/api/v1/m5/resources/{handout['resource']['resource_id']}", headers=owner_headers)
        assert detail.status_code == 200
        assert detail.json()["resource"]["status"] == handout["resource"]["status"]
        assert detail.json()["resource"]["generation_state"] == handout["resource"]["generation_state"]

        forbidden = client.get(
            f"/api/v1/resource-bundles/generation-jobs/{job['job_id']}",
            headers=other_headers,
        )
        assert forbidden.status_code == 403


def test_demo_execution_archives_nine_resources_and_does_not_create_learning_evidence(monkeypatch):
    original_demo_mode = CONFIG.demo_mode
    with TestClient(app) as client:
        try:
            headers = auth_headers(client, "f2_resource_demo_owner")
            seed = _seed("f2_resource_demo_owner", "demo")
            payload = _payload(seed, "f2-resource-demo-0001")

            created = client.post(
                "/api/v1/resource-bundles/generation-jobs",
                headers=headers,
                json=payload,
            )
            assert created.status_code == 201, created.text
            job_id = created.json()["job_id"]

            object.__setattr__(CONFIG, "demo_mode", False)
            disabled = client.post(
                f"/api/v1/resource-bundles/generation-jobs/{job_id}/execute-demo",
                headers=headers,
            )
            assert disabled.status_code == 409
            assert disabled.json()["detail"]["code"] == "resource_generation.demo_disabled"

            with SessionLocal() as db:
                owner = _user(db, "f2_resource_demo_owner")
                learning_events_before = db.query(DBLearningEvent).filter_by(
                    owner_public_id=owner.public_id,
                ).count()
                profile_snapshots_before = db.query(DBProfileSnapshot).filter_by(
                    owner_public_id=owner.public_id,
                ).count()
                complete_generation_item(
                    db,
                    owner,
                    job_id,
                    "handout",
                    content="# 已归档讲义",
                )
                fail_generation_item(
                    db,
                    owner,
                    job_id,
                    "mind_map",
                    error_code="demo_retry",
                    error_message="演示失败项",
                )
                db.commit()

            object.__setattr__(CONFIG, "demo_mode", True)
            retry = client.post(
                f"/api/v1/resource-bundles/generation-jobs/{job_id}/items/mind_map/retry",
                headers=headers,
            )
            assert retry.status_code == 200, retry.text
            assert next(item for item in retry.json()["items"] if item["type"] == "mind_map")["attempt"] == 2

            executed = client.post(
                f"/api/v1/resource-bundles/generation-jobs/{job_id}/execute-demo",
                headers=headers,
            )
            assert executed.status_code == 200, executed.text
            result = executed.json()
            assert result["status"] == "succeeded"
            assert result["progress"] == 1
            assert all(item["state"] == "succeeded" for item in result["items"])
            assert len({item["resource"]["resource_id"] for item in result["items"]}) == 9

            replay = client.post(
                f"/api/v1/resource-bundles/generation-jobs/{job_id}/execute-demo",
                headers=headers,
            )
            assert replay.status_code == 200, replay.text
            assert [item["resource"]["resource_id"] for item in replay.json()["items"]] == [
                item["resource"]["resource_id"] for item in result["items"]
            ]

            with SessionLocal() as db:
                owner = _user(db, "f2_resource_demo_owner")
                assert db.query(DBArtifact).filter_by(
                    owner_public_id=owner.public_id,
                    creating_task_id=job_id,
                ).count() == 9
                assert db.query(DBLearningEvent).filter_by(
                    owner_public_id=owner.public_id,
                ).count() == learning_events_before
                assert db.query(DBProfileSnapshot).filter_by(
                    owner_public_id=owner.public_id,
                ).count() == profile_snapshots_before
        finally:
            object.__setattr__(CONFIG, "demo_mode", original_demo_mode)


def test_single_resource_generation_uses_one_real_step_and_archives_one_resource():
    original_demo_mode = CONFIG.demo_mode
    with TestClient(app) as client:
        try:
            headers = auth_headers(client, "f5_t07_single_resource_owner")
            seed = _seed("f5_t07_single_resource_owner", "single-deck")
            payload = {
                "course_id": seed["course_id"],
                "knowledge_point_id": seed["knowledge_point_id"],
                "profile_snapshot_id": seed["profile_snapshot_id"],
                "idempotency_key": "f5-t07-single-deck-0001",
                "scope": "single",
                "items": [{
                    "type": "deck",
                    "title": "梯度下降自定义课件",
                    "source_ref_ids": [seed["source_ref_id"]],
                    "completion_rule": "完成课件中的今日必做学习动作",
                }],
            }
            created = client.post(
                "/api/v1/resource-bundles/generation-jobs",
                headers=headers,
                json=payload,
            )
            assert created.status_code == 201, created.text
            job = created.json()
            assert job["scope"] == "single"
            assert job["status"] == "queued"
            assert job["progress"] == 0
            assert [item["type"] for item in job["items"]] == ["deck"]

            with SessionLocal() as db:
                owner = _user(db, "f5_t07_single_resource_owner")
                steps = db.query(DBTaskStep).filter_by(task_id=job["job_id"]).all()
                assert len(steps) == 1
                assert steps[0].sequence == GENERATION_RESOURCE_TYPES.index("deck") + 1
                learning_events_before = db.query(DBLearningEvent).filter_by(
                    owner_public_id=owner.public_id,
                ).count()

            object.__setattr__(CONFIG, "demo_mode", True)
            executed = client.post(
                f"/api/v1/resource-bundles/generation-jobs/{job['job_id']}/execute-demo",
                headers=headers,
            )
            assert executed.status_code == 200, executed.text
            result = executed.json()
            assert result["scope"] == "single"
            assert result["status"] == "succeeded"
            assert result["progress"] == 1
            assert len(result["items"]) == 1
            assert result["items"][0]["resource"]["type"] == "deck"

            resource_id = result["items"][0]["resource"]["resource_id"]
            detail = client.get(f"/api/v1/m5/resources/{resource_id}", headers=headers)
            assert detail.status_code == 200, detail.text
            assert detail.json()["deck"]["current"]["mode"] == "structured"

            replay = client.post(
                "/api/v1/resource-bundles/generation-jobs",
                headers=headers,
                json=payload,
            )
            assert replay.status_code == 201, replay.text
            assert replay.json()["created"] is False
            assert replay.json()["job_id"] == job["job_id"]

            with SessionLocal() as db:
                owner = _user(db, "f5_t07_single_resource_owner")
                assert db.query(DBArtifact).filter_by(
                    owner_public_id=owner.public_id,
                    creating_task_id=job["job_id"],
                ).count() == 1
                assert db.query(DBLearningEvent).filter_by(
                    owner_public_id=owner.public_id,
                ).count() == learning_events_before
        finally:
            object.__setattr__(CONFIG, "demo_mode", original_demo_mode)


def test_resource_completion_requires_current_version_and_server_rule_without_mastery():
    with TestClient(app) as client:
        headers = auth_headers(client, "f5_t07_completion_owner")
        seed = _seed("f5_t07_completion_owner", "completion")
        created = client.post(
            "/api/v1/resource-bundles/generation-jobs",
            headers=headers,
            json=_payload(seed, "f5-t07-completion-job-0001"),
        ).json()
        with SessionLocal() as db:
            owner = _user(db, "f5_t07_completion_owner")
            result = complete_generation_item(
                db,
                owner,
                created["job_id"],
                "handout",
                content="# Completion handout",
            )
            db.commit()
            handout = next(item for item in result["items"] if item["type"] == "handout")
            resource_id = handout["resource"]["resource_id"]
            version_id = handout["resource"]["version"]["id"]
            completion_rule = handout["completion_rule"]

        payload = {
            "idempotency_key": "f5-t07-resource-completion-0001",
            "resource_version_id": version_id,
            "completion_rule": completion_rule,
            "actual_minutes": 12,
        }
        completed = client.post(
            f"/api/v1/m5/resources/{resource_id}/complete",
            headers=headers,
            json=payload,
        )
        assert completed.status_code == 201, completed.text
        event = completed.json()
        assert event["created"] is True
        assert event["event_type"] == "user_marked_complete"
        assert event["completion_effect"] == "progress"
        assert event["mastery_eligible"] is False
        assert event["evidence_status"] == "none"
        assert event["payload_summary"]["resource_version_id"] == version_id
        assert event["payload_summary"]["completion_rule"] == completion_rule
        assert event["payload_summary"]["actual_minutes"] == 12

        replay = client.post(
            f"/api/v1/m5/resources/{resource_id}/complete",
            headers=headers,
            json=payload,
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["created"] is False
        assert replay.json()["id"] == event["id"]

        wrong_rule = client.post(
            f"/api/v1/m5/resources/{resource_id}/complete",
            headers=headers,
            json={**payload, "idempotency_key": "f5-t07-resource-completion-0002", "completion_rule": "wrong rule"},
        )
        assert wrong_rule.status_code == 409
        assert wrong_rule.json()["detail"]["code"] == "resource_completion_rule_mismatch"

        with SessionLocal() as db:
            owner = _user(db, "f5_t07_completion_owner")
            artifact = db.get(DBArtifact, resource_id)
            create_resource_version(
                db,
                artifact=artifact,
                actor_public_id=owner.public_id,
                request=ResourceVersionCreateRequest(
                    expected_lock_version=artifact.lock_version,
                    source_version_id=artifact.current_version_id,
                    content="# Completion handout v2",
                ),
            )

        stale = client.post(
            f"/api/v1/m5/resources/{resource_id}/complete",
            headers=headers,
            json={**payload, "idempotency_key": "f5-t07-resource-completion-0003"},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "resource_version_stale"

        with SessionLocal() as db:
            owner = _user(db, "f5_t07_completion_owner")
            rows = db.query(DBLearningEvent).filter_by(
                owner_public_id=owner.public_id,
                event_type="user_marked_complete",
            ).all()
            assert len(rows) == 1
            assert rows[0].mastery_eligible is False
            assert rows[0].completion_effect == "progress"


def test_cancelled_job_rejects_late_failure_and_completed_job_rejects_recovery():
    with TestClient(app) as client:
        headers = auth_headers(client, "f2_resource_state_owner")
        cancelled_seed = _seed("f2_resource_state_owner", "cancelled")
        cancelled = client.post(
            "/api/v1/resource-bundles/generation-jobs",
            headers=headers,
            json=_payload(cancelled_seed, "f2-resource-cancelled-0001"),
        ).json()
        stopped = client.post(
            f"/api/v1/resource-bundles/generation-jobs/{cancelled['job_id']}/cancel",
            headers=headers,
        )
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "cancelled"
        with SessionLocal() as db:
            owner = _user(db, "f2_resource_state_owner")
            with pytest.raises(ResourceBundleError, match="不能标记为失败"):
                fail_generation_item(
                    db,
                    owner,
                    cancelled["job_id"],
                    "handout",
                    error_code="late_callback",
                    error_message="取消后的迟到回调",
                )

        completed_seed = _seed("f2_resource_state_owner", "completed")
        completed = client.post(
            "/api/v1/resource-bundles/generation-jobs",
            headers=headers,
            json=_payload(completed_seed, "f2-resource-completed-0001"),
        ).json()
        with SessionLocal() as db:
            owner = _user(db, "f2_resource_state_owner")
            payload = execute_generation_job_demo(db, owner, completed["job_id"])
            db.commit()
        assert payload["status"] == "succeeded"
        recovery = client.post(
            f"/api/v1/resource-bundles/generation-jobs/{completed['job_id']}/recover",
            headers=headers,
        )
        assert recovery.status_code == 409
        assert recovery.json()["detail"]["code"] == "resource_generation.recovery_conflict"


def test_recovery_only_requeues_interrupted_items_and_preserves_successful_resource():
    with TestClient(app) as client:
        headers = auth_headers(client, "f2_resource_recovery_owner")
        seed = _seed("f2_resource_recovery_owner", "recovery")
        created = client.post(
            "/api/v1/resource-bundles/generation-jobs",
            headers=headers,
            json=_payload(seed, "f2-resource-recovery-0001"),
        ).json()
        with SessionLocal() as db:
            owner = _user(db, "f2_resource_recovery_owner")
            completed = complete_generation_item(
                db, owner, created["job_id"], "handout", content="# 已完成讲义",
            )
            handout = next(item for item in completed["items"] if item["type"] == "handout")
            resource_id = handout["resource"]["resource_id"]
            mark_generation_item_running(db, owner, created["job_id"], "mind_map")
            fail_generation_item(
                db,
                owner,
                created["job_id"],
                "quiz",
                error_code="model_capacity",
                error_message="模型暂时不可用",
            )
            db.commit()

        recovered = client.post(
            f"/api/v1/resource-bundles/generation-jobs/{created['job_id']}/recover",
            headers=headers,
        )
        assert recovered.status_code == 200, recovered.text
        payload = recovered.json()
        assert payload["status"] == "partial_success"
        items = {item["type"]: item for item in payload["items"]}
        assert items["handout"]["state"] == "succeeded"
        assert items["handout"]["attempt"] == 1
        assert items["handout"]["resource"]["resource_id"] == resource_id
        assert items["mind_map"]["state"] == "queued"
        assert items["mind_map"]["attempt"] == 2
        assert items["quiz"]["state"] == "queued"
        assert items["quiz"]["attempt"] == 2
        assert items["training_task"]["state"] == "queued"
        assert items["training_task"]["attempt"] == 1
        with SessionLocal() as db:
            assert db.query(DBArtifact).filter_by(id=resource_id).count() == 1
            assert db.query(DBArtifactVersion).filter_by(artifact_id=resource_id).count() == 1


def test_source_withdrawal_preserves_resource_and_marks_it_unavailable():
    with TestClient(app) as client:
        headers = auth_headers(client, "f2_resource_source_owner")
        seed = _seed("f2_resource_source_owner", "source")
        created = client.post(
            "/api/v1/resource-bundles/generation-jobs",
            headers=headers,
            json=_payload(seed, "f2-resource-source-0001"),
        ).json()
        with SessionLocal() as db:
            owner = _user(db, "f2_resource_source_owner")
            result = complete_generation_item(
                db,
                owner,
                created["job_id"],
                "handout",
                content="# 来源撤回测试",
            )
            resource_id = next(item for item in result["items"] if item["type"] == "handout")["resource"]["resource_id"]
            source = db.get(DBSourceDocument, seed["source_document_id"])
            source.processing_status = "failed"
            source.processing_error_code = "source_withdrawn"
            db.commit()

        detail = client.get(f"/api/v1/m5/resources/{resource_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        resource = detail.json()["resource"]
        assert resource["status"] == "source_unavailable"
        assert resource["source_refs"][0]["available"] is False
        assert detail.json()["versions"][0]["content"] == "# 来源撤回测试"


def test_resource_revision_compare_and_restore_preserve_old_versions():
    with TestClient(app) as client:
        headers = auth_headers(client, "f2_resource_version_owner")
        seed = _seed("f2_resource_version_owner", "version")
        created = client.post(
            "/api/v1/resource-bundles/generation-jobs",
            headers=headers,
            json=_payload(seed, "f2-resource-version-0001"),
        ).json()
        with SessionLocal() as db:
            owner = _user(db, "f2_resource_version_owner")
            result = complete_generation_item(
                db,
                owner,
                created["job_id"],
                "handout",
                content="# 讲义 v1",
            )
            resource_id = next(item for item in result["items"] if item["type"] == "handout")["resource"]["resource_id"]
            artifact = db.get(DBArtifact, resource_id)
            first_version_id = artifact.current_version_id
            detail = create_resource_version(
                db,
                artifact=artifact,
                actor_public_id=owner.public_id,
                request=ResourceVersionCreateRequest(
                    expected_lock_version=artifact.lock_version,
                    source_version_id=first_version_id,
                    content="# 讲义 v2",
                ),
            )
            second_version_id = artifact.current_version_id
            with pytest.raises(M5CapabilityError, match="lock version"):
                create_resource_version(
                    db,
                    artifact=artifact,
                    actor_public_id=owner.public_id,
                    request=ResourceVersionCreateRequest(
                        expected_lock_version=1,
                        source_version_id=second_version_id,
                        content="# 讲义 v3",
                    ),
                )
            assert db.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).count() == 2
            restored = restore_resource_version(
                db,
                artifact=artifact,
                actor_public_id=owner.public_id,
                request=ResourceVersionRestoreRequest(
                    expected_lock_version=detail["lock_version"],
                    version_id=first_version_id,
                ),
            )
            restored_version_id = artifact.current_version_id
            restored_version = db.get(DBArtifactVersion, restored_version_id)
            assert restored["current_version_id"] == restored_version_id
            assert restored_version_id not in {first_version_id, second_version_id}
            assert db.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).count() == 3
            assert restored_version.content == "# 讲义 v1"
            assert restored_version.metadata_json["restored_from_version_id"] == first_version_id
            assert db.get(DBArtifactVersion, second_version_id).content == "# 讲义 v2"
            assert resource_detail(db, artifact)["resource"]["version"]["id"] == restored_version_id

        compare = client.get(
            f"/api/v1/m5/resources/{resource_id}/compare",
            params={"left_version": 1, "right_version": 2},
            headers=headers,
        )
        assert compare.status_code == 200, compare.text
        assert compare.json()["changed"] is True
        assert "讲义 v1" in compare.json()["diff"]
        assert "讲义 v2" in compare.json()["diff"]
