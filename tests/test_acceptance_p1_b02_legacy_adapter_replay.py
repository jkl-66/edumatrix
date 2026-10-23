from __future__ import annotations

from copy import deepcopy

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.crud import load_student_profile
from app.database import (
    Base,
    DBCourse,
    DBCourseMembership,
    DBConversationHistory,
    DBProfileEvidence,
    DBProfileSnapshot,
    DBStudentProfile,
    DBUser,
)
from app.legacy_adapter import LegacyDataAdapter
from app.m1_profile_evidence import profile_evidence_compat_view, sync_legacy_profile_evidence
from app.profile_onboarding import confirm_continuous_turn, record_continuous_turn, start_continuous_update


def _candidate() -> dict:
    return {
        "mode": "continuous_profile_update",
        "summary": "正则化仍然需要继续练习。",
        "understanding": "你能完成基础推导，但正则化容易混淆。",
        "fields": {"weak_points": ["正则化"]},
        "dimensions": [
            {
                "key": "knowledge_mastery",
                "label": "知识基础与掌握度",
                "value": "基础推导较稳，正则化仍需辨析",
                "status": "部分掌握",
                "evidence": "最近正则化还是容易错。",
                "confidence": 0.9,
            }
        ],
        "weakPointAttribution": [
            {
                "weakPoint": "正则化",
                "reason": "概念边界混淆",
                "evidence": "最近正则化还是容易错。",
                "confidence": 0.9,
            }
        ],
        "uncertainties": [],
        "originalAnswer": "最近正则化还是容易错。",
    }


def test_old_ml_bkt_and_history_adapters_replay_into_one_canonical_snapshot():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        user = DBUser(
            public_id="usr-p1-b02-legacy-replay",
            username="p1-b02-legacy-replay",
            hashed_password="not-used",
            role="student",
        )
        course = DBCourse(
            id="course-p1-b02-legacy-replay",
            version="1",
            title="机器学习导论",
            status="published",
            manifest_version="1",
        )
        profile = DBStudentProfile(
            student_id=user.username,
            target_course=course.title,
            bkt_states={
                "正则化": {
                    "p_mastery": 0.41,
                    "attempts": 4,
                    "history": [0, 1, 0],
                }
            },
            knowledge_traces={
                "正则化": {
                    "concept": "正则化",
                    "mastery": 0.38,
                    "attempts": 3,
                    "correct_attempts": 1,
                    "last_updated": "2026-08-20T09:00:00",
                }
            },
            history_logs="legacy-analysis-2026-08",
            mental_state_history=[
                {"timestamp": "2026-08-01", "cognitive_load": 0.7}
            ],
            profile_evidence=[
                {
                    "source": "student_message",
                    "text": "旧系统记录：正则化容易混淆",
                    "features": ["weak_point"],
                    "weight": 0.8,
                    "confidence": 0.8,
                    "timestamp": "2026-08-20T09:00:00Z",
                }
            ],
        )
        membership = DBCourseMembership(
            course_id=course.id,
            user_public_id=user.public_id,
            role="student",
            status="active",
        )
        history = DBConversationHistory(
            student_id=user.username,
            query="旧系统如何记录正则化学习？",
            response_summary="旧历史回答",
            target="正则化",
            profile_snapshot={"profile_version": "legacy-v0"},
        )
        db.add_all([user, course, profile, membership, history])
        db.commit()

        legacy_before = {
            "bkt_states": deepcopy(profile.bkt_states),
            "knowledge_traces": deepcopy(profile.knowledge_traces),
            "history_logs": profile.history_logs,
            "mental_state_history": deepcopy(profile.mental_state_history),
            "profile_evidence": deepcopy(profile.profile_evidence),
        }

        # Replay the actual old read paths before opening the new update flow.
        loaded = load_student_profile(db, user.username)
        assert loaded.bkt_states == legacy_before["bkt_states"]
        assert loaded.knowledge_traces["正则化"].attempts == 3
        assert loaded.history == ["legacy-analysis-2026-08"]
        assert loaded.mental_state_history == legacy_before["mental_state_history"]

        conversations = LegacyDataAdapter(db).conversations(user.username)
        assert conversations[0]["query"] == "旧系统如何记录正则化学习？"
        assert conversations[0]["profile_snapshot"]["profile_version"] == "legacy-v0"

        projected_evidence = sync_legacy_profile_evidence(db, profile)
        db.commit()
        assert len(projected_evidence) == 1
        assert profile_evidence_compat_view(db, user.username)[0]["text"] == "旧系统记录：正则化容易混淆"

        # Continue through the same confirmation-only path used by the product.
        start_continuous_update(db, user, course_id=course.id)
        record_continuous_turn(
            db,
            user,
            turn_id="legacy-adapter-replay-turn",
            user_answer="最近正则化还是容易错。",
            course_id=course.id,
            extractor=lambda *_args: _candidate(),
        )
        confirm_continuous_turn(
            db,
            user,
            turn_id="legacy-adapter-replay-turn",
            fields={"weak_points": ["正则化"]},
            dimensions=_candidate()["dimensions"],
            attributions=_candidate()["weakPointAttribution"],
        )

        snapshot = db.query(DBProfileSnapshot).one()
        projection = snapshot.snapshot["profile_projection"]
        assert projection["bkt_states"] == legacy_before["bkt_states"]
        assert projection["knowledge_traces"] == legacy_before["knowledge_traces"]
        assert projection["history_logs"] == legacy_before["history_logs"]
        assert projection["mental_state_history"] == legacy_before["mental_state_history"]
        assert snapshot.snapshot["weak_points"] == ["正则化"]

        # The old source remains readable and unchanged; the canonical profile/snapshot
        # is the only profile write path created by this replay.
        db.expire_all()
        current = db.get(DBStudentProfile, user.username)
        assert current.bkt_states == legacy_before["bkt_states"]
        assert current.knowledge_traces == legacy_before["knowledge_traces"]
        assert current.history_logs == legacy_before["history_logs"]
        assert current.mental_state_history == legacy_before["mental_state_history"]
        assert current.profile_evidence[:1] == legacy_before["profile_evidence"]
        assert db.query(DBStudentProfile).count() == 1
        assert db.query(DBProfileSnapshot).count() == 1
        assert db.query(DBProfileEvidence).filter_by(legacy_student_id=user.username).count() == 1
    finally:
        db.close()
        engine.dispose()
