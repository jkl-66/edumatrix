from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from app.database import Base, DBDomainPack, DBDomainVersion, DBEvaluationCase, DBEvaluationResult
from app.m4_evaluation import M4EvaluationError, load_frozen_benchmark
from app.m4_runs import (
    BlindCaseOutput,
    blind_cases_for_run,
    record_blind_result,
    seal_blind_run,
    start_evaluation_run,
    sync_frozen_cases,
)


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    pack = DBDomainPack(id="dp-m4", domain_key="domain-rag", title="RAG", status="active")
    version = DBDomainVersion(
        id="dv-m4",
        domain_pack_id=pack.id,
        version="0.1",
        content_hash="0" * 64,
    )
    session.add_all((pack, version))
    session.commit()
    return session, version


def test_m4_blind_run_is_persistent_idempotent_and_not_prematurely_passed():
    session, version = _session()
    benchmark = load_frozen_benchmark()
    sync_frozen_cases(session, benchmark=benchmark, domain_version_id=version.id)

    run = start_evaluation_run(
        session,
        benchmark=benchmark,
        trace_id="trace-m4-run-001",
        code_version="dirty-test-tree",
        model_version="deterministic-test-double",
    )
    replay = start_evaluation_run(
        session,
        benchmark=benchmark,
        trace_id="trace-m4-run-001",
        code_version="dirty-test-tree",
        model_version="deterministic-test-double",
    )
    blind = blind_cases_for_run(session, run)

    assert replay.id == run.id
    assert len(blind) == 60
    assert all("gold" not in item and "failure_branch" not in item for item in blind)
    result = record_blind_result(
        session,
        run=run,
        output=BlindCaseOutput(case_id=blind[0]["case_id"], status="completed", response_text="raw output"),
    )
    replayed_result = record_blind_result(
        session,
        run=run,
        output=BlindCaseOutput(case_id=blind[0]["case_id"], status="completed", response_text="raw output"),
    )
    assert result.id == replayed_result.id
    assert result.passed is False
    assert session.query(DBEvaluationCase).count() == 60
    assert session.query(DBEvaluationResult).count() == 1
    with pytest.raises(M4EvaluationError, match="1/60"):
        seal_blind_run(session, run)


def test_m4_result_replay_rejects_changed_output():
    session, version = _session()
    benchmark = load_frozen_benchmark()
    sync_frozen_cases(session, benchmark=benchmark, domain_version_id=version.id)
    run = start_evaluation_run(
        session,
        benchmark=benchmark,
        trace_id="trace-m4-run-002",
        code_version="dirty-test-tree",
        model_version="deterministic-test-double",
    )
    output = BlindCaseOutput(case_id="M0-K01", status="completed", response_text="first")
    record_blind_result(session, run=run, output=output)
    with pytest.raises(M4EvaluationError, match="different immutable output"):
        record_blind_result(
            session,
            run=run,
            output=BlindCaseOutput(case_id="M0-K01", status="completed", response_text="changed"),
        )
