from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_learning_path_removes_legacy_analysis_history_entry_but_keeps_personalized_draft():
    source = _source("frontend/src/views/LearningPathGraph.vue")

    assert "路径分析与历史" not in source
    assert "showAdvancedPathAnalysis" not in source
    assert "showAll" not in source
    assert "goAnalysis" not in source
    assert "/student-analysis" not in source
    assert 'data-testid="legacy-path-analysis-removed"' not in source
    assert 'data-testid="textbook-path-draft"' in source
    assert "generateTextbookDraft" in source
    assert "confirmTextbookDraft" in source
    assert "textbookGeneration.status === 'failed'" in source


def test_legacy_path_links_migrate_and_history_route_remains_read_only_entry():
    migration = json.loads(_source("frontend/src/router/routeMigrationContract.json"))
    by_path = {item["sourcePath"]: item for item in migration}
    assert by_path["/learning-path"]["destination"] == "/workspace/path"
    assert by_path["/student-analysis"]["destination"] == "/profile/learning"
    assert by_path["/learning-path"]["notice"] == "legacy-route"
    assert by_path["/student-analysis"]["notice"] == "legacy-route"

    router = _source("frontend/src/router/index.js")
    assert "path: '/profile/history'" in router
    assert "compatibilityRedirect" in router
    assert "legacy_path" in router

    shell = _source("frontend/src/components/AppShell.vue")
    assert "路径分析与历史" not in shell
