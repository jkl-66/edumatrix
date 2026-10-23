from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELF = ROOT / "frontend" / "src" / "components" / "KnowledgeCourseShelf.vue"


def test_material_recommendation_section_is_separate_and_actionable() -> None:
    source = SHELF.read_text(encoding="utf-8")
    assert "material_recommendations" in source
    assert "教材补充推荐" in source
    assert 'data-testid="material-recommendations"' in source
    assert 'data-testid="material-recommendations-empty"' in source
    assert "辅助材料 / 待审核" in source
    assert "查看预览" in source
    assert "打开教材" in source
    assert "getKnowledgeDocument" in source
    assert "materialPreviewScope" in source
    assert "owner_id" in source
    assert "materialRecommendations.value.length" in source
    assert "emit('open-source'" in source


def test_material_preview_does_not_claim_main_course_authority() -> None:
    source = SHELF.read_text(encoding="utf-8")
    assert "不属于主课程证据" in source
    assert "不会改变课程检索或学习进度" in source
