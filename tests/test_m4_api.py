from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import DBUser
from app.main import app


def test_m4_benchmark_api_is_operator_only_and_never_returns_gold():
    client = TestClient(app)
    teacher = DBUser(public_id="usr-m4-teacher", username="m4-teacher", role="teacher", is_active=True)
    app.dependency_overrides[get_current_user] = lambda: teacher
    try:
        response = client.get("/api/v1/m4/benchmark")
        assert response.status_code == 200
        assert response.json()["case_count"] == 60
        assert response.json()["gold_included"] is False

        app.dependency_overrides[get_current_user] = lambda: DBUser(
            public_id="usr-m4-student", username="m4-student", role="student", is_active=True
        )
        assert client.get("/api/v1/m4/benchmark").status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
