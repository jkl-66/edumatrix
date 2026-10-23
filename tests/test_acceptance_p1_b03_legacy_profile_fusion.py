from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBProfileSnapshot, DBStudentProfile, DBUser
from app.legacy_adapter import LegacyDataAdapter, LegacyProfileMigrationError
from app.profile_summary import build_personal_activity


def _db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _legacy_profile(user: DBUser) -> DBStudentProfile:
    return DBStudentProfile(
        student_id=user.username,
        target_course="机器学习导论",
        cognitive_style="图示+代码",
        motivation_type="岗位转型",
        cognitive_load=0.78,
        weak_points=["正则化"],
        learning_goals=["能够完成模型评估"],
        interaction_preferences=["先看例子"],
        concept_mastery={"正则化": 0.38},
        misconception_patterns={"正则化": {"cause": "概念边界"}},
        dimension_states={"knowledge_mastery": {"score": 0.42, "status": "部分掌握"}},
        learning_state_causes={"cognitive_load": {"percentage": 64}},
        knowledge_traces={"正则化": {"mastery": 0.38, "attempts": 3}},
        bkt_states={"正则化": {"p_mastery": 0.41, "attempts": 4}},
        dkt_bias=[0.12, -0.04],
        mental_state_history=[{"cognitive_load": 0.7}],
        concept_layers={"正则化": {"layer": "应用"}},
        cognitive_map={"正则化": ["线性回归"]},
        fsm_mode="support",
        fsm_accuracy_history={"正则化": [0.4, 0.5]},
        rl_q_table={"review": {"正则化": 0.8}},
        history_logs="旧系统分析：正则化需要更多辨析",
        profile_evidence=[
            {
                "source": "student_message",
                "text": "我总是分不清正则化的边界",
                "features": ["weak_point"],
                "weight": 0.8,
                "confidence": 0.8,
                "timestamp": "2026-08-20T09:00:00Z",
            }
        ],
    )


def test_legacy_profile_projection_maps_ml_fields_and_exposes_influence():
    engine, db = _db()
    try:
        user = DBUser(
            public_id="usr-p1-b03-map",
            username="p1-b03-map",
            hashed_password="not-used",
            role="student",
        )
        profile = _legacy_profile(user)
        db.add_all([user, profile])
        db.commit()

        report = LegacyDataAdapter(db).profile_migration_report(user.public_id, course_id="course-a")
        assert report["status"] == "mapped"
        assert report["mapping_version"] == "legacy-profile-map.v1"
        assert report["effective_projection"]["bkt_states"]["正则化"]["p_mastery"] == 0.41
        fields = {item["legacy_field"]: item for item in report["diff"]}
        assert fields["dimension_states"]["algorithm_version"] == "legacy-ten-dimension.v1"
        assert fields["dimension_states"]["status"] == "imported"
        used_by = {target for item in report["influence"] for target in item["usedBy"]}
        assert {"学习路径", "今日任务", "智能组卷", "讲义", "测验题"}.issubset(used_by)
        assert report["read_only"] is True
        assert db.query(DBProfileSnapshot).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_replay_preserves_confirmed_value_and_is_idempotent():
    engine, db = _db()
    try:
        user = DBUser(
            public_id="usr-p1-b03-replay",
            username="p1-b03-replay",
            hashed_password="not-used",
            role="student",
        )
        profile = _legacy_profile(user)
        profile.customized_fields = ["cognitive_load"]
        db.add_all([user, profile])
        db.flush()
        db.add(DBProfileSnapshot(
            id="ps-confirmed-profile",
            owner_public_id=user.public_id,
            legacy_student_id=user.username,
            profile_version="profile.continuous.v4",
            snapshot={
                "kind": "continuous_profile_update",
                "course_id": "course-a",
                "source_turn_id": "turn-confirmed",
                "profile_projection": {"cognitive_load": 0.22, "weak_points": ["正则化"]},
            },
            content_hash="confirmed-content",
            trace_id="turn-confirmed",
        ))
        db.commit()
        before = deepcopy(db.get(DBStudentProfile, user.username).bkt_states)

        adapter = LegacyDataAdapter(db)
        report = adapter.profile_migration_report(user.public_id, course_id="course-a")
        conflict = next(item for item in report["diff"] if item["legacy_field"] == "cognitive_load")
        assert conflict["status"] == "preserved_confirmed"
        assert report["effective_projection"]["cognitive_load"] == 0.22

        first = adapter.project_profile_snapshot(user.public_id, course_id="course-a")
        db.commit()
        second = adapter.project_profile_snapshot(user.public_id, course_id="course-a")
        db.commit()
        assert first.id == second.id
        assert first.profile_version == "profile.legacy-migration.v1"
        assert db.query(DBProfileSnapshot).count() == 2
        visible = adapter.profile_migration_report(user.public_id, course_id="course-a")
        assert visible["canonical_snapshot"]["version"] == "profile.legacy-migration.v1"
        assert visible["canonical_snapshot"]["kind"] == "legacy_profile_migration"
        assert db.get(DBStudentProfile, user.username).bkt_states == before
        assert first.snapshot["profile_projection"]["cognitive_load"] == 0.22
        assert first.snapshot["legacy_migration"]["mapping_version"] == "legacy-profile-map.v1"
    finally:
        db.close()
        engine.dispose()


def test_missing_legacy_profile_is_explicit_and_does_not_create_snapshot():
    engine, db = _db()
    try:
        user = DBUser(
            public_id="usr-p1-b03-missing",
            username="p1-b03-missing",
            hashed_password="not-used",
            role="student",
        )
        db.add(user)
        db.commit()
        try:
            LegacyDataAdapter(db).project_profile_snapshot(user.public_id)
        except LegacyProfileMigrationError as exc:
            assert exc.code == "legacy_profile_not_found"
        else:
            raise AssertionError("missing legacy profile should not be projected")
        assert db.query(DBProfileSnapshot).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_profile_surfaces_keep_migration_data_private_from_learning_ui():
    root = Path(__file__).resolve().parents[1]
    summary = (root / "frontend/src/components/ProfileSummaryPanel.vue").read_text(encoding="utf-8")
    dashboard = (root / "frontend/src/views/ProfileDashboard.vue").read_text(encoding="utf-8")
    backend = (root / "app/profile_summary.py").read_text(encoding="utf-8")
    for surface in (summary, dashboard):
        assert "legacy-profile-migration" not in surface
        assert "dashboard-legacy-migration" not in surface
        assert "legacy-profile-map.v1" not in surface
        assert "f8.learning-feedback.v2" not in surface
        assert "legacy-migration" not in surface
    assert '"legacy_migration": legacy_migration' in backend
    assert '"legacyMigration": legacy_migration' in backend


def test_personal_activity_carries_the_same_read_only_migration_evidence():
    engine, db = _db()
    try:
        user = DBUser(
            public_id="usr-p1-b03-activity",
            username="p1-b03-activity",
            hashed_password="not-used",
            role="student",
        )
        db.add_all([user, _legacy_profile(user)])
        db.commit()
        activity = build_personal_activity(db, current_user=user, days=7)
        migration = activity["profile"]["legacyMigration"]
        assert migration["mapping_version"] == "legacy-profile-map.v1"
        assert migration["read_only"] is True
        assert migration["influence"]
    finally:
        db.close()
        engine.dispose()


def test_existing_downstream_surfaces_keep_one_snapshot_version_contract():
    root = Path(__file__).resolve().parents[1]
    downstream_markers = {
        root / "app/m5_learning.py": ("profile_snapshot_id", "profile_version", "profile_influence"),
        root / "app/m5_workspace.py": ("snapshot_id", "profile_version", "profile_influence"),
        root / "app/m5_exam_core.py": ("profile_snapshot_id", "profile_version", "profile_influence"),
        root / "app/resource_bundles.py": ("profile_snapshot_id", "profile_version", "profile_influence"),
    }
    for path, markers in downstream_markers.items():
        text = path.read_text(encoding="utf-8")
        assert all(marker in text for marker in markers), path
