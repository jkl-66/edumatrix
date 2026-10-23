from pathlib import Path


CHAT = Path(__file__).parents[1] / "frontend" / "src" / "views" / "Chat.vue"


def test_composer_resource_picker_exposes_all_nine_types_and_selection_controls():
    source = CHAT.read_text(encoding="utf-8")
    for resource_type in (
        "handout",
        "mind_map",
        "quiz",
        "training_task",
        "code_sandbox",
        "video",
        "deck",
        "interactive_model",
        "feynman",
    ):
        assert f"type: '{resource_type}'" in source
    assert "resourcePickerOpen" in source
    assert "selectedResourceTypes" in source
    assert "selectAllResourceTypes" in source
    assert "clearResourceTypes" in source
    assert "role=\"dialog\" aria-label=\"选择生成资源类型\"" in source
    assert "composerPlaceholder" in source


def test_composer_send_uses_canonical_resource_message_protocol():
    source = CHAT.read_text(encoding="utf-8")
    assert "const intent = intentOverride || (resourceTypes.length ? 'resource_generation' : 'chat')" in source
    assert "intent === 'general_qa' ? [] : outgoingContextRefs.value" in source
    assert "resourceTypes," in source


def test_completed_message_resource_action_returns_to_composer_instead_of_legacy_endpoint():
    source = CHAT.read_text(encoding="utf-8")
    assert "在输入框生成资源" in source
    assert "startResourceFromMessage" in source
    assert "createResourceFromMessage" not in source
    assert "resource-menu" not in source
    assert "规划、协作、审核和发布过程" in source
    assert "data-testid=\"chat-composer-context\"" in source


def test_course_picker_and_level_d_general_answer_action_are_exposed():
    source = CHAT.read_text(encoding="utf-8")
    assert "courseSearch" in source
    assert "最近课程" in source
    assert "filteredCourseOptions" in source
    assert "chat-general-knowledge-action" in source
    assert "用通用知识继续回答" in source
    assert "workflowEventCount(message)" in source
    assert "messageAgentAudit(message)" in source
