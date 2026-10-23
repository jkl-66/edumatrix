from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBUser
from app.m6_teacher import teacher_intervention_overview


ROOT = Path(__file__).parents[1]
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"
ROUTE_CONTRACT = ROOT / "frontend" / "src" / "router" / "routeMigrationContract.json"
APP = ROOT / "frontend" / "src" / "App.vue"
APP_SHELL = ROOT / "frontend" / "src" / "components" / "AppShell.vue"
RECOVERY_BANNER = ROOT / "frontend" / "src" / "components" / "RecoveryBanner.vue"
CONTEXT_RECOVERY = ROOT / "frontend" / "src" / "views" / "ContextRecovery.vue"
INTERVENTIONS = ROOT / "frontend" / "src" / "views" / "TeacherInterventions.vue"


def _route_contract(source_path: str) -> dict:
    records = json.loads(ROUTE_CONTRACT.read_text(encoding="utf-8"))
    return next(record for record in records if record["sourcePath"] == source_path)


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def test_legacy_loop_bookmarks_redirect_to_the_learning_workspace_with_notice():
    source = ROUTER.read_text(encoding="utf-8")
    golden = _route_contract("/golden-loop")
    competition = _route_contract("/competition-loop")

    assert (golden["destination"], golden["notice"], golden["rollbackRoute"]) == (
        "/workspace", "golden-loop", "/golden-loop",
    )
    assert (competition["destination"], competition["notice"], competition["rollbackRoute"]) == (
        "/workspace", "competition-loop", "/competition-loop",
    )
    assert "CURRENT_ROUTE_MIGRATION_CONTRACT" in source
    assert ".map(legacy)" in source
    assert "component: GoldenLoop" not in source
    assert "component: M3CompetitionLoop" not in source


def test_student_organization_marketplace_bookmark_has_role_safe_fallback():
    contract = _route_contract("/organization-marketplace")
    assert contract["disposition"] == "deferred"
    assert contract["destination"] == "/context-recovery"
    assert contract["roles"] == ["teacher", "admin"]
    assert contract["enabledByDefault"] is False
    assert contract["recoveryReason"] == "feature_deferred"
    assert contract["rollbackRoute"] == "/organization-marketplace"


def test_compatibility_results_are_explained_in_the_shell_or_recovery_surface():
    app = APP.read_text(encoding="utf-8")
    shell = APP_SHELL.read_text(encoding="utf-8")
    banner = RECOVERY_BANNER.read_text(encoding="utf-8")
    recovery = CONTEXT_RECOVERY.read_text(encoding="utf-8")

    for notice in ("golden-loop", "competition-loop", "legacy-route"):
        assert f"'{notice}':" in app
    assert ':route-notice="routeNotice"' in app
    assert "<RecoveryBanner" in shell
    assert 'v-if="routeNotice"' in shell
    assert 'role="status"' in banner
    assert "route.query.reason" in recovery
    assert "没有创建空对象，也没有修改现有学习记录" in recovery


def test_teacher_intervention_navigation_uses_current_course_and_real_permissions():
    source = INTERVENTIONS.read_text(encoding="utf-8")
    for marker in (
        "const selectedCourseId = ref('')",
        "const coursePayload = await getTeacherCourses()",
        "localStorage.getItem('edumatrix_course_id')",
        "getM6TeacherInterventions(selectedCourseId.value)",
    ):
        assert marker in source
    assert "const COURSE_ID" not in source

    engine, session = _session()
    try:
        seed_competition_demo(session)
        teacher = session.query(DBUser).filter_by(username="teacher").one()
        learner = session.query(DBUser).filter_by(username="lzz").one()

        overview = teacher_intervention_overview(
            session,
            actor=teacher,
            course_id="demo-course-rag-trust-v1",
        )
        assert overview["course_id"] == "demo-course-rag-trust-v1"
        assert len(overview["students"]) == 15

        with pytest.raises(HTTPException) as exc_info:
            teacher_intervention_overview(
                session,
                actor=learner,
                course_id="demo-course-rag-trust-v1",
            )
        assert exc_info.value.status_code == 403
    finally:
        session.close()
        engine.dispose()
