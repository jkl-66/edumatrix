from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBArtifact,
    DBArtifactVersion,
    DBLearningEvent,
    DBLearningEventConsumption,
    DBProfileSnapshot,
    DBSourceRef,
    DBUser,
)
from app.feynman import (
    FeynmanError,
    _focus_relevant_to_knowledge,
    apply_action,
    create_session,
    get_session,
    list_sessions,
)
from app.resource_bundles import create_generation_job, execute_generation_job_demo


ROOT = Path(__file__).resolve().parents[1]
COURSE_ID = "demo-course-rag-trust-v1"


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _resource(session, learner: DBUser, key: str = "f6-t05-resource-001") -> DBArtifact:
    source = session.get(DBSourceRef, "demo-ref-07")
    profile = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
    assert source is not None and profile is not None
    job = create_generation_job(
        session,
        learner,
        course_id=COURSE_ID,
        knowledge_point_id="demo-kp-07",
        profile_snapshot_id=profile.id,
        idempotency_key=key,
        scope="single",
        items=[{
            "type": "feynman",
            "title": "混合检索费曼复述",
            "source_ref_ids": [source.id],
            "completion_rule": "完成两轮复述、真实追问、对比并应用学习结果",
        }],
        learning_goal="用自己的话解释混合检索机制、条件、例子和边界",
    )
    session.commit()
    result = execute_generation_job_demo(session, learner, job["job_id"])
    session.commit()
    item = result["items"][0]
    assert item["state"] == "succeeded"
    return session.get(DBArtifact, item["resource"]["resource_id"])


def _action(session, learner, payload, action, key, text=None):
    return apply_action(
        session,
        session_id=payload["session_id"],
        actor=learner,
        action=action,
        text=text,
        expected_version=payload["version_number"],
        idempotency_key=key,
    )[0]


ROUND1 = (
    "混合检索是把关键词检索和向量检索结合起来解决单一检索方式覆盖不足的问题。"
    "先接收查询，然后分别召回候选并进行排序，因此输出更相关的课程片段。"
)
ROUND2 = (
    "混合检索是把关键词检索和向量检索结合起来解决单一检索覆盖不足的问题。"
    "它的输入是查询和课程索引，先分别召回，再按权重合并和重排，因此得到可核对的来源结果。"
    "前提是两类索引属于同一课程版本并保持用户隔离。例如术语查询可提高关键词权重，语义改写可提高向量权重。"
    "但是权重不是越大越好，忽略课程范围和来源版本就是常见误区；当来源撤回时结果也不应继续使用。"
)


def test_profile_focus_must_match_the_current_knowledge_topic():
    focus = "我容易混淆召回率、向量检索和关键词检索"
    assert not _focus_relevant_to_knowledge(focus, "优化算法、正则化与训练稳定性")
    assert _focus_relevant_to_knowledge(focus, "混合检索")
    assert _focus_relevant_to_knowledge("来源版本边界和失败恢复", "RAG 文档解析与混合检索")


def test_dynamic_task_owner_binding_and_versioned_recovery():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        other = session.query(DBUser).filter(DBUser.public_id != learner.public_id).first()
        resource = _resource(session, learner)

        artifact, version, state, created = create_session(
            session,
            owner=learner.public_id,
            source_resource_id=resource.id,
            idempotency_key="f6-t05-session-dynamic-001",
        )
        session.commit()
        assert created is True
        assert state.status == "draft"
        assert state.knowledge_point_id == "demo-kp-07"
        assert state.knowledge_point_title in state.task_prompt
        assert state.profile_snapshot_id
        assert state.source_refs[0].source_ref_id == "demo-ref-07"
        assert "accuracy" not in state.task_prompt.lower()
        assert "recall" not in state.task_prompt.lower()
        assert "kp-" not in state.task_prompt.lower()
        same = create_session(
            session,
            owner=learner.public_id,
            source_resource_id=resource.id,
            idempotency_key="f6-t05-session-dynamic-001",
        )
        assert same[3] is False
        assert same[0].id == artifact.id
        assert same[1].id == version.id

        with pytest.raises(FeynmanError) as exc_info:
            create_session(
                session,
                owner=other.public_id,
                source_resource_id=resource.id,
                idempotency_key="f6-t05-session-foreign-001",
            )
        assert exc_info.value.code == "feynman_source_forbidden"

        loaded = get_session(session, state.session_id, learner.public_id)
        assert loaded["status"] == "draft"
        assert len(loaded["history"]) == 1
        assert list_sessions(session, learner.public_id, resource.id)[0]["session_id"] == state.session_id
    finally:
        session.close()
        engine.dispose()


def test_state_machine_requires_real_question_and_preserves_original_rounds():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        resource = _resource(session, learner, "f6-t05-resource-state-001")
        _, _, state, _ = create_session(
            session,
            owner=learner.public_id,
            source_resource_id=resource.id,
            idempotency_key="f6-t05-session-state-001",
        )
        session.commit()
        payload = get_session(session, state.session_id, learner.public_id)
        baseline_events = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()

        with pytest.raises(FeynmanError) as exc_info:
            _action(session, learner, payload, "submit_round2", "f6-t05-invalid-round2-001", ROUND2)
        assert exc_info.value.code == "feynman_transition_invalid"

        payload = _action(session, learner, payload, "submit_round1", "f6-t05-submit-r1-001", ROUND1)
        assert payload["status"] == "round1_submitted"
        assert payload["round1_text"] == ROUND1
        payload = _action(session, learner, payload, "evaluate_round1", "f6-t05-evaluate-r1-001")
        assert payload["status"] == "review1_ready"
        assert payload["round1_evaluation"]["rubric_version"] == "f6.feynman-rubric.v1"
        assert "kp-" not in " ".join(
            item["evidence"] for item in payload["round1_evaluation"]["dimensions"]
        ).lower()
        payload = _action(session, learner, payload, "begin_question", "f6-t05-begin-question-001")
        assert payload["status"] == "question_pending"

        with pytest.raises(FeynmanError) as exc_info:
            _action(session, learner, payload, "answer_question", "f6-t05-empty-question-001", "为什么")
        assert exc_info.value.code == "feynman_question_too_short"
        with pytest.raises(FeynmanError):
            _action(session, learner, payload, "submit_round2", "f6-t05-early-round2-002", ROUND2)

        payload = _action(
            session,
            learner,
            payload,
            "answer_question",
            "f6-t05-answer-question-001",
            "为什么混合权重需要保持平衡，不能只提高向量检索权重？",
        )
        assert payload["status"] == "question_answered"
        assert payload["question_answer"]["source_ref_ids"] == ["demo-ref-07"]
        assert all(marker in payload["question_answer"]["answer"] for marker in (
            "重排只能", "完整链路", "关键信息缺失",
        ))
        assert not any(marker in payload["question_answer"]["answer"] for marker in (
            "deterministic_local", "sha256", ".md", "kp-",
        ))
        assert payload["external_model_called"] is False
        payload = _action(session, learner, payload, "submit_round2", "f6-t05-submit-r2-001", ROUND2)
        assert payload["status"] == "round2_submitted"
        payload = _action(session, learner, payload, "evaluate_round2", "f6-t05-evaluate-r2-001")
        assert payload["status"] == "comparison_ready"
        assert payload["round1_text"] == ROUND1
        assert payload["round2_text"] == ROUND2
        assert payload["comparison"]["first_score"] == payload["round1_evaluation"]["score"]
        assert payload["comparison"]["second_score"] == payload["round2_evaluation"]["score"]
        assert payload["comparison"]["score_delta"] > 0
        assert session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count() == baseline_events
        assert len(payload["history"]) == 7
    finally:
        session.close()
        engine.dispose()


def test_comparison_never_fabricates_improvement_and_apply_is_idempotent():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        resource = _resource(session, learner, "f6-t05-resource-apply-001")
        _, _, state, _ = create_session(
            session,
            owner=learner.public_id,
            source_resource_id=resource.id,
            idempotency_key="f6-t05-session-apply-001",
        )
        session.commit()
        payload = get_session(session, state.session_id, learner.public_id)
        payload = _action(session, learner, payload, "submit_round1", "f6-t05-apply-r1-001", ROUND2)
        payload = _action(session, learner, payload, "evaluate_round1", "f6-t05-apply-e1-001")
        payload = _action(session, learner, payload, "begin_question", "f6-t05-apply-bq-001")
        payload = _action(
            session, learner, payload, "answer_question", "f6-t05-apply-aq-001",
            "这个机制在什么条件下会失效，需要怎样检查来源版本？",
        )
        payload = _action(session, learner, payload, "submit_round2", "f6-t05-apply-r2-001", ROUND2)
        payload = _action(session, learner, payload, "evaluate_round2", "f6-t05-apply-e2-001")
        assert payload["comparison"]["score_delta"] == 0
        assert payload["comparison"]["conclusion"] == "unchanged"
        assert payload["comparison"]["improved_dimensions"] == []

        before = session.query(DBLearningEvent).filter_by(
            owner_public_id=learner.public_id, event_type="feynman_submitted",
        ).count()
        applied, created = apply_action(
            session,
            session_id=payload["session_id"],
            actor=learner,
            action="apply",
            text=None,
            expected_version=payload["version_number"],
            idempotency_key="f6-t05-apply-final-001",
        )
        session.commit()
        assert created is True
        assert applied["status"] == "applied"
        event = session.get(DBLearningEvent, applied["applied_event_id"])
        assert event.event_type == "feynman_submitted"
        assert event.evidence_status == "accepted"
        assert event.mastery_eligible is True
        assert event.completion_effect == "complete"
        assert event.payload["rubric_score"] == applied["round2_evaluation"]["normalized_score"]
        assert session.query(DBLearningEventConsumption).filter_by(learning_event_id=event.id).count() >= 1
        assert session.query(DBLearningEvent).filter_by(
            owner_public_id=learner.public_id, event_type="feynman_submitted",
        ).count() == before + 1

        replay, replay_created = apply_action(
            session,
            session_id=payload["session_id"],
            actor=learner,
            action="apply",
            text=None,
            expected_version=payload["version_number"],
            idempotency_key="f6-t05-apply-final-001",
        )
        assert replay_created is False
        assert replay["version_id"] == applied["version_id"]
        assert session.query(DBLearningEvent).filter_by(
            owner_public_id=learner.public_id, event_type="feynman_submitted",
        ).count() == before + 1
    finally:
        session.close()
        engine.dispose()


def test_dedicated_frontend_contract_replaces_chat_route():
    router = (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8")
    view_path = ROOT / "frontend/src/views/FeynmanWorkspace.vue"
    api_path = ROOT / "frontend/src/api/feynman.js"
    assert view_path.is_file()
    assert api_path.is_file()
    view = view_path.read_text(encoding="utf-8")
    assert "component: FeynmanWorkspace" in router
    assert "五阶段进度" in view
    assert "第一次复述" in view
    assert "提出真实疑问" in view
    assert "第二次复述" in view
    assert "理解变化" in view
    assert "应用到后续学习" in view
    assert "deterministic_local" not in view
    assert "context_fingerprint" not in view
    assert "source.quote" not in view
    assert "课程评价已准备" not in view
    assert "评价规则" not in view
    assert "上下文短哈希" not in view
    assert "Chat" not in router.split("name: 'FeynmanResource'", 1)[1].split("}", 1)[0]


def test_dynamic_context_changes_task_question_and_rubric_inputs_without_writing_evidence():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        first_resource = _resource(session, learner, "pr08-context-resource-a")
        base_profile = session.query(DBProfileSnapshot).filter_by(
            owner_public_id=learner.public_id,
        ).first()
        variant_profile = DBProfileSnapshot(
            id="pr08-profile-variant",
            owner_public_id=learner.public_id,
            profile_version="pr08.profile.v1",
            snapshot={"weak_topics": ["来源版本边界"], "goal": "核对失败恢复"},
            content_hash="pr08-profile-variant-hash",
            trace_id="pr08-profile-variant-trace",
        )
        session.add(variant_profile)
        session.commit()
        source = session.get(DBSourceRef, "demo-ref-07")
        job = create_generation_job(
            session,
            learner,
            course_id=COURSE_ID,
            knowledge_point_id="demo-kp-07",
            profile_snapshot_id=variant_profile.id,
            idempotency_key="pr08-context-resource-b",
            scope="single",
            items=[{
                "type": "feynman",
                "title": "混合检索费曼复述变体",
                "source_ref_ids": [source.id],
                "completion_rule": "完成两轮复述、真实追问、对比并应用学习结果",
            }],
            learning_goal="核对来源版本边界和失败恢复",
        )
        session.commit()
        second_resource = session.get(
            DBArtifact,
            execute_generation_job_demo(session, learner, job["job_id"])["items"][0]["resource"]["resource_id"],
        )
        session.commit()

        first = create_session(
            session, owner=learner.public_id, source_resource_id=first_resource.id,
            idempotency_key="pr08-context-session-a",
        )[2]
        second = create_session(
            session, owner=learner.public_id, source_resource_id=second_resource.id,
            idempotency_key="pr08-context-session-b",
        )[2]
        assert first.context_snapshot is not None
        assert second.context_snapshot is not None
        assert first.context_snapshot.context_fingerprint != second.context_snapshot.context_fingerprint
        assert first.task_prompt != second.task_prompt
        assert "来源版本边界" in second.adaptation_note

        first_payload = get_session(session, first.session_id, learner.public_id)
        second_payload = get_session(session, second.session_id, learner.public_id)
        for payload, key in ((first_payload, "pr08-a"), (second_payload, "pr08-b")):
            payload = _action(session, learner, payload, "submit_round1", f"{key}-r1", ROUND1)
            payload = _action(session, learner, payload, "evaluate_round1", f"{key}-e1")
            payload = _action(session, learner, payload, "begin_question", f"{key}-bq")
            payload = _action(
                session, learner, payload, "answer_question", f"{key}-aq",
                "为什么来源版本边界会影响混合检索的解释？",
            )
            assert payload["question_answer"]["context_fingerprint"] == payload["context_fingerprint"]
            assert payload["round1_evaluation"]["context_fingerprint"] == payload["context_fingerprint"]
            assert payload["generation_mode"] == "deterministic_local"
            if key == "pr08-a":
                first_payload = payload
            else:
                second_payload = payload
        assert first_payload["round1_evaluation"]["context_fingerprint"] != second_payload["round1_evaluation"]["context_fingerprint"]
        assert session.query(DBLearningEvent).filter_by(
            owner_public_id=learner.public_id, event_type="feynman_submitted",
        ).count() == 0
    finally:
        session.close()
        engine.dispose()
