import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, DBModelCall
from models import CauseBreakdown, StudentProfile
from profile_api import NarrativeReportGenerator


class Backend:
    model = "profile-report-test-model"

    def __init__(self, outputs):
        self.outputs = outputs

    async def generate(self, system_prompt, user_prompt, *, role):
        value = self.outputs[role]
        if isinstance(value, BaseException):
            raise value
        return value


def _fixture(outputs):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    async def database_runner(operation, *args):
        return operation(session, *args)

    profile = StudentProfile(
        student_id="private-student",
        target_course="private-course",
        concept_mastery={"private-concept": 0.42},
        learning_state_causes={
            "gap": CauseBreakdown(
                key="gap",
                label="private-cause",
                percentage=73,
                confidence=0.8,
                evidence_count=1,
            )
        },
    )
    return session, NarrativeReportGenerator(
        Backend(outputs), database_runner=database_runner,
    ), profile


def test_profile_report_agents_share_trace_owner_and_minimal_summary():
    session, generator, profile = _fixture({
        "教师评估": "teacher advice",
        "叙事故事生成": "narrative output",
        "仪表盘诊断生成": "dashboard output",
    })

    narrative, dashboard = asyncio.run(generator.generate_report(
        profile, owner_public_id="profile-owner", trace_id="profile-shared-trace",
    ))
    rows = session.query(DBModelCall).order_by(DBModelCall.created_at).all()

    assert "narrative output" in narrative
    assert dashboard == "dashboard output"
    assert len(rows) == 3
    assert {row.trace_id for row in rows} == {"profile-shared-trace"}
    assert {row.owner_public_id for row in rows} == {"profile-owner"}
    assert {row.status for row in rows} == {"completed"}
    summaries = str([row.input_summary for row in rows])
    assert "private-student" not in summaries
    assert "private-course" not in summaries
    assert "private-concept" not in summaries
    assert "private-cause" not in summaries


def test_profile_report_single_parallel_failure_keeps_sibling_output():
    session, generator, profile = _fixture({
        "教师评估": "teacher advice",
        "叙事故事生成": "surviving narrative",
        "仪表盘诊断生成": RuntimeError("dashboard unavailable"),
    })

    narrative, dashboard = asyncio.run(generator.generate_report(
        profile, owner_public_id="profile-owner", trace_id="profile-partial-trace",
    ))
    rows = session.query(DBModelCall).order_by(DBModelCall.created_at).all()
    by_operation = {row.input_summary["operation"]: row for row in rows}

    assert "surviving narrative" in narrative
    assert "dashboard unavailable" not in dashboard
    assert by_operation["narrative"].status == "completed"
    failed = by_operation["dashboard_diagnosis"]
    assert (failed.status, failed.error_code) == (
        "failed", "profile_dashboard_diagnosis_provider_failed",
    )


def test_profile_report_cancellation_is_terminal_and_propagates():
    session, generator, _ = _fixture({"教师评估": asyncio.CancelledError()})

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(generator._generate_agent(
            system_prompt="system",
            user_prompt="private profile body",
            role="教师评估",
            operation="teacher_evaluation",
            capability="evaluate",
            owner_public_id="profile-owner",
            trace_id="profile-cancel-trace",
        ))

    row = session.query(DBModelCall).one()
    assert (row.status, row.error_code) == ("failed", "client_disconnected")
    assert "private profile body" not in str(row.input_summary)
