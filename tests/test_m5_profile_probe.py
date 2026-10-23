import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import agent_swarm
from agent_swarm import EduMatrixSwarm, ProfileProbeAgent
from app.database import Base, DBModelCall
from models import StudentProfile


class Backend:
    model = "profile-test-model"

    def __init__(self, output):
        self.output = output

    async def generate(self, system_prompt, user_prompt, *, role):
        return self.output


def _fixture(output):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    async def database_runner(operation, *args):
        return operation(session, *args)

    return session, ProfileProbeAgent(Backend(output), database_runner=database_runner)


def test_profile_probe_fast_path_does_not_pretend_to_call_model():
    session, probe = _fixture("not used")
    profile = StudentProfile(student_id="profile-owner", concept_mastery={"逻辑回归": 0.5})
    asyncio.run(probe.async_update(
        profile,
        "什么是逻辑回归？",
        owner_public_id="profile-owner",
        course_id="profile-course",
    ))
    assert session.query(DBModelCall).count() == 0
    assert "逻辑回归" in profile.weak_points


def test_profile_probe_records_valid_call_and_filters_unknown_concepts():
    session, probe = _fixture(
        '{"weak_points":["逻辑回归","伪造知识点"],'
        '"mastery_updates":{"逻辑回归":0.1,"伪造知识点":0.9},'
        '"learning_state_causes":["prerequisite_gap"]}'
    )
    profile = StudentProfile(student_id="profile-owner", concept_mastery={"逻辑回归": 0.5})
    asyncio.run(probe.async_update(
        profile,
        "我总是分不清逻辑回归和另一个分类器",
        owner_public_id="profile-owner",
        course_id="profile-course",
    ))
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("completed", "")
    assert row.prompt_version == "legacy_profile_extraction:1.0"
    assert row.owner_public_id == "profile-owner"
    assert "伪造知识点" not in profile.weak_points
    assert "伪造知识点" not in profile.concept_mastery
    assert profile.concept_mastery["逻辑回归"] > 0.5


def test_profile_probe_records_invalid_output_without_profile_pollution():
    session, probe = _fixture('{"weak_points":"not-a-list"}')
    profile = StudentProfile(student_id="profile-owner", concept_mastery={"逻辑回归": 0.5})
    asyncio.run(probe.async_update(
        profile,
        "我对分类模型的边界存在复杂困惑",
        owner_public_id="profile-owner",
        course_id="profile-course",
    ))
    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "profile_output_invalid")
    assert "not-a-list" not in profile.weak_points
    assert profile.concept_mastery["逻辑回归"] == 0.5


def test_swarm_intent_wrapper_reuses_shared_service_with_ownership(monkeypatch):
    captured = {}

    async def fake_classify(llm, message, **kwargs):
        captured.update({"llm": llm, "message": message, **kwargs})
        return {"is_academic": True, "reason": "shared", "reply": ""}

    monkeypatch.setattr(agent_swarm, "classify_academic_intent", fake_classify)
    backend = Backend("{}")
    swarm = EduMatrixSwarm(llm=backend)
    result = asyncio.run(swarm._check_academic_intent(
        "shared intent",
        owner_public_id="profile-owner",
        course_id="profile-course",
    ))
    assert result["reason"] == "shared"
    assert captured == {
        "llm": backend,
        "message": "shared intent",
        "owner_public_id": "profile-owner",
        "course_id": "profile-course",
    }
