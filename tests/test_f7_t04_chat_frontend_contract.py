from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "frontend" / "src" / "views" / "Chat.vue"
QUIZ_WORKSPACE = ROOT / "frontend" / "src" / "views" / "QuizResourceWorkspace.vue"
INLINE_QUIZ = ROOT / "frontend" / "src" / "components" / "InlineQuizCard.vue"
STORE = ROOT / "frontend" / "src" / "stores" / "chat.js"
RENDERER = ROOT / "frontend" / "src" / "components" / "IncrementalMarkdownRenderer.vue"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chat_is_one_focused_conversation_surface() -> None:
    chat = source(CHAT)

    for marker in (
        'data-testid="focused-chat-workspace"',
        'data-testid="chat-conversation-rail"',
        'data-testid="chat-answer-workspace"',
        'data-testid="chat-evidence-rail"',
        'data-testid="chat-composer"',
    ):
        assert marker in chat
    for removed in (
        "SandboxConsole",
        "SandboxVisualizer",
        "runCode",
        "webSearch",
        "searchResults",
        "codeInput",
        "activeTab",
        "edumatrix_chat_messages",
        "edumatrix_sandbox_mount_code",
    ):
        assert removed not in chat


def test_legacy_workbenches_redirect_to_formal_modules() -> None:
    chat = source(CHAT)

    assert "'/knowledge/discover'" in chat
    assert "`/workspace/code/${encodeURIComponent(resourceId)}`" in chat
    assert "`/workspace/resources/quizzes/${encodeURIComponent(resourceId)}`" in chat
    assert "quiz_follow_up" in chat
    assert "quiz_resource_id" in chat
    assert "question_version_id" in chat
    assert "attempt_id" in chat
    assert "route.query.prompt" in chat


def test_canonical_attachment_states_and_recovery_actions_are_visible() -> None:
    chat = source(CHAT)

    for state in (
        "等待解析",
        "正在解析",
        "可发送",
        "部分解析失败",
        "失败可重试",
        "已移除",
    ):
        assert state in chat
    for action in (
        "uploadAttachment",
        "retryAttachment",
        "confirmPartialAttachment",
        "removeAttachment",
        "attachmentBlockReason",
        "retryPendingMessage",
    ):
        assert action in chat
    assert 'accept=".ppt,.pdf,.pptx,.docx,.md,.txt,.png,.jpg,.jpeg,.webp"' in chat


def test_answer_first_stream_and_explicit_resource_contract() -> None:
    chat = source(CHAT)
    store = source(STORE)

    for action in ("stopActiveResponse", "continueResponse"):
        assert action in chat
        assert action in store
    assert "startResourceFromMessage" in chat
    assert "createResourceFromMessage" in store
    assert "resourceOptions" in chat
    assert "个性化讲义" in chat
    assert "思维导图" in chat
    assert "测验题资源" in chat
    assert 'data-testid="chat-compact-resource-links"' in chat
    assert "message.resourceLinks" in chat
    assert "full_resource_content" not in chat


def test_quiz_context_delegates_answering_to_the_f6_resource_workspace() -> None:
    chat = source(CHAT)
    quiz_workspace = source(QUIZ_WORKSPACE)
    inline_quiz = source(INLINE_QUIZ)

    for required in (
        'data-testid="chat-quiz-context"',
        "getM5Resource",
        "quizQuestion",
        "quizSourceRefs",
        "openQuizSource",
        "openQuizResource",
        "进入测验题资源作答",
        "作答、判分、解析和历史记录使用正式题目版本",
        "quiz_follow_up",
        "question_version_id",
        "attempt_id",
        "import InlineQuizCard",
        "<InlineQuizCard",
        '@submitted="handleQuizSubmitted"',
        '@follow-up="handleQuizFollowUp"',
    ):
        assert required in chat
    # Chat may host the canonical card for the single-question journey, but it
    # must not create a second server-side attempt/history writer.
    for forbidden in (
        "submitM5AssessmentAttempt",
        "record_attempt",
        "DBAssessmentAttempt",
    ):
        assert forbidden not in chat
    assert "import InlineQuizCard" in quiz_workspace
    assert '<InlineQuizCard' in quiz_workspace
    assert '@submitted="handleSubmitted"' in quiz_workspace
    assert '@follow-up="openFollowUp"' in quiz_workspace
    assert "submitM5AssessmentAttempt" in inline_quiz
    for forbidden in ("correctAnswer", "correct_answer", "accuracy/recall"):
        assert forbidden not in chat


def test_context_source_and_return_evidence_are_present_without_private_process() -> None:
    chat = source(CHAT)

    for marker in (
        'data-testid="chat-processing-state"',
        'data-testid="chat-context-refs"',
        'data-testid="chat-source-list"',
        "streamCheckpoint",
        "sourceRefs",
        "returnTo",
    ):
        assert marker in chat
    for forbidden in (
        "chain_of_thought",
        "reasoning_content",
        "system_prompt",
        "raw_log",
        "api_key",
        "完整思维链",
    ):
        assert forbidden not in chat


def test_frozen_desktop_visual_contract_and_minimum_text_size() -> None:
    chat = source(CHAT).lower()

    for token in ("#f5f7f7", "#ffffff", "#06141b", "#11212d"):
        assert token in chat
    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
        "#10b981",
        "#0ea5e9",
        "#8b5cf6",
        "font-size: 10px",
        "font-size: 11px",
        "font-size: 12px",
        "font-size: 13px",
    ):
        assert forbidden not in chat
    assert "grid-template-columns: 228px minmax(520px, 1fr) 292px" in chat
    assert "var(--font-sans)" in chat
    assert "var(--font-heading)" in chat


def test_streaming_renderer_uses_semantic_minimal_styles() -> None:
    renderer = source(RENDERER).lower()

    for marker in (
        "inc-paragraph",
        "code-block-wrapper",
        "inc-mermaid-loading",
        "skeleton-block",
    ):
        assert marker in renderer
    for forbidden in (
        "text-[10px]",
        "text-[11px]",
        "text-xs",
        "rounded-xl",
        "indigo",
        "linear-gradient",
        "font-size: 10px",
        "font-size: 11px",
        "font-size: 12px",
        "font-size: 13px",
    ):
        assert forbidden not in renderer
