from datetime import datetime, timezone

import json
import pytest

from app.database import (
    DBAssessmentAttempt,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBLearningEvent,
    DBReviewPlan,
    DBUser,
)
from app.m1_repository import create_artifact_with_version
from app.review_schedule import ReviewScheduleError, build_review_schedule, complete_review_task
from app.m5_learning import today_work_items
from app.m5_resources import resource_detail
from app.resource_bundles import _attach_canonical_binding_identity, _version_generation_metadata
from tests.test_f8_t01_review_schedule import _fixture
from tests.test_f5_t04_mindmap_workspace import _content as mindmap_content, _mindmap, _session as _mindmap_session
from tests.test_r3_today_tasks import COURSE_ID, _session as _today_fixture
from app.competition_demo_seed import seed_competition_demo


def test_review_schedule_exposes_resource_then_intelligent_assessment_without_writes():
    session, engine, learner, _, _, _, plans = _fixture()
    try:
        before = {
            "events": session.query(DBLearningEvent).count(),
            "plans": session.query(DBReviewPlan).count(),
        }
        payload = build_review_schedule(
            session,
            actor=learner,
            month="2026-08",
            now=datetime(2026, 8, 16, 8, tzinfo=timezone.utc),
        )
        task = next(item for item in payload["tasks"] if item["source_type"] == "sm2_review_plan")

        assert task["method"] == "先回顾当前知识点的授权资源，再完成一次智能组卷并提交作答。"
        assert task["completion_rule"] == "完成资源回顾并提交一次服务端判分的智能组卷作答。"
        assert task["review_flow"]["sequence"] == ["resource_review", "intelligent_assessment", "submit"]
        assert task["review_flow"]["resource_review"]["source_ref_ids"] == ["f8-ref"]
        assert task["review_flow"]["assessment"]["status"] == "pending"
        assert task["review_flow"]["completion_requires_assessment"] is True
        assert before == {
            "events": session.query(DBLearningEvent).count(),
            "plans": session.query(DBReviewPlan).count(),
        }
    finally:
        session.close()
        engine.dispose()


def _assessment(session, learner, course, point, *, status="graded", score=0.75, suffix="one"):
    question_id = f"b15-question-{suffix}"
    version_id = f"b15-question-version-{suffix}"
    attempt_id = f"b15-assessment-attempt-{suffix}"
    question = DBAssessmentQuestion(
        id=question_id,
        owner_public_id=learner.public_id,
        course_id=course.id,
        question_type="single_choice",
        origin="manual",
        status="approved",
    )
    session.add(question)
    session.flush()
    version = DBAssessmentQuestionVersion(
        id=version_id,
        question_id=question_id,
        version_number=1,
        prompt="选择正确的梯度方向",
        options=["A", "B"],
        answer_key={"choice": "B"},
        scoring_rule={"type": "exact"},
        content_hash="b" * 64,
        created_by_public_id=learner.public_id,
        primary_knowledge_point_id=point.id,
    )
    session.add(version)
    session.flush()
    question.current_version_id = version.id
    attempt = DBAssessmentAttempt(
        id=attempt_id,
        owner_public_id=learner.public_id,
        course_id=course.id,
        question_version_id=version.id,
        idempotency_key=f"b15-attempt-{status}",
        mode="practice",
        answer={"choice": "B"},
        score=score,
        correct=True,
        duration_seconds=90,
        grading_status=status,
    )
    session.add(attempt)
    session.flush()
    return attempt


def test_review_completion_accepts_only_a_graded_matching_assessment_for_new_flow():
    session, engine, learner, _, course, point, plans = _fixture()
    try:
        pending = _assessment(session, learner, course, point, status="pending", suffix="pending")
        before = session.query(DBLearningEvent).count()
        with pytest.raises(ReviewScheduleError) as exc_info:
            complete_review_task(
                session,
                actor=learner,
                task_id=f"review-plan:{plans[0].id}",
                idempotency_key="b15-pending-submit",
                recall_score=0.9,
                duration_minutes=12,
                assessment_attempt_id=pending.id,
            )
        assert exc_info.value.code == "review_schedule.assessment_not_graded"
        assert session.query(DBLearningEvent).count() == before

        session.delete(pending)
        session.flush()
        graded = _assessment(session, learner, course, point, status="graded", score=0.75, suffix="graded")
        result = complete_review_task(
            session,
            actor=learner,
            task_id=f"review-plan:{plans[0].id}",
            idempotency_key="b15-graded-submit",
            recall_score=0.1,
            duration_minutes=12,
            assessment_attempt_id=graded.id,
        )
        assert result["created"] is True
        assert result["assessment"] == {
            "required": True,
            "attempt_id": graded.id,
            "event_id": None,
            "score": 0.75,
            "submitted": True,
        }
        event = session.query(DBLearningEvent).filter_by(idempotency_key="b15-graded-submit").one()
        assert event.payload["assessment_attempt_id"] == graded.id
        assert event.payload["assessment_score"] == 0.75
        assert event.payload["recall_score"] == 0.75
    finally:
        session.close()
        engine.dispose()


def test_today_new_learning_is_followed_by_the_real_review_flow_without_writes():
    engine, session = _today_fixture()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        before = {
            "events": session.query(DBLearningEvent).count(),
            "plans": session.query(DBReviewPlan).count(),
        }
        items = list(today_work_items(
            session, owner_public_id=learner.public_id, course_id=COURSE_ID, limit=3,
        ))
        assert items and items[0]["task_kind"] == "path"
        review = next(item for item in items[1:] if item["task_kind"] == "review")
        assert items.index(review) == 1
        assert review["completion_criteria"] == "先回顾该知识点的授权资源，再完成一次智能组卷并提交服务端判分结果。"
        assert review["continue_route"].startswith("/workspace/review?review_task=review-plan:")
        assert review["review_flow"]["sequence"] == ["resource_review", "intelligent_assessment", "submit"]
        assert review["review_flow"]["completion_requires_assessment"] is True
        after = {
            "events": session.query(DBLearningEvent).count(),
            "plans": session.query(DBReviewPlan).count(),
        }
        assert before == after
    finally:
        session.close()
        engine.dispose()


def test_mindmap_projection_exposes_canonical_artifact_version_and_linked_source_bindings():
    session = _mindmap_session()
    try:
        artifact, version, source_ref, handout = _mindmap(
            session,
            content=mindmap_content(linked_id="unused-linked-id"),
        )
        # Replace the deliberately unavailable link with the actual handout while keeping
        # the test focused on the canonical binding projection.
        payload = json.loads(version.content)
        for node in payload["nodes"]:
            node["linkedResourceIds"] = [handout.id] if node["nodeId"] == "root" else []
        version.content = json.dumps(payload, ensure_ascii=False)
        session.commit()

        projection = resource_detail(session, artifact)["mindmap"]["current"]
        binding = projection["canonical_binding"]
        assert binding["artifact_id"] == artifact.id
        assert binding["artifact_version_id"] == version.id
        assert binding["course_id"] == artifact.course_id
        assert binding["source_ref_ids"] == [source_ref.id]
        assert binding["source_status"] == "available"
        linked = projection["linked_resource_bindings"]
        assert linked and linked[0]["artifact_id"] == handout.id
        assert linked[0]["artifact_version_id"]
        assert linked[0]["source_ref_ids"] == [source_ref.id]
    finally:
        session.close()


def test_generated_resource_metadata_keeps_canonical_binding_after_ids_exist():
    session = _mindmap_session()
    try:
        source_artifact, source_version, source_ref, handout = _mindmap(session)
        source_snapshots = [{
            "source_ref_id": source_ref.id,
            "title": "优化算法课程讲义",
            "location_label": "第 2 章 梯度下降",
            "available": True,
        }]
        manifest = {
            "course_id": source_artifact.course_id,
            "knowledge_point_id": "kp-gradient",
            "profile_snapshot_id": "profile-gradient-v1",
            "context": {
                "knowledge_point_title": "梯度下降",
                "learning_goal": "解释梯度下降更新机制",
                "profile_adaptation": "先建立直觉，再完成练习",
                "mastery_summary": "当前仍需巩固",
                "recent_learning_summary": "近期有学习记录",
            },
            "input_snapshot": {
                "profile_snapshot_hash": "profile-hash",
                "source_snapshot_hashes": {},
                "input_snapshot_hash": "input-hash",
            },
        }
        metadata = _version_generation_metadata(
            manifest=manifest,
            resource_type="mind_map",
            source_snapshots=source_snapshots,
            content=source_version.content,
            question_version_ids=[],
            task_id="generation-task-b15",
            attempt=1,
            completion_rule="查看导图并完成理解检查。",
            generation_mode="llm",
            model="deepseek-v4-flash",
            reasoning_effort="max",
        )
        artifact, version = create_artifact_with_version(
            session,
            owner_public_id=source_artifact.owner_public_id,
            course_id=source_artifact.course_id,
            artifact_type="mind_map",
            title="绑定测试导图",
            content=source_version.content,
            content_format="json",
            metadata=metadata,
        )
        _attach_canonical_binding_identity(
            session,
            artifact=artifact,
            version=version,
            resource_type="mind_map",
            content=version.content,
        )
        session.commit()

        binding = (session.get(type(version), version.id).metadata_json or {})["canonical_binding"]
        assert binding["artifact_id"] == artifact.id
        assert binding["artifact_version_id"] == version.id
        assert binding["source_ref_ids"] == [source_ref.id]
        assert binding["linked_resource_bindings"][0]["artifact_id"] == handout.id
        assert binding["linked_resource_bindings"][0]["artifact_version_id"]
    finally:
        session.close()
