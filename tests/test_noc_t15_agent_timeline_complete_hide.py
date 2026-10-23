from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TIMELINE = ROOT / "frontend" / "src" / "components" / "AgentTimeline.vue"
CHAT = ROOT / "frontend" / "src" / "views" / "Chat.vue"


def test_chat_timeline_hides_completed_items_without_changing_audit_facts() -> None:
    timeline = TIMELINE.read_text(encoding="utf-8")
    chat = CHAT.read_text(encoding="utf-8")

    assert "hideCompleted: { type: Boolean, default: false }" in timeline
    assert "const allItems = eventItems.length" in timeline
    assert "const currentEventItems = latestEventItems(eventItems)" in timeline
    assert "props.hideCompleted ? visibleEventItems : eventItems" in timeline
    assert "allItems.filter((item) => item.status !== 'completed')" in timeline
    assert "stageCount: stageKeys.size || allItems.length" in timeline
    assert "resourceProgress" in timeline
    assert chat.count("hide-completed") == 2


def test_chat_timeline_reconciles_each_logical_step_before_hiding_completed_events() -> None:
    timeline = TIMELINE.read_text(encoding="utf-8")

    assert "function eventStepKey(item)" in timeline
    assert "function latestEventItems(items)" in timeline
    assert "if (item.eventType.startsWith('run.')) return 'run'" in timeline
    assert "if (item.resourceType) return `resource:${item.resourceType}`" in timeline
    assert "stageId.startsWith('resource:')" in timeline
    assert "item.eventType === 'run.failed' && hasResourceFailure" in timeline
    assert "const key = item.resourceType || item.resourceItemId" in timeline


def test_completed_filter_keeps_other_statuses_and_other_surfaces_default() -> None:
    timeline = TIMELINE.read_text(encoding="utf-8")
    for status in ("pending", "queued", "running", "failed", "stopped"):
        assert f"{status}" in timeline
    floating = (ROOT / "frontend" / "src" / "components" / "ResourceFloatingQa.vue").read_text(encoding="utf-8")
    reader = (ROOT / "frontend" / "src" / "views" / "KnowledgeDocumentReader.vue").read_text(encoding="utf-8")
    assert "hide-completed" not in floating
    assert "hide-completed" not in reader
