from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_profile_page_exposes_natural_language_continuous_update_contract():
    source = (ROOT / "frontend/src/views/StudentAnalysis.vue").read_text(encoding="utf-8")
    for marker in (
        'data-testid="profile-continuous-update"',
        "更新学情画像",
        "保留你的原话",
        "确认并更新画像",
        "submitProfileUpdateTurn",
        "confirmProfileUpdateTurn",
        "profileFieldLabels",
        "profileFieldLabel(key)",
    ):
        assert marker in source
    assert "font-size: 14px" in source


def test_today_learning_places_deduplicated_profile_reminder_above_tasks():
    source = (ROOT / "frontend/src/views/LearningWorkspace.vue").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api/onboarding.js").read_text(encoding="utf-8")
    for marker in (
        'data-testid="today-profile-update-reminder"',
        "现在更新",
        "稍后提醒",
        "getProfileUpdateReminder",
        "dismissProfileUpdateReminder",
    ):
        assert marker in source or marker in api
    assert "profileReminder?.due" in source


def test_profile_update_and_reminder_copy_uses_human_readable_labels_and_accessible_size():
    profile = (ROOT / "frontend/src/views/StudentAnalysis.vue").read_text(encoding="utf-8")
    workspace = (ROOT / "frontend/src/views/LearningWorkspace.vue").read_text(encoding="utf-8")
    assert "{{ profileFieldLabel(key) }}" in profile
    assert ".continuous-update-flow span" in profile and "font-size: 14px" in profile
    assert ".today-profile-reminder__body small" in workspace and "font-size: 14px" in workspace
    assert ".today-profile-reminder__actions button" in workspace and "font: 600 14px" in workspace
