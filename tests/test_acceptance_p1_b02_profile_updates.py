from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.m5_legacy_calls as legacy_calls
import app.profile_onboarding as onboarding
import llm_client

from app.database import (
    Base,
    DBCourse,
    DBCourseDocument,
    DBCourseMembership,
    DBOnboardingSession,
    DBOnboardingTurn,
    DBProfileSnapshot,
    DBStudentProfile,
    DBUser,
)
from app.profile_onboarding import (
    confirm_continuous_turn,
    continuous_update_reminder,
    dismiss_continuous_update_reminder,
    get_or_create_session,
    record_continuous_turn,
    start_continuous_update,
)


def _database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _publish_material(db, course):
    content = f"# {course.title}\n训练集用于拟合参数，验证集用于选择模型，测试集用于评估泛化表现。"
    db.add(DBCourseDocument(
        id=f"doc-{course.id}", course_id=course.id, chapter_order=1,
        filename="course-notes.md", title=f"{course.title}课程讲义",
        content=content, chunk_count=1, status="published",
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    ))
    db.flush()


def _learner(db, suffix: str = "main"):
    user = DBUser(
        public_id=f"usr-p1-b02-{suffix}",
        username=f"p1-b02-{suffix}",
        hashed_password="not-used",
        role="student",
        display_name="持续画像测试学生",
    )
    course = DBCourse(
        id=f"course-p1-b02-{suffix}",
        version="1",
        title="机器学习导论",
        status="published",
        manifest_version="1",
    )
    db.add_all([user, course])
    db.flush()
    _publish_material(db, course)
    db.add(DBCourseMembership(
        course_id=course.id,
        user_public_id=user.public_id,
        role="student",
        status="active",
    ))
    db.add(DBStudentProfile(student_id=user.username, target_course=course.title))
    db.commit()
    return user, course


def _candidate(answer="最近我能独立推导线性回归，但一遇到正则化就容易混淆"):
    return {
        "mode": "continuous_profile_update",
        "summary": "你现在能独立处理基础推导，但正则化概念容易混淆。",
        "understanding": "你现在能独立处理基础推导，但正则化概念容易混淆。",
        "fields": {"weak_points": ["正则化"]},
        "dimensions": [{
            "key": "knowledge_mastery",
            "label": "知识基础与掌握度",
            "value": "基础推导较稳，正则化仍需辨析",
            "status": "部分掌握",
            "score": 0.62,
            "evidence": "我能独立推导线性回归，但一遇到正则化就容易混淆",
            "confidence": 0.9,
        }],
        "weakPointAttribution": [{
            "weakPoint": "正则化",
            "reason": "相近概念还没有形成清晰区分",
            "evidence": "一遇到正则化就容易混淆",
            "confidence": 0.86,
        }],
        "uncertainties": [],
        "source": "test-model",
        "originalAnswer": answer,
    }


def test_continuous_model_extractor_requires_deepseek_max_without_fallback(monkeypatch):
    calls = {}

    class FakeLLM:
        model = "deepseek-v4-flash"

    def fake_build_async_llm(**kwargs):
        calls.update(kwargs)
        return FakeLLM()

    async def fake_audited(_llm, *, response_validator, **_kwargs):
        raw = json.dumps({
            "understanding": "最近容易混淆正则化。",
            "fields": [],
            "dimensions": [],
            "weak_point_attribution": [],
            "uncertainties": ["还需要补充最近的练习表现"],
        }, ensure_ascii=False)
        response_validator(raw)
        return raw

    monkeypatch.setattr(llm_client, "build_async_llm", fake_build_async_llm)
    monkeypatch.setattr(legacy_calls, "audited_legacy_text_call", fake_audited)
    result = onboarding.llm_extract_continuous_candidates(
        "我最近总把正则化和交叉验证混淆。",
        owner_public_id="usr-p1-b02-model",
        profile=None,
        course_context={"courseId": "course-p1-b02-model", "title": "机器学习导论"},
    )
    assert result["source"] == "deepseek-v4-flash"
    assert result["modelMeta"]["reasoningEffort"] == "max"
    assert calls == {
        "provider": "openai",
        "model": "deepseek-v4-flash",
        "thinking_mode": "max",
        "reasoning_effort": "max",
        "allow_fallback": False,
    }


def test_demo_continuous_reply_is_specific_and_does_not_nest_echoes():
    result = onboarding._demo_continuous_candidates(
        "我想把项目真正上线，通勤时间比较碎，遇到长公式会有点紧张。",
        "最近的学习经历",
        1,
    )
    reply = result["assistantReply"]
    assert "你刚才讲的是：你刚才讲的是" not in reply
    assert "。。" not in reply
    assert "项目真正上线" in reply
    statuses = [item["status"] for item in result["dimensions"]]
    assert len(statuses) == len(set(statuses)), "不同画像方面不应退化成同一句状态"
    assert any(item["key"] == "learning_context" for item in result["fields"])


def test_continue_conversation_keeps_session_open_after_confirmed_round():
    engine, db = _database()
    try:
        user, course = _learner(db, "continue")
        start_continuous_update(db, user, course_id=course.id)
        record_continuous_turn(
            db,
            user,
            turn_id="continuous-continue",
            user_answer="我喜欢先看一个例子，再自己动手试一遍。",
            course_id=course.id,
            extractor=lambda text, *_: _candidate(text),
        )
        continued = confirm_continuous_turn(
            db,
            user,
            turn_id="continuous-continue",
            fields={"interaction_preferences": ["先看例子，再动手试"]},
            dimensions=_candidate()["dimensions"],
            attributions=_candidate()["weakPointAttribution"],
            continue_conversation=True,
        )
        assert continued["active"] is True
        assert continued["status"] == "in_progress"
        assert continued["turns"][0]["status"] == "confirmed"
        assert continued["profileVersion"] == "profile.continuous.v1"
        assert db.query(DBProfileSnapshot).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_continuous_turn_saves_original_before_extraction_and_confirmation_projects_version():
    engine, db = _database()
    try:
        user, course = _learner(db)
        start_continuous_update(db, user, course_id=course.id)
        answer = "最近我能独立推导线性回归，但一遇到正则化就容易混淆"

        def extractor(text, profile, context):
            saved = db.query(DBOnboardingTurn).filter_by(turn_id="continuous-1").one()
            assert saved.status == "saved"
            assert saved.user_answer == answer
            assert context["courseId"] == course.id
            return _candidate(text)

        pending = record_continuous_turn(
            db, user, turn_id="continuous-1", user_answer=answer,
            course_id=course.id, extractor=extractor,
        )
        assert pending["turns"][0]["status"] == "awaiting_confirmation"
        assert db.get(DBStudentProfile, user.username).weak_points == []
        assert db.query(DBProfileSnapshot).count() == 0

        confirmed = confirm_continuous_turn(
            db, user, turn_id="continuous-1",
            fields={"weak_points": ["正则化"], "misconception_patterns": {"正则化": 0.64, "交叉验证": 0.0}},
            dimensions=_candidate()["dimensions"],
            attributions=_candidate()["weakPointAttribution"],
        )
        assert confirmed["turns"][0]["status"] == "confirmed"
        assert confirmed["profileVersion"] == "profile.continuous.v1"
        profile = db.get(DBStudentProfile, user.username)
        assert profile.weak_points == ["正则化"]
        assert profile.misconception_patterns == {"正则化": 0.64, "交叉验证": 0.0}
        snapshot = db.query(DBProfileSnapshot).one()
        assert snapshot.snapshot["course_id"] == course.id
        assert snapshot.snapshot["profile_version"] == "profile.continuous.v1"
        assert snapshot.snapshot["evidence"][0]["text"]
    finally:
        db.close()
        engine.dispose()


def test_model_failure_keeps_original_and_allows_manual_review_confirmation():
    engine, db = _database()
    try:
        user, course = _learner(db, "failure")
        start_continuous_update(db, user, course_id=course.id)
        pending = record_continuous_turn(
            db, user, turn_id="continuous-failure",
            user_answer="我最近总把召回率和精确率混在一起。",
            course_id=course.id,
            extractor=lambda *_: (_ for _ in ()).throw(RuntimeError("model unavailable")),
        )
        turn = pending["turns"][0]
        assert turn["status"] == "extraction_failed"
        assert turn["userAnswer"] == "我最近总把召回率和精确率混在一起。"
        confirmed = confirm_continuous_turn(
            db, user, turn_id="continuous-failure",
            fields={"weak_points": ["召回率和精确率"]},
        )
        assert confirmed["turns"][0]["status"] == "confirmed"
        assert db.get(DBStudentProfile, user.username).weak_points == ["召回率和精确率"]
    finally:
        db.close()
        engine.dispose()


def test_continuous_update_is_course_scoped_and_does_not_mix_active_course():
    engine, db = _database()
    try:
        user, course_a = _learner(db, "course-a")
        course_b = DBCourse(
            id="course-p1-b02-course-b", version="1", title="数据结构",
            status="published", manifest_version="1",
        )
        db.add(course_b)
        _publish_material(db, course_b)
        db.add(DBCourseMembership(
            course_id=course_b.id, user_public_id=user.public_id,
            role="student", status="active",
        ))
        db.commit()
        start_continuous_update(db, user, course_id=course_a.id)
        try:
            record_continuous_turn(
                db, user, turn_id="wrong-course", user_answer="跨课程内容",
                course_id=course_b.id, extractor=lambda *_: _candidate(),
            )
        except Exception as error:
            assert getattr(error, "code", "") == "update_in_progress_course"
        else:
            raise AssertionError("active update must reject a different course")
        assert db.query(DBOnboardingTurn).filter_by(turn_id="wrong-course").count() == 0
    finally:
        db.close()
        engine.dispose()


def test_three_day_reminder_is_read_only_deduplicated_and_clears_after_new_confirmation():
    engine, db = _database()
    try:
        user, course = _learner(db, "reminder")
        session = get_or_create_session(db, user)
        old = datetime.utcnow() - timedelta(days=3, hours=1)
        session.confirmed_at = old
        db.add(DBProfileSnapshot(
            id="ps-p1-b02-reminder-old", owner_public_id=user.public_id,
            legacy_student_id=user.username, profile_version="onboarding.initial.v1",
            snapshot={"course_context": {"courseId": course.id}},
            content_hash="old", trace_id="old",
            created_at=old,
        ))
        db.commit()
        before = dict(session.course_context or {})
        first = continuous_update_reminder(db, user, course_id=course.id)
        second = continuous_update_reminder(db, user, course_id=course.id)
        assert first["due"] is True
        assert second == first
        assert dict(db.get(DBOnboardingSession, session.id).course_context or {}) == before

        dismissed = dismiss_continuous_update_reminder(db, user, course_id=course.id)
        assert dismissed["due"] is False
        assert continuous_update_reminder(db, user, course_id=course.id)["due"] is False
    finally:
        db.close()
        engine.dispose()


def test_old_snapshot_remains_readable_after_new_profile_version():
    engine, db = _database()
    try:
        user, course = _learner(db, "history")
        start_continuous_update(db, user, course_id=course.id)
        for index in (1, 2):
            record_continuous_turn(
                db, user, turn_id=f"history-{index}", user_answer=f"第{index}次我在正则化上有变化。",
                course_id=course.id, extractor=lambda text, *_: _candidate(text),
            )
            confirm_continuous_turn(
                db, user, turn_id=f"history-{index}",
                fields={"weak_points": [f"正则化-{index}"]},
                dimensions=_candidate()["dimensions"],
                attributions=_candidate()["weakPointAttribution"],
            )
            if index == 1:
                first_id = db.query(DBProfileSnapshot).order_by(DBProfileSnapshot.created_at.asc()).one().id
        snapshots = db.query(DBProfileSnapshot).filter_by(owner_public_id=user.public_id).order_by(
            DBProfileSnapshot.created_at.asc(), DBProfileSnapshot.id.asc(),
        ).all()
        assert len(snapshots) == 2
        assert db.get(DBProfileSnapshot, first_id).profile_version == "profile.continuous.v1"
        assert snapshots[-1].profile_version == "profile.continuous.v2"
    finally:
        db.close()
        engine.dispose()


def test_legacy_ml_and_history_fields_are_carried_into_the_canonical_snapshot():
    engine, db = _database()
    try:
        user, course = _learner(db, "legacy")
        profile = db.get(DBStudentProfile, user.username)
        profile.bkt_states = {"正则化": {"p_mastery": 0.41}}
        profile.knowledge_traces = {"正则化": {"attempts": 3, "correct_attempts": 1}}
        profile.history_logs = "legacy-analysis-2026-08"
        profile.mental_state_history = [{"timestamp": "2026-08-01", "cognitive_load": 0.7}]
        db.commit()
        start_continuous_update(db, user, course_id=course.id)
        record_continuous_turn(
            db, user, turn_id="legacy-update", user_answer="最近正则化还是容易错。",
            course_id=course.id, extractor=lambda text, *_: _candidate(text),
        )
        confirm_continuous_turn(
            db, user, turn_id="legacy-update",
            fields={"weak_points": ["正则化"]},
            dimensions=_candidate()["dimensions"],
            attributions=_candidate()["weakPointAttribution"],
        )
        snapshot = db.query(DBProfileSnapshot).one()
        projection = snapshot.snapshot["profile_projection"]
        assert projection["bkt_states"]["正则化"]["p_mastery"] == 0.41
        assert projection["knowledge_traces"]["正则化"]["attempts"] == 3
        assert projection["history_logs"] == "legacy-analysis-2026-08"
        assert projection["mental_state_history"][0]["cognitive_load"] == 0.7
    finally:
        db.close()
        engine.dispose()


def test_continuous_update_accepts_course_without_active_membership():
    engine, db = _database()
    try:
        user, course = _learner(db, "permission")
        foreign = DBCourse(
            id="course-p1-b02-foreign", version="1", title="未授权课程",
            status="published", manifest_version="1",
        )
        db.add(foreign)
        _publish_material(db, foreign)
        db.commit()
        payload = start_continuous_update(db, user, course_id=foreign.id)
        assert payload["courseContext"]["courseId"] == foreign.id
        assert payload["courseContext"]["title"] == foreign.title
        assert db.query(DBOnboardingSession).filter_by(owner_public_id=user.public_id).count() == 1
        assert course.id != foreign.id
    finally:
        db.close()
        engine.dispose()


def test_continuous_update_rejects_course_without_learning_material():
    engine, db = _database()
    try:
        user, course = _learner(db, "empty-course")
        db.query(DBCourseDocument).filter_by(course_id=course.id).delete()
        db.commit()
        with pytest.raises(onboarding.OnboardingError) as error:
            start_continuous_update(db, user, course_id=course.id)
        assert error.value.code == "course_unavailable"
    finally:
        db.close()
        engine.dispose()
