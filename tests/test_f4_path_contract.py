from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBChapter, DBCourse, DBLearningPath, DBPathNode, DBPlanDraft, DBPlanVersion
from app.m5_api import _path_payload


ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_f4_path_payload_keeps_course_identity_and_node_contract():
    engine, session = _session()
    try:
        session.add(DBCourse(
            id="f4-course",
            version="1",
            title="检索工程",
            subject="人工智能",
            visibility="public",
            manifest_version="1",
        ))
        plan = DBPlanDraft(
            id="f4-plan",
            owner_public_id="f4-student",
            course_id="f4-course",
            title="检索工程路径",
            status="confirmed",
            idempotency_key="f4-plan-key",
        )
        session.add(plan)
        session.flush()
        version = DBPlanVersion(
            id="f4-version",
            plan_draft_id=plan.id,
            version_number=1,
            content={"schema_version": "m5.plan.v1", "goal": "g", "assumptions": [], "nodes": []},
            content_hash="f" * 64,
        )
        session.add(version)
        session.flush()
        path = DBLearningPath(
            id="f4-path",
            owner_public_id="f4-student",
            course_id="f4-course",
            source_plan_version_id=version.id,
            status="active",
        )
        session.add(path)
        session.flush()
        session.add(DBPathNode(
            id="f4-node",
            learning_path_id=path.id,
            node_key="f4-node-key",
            sequence=1,
            node_type="chapter",
            target_object_id="chapter-1",
            title="混合检索",
            prerequisites=[],
            resource_status="existing",
            estimate_min_minutes=15,
            estimate_max_minutes=25,
        ))
        session.commit()

        payload = _path_payload(session, path)
        assert payload["course"] == {"id": "f4-course", "title": "检索工程", "subject": "人工智能"}
        assert payload["nodes"][0]["title"] == "混合检索"
        assert payload["nodes"][0]["estimate_minutes"] == [15, 25]
    finally:
        session.close()
        engine.dispose()


def test_f4_path_page_exposes_total_subject_today_and_advanced_contract():
    view = (ROOT / "frontend/src/views/LearningPathGraph.vue").read_text(encoding="utf-8")
    task_list = (ROOT / "frontend/src/components/PathTaskList.vue").read_text(encoding="utf-8")

    for marker in (
        'data-testid="path-total-view"',
        'data-testid="path-subject-view"',
        'data-testid="path-overview"',
        'data-testid="textbook-path-draft"',
        '今天学什么',
        '接下来',
        '本阶段',
        '科目进度',
        '调整预算与重建',
        '路径分析与历史',
        'getM5TodayWork',
        'listM5Paths',
        'getM5TextbookPathDraft',
        'isLearner.value && !isPersonalPath.value && courseId',
    ):
        assert marker in view

    for marker in (
        '知识点',
        '完成条件：',
        '分钟',
        '进入',
        '今日必做',
        'path-task--locked',
    ):
        assert marker in task_list

    assert "cannot revise plan from replan_pending" not in view
