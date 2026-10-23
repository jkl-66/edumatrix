#!/usr/bin/env python3
"""Populate and validate F5-T03's per-atom realization evidence."""

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
REPORT = "outputs/原系统融合重构执行/evidence/f5_t03_handout/report.json"


def primary(
    implementation_evidence: list[str],
    verification_evidence: list[str],
    user_visible_result: str,
) -> dict[str, object]:
    return {
        "status": "IMPLEMENTED_AND_VERIFIED",
        "implementation_evidence": implementation_evidence,
        "verification_evidence": verification_evidence,
        "user_visible_result": user_visible_result,
        "compatibility_or_defer_rationale": "",
    }


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
    "G03-R03": primary(
        [
            "frontend/src/views/HandoutWorkspace.vue: dedicated 220px/flexible/300px reading workspace separates outline, continuous document and bounded learning support instead of rendering a card wall or text wall.",
            "app/m5_resources.py: HandoutContent and parse_handout_content require a strict structured f5.handout.v1 document and reject incomplete one-field JSON.",
        ],
        [
            "tests/test_f5_t03_handout_workspace.py::test_handout_schema_requires_every_learning_section_and_rejects_text_wall_json verifies the structure cannot regress to a single long field.",
            f"{REPORT}: eight desktop captures at 1440x900 and 1366x768 report zero clipping, collisions, overflow, sub-14px visible text or forbidden effects; 01-structured-current-1440x900.png shows the complete reading geometry.",
        ],
        "学生打开讲义后先用左侧目录定位章节，在中央连续阅读正文，并在右侧按需查看伙伴、学习支架、来源和导出；页面不再是一整块长文本。",
    ),
    "G03-R07": primary(
        [
            "app/m5_resources.py: HandoutContent requires title, adaptation summary, learning goal, outline, concepts, figures/formulas, examples, counterexamples, code, mini quiz and source footnotes; resource detail adds source readiness and version projections.",
            "frontend/src/views/HandoutWorkspace.vue: renders every required section plus AI partner, reading position, structured editing, version selection/comparison and HTML/JSON export with loading, conflict, legacy, invalid and unavailable-source states.",
            "app/resource_bundles.py:_deterministic_demo_content emits a complete structured handout for the normal F5 resource-bundle path.",
        ],
        [
            "tests/test_f5_t03_handout_workspace.py covers complete generation, structured/legacy/invalid projections, unavailable sources, additive history editing, non-handout isolation, export and frontend contracts; 9 focused tests pass.",
            f"{REPORT}: structured quiz, historical version, new version from history, legacy compatibility, invalid repair, unavailable source and both desktop sizes pass with three immutable structured versions and a verified HTML export.",
        ],
        "学生可在一份讲义里完成目录导航、概念和公式阅读、正反例对照、代码阅读、小测、来源核对、伙伴追问、进度查看、编辑另存、历史比较和导出。",
    ),
    "G03-R01": related(
        "F5-T03只实现个性化讲义详情，不把可交互模型或PPT/网页课件嵌入讲义；两类资源继续保持九类资源包中的独立类型和深链，由各自主责任务完成。",
        [
            "app/resource_bundles.py keeps handout, deck and interactive_model as three distinct GENERATION_RESOURCE_TYPES with separate routes.",
            "The F5-T03 modified-file set adds only the handout workspace and does not alter model or deck workspaces; the 24-test F5/resource regression passes.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G03-R02": related(
        "讲义沿用F5-T02冻结的画像、知识点和学习目标；结构化正文把适配摘要、难度和学习支架作为必需字段展示，不创建第二套画像或从普通阅读推断新画像。",
        [
            "app/resource_bundles.py emits profileAdaptation, learningGoal and knowledge-point-linked source metadata in the structured handout content.",
            "HandoutWorkspace.vue displays the stored adaptation summary and scaffolding; report.json proves profile snapshots remain byte-identical throughout reading, quiz, version and export actions.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G03-R04": related(
        "专用讲义页只读取已经归档的resourceId；加载、切换版本、滚动、查看来源和小测检查不会调用资源生成接口，生成仍只由F4/F5-T02显式动作触发。",
        [
            "frontend/src/views/HandoutWorkspace.vue loads getM5Resource(resourceId) and contains no resource-bundle create call or implicit generation watcher.",
            f"{REPORT}: all journeys open seeded existing resources, learning events/profile snapshots/path nodes remain unchanged, and no failed or unexpected requests are recorded.",
        ],
    ),
    "G03-R05": related(
        "讲义专用页是统一资源对象的详情视图；返回动作指向既有资源中心，页面没有新增讲义目录、搜索数据库或第二个资源入口。",
        [
            "frontend/src/router/index.js maps the existing handout resource deep link to HandoutWorkspace while ResourceCenter remains the catalog owner.",
            "HandoutWorkspace.vue uses the shared M5 resource detail/version/export APIs and provides a clear resource-center breadcrumb/back action; the 24-test shared-resource regression passes.",
        ],
    ),
    "G03-R06": related(
        "F5-T03只改变handout内容生成和handout详情路由；另外八项继续使用F5-T02的独立item状态、资源身份和深链，讲义保存不会改写兄弟资源。",
        [
            "app/resource_bundles.py changes deterministic content only in the handout branch and leaves the exact nine-type tuple and sibling branches intact.",
            "tests/test_f5_t02_resource_bundle_workspace.py and tests/test_f2_resource_generation_protocol.py pass in the 24-test regression, while report.json records only handout versions changing.",
        ],
    ),
    "G03-R08": related(
        "讲义全文、来源和版本历史继续保存在统一artifact/version对象；AI伙伴只把问题和当前讲义/版本上下文带到既有智能对话，不把完整产物复制进消息。",
        [
            "app/m5_resources.py serves handout projections from DBArtifactVersion and canonical source refs; edits append through create_resource_version.",
            "HandoutWorkspace.vue:askPartner navigates with resource_id/version_id/prompt context, and the E2E returns three persisted structured versions without creating duplicate resource objects.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G08-R01": related(
        "讲义仍由资源包成功项自动创建并归档；专用页只展示该归档资源和其生成/来源状态，不增加手动入库按钮。",
        [
            "app/resource_bundles.py creates the handout through the shared complete-generation path with artifact metadata and stable route.",
            "HandoutWorkspace.vue contains no manual archive or import action; tests/test_f5_t02_resource_bundle_workspace.py remains green.",
        ],
    ),
    "G08-R02": related(
        "搜索、类型筛选和讲义查找继续由统一资源中心承担；专用页仅提供面包屑与返回，不重复实现搜索或分类界面。",
        [
            "frontend/src/views/HandoutWorkspace.vue has no catalog search/filter state and links back to WorkspaceResources.",
            "tests/test_m5_resources.py passes in the combined regression, preserving the shared catalog search and source filters.",
        ],
    ),
    "G08-R03": related(
        "讲义页只展示可复制的代码阅读块，并明确真实运行必须进入独立代码沙盒；不把代码沙盒或交互实验伪装成讲义内部功能。",
        [
            "HandoutWorkspace.vue copyCode reports '真实运行请进入代码沙盒' and exposes no run/stop/output controls.",
            "app/resource_bundles.py retains code_sandbox and interactive_model as separate types/routes; the 24-test protocol regression passes.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G08-R04": related(
        "结构化编辑器直接编辑标题、摘要、目标、概念、图表、例子、反例、代码、小测和画像适配字段；无需整份重新生成，来源ID保持只读边界。",
        [
            "frontend/src/views/HandoutWorkspace.vue:startEditing clones the selected version and exposes section-level fields before createM5ResourceVersion.",
            "tests/test_f5_t03_handout_workspace.py::test_handout_frontend_contract_has_dedicated_route_full_sections_and_no_mastery_write checks the editing contract; E2E creates a new version from an edited historical version.",
        ],
        implementation_evidence=[
            "frontend/src/views/HandoutWorkspace.vue: structured editor and source-edit boundary.",
        ],
    ),
    "G08-R05": related(
        "讲义保存始终调用统一新增版本接口；即使从历史版本开始编辑也生成新的current版本，旧版本内容、哈希和来源保持不变。",
        [
            "tests/test_f5_t03_handout_workspace.py::test_historical_handout_edit_appends_version_without_mutating_history verifies v1/v2 remain unchanged while v3 is appended.",
            f"{REPORT}: database_audit lists structured versions v1, v2 and v3 with distinct hashes, SQLite integrity is ok and foreign-key violations are zero.",
        ],
        implementation_evidence=[
            "app/m5_resources.py:create_resource_version allows historical handout branching only through add_artifact_version and optimistic lock validation.",
        ],
    ),
    "G08-R06": related(
        "讲义页已提供版本列表、旧版只读切换和与当前版比较；F5-T03不暴露覆盖式恢复按钮，跨资源统一的‘恢复即另存’动作仍由F5-T07主责收口。",
        [
            "HandoutWorkspace.vue marks historical versions read-only, offers compareWithCurrent, and changes the primary action to '从此版本继续编辑'.",
            f"{REPORT}: 03-historical-version-1440x900.png and 04-new-version-from-history-1440x900.png verify historical viewing, comparison and additive branching without direct overwrite.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G08-R07": related(
        "讲义详情如实呈现加载、结构待修复、旧版兼容、来源不足、保存冲突、导出失败和恢复成功；错误只影响对应动作，正文与草稿保留。资源包级生成中/部分成功仍由F5-T02页展示。",
        [
            "app/m5_resources.py returns learner-facing Chinese warnings and per-version source readiness for structured, legacy and invalid modes.",
            "HandoutWorkspace.vue preserves drafts across optimistic-lock refresh, keeps content on export failure, and has distinct loading/error/invalid/source states.",
            f"{REPORT}: 05/06/07 screenshots verify legacy, invalid and unavailable-source states with stable layouts; zero HTTP, console, page or request errors are recorded.",
        ],
        status="COORDINATION_VERIFIED",
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F5-T03_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F5-T03 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F5-T03")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T03",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F5-T03 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F5-T03 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
