from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.competition_demo_seed import seed_competition_demo
from app.database import DBAssessmentQuestionVersion, DBGenerationTask, DBProfileSnapshot, DBSourceDocument, DBSourceRef, DBUser
from app.m1_repository import create_artifact_with_version
from app.m5_resources import _quiz_projection
from app.resource_bundles import (
    _create_quiz_resource_content,
    _generation_manifest,
    _normalize_quiz_options,
    _source_snapshots,
    create_generation_job,
)
from tests.test_f6_t03_code_sandbox_resource import _session


COURSE_ID = "demo-course-rag-trust-v1"


def test_model_option_object_is_persisted_as_option_text_not_keys() -> None:
    assert _normalize_quiz_options(
        {"A": "选择正确的课程机制", "B": "只记术语", "C": "只看标题", "D": "引用无关结论"},
        position=1,
    ) == ("选择正确的课程机制", "只记术语", "只看标题", "引用无关结论")


def test_letter_only_options_are_rejected_instead_of_persisted() -> None:
    from app.resource_bundles import ResourceBundleError

    with pytest.raises(ResourceBundleError, match="四个非空选项正文"):
        _normalize_quiz_options(["A", "B", "C", "D"], position=1)


def test_live_quiz_projection_keeps_prompt_and_option_bodies() -> None:
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        profile = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
        source = (
            session.query(DBSourceRef)
            .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
            .filter(DBSourceDocument.course_id == COURSE_ID)
            .first()
        )
        assert profile is not None and source is not None
        job = create_generation_job(
            session,
            learner,
            course_id=COURSE_ID,
            knowledge_point_id="demo-kp-07",
            profile_snapshot_id=profile.id,
            idempotency_key="noc-t17-live-options",
            scope="single",
            items=[{"type": "quiz", "title": "题干显示回归", "source_ref_ids": [source.id]}],
            learning_goal="验证资源测验题干和选项正文",
        )
        task = session.get(DBGenerationTask, job["job_id"])
        manifest = _generation_manifest(session, task.id)
        snapshots = _source_snapshots(session, course_id=COURSE_ID, source_ref_ids=[source.id], require_available=True)
        content_text = _create_quiz_resource_content(
            session,
            actor=learner,
            task=task,
            item=manifest["items"][0],
            manifest=manifest,
            source_snapshots=snapshots,
            llm_payload={
                "summary": "模型生成的测验",
                "quizQuestions": [
                    {"prompt": "题干一", "options": {"A": "选项一", "B": "选项二", "C": "选项三", "D": "选项四"}, "answer": "A", "explanation": "解析一", "bloom": "remember", "difficulty": 0.3},
                    {"prompt": "题干二", "options": {"A": "选项甲", "B": "选项乙", "C": "选项丙", "D": "选项丁"}, "answer": "B", "explanation": "解析二", "bloom": "understand", "difficulty": 0.5},
                    {"prompt": "题干三", "options": {"A": "选项甲一", "B": "选项乙二", "C": "选项丙三", "D": "选项丁四"}, "answer": "C", "explanation": "解析三", "bloom": "apply", "difficulty": 0.7},
                ],
            },
        )
        content = json.loads(content_text)
        versions = [session.get(DBAssessmentQuestionVersion, ref["questionVersionId"]) for ref in content["questions"]]
        assert [version.prompt.endswith(value) for version, value in zip(versions, ("题干一", "题干二", "题干三"))] == [True, True, True]
        assert [list(version.options) for version in versions] == [
            ["选项一", "选项二", "选项三", "选项四"],
            ["选项甲", "选项乙", "选项丙", "选项丁"],
            ["选项甲一", "选项乙二", "选项丙三", "选项丁四"],
        ]
        assert all(list(version.options) != ["A", "B", "C", "D"] for version in versions)
        artifact, artifact_version = create_artifact_with_version(
            session,
            owner_public_id=learner.public_id,
            artifact_type="quiz",
            title="题干显示回归",
            content=content_text,
            content_format="json",
            course_id=COURSE_ID,
            creating_task_id=task.id,
            metadata={"resource_type": "quiz", "source_ref_ids": [source.id]},
        )
        projection = _quiz_projection(session, artifact, artifact_version)
        assert projection["mode"] == "structured"
        assert [question["prompt"].endswith(value) for question, value in zip(projection["questions"], ("题干一", "题干二", "题干三"))] == [True, True, True]
        assert projection["questions"][0]["options"] == ["选项一", "选项二", "选项三", "选项四"]
    finally:
        session.close()
        engine.dispose()


def test_inline_quiz_card_renders_bodies_and_rejects_letter_only_history() -> None:
    source = Path("frontend/src/components/InlineQuizCard.vue").read_text(encoding="utf-8")
    assert "{{ question.prompt }}" in source
    assert "{{ optionText(option, index) }}" in source
    assert "option.text || option.content || option.option || option.value" in source
    assert "text.toUpperCase() === optionLabel(option, index)" in source
    assert "题目选项正文未保存，请重新生成这份测验资源。" in source
    assert "{{ unavailableReason }}" in source
