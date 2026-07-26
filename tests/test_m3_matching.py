from __future__ import annotations

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBLearningEvent, DBPlanDraft, DBPlanVersion
from app.m3_agents import (
    M3AgentRole,
    complete_m3_agent_run,
    create_m3_collaboration_task,
    start_m3_agent_run,
    start_m3_collaboration_task,
)
from app.m3_baseline import seed_m3_profile_baselines
from app.m3_debate import AtomicClaimInput, conduct_m3_debate, persist_m3_debate_report
from app.m3_matching import build_m3_matching_report, persist_m3_matching_report
from app.m3_resources import M3PersonalizedResourceGenerator, persist_m3_resource_bundle
from tests.test_m3_debate import DeterministicDebateReviewer
from tests.test_m3_resources import ProfileAwareFakeLLM


def _prepare(session, fixture):
    context = fixture.generation_context
    task, _ = create_m3_collaboration_task(
        session,
        context=context,
        idempotency_key=f"m3-matching-{fixture.gold_profile.archetype}",
    )
    start_m3_collaboration_task(session, task_id=task.id, owner_public_id=context.owner_public_id)
    start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DIAGNOSIS)
    complete_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DIAGNOSIS)
    start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DOMAIN_GENERATION)
    bundle = asyncio.run(M3PersonalizedResourceGenerator(ProfileAwareFakeLLM()).generate(session, context=context))
    _manifest, _version, resources, _created = persist_m3_resource_bundle(session, task_id=task.id, context=context, bundle=bundle)
    start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.EVIDENCE_REVIEW)
    lesson = next(resource for resource in resources if resource.artifact_type == "lesson")
    report = asyncio.run(
        conduct_m3_debate(
            session,
            task_id=task.id,
            owner_public_id=context.owner_public_id,
            claims=[AtomicClaimInput(
                claim_id=f"claim-{fixture.gold_profile.archetype}",
                artifact_version_id=lesson.current_version_id,
                location="lesson.sections[0]",
                atomic_claim="top-k changes the candidate set",
                proposed_source_ref_ids=(context.source_ref_ids[0],),
            )],
            reviewer=DeterministicDebateReviewer(),
            reviewer_version="deterministic-debate-fixture.v1",
        )
    )
    persist_m3_debate_report(session, owner_public_id=context.owner_public_id, report=report)
    start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DECISION_ORCHESTRATION)
    return task


def test_three_matching_reports_use_intervals_formal_paths_and_no_fake_performance():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        fixtures = seed_m3_profile_baselines(session).fixtures
        reports = []
        for fixture in fixtures:
            task = _prepare(session, fixture)
            report = build_m3_matching_report(
                session,
                task_id=task.id,
                owner_public_id=fixture.generation_context.owner_public_id,
            )
            artifact, version, created = persist_m3_matching_report(session, report=report)
            assert created is True
            replay = persist_m3_matching_report(session, report=report)
            assert replay[0].id == artifact.id and replay[1].id == version.id and replay[2] is False
            reports.append(report)
        session.commit()

        assert [report.recommended_interval.ability_midpoint for report in reports] == sorted(
            report.recommended_interval.ability_midpoint for report in reports
        )
        assert len({report.plan_version_id for report in reports}) == 3
        assert session.query(DBPlanDraft).count() == 3
        assert session.query(DBPlanVersion).count() == 3
        for report in reports:
            assert report.plan_execution_authorized is False
            assert report.performance.status == "no_valid_events"
            assert report.performance.points == ()
            assert len(report.resource_matches) == 3
            assert all(match.status in {"adapted", "acceptable_challenge"} for match in report.resource_matches)
            assert all(gap.state != "confirmed_weak" for gap in report.knowledge_gaps)
    finally:
        session.close()
        engine.dispose()


def test_new_observation_appends_report_version_without_claiming_mastery():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        fixture = seed_m3_profile_baselines(session).fixtures[0]
        task = _prepare(session, fixture)
        first = build_m3_matching_report(session, task_id=task.id, owner_public_id=task.owner_public_id)
        artifact, first_version, _ = persist_m3_matching_report(session, report=first)
        session.add(
            DBLearningEvent(
                owner_public_id=task.owner_public_id,
                course_id=task.course_id,
                event_type="m3.interactive.observation",
                trace_id=task.trace_id,
                object_type="interactive_artifact",
                object_id="artifact-session-fixture",
                payload={"completed": True, "mastery_update": "none"},
            )
        )
        session.flush()
        second = build_m3_matching_report(session, task_id=task.id, owner_public_id=task.owner_public_id)
        same_artifact, second_version, created = persist_m3_matching_report(session, report=second)

        assert same_artifact.id == artifact.id
        assert created is True
        assert second_version.id != first_version.id
        assert second.performance.status == "observed_not_mastery"
        assert len(second.performance.learning_event_ids) == 1
        assert "不据此宣称长期掌握" in second.performance.explanation
    finally:
        session.close()
        engine.dispose()
