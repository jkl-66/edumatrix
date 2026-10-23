from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBPathNode, DBUser
from app.m5_workspace import workspace_overview


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "frontend" / "src" / "views" / "LearningWorkspace.vue"


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_workspace_chapters_include_canonical_source_markers():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()

        payload = workspace_overview(session, current_user=learner)

        assert len(payload["chapters"]) == 12
        assert all(item["source"] for item in payload["chapters"])
        assert all(item["source"]["title"] for item in payload["chapters"])
        assert all(item["source"]["file_format"] for item in payload["chapters"])
        assert all(item["source"]["processing_status"] == "ready" for item in payload["chapters"])
        assert payload["today_tasks"][0]["continue_route"].endswith(
            payload["today_tasks"][0]["node_id"],
        )
    finally:
        session.close()
        engine.dispose()


def test_completed_task_leaves_today_queue_but_remains_in_path_history():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        first = session.query(DBPathNode).filter_by(id="demo-task-lzz-read-01").one()
        first.status = "completed"
        session.commit()

        payload = workspace_overview(session, current_user=learner)

        assert first.id not in {item["node_id"] for item in payload["today_tasks"]}
        history = {item["id"]: item for item in payload["current_path"]["nodes"]}
        assert history[first.id]["status"] == "completed"
        assert payload["today_tasks"][0]["node_id"] == "demo-task-lzz-lab-01"
    finally:
        session.close()
        engine.dispose()


def test_workspace_course_rail_exposes_chapters_sources_status_and_continue_action():
    source = WORKSPACE.read_text(encoding="utf-8")

    for marker in (
        'aria-label="课程章节树"',
        "课程教材",
        "预计 ",
        "继续任务：",
        "下一任务",
        "已完成",
        "completedTasks",
        "continueTask",
        "chapterSourceLabel",
        "selectMobilePanel",
    ):
        assert marker in source
