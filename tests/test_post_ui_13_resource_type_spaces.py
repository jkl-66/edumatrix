from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_CENTER = ROOT / "frontend/src/views/ResourceCenter.vue"
TYPE_STAGE = ROOT / "frontend/src/components/ResourceTypeStage.vue"
ROUTER = ROOT / "frontend/src/router/index.js"

RESOURCE_TYPES = (
    "handout",
    "mind_map",
    "quiz",
    "training_task",
    "code_sandbox",
    "video",
    "deck",
    "interactive_model",
    "feynman",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_nine_resource_types_have_distinct_workspace_surfaces() -> None:
    center = read(RESOURCE_CENTER)
    stage = read(TYPE_STAGE)

    assert "import ResourceTypeStage" in center
    assert '<ResourceTypeStage' in center
    assert 'v-if="activeTypeDefinition"' in center
    assert ':data-resource-space="definition.id"' in stage

    for resource_type in RESOURCE_TYPES:
        assert f"definition.id === '{resource_type}'" in stage or resource_type == "feynman"
        assert f"id: '{resource_type}'" in center

    distinct_markers = (
        "handout-outline",
        "mindmap-board",
        "quiz-sheet",
        "task-document",
        "code-editor",
        "video-player",
        "deck-slide",
        "model-controls",
        "feynman-flow",
    )
    assert all(marker in stage for marker in distinct_markers)


def test_type_space_keeps_unified_catalog_and_existing_detail_actions() -> None:
    center = read(RESOURCE_CENTER)

    for marker in (
        'data-resource-type="all"',
        'class="catalog-toolbar"',
        'class="resource-results"',
        '<ResourcePreviewDrawer',
        '<ResourceHistoryDrawer',
        '<ResourceEditorDialog',
        '@open="openResource"',
        '@download="downloadResource"',
        '@history="openHistory"',
        '@edit="openEditor"',
    ):
        assert marker in center

    assert 'class="type-history-empty"' in center
    assert '使用上方“自定义生成”选择课程知识点' in center


def test_custom_generation_uses_real_outline_point_sources_and_profile_snapshot() -> None:
    center = read(RESOURCE_CENTER)

    for marker in (
        "getCanonicalCourseOutline",
        "getM5TodayWork",
        "flattenOutlineKnowledgePoints",
        "chapter.source_ref_id",
        "generationKnowledgePointId",
        "generationGoal",
        "generationTypeLocked",
        'knowledge_point_id: point.id',
        'source_ref_ids: point.source_ref_ids',
        "profile_snapshot_id",
        "createM5ResourceGenerationJob",
        '@generate="openTypeGeneration"',
        '@generate="openPreviewGeneration"',
        '@click="openGenericGeneration"',
    ):
        assert marker in center

    request_start = center.index("generationJob.value = await createM5ResourceGenerationJob({")
    request_end = center.index("})", request_start)
    request = center[request_start:request_end]
    assert "knowledge_point_id: point.id" in request
    assert "learning_goal: learningGoal" in request
    assert "source_ref_ids: point.source_ref_ids" in request


def test_custom_generation_keeps_native_map_for_outline_deduplication() -> None:
    center = read(RESOURCE_CENTER)

    assert "Map as MapIcon" in center
    assert "icon: MapIcon" in center
    assert "const points = new Map()" in center


def test_generation_form_exposes_type_point_goal_and_truthful_block_states() -> None:
    center = read(RESOURCE_CENTER)

    for label in ("资源类型", "课程知识点", "学习重点"):
        assert f"<span>{label}</span>" in center
    for message in (
        "请先选择一门课程",
        "当前课程还没有可用知识点",
        "当前账号还没有可用画像快照",
        "该知识点尚未绑定可用章节来源",
    ):
        assert message in center

    assert ':disabled="!generationCanStart || generationLoading"' in center
    assert "不会产生学习证据或改变掌握度" in center


def test_existing_nine_dedicated_workspace_routes_remain_registered() -> None:
    router = read(ROUTER)
    expected_components = (
        "HandoutWorkspace",
        "MindmapWorkspace",
        "QuizResourceWorkspace",
        "TrainingTaskWorkspace",
        "CodeSandboxWorkspace",
        "VideoRecommendationWorkspace",
        "WebDeckWorkspace",
        "InteractiveLabWorkspace",
        "FeynmanWorkspace",
    )
    assert all(component in router for component in expected_components)

    workspace_paths = re.findall(r"path:\s*'([^']+)'", router)
    assert any("handout" in path for path in workspace_paths)
    assert any("mind" in path for path in workspace_paths)
    assert "/workspace/code/:resourceId" in workspace_paths
    assert "/workspace/feynman/:resourceId" in workspace_paths
