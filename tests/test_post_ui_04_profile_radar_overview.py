from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "frontend" / "src" / "views" / "StudentAnalysis.vue"
RADAR = ROOT / "frontend" / "src" / "components" / "MasteryRadar.vue"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_profile_radar_has_a_compact_scrollable_mastery_overview() -> None:
    source = _source(PROFILE)

    for marker in (
        'class="profile-radar-layout"',
        'class="profile-radar-chart"',
        'class="profile-radar-overview" aria-label="知识点掌握度一览"',
        'class="profile-radar-list" role="list"',
        'v-for="concept in conceptMastery"',
        'concept.name',
        'formatMasteryPercent(concept.mastery)',
        'function masteryOverviewTone(score)',
        'function formatMasteryPercent(score)',
        'max-height: 236px',
        'overflow-y: auto',
        '.profile-radar-concept-name',
        'text-overflow: ellipsis',
    ):
        assert marker in source

    assert 'class="profile-radar-empty">暂无数据</div>' in source
    assert '<MasteryRadar :concepts="conceptMastery" :student-id="studentId" />' in source


def test_radar_interaction_contract_remains_owned_by_mastery_radar() -> None:
    profile = _source(PROFILE)
    radar = _source(RADAR)

    assert "import MasteryRadar from '../components/MasteryRadar.vue'" in profile
    assert "axisName: {" in radar
    assert "show: false" in radar
    assert "triggerOn: 'none'" in radar
    assert "handleRadarMouseOver" in radar
    assert "handleRadarGlobalOut" in radar
    assert "profile-radar-list" not in radar
