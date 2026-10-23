#!/usr/bin/env python3
"""Finalize F5-T07's per-atom evidence after focused tests and desktop E2E."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ROOT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
LEDGER_DIR = CONTEXT_ROOT / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
REPORT = "outputs/原系统融合重构执行/evidence/f5_t07_resource_history/report.json"
FOCUSED_TESTS = "tests/test_f5_t07_resource_history.py"
REGRESSION_TESTS = (
    "tests/test_f5_t03_handout_workspace.py, "
    "tests/test_f5_t04_mindmap_workspace.py, "
    "tests/test_f5_t05_training_task_workspace.py, "
    "tests/test_f5_t06_video_deck_workspace.py"
)
E2E = "scripts/e2e_f5_t07_resource_history.py"
E2E_REPORT = f"{REPORT} result=passed; screenshots=7; learning_state_unchanged=true; database_audit=ok"
DETECTOR = "Impeccable detector: [] for ResourceCenter, ResourceEditorDialog, ResourceHistoryDrawer, ResourceToolbar and five resource workspaces."


COMMON_FILES = [
    "frontend/src/views/ResourceCenter.vue",
    "frontend/src/components/ResourcePreviewDrawer.vue",
    "frontend/src/components/ResourceHistoryDrawer.vue",
    "frontend/src/components/ResourceEditorDialog.vue",
    "frontend/src/components/ResourceToolbar.vue",
    "frontend/src/api/m5.js",
    "app/m5_resources.py",
    "app/m5_api.py",
]
WORKSPACE_FILES = [
    "frontend/src/views/HandoutWorkspace.vue",
    "frontend/src/views/MindmapWorkspace.vue",
    "frontend/src/views/TrainingTaskWorkspace.vue",
    "frontend/src/views/VideoRecommendationWorkspace.vue",
    "frontend/src/views/WebDeckWorkspace.vue",
]


def primary(implementation: list[str], verification: list[str], visible: str) -> dict[str, object]:
    return {
        "status": "IMPLEMENTED_AND_VERIFIED",
        "implementation_evidence": implementation,
        "verification_evidence": verification,
        "user_visible_result": visible,
        "compatibility_or_defer_rationale": "本任务只统一资源版本、来源、编辑、比较、恢复、完成和生成入口；测验判分、代码运行、交互实验和费曼证据仍由各自任务负责。",
    }


def related(rationale: str, implementation: list[str], verification: list[str]) -> dict[str, object]:
    return {
        "status": "COORDINATION_VERIFIED",
        "implementation_evidence": implementation,
        "verification_evidence": verification,
        "user_visible_result": "相关能力保持在原责任模块中，并通过本任务的统一资源入口、版本事实或回归证据继续可用。",
        "compatibility_or_defer_rationale": rationale,
    }


REALIZATION = {
    "G05-R04": primary(
        [
            *COMMON_FILES,
            "ResourceCenter owns selection, preview, history, compare, restore, editor and deep-link actions.",
        ],
        [
            f"{FOCUSED_TESTS}::test_history_projection_is_descending_read_only_and_source_aware",
            f"{FOCUSED_TESTS}::test_historical_edit_and_restore_create_new_versions_without_mutating_old_versions",
            f"{E2E_REPORT}; 1440x900 and 1366x768 history/editor screenshots are recorded.",
            DETECTOR,
        ],
        "学生可在资源中心按类型找到资源、查看右侧预览、打开专用页面、查看版本历史并回到同一资源继续学习。",
    ),
    "G08-R04": primary(
        [
            "frontend/src/views/ResourceCenter.vue:openEditor and saveEditorVersion read the selected current version and submit a structured draft.",
            "frontend/src/components/ResourceEditorDialog.vue provides the editor, format/line context, validation notice and save action.",
            "app/m5_resources.py:create_resource_version validates the content format and source version before writing.",
        ],
        [
            f"{FOCUSED_TESTS}::test_historical_edit_and_restore_create_new_versions_without_mutating_old_versions",
            f"{E2E}: editor dialog accepted a valid structured JSON revision and report.editor_save.created_new_version=true.",
            "34 focused F5-T03 through F5-T07 tests passed.",
        ],
        "学生点击‘编辑另存’，会看到当前版本内容和结构校验说明，可以在原内容基础上修改后保存。",
    ),
    "G08-R05": primary(
        [
            "app/m5_resources.py:create_resource_version writes a new ArtifactVersion and leaves the source version immutable.",
            "frontend/src/components/ResourceEditorDialog.vue explicitly states that saving creates a new current version.",
            "frontend/src/components/ResourceHistoryDrawer.vue keeps old versions read-only and source-aware.",
        ],
        [
            f"{FOCUSED_TESTS}::test_historical_edit_and_restore_create_new_versions_without_mutating_old_versions",
            f"{E2E_REPORT}; database audit records four structured versions with distinct hashes where content changed.",
            "frontend npm run build passed after 6218 modules transformed.",
        ],
        "保存后系统显示新版本已保存，旧版本、来源引用和历史内容仍可查看，不能被覆盖。",
    ),
    "G08-R06": primary(
        [
            "frontend/src/components/ResourceHistoryDrawer.vue renders read-only version rows with compare and restore actions.",
            "frontend/src/views/ResourceCenter.vue:compareHistory calls the shared version comparison endpoint.",
            "app/m5_resources.py:compare_resource_versions returns a source-preserving diff projection.",
        ],
        [
            f"{FOCUSED_TESTS}::test_history_projection_is_descending_read_only_and_source_aware",
            f"{FOCUSED_TESTS}::test_historical_edit_and_restore_create_new_versions_without_mutating_old_versions",
            f"{E2E}: screenshot 02-history-compare-1440x900.png shows the comparison result.",
        ],
        "学生在版本历史中点击‘比较’，可以看到历史版本与当前版本的差异；旧版本仍然只读。",
    ),
    "G08-R07": primary(
        [
            "frontend/src/views/ResourceCenter.vue preserves generationJob, item-level failure, retry and recovery states while adding version actions.",
            "app/resource_bundles.py remains the shared nine-resource generation and recovery owner; ResourceCenter only projects its state.",
            "frontend/src/components/ResourceHistoryDrawer.vue exposes restoring/comparing progress and an honest error region.",
        ],
        [
            "tests/test_f5_t02_resource_bundle_workspace.py and its report cover queued, partial success, item failure, retry and recovery states.",
            "outputs/原系统融合重构执行/evidence/f5_t01_resource_center/report.json covers preview failure and retry without clearing the catalog.",
            f"{E2E}: history/editor failure boundaries are protected by server validation; valid retry path completes with no unexpected HTTP errors.",
        ],
        "资源生成或版本操作失败时，界面保留已成功内容并显示可重试入口，不会把整批资源清空。",
    ),
    "G21-R10": primary(
        [
            *WORKSPACE_FILES,
            "frontend/src/components/ResourceToolbar.vue and ResourceHistoryDrawer.vue provide the same history affordance across five resource workspaces.",
            "app/m5_resources.py keeps resource-specific parsers while sharing ArtifactVersion history and restore facts.",
        ],
        [
            f"{REGRESSION_TESTS} passed and cover handout, mind map, training task, video and deck workspaces.",
            "outputs/原系统融合重构执行/evidence/f5_t03_handout/report.json, f5_t04_mindmap/report.json, f5_t05_training_task/report.json and f5_t06_video_deck/report.json record dual-desktop workspace evidence.",
            f"{E2E_REPORT}; generic resource-center history is independently exercised.",
            DETECTOR,
        ],
        "每种资源都在自己的专用页面保留版本历史，并可通过统一入口回到资源中心或继续生成同类资源。",
    ),
    "G22-R10": primary(
        [
            "frontend/src/views/ResourceCenter.vue and the five resource workspaces all consume the shared current_version_id/history projection.",
            "frontend/src/api/m5.js centralizes create-version, compare, restore, complete and generation calls.",
            "app/m5_api.py and app/m5_resources.py enforce owner, course, lock-version and immutable-history boundaries.",
        ],
        [
            f"{FOCUSED_TESTS} passed: 5 tests cover history projection, compare, edit, restore failure and owner isolation.",
            f"{E2E_REPORT}; refresh restores the same resource identity and version drawer at 1366x768.",
            "F4 path/exam regression contracts remain green; ordinary resource browsing does not write learning state.",
        ],
        "从资源生成到打开、编辑、比较、恢复和再次学习，学生看到的是同一个有来源、有版本的资源对象。",
    ),
    "G05-R01": related(
        "资源分类继续由 F5-T01 资源中心负责；F5-T07 只增加统一版本与编辑工具，不另建资源目录。",
        ["frontend/src/views/ResourceCenter.vue:type-rail renders all nine resource type filters."],
        ["outputs/原系统融合重构执行/evidence/f5_t01_resource_center/report.json records the nine-type catalog and category screenshots."],
    ),
    "G05-R02": related(
        "搜索、模块、标签和知识点筛选仍由 F5-T01 资源中心负责，版本操作沿用筛选后的 selected resource。",
        ["frontend/src/views/ResourceCenter.vue uses the debounced query and artifact filters before selecting a resource."],
        ["F5-T01 desktop E2E report records search, empty state, clear filters and list/grid restoration."],
    ),
    "G05-R03": related(
        "预览由 ResourcePreviewDrawer 负责；版本历史从预览动作进入而不是改变资源目录布局。",
        ["frontend/src/components/ResourcePreviewDrawer.vue renders course, knowledge point, version, source and completion preview facts."],
        ["F5-T01 screenshots and report cover selected-resource preview and preview failure recovery."],
    ),
    "G05-R05": related(
        "已批准边界排除竞品多浮窗桌面；F5-T07 使用同一页面右侧预览和 Teleport 抽屉，不增加漂浮应用层。",
        ["frontend/src/views/ResourceCenter.vue composes ResourcePreviewDrawer and ResourceHistoryDrawer as one resource-center flow."],
        [DETECTOR, f"{E2E}: resource center and history screenshots show no multi-window floating layout."],
    ),
    "G05-R06": related(
        "条目元数据由资源目录/预览投影；版本编辑不复制另一份元数据事实。",
        ["frontend/src/components/ResourcePreviewDrawer.vue displays course, knowledge point, status, completion, version, source count and update time."],
        [f"{E2E_REPORT}; screenshot 01-resource-center-current-1440x900.png records the metadata and preview."],
    ),
    "G05-R07": related(
        "预览采用右侧详情栏，历史采用右侧抽屉；不复制图5的多窗口交互。",
        ["frontend/src/components/ResourcePreviewDrawer.vue and ResourceHistoryDrawer.vue implement the approved nearby-preview boundary."],
        [f"{E2E_REPORT}; screenshot 02-history-compare-1440x900.png validates the drawer state."],
    ),
    "G08-R01": related(
        "资源自动归档与九类生成由 F5-T01/F5-T02 负责，F5-T07 保留同一 Artifact/ArtifactVersion 事实源。",
        ["app/resource_bundles.py and app/m5_resources.py remain the generation and resource projection owners."],
        ["F5-T02 resource-bundle report covers nine resource entries and archive/recovery states."],
    ),
    "G08-R02": related(
        "类型筛选和关键词搜索仍使用 F5-T01 的 ResourceCenter 查询，不被版本抽屉分叉。",
        ["frontend/src/views/ResourceCenter.vue keeps query, artifactType, status, sourceStatus and archive filters as the catalog state."],
        ["F5-T01 report records category, search, list/grid and empty-state checks."],
    ),
    "G08-R03": related(
        "程序类产物继续拥有独立 artifact_type 和专用路由；统一工具栏不把它们合并成普通文本。",
        ["frontend/src/api/m5.js and app/m5_resources.py preserve code_sandbox, training_task and interactive_model identities."],
        [f"{REGRESSION_TESTS} passed with dedicated training-task, mind-map and media routes."],
    ),
    "G21-R01": related(
        "学习空间一级入口和资源子路由由 F4/F5-T01 保护；本任务只统一资源版本操作。",
        ["frontend/src/router/index.js retains resource-scoped routes and the five workspace components remain siblings under the resource space."],
        [f"{REGRESSION_TESTS} passed; each workspace report records its route and desktop evidence."],
    ),
    "G21-R02": related(
        "专用学习页面由 F5-T03 至 F5-T06 负责，F5-T07 将统一历史投影接入这些页面。",
        [*WORKSPACE_FILES, "frontend/src/components/ResourceToolbar.vue"],
        [f"{REGRESSION_TESTS} passed and the four workspace reports record refresh/deep-link behavior."],
    ),
    "G21-R03": related(
        "课程、知识点、来源和版本上下文继续来自共享资源详情，专用页面只消费对应结构化内容。",
        ["app/m5_resources.py projects course, knowledge point, source and version facts; ResourceToolbar renders type/title/version/status."],
        [f"{REGRESSION_TESTS} passed; desktop reports show shared context headers."],
    ),
    "G21-R04": related(
        "资源到智能对话的深链仍由各专用工作区维护；统一版本历史不改变 context-bearing query 参数。",
        ["frontend/src/views/HandoutWorkspace.vue, MindmapWorkspace.vue, TrainingTaskWorkspace.vue, VideoRecommendationWorkspace.vue and WebDeckWorkspace.vue preserve source/question deep links."],
        ["F5-T03 through F5-T06 reports record source and question/deep-link checks where applicable."],
    ),
    "G21-R05": related(
        "测评中心仍只由入学诊断和智能组卷承担；资源版本入口不新增正式测评动作。",
        ["frontend/src/views/ResourceCenter.vue and the five workspaces expose history/edit/complete/resource actions, not assessment-center actions."],
        ["tests/test_f4_exam_gate.py and tests/test_f4_path_contract.py remain the protected assessment/path contracts; 34 F5 tests passed."],
    ),
    "G21-R06": related(
        "总路径、科目路径和每日任务由 F4 负责；F5-T07 不改变预算、节奏或任务编排，只保留资源返回上下文。",
        ["ResourceCenter deep links preserve course_id and resource identity; no path mutation is called by history/editor actions."],
        ["tests/test_f4_path_contract.py and F5-T07 learning-state digest confirm path state is unchanged by resource browsing/editing."],
    ),
    "G21-R07": related(
        "复习日历和复习首页不属于 F5-T07；资源历史动作不创建复习证据。",
        ["frontend/src/views/ResourceCenter.vue only calls resource detail/version endpoints for this flow."],
        ["F4 review/path protected contracts remain green; F5-T07 report learning_events/profile/path digests are unchanged."],
    ),
    "G21-R08": related(
        "从复习知识点生成资源仍由既有资源包/单项生成入口负责；F5-T07 保留生成同类资源按钮和任务状态投影。",
        ["frontend/src/views/ResourceCenter.vue keeps openGeneration and generationJob retry/recovery actions beside history/edit."],
        ["F5-T02 resource-bundle report covers complete generation/recovery; F5-T07 regression preserves the entry."],
    ),
    "G21-R09": related(
        "复习完成与画像反馈由 F4/F6 的证据协议负责；F5-T07 的版本浏览、比较和编辑不伪装成掌握证据。",
        ["frontend/src/components/ResourcePreviewDrawer.vue labels completion separately; history/editor endpoints write ArtifactVersion only."],
        [f"{E2E_REPORT}; learning_state_before equals learning_state_after and database audit is valid."],
    ),
    "G21-R11": related(
        "测评中心不增加第三入口，资源中的即时练习仍是 quiz artifact；F5-T07 不把历史/编辑动作放入测评中心。",
        ["app/m5_resources.py keeps quiz resource type separate; ResourceCenter and workspaces do not import formal assessment actions."],
        ["tests/test_f4_exam_gate.py plus the focused F5 regression suites pass with the assessment boundary intact."],
    ),
    "G21-R12": related(
        "实训任务书、代码沙盒、可交互模型、视频和课件仍是不同资源类型与路由；统一版本组件只提供共享历史协议。",
        ["app/m5_resources.py:RESOURCE_CATALOG_TYPES and frontend/src/router/index.js preserve distinct artifact types and workspace routes."],
        [f"{REGRESSION_TESTS} passed; training-task, video and deck reports confirm separate pages and actions."],
    ),
    "G21-R13": related(
        "资源全部归档与智能组卷门禁属于 F4/F5-T01/T02；F5-T07 编辑、比较、恢复和普通浏览不能解锁组卷。",
        ["frontend/src/views/ResourceCenter.vue does not call path completion or exam-unlock APIs from history/editor actions."],
        [f"{E2E_REPORT}; learning events, profile snapshots and path-node digests remain unchanged after all F5-T07 actions."],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F5-T07_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F5-T07 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in REALIZATION]
    extra = [atom_id for atom_id in REALIZATION if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic realization mismatch: missing={missing}, extra={extra}")

    for entry in ledger["entries"]:
        entry["realization"] = REALIZATION[entry["atomic_requirement_id"]]

    batch = {
        "id": "F5-T07-B04",
        "status": "VERIFIED",
        "direct_atoms": ["G05-R04", "G08-R04", "G08-R05", "G08-R06", "G08-R07", "G21-R10", "G22-R10"],
        "related_atoms": [atom_id for atom_id in actual_ids if atom_id not in {"G05-R04", "G08-R04", "G08-R05", "G08-R06", "G08-R07", "G21-R10", "G22-R10"}],
        "files": [*COMMON_FILES, *WORKSPACE_FILES, E2E],
        "interfaces": [
            "GET /api/v1/m5/resources/{artifact_id}",
            "GET /api/v1/m5/resources/{artifact_id}/compare",
            "POST /api/v1/m5/resources/{artifact_id}/versions",
            "POST /api/v1/m5/resources/{artifact_id}/restore",
        ],
        "states": ["history_compare", "historical_read_only", "history_restore", "edit_source", "save_as_new_version", "refresh_recovery", "validation_failure"],
        "verification": [f"{FOCUSED_TESTS}: 5 passed", f"{E2E_REPORT}", "npm run build: passed", "Impeccable detector: []"],
        "protection_contracts": [
            "old versions remain immutable",
            "structured content validation remains server-owned",
            "resource actions do not change learning evidence, profile or path state",
            "specialized workspaces retain their own content schemas and exports",
        ],
    }
    batches = ledger.setdefault("execution_batches", [])
    existing = next((item for item in batches if item.get("id") == batch["id"]), None)
    if existing is None:
        batches.append(batch)
    else:
        existing.update(batch)
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    sys.path.insert(0, str(ROOT / "scripts"))
    from context_recovery_atomic_gate import expected_entries, load_task_payload, validate_ledger_identity, validate_realization

    active = json.loads((CONTEXT_ROOT / "active_manifest.json").read_text(encoding="utf-8"))
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F5-T07")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T07",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F5-T07 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F5-T07 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
