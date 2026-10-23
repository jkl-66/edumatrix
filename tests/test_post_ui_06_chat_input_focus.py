from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "frontend" / "src" / "views" / "Chat.vue"


def _source() -> str:
    return CHAT.read_text(encoding="utf-8")


def test_chat_composer_uses_one_focus_owner() -> None:
    source = _source()

    generic_focus = source.index("textarea:focus-visible")
    composer_focus = source.index(".composer-input:focus,")
    assert composer_focus > generic_focus

    focus_block = source[composer_focus:source.index(".spin", composer_focus)]
    assert "outline: 0" in focus_block
    assert "outline-offset: 0" in focus_block
    assert ".composer-box:focus-within" in source


def test_chat_composer_behavior_and_accessible_global_focus_remain() -> None:
    source = _source()

    for marker in (
        'class="composer-box"',
        'v-model="draft"',
        '@keydown="onComposerKeydown"',
        'class="send-button"',
        'class="icon-button" title="添加附件"',
        "button:focus-visible",
        "textarea:focus-visible",
    ):
        assert marker in source
