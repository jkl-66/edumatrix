#!/usr/bin/env python3
"""Populate and validate F5-T02's per-atom realization evidence."""

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
REPORT = "outputs/原系统融合重构执行/evidence/f5_t02_resource_bundle/report.json"


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
    "G03-R01": primary(
        [
            "app/resource_bundles.py: GENERATION_RESOURCE_TYPES includes interactive_model and deck as separate archived types.",
            "frontend/src/views/ResourceBundleWorkspace.vue: resourceMeta renders separate '可交互模型' and 'PPT / 网页课件' rows with distinct purposes and open actions.",
        ],
        [
            "tests/test_f5_t02_resource_bundle_workspace.py::test_student_workspace_contract_uses_nine_items_and_no_engineering_metadata checks both labels in the learner workspace.",
            f"{REPORT}: retry and recovery scenarios each archive nine distinct artifacts; both type lists contain deck and interactive_model exactly once.",
        ],
        "学生在完整资源包中能分别看到并打开可交互模型和 PPT/网页课件，它们不会被藏进聊天消息或其他资源类型。",
    ),
    "G03-R02": primary(
        [
            "app/resource_bundles.py:_generation_context_snapshot freezes course, knowledge point, bounded learning_goal, profile adaptation and profile snapshot identity in the requested manifest.",
            "frontend/src/views/LearningPathGraph.vue: buildGenerationPayload sends the selected today's task knowledge point and explicit learning goal in the single generation request.",
        ],
        [
            "tests/test_f5_t02_resource_bundle_workspace.py::test_generation_job_freezes_student_safe_context_and_hides_event_ids verifies the frozen goal/profile context and idempotency conflict when the goal changes.",
            f"{REPORT}: both jobs expose the same frozen course, knowledge point, learning goal and learner-safe profile adaptation across all nine items.",
        ],
        "九项资源共享同一份已冻结的课程、知识点、学习目标和画像适配依据，页面顶部统一说明本次资源为什么这样生成。",
    ),
    "G03-R04": primary(
        [
            "frontend/src/views/LearningPathGraph.vue: generateSelectedTaskResources is bound to the explicit '一键生成完整资源包' action and is not invoked by task selection or ordinary browsing.",
            "frontend/src/views/LearningPathGraph.vue: successful creation navigates once to the ResourceBundle route for the returned job_id.",
        ],
        [
            "tests/test_f5_t02_resource_bundle_workspace.py::test_student_workspace_contract_uses_nine_items_and_no_engineering_metadata confirms the explicit path-to-bundle navigation contract.",
            f"{REPORT}: both scenarios record one_generation_job=true after the explicit path click; no browsing action creates a second job.",
        ],
        "学生先选择今日知识点，再主动点击一次生成；仅查看路径、切换任务或进入页面不会偷偷开始生成。",
    ),
    "G03-R06": primary(
        [
            "app/resource_bundles.py: GENERATION_RESOURCE_TYPES fixes the protocol order to handout, mind_map, quiz, training_task, code_sandbox, video, deck, interactive_model and feynman.",
            "frontend/src/views/ResourceBundleWorkspace.vue: resourceMeta gives all nine protocol types learner-facing names, purposes and stable rows.",
        ],
        [
            "tests/test_f2_resource_generation_protocol.py::test_nine_type_job_idempotency_partial_retry_and_owner_boundary asserts the exact nine-type sequence and nine unique item idempotency keys.",
            f"{REPORT}: every generated job reports exactly the nine approved types and nine_generated_artifacts=true.",
        ],
        "一次请求固定准备九项资源，学生不需要逐项重复点击，也不会漏掉测验、实训、代码、视频、课件、交互模型或费曼任务。",
    ),
    "G03-R08": primary(
        [
            "app/resource_bundles.py: complete_generation_item creates or reuses the typed resource, records its source/profile/task identity and returns a stable resource route without replacing successful siblings.",
            "frontend/src/views/ResourceBundleWorkspace.vue: succeeded rows expose only their archived resource deep link; full content remains on the dedicated resource page.",
        ],
        [
            "tests/test_f2_resource_generation_protocol.py::test_demo_execution_archives_nine_resources_and_does_not_create_learning_evidence verifies nine persisted artifacts, stable replay identities and zero learning evidence from generation.",
            "tests/test_f2_resource_generation_protocol.py::test_nine_type_job_idempotency_partial_retry_and_owner_boundary verifies the archived resource can be reopened through the owner-scoped resource API.",
        ],
        "每个成功产物都以独立资源身份归档，学生可从资源包或资源中心再次打开；聚合页只显示状态和入口，不堆放完整正文。",
    ),
    "G21-R12": primary(
        [
            "frontend/src/views/ResourceBundleWorkspace.vue: resourceMeta defines separate labels and purposes for training_task, code_sandbox and interactive_model.",
            "app/resource_bundles.py: each of the three types receives its own item state, completion rule, resource identity and route.",
        ],
        [
            "tests/test_f5_t02_resource_bundle_workspace.py::test_student_workspace_contract_uses_nine_items_and_no_engineering_metadata requires all three learner-facing labels.",
            "Manual screenshot review of retry-02-single-item-failed-1440x900.png and recovery-04-complete-1366x768.png confirms each type occupies a distinct row with a distinct purpose and action.",
        ],
        "学生能直接分辨：实训任务书用于看工程要求，代码沙盒任务用于进入运行环境，可交互模型用于调参观察规律。",
    ),
    "G22-R03": primary(
        [
            "app/resource_bundles.py:_mastery_summary freezes the current knowledge-point mastery interpretation from the profile snapshot.",
            "app/resource_bundles.py:_recent_learning_context includes only related accepted mastery-eligible events and stores their IDs privately while exposing only a count summary.",
        ],
        [
            "tests/test_f5_t02_resource_bundle_workspace.py::test_generation_job_freezes_student_safe_context_and_hides_event_ids verifies mastery 42%, one accepted event, private event IDs and the learner-safe public response.",
            "tests/test_f5_t02_resource_bundle_workspace.py::test_generation_context_ignores_non_evidence_browsing_events verifies an ordinary resource.viewed event is excluded.",
        ],
        "资源包会根据学生当前掌握程度和最近的有效学习证据调整内容，但页面不会泄露内部事件 ID 或把普通浏览误当成学习证据。",
    ),
    "G22-R09": primary(
        [
            "frontend/src/views/LearningPathGraph.vue: all path-triggered generation requests use the shared resource-bundle API and navigate to /workspace/resources/bundles/:jobId.",
            "frontend/src/views/ResourceBundleWorkspace.vue: completed items open their shared archived resource route and the page offers a direct return to the unified resource center.",
        ],
        [
            f"{REPORT}: both scenarios recover the same job by deep link, archive nine artifacts and return to the selected today's task.",
            "tests/test_f2_resource_generation_protocol.py::test_nine_type_job_idempotency_partial_retry_and_owner_boundary verifies the same archived resource is available through the shared /api/v1/m5/resources endpoint.",
        ],
        "无论从路径触发还是以后从其他入口触发，完整产物都回到同一个学习空间资源体系继续学习。",
    ),
    "G03-R03": related(
        "F5-T02只保证讲义作为独立资源被编排、归档和打开，不提前宣称完成F5-T03的高级讲义正文与视觉合同。",
        [
            "ResourceBundleWorkspace.vue labels handout as '个性化讲义' and describes its purpose without rendering a long text body.",
            f"{REPORT}: handout is archived once with a stable identity and can be opened after sibling failure and recovery.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G03-R05": related(
        "F5-T02复用F5-T01统一资源中心和既有资源详情接口，不建立第二个资源目录。",
        [
            "ResourceBundleWorkspace.vue provides '查看资源中心' after completion and opens each succeeded resource through resource.route.",
            "The 42-test regression includes F1/F4 protection and the shared resource protocol; all passed.",
        ],
    ),
    "G03-R07": related(
        "讲义的目录、图表、正反例、代码、小测、伙伴、编辑和导出由F5-T03唯一主责；本任务保留讲义的来源、版本身份和完成规则，不用简陋正文替代后续实现。",
        [
            "tests/test_f2_resource_generation_protocol.py::test_resource_revision_compare_restore_and_source_withdrawal cover the existing version/source protocol retained for later handout work.",
            "The resource-bundle page contains no generic handout text wall and only exposes the dedicated open action.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G21-R01": related(
        "本任务只把九类资源包接入既有学习空间信息架构；测评、路径、复习、笔记、错题和资源中心的现有入口没有被重命名或复制。",
        [
            "tests/test_fusion_f0_f1_contract.py::test_f1_router_declares_the_50_approved_target_routes_once passed in the final 42-test set.",
            "ResourceBundleWorkspace.vue uses the existing AppShell and WorkspaceResources/LearningPath named routes.",
        ],
    ),
    "G21-R02": related(
        "资源包和九个归档资源均使用稳定ID深链；刷新只重新读取同一job_id，不依赖内存中的临时页面状态。",
        [
            f"{REPORT}: service_restart_verified=true for recovery and both scenarios complete after deep-link refresh.",
            "recovery-02-restored-after-service-restart-1440x900.png shows the same job restored after backend restart.",
        ],
    ),
    "G21-R03": related(
        "F5-T02沿用F2/F4统一课程、知识点、画像快照和路径任务标识，不创建资源专用的第二套上下文事实源。",
        [
            "tests/test_f5_t02_resource_bundle_workspace.py::test_generation_job_freezes_student_safe_context_and_hides_event_ids validates the shared course, knowledge-point and profile snapshot context.",
            f"{REPORT}: path_nodes_unchanged and profile_snapshots_unchanged are true in both isolated scenarios.",
        ],
    ),
    "G21-R04": related(
        "智能对话携带资源上下文属于F7-T04；F5-T02保持创建协议与聊天UI解耦，并提供稳定资源ID和路由供后续对话引用。",
        [
            "app/resource_bundles_api.py creates and reads jobs using course/profile/task/item fields without any chat-message schema dependency.",
            "The F5-T02 modified-file list contains no Chat.vue or chat backend module.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G21-R05": related(
        "九类资源包中的quiz明确是测验题资源，不新增测评中心入口，也不把生成任务当成正式测评。",
        [
            "ResourceBundleWorkspace.vue uses the label '测验题资源'.",
            "tests/test_f4_exam_gate.py and tests/test_fusion_f0_f1_contract.py passed in the final regression set, preserving the existing assessment boundary.",
        ],
    ),
    "G21-R06": related(
        "资源包从F4今日路径进入，并保留return_task/node_id以返回同一任务；没有引入割裂的阶段工作台。",
        [
            "LearningPathGraph.vue passes return_task when navigating to ResourceBundle; ResourceBundleWorkspace.vue returns with node_id.",
            f"{REPORT}: both browser scenarios verify return to today's task.",
        ],
    ),
    "G21-R07": related(
        "真实复习日历由F8-T01负责；F5-T02没有修改复习页面或把资源生成状态伪装成复习安排。",
        [
            "The F5-T02 modified-file and impact lists contain no review-calendar implementation file.",
            f"{REPORT}: generation leaves learning events, profile snapshots and path nodes unchanged, so no synthetic review state is created.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G21-R08": related(
        "后续复习入口可复用同一创建API，因为协议只需要统一课程、知识点、画像、任务和九类item，不依赖今日路径组件的私有结构；本任务不提前改F8页面。",
        [
            "app/resource_bundles_api.py exposes owner-scoped create/get/retry/recover operations independent of a specific frontend caller.",
            "tests/test_f2_resource_generation_protocol.py::test_nine_type_job_idempotency_partial_retry_and_owner_boundary exercises the API without LearningPathGraph.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G21-R09": related(
        "生成、查看、重试和恢复只改变生成任务与资源归档，不写复习完成或掌握证据。",
        [
            f"{REPORT}: learning_events_unchanged=true and profile_snapshots_unchanged=true in retry and recovery scenarios.",
            "tests/test_f2_resource_generation_protocol.py::test_demo_execution_archives_nine_resources_and_does_not_create_learning_evidence verifies zero event/profile growth.",
        ],
    ),
    "G21-R10": related(
        "完整资源历史和自定义知识点生成仍由F5-T07负责；F5-T02只保留本次job的attempt_history与成功资源版本身份，不把两类历史混为一谈。",
        [
            "tests/test_f2_resource_generation_protocol.py::test_nine_type_job_idempotency_partial_retry_and_owner_boundary verifies item retry increments attempt_history while the successful handout remains unchanged.",
            "tests/test_f2_resource_generation_protocol.py::test_resource_revision_compare_restore_and_source_withdrawal protects the separate resource-version protocol.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G21-R11": related(
        "学习中的即时练习只以quiz/测验题资源归档，本任务没有增加'学习中练习'或第三个测评中心模块。",
        [
            "tests/test_f5_t02_resource_bundle_workspace.py::test_student_workspace_contract_uses_nine_items_and_no_engineering_metadata requires '测验题资源'.",
            "The final F1/F4 regression set passed, including assessment routing and exam-gate protection.",
        ],
    ),
    "G21-R13": related(
        "九项资源归档与智能组卷门禁保持分离；生成成功不是学习完成，也不会解锁组卷。",
        [
            "ResourceBundleWorkspace.vue explicitly states '生成完成不等于学习完成' and provides no manual completion control.",
            "tests/test_f4_exam_gate.py passed and the E2E report proves path nodes and learning events remain unchanged after all nine artifacts are generated.",
        ],
    ),
    "G22-R01": related(
        "F5-T02消费已存在的合法课程、画像快照和路径知识点，不绕过F3为新学生创建虚构画像或路径。",
        [
            "app/resource_bundles.py requires owner-scoped course, profile_snapshot_id and knowledge_point_id before creating the job.",
            "tests/test_f5_t02_resource_bundle_workspace.py seeds and verifies the same persisted profile snapshot; the job does not create another profile snapshot.",
        ],
    ),
    "G22-R02": related(
        "知识点由F4今日路径任务提供，F5-T02只冻结并消费它，不重新推荐、不改路径。",
        [
            "LearningPathGraph.vue builds the request from selectedTodayTask/selected generation context and passes task.node_id.",
            f"{REPORT}: path_nodes_unchanged=true in both scenarios and the displayed knowledge point remains '混合检索与重排'.",
        ],
    ),
    "G22-R04": related(
        "每项显示自己的完成条件，但生成、刷新和打开均不产生完成事件；真实完成仍由后续资源学习页和F4聚合处理。",
        [
            "ResourceBundleWorkspace.vue renders completion_rule and contains no completion mutation button.",
            f"{REPORT}: learning events and path nodes are unchanged before and after generation, retry and recovery.",
        ],
    ),
    "G22-R05": related(
        "F5-T02只提供学习材料，不修改F4-T05对今日必做证据的组卷门禁。",
        [
            "tests/test_f4_exam_gate.py passed in the final 42-test regression set.",
            "The resource-bundle completed state returns to today's task or resource center and never links directly to an unlocked exam.",
        ],
    ),
    "G22-R06": related(
        "资源生成只读画像和路径上下文，不创建新画像快照、不重排下一日计划；正式测评反馈仍由F6-T06负责。",
        [
            f"{REPORT}: profile_snapshots_unchanged=true and path_nodes_unchanged=true in retry and recovery scenarios.",
            "tests/test_f2_resource_generation_protocol.py::test_demo_execution_archives_nine_resources_and_does_not_create_learning_evidence verifies no profile snapshot growth.",
        ],
    ),
    "G22-R07": related(
        "本任务不提前重构错题、复习或笔记，但为每个产物保存课程、知识点、来源、画像和任务身份，供F8及资源中心继续追溯。",
        [
            "tests/test_f2_resource_generation_protocol.py verifies archived resource source_refs, profile_snapshot_id and creating task identity.",
            "tests/test_fusion_f0_f1_contract.py::test_protected_pages_follow_their_current_phase_contracts passed, preserving notes and wrong-question capabilities.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G22-R08": related(
        "动态问题与对话显式触发由F7-T04负责；当前创建API不监听聊天或普通页面活动，未来入口可复用同一协议。",
        [
            "app/resource_bundles_api.py has an explicit POST create endpoint and no automatic chat-event subscriber.",
            "tests/test_f5_t02_resource_bundle_workspace.py::test_generation_context_ignores_non_evidence_browsing_events proves ordinary browsing does not enter generation context as evidence.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G22-R10": related(
        "失败重试历史只描述生成attempt；资源版本编辑、比较、恢复和自定义生成仍由F5-T07统一呈现。",
        [
            "tests/test_f2_resource_generation_protocol.py::test_recovery_only_requeues_interrupted_items_and_preserves_successful_resource verifies retries preserve the successful resource ID.",
            "tests/test_f2_resource_generation_protocol.py::test_resource_revision_compare_restore_and_source_withdrawal remains green for the separate version lifecycle.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G22-R11": related(
        "资源包页面只展示课程、目标、画像适配、掌握、近期学习、来源、业务状态和学生可理解的失败原因；不展示提示词、密钥、worker、lease、原始日志或私有推理。",
        [
            "tests/test_f5_t02_resource_bundle_workspace.py checks learner-safe context and forbids engineering metadata in the workspace.",
            f"{REPORT}: console_errors, http_errors, failed_requests and page_errors are empty; visual screenshots show only business-facing status.",
        ],
    ),
    "G22-R12": related(
        "F10聊天迁移明确不在本轮；F5-T02只为quiz和code_sandbox建立目标资源身份与深链，不删除旧聊天能力。",
        [
            "The F5-T02 modified-file list contains no chat migration file.",
            "ResourceBundleWorkspace.vue exposes separate '测验题资源' and '代码沙盒任务' rows using target learning-space routes.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G22-R13": related(
        "学生生成资源时直接使用团队预置来源；页面不要求上传教材、课件或课程大纲，来源不足时由后端诚实拒绝而非转嫁上传步骤。",
        [
            f"{REPORT}: both successful jobs use source_count=1 and the complete browser journey contains no course-material upload control.",
            "ResourceBundleWorkspace.vue only displays the frozen source count and no upload field.",
        ],
    ),
    "G22-R14": related(
        "F4总路径的一次显式动作创建同一job_id下的九项资源，随后统一进入资源包页；不逐项弹窗，也不在对话中展开完整产物。",
        [
            f"{REPORT}: one_generation_job=true, nine_generated_artifacts=true and each scenario lists all nine types.",
            "LearningPathGraph.vue creates one payload with nine items and immediately routes to ResourceBundle.",
        ],
    ),
    "G22-R15": related(
        "资源包页不把9/9归档展示成组卷解锁；完成态主动作仍是返回今日任务，由F4展示真实缺项和组卷门禁。",
        [
            "ResourceBundleWorkspace.vue progress note distinguishes generation from learning completion and its primary action is '返回今日任务'.",
            "tests/test_f4_exam_gate.py passed and E2E path nodes remain unchanged after 9/9 generation.",
        ],
    ),
    "G22-R16": related(
        "现有partial_success、单项retry、interrupted recover、cancel和attempt_history协议被完整复用；成功项不会因其他项失败或服务重启被清空。",
        [
            "tests/test_f2_resource_generation_protocol.py::test_nine_type_job_idempotency_partial_retry_and_owner_boundary verifies partial success and failed-item attempt 2.",
            "tests/test_f2_resource_generation_protocol.py::test_recovery_only_requeues_interrupted_items_and_preserves_successful_resource verifies successful identity preservation.",
            f"{REPORT}: single-item retry and service-restart recovery pass with nine final artifacts, zero unexpected errors and intact SQLite databases.",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F5-T02_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F5-T02 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F5-T02")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T02",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F5-T02 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F5-T02 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
