from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBArtifact, DBClaimCheck, DBDebateRound
from app.m3_agents import (
    M3AgentRole,
    complete_m3_agent_run,
    create_m3_collaboration_task,
    start_m3_agent_run,
    start_m3_collaboration_task,
)
from app.m3_baseline import seed_m3_profile_baselines
from app.m3_debate import (
    AtomicClaimInput,
    M3DebateError,
    conduct_m3_debate,
    persist_m3_debate_report,
)
from app.m3_resources import M3PersonalizedResourceGenerator, persist_m3_resource_bundle
from tests.test_m3_resources import ProfileAwareFakeLLM


class DeterministicDebateReviewer:
    async def review_claim(self, claim, *, round_number, previous_rounds):
        source_ids = claim["proposed_source_ref_ids"]
        if claim["claim_id"] == "claim-revise" and round_number == 1:
            verdict, issues = "revise", ["missing_condition"]
        elif claim["claim_id"] == "claim-uncertain":
            verdict, issues = "uncertain", ["unsupported"]
        else:
            verdict, issues = "keep", ["none"]
        return {
            "prover": {
                "support_status": "supported" if verdict == "keep" else "partial",
                "evidence_ref_ids": source_ids,
                "applicable_conditions": ["owner/course/version filter remains enabled"],
                "rationale": "frozen source is proposed for this atomic claim",
            },
            "challenger": {
                "issue_types": issues,
                "evidence_ref_ids": source_ids,
                "rationale": "check omitted conditions and evidence scope",
            },
            "judge": {
                "verdict": verdict,
                "rationale": "structured deterministic fixture verdict",
                "evidence_ref_ids": source_ids,
                "confidence": 0.8 if verdict != "uncertain" else 0.4,
            },
        }


def _prepared_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    fixture = seed_m3_profile_baselines(session).fixtures[1]
    context = fixture.generation_context
    task, _ = create_m3_collaboration_task(session, context=context, idempotency_key="m3-debate")
    start_m3_collaboration_task(session, task_id=task.id, owner_public_id=context.owner_public_id)
    for role in (M3AgentRole.DIAGNOSIS,):
        start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=role)
        complete_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=role)
    start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.DOMAIN_GENERATION)
    bundle = asyncio.run(M3PersonalizedResourceGenerator(ProfileAwareFakeLLM()).generate(session, context=context))
    _manifest, _version, resources, _created = persist_m3_resource_bundle(session, task_id=task.id, context=context, bundle=bundle)
    start_m3_agent_run(session, task_id=task.id, owner_public_id=context.owner_public_id, role=M3AgentRole.EVIDENCE_REVIEW)
    return engine, session, context, task, resources


def test_claim_debate_persists_separate_arguments_verdicts_and_stop_reasons():
    engine, session, context, task, resources = _prepared_session()
    try:
        versions = {resource.artifact_type: resource.current_version_id for resource in resources}
        source_id = context.source_ref_ids[0]
        claims = [
            AtomicClaimInput(claim_id="claim-keep", artifact_version_id=versions["lesson"], location="lesson.sections[0]", atomic_claim="top-k changes candidate set size", proposed_source_ref_ids=(source_id,)),
            AtomicClaimInput(claim_id="claim-revise", artifact_version_id=versions["lab_guide"], location="lab.steps[0]", atomic_claim="filtering must precede ranking", proposed_source_ref_ids=(source_id,)),
            AtomicClaimInput(claim_id="claim-uncertain", artifact_version_id=versions["tiered_quiz"], location="quiz.q-x", atomic_claim="one parameter is globally optimal", proposed_source_ref_ids=(source_id,)),
        ]
        report = asyncio.run(
            conduct_m3_debate(
                session,
                task_id=task.id,
                owner_public_id=context.owner_public_id,
                claims=claims,
                reviewer=DeterministicDebateReviewer(),
                reviewer_version="deterministic-debate-fixture.v1",
                max_rounds=2,
            )
        )
        assert [result.final_verdict for result in report.results] == ["keep", "keep", "uncertain"]
        assert [len(result.rounds) for result in report.results] == [1, 2, 1]
        assert report.results[-1].stopping_reason == "evidence_insufficient"
        assert report.overall_status == "uncertain"
        assert report.semantic_quality_metric_assessed is False

        artifact, version, created = persist_m3_debate_report(
            session, owner_public_id=context.owner_public_id, report=report
        )
        assert created is True
        replay = persist_m3_debate_report(session, owner_public_id=context.owner_public_id, report=report)
        assert replay[0].id == artifact.id and replay[1].id == version.id and replay[2] is False
        session.commit()

        assert session.query(DBClaimCheck).filter_by(trace_id=task.trace_id).count() == 3
        assert session.query(DBDebateRound).filter_by(trace_id=task.trace_id).count() == 4
        assert session.query(DBArtifact).filter_by(creating_task_id=task.id).count() == 5
        for row in session.query(DBDebateRound).filter_by(trace_id=task.trace_id):
            assert row.prover_claim != row.challenger_response
            assert row.judge_decision in {"keep", "revise", "reject", "uncertain"}
        resource_versions = {resource.id: resource.current_version_id for resource in resources}
        assert {resource.id: resource.current_version_id for resource in resources} == resource_versions
    finally:
        session.close()
        engine.dispose()


def test_debate_rejects_source_outside_the_resource_scope():
    engine, session, context, task, resources = _prepared_session()
    try:
        claim = AtomicClaimInput(
            claim_id="claim-outside",
            artifact_version_id=resources[0].current_version_id,
            location="lesson.sections[0]",
            atomic_claim="out of scope claim",
            proposed_source_ref_ids=("ref-outside-context",),
        )
        with pytest.raises(M3DebateError) as raised:
            asyncio.run(
                conduct_m3_debate(
                    session,
                    task_id=task.id,
                    owner_public_id=context.owner_public_id,
                    claims=[claim],
                    reviewer=DeterministicDebateReviewer(),
                    reviewer_version="deterministic-debate-fixture.v1",
                )
            )
        assert raised.value.code == "claim_source_out_of_scope"
        assert session.query(DBClaimCheck).count() == 0
        assert session.query(DBDebateRound).count() == 0
    finally:
        session.close()
        engine.dispose()
