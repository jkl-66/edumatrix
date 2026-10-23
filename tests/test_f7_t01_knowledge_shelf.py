from __future__ import annotations

from fastapi.testclient import TestClient

from app.database import DBCourse, DBCourseMembership, DBStudentProfile, SessionLocal
from app.main import app
from tests.api_test_helpers import auth_headers


FLAGSHIP_COURSE_ID = "course-machine-learning-foundations-v1"


def _course(payload: dict, course_id: str) -> dict:
    return next(
        item
        for section in (payload["shelf"], payload["recommendations"])
        for item in section
        if item["id"] == course_id
    )


def test_new_student_sees_preloaded_reviewed_ai_course_without_upload() -> None:
    with TestClient(app) as client:
        headers = auth_headers(client, "f7_t01_new_student")
        response = client.get("/api/knowledge/courses", headers=headers)

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["schema_version"] == "edumatrix.knowledge-course-shelf.v1"
        assert payload["requires_course_upload"] is False
        assert payload["shelf"]
        flagship = _course(payload, FLAGSHIP_COURSE_ID)
        assert flagship["in_shelf"] is True
        assert flagship["shelf_origin"] == "team_preloaded"
        assert flagship["requires_upload"] is False
        assert flagship["authority_status"] == "authoritative"
        assert flagship["review_status"] == "approved"
        assert flagship["source_health"] == "ready"
        assert flagship["index_status"] == "ready"
        assert flagship["chapter_count"] == 12
        assert flagship["document_count"] == 12
        assert flagship["knowledge_point_count"] == 13
        assert flagship["source_count"] == 12
        assert flagship["ready_source_count"] == 12
        assert flagship["indexed_document_count"] == 12
        assert flagship["chapter_preview"]

        outline = client.get(
            f"/api/v1/courses/{FLAGSHIP_COURSE_ID}/outline",
            headers=headers,
        )
        assert outline.status_code == 200, outline.text
        source_document_id = outline.json()[0]["source_document_id"]
        source = client.get(
            f"/api/knowledge/sources/{source_document_id}",
            headers=headers,
        )
        assert source.status_code == 200, source.text
        assert source.json()["course_id"] == FLAGSHIP_COURSE_ID
        assert source.json()["content"].strip()

        assert payload["discovery"]["route"] == "/knowledge/discover"
        assert "候选来源" in payload["discovery"]["authority_boundary"]


def test_recommendations_use_explainable_profile_or_neutral_basis_only() -> None:
    username = "f7_t01_profile_student"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        with SessionLocal() as session:
            profile = session.get(DBStudentProfile, username)
            if profile is None:
                profile = DBStudentProfile(student_id=username)
                session.add(profile)
            profile.target_course = "边缘人工智能与嵌入式机器学习"
            profile.learning_goals = ["掌握边缘模型部署"]
            session.commit()

        response = client.get("/api/knowledge/courses", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["profile_basis"]["mode"] == "profile_evidence"
        assert "边缘" in payload["profile_basis"]["labels"]
        assert payload["recommendations"]
        assert all(item["authority_status"] == "authoritative" for item in payload["recommendations"])
        assert all(item["review_status"] in {"approved", "source_review_required"} for item in payload["recommendations"])
        assert all(item["recommendation_reason"] for item in payload["recommendations"])
        recommendation_ids = [item["id"] for item in payload["recommendations"]]
        assert recommendation_ids[0] == "course-embedded-machine-learning-engineering-v2"
        assert "course-embedded-edge-intelligence-v1" in recommendation_ids
        assert "边缘" in payload["recommendations"][0]["recommendation_reason"]


def test_adding_reviewed_public_course_to_shelf_is_idempotent() -> None:
    username = "f7_t01_shelf_member"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        initial = client.get("/api/knowledge/courses", headers=headers)
        assert initial.status_code == 200, initial.text
        recommendation = initial.json()["recommendations"][0]

        first = client.post(
            f"/api/knowledge/courses/{recommendation['id']}/shelf",
            headers=headers,
        )
        second = client.post(
            f"/api/knowledge/courses/{recommendation['id']}/shelf",
            headers=headers,
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["created"] is True
        assert second.json()["created"] is False
        assert first.json()["course"]["id"] == recommendation["id"]
        assert second.json()["course"]["in_shelf"] is True
        with SessionLocal() as session:
            course = session.get(DBCourse, recommendation["id"])
            assert course is not None
            assert session.query(DBCourseMembership).filter_by(
                course_id=recommendation["id"],
                status="active",
            ).count() >= 1


def test_course_shelf_requires_authentication_and_never_lists_raw_repositories() -> None:
    with TestClient(app) as client:
        assert client.get("/api/knowledge/courses").status_code == 401
        headers = auth_headers(client, "f7_t01_authority_reader")
        payload = client.get("/api/knowledge/courses", headers=headers).json()
        course_ids = {
            item["id"]
            for section in (payload["shelf"], payload["recommendations"])
            for item in section
        }
        assert course_ids
        assert not any("github_repos" in course_id for course_id in course_ids)
        assert all(item["authority_status"] == "authoritative" for item in payload["shelf"])
