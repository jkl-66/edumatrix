from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "frontend" / "src" / "views" / "LearningWorkspace.vue"
APP = ROOT / "frontend" / "src" / "App.vue"


def test_workspace_shell_has_three_semantic_regions_and_overview_api():
    source = WORKSPACE.read_text(encoding="utf-8")

    assert "getM5WorkspaceOverview" in source
    assert 'aria-label="课程与任务"' in source
    assert 'aria-label="当前学习对象"' in source
    assert 'aria-label="AI 学习伙伴"' in source
    assert 'class="workspace-grid"' in source
    assert "grid-template-columns: minmax(210px, 24%) minmax(0, 1fr) minmax(230px, 25%)" in source


def test_workspace_shell_uses_mobile_tabs_instead_of_compressed_columns():
    source = WORKSPACE.read_text(encoding="utf-8")

    assert 'class="mobile-workspace-tabs"' in source
    assert "mobilePanel === 'course'" in source
    assert "mobilePanel === 'learning'" in source
    assert "mobilePanel === 'partner'" in source
    assert "@media (max-width: 900px)" in source
    assert ".workspace-grid { min-height: 590px; grid-template-columns: minmax(0, 1fr); }" in source
    assert ".mobile-hidden { display: none; }" in source


def test_workspace_keeps_existing_plan_actions_and_user_facing_title():
    workspace = WORKSPACE.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")

    for action in (
        "saveDraft",
        "confirmPlan",
        "transitionPath",
        "recordNodeEvent",
    ):
        assert action in workspace
    assert "'/workspace': '学习空间'" in app
    assert "'/workspace': '计划工作台'" not in app
