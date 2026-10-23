from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database import (
    DBAssessmentQuestion, DBAssessmentQuestionVersion, DBArtifact, DBArtifactVersion,
    DBCourse, DBCourseDocument, DBCourseMembership, DBKnowledgePoint, DBResourceBundleItem,
    DBResourceBundleVersion, DBTeachingAnimation, DBTeachingAnimationVersion,
    DBUser, DBVideoProject, DBVideoScriptVersion, DBWebDeck, DBWebDeckVersion, SessionLocal,
)
from app.main import app
from app.m1_object_service import OBJECT_SPECS
from tests.api_test_helpers import auth_headers


TYPES = ("handout", "mind_map", "code", "exercise", "video", "ppt", "animation", "lab")


def _user(db, username):
    return db.query(DBUser).filter_by(username=username).one()


def _seed(username: str, suffix: str):
    with SessionLocal() as db:
        user = _user(db, username); course_id = f"fc1-bundle-course-{suffix}"
        course = DBCourse(id=course_id, version="1", title="机器学习技能训练", subject="人工智能",
            domain_pack="ml", visibility="private", status="published", owner_public_id=user.public_id,
            manifest_version="fc1-bundle-v1", manifest_data={"demo": True})
        kp = DBKnowledgePoint(domain_pack="ml", code=f"gradient-{suffix}", version="1", title="梯度下降")
        db.add_all([course, kp]); db.flush(); db.add(DBCourseMembership(course_id=course_id, user_public_id=user.public_id, role="student", status="active"))
        content = "# 梯度下降\n沿损失函数梯度的反方向更新参数；学习率过大可能导致震荡，过小则收敛缓慢。"
        db.add(DBCourseDocument(
            id=f"fc1-bundle-material-{suffix}", course_id=course_id, chapter_order=1,
            filename="gradient-descent.md", title="梯度下降课程讲义", content=content,
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            chunk_count=1, status="published",
        ))
        refs = []
        artifact_map = {"handout": "lesson", "mind_map": "mindmap", "code": "code_example", "lab": "interactive_lab_instance"}
        for kind, artifact_type in artifact_map.items():
            artifact = DBArtifact(owner_public_id=user.public_id, course_id=course_id, artifact_type=artifact_type,
                title={"handout":"梯度下降讲义","mind_map":"优化算法导图","code":"梯度下降代码","lab":"参数调优实验"}[kind], status="approved")
            db.add(artifact); db.flush()
            version = DBArtifactVersion(artifact_id=artifact.id, version_number=1, content=f"{kind} content",
                content_format="markdown", content_hash=hashlib.sha256(kind.encode()).hexdigest(),
                metadata_json={"source_ref_ids":[f"source-{kind}"],"quality":{"status":"checked"},"profile":{"modality":kind}}, created_by_public_id=user.public_id)
            db.add(version); db.flush(); artifact.current_version_id=version.id
            refs.append({"resource_type":kind,"resource_id":artifact.id,"resource_version_id":version.id})
        question = DBAssessmentQuestion(course_id=course_id, owner_public_id=user.public_id, question_type="single_choice", origin="manual", status="approved")
        db.add(question); db.flush(); qv=DBAssessmentQuestionVersion(question_id=question.id,version_number=1,prompt="学习率过大最可能导致什么？",options=["收敛","震荡"],answer_key={"correct":[1]},scoring_rule={"type":"exact"},explanation="步长过大",primary_knowledge_point_id=kp.id,bloom_level="analyze",expert_difficulty=.6,source_ref_ids=["source-exercise"],content_hash="e"*64,created_by_public_id=user.public_id)
        db.add(qv); db.flush(); question.current_version_id=qv.id; refs.append({"resource_type":"exercise","resource_id":question.id,"resource_version_id":qv.id})
        video=DBVideoProject(owner_public_id=user.public_id,course_id=course_id,title="梯度下降讲解视频");db.add(video);db.flush();vv=DBVideoScriptVersion(project_id=video.id,version_number=1,scenes=[{"title":"目标"}],total_duration_ms=30000,content_hash="v"*64,created_by_public_id=user.public_id);db.add(vv);db.flush();video.current_script_version_id=vv.id;refs.append({"resource_type":"video","resource_id":video.id,"resource_version_id":vv.id})
        deck=DBWebDeck(owner_public_id=user.public_id,course_id=course_id,title="梯度下降网页课件");db.add(deck);db.flush();dv=DBWebDeckVersion(deck_id=deck.id,version_number=1,slides_snapshot=[{"title":"梯度下降"}],theme_snapshot={},content_hash="p"*64,created_by_public_id=user.public_id);db.add(dv);db.flush();deck.current_version_id=dv.id;refs.append({"resource_type":"ppt","resource_id":deck.id,"resource_version_id":dv.id})
        animation=DBTeachingAnimation(owner_public_id=user.public_id,course_id=course_id,title="梯度下降轨迹",template_id="gradient-descent-2d-v1");db.add(animation);db.flush();av=DBTeachingAnimationVersion(animation_id=animation.id,version_number=1,parameters={"learning_rate":.1},frame_data=[{"index":0}],formula_snapshot={},quality_snapshot={"deterministic":True},content_hash="a"*64,created_by_public_id=user.public_id);db.add(av);db.flush();animation.current_version_id=av.id;refs.append({"resource_type":"animation","resource_id":animation.id,"resource_version_id":av.id})
        db.commit(); return course_id, kp.id, sorted(refs,key=lambda x:TYPES.index(x["resource_type"]))


def _create(client, headers, course_id, kp_id, refs):
    response=client.post('/api/v1/resource-bundles',headers=headers,json={"title":"梯度下降技能资源包","learning_objective":"完成后能够解释学习率并完成参数调优实验。","course_id":course_id,"knowledge_point_id":kp_id,"profile":{"source":"冻结合成画像","preference":"视觉与实操"},"items":refs})
    assert response.status_code==201,response.text; return response.json()


def test_eight_type_bundle_version_idempotency_restore_and_immutability():
    with TestClient(app) as client:
        headers=auth_headers(client,'fc1_010_owner');course,kp,refs=_seed('fc1_010_owner','flow');bundle=_create(client,headers,course,kp,refs)
        assert bundle['current_version']['quality']['coverage']==1.0
        assert [x['resource_type'] for x in bundle['current_version']['items']]==list(TYPES)
        assert all(x['availability']['status']=='available' for x in bundle['current_version']['items'])
        first=bundle['current_version_id']; lock=bundle['lock_version']
        reordered=list(reversed(refs)); changed=client.post(f"/api/v1/resource-bundles/{bundle['id']}/versions",headers=headers,json={"profile":{"source":"冻结合成画像","preference":"视觉与实操"},"items":reordered,"expected_lock_version":lock,"change_summary":"按任务顺序重排"})
        assert changed.status_code==200,changed.text; changed=changed.json(); assert changed['version_created'] and changed['current_version']['version_number']==2
        replay=client.post(f"/api/v1/resource-bundles/{bundle['id']}/versions",headers=headers,json={"profile":changed['current_version']['profile'],"items":reordered,"expected_lock_version":changed['lock_version'],"change_summary":"重复"})
        assert replay.status_code==200 and replay.json()['version_created'] is False
        restored=client.post(f"/api/v1/resource-bundles/{bundle['id']}/restore",headers=headers,json={"version_id":first,"expected_lock_version":changed['lock_version']})
        assert restored.status_code==200 and restored.json()['current_version_id']==first
        version_id=restored.json()['current_version_id']; item_id=restored.json()['current_version']['items'][0]['id']
    assert OBJECT_SPECS['resource_bundle'].model.__tablename__=='resource_bundles'
    with SessionLocal() as db:
        version=db.get(DBResourceBundleVersion,version_id);version.content_hash='0'*64
        with pytest.raises(DatabaseError,match='immutable'):db.commit()
        db.rollback();item=db.get(DBResourceBundleItem,item_id);item.position=7
        with pytest.raises(DatabaseError,match='immutable'):db.commit()
        db.rollback()


def test_owner_course_type_conflict_strict_input_and_unavailable_degradation():
    with TestClient(app) as client:
        owner=auth_headers(client,'fc1_010_boundary_owner');other=auth_headers(client,'fc1_010_boundary_other');course,kp,refs=_seed('fc1_010_boundary_owner','boundary');bundle=_create(client,owner,course,kp,refs)
        assert client.get(f"/api/v1/resource-bundles/{bundle['id']}",headers=other).status_code==403
        duplicate=client.post(f"/api/v1/resource-bundles/{bundle['id']}/versions",headers=owner,json={"profile":{},"items":[refs[0],refs[0]],"expected_lock_version":bundle['lock_version'],"change_summary":"bad"})
        assert duplicate.status_code==422
        mismatch=dict(refs[0],resource_type='ppt')
        bad=client.post(f"/api/v1/resource-bundles/{bundle['id']}/versions",headers=owner,json={"profile":{},"items":[mismatch],"expected_lock_version":bundle['lock_version'],"change_summary":"bad"})
        assert bad.status_code==422
        injected=client.post('/api/v1/resource-bundles',headers=owner,json={"title":"x","learning_objective":"y","course_id":course,"items":[refs[0]],"quality":{"status":"fake"}})
        assert injected.status_code==422
        version_id=bundle['current_version_id']
        with SessionLocal() as db:
            item=db.query(DBResourceBundleItem).filter_by(bundle_version_id=version_id,resource_type='handout').one()
            db.execute(text('DROP TRIGGER trg_resource_bundle_item_no_update'));db.execute(text("UPDATE resource_bundle_items SET resource_id='missing-artifact' WHERE id=:id"),{'id':item.id});db.execute(text("CREATE TRIGGER trg_resource_bundle_item_no_update BEFORE UPDATE ON resource_bundle_items BEGIN SELECT RAISE(ABORT, 'resource bundle item is immutable'); END"));db.commit()
        detail=client.get(f"/api/v1/resource-bundles/{bundle['id']}",headers=owner).json();handout=next(x for x in detail['current_version']['items'] if x['resource_type']=='handout')
        assert handout['availability']['status']=='unavailable' and detail['current_version']['quality']['coverage']==1.0
