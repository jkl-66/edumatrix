from __future__ import annotations

from pathlib import Path
import json
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import (
    Base,
    DBAuditLog,
    DBCheckinLog,
    DBCodeExecution,
    DBKnowledgeDocument,
    DBNote,
    DBStudentProfile,
    DBUser,
    DBWebSearchHistory,
)
from app.legacy_repositories import LegacyReadRepository
from app.legacy_migration_governance import (
    ActivityExecutionSearchCanonicalReader,
    IdentityProfileHistoryCanonicalReader,
    KnowledgeSourceNoteCanonicalReader,
    compare_migration_results,
    legacy_governance_summary,
    migration_runtime_summary,
    observe_legacy_shadow_read,
    project_checkin_rows,
    project_code_rows,
    project_model_row,
    project_model_rows,
    project_model_tree,
    project_web_search_rows,
    record_migration_observation,
)


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_inventory_is_registered_and_no_deletion_is_claimed():
    summary = legacy_governance_summary(ROOT)
    assert summary["consumer_count"] == 43
    assert summary["consumer_file_count"] == 8
    assert summary["repository_method_count"] == 41
    assert summary["dormant_model_call_count"] == 5
    assert summary["unregistered_consumer_count"] == 0
    assert summary["unregistered_method_count"] == 0
    assert summary["stale_method_policy_count"] == 0
    assert summary["invalid_deletion_claim_count"] == 0
    assert summary["deletion_eligible_dormant_keys"] == []


def test_each_registered_consumer_has_a_migration_chain():
    summary = legacy_governance_summary(ROOT)
    assert set(summary["chain_counts"]) == {
        "activity-execution-search",
        "assessment-review-calibration",
        "identity-profile-history",
        "knowledge-source-note",
    }
    assert all(item["chains"] for item in summary["consumers"])


def test_shadow_comparison_is_stable_and_content_free():
    legacy = [{"id": "a", "score": 0.8}, {"id": "b", "score": 0.5}]
    canonical = [{"score": 0.5, "id": "b"}, {"score": 0.8, "id": "a"}]
    matched = compare_migration_results("activity-execution-search", legacy, canonical)
    assert matched["status"] == "matched"
    mismatched = compare_migration_results("activity-execution-search", legacy, [{"id": "secret raw text"}])
    assert mismatched["status"] == "mismatched"
    assert "secret raw text" not in json.dumps(mismatched)


def test_runtime_observation_persists_only_allowlisted_metadata():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    comparison = compare_migration_results("identity-profile-history", {"id": "u1"}, {"id": "u1"})
    row = record_migration_observation(
        session, chain_id="identity-profile-history", mode="shadow_read",
        comparison=comparison, trace_id="trace-migration-test",
    )
    session.commit()
    persisted = session.query(DBAuditLog).filter_by(id=row.id).one()
    rendered = json.dumps(persisted.metadata_json)
    assert persisted.outcome == "success"
    assert all(word not in rendered for word in ("prompt", "password", "answer", "content"))
    summary = migration_runtime_summary(session)
    assert summary["observation_count"] == 1
    assert summary["chains"]["identity-profile-history"]["matched"] == 1
    assert summary["raw_content_persisted"] is False


def test_activity_chain_shadow_reads_match_and_do_not_persist_raw_content():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(DBStudentProfile(student_id="learner"))
    session.add(DBCheckinLog(
        student_id="learner", checkin_date=datetime(2026, 8, 3, 8, 0),
        duration_minutes=15, concepts_reviewed=["matrix"],
    ))
    session.add(DBCodeExecution(
        id="code-1", student_id="learner", code="print('private')",
        output="private output", error="", execution_time_ms=2,
    ))
    session.add(DBWebSearchHistory(
        id="search-1", student_id="learner", query="private query",
        source_type="web_search", source_url="https://example.invalid/private",
        title="Private title", content_preview="private content", chunk_count=1,
    ))
    session.commit()

    repository = LegacyReadRepository(session)
    canonical = ActivityExecutionSearchCanonicalReader(session)
    assert callable(canonical.web_search_history)
    cases = [
        (repository.checkin_history("learner"), lambda: canonical.checkin_history("learner"), project_checkin_rows),
        (repository.checkin_dates("learner"), lambda: canonical.checkin_dates("learner"), lambda value: value),
        (repository.code_history("learner", limit=20), lambda: canonical.code_history("learner", limit=20), project_code_rows),
        (repository.web_search_history("learner", limit=20), lambda: canonical.web_search_history("learner", limit=20), project_web_search_rows),
    ]
    for legacy_result, loader, projector in cases:
        comparison = observe_legacy_shadow_read(
            session,
            chain_id="activity-execution-search",
            legacy_result=legacy_result,
            canonical_loader=loader,
            legacy_projector=projector,
            actor_public_id="user-learner",
        )
        assert comparison["status"] == "matched"
    session.expunge_all()
    assert cases[0][0][0].duration_minutes == 15
    assert cases[2][0][0].code == "print('private')"
    assert cases[3][0][0].query == "private query"

    rows = session.query(DBAuditLog).filter_by(action="legacy_migration_observation").all()
    assert len(rows) == 4
    rendered = json.dumps([row.metadata_json for row in rows])
    assert all(value not in rendered for value in (
        "print('private')", "private output", "private query", "private content",
    ))


def test_activity_chain_mismatch_and_target_error_use_explicit_fallback():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    mismatch = observe_legacy_shadow_read(
        session,
        chain_id="activity-execution-search",
        legacy_result=[{"id": "legacy"}],
        canonical_loader=lambda: [{"id": "canonical"}],
    )

    def fail_target():
        raise RuntimeError("raw target detail must not persist")

    target_error = observe_legacy_shadow_read(
        session,
        chain_id="activity-execution-search",
        legacy_result=[{"id": "legacy"}],
        canonical_loader=fail_target,
    )
    rows = session.query(DBAuditLog).filter_by(action="legacy_migration_observation").all()
    by_status = {row.metadata_json["status"]: row for row in rows}
    assert mismatch["status"] == "mismatched"
    assert target_error["status"] == "target_error"
    assert all(row.metadata_json["fallback_used"] for row in rows)
    assert by_status["target_error"].metadata_json["error_code"] == "canonical_target_runtimeerror"
    assert "raw target detail" not in json.dumps(by_status["target_error"].metadata_json)

    sql_error = observe_legacy_shadow_read(
        session,
        chain_id="activity-execution-search",
        legacy_result=[],
        canonical_loader=lambda: session.execute(text("SELECT * FROM missing_shadow_table")).all(),
    )
    assert sql_error["status"] == "target_error"
    assert session.query(DBAuditLog).filter_by(action="legacy_migration_observation").count() == 3


def test_activity_history_endpoints_keep_payloads_and_persist_shadow_observations(monkeypatch):
    import code_exec_api
    import quiz_api
    import web_search_api
    from app.auth import get_current_user

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        DBStudentProfile(student_id="learner"),
        DBCheckinLog(
            student_id="learner", checkin_date=datetime(2026, 8, 3, 8, 0),
            duration_minutes=15, concepts_reviewed=["matrix"],
        ),
        DBCodeExecution(
            id="code-http", student_id="learner", code="print(1)", output="1",
            error="", execution_time_ms=3,
        ),
        DBWebSearchHistory(
            id="search-http", student_id="learner", query="matrix",
            source_type="web_search", source_url="https://example.invalid/matrix",
            title="Matrix", content_preview="private source excerpt", chunk_count=2,
        ),
    ])
    session.commit()

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(quiz_api, "run_db_op", fake_run_db_op)
    monkeypatch.setattr(code_exec_api, "run_db_op", fake_run_db_op)
    monkeypatch.setattr(web_search_api, "run_db_op", fake_run_db_op)
    app = FastAPI()
    app.include_router(quiz_api.router)
    app.include_router(code_exec_api.router)
    app.include_router(web_search_api.router)
    app.dependency_overrides[get_current_user] = lambda: DBUser(
        public_id="user-learner", username="learner", role="student", is_active=True,
    )
    client = TestClient(app)
    try:
        checkins = client.get("/api/quiz/checkin/history/learner")
        streak = client.get("/api/quiz/checkin/streak/learner")
        code = client.get("/api/code/history/learner")
        searches = client.get("/api/web/history/learner")
    finally:
        app.dependency_overrides.clear()

    assert checkins.status_code == 200 and checkins.json()[0]["duration_minutes"] == 15
    assert streak.status_code == 200 and "streak" in streak.json()
    assert code.status_code == 200 and code.json()[0]["code"] == "print(1)"
    assert searches.status_code == 200 and searches.json()[0]["query"] == "matrix"
    rows = session.query(DBAuditLog).filter_by(action="legacy_migration_observation").all()
    assert len(rows) == 4
    assert all(row.metadata_json["status"] == "matched" for row in rows)
    assert "private source excerpt" not in json.dumps([row.metadata_json for row in rows])


def test_legacy_migration_governance_api_requires_operator(monkeypatch):
    from app import m5_api
    from app.auth import get_current_user

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    async def fake_run_db_op(operation, *args, **kwargs):
        return operation(session, *args, **kwargs)

    monkeypatch.setattr(m5_api, "run_db_op", fake_run_db_op)
    identity = {"user": DBUser(public_id="student", username="student", role="student", is_active=True)}
    app = FastAPI()
    app.include_router(m5_api.router)
    app.dependency_overrides[get_current_user] = lambda: identity["user"]
    client = TestClient(app)
    try:
        assert client.get("/api/v1/m5/legacy-migration-governance").status_code == 403
        identity["user"] = DBUser(public_id="teacher", username="teacher", role="teacher", is_active=True)
        response = client.get("/api/v1/m5/legacy-migration-governance")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["inventory"]["unregistered_consumer_count"] == 0
    assert payload["inventory"]["unregistered_method_count"] == 0
    assert payload["raw_content_persisted"] is False


def test_identity_profile_history_reader_matches_all_registered_read_shapes():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(DBUser(
        public_id="user-identity", username="identity", hashed_password="private-password-hash",
        role="student", display_name="Identity Learner", is_active=True,
    ))
    session.add(DBStudentProfile(student_id="identity", target_course="Machine Learning"))
    session.commit()
    repository = LegacyReadRepository(session)
    canonical = IdentityProfileHistoryCanonicalReader(session)
    cases = [
        (repository.user_by_username("identity"), lambda: canonical.user_by_username("identity"), project_model_row),
        (repository.student_profile("identity"), lambda: canonical.student_profile("identity"), project_model_row),
        (repository.student_profile_ids(), canonical.student_profile_ids, lambda value: value),
        (repository.display_name("identity"), lambda: canonical.display_name("identity"), lambda value: value),
        (repository.latest_alignment("identity"), lambda: canonical.latest_alignment("identity"), project_model_row),
        (repository.quiz_history("identity"), lambda: canonical.quiz_history("identity"), project_model_rows),
        (repository.personal_knowledge_documents("identity"), lambda: canonical.personal_knowledge_documents("identity"), project_model_rows),
        (repository.conversation_snapshot("identity", "missing"), lambda: canonical.conversation_snapshot("identity", "missing"), project_model_row),
    ]
    for legacy_result, loader, projector in cases:
        comparison = observe_legacy_shadow_read(
            session,
            chain_id="identity-profile-history",
            legacy_result=legacy_result,
            canonical_loader=loader,
            legacy_projector=projector,
            actor_public_id="user-identity",
        )
        assert comparison["status"] == "matched"
    rows = session.query(DBAuditLog).filter_by(action="legacy_migration_observation").all()
    assert len(rows) == 8
    assert "private-password-hash" not in json.dumps([row.metadata_json for row in rows])


def test_knowledge_chain_reads_and_single_write_postchecks_match_without_raw_text():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(DBStudentProfile(student_id="knowledge-owner"))
    session.add(DBKnowledgeDocument(
        id="doc-knowledge", student_id="knowledge-owner", filename="private.md",
        file_type="md", content="private course body", tags=["matrix"],
    ))
    session.commit()
    repository = LegacyReadRepository(session)
    canonical = KnowledgeSourceNoteCanonicalReader(session)

    legacy_library = repository.knowledge_library_rows("knowledge-owner")
    library = observe_legacy_shadow_read(
        session, chain_id="knowledge-source-note", legacy_result=legacy_library,
        canonical_loader=lambda: canonical.knowledge_library_rows("knowledge-owner"),
        legacy_projector=project_model_tree,
    )
    context = repository.knowledge_document_context("doc-knowledge", "knowledge-owner")
    detail = observe_legacy_shadow_read(
        session, chain_id="knowledge-source-note", legacy_result=context,
        canonical_loader=lambda: canonical.knowledge_document_context("doc-knowledge", "knowledge-owner"),
        legacy_projector=project_model_tree,
    )
    assert repository.set_document_guide(
        "doc-knowledge", "knowledge-owner", {"summary": "private guide"},
    ) is True
    document = session.query(DBKnowledgeDocument).filter_by(id="doc-knowledge").one()
    guide_postcheck = observe_legacy_shadow_read(
        session, chain_id="knowledge-source-note", legacy_result=document,
        canonical_loader=lambda: canonical.document_poststate("doc-knowledge", "knowledge-owner"),
        legacy_projector=project_model_row, mode="canonical_write_postcheck",
    )
    note_id = repository.upsert_generated_note(
        note_id="note-knowledge", student_id="knowledge-owner", content="private note body",
        tag="AI", concepts=["matrix"],
    )
    note = session.query(DBNote).filter_by(id=note_id).one()
    note_postcheck = observe_legacy_shadow_read(
        session, chain_id="knowledge-source-note", legacy_result=note,
        canonical_loader=lambda: canonical.note_poststate(note_id, "knowledge-owner"),
        legacy_projector=project_model_row, mode="canonical_write_postcheck",
    )
    assert {library["status"], detail["status"], guide_postcheck["status"], note_postcheck["status"]} == {"matched"}
    rendered = json.dumps([
        row.metadata_json for row in session.query(DBAuditLog).filter_by(
            action="legacy_migration_observation"
        ).all()
    ])
    assert all(value not in rendered for value in (
        "private course body", "private guide", "private note body",
    ))
