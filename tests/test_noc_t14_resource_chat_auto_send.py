from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "frontend" / "src" / "views" / "Chat.vue"


def _source() -> str:
    return CHAT.read_text(encoding="utf-8")


def test_resource_route_submission_clears_the_prefilled_composer() -> None:
    source = _source()
    start = source.index("async function sendRouteResourceMessage()")
    end = source.index("watch(", start)
    block = source[start:end]

    assert "await chatStore.sendMessage" in block
    assert "draft.value = ''" in block
    assert "selectedResourceTypes.value = []" in block
    assert "resourcePickerOpen.value = false" in block
    assert "routeResourceMessageStarted.value = true" in block


def test_resource_route_waits_for_an_existing_stream_then_retries_once() -> None:
    source = _source()
    assert "if (chatStore.sending) return" in source
    watcher_start = source.index("// A resource route can open while")
    watcher = source[watcher_start:source.index("</script>")]
    assert "() => chatStore.sending" in watcher
    assert "wasSending && !sending" in watcher
    assert "!routeResourceMessageStarted.value" in watcher
    assert "void sendRouteResourceMessage()" in watcher


def test_resource_route_keeps_context_and_idempotency_payload() -> None:
    source = _source()
    start = source.index("async function sendRouteResourceMessage()")
    end = source.index("watch(", start)
    block = source[start:end]
    for marker in (
        "contextRefs: resourceMessageContextRefs.value",
        "intent: resourceIntent.value",
        "resourceTypes: effectiveResourceTypes.value",
        "contextSnapshotId:",
        "idempotencyKey",
    ):
        assert marker in block
