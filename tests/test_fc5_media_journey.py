from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.competition_journey_api as journey_api
from app.auth import get_current_user, get_password_hash
from app.database import (
    Base, DBArtifact, DBArtifactVersion, DBChapter, DBChapterVideoLink,
    DBCompetitionJourneyRun, DBCourse, DBResourceBundle, DBResourceBundleItem,
    DBResourceBundleVersion, DBSourceDocument, DBUser, DBVideoOutputVersion,
    DBVideoPracticeSet, DBVideoPracticeVersion, DBVideoProject, DBVideoRenderTask,
    DBVideoScriptVersion, DBWebDeck, DBWebDeckVersion,
)
from app.main import app
from app.migrations import apply_registered_migrations


def fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    apply_registered_migrations(engine)
    db = sessionmaker(bind=engine)()
    owner = DBUser(public_id="media-owner", username="media-owner", display_name="媒体创作者", hashed_password=get_password_hash("pw"), role="student")
    other = DBUser(public_id="media-other", username="media-other", display_name="其他用户", hashed_password=get_password_hash("pw"), role="student")
    course = DBCourse(id="media-course", version="v1", title="媒体课程", status="published", manifest_version="m1")
    db.add_all([owner, other, course]); db.commit()
    return db, owner, other, course


def client(monkeypatch, db, user):
    async def fake(operation):
        return operation(db)
    monkeypatch.setattr(journey_api, "run_db_op", fake)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_media_visits_do_not_complete_and_type_isolation(monkeypatch):
    db, owner, other, course = fixture()
    c = client(monkeypatch, db, owner)
    try:
        response = c.post("/api/v1/competition-journeys/media/runs", json={"course_id": course.id, "run_key": "media-run"})
        assert response.status_code == 201, response.text
        run = response.json()
        assert run["journey_type"] == "media" and run["progress"] == {"completed": 0, "total": 7, "percent": 0}
        for step in run["steps"]:
            visit = c.post(f"/api/v1/competition-journeys/media/runs/{run['id']}/visits", json={"step_key": step["key"], "route": step["route"]})
            assert visit.status_code == 201, visit.text
        refreshed = c.get(f"/api/v1/competition-journeys/media/runs/{run['id']}").json()
        assert refreshed["progress"]["completed"] == 0 and len(refreshed["visits"]) == 7
        student = c.post("/api/v1/competition-journeys/student/runs", json={"course_id": course.id, "run_key": "student-run"}).json()
        assert c.get(f"/api/v1/competition-journeys/media/runs/{student['id']}").status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    c = client(monkeypatch, db, other)
    try:
        assert c.get(f"/api/v1/competition-journeys/media/runs/{run['id']}").status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_media_canonical_evidence_requires_final_bundle(monkeypatch):
    db, owner, _, course = fixture()
    c = client(monkeypatch, db, owner)
    try:
        run = c.post("/api/v1/competition-journeys/media/runs", json={"course_id": course.id, "run_key": "evidence-run"}).json()
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    source = DBSourceDocument(course_id=course.id, title="章节来源", filename="chapter.md", file_format="md", content_hash="1" * 64)
    db.add(source); db.flush()
    chapter = DBChapter(course_id=course.id, source_document_id=source.id, stable_key="chapter-1", title="第一章", position=1)
    handout = DBArtifact(owner_public_id=owner.public_id, course_id=course.id, artifact_type="handout", title="讲义", status="approved")
    db.add_all([chapter, handout]); db.flush()
    handout_version = DBArtifactVersion(artifact_id=handout.id, version_number=1, content="# 讲义", content_format="markdown", content_hash="2" * 64, created_by_public_id=owner.public_id)
    db.add(handout_version); db.flush(); handout.current_version_id = handout_version.id
    deck = DBWebDeck(owner_public_id=owner.public_id, course_id=course.id, title="课件")
    db.add(deck); db.flush()
    deck_version = DBWebDeckVersion(deck_id=deck.id, version_number=1, slides_snapshot=[{"title": "第一章"}], theme_snapshot={}, content_hash="3" * 64, created_by_public_id=owner.public_id)
    db.add(deck_version); db.flush(); deck.current_version_id = deck_version.id
    project = DBVideoProject(owner_public_id=owner.public_id, course_id=course.id, title="课程视频")
    db.add(project); db.flush()
    script = DBVideoScriptVersion(project_id=project.id, version_number=1, scenes=[{"narration": "讲解"}], total_duration_ms=1000, content_hash="4" * 64, created_by_public_id=owner.public_id)
    db.add(script); db.flush(); project.current_script_version_id = script.id
    task = DBVideoRenderTask(project_id=project.id, script_version_id=script.id, owner_public_id=owner.public_id, idempotency_key="media-render", status="completed", progress=100, audio_status="text_only")
    db.add(task); db.flush()
    output = DBVideoOutputVersion(project_id=project.id, render_task_id=task.id, owner_public_id=owner.public_id, version_number=1, output_manifest={"files": []}, output_dir="isolated", mp4_sha256="5" * 64, duration_ms=1000, quality_report={"passed": True})
    db.add(output); db.flush(); task.output_version_id = output.id
    link = DBChapterVideoLink(owner_public_id=owner.public_id, course_id=course.id, chapter_id=chapter.id, video_project_id=project.id, input_hash="6" * 64, truth_boundary="synthetic fixture")
    db.add(link); db.flush()
    practice = DBVideoPracticeSet(owner_public_id=owner.public_id, chapter_video_link_id=link.id, course_id=course.id)
    db.add(practice); db.flush()
    practice_version = DBVideoPracticeVersion(practice_set_id=practice.id, version_number=1, question_version_ids=[], interactive_lab_instance_ids=[], binding_snapshot=[], content_hash="7" * 64, created_by_public_id=owner.public_id)
    db.add(practice_version); db.flush(); practice.current_version_id = practice_version.id
    db.commit()

    c = client(monkeypatch, db, owner)
    try:
        before = c.get(f"/api/v1/competition-journeys/media/runs/{run['id']}").json()
        assert before["progress"]["completed"] == 6
        assert next(x for x in before["steps"] if x["key"] == "bundle")["complete"] is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    bundle = DBResourceBundle(owner_public_id=owner.public_id, course_id=course.id, title="完整资源包", learning_objective="完成第一章")
    db.add(bundle); db.flush()
    bundle_version = DBResourceBundleVersion(bundle_id=bundle.id, version_number=1, profile_snapshot={"data_class": "synthetic"}, quality_summary={"coverage": .375}, content_hash="8" * 64, created_by_public_id=owner.public_id)
    db.add(bundle_version); db.flush(); bundle.current_version_id = bundle_version.id
    for position, (kind, resource_id, version_id) in enumerate((("handout", handout.id, handout_version.id), ("ppt", deck.id, deck_version.id), ("video", project.id, script.id))):
        db.add(DBResourceBundleItem(bundle_version_id=bundle_version.id, position=position, resource_type=kind, resource_id=resource_id, resource_version_id=version_id, frozen_snapshot={"data_class": "synthetic"}))
    db.commit()
    c = client(monkeypatch, db, owner)
    try:
        final = c.get(f"/api/v1/competition-journeys/media/runs/{run['id']}")
        assert final.status_code == 200, final.text
        body = final.json(); assert body["status"] == "completed" and body["progress"]["completed"] == 7
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_migration_056_preserves_student_run(monkeypatch):
    db, owner, _, course = fixture()
    assert db.execute(text("select count(*) from schema_migrations where version='20260805_056'")).scalar_one() == 1
    student = DBCompetitionJourneyRun(owner_public_id=owner.public_id, course_id=course.id, journey_type="student", run_key="preserved", baseline_snapshot={}, baseline_hash="9" * 64)
    db.add(student); db.commit()
    assert db.query(DBCompetitionJourneyRun).filter_by(journey_type="student", run_key="preserved").one().id == student.id
