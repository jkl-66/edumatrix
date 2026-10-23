from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import DBCourse, DBCourseMembership, DBTeachingClassMember, DBTeachingTask, DBUser, SessionLocal
from app.main import app
from tests.api_test_helpers import TEST_PASSWORD, auth_headers


def _user(username: str) -> DBUser:
    with SessionLocal() as db:
        return db.query(DBUser).filter_by(username=username).one()


def _fixture(client: TestClient, suffix: str):
    teacher_name, learner_name, outsider_name = (f"{name}_{suffix}" for name in ("gov_teacher", "gov_learner", "gov_outsider"))
    auth_headers(client, teacher_name)
    learner_headers = auth_headers(client, learner_name)
    outsider_headers = auth_headers(client, outsider_name)
    with SessionLocal() as db:
        db.query(DBUser).filter_by(username=teacher_name).update({"role":"teacher"}); db.commit()
    teacher_login = client.post("/api/auth/login",data={"username":teacher_name,"password":TEST_PASSWORD})
    assert teacher_login.status_code == 200
    teacher_headers = {"Authorization":f"Bearer {teacher_login.json()['access_token']}"}
    teacher, learner = _user(teacher_name), _user(learner_name)
    course_id = f"course-gov-{suffix}"
    with SessionLocal() as db:
        db.add(DBCourse(id=course_id, version="1", title="AI 工程治理", visibility="private", status="published",
                        owner_public_id=teacher.public_id, manifest_version="gov-1"))
        db.add(DBCourseMembership(course_id=course_id, user_public_id=teacher.public_id, role="teacher", status="active"))
        db.add(DBCourseMembership(course_id=course_id, user_public_id=learner.public_id, role="student", status="active"))
        db.commit()
    return teacher_headers, learner_headers, outsider_headers, teacher, learner, course_id


def test_class_group_member_task_publish_and_learner_visibility():
    with TestClient(app) as client:
        teacher_h, learner_h, _, _, learner, course_id = _fixture(client, "flow")
        catalog = client.get("/api/v1/course-governance/catalog", headers=teacher_h)
        assert catalog.status_code == 200
        assert course_id in {item["id"] for item in catalog.json()["courses"]}
        assert learner.public_id in {item["public_id"] for item in catalog.json()["candidate_members"]}
        classroom = client.post("/api/v1/course-governance/classes", headers=teacher_h,
                                json={"course_id":course_id,"title":"2026 AI 一班","term":"2026 秋"})
        assert classroom.status_code == 201, classroom.text
        classroom = classroom.json()
        grouped = client.post(f"/api/v1/course-governance/classes/{classroom['id']}/groups", headers=teacher_h,
                              json={"name":"A 组","description":"检索实验组"}).json()
        group_id = grouped["groups"][0]["id"]
        enrolled = client.put(f"/api/v1/course-governance/classes/{classroom['id']}/members", headers=teacher_h,
                              json={"user_public_id":learner.public_id,"role":"student","group_id":group_id,"expected_version":None})
        assert enrolled.status_code == 200, enrolled.text
        assert enrolled.json()["members"][0]["group_id"] == group_id
        task = client.post(f"/api/v1/course-governance/classes/{classroom['id']}/tasks", headers=teacher_h,
                           json={"title":"完成阈值校准","instructions":"提交实验结果。","group_id":group_id,
                                 "due_at":"2026-09-30T12:00:00","idempotency_key":"task-flow-001"})
        assert task.status_code == 201
        task_row = task.json()["tasks"][0]
        published = client.post(f"/api/v1/course-governance/tasks/{task_row['id']}/publish", headers=teacher_h,
                                json={"expected_version":task_row["lock_version"]})
        assert published.status_code == 200 and published.json()["tasks"][0]["status"] == "published"
        learner_view = client.get(f"/api/v1/course-governance/classes/{classroom['id']}", headers=learner_h)
        assert learner_view.status_code == 200
        assert learner_view.json()["can_manage"] is False
        assert len(learner_view.json()["members"]) == 1 and len(learner_view.json()["tasks"]) == 1
        with SessionLocal() as db:
            membership = db.query(DBCourseMembership).filter_by(course_id=course_id,user_public_id=learner.public_id).one()
            assert membership.status == "active" and membership.role == "student"


def test_permissions_group_scope_version_and_idempotency_are_fail_closed():
    with TestClient(app) as client:
        teacher_h, learner_h, outsider_h, _, learner, course_id = _fixture(client, "security")
        first = client.post("/api/v1/course-governance/classes",headers=teacher_h,json={"course_id":course_id,"title":"治理班","term":"2026"}).json()
        second = client.post("/api/v1/course-governance/classes",headers=teacher_h,json={"course_id":course_id,"title":"另一班","term":"2026"}).json()
        foreign_group = client.post(f"/api/v1/course-governance/classes/{second['id']}/groups",headers=teacher_h,json={"name":"外班组","description":""}).json()["groups"][0]
        denied = [
            client.post("/api/v1/course-governance/classes",headers=learner_h,json={"course_id":course_id,"title":"越权班","term":"2026"}),
            client.get(f"/api/v1/course-governance/classes/{first['id']}",headers=outsider_h),
            client.put(f"/api/v1/course-governance/classes/{first['id']}/members",headers=learner_h,
                       json={"user_public_id":learner.public_id,"role":"student","group_id":None,"expected_version":None}),
        ]
        assert [item.status_code for item in denied] == [403,403,403]
        wrong_group = client.put(f"/api/v1/course-governance/classes/{first['id']}/members",headers=teacher_h,
                                 json={"user_public_id":learner.public_id,"role":"student","group_id":foreign_group["id"],"expected_version":None})
        assert wrong_group.status_code == 422
        created = client.post(f"/api/v1/course-governance/classes/{first['id']}/tasks",headers=teacher_h,
                              json={"title":"任务 A","instructions":"A","group_id":None,"due_at":None,"idempotency_key":"same-task-key"})
        replay = client.post(f"/api/v1/course-governance/classes/{first['id']}/tasks",headers=teacher_h,
                             json={"title":"任务 A","instructions":"A","group_id":None,"due_at":None,"idempotency_key":"same-task-key"})
        conflict = client.post(f"/api/v1/course-governance/classes/{first['id']}/tasks",headers=teacher_h,
                               json={"title":"任务 B","instructions":"B","group_id":None,"due_at":None,"idempotency_key":"same-task-key"})
        task = created.json()["tasks"][0]
        stale = client.post(f"/api/v1/course-governance/tasks/{task['id']}/publish",headers=teacher_h,json={"expected_version":99})
        assert replay.status_code == 201 and len(replay.json()["tasks"]) == 1
        assert conflict.status_code == stale.status_code == 409


def test_course_withdrawal_freezes_impact_and_preserves_history():
    with TestClient(app) as client:
        teacher_h, learner_h, _, _, learner, course_id = _fixture(client, "withdraw")
        classroom = client.post("/api/v1/course-governance/classes",headers=teacher_h,json={"course_id":course_id,"title":"撤回班","term":"2026"}).json()
        client.put(f"/api/v1/course-governance/classes/{classroom['id']}/members",headers=teacher_h,
                   json={"user_public_id":learner.public_id,"role":"student","group_id":None,"expected_version":None})
        task_view = client.post(f"/api/v1/course-governance/classes/{classroom['id']}/tasks",headers=teacher_h,
                                json={"title":"待撤回任务","instructions":"历史保留","group_id":None,"due_at":None,"idempotency_key":"withdraw-task"}).json()
        task = task_view["tasks"][0]
        client.post(f"/api/v1/course-governance/tasks/{task['id']}/publish",headers=teacher_h,json={"expected_version":task["lock_version"]})
        withdrawal = client.post(f"/api/v1/course-governance/courses/{course_id}/withdraw",headers=teacher_h,
                                 json={"reason":"课程来源版本需要停止教学并保留历史记录","expected_status":"published"})
        assert withdrawal.status_code == 200, withdrawal.text
        impact = withdrawal.json()["impact_snapshot"]
        assert impact["class_count"] == impact["class_member_count"] == impact["task_count"] == 1
        assert impact["historical_learning_evidence_deleted"] == 0
        assert impact["learner_membership_suspended_count"] == 1
        assert impact["manager_membership_preserved_count"] == 1
        repeated = client.post(f"/api/v1/course-governance/courses/{course_id}/withdraw",headers=teacher_h,
                               json={"reason":"课程来源版本需要停止教学并保留历史记录","expected_status":"published"})
        assert repeated.status_code == 200 and repeated.json()["id"] == withdrawal.json()["id"]
        assert client.get(f"/api/v1/course-governance/classes/{classroom['id']}",headers=learner_h).status_code == 403
        with SessionLocal() as db:
            assert db.get(DBCourse,course_id).status == "withdrawn"
            assert db.get(DBTeachingTask,task["id"]).status == "withdrawn"
            assert db.query(DBTeachingClassMember).filter_by(class_id=classroom["id"],user_public_id=learner.public_id).one().status == "suspended"
            memberships = {item.role:item.status for item in db.query(DBCourseMembership).filter_by(course_id=course_id).all()}
            assert memberships == {"teacher":"active","student":"suspended"}


def test_migration_contains_governance_tables_and_immutable_withdrawal():
    import pytest
    from app.database import engine
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import DatabaseError
    tables = set(inspect(engine).get_table_names())
    assert {"teaching_classes","teaching_groups","teaching_class_members","teaching_tasks","course_withdrawals"} <= tables
    with SessionLocal() as db:
        # The database trigger is the final guard even if application code is bypassed.
        row = db.execute(text("SELECT id FROM course_withdrawals LIMIT 1")).first()
        assert row is not None
        with pytest.raises(DatabaseError):
            db.execute(text("UPDATE course_withdrawals SET reason='tampered' WHERE id=:id"),{"id":row.id}); db.commit()
        db.rollback()
