#!/usr/bin/env python3
"""Populate and validate F5-T05's per-atom realization evidence."""

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
REPORT = "outputs/原系统融合重构执行/evidence/f5_t05_training_task/report.json"
FOCUSED_TESTS = "tests/test_f5_t05_training_task_workspace.py"


def primary(
    user_visible_result: str,
    implementation_evidence: list[str],
    verification_evidence: list[str],
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
    "G26-R03": primary(
        "学生打开实训任务书后能从课程理论直接进入一项可执行的 AI/ML 工程任务，并通过独立入口继续到代码沙盒或可交互模型；阅读本身不会伪造技能证据。",
        [
            "app/resource_bundles.py:_deterministic_demo_content converts the current knowledge point into an engineering objective, executable steps and linked execution resources.",
            "frontend/src/views/TrainingTaskWorkspace.vue renders the engineering document and separate code-sandbox/model actions while stating the evidence boundary.",
        ],
        [
            f"{FOCUSED_TESTS}::test_deterministic_demo_generates_complete_ai_ml_training_task verifies the theory-to-engineering task conversion.",
            f"{REPORT}: sandbox_link/model_link resolve, learning_state_before equals learning_state_after, and the 1366x768 primary action is keyboard-focusable.",
        ],
    ),
    "G26-R04": primary(
        "学生会看到数据检查、模型与指标选择、真实训练、评估诊断和改进四个连续工程阶段，每步同时说明预期结果与故障处理。",
        [
            "app/resource_bundles.py emits four knowledge-point-scoped AI/ML steps covering data, model/metric choice, training, evaluation, diagnosis and improvement.",
            "frontend/src/views/TrainingTaskWorkspace.vue renders every step with expectedResult and errorGuidance instead of a generic checklist.",
        ],
        [
            f"{FOCUSED_TESTS}::test_deterministic_demo_generates_complete_ai_ml_training_task asserts the exact four-stage AI/ML task sequence and profile-dependent content.",
            f"{REPORT}: structured-current screenshots at both desktop sizes contain the generated task stages without clipping or console errors.",
        ],
    ),
    "G26-R06": primary(
        "每份结构化任务书完整展示前置条件、运行环境、数据、步骤、预期结果、错误处理、检查点、提交物和总分 100 分的评分标准；格式损坏时明确指出缺项并允许重试。",
        [
            "app/training_tasks.py defines and validates the complete f5.training-task.v1 execution contract, checkpoint references, unique IDs and a 100-point rubric.",
            "frontend/src/views/TrainingTaskWorkspace.vue provides navigable preparation, steps, checkpoints, deliverables and rubric sections plus loading, invalid, legacy and retryable failure states.",
        ],
        [
            f"{FOCUSED_TESTS}::test_training_task_schema_requires_complete_execution_contract rejects invalid checkpoint links and incomplete rubric totals.",
            f"{FOCUSED_TESTS}::test_legacy_lab_guide_and_invalid_json_are_preserved_honestly verifies honest legacy and invalid projections.",
            f"{REPORT}: 9 screenshots cover current, rubric, historical, legacy, invalid, injected 503 and recovered states with zero clipping/collisions/small text.",
        ],
    ),
    "G26-R07": primary(
        "右侧把实训任务书、代码沙盒和可交互模型清楚区分：任务书负责说明，沙盒负责真实运行，模型负责参数实验；不可用的历史关联会被禁用而不是伪装可用。",
        [
            "app/m5_resources.py:_training_task_link validates owner, course, resource type, archive state and current version before exposing either linked tool.",
            "frontend/src/views/TrainingTaskWorkspace.vue renders the sandbox as the primary execution action and the interactive model as a distinct secondary action with separate routes and descriptions.",
        ],
        [
            f"{FOCUSED_TESTS}::test_structured_training_task_projects_sources_and_distinct_linked_tools verifies distinct resource identities and routes.",
            f"{FOCUSED_TESTS}::test_cross_owner_or_wrong_type_link_is_not_exposed_as_available verifies unsafe links are disabled.",
            f"{REPORT}: linked_resource_visual_distinction records different foreground/background styles and unavailable_link.model_disabled is true for the historical version.",
        ],
    ),
    "G03-R01": related(
        "实训任务书仍是九类资源中的独立 training_task 项；代码沙盒、可交互模型、视频和课件保留独立类型与路由，任务书没有吞并其他资源。",
        [
            "app/resource_bundles.py keeps all nine GENERATION_RESOURCE_TYPES and assigns independent routes to training_task, code_sandbox, interactive_model, video and deck.",
            f"{FOCUSED_TESTS}::test_structured_training_task_projects_sources_and_distinct_linked_tools verifies only explicit linked tools are projected.",
        ],
        implementation_evidence=[
            "app/m5_resources.py maps training_task to its dedicated workspace while preserving sibling resource catalog identities.",
        ],
    ),
    "G03-R02": related(
        "任务内容读取统一生成清单中的课程、知识点、学习目标、画像适配、掌握摘要和最近学习证据；难度、支架及排错重点会随这些冻结输入变化。",
        [
            f"{FOCUSED_TESTS}::test_deterministic_demo_generates_complete_ai_ml_training_task verifies profile adaptation, mastery and recent evidence change the generated task.",
            "The focused F2 generation regression passes, preserving the frozen generation-context and source-snapshot contract.",
        ],
        status="COORDINATION_VERIFIED",
        implementation_evidence=[
            "app/resource_bundles.py:_deterministic_demo_content derives the task from _public_generation_context rather than fixed user-independent prose.",
        ],
    ),
    "G03-R03": related(
        "已关闭的高质量讲义没有被重做或降级；实训任务书使用工程执行文档的信息层级，避免文本墙，也没有复制讲义的阅读型结构。",
        [
            "The 18-test focused/protection regression includes the shared resource protocol and remains green without modifying HandoutWorkspace.vue.",
            f"{REPORT}: the task page exposes structured preparation, steps, checkpoints, deliverables and rubric with zero layout defects at both desktop sizes.",
        ],
    ),
    "G03-R04": related(
        "任务书只通过资源中心、资源包或稳定深链显式进入；页面加载、滚动、版本切换和来源查看都不会自动生成资源或写学习完成证据。",
        [
            f"{FOCUSED_TESTS}::test_frontend_contract_uses_dedicated_workspace_and_never_writes_learning_evidence rejects generation, completion, exam-unlock and profile-update calls from the page.",
            f"{REPORT}: unexpected_write_requests is empty and learning events, profile snapshots and path nodes are byte-identical before and after the full browser journey.",
        ],
    ),
    "G03-R05": related(
        "资源中心继续负责目录、搜索和归档；专用任务书页面读取同一 artifact/version 并可返回资源中心，没有建立第二套任务库。",
        [
            "frontend/src/router/index.js adds only /workspace/resources/training-tasks/:resourceId under the existing resource hierarchy.",
            "frontend/src/views/TrainingTaskWorkspace.vue loads getM5ResourceDetail(resourceId) and returns to WorkspaceResources with course context.",
        ],
        implementation_evidence=[
            "app/m5_resources.py:resource_detail projects current and historical DBArtifactVersion records into the dedicated read workspace.",
        ],
    ),
    "G03-R06": related(
        "F5-T05只完善九类资源包中的 training_task 内容和专用视图；其他八类的状态、重试、归档和完成规则保持 F5-T02 协议不变。",
        [
            "tests/test_f2_resource_generation_protocol.py and tests/test_m5_resources.py pass in the 18-test protection regression.",
            "app/resource_bundles.py still requires every GENERATION_RESOURCE_TYPES value exactly once and processes training_task as one independent item.",
        ],
    ),
    "G03-R07": related(
        "个性化讲义的高级阅读合同保持不变；实训任务书只消费统一课程来源和资源上下文，没有替换讲义内容、版本或导出路径。",
        [
            "F5-T05 changes do not modify frontend/src/views/HandoutWorkspace.vue or the handout schema.",
            "The production frontend build succeeds with both HandoutWorkspace and TrainingTaskWorkspace emitted as separate chunks.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G03-R08": related(
        "完整任务书、来源、版本和状态保存在统一资源对象中；路径或资源卡只负责打开深链，页面不会把全文复制进对话或另一个事实源。",
        [
            "app/m5_resources.py returns training_task.current and training_task.versions from persisted artifact versions.",
            f"{REPORT}: database_audit records stable task-version hashes while source and linked-resource navigation return to the same resource identity.",
        ],
        status="COORDINATION_VERIFIED",
        implementation_evidence=[
            "frontend/src/views/TrainingTaskWorkspace.vue renders the selected persisted projection and contains no chat-content replication path.",
        ],
    ),
    "G26-R01": related(
        "任务书直接使用团队预置、已冻结并可追溯的课程来源生成；学生进入页面不需要上传课程资料，来源缺失时只显示诚实未发布状态。",
        [
            f"{FOCUSED_TESTS}::test_structured_training_task_projects_sources_and_distinct_linked_tools verifies canonical source references and publishability.",
            f"{REPORT}: source_deep_link reaches the frozen course source and no upload action appears in any tested state.",
        ],
        status="COORDINATION_VERIFIED",
        implementation_evidence=[
            "app/m5_resources.py:_training_task_projection checks every structured citation against the persisted source_refs before allowing the task to be publishable.",
        ],
    ),
    "G26-R02": related(
        "当前任务书明确采用人工智能/机器学习工程语境，围绕当前知识点组织数据、模型、训练、指标、评估和排错，而不是通用待办模板。",
        [
            f"{FOCUSED_TESTS}::test_deterministic_demo_generates_complete_ai_ml_training_task verifies the AI/ML engineering stages for a gradient-descent knowledge point.",
            f"{REPORT}: structured screenshots display the AI/ML course and knowledge-point context without claims of real enterprise certification.",
        ],
        status="COORDINATION_VERIFIED",
    ),
    "G26-R05": related(
        "实训任务书由今日知识点的统一九类资源生成任务创建并归档，可从资源中心或总路径深链进入；后续沙盒和模型仍接在同一资源/课程上下文中。",
        [
            "app/resource_bundles.py creates training_task from the same generation manifest and links already generated code_sandbox and interactive_model artifacts by stable IDs.",
            f"{REPORT}: both linked routes work, while path_nodes and learning events remain unchanged until genuine execution evidence is produced.",
        ],
        status="COORDINATION_VERIFIED",
        implementation_evidence=[
            "frontend/src/views/TrainingTaskWorkspace.vue preserves course_id on return/source links and routes execution actions to sibling resources instead of creating a disconnected workflow.",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F5-T05_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F5-T05 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F5-T05")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T05",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F5-T05 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F5-T05 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
