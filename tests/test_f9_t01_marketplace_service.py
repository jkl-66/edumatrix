from __future__ import annotations

import json
from uuid import uuid4
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest

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
    DBSourceRef,
    DBChapter,
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
            legacy_document_id=f"f9-doc-{suffix}",
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
        db.flush()
        db.add(DBChapter(id=f"f9-ch-{suffix}", course_id=course_id, source_document_id=f"f9-src-{suffix}",
                         stable_key="chapter-1", title="监督学习基础", char_start=0, char_end=6))
        db.flush()
        db.add(DBSourceRef(id=f"f9-ref-{suffix}", source_document_id=f"f9-src-{suffix}", chapter_id=f"f9-ch-{suffix}",
                           parser_version="v1", content_hash="1" * 64, quote="冻结课程正文"))
        resource_content = json.dumps({
            "title": "监督学习个性化讲义",
            "summary": "根据当前课程版本冻结的讲义摘要",
            "answer": "TOP_SECRET_ANSWER",
            "system_prompt": "TOP_SECRET_PROMPT",
            "raw_log": "TOP_SECRET_LOG",
            "sourceRefIds": [f"f9-ref-{suffix}"],
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
            metadata_json={"summary": "冻结讲义", "api_key": "TOP_SECRET_KEY", "source_ref_ids": [f"f9-ref-{suffix}"]},
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
                    "node_key": f"f9-ch-{suffix}",
                    "node_type": "chapter",
                    "target_object_id": f"f9-ch-{suffix}",
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
            node_key=f"f9-ch-{suffix}",
            sequence=1,
            node_type="chapter",
            target_object_id=f"f9-ch-{suffix}",
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
        # The course is readable, but this source deliberately lacks origin and
        # license evidence, so publishing reaches the provenance check.
        db.add(DBSourceDocument(
            id=f"f9-bad-src-{suffix}", course_id=bad_course_id,
            title="来源未核验资料", filename="unverified.md", file_format="md",
            content_hash="8" * 64, source_sha256="8" * 64, processed_sha256="8" * 64,
            source_url="", license_text="", processing_status="ready",
        ))
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


@pytest.mark.parametrize('item_type,object_key,version_key', [
    ('resource', 'artifact_id', 'artifact_version_id'),
    ('resource_bundle', 'bundle_id', 'bundle_version_id'),
    ('learning_path', 'path_id', 'path_version_id'),
])
def test_marketplace_rework_preserves_original_and_withdrawn_copy_and_favorite(item_type, object_key, version_key):
    with TestClient(app) as client:
        seeded = _seed_marketplace_objects(client)
        headers = seeded['headers']
        original = _submit(client, headers['publisher'], suffix=seeded['suffix'], item_type=item_type,
                           source_object_id=seeded[object_key], source_version_id=seeded[version_key])
        path = f"/api/v1/marketplace/listings/{original['id']}"
        rework = client.post(path+'/decisions', headers=headers['admin'], json={
            'action':'request_changes', 'reason':'请补充适合的学习阶段和练习方式。', 'expected_version':original['lock_version']})
        assert rework.status_code == 200, rework.text
        payload = {'item_type':item_type, 'source_object_id':seeded[object_key], 'source_version_id':seeded[version_key],
                   'title':'修改后的学习分享', 'summary':'适合初学者从具体例子开始，完成练习后再核对解释。',
                   'category':'人工智能', 'tags':['初学者'], 'revision_of':original['id'],
                   'expected_version':rework.json()['lock_version']}
        assert client.post('/api/v1/marketplace/listings', headers=headers['outsider'], json=payload).status_code == 403
        stale = client.post('/api/v1/marketplace/listings', headers=headers['publisher'], json={**payload,'expected_version':1})
        assert stale.status_code == 409, stale.text
        submitted = client.post('/api/v1/marketplace/listings', headers=headers['publisher'], json=payload)
        assert submitted.status_code == 201, submitted.text
        updated = submitted.json()
        assert updated['id'] != original['id'] and updated['status'] == 'pending'
        assert updated['source_version_id'] == original['source_version_id']
        repeated = client.post('/api/v1/marketplace/listings', headers=headers['publisher'], json=payload)
        assert repeated.json()['id'] == updated['id']
        old = client.get(path, headers=headers['publisher']).json()
        assert old['title'] == original['title'] and old['snapshot_hash'] == original['snapshot_hash']
        assert old['can_resubmit'] is False and old['resubmitted_listing_id'] == updated['id']
        assert any(x['reason'] == '请补充适合的学习阶段和练习方式。' for x in old['decisions'])
        changed_again = client.post('/api/v1/marketplace/listings', headers=headers['publisher'], json={**payload,'title':'另一次修改'})
        assert changed_again.status_code == 409
        published = _publish(client, headers['admin'], updated)
        path = f"/api/v1/marketplace/listings/{published['id']}"
        assert client.put(path+'/favorite',headers=headers['learner'],json={'active':True}).status_code == 200
        copied = client.post(path+'/acquisitions',headers=headers['learner']).json()
        withdrawn = client.post(path+'/decisions',headers=headers['admin'],json={'action':'withdraw',
            'reason':'检查下架后本人副本和收藏仍然可以找到。','expected_version':published['lock_version']})
        assert withdrawn.status_code == 200, withdrawn.text
        own = client.get('/api/v1/marketplace/workspace',headers=headers['learner']).json()
        assert any(x['id'] == published['id'] and x['status']=='withdrawn' for x in own['favorites'])
        assert all(x['id'] != published['id'] for x in own['published'])
        personal = next(x for x in own['personal_copies'] if x['id']==copied['id'])
        assert personal['source_status']=='withdrawn' and personal['copy_version_id']==copied['copy_version_id']
        assert client.get(path,headers=headers['learner']).status_code == 200
        assert client.get(path,headers=headers['outsider']).status_code == 403
        assert client.post(path+'/acquisitions',headers=headers['outsider']).status_code == 422
        assert client.put(path+'/favorite',headers=headers['learner'],json={'active':False}).status_code == 200
        assert client.get('/api/v1/marketplace/workspace',headers=headers['learner']).json()['favorites']==[]
        with SessionLocal() as db:
            assert db.query(DBLearningEvent).count() == seeded['protected_counts']['learning_events']
            assert db.query(DBProfileSnapshot).count() == seeded['protected_counts']['profile_snapshots']


def test_bundle_copy_remaps_links_between_its_personal_resources():
    from types import SimpleNamespace
    from app.database import DBMarketplaceListing
    from app.marketplace import _clone_bundle
    with TestClient(app) as client:
        seeded = _seed_marketplace_objects(client)
        listed = _submit(client, seeded["headers"]["publisher"], suffix=seeded["suffix"],
            item_type="resource_bundle", source_object_id=seeded["bundle_id"], source_version_id=seeded["bundle_version_id"])
        with SessionLocal() as db:
            listing = db.get(DBMarketplaceListing, listed["id"])
            snapshot = json.loads(json.dumps(listing.snapshot_data))
            linked = {"linkedResourceIds": [seeded["artifact_id"]], "linkedVersionId": seeded["artifact_version_id"]}
            snapshot["object"]["items"].append({
                "position": 1, "resource_type": "lab", "resource_id": "linked-task", "resource_version_id": "linked-task-version",
                "frozen_snapshot": {"linkedResourceIds": [seeded["artifact_id"]]},
                "reference": {"kind": "artifact", "artifact": {"artifact_type": "training_task", "title": "Linked task"},
                    "version": {"content": json.dumps(linked), "content_format": "json", "content_hash": "d" * 64, "metadata": linked}},
            })
            actor = db.query(DBUser).filter_by(username=f"f9_market_learner_{seeded['suffix']}").one()
            course = DBCourse(id="bundle-copy-" + seeded["suffix"], version="1", title="Personal course", status="published", owner_public_id=actor.public_id, manifest_version="test")
            db.add(course);db.flush()
            frozen_listing = SimpleNamespace(id=listing.id, snapshot_data=snapshot, title=listing.title, summary=listing.summary,
                snapshot_hash=listing.snapshot_hash, source_object_id=listing.source_object_id, source_version_id=listing.source_version_id)
            _, version_id, _ = _clone_bundle(db, actor, frozen_listing, course)
            items = db.query(DBResourceBundleItem).filter_by(bundle_version_id=version_id).order_by(DBResourceBundleItem.position).all()
            linked_version = db.get(DBArtifactVersion, items[1].resource_version_id)
            content = json.loads(linked_version.content)
            assert content["linkedResourceIds"] == [items[0].resource_id]
            assert content["linkedVersionId"] == items[0].resource_version_id
            assert linked_version.metadata_json["linkedResourceIds"] == [items[0].resource_id]
            assert items[1].frozen_snapshot["linkedResourceIds"] == [items[0].resource_id]


def test_current_generation_bundle_can_be_published_and_opened_as_personal_resources():
    from app.database import DBGenerationTask, DBTaskEvent, DBTaskStep
    from app.resource_bundles import GENERATION_RESOURCE_TYPES, get_bundle
    with TestClient(app) as client:
        seeded = _seed_marketplace_objects(client)
        suffix = seeded["suffix"]
        task_id = "market-job-" + suffix
        with SessionLocal() as db:
            actor = db.query(DBUser).filter_by(username=f"f9_market_publisher_{suffix}").one()
            db.add(DBGenerationTask(id=task_id, owner_public_id=actor.public_id, course_id=seeded["course_id"],
                trace_id="trace-" + suffix, status="completed", capability="learning_resource_bundle.generate",
                idempotency_key=task_id, progress=1.0))
            db.flush()
            kinds = ["handout", "training_task", "feynman"]
            for kind in kinds:
                art_id, version_id = f"market-{kind}-{suffix}", f"market-ver-{kind}-{suffix}"
                db.add(DBArtifact(id=art_id, owner_public_id=actor.public_id, course_id=seeded["course_id"],
                    artifact_type=kind, title=kind, status="approved", current_version_id=version_id))
                db.flush()
                db.add(DBArtifactVersion(id=version_id, artifact_id=art_id, version_number=1,
                    content=json.dumps({"title":kind,"linkedResourceIds":[f"market-handout-{suffix}"]}),
                    content_format="json", content_hash=(str(kinds.index(kind)+1)*64),
                    metadata_json={"resource_type":kind,"source_ref_ids":[f"f9-ref-{suffix}"]},
                    created_by_public_id=actor.public_id))
                db.flush()
                db.add(DBTaskStep(task_id=task_id, sequence=GENERATION_RESOURCE_TYPES.index(kind)+1,
                    status="succeeded", input_summary=json.dumps({"title":kind}), output_artifact_version_id=version_id))
            for index, (event_type,payload) in enumerate([
                ("resource_generation.requested",{"manifest":{"scope":"bundle","items":[{"type":k} for k in kinds]}}),
                ("review_gate.passed",{}), ("publish.completed",{}),
            ],1):
                db.add(DBTaskEvent(task_id=task_id,sequence=index,event_type=event_type,payload=payload))
            db.commit()
        available = client.get('/api/v1/marketplace/workspace',headers=seeded['headers']['publisher']).json()['publishable_sources']['resource_bundle']
        source = next(item for item in available if item['id']==task_id)
        listing = _submit(client,seeded['headers']['publisher'],suffix=suffix,item_type='resource_bundle',
            source_object_id=task_id,source_version_id=source['version_id'])
        listing = _publish(client,seeded['headers']['admin'],listing)
        acquired = client.post(f"/api/v1/marketplace/listings/{listing['id']}/acquisitions",headers=seeded['headers']['learner'])
        assert acquired.status_code==201,acquired.text
        with SessionLocal() as db:
            learner = db.query(DBUser).filter_by(username=f"f9_market_learner_{suffix}").one()
            bundle = get_bundle(db,learner,acquired.json()['copy_object_id'])
            items = bundle['current_version']['items']
            assert {item['resource_type'] for item in items} == set(kinds)
            assert all(item['availability']['status']=='available' for item in items)
            assert all(item['resource_id'].startswith('market-art-') for item in items)
            versions = [db.get(DBArtifactVersion,item['resource_version_id']) for item in items]
            handout_id=next(item['resource_id'] for item in items if item['resource_type']=='handout')
            assert all(json.loads(v.content)['linkedResourceIds']==[handout_id] for v in versions)


def test_bundle_type_migration_retains_rows_and_immutable_triggers():
    from sqlalchemy import create_engine
    from app.migrations import _extend_bundle_item_types
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE resource_bundle_items(id INTEGER PRIMARY KEY, resource_type TEXT CHECK(resource_type IN ('handout','lab')))")
        db.exec_driver_sql("INSERT INTO resource_bundle_items VALUES(1,'handout')")
        db.exec_driver_sql("CREATE TRIGGER keep_items BEFORE DELETE ON resource_bundle_items BEGIN SELECT RAISE(ABORT,'keep'); END")
        _extend_bundle_item_types(db)
        _extend_bundle_item_types(db)
        db.exec_driver_sql("INSERT INTO resource_bundle_items VALUES(2,'training_task'),(3,'feynman')")
        assert db.exec_driver_sql("SELECT count(*) FROM resource_bundle_items").scalar()==3
        assert db.exec_driver_sql("SELECT count(*) FROM sqlite_master WHERE name='keep_items'").scalar()==1
        assert db.exec_driver_sql('PRAGMA integrity_check').scalar()=='ok'
    engine.dispose()


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
            review = client.get(f"/api/v1/marketplace/listings/{listing['id']}", headers=headers["admin"])
            assert review.status_code == 200, review.text
            assert review.json()["review_contents"], "Administrators need the submitted content, not just a public teaser"
            public_detail = client.get(f"/api/v1/marketplace/listings/{listing['id']}", headers=headers["learner"])
            assert public_detail.status_code == 200, public_detail.text
            assert "review_contents" not in public_detail.json()

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
            assert parse_qs(urlsplit(first.json()["open_route"]).query).get("course_id")
            copies[item_type] = first.json()

        with SessionLocal() as db:
            learner = db.query(DBUser).filter_by(username=f"f9_market_learner_{seeded['suffix']}").one()
            resource_copy = db.get(DBArtifact, copies["resource"]["copy_object_id"])
            assert resource_copy is not None and resource_copy.owner_public_id == learner.public_id
            assert resource_copy.id != seeded["artifact_id"]
            resource_course_id = resource_copy.course_id
            assert parse_qs(urlsplit(copies["resource"]["open_route"]).query)["course_id"] == [resource_course_id]
            version = db.get(DBArtifactVersion, resource_copy.current_version_id)
            copied_ref_id = version.metadata_json["source_ref_ids"][0]
            assert copied_ref_id != f"f9-ref-{seeded['suffix']}"
            assert json.loads(version.content)["sourceRefIds"] == [copied_ref_id]
            ref = db.get(DBSourceRef, copied_ref_id)
            source = db.get(DBSourceDocument, ref.source_document_id)
            assert source.course_id == resource_course_id
            assert db.get(DBCourseDocument, source.legacy_document_id).content == "冻结课程正文"
            assert db.get(DBChapter, ref.chapter_id).course_id == resource_course_id

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
            copied_chapter = db.get(DBChapter, copied_nodes[0].target_object_id)
            assert copied_chapter and copied_chapter.course_id == path_copy.course_id
            assert copied_plan_version.content["nodes"][0]["target_object_id"] == copied_chapter.id
            assert copied_nodes[0].node_key == copied_chapter.id
            assert copied_plan_version.content_hash != "6" * 64
            from app.m5_learning import path_task_route, _generation_context
            read_route = path_task_route(db, node=copied_nodes[0], course_id=path_copy.course_id)
            assert f"/knowledge/documents/{copied_chapter.source_document_id}" in read_route
            generation = _generation_context(db, owner_public_id=learner.public_id,
                course_id=path_copy.course_id, node=copied_nodes[0])
            assert generation["source_ref_ids"]
            assert db.get(DBSourceRef, generation["source_ref_ids"][0]).chapter_id == copied_chapter.id

            # Isolated legacy-copy fixture: keep an existing completion and a
            # local text edit while repairing only the broken source links.
            from app.marketplace import repair_personal_path_sources
            import copy
            legacy_content = copy.deepcopy(copied_plan_version.content)
            legacy_content["goal"] = "本人的练习安排（合成测试）"
            legacy_content["nodes"][0]["target_object_id"] = f"f9-ch-{seeded['suffix']}"
            legacy_content["nodes"][0]["node_key"] = f"f9-ch-{seeded['suffix']}"
            legacy_version = DBPlanVersion(plan_draft_id=copied_plan_version.plan_draft_id,
                version_number=2, content=legacy_content, content_hash="legacy-test-copy",
                created_by_public_id=learner.public_id)
            db.add(legacy_version); db.flush()
            path_copy.source_plan_version_id = legacy_version.id
            copied_plan = db.get(DBPlanDraft, legacy_version.plan_draft_id)
            copied_plan.current_version_id = copied_plan.confirmed_version_id = legacy_version.id
            copied_nodes[0].target_object_id = copied_nodes[0].node_key = f"f9-ch-{seeded['suffix']}"
            copied_nodes[0].status = "completed"
            copied_nodes[0].actual_minutes = 7
            repair_personal_path_sources(db)
            fixed = db.get(DBPlanVersion, path_copy.source_plan_version_id)
            assert fixed.id != legacy_version.id
            assert fixed.content["goal"] == legacy_content["goal"]
            assert fixed.content["nodes"][0]["target_object_id"] == copied_chapter.id
            assert legacy_version.content == legacy_content
            assert copied_nodes[0].target_object_id == copied_nodes[0].node_key == copied_chapter.id
            assert copied_nodes[0].status == "completed" and copied_nodes[0].actual_minutes == 7
            repair_personal_path_sources(db)
            assert path_copy.source_plan_version_id == fixed.id

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

        resolved = client.post("/api/v1/m5/context/resolve", headers=headers["learner"], json={"context": {
            "courseId": resource_course_id, "resourceId": copies["resource"]["copy_object_id"],
        }})
        assert resolved.status_code == 200, resolved.text
        review = client.get(f"/api/v1/marketplace/listings/{listings['resource']['id']}", headers=headers["admin"])
        assert "上游后来修改的标题" not in json.dumps(review.json()["review_contents"], ensure_ascii=False)

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
