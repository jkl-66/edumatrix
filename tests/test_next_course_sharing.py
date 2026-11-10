from __future__ import annotations

import hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database import (
    DBCourse, DBCourseDerivedCopy, DBCourseDocument, DBCourseMembership,
    DBCourseShareDecision, DBCourseShareRelease, DBSourceDocument,
    DBTeachingClass, DBTeachingClassMember, DBUser, SessionLocal, DBChapter, DBSourceRef, DBKnowledgeDocument,
)
from app.main import app
from tests.api_test_helpers import TEST_PASSWORD, auth_headers


def _user(username: str) -> DBUser:
    with SessionLocal() as db: return db.query(DBUser).filter_by(username=username).one()


def _login(client: TestClient, username: str) -> dict[str, str]:
    result = client.post("/api/auth/login", data={"username": username, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {result.json()['access_token']}"}


def _fixture(client: TestClient, suffix: str):
    names = [f"share_{role}_{suffix}" for role in ("teacher", "learner", "outsider")]
    for name in names: auth_headers(client, name)
    with SessionLocal() as db:
        db.query(DBUser).filter_by(username=names[0]).update({"role": "teacher"}); db.commit()
    teacher_h, learner_h, outsider_h = (_login(client, name) for name in names)
    teacher, learner = _user(names[0]), _user(names[1])
    course_id = f"share-course-{suffix}"
    with SessionLocal() as db:
        db.add(DBCourse(id=course_id, version="1.0", title="可信机器学习", subject="AI", description="原始说明",
            content_origin="https://example.invalid/course", license_text="CC BY 4.0", visibility="private", status="published",
            owner_public_id=teacher.public_id, manifest_version="manifest-v1", manifest_data={"commit": "abc"}))
        db.add(DBCourseMembership(course_id=course_id, user_public_id=teacher.public_id, role="teacher", status="active"))
        classroom = DBTeachingClass(course_id=course_id, title=f"分享班-{suffix}", term="2026", owner_public_id=teacher.public_id)
        db.add(classroom); db.flush()
        db.add(DBTeachingClassMember(class_id=classroom.id, user_public_id=learner.public_id, role="student", status="active"))
        db.add(DBCourseDocument(id=f"doc-{suffix}", course_id=course_id, chapter_order=1, filename="chapter.md", file_type="md",
            file_size=10, title="第一章", content="版本一正文", tags=["AI"], chunk_count=1, content_hash="hash-v1",
            source_path="repo/chapter.md", license_text="CC BY 4.0", status="published"))
        db.add(DBSourceDocument(id=f"src-{suffix}", course_id=course_id, title="第一章", filename="chapter.md", file_format="md",
            content_hash="hash-v1", source_sha256="source-v1", processed_sha256="processed-v1", file_size=10,
            source_url="https://example.invalid/chapter", source_path="repo/chapter.md", license_text="CC BY 4.0",
            parser_version="test-v1", processing_status="ready", uploader_public_id=teacher.public_id))
        db.commit(); class_id = classroom.id
    return teacher_h, learner_h, outsider_h, teacher, learner, course_id, class_id


def _publish(client, headers, course_id, class_id, title="可信机器学习共享版"):
    response = client.post("/api/v1/course-sharing/releases", headers=headers,
        json={"course_id": course_id, "target_type": "class", "target_id": class_id, "title": title})
    assert response.status_code == 201, response.text
    return response.json()


def test_uploaded_course_material_is_frozen_and_readable_in_student_copy():
    with TestClient(app) as client:
        teacher_h, learner_h, _, _, _, course_id, class_id = _fixture(client, 'uploaded')
        body = '合成教材：数组下标从0开始，选择下标1和3得到20和40，和为60。'
        digest = hashlib.sha256(body.encode()).hexdigest()
        with SessionLocal() as db:
            db.add(DBKnowledgeDocument(id='upload-sharing-doc', filename='补充材料.md', file_type='md',
                title='教师上传补充材料', content=body, chunk_count=1))
            db.add(DBSourceDocument(id='upload-sharing-src',course_id=course_id,legacy_document_id='upload-sharing-doc',
                filename='补充材料.md',file_format='md',title='教师上传补充材料',content_hash=digest,
                processed_sha256=digest,source_sha256=digest,license_text='CC0',processing_status='ready'))
            db.flush()
            db.add(DBChapter(id='upload-sharing-ch',course_id=course_id,source_document_id='upload-sharing-src',
                stable_key='upload-sharing',title='数组下标',char_start=0,char_end=len(body)))
            db.commit()
        first = _publish(client,teacher_h,course_id,class_id)
        with SessionLocal() as db:
            db.get(DBKnowledgeDocument,'upload-sharing-doc').content='作者发布以后改过的正文，不能出现在原副本。'
            db.commit()
        response = client.post(f"/api/v1/course-sharing/releases/{first['id']}/copies",headers=learner_h)
        assert response.status_code == 201,response.text
        copy = response.json()
        with SessionLocal() as db:
            source = db.query(DBSourceDocument).filter_by(course_id=copy['derived_course']['id'],filename='补充材料.md').one()
            source_id=source.id
            assert source.legacy_document_id != 'upload-sharing-doc'
        read = client.get('/api/knowledge/sources/'+source_id,headers=learner_h)
        assert read.status_code == 200,read.text
        assert read.json()['content'] == body


def test_release_and_derived_copy_freeze_license_source_and_identity():
    with TestClient(app) as client:
        teacher_h, learner_h, outsider_h, _, learner, course_id, class_id = _fixture(client, "flow")
        with SessionLocal() as db:
            content_hash = hashlib.sha256('版本一正文'.encode('utf-8')).hexdigest()
            db.get(DBCourseDocument, 'doc-flow').content_hash = content_hash
            db.get(DBSourceDocument, 'src-flow').content_hash = content_hash
            db.get(DBSourceDocument, 'src-flow').processed_sha256 = content_hash
            db.add(DBChapter(id="share-ch-flow", course_id=course_id, source_document_id="src-flow",
                             stable_key="first", title="第一章", char_start=0, char_end=5))
            db.flush()
            db.add(DBSourceRef(id="share-ref-flow", source_document_id="src-flow", chapter_id="share-ch-flow",
                               parser_version="test-v1", content_hash="hash-v1", quote="版本一正文"))
            db.commit()
        release = _publish(client, teacher_h, course_id, class_id)
        with SessionLocal() as db:
            db.get(DBCourseDocument, "doc-flow").content = "发布后更改的正文"
            db.get(DBSourceDocument, "src-flow").content_hash = "hash-new"
            db.commit()
        workspace = client.get("/api/v1/course-sharing/workspace", headers=learner_h)
        assert workspace.status_code == 200 and workspace.json()["releases"][0]["id"] == release["id"]
        assert release["license_snapshot"]["course_license"] == "CC BY 4.0"
        assert release["license_snapshot"]["legal_review_state"] == "not_automatically_determined"
        created = client.post(f"/api/v1/course-sharing/releases/{release['id']}/copies", headers=learner_h)
        assert created.status_code == 201, created.text
        copy = created.json(); assert copy["derived_course"]["title"].endswith("（派生副本）")
        assert copy["derived_course"]["license_text"] == "CC BY 4.0"
        shelf = client.get('/api/knowledge/courses', headers=learner_h).json()
        assert copy['derived_course']['id'] in {item['id'] for item in shelf['shelf']}
        outsider = client.get('/api/knowledge/courses', headers=outsider_h).json()
        assert copy['derived_course']['id'] not in {item['id'] for item in outsider['shelf'] + outsider['recommendations']}
        with SessionLocal() as db:
            course = db.get(DBCourse, copy["derived_course"]["id"])
            assert course.owner_public_id == learner.public_id and course.visibility == "private"
            assert db.query(DBCourseDocument).filter_by(course_id=course.id).one().content == "版本一正文"
            assert db.query(DBSourceDocument).filter_by(course_id=course.id).one().source_sha256 == "source-v1"
            source = db.query(DBSourceDocument).filter_by(course_id=course.id).one()
            assert source.legacy_document_id == db.query(DBCourseDocument).filter_by(course_id=course.id).one().id
            ref = db.query(DBSourceRef).filter_by(source_document_id=source.id).one()
            assert ref.quote == "版本一正文" and ref.id != "share-ref-flow"
            assert db.get(DBChapter, ref.chapter_id).course_id == course.id
            copied_source_id = source.id
        readable = client.get(f'/api/knowledge/sources/{copied_source_id}', headers=learner_h)
        assert readable.status_code == 200, readable.text
        assert readable.json()['content'] == '版本一正文'
        assert client.get(f'/api/knowledge/sources/{copied_source_id}', headers=outsider_h).status_code == 403


def test_three_way_conflict_requires_explicit_accept_or_ignore():
    with TestClient(app) as client:
        teacher_h, learner_h, _, _, _, course_id, class_id = _fixture(client, "update")
        first = _publish(client, teacher_h, course_id, class_id)
        copy = client.post(f"/api/v1/course-sharing/releases/{first['id']}/copies", headers=learner_h).json()
        with SessionLocal() as db:
            local = db.get(DBCourse, copy["derived_course"]["id"]); local.description = "接收方本地说明"; local.subject = '个人学习方向'; db.commit()
            upstream = db.get(DBCourse, course_id); upstream.version = "2.0"; upstream.description = "上游新版说明"; upstream.manifest_version = "manifest-v2"
            db.query(DBCourseDocument).filter_by(course_id=course_id).update({"content": "版本二正文", "content_hash": "hash-v2"}); db.commit()
        second = _publish(client, teacher_h, course_id, class_id, "可信机器学习 2.0")
        current = client.get("/api/v1/course-sharing/workspace", headers=learner_h).json()["copies"][0]
        preview = current["update_preview"]
        assert preview["release"]["id"] == second["id"]
        assert "course.description" in preview["conflicts"] and preview["conflict_count"] == 1
        assert 'course.title' not in preview['local_changes'], 'The automatic copy suffix is not a learner edit'
        description = next(item for item in preview['change_details'] if item['label']=='课程说明')
        assert description == {'label':'课程说明','before':'原始说明','local':'接收方本地说明','after':'上游新版说明','conflict':True}
        document = next(item for item in preview['change_details'] if item['label']=='资料：chapter.md')
        assert document['before']=='版本一正文' and document['after']=='版本二正文'
        stale = client.post(f"/api/v1/course-sharing/copies/{copy['id']}/decisions", headers=learner_h,
            json={"upstream_release_id": second["id"], "action": "accept", "reason": "接受新版并保留审计", "expected_version": 99})
        assert stale.status_code == 409
        accepted = client.post(f"/api/v1/course-sharing/copies/{copy['id']}/decisions", headers=learner_h,
            json={"upstream_release_id": second["id"], "action": "accept", "reason": "接受新版并保留审计", "expected_version": current["lock_version"]})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["derived_course"]["version"] == "2.0"
        assert accepted.json()["derived_course"]["title"].endswith("（派生副本）")
        with SessionLocal() as db:
            assert db.get(DBCourse,copy['derived_course']['id']).subject == '个人学习方向'
            decision = db.query(DBCourseShareDecision).filter_by(derived_copy_id=copy["id"]).one()
            assert decision.conflict_snapshot["local"]["course"]["description"] == "接收方本地说明"
            assert decision.conflict_snapshot["upstream"]["course"]["description"] == "上游新版说明"


@pytest.mark.parametrize('same_name_upload', [True, False])
def test_updated_material_preserves_old_reader_and_maps_each_frozen_version(same_name_upload):
    from app.course_sharing import copied_source_mapping
    suffix = 'same-name' if same_name_upload else 'changed-body'
    with TestClient(app) as client:
        teacher_h, learner_h, _, teacher, _, course_id, class_id = _fixture(client, suffix)
        before, after = '第一版数组选择20和40，合计60。', '第二版数组选择24和48，合计72。'
        def digest(body): return hashlib.sha256(body.encode()).hexdigest()
        with SessionLocal() as db:
            doc = db.get(DBCourseDocument, f'doc-{suffix}')
            doc.content, doc.content_hash = before, digest(before)
            source = db.get(DBSourceDocument, f'src-{suffix}')
            source.legacy_document_id = doc.id
            source.content_hash = source.processed_sha256 = digest(before)
            db.add(DBChapter(id=f'ch-{suffix}',course_id=course_id,source_document_id=source.id,
                stable_key='chapter-one',title='原材料',char_start=0,char_end=len(before)))
            db.flush()
            db.add(DBSourceRef(id=f'ref-{suffix}',source_document_id=source.id,chapter_id=f'ch-{suffix}',
                parser_version='test-v1',content_hash=digest(before),quote=before,char_start=0,char_end=len(before)))
            db.commit()
        first = _publish(client,teacher_h,course_id,class_id)
        copy = client.post(f"/api/v1/course-sharing/releases/{first['id']}/copies",headers=learner_h).json()
        cid = copy['derived_course']['id']
        with SessionLocal() as db:
            mapping = copied_source_mapping(db,db.get(DBCourse,cid),db.get(DBCourseShareRelease,first['id']).snapshot_data)
            old_source, old_ref = mapping[f'src-{suffix}'], mapping[f'ref-{suffix}']
            if same_name_upload:
                doc = DBKnowledgeDocument(id=f'new-doc-{suffix}',filename='chapter.md',title='新版材料',content=after,file_type='md')
                db.add(doc)
                source = DBSourceDocument(id=f'new-src-{suffix}',course_id=course_id,legacy_document_id=doc.id,
                    filename='chapter.md',file_format='md',title='新版材料',content_hash=digest(after),
                    processed_sha256=digest(after),source_sha256=digest(after),processing_status='ready',uploader_public_id=teacher.public_id)
                db.add(source);db.flush()
                ch = DBChapter(id=f'new-ch-{suffix}',course_id=course_id,source_document_id=source.id,
                    stable_key='new-chapter-one',title='新版材料',char_start=0,char_end=len(after))
                db.add(ch);db.flush()
            else:
                doc = db.get(DBCourseDocument,f'doc-{suffix}');doc.content,doc.content_hash = after,digest(after)
                source = db.get(DBSourceDocument,f'src-{suffix}')
                source.content_hash = source.processed_sha256 = digest(after)
                ch = db.get(DBChapter,f'ch-{suffix}');ch.title='新版材料';ch.char_end=len(after)
                ref = db.get(DBSourceRef,f'ref-{suffix}');ref.quote=after;ref.content_hash=digest(after);ref.char_end=len(after)
            db.commit()
        second = _publish(client,teacher_h,course_id,class_id,'新材料')
        current = client.get('/api/v1/course-sharing/workspace',headers=learner_h).json()['copies'][0]
        preview = current['update_preview']
        assert not preview['local_changes'], 'Copying sources must not invent local edits'
        assert any(after in x['after'] for x in preview['change_details']), 'Same-name additions must appear in the comparison'
        accepted = client.post(f"/api/v1/course-sharing/copies/{copy['id']}/decisions",headers=learner_h,
            json={'upstream_release_id':second['id'],'action':'accept','reason':'接收新材料，同时保留原学习依据','expected_version':current['lock_version']})
        assert accepted.status_code == 200,accepted.text
        read = client.get('/api/knowledge/sources/'+old_source,headers=learner_h)
        assert read.status_code == 200,read.text
        assert read.json()['content'] == before, 'An old note must still open the exact original body'
        with SessionLocal() as db:
            assert db.get(DBSourceRef,old_ref).quote == before
            assert db.get(DBSourceDocument,old_source).processed_sha256 == digest(before)
            mapping = copied_source_mapping(db,db.get(DBCourse,cid),db.get(DBCourseShareRelease,second['id']).snapshot_data)
            new_source = mapping[f'new-src-{suffix}' if same_name_upload else f'src-{suffix}']
            assert new_source != old_source
            if same_name_upload: assert mapping[f'src-{suffix}'] == old_source
        read = client.get('/api/knowledge/sources/'+new_source,headers=learner_h)
        assert read.status_code == 200,read.text
        assert read.json()['content'] == after


def test_scope_is_fail_closed_and_ignore_is_not_reoffered():
    with TestClient(app) as client:
        teacher_h, learner_h, outsider_h, _, _, course_id, class_id = _fixture(client, "scope")
        release = _publish(client, teacher_h, course_id, class_id)
        assert client.post(f"/api/v1/course-sharing/releases/{release['id']}/copies", headers=outsider_h).status_code == 403
        copy = client.post(f"/api/v1/course-sharing/releases/{release['id']}/copies", headers=learner_h).json()
        with SessionLocal() as db:
            course = db.get(DBCourse, course_id); course.version = "1.1"; course.manifest_version = "manifest-v1.1"; db.commit()
        latest = _publish(client, teacher_h, course_id, class_id, "1.1")
        current = client.get("/api/v1/course-sharing/workspace", headers=learner_h).json()["copies"][0]
        ignored = client.post(f"/api/v1/course-sharing/copies/{copy['id']}/decisions", headers=learner_h,
            json={"upstream_release_id": latest["id"], "action": "ignore", "reason": "保留本地教学版本", "expected_version": current["lock_version"]})
        assert ignored.status_code == 200 and ignored.json()["upstream_status"] == "current"
        assert ignored.json()["update_preview"]["decision"]["action"] == "ignore"
        assert client.post(f"/api/v1/course-sharing/copies/{copy['id']}/decisions", headers=outsider_h,
            json={"upstream_release_id": latest["id"], "action": "accept", "reason": "越权接受更新版本", "expected_version": 2}).status_code == 403


def test_withdrawal_propagates_status_without_deleting_copy_history():
    with TestClient(app) as client:
        teacher_h, learner_h, _, _, _, course_id, class_id = _fixture(client, "withdraw")
        release = _publish(client, teacher_h, course_id, class_id)
        copy = client.post(f"/api/v1/course-sharing/releases/{release['id']}/copies", headers=learner_h).json()
        withdrawal = client.post(f"/api/v1/course-governance/courses/{course_id}/withdraw", headers=teacher_h,
            json={"reason": "上游课程来源撤回但保留历史", "expected_status": "published"})
        assert withdrawal.status_code == 200
        propagated = client.post("/api/v1/course-sharing/withdrawals/propagate", headers=teacher_h)
        assert propagated.json() == {"release_count": 1, "copy_count": 1, "historical_copies_deleted": 0}
        historical = client.get("/api/v1/course-sharing/workspace", headers=learner_h)
        assert historical.status_code == 200
        assert historical.json()["copies"][0]["upstream_status"] == "withdrawn"
        assert historical.json()["releases"][0]["status"] == "withdrawn"
        with SessionLocal() as db:
            assert db.get(DBCourseShareRelease, release["id"]).status == "withdrawn"
            assert db.get(DBCourseDerivedCopy, copy["id"]).upstream_status == "withdrawn"
            assert db.get(DBCourse, copy["derived_course"]["id"]).status == "published"
            assert db.query(DBCourseDocument).filter_by(course_id=copy["derived_course"]["id"]).count() == 1


def test_migration_enforces_release_and_decision_immutability():
    with SessionLocal() as db:
        release = db.query(DBCourseShareRelease).first(); decision = db.query(DBCourseShareDecision).first()
        assert release is not None and decision is not None
        with pytest.raises(DatabaseError):
            db.execute(text("UPDATE course_share_releases SET title='tampered' WHERE id=:id"), {"id": release.id}); db.commit()
        db.rollback()
        with pytest.raises(DatabaseError):
            db.execute(text("DELETE FROM course_share_decisions WHERE id=:id"), {"id": decision.id}); db.commit()
        db.rollback()
