from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBCourse,
    DBCourseDocument,
    DBCourseMembership,
    DBLearningEvent,
    DBLearningPath,
    DBMarketplacePersonalCopy,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBResourceBundle,
    DBResourceBundleItem,
    DBResourceBundleVersion,
    DBSourceDocument,
    DBUser,
    SessionLocal,
)
from app.main import app
from app.m5_learning import PlanSpec
from tests.api_test_helpers import TEST_PASSWORD, auth_headers


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        data={"username": username, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _seed_marketplace_objects(client: TestClient) -> dict[str, object]:
    suffix = uuid4().hex[:10]
    usernames = {
        "publisher": f"f9_market_publisher_{suffix}",
        "admin": f"f9_market_admin_{suffix}",
        "learner": f"f9_market_learner_{suffix}",
        "outsider": f"f9_market_outsider_{suffix}",
    }
    for username in usernames.values():
        auth_headers(client, username)
    with SessionLocal() as db:
        db.query(DBUser).filter_by(username=usernames["admin"]).update({"role": "admin"})
        db.commit()
    headers = {role: _login(client, username) for role, username in usernames.items()}

    course_id = f"f9-market-course-{suffix}"
    bad_course_id = f"f9-market-bad-course-{suffix}"
    artifact_id = f"f9-art-{suffix}"
    artifact_version_id = f"f9-av-{suffix}"
    bad_artifact_id = f"f9-bad-art-{suffix}"
    bad_artifact_version_id = f"f9-bad-av-{suffix}"
    bundle_id = f"f9-bundle-{suffix}"
    bundle_version_id = f"f9-bundlever-{suffix}"
    plan_id = f"f9-plan-{suffix}"
    plan_version_id = f"f9-planver-{suffix}"
    path_id = f"f9-path-{suffix}"

    with SessionLocal() as db:
        users = {
            role: db.query(DBUser).filter_by(username=username).one()
            for role, username in usernames.items()
        }
        publisher_id = users["publisher"].public_id
        db.add(DBCourse(
            id=course_id,
            version="v1",
            title="机器学习工程实践",
            subject="人工智能",
            description="用于学习市场隔离测试的冻结合成课程",
            domain_pack="machine-learning",
            language="zh-CN",
            content_origin="https://example.invalid/frozen-ml-course",
            license_text="CC BY 4.0",
            visibility="private",
            status="published",
            owner_public_id=publisher_id,
            manifest_version="f9-test-v1",
            manifest_data={"demo_scope": "匿名合成比赛演示数据"},
        ))
        db.flush()
        db.add(DBCourseMembership(
            course_id=course_id,
            user_public_id=publisher_id,
            role="student",
            status="active",
        ))
        db.add(DBCourseDocument(
            id=f"f9-doc-{suffix}",
            course_id=course_id,
            chapter_order=1,
            filename="chapter-1.md",
            title="监督学习基础",
            content="冻结课程正文",
            content_hash="1" * 64,
            license_text="CC BY 4.0",
        ))
        db.add(DBSourceDocument(
            id=f"f9-src-{suffix}",
            course_id=course_id,
            title="监督学习基础",
            filename="chapter-1.md",
            file_format="md",
            content_hash="1" * 64,
            source_sha256="2" * 64,
            processed_sha256="3" * 64,
            source_url="https://example.invalid/frozen-ml-course/chapter-1",
            license_text="CC BY 4.0",
            processing_status="ready",
        ))
        resource_content = json.dumps({
            "title": "监督学习个性化讲义",
            "summary": "根据当前课程版本冻结的讲义摘要",
            "answer": "TOP_SECRET_ANSWER",
            "system_prompt": "TOP_SECRET_PROMPT",
            "raw_log": "TOP_SECRET_LOG",
        }, ensure_ascii=False)
        db.add(DBArtifact(
            id=artifact_id,
            owner_public_id=publisher_id,
            course_id=course_id,
            artifact_type="handout",
            title="监督学习个性化讲义",
            status="approved",
            current_version_id=artifact_version_id,
        ))
        db.add(DBArtifactVersion(
            id=artifact_version_id,
            artifact_id=artifact_id,
            version_number=1,
            content=resource_content,
            content_format="json",
            content_hash="4" * 64,
            metadata_json={"summary": "冻结讲义", "api_key": "TOP_SECRET_KEY"},
            created_by_public_id=publisher_id,
        ))
        db.flush()
        db.add(DBResourceBundle(
            id=bundle_id,
            owner_public_id=publisher_id,
            course_id=course_id,
            title="监督学习完整资源包",
            learning_objective="理解损失函数并完成一次工程练习",
            current_version_id=bundle_version_id,
            status="active",
        ))
        db.add(DBResourceBundleVersion(
            id=bundle_version_id,
            bundle_id=bundle_id,
            version_number=1,
            profile_snapshot={"scope": "anonymous-test"},
            quality_summary={"state": "verified"},
            content_hash="5" * 64,
            change_summary="冻结测试资源包",
            created_by_public_id=publisher_id,
        ))
        db.flush()
        db.add(DBResourceBundleItem(
            bundle_version_id=bundle_version_id,
            position=0,
            resource_type="handout",
            resource_id=artifact_id,
            resource_version_id=artifact_version_id,
            frozen_snapshot={"title": "监督学习个性化讲义"},
        ))
        db.flush()
        db.add(DBPlanDraft(
            id=plan_id,
            owner_public_id=publisher_id,
            course_id=course_id,
            title="监督学习两阶段路径",
            status="confirmed",
            current_version_id=plan_version_id,
            confirmed_version_id=plan_version_id,
        ))
        db.add(DBPlanVersion(
            id=plan_version_id,
            plan_draft_id=plan_id,
            version_number=1,
            content={
                "schema_version": "m5.plan.v1",
                "goal": "完成监督学习理论与工程实践",
                "assumptions": [],
                "nodes": [{
                    "node_key": "loss-function",
                    "node_type": "artifact",
                    "target_object_id": artifact_id,
                    "title": "理解损失函数",
                    "prerequisites": [],
                    "resource_status": "existing",
                    "estimate_min_minutes": 20,
                    "estimate_max_minutes": 30,
                }],
            },
            content_hash="6" * 64,
            created_by_public_id=publisher_id,
        ))
        db.flush()
        db.add(DBLearningPath(
            id=path_id,
            owner_public_id=publisher_id,
            course_id=course_id,
            source_plan_version_id=plan_version_id,
            status="active",
        ))
        db.flush()
        db.add(DBPathNode(
            learning_path_id=path_id,
            node_key="loss-function",
            sequence=1,
            node_type="knowledge_point",
            title="理解损失函数",
            status="completed",
            prerequisites=[],
            resource_status="existing",
            estimate_min_minutes=20,
            estimate_max_minutes=30,
        ))
        db.flush()

        db.add(DBCourse(
            id=bad_course_id,
            version="v1",
            title="来源不完整课程",
            subject="人工智能",
            description="故意缺少来源和许可证",
            content_origin="",
            license_text="",
            visibility="private",
            status="published",
            owner_public_id=publisher_id,
            manifest_version="f9-test-v1",
            manifest_data={},
        ))
        db.flush()
        db.add(DBArtifact(
            id=bad_artifact_id,
            owner_public_id=publisher_id,
            course_id=bad_course_id,
            artifact_type="handout",
            title="来源不完整讲义",
            status="approved",
            current_version_id=bad_artifact_version_id,
        ))
        db.add(DBArtifactVersion(
            id=bad_artifact_version_id,
            artifact_id=bad_artifact_id,
            version_number=1,
            content="来源不完整",
            content_format="markdown",
            content_hash="7" * 64,
            metadata_json={},
            created_by_public_id=publisher_id,
        ))
        db.commit()

        protected_counts = {
            "learning_events": db.query(DBLearningEvent).count(),
            "profile_snapshots": db.query(DBProfileSnapshot).count(),
        }

    return {
        "suffix": suffix,
        "headers": headers,
        "course_id": course_id,
        "artifact_id": artifact_id,
        "artifact_version_id": artifact_version_id,
        "bad_artifact_id": bad_artifact_id,
        "bundle_id": bundle_id,
        "bundle_version_id": bundle_version_id,
        "path_id": path_id,
        "path_version_id": plan_version_id,
        "protected_counts": protected_counts,
    }


def _submit(
    client: TestClient,
    headers: dict[str, str],
    *,
    suffix: str,
    item_type: str,
    source_object_id: str,
    source_version_id: str,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/marketplace/listings",
        headers=headers,
        json={
            "item_type": item_type,
            "source_object_id": source_object_id,
            "source_version_id": source_version_id,
            "title": f"F9 {item_type} {suffix}",
            "summary": "冻结来源的学习市场测试内容，可安全预览并保存个人副本。",
            "category": "人工智能",
            "tags": ["F9", suffix, item_type],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _publish(client: TestClient, headers: dict[str, str], listing: dict[str, object]) -> dict[str, object]:
    approved = client.post(
        f"/api/v1/marketplace/listings/{listing['id']}/decisions",
        headers=headers,
        json={
            "action": "approve",
            "reason": "冻结来源、许可证和公开预览已经通过审核",
            "expected_version": listing["lock_version"],
        },
    )
    assert approved.status_code == 200, approved.text
    published = client.post(
        f"/api/v1/marketplace/listings/{listing['id']}/decisions",
        headers=headers,
        json={
            "action": "publish",
            "reason": "批准在轻量学习市场中公开展示并保存副本",
            "expected_version": approved.json()["lock_version"],
        },
    )
    assert published.status_code == 200, published.text
    return published.json()


def test_typed_marketplace_publish_preview_clone_and_withdrawal_are_safe_and_idempotent():
    with TestClient(app) as client:
        seeded = _seed_marketplace_objects(client)
        headers = seeded["headers"]
        assert isinstance(headers, dict)

        forbidden = client.post(
            "/api/v1/marketplace/listings",
            headers=headers["outsider"],
            json={
                "item_type": "resource",
                "source_object_id": seeded["artifact_id"],
                "source_version_id": seeded["artifact_version_id"],
                "title": "越权发布",
                "summary": "该请求必须因为对象不属于当前账号而被拒绝。",
                "category": "人工智能",
                "tags": ["F9"],
            },
        )
        assert forbidden.status_code == 403, forbidden.text

        incomplete = client.post(
            "/api/v1/marketplace/listings",
            headers=headers["publisher"],
            json={
                "item_type": "resource",
                "source_object_id": seeded["bad_artifact_id"],
                "title": "来源不完整讲义",
                "summary": "该请求必须因为来源和许可证缺失而被拒绝。",
                "category": "人工智能",
                "tags": ["F9"],
            },
        )
        assert incomplete.status_code == 422, incomplete.text
        assert incomplete.json()["detail"]["code"] == "marketplace_provenance_incomplete"

        sources = {
            "resource": (seeded["artifact_id"], seeded["artifact_version_id"]),
            "resource_bundle": (seeded["bundle_id"], seeded["bundle_version_id"]),
            "learning_path": (seeded["path_id"], seeded["path_version_id"]),
        }
        listings: dict[str, dict[str, object]] = {}
        for item_type, (object_id, version_id) in sources.items():
            listing = _submit(
                client,
                headers["publisher"],
                suffix=str(seeded["suffix"]),
                item_type=item_type,
                source_object_id=str(object_id),
                source_version_id=str(version_id),
            )
            assert listing["item_type"] == item_type
            assert listing["provenance"]["complete"] is True
            listings[item_type] = _publish(client, headers["admin"], listing)

        workspace = client.get("/api/v1/marketplace/workspace", headers=headers["publisher"])
        assert workspace.status_code == 200, workspace.text
        publishable = workspace.json()["publishable_sources"]
        assert {item_type for item_type, rows in publishable.items() if rows} == set(sources)

        for item_type, listing in listings.items():
            response = client.get(
                "/api/v1/marketplace/public",
                headers=headers["learner"],
                params={"q": seeded["suffix"], "item_type": item_type},
            )
            assert response.status_code == 200, response.text
            items = [item for item in response.json()["items"] if item["id"] == listing["id"]]
            assert len(items) == 1
            public_text = json.dumps(items[0], ensure_ascii=False)
            for secret in ("TOP_SECRET_ANSWER", "TOP_SECRET_PROMPT", "TOP_SECRET_LOG", "TOP_SECRET_KEY"):
                assert secret not in public_text
            assert items[0]["preview"]["kind"] == item_type
            assert items[0]["saved_copy"] is None

        copies: dict[str, dict[str, object]] = {}
        for item_type, listing in listings.items():
            first = client.post(
                f"/api/v1/marketplace/listings/{listing['id']}/acquisitions",
                headers=headers["learner"],
            )
            assert first.status_code == 201, first.text
            second = client.post(
                f"/api/v1/marketplace/listings/{listing['id']}/acquisitions",
                headers=headers["learner"],
            )
            assert second.status_code == 201, second.text
            assert second.json()["id"] == first.json()["id"]
            assert first.json()["item_type"] == item_type
            assert first.json()["open_route"].startswith("/workspace/")
            copies[item_type] = first.json()

        with SessionLocal() as db:
            learner = db.query(DBUser).filter_by(username=f"f9_market_learner_{seeded['suffix']}").one()
            resource_copy = db.get(DBArtifact, copies["resource"]["copy_object_id"])
            assert resource_copy is not None and resource_copy.owner_public_id == learner.public_id
            assert resource_copy.id != seeded["artifact_id"]

            bundle_copy = db.get(DBResourceBundle, copies["resource_bundle"]["copy_object_id"])
            assert bundle_copy is not None and bundle_copy.owner_public_id == learner.public_id
            bundle_items = db.query(DBResourceBundleItem).filter_by(
                bundle_version_id=copies["resource_bundle"]["copy_version_id"]
            ).all()
            assert len(bundle_items) == 1 and bundle_items[0].resource_id != seeded["artifact_id"]

            path_copy = db.get(DBLearningPath, copies["learning_path"]["copy_object_id"])
            assert path_copy is not None and path_copy.owner_public_id == learner.public_id
            copied_plan_version = db.get(DBPlanVersion, path_copy.source_plan_version_id)
            assert copied_plan_version is not None
            PlanSpec.model_validate(copied_plan_version.content)
            copied_nodes = db.query(DBPathNode).filter_by(learning_path_id=path_copy.id).all()
            assert copied_nodes and {node.status for node in copied_nodes} == {"pending"}

            local_version_id = f"f9-local-bundlever-{seeded['suffix']}"
            db.add(DBResourceBundleVersion(
                id=local_version_id,
                bundle_id=bundle_copy.id,
                version_number=2,
                profile_snapshot={"scope": "learner-edit"},
                quality_summary={"state": "personal"},
                content_hash="8" * 64,
                change_summary="学习者自己的独立修改",
                created_by_public_id=learner.public_id,
            ))
            bundle_copy.current_version_id = local_version_id
            source_artifact = db.get(DBArtifact, seeded["artifact_id"])
            source_artifact.title = "上游后来修改的标题"
            db.commit()

        bundle_listing = listings["resource_bundle"]
        withdrawn = client.post(
            f"/api/v1/marketplace/listings/{bundle_listing['id']}/decisions",
            headers=headers["admin"],
            json={
                "action": "withdraw",
                "reason": "验证上游下架不会删除或覆盖已有个人副本",
                "expected_version": bundle_listing["lock_version"],
            },
        )
        assert withdrawn.status_code == 200, withdrawn.text
        blocked = client.post(
            f"/api/v1/marketplace/listings/{bundle_listing['id']}/acquisitions",
            headers=headers["outsider"],
        )
        assert blocked.status_code == 422, blocked.text

        learner_workspace = client.get("/api/v1/marketplace/workspace", headers=headers["learner"])
        assert learner_workspace.status_code == 200, learner_workspace.text
        saved_bundle = next(
            row for row in learner_workspace.json()["personal_copies"]
            if row["id"] == copies["resource_bundle"]["id"]
        )
        assert saved_bundle["source_status"] == "withdrawn"
        assert saved_bundle["open_route"] == copies["resource_bundle"]["open_route"]

        with SessionLocal() as db:
            personal = db.get(DBMarketplacePersonalCopy, copies["resource_bundle"]["id"])
            bundle_copy = db.get(DBResourceBundle, copies["resource_bundle"]["copy_object_id"])
            assert personal is not None and personal.source_status == "withdrawn"
            assert bundle_copy is not None
            assert bundle_copy.current_version_id == f"f9-local-bundlever-{seeded['suffix']}"
            assert db.query(DBLearningEvent).count() == seeded["protected_counts"]["learning_events"]
            assert db.query(DBProfileSnapshot).count() == seeded["protected_counts"]["profile_snapshots"]
