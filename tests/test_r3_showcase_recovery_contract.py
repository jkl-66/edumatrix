from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_showcase_keeps_reset_available_for_degraded_context():
    source = (ROOT / "frontend/src/views/CompetitionShowcase.vue").read_text(encoding="utf-8")

    assert "hasDemoData.value&&!data.value.initialized" in source
    assert ":disabled=\"resetting||initializing||!hasDemoData\"" in source
    assert "if(repairRequired.value){await resetCompetitionDemo()" in source
    assert "恢复冻结初始状态" in source


def test_context_band_can_delegate_its_primary_action_to_the_page():
    source = (ROOT / "frontend/src/components/CompetitionDemoContextBand.vue").read_text(encoding="utf-8")

    assert "defineEmits(['primary-action'])" in source
    assert "emit('primary-action', route)" in source
    assert "primaryActionLabel || contract.primary_action.label" in source
