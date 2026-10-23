from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBLearningEvent, DBProfileSnapshot, DBStudentProfile, DBUser, SessionLocal
from app.main import app
from models import StudentProfile


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_feedback_completion_copy_no_longer_claims_sync() -> None:
    component = read("frontend/src/components/AggregationStatus.vue")
    dashboard_summary = read("app/dashboard_summary.py")
    exam = read("frontend/src/views/FormalExamWorkspace.vue")
    assert "学习反馈已同步" not in component
    assert "本次学习已记录" in component
    assert "学习结果已更新到相关页面" in component
    assert "同步完成后更新" not in dashboard_summary
    assert "完成当前学习动作后即可查看最新结果" in dashboard_summary
    assert "学习闭环已同步" not in exam
    assert "反馈同步未完成" not in exam
    assert "学习闭环已记录" in exam
    assert "反馈仍在处理" in exam


def test_dimension_display_has_chinese_labels_for_all_continuous_keys() -> None:
    view = read("frontend/src/views/StudentAnalysis.vue")
    for key in (
        "knowledge_mastery",
        "misconception_profile",
        "understanding_fluency_transfer",
        "cognitive_processing",
        "learning_strategy",
        "metacognition",
        "motivation_and_purpose",
        "affect_resilience",
        "interaction_preference",
        "learning_context",
    ):
        assert key in view
    for label in ("知识基础与掌握度", "易错点与概念理解", "学习环境和安排"):
        assert label in view


def test_knowledge_shelf_uses_requested_discovery_button_copy() -> None:
    component = read("frontend/src/components/KnowledgeCourseShelf.vue")
    assert 'data-testid="enter-knowledge-discovery"' in component
    assert "进入联网发现" in component


def test_agent_timeline_translates_public_owners_and_event_labels() -> None:
    component = read("frontend/src/components/AgentTimeline.vue")
    for label in ("对话编排智能体", "上下文构建智能体", "反驳检查智能体", "证据核验智能体"):
        assert label in component
    assert "协作 Agent" not in component
    assert "Resource Planner" in component
    assert "资源规划智能体" in component
    for label in ("阶段开始", "阶段完成", "结论已核验", "处理完成"):
        assert label in component
    assert "<dt>反驳检查</dt>" in component
    assert "<dt>证据核验</dt>" in component


def test_onboarding_echoes_answer_before_model_response() -> None:
    view = read("frontend/src/views/Onboarding.vue")
    assert "status: 'analyzing'" in view
    assert "正在分析你的回答" in view
    assert "submission_failed" in view
    assert "turns: [...(session.value?.turns || []), optimisticTurn]" in view


def test_profile_summary_and_analysis_end_loading_without_a_course() -> None:
    panel = read("frontend/src/components/ProfileSummaryPanel.vue")
    view = read("frontend/src/views/StudentAnalysis.vue")
    assert "if (!props.courseId)" in panel
    assert "loading.value = false" in panel
    assert "请选择课程后查看对应的知识掌握图谱" in view
    assert "v-else-if=\"courseGraphLoading || !courseGraph\"" in view


def test_profile_analysis_projects_the_canonical_course_graph() -> None:
    view = read("frontend/src/views/StudentAnalysis.vue")
    api = read("frontend/src/api/knowledge.js")
    assert "getCourseKnowledgeGraph" in view
    assert "courseGraph.value = await getCourseKnowledgeGraph(courseId)" in view
    assert "node.nodeType === 'knowledge_point'" in view
    assert "relationType === 'prerequisite'" in view
    assert "f7.course-knowledge-graph.profile-projection.v1" in view
    assert "/knowledge/courses/${encodeURIComponent(courseId)}/graph" in api


def test_profile_graph_nodes_without_history_have_a_safe_next_action() -> None:
    view = read("frontend/src/views/StudentAnalysis.vue")

    assert "nextAction: legacy?.nextAction || {" in view
    assert "查看课程资料" in view
    assert "当前节点暂无已记录的下一步动作" in view
    assert "knowledge_point_id=${encodeURIComponent(id)}" in view


def test_new_registration_has_no_machine_learning_or_peer_mastery_seed() -> None:
    username = f"new-opinion-{uuid4().hex[:12]}"
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": "EduMatrix123!", "display_name": "新账号"},
        )
        assert response.status_code == 200, response.text
    with SessionLocal() as session:
        profile = session.query(DBStudentProfile).filter_by(student_id=username).one()
        assert profile.target_course == ""
        assert profile.knowledge_base == ""
        assert profile.cognitive_style == ""
        assert profile.motivation_type == "未诊断"
        assert profile.concept_mastery == {}
        assert profile.bkt_states == {}
        user = session.query(DBUser).filter_by(username=username).one()
        assert session.query(DBProfileSnapshot).filter_by(owner_public_id=user.public_id).count() == 0
        assert session.query(DBLearningEvent).filter_by(owner_public_id=user.public_id).count() == 0


def test_delayed_profile_creation_keeps_initial_fields_empty() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        profile = DBStudentProfile(student_id="delayed-new-opinion")
        session.add(profile)
        session.commit()
        session.refresh(profile)
        assert profile.target_course == ""
        assert profile.knowledge_base == ""
        assert profile.cognitive_style == ""
    engine.dispose()


def test_empty_profile_analysis_waits_for_evidence_without_machine_learning_seed() -> None:
    from profile_api import _empty_profile_analysis, _profile_has_meaningful_evidence

    profile = StudentProfile(student_id="empty-analysis")
    assert _profile_has_meaningful_evidence(profile) is False
    payload = _empty_profile_analysis(profile, "新账号")

    assert payload["profile_initialization_state"] == "awaiting_learning_evidence"
    assert payload["kalman_concept"] is None
    assert payload["kalman_history"] == []
    assert payload["mental_state_history"] == []
    assert payload["causes"] == {}
    assert payload["weak_analysis"] == []
    assert "机器学习" not in str(payload)
    assert "池化层" not in str(payload)
    assert all(item["score"] is None and item["level"] == "pending" for item in payload["dimensions"].values())

    profile.customized_fields = ["major"]
    assert _profile_has_meaningful_evidence(profile) is True


def test_empty_profile_api_paths_do_not_restore_legacy_machine_learning_defaults() -> None:
    api = read("profile_api.py")
    onboarding = read("frontend/src/views/Onboarding.vue")
    view = read("frontend/src/views/StudentAnalysis.vue")

    assert '"target_course": getattr(profile, "target_course", "机器学习导论")' not in api
    assert 'target_course: session.value?.courseContext?.title || \'机器学习导论\'' not in onboarding
    assert "awaiting_learning_evidence" in api
    assert "等待有效学习证据，暂不评分" in view
    assert "profileAwaitingEvidence ? '待评估'" in view


def test_new_onboarding_context_does_not_invent_a_course_id() -> None:
    source = read("app/profile_onboarding.py")
    assert '"courseId": "legacy-default-course"' not in source
    assert '"source": "尚未选择课程"' in source


def test_course_context_is_inherited_by_chat_and_learning_workspace() -> None:
    chat = read("frontend/src/views/Chat.vue")
    workspace = read("frontend/src/views/LearningWorkspace.vue")
    dashboard = read("frontend/src/views/Dashboard.vue")
    assert "courseContext.contextRef?.courseId" in chat
    assert "getM5TodayWork(requestedCourseId)" in workspace
    assert "localStorage.getItem('edumatrix_course_id')" not in dashboard.split("const currentCourseId", 1)[1].split("const activeLearningTarget", 1)[0]


def test_profile_update_exposes_waiting_completion_failure_and_retry_states() -> None:
    view = read("frontend/src/views/StudentAnalysis.vue")
    for marker in (
        "const profileUpdateStatus = ref('idle')",
        "正在打开画像更新会话…",
        "正在分析你的回答…",
        "正在保存已确认的画像变化…",
        "画像更新已完成，最新版本已经载入",
        "画像更新暂时失败，可以重试",
        "function retryProfileUpdate()",
        "重试画像更新",
        "profileUpdateBusy || !profileUpdateAnswer.trim()",
        'aria-live="polite"',
    ):
        assert marker in view


def test_profile_update_shows_multi_turn_history_and_ten_dimension_preview() -> None:
    view = read("frontend/src/views/StudentAnalysis.vue")
    for marker in (
        "continuous-update-workspace",
        "aria-label=\"十维画像更新预览\"",
        "profileUpdateDimensionPreview",
        "continuousDimensionLabels[item.key]",
        "依据：{{ item.evidence }}",
        "置信度：{{ Math.round(Number(item.confidence) * 100) }}%",
        "v-for=\"turn in profileUpdate.turns\"",
        "function profileUpdateTurnStatus(status)",
        "模型整理失败，可重试或手动确认",
        "confirmProfileUpdateTurn(turn.turnId",
    ):
        assert marker in view


def test_student_assessment_routes_do_not_invent_a_course_without_context() -> None:
    assessment = read("frontend/src/views/AssessmentWorkspace.vue")
    exam = read("frontend/src/views/FormalExamWorkspace.vue")
    store = read("frontend/src/stores/courseContext.js")
    profile = read("frontend/src/views/ProfileDashboard.vue")

    assert "route.query.course_id || courseContext.contextRef?.courseId || ''" in assessment
    assert "if (!courseId.value)" in assessment
    assert 'data-testid="assessment-course-required"' in assessment
    assert "route.query.course_id" in exam
    assert "courseContext.contextRef?.courseId" in exam
    assert "studentNeedsCourse" in exam
    assert 'data-testid="exam-course-required"' in exam
    assert "contextRef.value.courseId ? '当前课程' : '选择当前课程'" in store
    assert "localStorage.getItem('edumatrix_course_title')" not in store
    assert "courseContext.contextRef?.courseId" in profile
    assert "localStorage.getItem('edumatrix_course_id')" not in profile


def test_history_inherits_canonical_course_context_without_legacy_storage_read() -> None:
    history = read("frontend/src/views/History.vue")

    assert "useCourseContextStore" in history
    assert "route.query.course_id || courseContext.contextRef?.courseId || ''" in history
    assert "localStorage.getItem('edumatrix_course_id')" not in history


def test_profile_regions_have_request_race_protection_and_retry_states() -> None:
    panel = read("frontend/src/components/ProfileSummaryPanel.vue")
    view = read("frontend/src/views/StudentAnalysis.vue")

    for marker in (
        "let requestSequence = 0",
        "requestId !== requestSequence",
        "requestedCourseId !== String(props.courseId || '')",
        'class="summary-retry"',
        '重试</button>',
    ):
        assert marker in panel
    for marker in (
        "let courseGraphRequestSequence = 0",
        "requestId !== courseGraphRequestSequence",
        "requestedCourseId !== profileCourseId.value",
        "function retryCourseGraph()",
        'class="profile-map-retry"',
        ':class="{ error: courseGraphError }"',
    ):
        assert marker in view
