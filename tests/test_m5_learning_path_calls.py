from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBModelCall, DBUser, SessionLocal
from app.main import app
from app.m5_legacy_calls import audited_legacy_sync_text_call
from learning_strategy import _review_candidate_route_with_planner
import llm_client
from tests.api_test_helpers import auth_headers


class Backend:
    model = "planner-test-model"

    def __init__(self, output=None, *, error=None):
        self.output = output
        self.error = error
        self.calls = 0

    def generate(self, system_prompt, user_prompt, *, role):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.output


def _fixture():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    session.add(DBUser(
        public_id="planner-owner-public", username="planner-owner",
        hashed_password="test", role="student", is_active=True,
    ))
    session.commit()
    return session, factory


def test_sync_planner_call_records_owner_and_minimal_summary():
    session, factory = _fixture()
    output = audited_legacy_sync_text_call(
        Backend("planner guidance"),
        system_prompt="system",
        user_prompt="private route and profile",
        role="路径规划师",
        operation="learning_path_review",
        capability="plan",
        owner_public_id="planner-owner-public",
        input_summary={
            "route_node_count": 2,
            "profile_payload_included": False,
        },
        session_factory=factory,
    )
    row = session.query(DBModelCall).one()

    assert output == "planner guidance"
    assert row.owner_public_id == "planner-owner-public"
    assert (row.status, row.error_code) == ("completed", "")
    assert "private route" not in str(row.input_summary)
    assert row.prompt_version == "legacy_learning_path_review:1.0"
    session.close()


def test_sync_planner_provider_failure_is_terminal():
    session, factory = _fixture()
    backend = Backend(error=RuntimeError("planner unavailable"))

    try:
        audited_legacy_sync_text_call(
            backend,
            system_prompt="system",
            user_prompt="private route",
            role="路径规划师",
            operation="learning_path_review",
            capability="plan",
            owner_public_id="planner-owner-public",
            input_summary={"profile_payload_included": False},
            session_factory=factory,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("provider error should propagate to caller fallback")

    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == (
        "failed", "learning_path_review_provider_failed",
    )
    session.close()


def test_unowned_internal_route_review_does_not_call_model(monkeypatch):
    backend = Backend("must not be used")
    monkeypatch.setattr(llm_client, "DEFAULT_LLM", backend)

    result = _review_candidate_route_with_planner(
        candidate_path=["A", "B"],
        route_nodes=[{"concept": "B", "action": "learn", "reason": "gap"}],
        target="B",
        final_goal="B",
        cognitive_load=0.4,
        frustration=0.1,
        audit={"passed": True},
        session_plan={"today_concepts": ["B"]},
        owner_public_id=None,
    )

    assert backend.calls == 0
    assert result["llm_backend"] == "deterministic-fallback-unowned"
    assert "B" in result["personalized_guidance"]


def test_learning_path_get_is_read_only_for_model_calls(monkeypatch):
    backend = Backend("must not be used")
    monkeypatch.setattr(llm_client, "DEFAULT_LLM", backend)

    with TestClient(app) as client:
        username = "learning_path_read_only"
        headers = auth_headers(client, username)
        with SessionLocal() as session:
            before = session.query(DBModelCall).count()

        response = client.get(
            f"/api/profile/{username}/learning-path",
            headers=headers,
        )

        with SessionLocal() as session:
            after = session.query(DBModelCall).count()

    assert response.status_code == 200, response.text
    assert response.json()["adaptive_route"]["planner_review"]["llm_backend"] == (
        "deterministic-fallback-unowned"
    )
    assert backend.calls == 0
    assert after == before
