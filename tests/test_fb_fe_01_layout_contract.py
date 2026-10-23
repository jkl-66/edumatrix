from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_shared_shell_uses_compact_icon_over_label_navigation():
    source = read("frontend/src/components/AppShell.vue")

    assert "--nav-width: 104px" in source
    assert ".app-nav :deep(.sidebar-item)" in source
    assert "flex-direction: column" in source
    assert "min-height: 68px" in source
    assert ".app-nav :deep(.sidebar-item__label)" in source
    assert "white-space: normal" in source
    assert ".app-content__layout--workspace" in source
    assert "grid-template-columns: 136px minmax(0, 1fr)" in source


def test_target_surfaces_rebalance_primary_and_secondary_columns():
    workspace = read("frontend/src/views/LearningWorkspace.vue")
    resources = read("frontend/src/views/ResourceCenter.vue")
    notes = read("frontend/src/views/Notes.vue")
    wrong = read("frontend/src/views/WrongQuestionBook.vue")

    assert "grid-template-columns: minmax(190px, 20%) minmax(0, 1fr) minmax(210px, 21%)" in workspace
    assert "grid-template-columns: minmax(0, 1fr) 236px" in workspace
    assert "grid-template-columns: 176px minmax(420px, 1fr) 248px" in resources
    assert "grid-template-columns: 190px minmax(420px, 1fr) 238px" in notes
    assert "grid-template-columns: 286px minmax(0, 1fr)" in wrong


def test_layout_contract_does_not_hide_core_navigation_or_use_horizontal_page_overflow():
    shell = read("frontend/src/components/AppShell.vue")
    fb_block = shell.split("/* FB-FE-01", 1)[1]

    assert "display: none" not in fb_block
    assert "overflow-x: hidden" not in fb_block
    assert "overflow-x:hidden" not in fb_block
