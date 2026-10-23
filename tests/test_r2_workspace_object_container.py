from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBArtifactVersion, DBUser
from app.m5_workspace import workspace_overview


ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_workspace_projects_four_switchable_learning_object_types():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()

        payload = workspace_overview(session, current_user=learner)
        objects = payload["learning_objects"]
        by_type = {item["object_type"]: item for item in objects}

        assert {"document", "code", "experiment", "exercise"}.issubset(by_type)
        assert by_type["document"]["source"]["id"] == "demo-src-04"
        assert by_type["document"]["render"]["excerpt"]
        assert by_type["code"]["render"]["language"] == "python"
        assert "hybrid_search" in by_type["code"]["render"]["content"]
        assert "未执行" in by_type["code"]["truth_boundary"]
        assert by_type["experiment"]["version"]["id"]
        assert by_type["exercise"]["render"]["options"] == ["是", "否"]
        assert all("version" in item and "source" in item for item in by_type.values())
    finally:
        session.close()
        engine.dispose()


def test_workspace_object_projection_contains_a_visible_error_boundary():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        version = session.get(DBArtifactVersion, "demo-artifact-version-lzz-lab-01")
        version.content = "not-json"
        session.flush()

        payload = workspace_overview(session, current_user=learner)
        experiment = next(item for item in payload["learning_objects"] if item["object_type"] == "experiment")

        assert experiment["render"]["kind"] == "experiment"
        assert "错误边界" in experiment["error_boundary"]
    finally:
        session.close()
        engine.dispose()


def test_learning_workspace_uses_one_stable_inline_object_container():
    source = (ROOT / "frontend" / "src" / "views" / "LearningWorkspace.vue").read_text(encoding="utf-8")

    for kind in ("document", "code", "experiment", "exercise"):
        assert f'learning-object-tab-${{type.key}}' in source
        assert f'learning-object-{kind}' in source
    assert 'data-testid="learning-object-container"' in source
    assert ".object-stage { display: flex; height: 430px; min-height: 430px" in source
    assert "<iframe" not in source
