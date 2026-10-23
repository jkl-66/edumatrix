from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_feedback_completion_panel_is_hidden_but_recovery_states_remain() -> None:
    component = read("frontend/src/components/AggregationStatus.vue")

    assert "feedback.value && feedback.value.status !== 'processed'" in component
    assert "loading.value" in component
    assert "error.value" in component
    assert "props.showEmpty && !feedback.value" in component
    assert "replayM5LearningEvent(eventId)" in component
    assert "正在核对学习结果" in component
    assert "学习结果处理中" in component
    assert "部分学习结果待恢复" in component
    assert "学习反馈暂时无法读取" in component


def test_profile_migration_and_internal_versions_are_not_projected_to_ui() -> None:
    panel = read("frontend/src/components/ProfileSummaryPanel.vue")
    dashboard = read("frontend/src/views/ProfileDashboard.vue")
    home = read("frontend/src/views/Dashboard.vue")

    for source in (panel, dashboard, home):
        assert "旧画像已接入当前画像" not in source
        assert "查看旧画像迁移与影响证据" not in source
        assert "legacy-profile-map.v1" not in source
        assert "f8.learning-feedback.v2" not in source
        assert "legacy-migration" not in source
    assert "最近画像摘要" in dashboard
    assert "画像快照：" in home
    assert "profile_alignment?.legacy_migration?.mapping_version" not in home


def test_all_feedback_consumers_keep_shared_component_for_non_completed_states() -> None:
    consumers = (
        "frontend/src/views/Dashboard.vue",
        "frontend/src/views/StudentAnalysis.vue",
        "frontend/src/views/LearningPathGraph.vue",
        "frontend/src/views/WrongQuestionBook.vue",
        "frontend/src/views/Review.vue",
        "frontend/src/views/History.vue",
        "frontend/src/views/FormalExamWorkspace.vue",
    )
    for relative in consumers:
        view = read(relative)
        assert "AggregationStatus" in view
        assert "<AggregationStatus" in view


def test_no_exact_learning_feedback_synced_copy_in_frontend_views() -> None:
    forbidden = ("学习反馈已同步", "学习闭环已同步", "反馈同步未完成")
    for path in (ROOT / "frontend" / "src").rglob("*"):
        if path.suffix not in {".vue", ".js", ".ts", ".jsx", ".tsx"}:
            continue
        content = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in content, f"{phrase} remains in {path}"
