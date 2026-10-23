from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "frontend" / "src" / "views" / "Chat.vue"


def test_send_button_does_not_forward_dom_event_as_intent_override() -> None:
    source = CHAT.read_text(encoding="utf-8")

    # sendMessage(intentOverride) accepts an optional string.  A bare Vue
    # handler reference forwards the click MouseEvent, which serializes into an
    # invalid `intent` payload and makes the canonical API reject the message.
    assert '@click="sendMessage()"' in source
    assert '@click="sendMessage"' not in source


def test_enter_and_click_share_the_same_explicit_send_path() -> None:
    source = CHAT.read_text(encoding="utf-8")
    assert 'void sendMessage()' in source
    assert '@click="sendMessage()"' in source
    assert 'const intent = intentOverride || (resourceTypes.length ? \'resource_generation\' : \'chat\')' in source
