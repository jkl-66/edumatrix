from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import (
    Base,
    DBAssessmentAttempt,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBAssessmentRetestTask,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCheckinLog,
    DBCourse,
    DBCourseMembership,
    DBGenerationTask,
    DBKnowledgePoint,
    DBLearningEvent,
    DBMisconceptionReview,
    DBProfileSnapshot,
    DBReviewPlan,
    DBSourceDocument,
    DBSourceRef,
    DBStudentProfile,
    DBTaskEvent,
    DBUser,
)
from app.review_schedule import (
    ReviewScheduleError,
    build_review_schedule,
    complete_review_task,
    create_review_resource_job,
)


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=None)


def _fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    learner = DBUser(
        public_id="f8-learner",
        username="f8-learner",
        hashed_password="x",
        role="student",
        is_active=True,
    )
    other = DBUser(
        public_id="f8-other",
        username="f8-other",
        hashed_password="x",
        role="student",
        is_active=True,
    )
    course = DBCourse(
        id="f8-course",
        version="1",
        title="机器学习导论",
        visibility="private",
        status="published",
        manifest_version="f8-course-v1",
    )
    session.add_all([
        learner,
        other,
        course,
        DBCourseMembership(
            course_id=course.id,
            user_public_id=learner.public_id,
            role="student",
            status="active",
        ),
        DBStudentProfile(
            student_id=learner.username,
            target_course=course.title,
            concept_mastery={"kp-gradient": 0.42},
        ),
        DBStudentProfile(student_id=other.username),
    ])
    session.flush()
    document = DBSourceDocument(
        id="f8-source",
        course_id=course.id,
        title="优化算法讲义",
        filename="optimization.md",
        file_format="markdown",
        content_hash="a" * 64,
        source_sha256="b" * 64,
        processed_sha256="c" * 64,
        processing_status="ready",
    )
    chapter = DBChapter(
        id="f8-chapter",
        course_id=course.id,
        source_document_id=document.id,
        stable_key="chapter-gradient",
        title="梯度下降",
    )
    point = DBKnowledgePoint(
        id="kp-gradient",
        domain_pack="machine-learning",
        code="gradient",
        version="1",
        title="梯度下降",
    )
    session.add_all([document, chapter, point])
    session.flush()
    session.add_all([
        DBChapterKnowledgePoint(
            id="f8-chapter-kp",
            chapter_id=chapter.id,
            knowledge_point_id=point.id,
        ),
        DBSourceRef(
            id="f8-ref",
            source_document_id=document.id,
            chapter_id=chapter.id,
            parser_version="f8-parser-v1",
            location_kind="section",
            location_index=1,
            location_label="第 2 章",
            content_hash="d" * 64,
            quote="梯度下降沿负梯度方向更新参数。",
        ),
        DBProfileSnapshot(
            id="f8-profile-snapshot",
            owner_public_id=learner.public_id,
            legacy_student_id=learner.username,
            profile_version="1",
            snapshot={"course_id": course.id, "mastery": {point.id: 0.42}},
            content_hash="e" * 64,
            trace_id="f8-profile-trace",
        ),
    ])
    session.flush()
    plans = [
        DBReviewPlan(
            student_id=learner.username,
            concept=point.id,
            next_review_at=_utc("2026-08-14T02:00:00"),
            interval_days=1,
            mastery=0.42,
            priority=0.35,
        ),
        DBReviewPlan(
            student_id=learner.username,
            concept="未归类旧知识点",
            next_review_at=_utc("2026-08-16T04:00:00"),
            interval_days=1,
            mastery=0.35,
            priority=0.5,
        ),
    ]
    session.add_all(plans)
    session.flush()
    session.add(DBLearningEvent(
        id="f8-completed-event",
        owner_public_id=learner.public_id,
        legacy_student_id=learner.username,
        course_id=course.id,
        event_type="review_completed",
        schema_version="m5.learning-event.v1",
        idempotency_key="f8-existing-completion",
        source="backend",
        trace_id="f8-existing-trace",
        object_type="knowledge_point",
        object_id=point.id,
        action="review.completed",
        context_ref={
            "userId": learner.public_id,
            "courseId": course.id,
            "chapterId": chapter.id,
            "knowledgePointId": point.id,
        },
        evidence_strength=0.7,
        evidence_status="accepted",
        evidence_reason="服务端确认的复习证据",
        mastery_eligible=True,
        completion_effect="complete",
        payload_version="1",
        payload={
            "review_id": "review-plan:old",
            "recall_score": 0.8,
            "concept": point.id,
            "duration_minutes": 12,
        },
        occurred_at=_utc("2026-08-15T03:00:00"),
    ))
    session.commit()
    return session, engine, learner, other, course, point, plans


def test_calendar_uses_real_42_day_grid_and_preserves_day_task_consistency():
    session, engine, learner, _, course, _, _ = _fixture()
    try:
        before = {
            "events": session.query(DBLearningEvent).count(),
            "plans": session.query(DBReviewPlan).count(),
            "checkins": session.query(DBCheckinLog).count(),
        }
        payload = build_review_schedule(
            session,
            actor=learner,
            month="2026-08",
            now=datetime(2026, 8, 16, 8, tzinfo=timezone.utc),
        )
        after = {
            "events": session.query(DBLearningEvent).count(),
            "plans": session.query(DBReviewPlan).count(),
            "checkins": session.query(DBCheckinLog).count(),
        }

        assert payload["schema_version"] == "f8.review-schedule.v1"
        assert len(payload["days"]) == 42
        assert payload["days"][0]["date"] == "2026-07-27"
        assert payload["days"][-1]["date"] == "2026-09-06"
        assert payload["weekdays"] == ["一", "二", "三", "四", "五", "六", "日"]
        assert before == after

        by_date = {item["date"]: item for item in payload["days"]}
        tasks_by_date = {
            day: [item for item in payload["tasks"] if item["date"] == day]
            for day in by_date
        }
        for day, summary in by_date.items():
            assert summary["counts"]["total"] == len(tasks_by_date[day])
            assert summary["task_ids"] == [item["id"] for item in tasks_by_date[day]]
        assert by_date["2026-08-14"]["state"] == "overdue"
        assert by_date["2026-08-15"]["state"] == "completed"
        assert by_date["2026-08-16"]["state"] == "today"
        assert payload["courses"][0] == {"id": course.id, "title": course.title}
        assert payload["courses"][-1] == {"id": "unclassified", "title": "未归类计划"}
    finally:
        session.close()
        engine.dispose()


def test_calendar_handles_leap_month_and_course_filters_without_guessing_legacy_context():
    session, engine, learner, _, course, _, _ = _fixture()
    try:
        leap = build_review_schedule(
            session,
            actor=learner,
            month="2028-02",
            now=datetime(2028, 2, 1, tzinfo=timezone.utc),
        )
        assert len(leap["days"]) == 42
        assert any(item["date"] == "2028-02-29" and item["in_month"] for item in leap["days"])

        classified = build_review_schedule(
            session,
            actor=learner,
            month="2026-08",
            course_id=course.id,
            now=datetime(2026, 8, 16, tzinfo=timezone.utc),
        )
        assert classified["tasks"]
        assert all(item["course_id"] == course.id for item in classified["tasks"])

        unclassified = build_review_schedule(
            session,
            actor=learner,
            month="2026-08",
            course_id="unclassified",
            now=datetime(2026, 8, 16, tzinfo=timezone.utc),
        )
        assert [item["knowledge_point_title"] for item in unclassified["tasks"]] == ["未归类旧知识点"]
        assert unclassified["tasks"][0]["resource_generation"]["ready"] is False
        assert "课程归属" in unclassified["tasks"][0]["resource_generation"]["block_reason"]

        with pytest.raises(ReviewScheduleError) as exc_info:
            build_review_schedule(
                session,
                actor=learner,
                month="2026-13",
                now=datetime(2026, 8, 16, tzinfo=timezone.utc),
            )
        assert exc_info.value.code == "review_schedule.month_invalid"
    finally:
        session.close()
        engine.dispose()


def test_completion_is_trusted_idempotent_and_reuses_five_step_aggregation():
    session, engine, learner, _, _, point, plans = _fixture()
    try:
        task_id = f"review-plan:{plans[0].id}"
        first = complete_review_task(
            session,
            actor=learner,
            task_id=task_id,
            idempotency_key="f8-review-submit-0001",
            recall_score=0.8,
            duration_minutes=15,
        )
        second = complete_review_task(
            session,
            actor=learner,
            task_id=task_id,
            idempotency_key="f8-review-submit-0001",
            recall_score=0.8,
            duration_minutes=15,
        )

        assert first["created"] is True
        assert second["created"] is False
        assert first["event"]["id"] == second["event"]["id"]
        assert first["event"]["status"] == "accepted"
        assert first["aggregation"]["status"] == "processed"
        assert session.query(DBLearningEvent).filter_by(
            idempotency_key="f8-review-submit-0001",
        ).count() == 1
        assert session.query(DBCheckinLog).filter_by(student_id=learner.username).count() == 1

        refreshed = session.get(DBReviewPlan, plans[0].id)
        assert refreshed.concept == point.title
        assert refreshed.review_count == 2
        assert refreshed.next_review_at > _utc("2026-08-16T00:00:00")
        profile = session.get(DBStudentProfile, learner.username)
        assert profile.concept_mastery[point.title] > 0.42

        with pytest.raises(ReviewScheduleError) as conflict:
            complete_review_task(
                session,
                actor=learner,
                task_id=task_id,
                idempotency_key="f8-review-submit-0001",
                recall_score=0.2,
                duration_minutes=15,
            )
        assert conflict.value.code == "review_schedule.idempotency_conflict"
    finally:
        session.close()
        engine.dispose()


def test_resource_action_reuses_nine_type_job_and_does_not_create_exam_gate_rules():
    session, engine, learner, _, _, _, plans = _fixture()
    try:
        task_id = f"review-plan:{plans[0].id}"
        result = create_review_resource_job(
            session,
            actor=learner,
            task_id=task_id,
            idempotency_key="f8-review-resource-0001",
        )
        repeated = create_review_resource_job(
            session,
            actor=learner,
            task_id=task_id,
            idempotency_key="f8-review-resource-0001",
        )

        assert result["created"] is True
        assert repeated["created"] is False
        assert result["job_id"] == repeated["job_id"]
        assert [item["type"] for item in result["items"]] == [
            "handout",
            "mind_map",
            "quiz",
            "training_task",
            "code_sandbox",
            "video",
            "deck",
            "interactive_model",
            "feynman",
        ]
        task = session.get(DBGenerationTask, result["job_id"])
        assert task.capability == "learning_resource_bundle.generate"
        manifest_event = session.query(DBTaskEvent).filter_by(
            task_id=task.id,
            event_type="resource_generation.requested",
        ).one()
        assert "exam_gate" not in (manifest_event.payload or {}).get("manifest", {})
    finally:
        session.close()
        engine.dispose()


def test_delayed_retest_reuses_the_same_resource_context_and_owner_boundary():
    session, engine, learner, other, course, point, _ = _fixture()
    try:
        question = DBAssessmentQuestion(
            id="f8-retest-question",
            course_id=course.id,
            owner_public_id=learner.public_id,
            question_type="single_choice",
            status="approved",
        )
        session.add(question)
        session.flush()
        version = DBAssessmentQuestionVersion(
            id="f8-retest-version",
            question_id=question.id,
            version_number=1,
            prompt="梯度下降沿哪个方向更新？",
            options=["正梯度", "负梯度"],
            answer_key={"choice": "B"},
            scoring_rule={"type": "exact"},
            primary_knowledge_point_id=point.id,
            source_ref_ids=["f8-ref"],
            content_hash="f" * 64,
            created_by_public_id=learner.public_id,
        )
        session.add(version)
        session.flush()
        question.current_version_id = version.id
        attempt = DBAssessmentAttempt(
            id="f8-retest-source-attempt",
            owner_public_id=learner.public_id,
            course_id=course.id,
            question_version_id=version.id,
            idempotency_key="f8-retest-source-attempt-key",
            answer={"choice": "A"},
            score=0.0,
            correct=False,
        )
        session.add(attempt)
        session.flush()
        misconception = DBMisconceptionReview(
            id="f8-retest-misconception",
            owner_public_id=learner.public_id,
            attempt_id=attempt.id,
            candidate_category="knowledge_gap",
            status="accepted",
        )
        session.add(misconception)
        session.flush()
        retest = DBAssessmentRetestTask(
            id="f8-retest-task",
            owner_public_id=learner.public_id,
            misconception_review_id=misconception.id,
            source_attempt_id=attempt.id,
            question_version_id=version.id,
            course_id=course.id,
            due_at=_utc("2026-08-16T04:00:00"),
            status="due",
        )
        session.add(retest)
        session.commit()

        result = create_review_resource_job(
            session,
            actor=learner,
            task_id=f"retest:{retest.id}",
            idempotency_key="f8-retest-resource-0001",
        )
        assert result["created"] is True
        assert [item["type"] for item in result["items"]] == [
            "handout", "mind_map", "quiz", "training_task", "code_sandbox",
            "video", "deck", "interactive_model", "feynman",
        ]
        with pytest.raises(ReviewScheduleError) as forbidden:
            create_review_resource_job(
                session,
                actor=other,
                task_id=f"retest:{retest.id}",
                idempotency_key="f8-retest-resource-cross-owner",
            )
        assert forbidden.value.code == "review_schedule.task_unknown"
    finally:
        session.close()
        engine.dispose()


def test_review_tasks_are_owner_scoped():
    session, engine, learner, other, _, _, plans = _fixture()
    try:
        task_id = f"review-plan:{plans[0].id}"
        with pytest.raises(ReviewScheduleError) as exc_info:
            complete_review_task(
                session,
                actor=other,
                task_id=task_id,
                idempotency_key="f8-cross-owner-0001",
                recall_score=0.8,
                duration_minutes=10,
            )
        assert exc_info.value.code == "review_schedule.task_unknown"
    finally:
        session.close()
        engine.dispose()
