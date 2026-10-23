from datetime import datetime

from fastapi.testclient import TestClient

from app.auth import get_password_hash
from app.database import DBCompetitionJourneyRun, DBCourseMembership, DBUser, SessionLocal
from app.main import app
from tests.api_test_helpers import TEST_PASSWORD, auth_headers


def _admin(username: str) -> dict[str, str]:
    with SessionLocal() as db:
        user = db.query(DBUser).filter_by(username=username).first()
        if user is None:
            db.add(DBUser(username=username, display_name="FC5 演示管理员", hashed_password=get_password_hash(TEST_PASSWORD), role="admin"))
        else:
            user.role = "admin"
        db.commit()
    with TestClient(app) as client:
        return auth_headers(client, username)


def test_showcase_is_admin_only_and_empty_state_is_truthful():
    suffix = datetime.utcnow().strftime("%H%M%S%f")
    admin_name, student_name = f"fc5_show_admin_{suffix}", f"fc5_show_student_{suffix}"
    admin = _admin(admin_name)
    with TestClient(app) as client:
        student = auth_headers(client, student_name)
        assert client.get("/api/v1/competition-showcase", headers=student).status_code == 403
        response = client.get("/api/v1/competition-showcase", headers=admin)
        assert response.status_code == 200
        body = response.json()
        assert body["schema_version"] == "fc5.showcase-context.v1"
        assert body["total_count"] == 6 and body["truthfulness"]["external_network_required"] is False


def test_showcase_bootstrap_is_idempotent_and_does_not_complete_journeys():
    suffix = datetime.utcnow().strftime("%H%M%S%f")
    username = f"fc5_show_boot_{suffix}"
    headers = _admin(username)
    with TestClient(app) as client:
        first = client.post("/api/v1/competition-showcase/bootstrap", headers=headers)
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["initialized"] is True and body["ready_count"] == 6
        assert body["context"]["course"]["id"] == "course-rag-engineering-m0"
        assert body["roles"]["teacher"]["local_demo_password"] == "EduMatrix-FC-Demo"
        assert body["roles"]["learner"]["local_demo_password"] == "EduMatrix-FC-Demo"
        for journey in ("student", "media", "teacher", "enterprise", "marketplace", "integration"):
            workspace = client.get(f"/api/v1/competition-journeys/{journey}", headers=headers)
            assert workspace.status_code == 200, f"{journey}: {workspace.text}"
        second = client.post("/api/v1/competition-showcase/bootstrap", headers=headers)
        assert second.status_code == 200, second.text
        assert second.json()["context"] == body["context"]
        readback = client.get("/api/v1/competition-showcase", headers=headers).json()
        assert "local_demo_password" not in readback["roles"]["teacher"]
    with SessionLocal() as db:
        admin = db.query(DBUser).filter_by(username=username).one()
        memberships = db.query(DBCourseMembership).filter_by(course_id="course-rag-engineering-m0", status="active").all()
        assert any(row.user_public_id == admin.public_id and row.role == "admin" for row in memberships)
        assert db.query(DBCompetitionJourneyRun).filter_by(owner_public_id=admin.public_id).count() == 0
