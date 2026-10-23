#!/usr/bin/env python3
"""Populate and validate F5-T06's per-atom realization evidence."""

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
REPORT = "outputs/原系统融合重构执行/evidence/f5_t06_video_deck/report.json"
FOCUSED_TESTS = "tests/test_f5_t06_video_deck_workspace.py"
REGRESSION_TESTS = (
    "tests/test_f5_t05_training_task_workspace.py, "
    "tests/test_f5_t04_mindmap_workspace.py, "
    "tests/test_f5_t03_handout_workspace.py, "
    "tests/test_f5_t02_resource_bundle_workspace.py"
)
E2E = "scripts/e2e_f5_t06_video_deck_workspace.py"


def related(
    rationale: str,
    verification_evidence: list[str],
    *,
    implementation_evidence: list[str] | None = None,
) -> dict[str, object]:
    return {
        "status": "COORDINATION_VERIFIED",
        "implementation_evidence": implementation_evidence or [],
        "verification_evidence": verification_evidence,
        "user_visible_result": "",
        "compatibility_or_defer_rationale": rationale,
    }


REALIZATION = {
    "G03-R01": related(
        "视频推荐和PPT/网页课件已经作为九类资源中的两个独立Artifact类型及专用深链存在；可交互模型仍保留独立类型与路由，F5-T06不吞并F6职责。",
        [
            f"{FOCUSED_TESTS}::test_resource_detail_projects_traceable_video_and_artifact_deck_without_writes verifies independent video/deck projections.",
            f"{REPORT}: video and deck source links, routes, and artifact versions are present; database_audit records separate f5-t06-video and f5-t06-deck identities.",
        ],
        implementation_evidence=[
            "app/m5_resources.py:RESOURCE_CATALOG_TYPES and RESOURCE_ROUTES define video and deck separately.",
            "frontend/src/views/VideoRecommendationWorkspace.vue and frontend/src/views/WebDeckWorkspace.vue are separate workspaces.",
        ],
    ),
    "G03-R02": related(
        "两类产物的结构化内容都携带课程、知识点、学习目标、画像适配摘要和sourceRefIds；推荐理由与课件内容来自冻结资源版本，而不是通用素材列表。",
        [
            f"{FOCUSED_TESTS}::test_deterministic_generation_uses_legal_video_catalog_and_structured_deck verifies deterministic, source-bound video/deck generation.",
            f"{REPORT}: the rendered pages show course/knowledge-point context, learning goal, adaptation basis, source and version panels.",
        ],
        implementation_evidence=[
            "app/resource_bundles.py emits the video/deck branches from the shared generation manifest.",
            "app/m5_resources.py:parse_video_recommendation_content and parse_deck_content validate structured source-bound schemas.",
        ],
    ),
    "G03-R03": related(
        "视频页采用推荐列表/播放器/分段/推荐理由/来源许可三栏学习结构；课件页采用大纲/大预览/来源版本与编辑导出结构，避免JSON和长文本墙。",
        [
            f"{REPORT}: 9 screenshots at 1440x900 and 2 at 1366x768 cover playable, unavailable, external, empty, current, editing and history states with no clipping, collision or small-text findings.",
            "final Impeccable detector returned an empty findings array for both target workspaces.",
        ],
        implementation_evidence=[
            "frontend/src/views/VideoRecommendationWorkspace.vue renders recommendation list, media state, segments, reason, evidence and source/license sections.",
            "frontend/src/views/WebDeckWorkspace.vue renders outline, page preview, source/version panel, editor and export actions.",
        ],
    ),
    "G03-R04": related(
        "媒体页面只在学生从资源中心或深链明确进入后读取既有resourceId/versionId；播放、跳段、翻页、查看来源和草稿编辑不会自动生成资源或打断主学习流程。",
        [
            f"{FOCUSED_TESTS}::test_frontend_contract_uses_dedicated_artifact_workspaces_and_no_generation_ui confirms the pages do not expose media generation controls.",
            f"{REPORT}: unexpected_write_requests is empty except the deliberate deck version POST; video browsing and notes do not write learning events.",
        ],
        implementation_evidence=[
            "frontend/src/router/index.js registers only resource-scoped video/deck routes under the existing workspace hierarchy.",
            "frontend/src/views/VideoRecommendationWorkspace.vue and WebDeckWorkspace.vue load by route resourceId/versionId and preserve return_to.",
        ],
    ),
    "G03-R05": related(
        "资源中心仍是视频和课件的唯一目录、搜索、归档和再次打开入口；专用页面只是同一Artifact/ArtifactVersion的学习视图，没有平行媒体库。",
        [
            f"{FOCUSED_TESTS}::test_resource_detail_projects_traceable_video_and_artifact_deck_without_writes verifies persisted artifact detail projections.",
            f"{REPORT}: return-to-resource-center links preserve course_id, resource_id and version_id for both workspaces.",
        ],
        implementation_evidence=[
            "app/m5_api.py routes resource detail, media lookup, deck export and version creation through the shared M5 resource protocol.",
            "frontend/src/api/m5.js uses the shared /v1/m5/resources/:artifactId endpoints.",
        ],
    ),
    "G03-R06": related(
        "视频和课件作为九类资源包的稳定兄弟条目生成、校验、归档和打开；F5-T06只完善这两项，不改变其他七项的身份、状态、重试和完成规则。",
        [
            f"{FOCUSED_TESTS}::test_deterministic_generation_uses_legal_video_catalog_and_structured_deck verifies both branches are generated from the shared resource bundle.",
            f"{REGRESSION_TESTS} and {FOCUSED_TESTS} passed together: 33 tests, including resource bundle, handout, mindmap and training-task contracts.",
        ],
        implementation_evidence=[
            "app/m5_resources.py:RESOURCE_CATALOG_TYPES and app/resource_bundles.py keep video/deck as independent nine-resource entries.",
        ],
    ),
    "G03-R07": related(
        "F5-T03高质量个性化讲义继续使用独立handout Artifact和页面；视频/课件只通过sourceRefs或relatedResources引用同源内容，不覆盖讲义内容、版本或导出。",
        [
            f"{REGRESSION_TESTS} passed with the F5-T06 focused suite; the handout workspace and handout projection remain covered.",
            "frontend production build emits separate HandoutWorkspace, VideoRecommendationWorkspace and WebDeckWorkspace chunks.",
        ],
        implementation_evidence=[
            "app/m5_resources.py keeps handout parsing/projection separate from video and deck schemas.",
            "frontend/src/views/HandoutWorkspace.vue is not modified by the F5-T06 page flow and remains a sibling resource route.",
        ],
    ),
    "G03-R08": related(
        "视频推荐、分段、课件页面树、来源、版本和导出状态都保存在统一ArtifactVersion内容中；对话、路径和资源包只需展示摘要和深链。",
        [
            f"{FOCUSED_TESTS}::test_video_and_deck_schemas_reject_ambiguous_or_duplicate_structure verifies complete structured content and rejects invalid schema.",
            f"{REPORT}: version history hashes, source links and exported HTML/PPTX are recorded; html_bytes=2705 and pptx_bytes=38304.",
        ],
        implementation_evidence=[
            "app/m5_resources.py parses and projects structured video/deck content from DBArtifactVersion.",
            "frontend/src/views/WebDeckWorkspace.vue keeps full content in the dedicated page rather than chat cards.",
        ],
    ),
    "G21-R01": related(
        "学习空间继续包含资源中心、视频推荐和PPT/网页课件，它们与其他学习资源共享现有应用壳，不增加学生一级导航上的独立媒体工作台。",
        [
            f"{REPORT}: both pages render inside the existing EduMatrix shell with 学习空间 active and a return-to-resource-center action.",
            f"{REGRESSION_TESTS} keeps the existing resource-space routes green.",
        ],
        implementation_evidence=[
            "frontend/src/router/index.js places both routes under /workspace/resources.",
            "frontend/src/components/AppShell.vue remains the shared application shell.",
        ],
    ),
    "G21-R02": related(
        "每个视频和课件都拥有以resourceId为核心的可刷新专用学习页面；刷新、历史版本切换和返回资源中心保持同一对象身份。",
        [
            f"{REPORT}: video_history_refresh_restored and deck_history_refresh_restored are true; 11 screenshots include both desktop sizes.",
            f"{FOCUSED_TESTS}::test_resource_detail_projects_traceable_video_and_artifact_deck_without_writes verifies stable resource detail routes.",
        ],
        implementation_evidence=[
            "frontend/src/router/index.js defines /workspace/resources/videos/:resourceId and /workspace/resources/decks/:resourceId.",
            "frontend/src/views/VideoRecommendationWorkspace.vue and WebDeckWorkspace.vue read route version_id without creating a second object.",
        ],
    ),
    "G21-R03": related(
        "首屏共享课程、知识点、学习目标、适配依据和版本上下文，并明确现在做什么、完成条件和下一步；媒体页面没有脱离原学习任务的标题。",
        [
            f"{REPORT}: rendered screenshots show ‘RAG应用开发与负责任评测实训·梯度下降’, learning goal, adaptation basis and the three-part task band.",
            "dual desktop visual checks report stable fog-white page, white surfaces and ink/navy primary actions.",
        ],
        implementation_evidence=[
            "app/m5_resources.py includes course/knowledge-point/source/version fields in the learner-safe resource projection.",
            "frontend/src/views/VideoRecommendationWorkspace.vue and WebDeckWorkspace.vue render the shared task-context header.",
        ],
    ),
    "G21-R04": related(
        "视频章节和课件页面提供当前章节/页面的智能对话入口，并将课程、资源、版本和页面上下文放入深链；完整媒体产物仍留在资源空间。",
        [
            f"{REPORT}: video_question_link and deck_question_link preserve course_id, resource_id, version_id and segment_id/slide_id.",
            f"{FOCUSED_TESTS}::test_resource_detail_projects_traceable_video_and_artifact_deck_without_writes verifies context-bearing source/question links.",
        ],
        implementation_evidence=[
            "frontend/src/views/VideoRecommendationWorkspace.vue creates segment-aware question links.",
            "frontend/src/views/WebDeckWorkspace.vue creates slide-aware question links while keeping the deck page as the artifact view.",
        ],
    ),
    "G21-R05": related(
        "视频和课件页面只提供学习、来源、笔记、编辑、导出和针对当前内容提问，不新增正式测评入口；测评中心仍由入学诊断和智能组卷承担。",
        [
            f"{FOCUSED_TESTS}::test_frontend_contract_uses_dedicated_artifact_workspaces_and_no_generation_ui verifies no assessment-center or exam-unlock call is introduced.",
            f"{REGRESSION_TESTS} passed and keeps quiz/exam resource contracts separate.",
        ],
        implementation_evidence=[
            "frontend/src/views/VideoRecommendationWorkspace.vue and WebDeckWorkspace.vue contain no formal assessment action.",
            "app/m5_resources.py keeps quiz and assessment routes separate from video/deck routes.",
        ],
    ),
    "G21-R06": related(
        "视频和课件从总路径/今日知识点生成的resourceId进入并保留课程任务返回上下文；F5-T06没有改变路径、预算、节奏或每日任务编排。",
        [
            f"{REPORT}: safe_return_to and all source/question links preserve the original course and resource-center return context.",
            f"{REGRESSION_TESTS} passed with protected path/resource-bundle contracts intact.",
        ],
        implementation_evidence=[
            "frontend/src/views/VideoRecommendationWorkspace.vue and WebDeckWorkspace.vue preserve return_to and course_id query parameters.",
            "app/m5_api.py reads shared artifacts without writing path versions or task plans.",
        ],
    ),
    "G21-R07": related(
        "F5-T06不改写复习中心日历或复习首页；视频和课件只保留可被未来复习任务按resourceId引用的兼容入口。",
        [
            f"{REGRESSION_TESTS} passed without modifying the review route or revision-calendar contract.",
            f"{FOCUSED_TESTS}::test_video_is_read_only_and_failed_deck_save_preserves_current_version verifies media browsing does not write review evidence.",
        ],
        implementation_evidence=[
            "frontend/src/router/index.js changes are limited to resource-scoped video/deck routes and do not replace /workspace/review.",
        ],
    ),
    "G21-R08": related(
        "两类媒体使用统一九类资源协议接受课程/知识点上下文，专用页面只负责消费已归档资源；本任务没有另建复习或媒体生成链。",
        [
            f"{FOCUSED_TESTS}::test_deterministic_generation_uses_legal_video_catalog_and_structured_deck verifies shared generation output and stable type identity.",
            f"{REGRESSION_TESTS} passed across resource bundle, handout, mindmap and training-task siblings.",
        ],
        implementation_evidence=[
            "app/resource_bundles.py is the shared generation source for video/deck entries.",
            "app/m5_api.py and frontend/src/api/m5.js use the same artifact/version APIs for every resource type.",
        ],
    ),
    "G21-R09": related(
        "观看、跳段、翻页、查看来源和编辑草稿不伪装成复习完成或掌握度证据；课件保存只写ArtifactVersion，视频和普通页面动作保持只读。",
        [
            f"{FOCUSED_TESTS}::test_video_is_read_only_and_failed_deck_save_preserves_current_version verifies no learning evidence is written by media actions.",
            f"{REPORT}: protected state is unchanged, unexpected_write_requests is empty and only two deliberate deck-version POSTs are recorded.",
        ],
        implementation_evidence=[
            "frontend/src/views/VideoRecommendationWorkspace.vue has no learning-event or task-completion call.",
            "frontend/src/views/WebDeckWorkspace.vue saves through the artifact-version endpoint only.",
        ],
    ),
    "G21-R10": related(
        "媒体资源显示版本历史；课件编辑以另存新版本方式保存，历史版本只读，并可返回统一资源中心重新生成同类资源。",
        [
            f"{FOCUSED_TESTS}::test_deck_edit_creates_new_artifact_version_and_exports_real_files verifies new version, HTML/PPTX export and history.",
            f"{REPORT}: deck versions 1, 2 and 3 have distinct content hashes; deck_history_refresh_restored and conflict_draft_preserved are true.",
        ],
        implementation_evidence=[
            "app/m5_resources.py:create_resource_version and render_deck_export implement versioned save and export.",
            "frontend/src/views/WebDeckWorkspace.vue separates current edit mode from read-only historical mode.",
        ],
    ),
    "G21-R11": related(
        "视频与课件页没有‘学习中练习’或正式测评中心第三入口；即时练习仍归测验题资源，视频页只做推荐/播放，课件页只做阅读/编辑/导出。",
        [
            f"{FOCUSED_TESTS}::test_frontend_contract_uses_dedicated_artifact_workspaces_and_no_generation_ui verifies the prohibited legacy generation/practice path is absent.",
            f"{REGRESSION_TESTS} passed with quiz, training-task and resource-bundle identities preserved.",
        ],
        implementation_evidence=[
            "frontend/src/views/VideoRecommendationWorkspace.vue is a read/recommendation workspace and WebDeckWorkspace.vue is a deck workspace; neither imports the exam-center actions.",
        ],
    ),
    "G21-R12": related(
        "实训任务书、代码沙盒、可交互模型、视频推荐和课件保持不同artifact_type与页面职责；媒体页只展示关联来源/学习入口，不代替工程指导、真实运行或参数实验。",
        [
            f"{REGRESSION_TESTS} passed and verifies the distinct training-task, mindmap, handout and resource bundle contracts.",
            f"{FOCUSED_TESTS}::test_resource_detail_projects_traceable_video_and_artifact_deck_without_writes verifies media-specific schemas and routes.",
        ],
        implementation_evidence=[
            "app/m5_resources.py:RESOURCE_CATALOG_TYPES and RESOURCE_ROUTES keep training_task, code_sandbox, interactive_model, video and deck distinct.",
            "frontend/src/views/TrainingTaskWorkspace.vue and the media workspaces remain separate route components.",
        ],
    ),
    "G21-R13": related(
        "视频和课件生成后进入资源中心，但普通观看、跳段、翻页、来源查看、记笔记和编辑不会自动完成今日任务或解锁智能组卷；完成边界仍由F4/F6证据协议判断。",
        [
            f"{FOCUSED_TESTS}::test_video_is_read_only_and_failed_deck_save_preserves_current_version verifies media actions do not call task completion or exam-unlock paths.",
            f"{REPORT}: protected learning/path/profile state remains unchanged, unexpected_write_requests is empty, and process cleanup is true.",
        ],
        implementation_evidence=[
            "frontend/src/views/VideoRecommendationWorkspace.vue and WebDeckWorkspace.vue expose return/task context but do not call completion APIs.",
            "app/m5_api.py keeps artifact version writes separate from learning-event aggregation and exam-gate decisions.",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F5-T06_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F5-T06 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F5-T06")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T06",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F5-T06 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F5-T06 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
