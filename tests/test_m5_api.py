from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import DBUser
from app.main import app


def test_m5_capability_api_is_authenticated_and_does_not_claim_missing_models():
    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: DBUser(
        public_id="usr-m5-student", username="m5-student", role="student", is_active=True,
    )
    try:
        status = client.get("/api/v1/m5/capabilities")
        assert status.status_code == 200
        body = status.json()
        assert body["user_configurable_secrets"] is False
        assert body["runtime"]["text_model"] is False

        route = client.post("/api/v1/m5/route", json={
            "contract": {"idempotency_key": "api-m5-001"},
            "message": "普通问答",
        })
        assert route.status_code == 200
        assert route.json()["status"] == "unavailable"
        assert route.json()["capability"] == "answer"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
