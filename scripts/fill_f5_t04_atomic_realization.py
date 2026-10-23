#!/usr/bin/env python3
"""Populate and validate F5-T04's per-atom realization evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ROOT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
LEDGER_DIR = (
    CONTEXT_ROOT
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
)
REPORT = "outputs/原系统融合重构执行/evidence/f5_t04_mindmap/report.json"
FOCUSED_TESTS = "tests/test_f5_t04_mindmap_workspace.py"


def related(
    rationale: str,
    verification_evidence: list[str],
    *,
    status: str = "COMPATIBILITY_VERIFIED",
    implementation_evidence: list[str] | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "implementation_evidence": implementation_evidence or [],
        "verification_evidence": verification_evidence,
        "user_visible_result": "",
        "compatibility_or_defer_rationale": rationale,
    }


REALIZATION = {
    "G03-R01": related(
        "思维导图继续是九类资源中的独立mind_map产物；可交互模型和PPT/网页课件仍有各自类型、归档状态和路由，导图没有吞并或替代它们。",
        [
            "app/resource_bundles.py keeps mind_map, interactive_model and deck as separate entries in GENERATION_RESOURCE_TYPES and separate GENERATION_ROUTES.",
            f"{FOCUSED_TESTS}::test_deterministic_demo_generates_complete_structured_mindmap verifies the mind-map item inside the complete nine-resource generation contract.",
        ],
        implementation_evidence=[
            "app/resource_bundles.py: deterministic mind_map generation emits f5.mindmap.v1 while sibling resource generators remain separate.",
        ],
    ),
    "G03-R02": related(
        "导图内容从统一资源生成清单中的课程、知识点、画像摘要、学习目标和来源快照生成；节点掌握提示只读，不会根据浏览行为重新计算画像。",
        [
            "app/resource_bundles.py:_deterministic_resource_content builds the mind map from the frozen public generation context and source snapshots.",
            f"{REPORT}: structured E2E opens the course-scoped resource, preserves the same source deep link, and records identical profile/path/event hashes before and after browsing.",
        ],
        status="COORDINATION_VERIFIED",
        implementation_evidence=[
            "app/m5_resources.py: MindmapContent projects sourceRefIds, linkedResourceIds and read-only masteryBand values from the persisted resource version.",
        ],
    ),
    "G03-R03": related(
        "F5-T04没有重做或降级已关闭的高质量讲义；导图只复用相同浅色极简视觉令牌，并通过真实关联资源深链进入原讲义工作区。",
        [
            "The combined F5-T03/F5-T04 regression passes 17 tests, including all nine handout tests.",
            f"{REPORT}: linked_handout_url resolves to the existing HandoutWorkspace and the 1366x768 primary-action check navigates there successfully.",
        ],
        implementation_evidence=[
            "frontend/src/views/MindmapWorkspace.vue opens linked handouts through their existing resource route instead of embedding or rewriting handout content.",
        ],
    ),
    "G03-R04": related(
        "导图仅在学生从资源中心、资源包或稳定深链显式进入后加载；页面打开、节点选择、搜索、缩放和折叠都不会自动生成新资源或弹出生成流程。",
        [
            f"{FOCUSED_TESTS}::test_frontend_contract_uses_dedicated_workspace_and_no_evidence_write_calls verifies the dedicated read workspace contains no generation or learning-evidence mutation call.",
            f"{REPORT}: all browser flows begin from an explicit mind-map URL, unexpected_write_requests is empty and the persisted resource count/hash is unchanged.",
        ],
    ),
    "G03-R05": related(
        "资源中心仍是导图的目录和归档所有者；专用页面读取同一artifact/version对象并提供返回资源中心动作，没有新增平行导图库或第二套搜索索引。",
        [
            "frontend/src/router/index.js maps /workspace/resources/mindmaps/:resourceId to MindmapWorkspace while ResourceCenter remains the catalog route.",
            f"{FOCUSED_TESTS}::test_structured_mindmap_projects_sources_and_safe_resource_links verifies the workspace projection comes from the shared artifact and current version.",
        ],
        implementation_evidence=[
            "frontend/src/views/MindmapWorkspace.vue loads getM5ResourceDetail(resourceId) and returns to WorkspaceResources with the same course context.",
        ],
    ),
    "G03-R06": related(
        "F5-T04只完善九类资源包中mind_map成功项的内容和专用视图；其他八类的任务步骤、状态、重试和归档身份保持F5-T02协议不变。",
        [
            "tests/test_f5_t02_resource_bundle_workspace.py passes in the 16-test protection regression.",
            f"{FOCUSED_TESTS}::test_deterministic_demo_generates_complete_structured_mindmap verifies one structured mind-map item without changing the nine-type set.",
        ],
    ),
    "G03-R07": related(
        "导图节点仅引用并打开完整讲义，节点摘要不替代讲义的目录、概念、图表、例反例、代码、小测、来源、版本和导出合同。",
        [
            "The F5-T03 focused suite remains green in the 17-test combined regression.",
            f"{REPORT}: linked_handout_url and right_panel_primary_action.navigated_to_linked_resource prove the node opens the complete persisted handout workspace.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G03-R08": related(
        "完整导图、来源和版本继续保存在统一artifact/version对象；节点提问只携带当前资源、版本、节点和来源上下文进入智能对话，不复制完整导图到消息。",
        [
            "app/m5_resources.py returns mindmap.current and mindmap.versions from persisted DBArtifactVersion records with canonical source projections.",
            f"{FOCUSED_TESTS}::test_mindmap_versions_remain_read_only_in_workspace_projection verifies version projections are read-only; {REPORT} records two stable version hashes.",
        ],
        status="COORDINATION_VERIFIED",
        implementation_evidence=[
            "frontend/src/views/MindmapWorkspace.vue:askAboutNode routes compact resource/version/node/source context to Chat and leaves the full artifact in the resource workspace.",
        ],
    ),
    "G10-R01": related(
        "资源导图按单份资源的根节点、知识簇和层级组织内容；它借鉴分组表达但使用独立资源路由、标题和语义，不冒充学习画像知识图谱。",
        [
            f"{FOCUSED_TESTS}::test_mindmap_schema_requires_one_connected_acyclic_tree verifies one rooted connected hierarchy with explicit depth and parent relations.",
            "The 16-test F2/F4/F5 protection regression passes, preserving profile and path contracts while adding the resource route.",
        ],
        implementation_evidence=[
            "app/m5_resources.py: MindmapNode/MindmapContent define a resource-scoped hierarchy; frontend/src/router/index.js assigns a dedicated MindmapResource route.",
        ],
    ),
    "G10-R02": related(
        "父子关系由稳定parentId和relation字段表达；重复ID、多根、缺失父节点、深度错误、断连和环均被严格拒绝，并诚实降级到有限层级列表。",
        [
            f"{FOCUSED_TESTS}::test_mindmap_schema_requires_one_connected_acyclic_tree covers duplicate IDs, multiple roots, invalid parents, depth mismatch, disconnected nodes and cycles.",
            f"{REPORT}: 04-legacy-hierarchy and 05-invalid-hierarchy render without browser errors, overflow or infinite traversal.",
        ],
        implementation_evidence=[
            "app/m5_resources.py: MindmapContent.valid_connected_tree enforces tree integrity and _mindmap_projection supplies an honest hierarchy fallback.",
        ],
    ),
    "G10-R03": related(
        "节点掌握区间仅作为只读阅读提示，支持unknown状态；它不提供编辑控件，也不从导图交互产生新的掌握值。",
        [
            f"{FOCUSED_TESTS}::test_structured_mindmap_projects_sources_and_safe_resource_links verifies masteryBand projection including unknown-compatible values.",
            f"{REPORT}: profile_snapshots and learning_events hashes are identical before and after all node, search, zoom, fold and navigation actions.",
        ],
        implementation_evidence=[
            "frontend/src/views/MindmapWorkspace.vue renders masteryLabel(selectedNode.masteryBand) as a fact row with no mutation action.",
        ],
    ),
    "G10-R04": related(
        "选择节点会在右侧显示关系、摘要、层级、只读掌握提示、来源、关联资源和下一步动作，而不是只改变节点颜色。",
        [
            f"{REPORT}: 01/02/03/06/07 screenshots show the node panel and the low-height primary action remains visible, keyboard-focusable and navigable after scroll.",
            f"{FOCUSED_TESTS}::test_frontend_contract_uses_dedicated_workspace_and_no_evidence_write_calls checks the required detail and action contract.",
        ],
        implementation_evidence=[
            "frontend/src/views/MindmapWorkspace.vue: node-panel renders node facts, canonical sources, linked resources, question/note/quiz actions and the evidence boundary.",
        ],
    ),
    "G10-R05": related(
        "7.20学习画像及知识掌握图谱的路由和功能没有被替换；新增页面只挂在资源中心的mindmaps深链下。",
        [
            "frontend/src/router/index.js keeps the existing profile routes and adds MindmapResource only under /workspace/resources/mindmaps/:resourceId.",
            "The 16-test F2/F4/F5 protection regression passes, including profile/path contracts.",
        ],
    ),
    "G10-R06": related(
        "导图浏览、搜索、缩放、折叠、节点选择以及视图/版本偏好保存只发生在内存或localStorage，不调用学习事件、画像、路径完成或组卷门禁写接口。",
        [
            f"{FOCUSED_TESTS}::test_frontend_contract_uses_dedicated_workspace_and_no_evidence_write_calls rejects learning-event, mastery and completion mutation calls from the workspace.",
            f"{REPORT}: unexpected_write_requests is empty and learning_events, profile_snapshots and path_nodes are byte-identical before and after the complete E2E.",
        ],
        implementation_evidence=[
            "frontend/src/views/MindmapWorkspace.vue stores selected version/node/fold/zoom state only in localStorage; CollapsibleMindmap.vue emits local view-change events.",
        ],
    ),
    "G10-R07": related(
        "资源导图只增加从资源学习到来源、讲义、对话、笔记和测验题的深链，没有删除或改写7.20画像维度、分析、建议、编辑和生成资源能力。",
        [
            "No profile view or profile API file is modified by F5-T04; the F4 profile/path protection tests pass in the 16-test regression.",
            f"{REPORT}: the E2E exercises only resource, source, handout and local view routes while profile data remains unchanged.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G21-R01": related(
        "学习空间现有测评、路径、资源、复习、笔记和错题入口继续存在；F5-T04只把思维导图资源入口从通用预览升级为完整专用页面。",
        [
            "frontend/src/router/index.js retains the existing workspace routes and maps only MindmapResource to the new workspace.",
            "The F2/F4/F5 protection regression passes 16 tests and the production frontend build succeeds.",
        ],
        implementation_evidence=[
            "frontend/src/views/MindmapWorkspace.vue provides a direct return to WorkspaceResources rather than a second learning-space shell.",
        ],
    ),
    "G21-R02": related(
        "resourceId唯一定位导图资源，专用URL可刷新和返回；选择版本、节点、缩放和折叠状态可恢复，收藏仍由统一资源中心负责而不重复实现。",
        [
            f"{REPORT}: view_restoration.current_version_node and historical_version_node are true after reload; source and handout navigation both return to the same resource deep link.",
            f"{FOCUSED_TESTS}::test_mindmap_versions_remain_read_only_in_workspace_projection verifies stable resource/version identities.",
        ],
        implementation_evidence=[
            "frontend/src/views/MindmapWorkspace.vue keys local view preferences by resourceId and versionId; router/index.js exposes the stable MindmapResource path.",
        ],
    ),
    "G21-R03": related(
        "导图读取统一课程、知识点、任务、资源版本和来源引用，并保留返回资源中心、来源原文及兄弟资源的上下文，因此不是孤立技术演示页。",
        [
            f"{REPORT}: source_deep_link contains canonical_source_id, course_id, focus_source_ref_id and return_to; linked_handout_url resolves a sibling artifact.",
            f"{FOCUSED_TESTS}::test_structured_mindmap_projects_sources_and_safe_resource_links verifies same-owner/course source and resource projections.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G21-R04": related(
        "节点不理解时可携带课程、资源、版本、节点、摘要和来源引用进入既有智能对话；完整导图仍保留在资源空间，消息只接收紧凑上下文。",
        [
            "frontend/src/views/MindmapWorkspace.vue:askAboutNode constructs the bounded chat query and does not serialize the complete node tree.",
            f"{FOCUSED_TESTS}::test_frontend_contract_uses_dedicated_workspace_and_no_evidence_write_calls verifies the explicit node-question action and dedicated workspace.",
        ],
        status="COORDINATION_VERIFIED",
        implementation_evidence=[
            "frontend/src/views/MindmapWorkspace.vue exposes '询问这个节点/提问' actions that route to Chat with return_to.",
        ],
    ),
    "G21-R05": related(
        "导图中的练习入口只查找并打开quiz资源；没有在测评中心增加第三类入口，入学诊断和智能组卷职责保持不变。",
        [
            "frontend/src/views/MindmapWorkspace.vue:openQuizResource selects a linked quiz resource or routes to WorkspaceResources filtered to quiz.",
            "tests/test_f4_exam_gate.py passes in the 16-test protection regression, preserving the formal exam gate contract.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G21-R06": related(
        "总路径和科目路径仍是知识点与今日任务的唯一规划来源；导图只消费资源中已有的课程/知识点上下文，没有规划、重建或完成路径节点。",
        [
            "No path API or path view is modified by F5-T04; tests/test_f4_path_contract.py remains green.",
            f"{REPORT}: path_nodes hash is identical before and after every mind-map operation.",
        ],
    ),
    "G21-R07": related(
        "复习中心及真实月历入口完全保留；资源导图新增在资源路由下，没有替换复习首屏、课程筛选或日期任务列表。",
        [
            "frontend/src/router/index.js retains /workspace/review and /workspace/review/calendar while adding the mind-map route under resources.",
            "The production build and F2/F4/F5 protection regression pass without changing Review or RevisionCalendar components.",
        ],
    ),
    "G21-R08": related(
        "F5-T04只提供可被复习流程复用的稳定导图深链；没有提前实现复习一键生成资源或改写复习到智能组卷的流程。",
        [
            "The F5-T04 changed-file set contains no review-generation implementation.",
            f"{REPORT}: all tested mutations are absent and the path/event state remains unchanged while the resource deep link is stable.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G21-R09": related(
        "复习完成仍只能由真实复习提交事件产生；导图打开、节点选择和浏览没有完成按钮，也不写复习或学习完成记录。",
        [
            f"{REPORT}: learning_events and path_nodes hashes remain identical after search, fold, zoom, version restore, source navigation and linked-resource navigation.",
            f"{FOCUSED_TESTS}::test_frontend_contract_uses_dedicated_workspace_and_no_evidence_write_calls verifies no completion/event mutation call exists.",
        ],
    ),
    "G21-R10": related(
        "导图版本继续使用统一artifact version历史；专用页只读切换历史版本并在本地恢复所选视图，没有建立导图专属历史表或生成机制，为F5-T07统一版本动作保留边界。",
        [
            f"{FOCUSED_TESTS}::test_mindmap_versions_remain_read_only_in_workspace_projection verifies shared immutable version projections.",
            f"{REPORT}: database_audit records exactly two persisted mind-map version hashes and historical_version_node restores after reload without changing current version.",
        ],
        status="COORDINATION_VERIFIED",
        implementation_evidence=[
            "app/m5_resources.py projects current and historical DBArtifactVersion records; MindmapWorkspace.vue has no create/restore version write action.",
        ],
    ),
    "G21-R11": related(
        "学习中练习仍属于quiz测验题资源；导图只提供测验题资源深链，没有新增学习中练习到正式测评中心或改变两类测评中心结构。",
        [
            "app/resource_bundles.py retains quiz as a separate generated resource with its own route and completion rule.",
            "tests/test_f4_exam_gate.py and tests/test_f5_t02_resource_bundle_workspace.py pass in the protection regression.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G21-R12": related(
        "实训任务书、代码沙盒和可交互模型继续是三种独立资源；导图只按真实资源类型显示并打开关联深链，不内嵌伪任务、伪运行或伪实验结果。",
        [
            "app/resource_bundles.py keeps training_task, code_sandbox and interactive_model as separate generation types and routes.",
            f"{FOCUSED_TESTS}::test_structured_mindmap_projects_sources_and_safe_resource_links verifies only safe same-owner linked resources are exposed; the E2E displays no embedded runner or model controls.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G21-R13": related(
        "导图生成、打开、查看版本和浏览节点都不等同于今日必做任务完成；智能组卷仍只由F4总路径中的必做任务门禁授权。",
        [
            "tests/test_f4_exam_gate.py passes in the 16-test protection regression.",
            f"{REPORT}: path_nodes, learning_events and profile snapshots remain unchanged after the full E2E, proving the mind-map page cannot unlock or advance the gate.",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F5-T04_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F5-T04 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in REALIZATION]
    extra = [atom_id for atom_id in REALIZATION if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic realization mismatch: missing={missing}, extra={extra}")
    for entry in ledger["entries"]:
        entry["realization"] = REALIZATION[entry["atomic_requirement_id"]]
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(ROOT / "scripts"))
    from context_recovery_atomic_gate import (
        expected_entries,
        load_task_payload,
        validate_ledger_identity,
        validate_realization,
    )

    active = json.loads((CONTEXT_ROOT / "active_manifest.json").read_text(encoding="utf-8"))
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F5-T04")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T04",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F5-T04 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F5-T04 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
