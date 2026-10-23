from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_initial_profile_accepts_and_projects_motivation() -> None:
    source = read("app/profile_onboarding.py")
    assert '"goal": {"learning_goals", "motivation_type", "goal_context"}' in source
    assert 'profile.motivation_type = str(fields["motivation_type"]).strip()' in source
    assert '"motivation_type": profile.motivation_type if profile else ""' in source


def test_dashboard_uses_canonical_profile_values_without_imported_status() -> None:
    view = read("frontend/src/views/Dashboard.vue")
    assert "function profileInsight(field)" in view
    assert "value.trim().toLowerCase() !== 'imported'" in view
    assert "profileInsight('cognitive_style')" in view
    assert "profileInsight('motivation_type')" in view


def test_discovery_failure_keeps_original_query_and_nested_error_text() -> None:
    view = read("frontend/src/views/KnowledgeDiscoveryWorkspace.vue")
    assert "searchQueryUsed.value = normalized" in view
    assert "action-label=\"使用原搜索词重试\"" in view
    assert "errorMessageText(" in view
    assert "provider_failed" in view


def test_profile_graph_has_course_selector_and_race_safe_refresh() -> None:
    view = read("frontend/src/views/StudentAnalysis.vue")
    assert "listKnowledgeCourseShelf" in view
    assert 'id="profile-graph-course"' in view
    assert "changeGraphCourse" in view
    assert "course_id: selectedGraphCourseId.value || undefined" in view
    assert "requestedCourseId !== profileCourseId.value" in view


def test_chat_course_picker_shows_pending_selection_without_changing_committed_context() -> None:
    view = read("frontend/src/views/Chat.vue")
    store = read("frontend/src/stores/chat.js")
    assert "const displayCourseIds = computed(() => (coursePickerOpen.value ? pendingCourseIds.value : selectedCourseIds.value))" in view
    assert "const displayCourses = computed(() => displayCourseIds.value" in view
    assert "const effectiveCourseIds = computed(() => selectedCourseIds.value.length" in view
    assert "await chatStore.createConversation" in view
    assert "chatStore.setSelectedCourseIds(next)" in view
    assert "courses: selectedCourses" in store
    assert "courseId: next[0] || null" in store


def test_reader_exposes_original_pdf_without_replacing_indexed_content() -> None:
    view = read("frontend/src/views/KnowledgeDocumentReader.vue")
    assert "getDocumentReaderExport" in view
    assert "const isPdfDocument = computed" in view
    assert "data-testid=\"original-pdf-preview\"" in view
    assert "解析页图与来源定位" in view
    assert "application/pdf" in view


def test_agent_timeline_translates_stage_and_resource_keys() -> None:
    component = read("frontend/src/components/AgentTimeline.vue")
    for label in ("问题理解", "课程检索", "学科专家起草", "答案综合", "个性化讲义", "代码沙盒"):
        assert label in component
    assert "resourceTypeLabels[resourceType]" in component
    assert "stageLabels[stageId]" in component
    assert "function statusLabel(status)" in component


def test_chat_errors_are_serialized_and_failed_send_remains_visible() -> None:
    common = read("frontend/src/api/common.js")
    store = read("frontend/src/stores/chat.js")
    stream = read("frontend/src/api/stream.js")
    assert "export function errorMessageText" in common
    assert "super(errorMessageText(detail" in common
    assert "const optimisticId = `optimistic-${request.idempotency_key}`" in store
    assert "failureMessage = errorMessageText(data.message" in store
    assert "response.text().then" in stream


def test_chat_message_failure_copy_never_renders_raw_object() -> None:
    view = read("frontend/src/views/Chat.vue")
    store = read("frontend/src/stores/chat.js")
    assert "message.failure?.message" in view
    assert "errorMessageText(" in store
    assert "[object Object]" not in view


def test_chat_stream_cleans_controller_after_all_terminal_error_paths() -> None:
    stream = read("frontend/src/api/stream.js")
    assert "function clearActiveController()" in stream
    assert "_activeStreamControllers.get(studentId) === controller" in stream
    assert "clearActiveController()\n          onError?.(error)" in stream
    assert "clearActiveController()\n          onError?.(new Error(`请求失败（HTTP ${response.status}）`))" in stream
    assert "clearActiveController()\n      onError?.(error)" in stream
