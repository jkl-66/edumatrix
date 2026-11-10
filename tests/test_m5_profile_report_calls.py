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
        self.prompts = {}

    async def generate(self, system_prompt, user_prompt, *, role):
        self.prompts[role] = user_prompt
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
    assert "暂时没有生成" in dashboard
    assert "90%" not in dashboard
    assert "过载" not in dashboard
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


def test_dimension_defaults_do_not_become_confident_learner_diagnoses():
    from models import DimensionState
    from profile_api import _build_dimension_analysis
    state = DimensionState(key="learning_strategy", label="学习方法", score=.53, confidence=.5,
                           status="策略证据仍需丰富")
    assert _build_dimension_analysis(state.key, state)["score"] is None
    state.evidence_count = 1
    state.evidence_fragments = ["完成了两种实践任务"]
    result = _build_dimension_analysis(state.key, state)
    assert result["score"] == .53
    assert result["diagnosis"] == "策略证据仍需丰富"
    assert "依赖看答案" not in result["diagnosis"]


def test_reports_use_confirmed_state_and_equipment_without_superseded_inferred_causes():
    from models import DimensionState
    session, generator, profile = _fixture({
        "教师评估": "尝试两张照片比较", "叙事故事生成": "学习建议", "仪表盘诊断生成": "学习回顾",
    })
    profile.frustration_index = .72
    profile.dimension_states = {
        "affect_resilience": DimensionState(key="affect_resilience", label="感受", score=.28, confidence=.9,
            status="当前自述", qualitative=True,
            self_report="我并不紧张，愿意自己试", confirmed_state_scores={"frustration_index": None}),
        "learning_context": {"confirmed_fields": {
            "available_tools": "安卓手机，无专业模式，无电脑", "study_schedule": "晚上20分钟",
        }},
    }
    profile.learning_state_causes["affective_barrier"] = CauseBreakdown(
        key="affective_barrier", label="旧焦虑推测", percentage=72, confidence=.5, evidence_count=1,
    )
    asyncio.run(generator.generate_report(profile, owner_public_id="profile-owner"))
    for prompt in generator.llm.prompts.values():
        assert "我并不紧张，愿意自己试" in prompt
        assert "安卓手机，无专业模式，无电脑" in prompt
        assert "晚上20分钟" in prompt
        assert "旧焦虑推测" not in prompt
    session.close()
