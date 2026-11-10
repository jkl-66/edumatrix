from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_context_band_can_delegate_its_primary_action_to_the_page():
    source = (ROOT / "frontend/src/components/CompetitionDemoContextBand.vue").read_text(encoding="utf-8")

    assert "defineEmits(['primary-action'])" in source
    assert "emit('primary-action', route)" in source
    assert "primaryActionLabel || contract.primary_action.label" in source
