from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "frontend" / "src" / "views" / "StudentAnalysis.vue"


def _source() -> str:
    return PROFILE.read_text(encoding="utf-8")


def _suggestions_section(source: str) -> str:
    start = source.index("<!-- Tab: Suggestions -->")
    end = source.index("<!-- Edit Profile Modal -->", start)
    return source[start:end]


def test_suggestions_tab_only_keeps_the_personalized_summary() -> None:
    source = _source()
    section = _suggestions_section(source)

    assert "class=\"profile-suggestions-panel\"" in section
    assert "id=\"profile-suggestions-title\"" in section
    assert "v-for=\"(s, i) in suggestions\"" in section
    assert "suggestions.length" in section
    assert "暂无个性化建议" in section

    for removed in (
        "综合各维度分析生成的个性化教学建议",
        "一键生成个性化资源",
        "针对性讲解",
        "生成练习题",
        "复习计划",
        "生成笔记",
        "开始学习",
        "学习路径",
        "错题本",
    ):
        assert removed not in section


def test_suggestions_summary_has_a_large_neutral_visual_contract() -> None:
    source = _source()

    for marker in (
        ".profile-suggestions-panel",
        ".profile-suggestions-header",
        "font-size: 24px",
        ".profile-suggestions-list",
        "font-size: 16px",
        ".profile-suggestion-index",
        ".profile-suggestions-empty",
    ):
        assert marker in source

    # The digital-twin tab was removed by acceptance feedback FB-21; the other
    # detail tabs remain part of the learning-profile surface.
    assert "activeTab === 'digital-twin'" not in source
    for tab in ("overview", "dimensions", "weakness", "causes"):
        assert f"activeTab === '{tab}'" in source
