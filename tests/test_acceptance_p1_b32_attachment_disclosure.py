from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "frontend" / "src" / "views" / "Chat.vue"
STORE = ROOT / "frontend" / "src" / "stores" / "chat.js"
CHAT_API = ROOT / "frontend" / "src" / "api" / "chat.js"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_attachment_queue_exposes_accessible_disclosure_without_replacing_rows() -> None:
    chat = source(CHAT)

    for marker in (
        'data-testid="chat-attachment-queue"',
        'data-testid="chat-attachment-toggle"',
        'aria-expanded="String(!attachmentsCollapsed)"',
        'aria-controls="chat-attachment-list"',
        'v-show="!attachmentsCollapsed"',
        'id="chat-attachment-list"',
        "attachmentQueueSummary",
        "attachmentsCollapsed = !attachmentsCollapsed",
        "向下隐藏附件",
        "向上展开附件",
    ):
        assert marker in chat

    for state_or_action in (
        "queued",
        "parsing",
        "ready",
        "partial_failed",
        "failed_retryable",
        "retryAttachment",
        "confirmPartialAttachment",
        "removeAttachment",
        "selectedAttachmentIds",
    ):
        assert state_or_action in chat


def test_disclosure_is_presentation_only_and_existing_attachment_contract_remains() -> None:
    chat = source(CHAT)
    store = source(STORE)
    api = source(CHAT_API)

    # The collapse state is local UI state; no store action or attachment API
    # is called by the toggle itself.
    toggle_start = chat.index('data-testid="chat-attachment-toggle"')
    toggle_end = chat.index('</button>', toggle_start)
    toggle_block = chat[toggle_start:toggle_end]
    for forbidden in ("uploadAttachment", "parseChatAttachment", "removeChatAttachment", "sendMessage"):
        assert forbidden not in toggle_block

    for marker in (
        "uploadAttachment",
        "retryAttachment",
        "confirmPartialAttachment",
        "removeAttachment",
        "attachmentBlockReason",
        "attachmentIds",
        "context_refs",
    ):
        assert marker in store or marker in api or marker in chat

    assert "attachmentsCollapsed" not in store
    assert "attachmentsCollapsed" not in api


def test_attachment_queue_keeps_long_list_scroll_and_readable_spacing() -> None:
    chat = source(CHAT)

    assert ".attachment-queue__list" in chat
    assert "max-height: 190px" in chat
    assert "overflow-y: auto" in chat
    assert "gap: 12px" in chat
    assert "padding: 7px 10px 7px 12px" in chat
    for forbidden in ("font-size: 10px", "font-size: 11px", "font-size: 12px", "font-size: 13px"):
        assert forbidden not in chat
