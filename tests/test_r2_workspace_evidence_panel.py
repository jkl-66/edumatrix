from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBArtifact,
    DBArtifactVersion,
    DBCourse,
    DBQualityCheck,
    DBSourceRef,
    DBUser,
)
from app.m5_workspace import _attach_workspace_evidence, workspace_overview


ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    seed_competition_demo(session)
    session.commit()
    return engine, session


def _overview(session):
    learner = session.query(DBUser).filter_by(username="lzz").one()
    return workspace_overview(session, current_user=learner)


def test_workspace_evidence_panel_projects_canonical_location_license_and_boundaries():
    engine, session = _session()
    try:
        document = next(item for item in _overview(session)["learning_objects"] if item["object_type"] == "document")
        panel = document["evidence_panel"]

        assert panel["schema_version"] == "r2.workspace-evidence-panel.v1"
        assert panel["ready"] is True
        assert panel["sources"][0]["source_ref_id"].startswith("demo-ref-")
        assert panel["sources"][0]["document_title"]
        assert panel["sources"][0]["location"]
        assert panel["sources"][0]["license"] != "未记录许可信息"
        assert {item["category"] for item in panel["checks"]} == {"structure", "source", "topic", "runnable"}
        assert next(item for item in panel["checks"] if item["category"] == "topic")["status"] == "not_recorded"
        assert "canonical" in panel["truth_boundary"]
    finally:
        session.close()
        engine.dispose()


def test_workspace_evidence_panel_fails_closed_for_missing_and_mismatched_source_refs():
    engine, session = _session()
    try:
        payload = _overview(session)
        document = next(item for item in payload["learning_objects"] if item["object_type"] == "document")
        foreign_ref = session.query(DBSourceRef).filter(
            DBSourceRef.chapter_id != document["context"]["chapter_id"],
        ).first()
        projected = dict(document)
        projected["context"] = {**document["context"], "source_ref_ids": [foreign_ref.id]}
        course = session.get(DBCourse, "demo-course-rag-trust-v1")
        _attach_workspace_evidence(session, course=course, item=projected)
        panel = projected["evidence_panel"]
        assert panel["ready"] is False
        assert panel["sources"] == []
        assert panel["invalid_reference_count"] == 1
        assert "source_reference_invalid" in panel["blockers"]

        projected["context"]["source_ref_ids"] = []
        _attach_workspace_evidence(session, course=course, item=projected)
        assert projected["evidence_panel"]["ready"] is False
        assert projected["evidence_panel"]["source_summary"] == "当前对象未记录可核查来源"
    finally:
        session.close()
        engine.dispose()


def test_failed_quality_check_blocks_ready_and_filters_internal_details():
    engine, session = _session()
    try:
        artifact = session.query(DBArtifact).filter_by(artifact_type="interactive_lab").first()
        version = session.get(DBArtifactVersion, artifact.current_version_id)
        session.add(DBQualityCheck(
            artifact_version_id=version.id,
            trace_id="r2-09-quality-failure",
            check_type="runnability",
            checker_version="runner-v1",
            status="failed",
            score=0.2,
            details={"secret_prompt": "must-not-leak", "api_key": "must-not-leak"},
            source_ref_ids=list((version.metadata_json or {}).get("source_ref_ids") or []),
        ))
        session.commit()

        experiment = next(item for item in _overview(session)["learning_objects"] if item["id"] == artifact.id)
        panel = experiment["evidence_panel"]
        runnable = next(item for item in panel["checks"] if item["category"] == "runnable")
        assert panel["ready"] is False
        assert runnable["status"] == "failed"
        assert "runnable_check_failed" in panel["blockers"]
        assert "must-not-leak" not in str(panel)
        assert "secret_prompt" not in str(panel)
    finally:
        session.close()
        engine.dispose()


def test_learning_workspace_renders_collapsible_source_and_quality_panel():
    source = (ROOT / "frontend" / "src" / "views" / "LearningWorkspace.vue").read_text(encoding="utf-8")

    assert 'data-testid="workspace-evidence-panel"' in source
    assert "activeObject.evidence_panel.sources" in source
    assert "activeObject.evidence_panel.checks" in source
    assert "真实性边界" in source
    assert "质量检查未记录" in source
