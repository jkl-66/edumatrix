#!/usr/bin/env python3
"""Finalize F6-T03's per-atom implementation and verification evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "原系统融合重构执行"
CONTEXT_ROOT = OUTPUT / "evidence" / "context_recovery"
LEDGER_DIR = CONTEXT_ROOT / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
REPORT = "outputs/原系统融合重构执行/evidence/f6_t03_code_sandbox/evidence_summary.md"
FOCUSED = "tests/test_f6_t03_code_sandbox_resource.py (7 passed)"
REGRESSION = (
    "F2 learning-event, F4 path/exam gates, F5 resource workspaces/history and F6 quiz/model/sandbox "
    "regression selection (69 passed)"
)
E2E = (
    "scripts/e2e_f6_t03_code_sandbox.py; "
    "outputs/原系统融合重构执行/evidence/f6_t03_code_sandbox/report.json; "
    "4 screenshots at 1440x900 and 1366x768"
)
BUILD = "frontend: npm run build (6926 modules transformed; existing/Monaco large-chunk warning only)"
VISUAL = "Impeccable detector returned []; representative screenshots passed bounded manual visual review"
DATABASE = "isolated f6_t03.sqlite3: integrity ok, 0 foreign-key violations, 1 completion event, 3 resource versions and 1 run artifact"


def primary(
    implementation: list[str],
    verification: list[str],
    visible: str,
    rationale: str,
) -> dict[str, object]:
    return {
        "status": "IMPLEMENTED_AND_VERIFIED",
        "implementation_evidence": implementation,
        "verification_evidence": verification,
        "user_visible_result": visible,
        "compatibility_or_defer_rationale": rationale,
    }


def related(
    implementation: list[str],
    verification: list[str],
    visible: str,
    rationale: str,
) -> dict[str, object]:
    return {
        "status": "COORDINATION_VERIFIED",
        "implementation_evidence": implementation,
        "verification_evidence": verification,
        "user_visible_result": visible,
        "compatibility_or_defer_rationale": rationale,
    }


REALIZATION = {
    "G16-R01": primary(
        [
            "frontend/src/views/CodeSandboxWorkspace.vue mounts a local Monaco Python editor, editable standard input and save/run actions on the formal resource route.",
            "app/code_sandbox.py prepares and executes the exact current resource version through a real local Python subprocess rather than returning fixture output.",
        ],
        [FOCUSED, E2E, BUILD],
        "学生可以直接修改当前资源代码和标准输入，保存版本后运行并看到由修改后代码产生的结果。",
        "F6-T03 owns editing and execution; AI review generation remains in F6-T04 and does not replace the real run path.",
    ),
    "G16-R02": primary(
        [
            "LocalPythonExecutor captures stdout, stderr, exit status and Matplotlib figures into a persisted run artifact.",
            "CodeSandboxWorkspace.vue exposes separate output, error and plot tabs bound to the selected runAttemptId.",
        ],
        [FOCUSED, f"{E2E}; the real run prints validation metrics and renders one captured plot.", DATABASE],
        "每次运行都显示真实标准输出；异常显示完整错误摘要；绘图代码在图表标签中显示实际生成图片。",
        "F6-T03 does not fabricate output when execution fails; it preserves the code and reports the actual terminal state.",
    ),
    "G16-R06": primary(
        [
            "CodeSandboxWorkspace.vue uses grid-template-columns: 22fr 50fr 28fr for task/history, editor/input and result/review responsibilities.",
            "The formal route is rendered inside the existing student application shell without a second global navigation system.",
        ],
        [BUILD, VISUAL, f"{E2E}; both viewports measure 0.22/0.50/0.28."],
        "左栏查看任务、检查点和运行历史，中栏编辑代码与标准输入，右栏查看运行结果、检查和点评入口。",
        "Detailed AI review content is intentionally absent until F6-T04; the third-column review tab keeps its reserved, evidence-bound location.",
    ),
    "G16-R07": primary(
        [
            "app/code_sandbox.py implements queued, running, stopping, stopped, timeout, runtime_error and success states with a bounded timeout.",
            "Windows execution uses a new process group and taskkill tree cleanup for stop and timeout paths; the frontend polls and exposes run/stop controls.",
        ],
        [f"{FOCUSED}; timeout and user-stop tests pass with final persisted states.", f"{E2E}; run controls and stable result states are visible."],
        "运行中可点击停止；超时、用户停止、运行错误和成功都有明确状态，代码与输入不会因失败丢失。",
        "This is process lifecycle control for a real local operation, not a speculative fallback or background self-healing loop.",
    ),
    "G16-R08": primary(
        [
            "The runner stores stdout and stderr independently and applies deterministic head-tail truncation metadata only after the configured byte limit.",
            "Plots are persisted separately from terminal text, and the frontend explains capture or truncation rather than silently dropping results.",
        ],
        [f"{FOCUSED}; large-output head/tail, stderr and plot capture tests pass.", E2E],
        "输出、错误和图表互不覆盖；大输出保留开头和结尾并明确显示截断原因，核心检查结果仍可核验。",
        "The local research-mode output limit remains necessary to prevent the page and persisted artifact from being overwhelmed by unbounded output.",
    ),
    "G16-R10": primary(
        [
            "LocalPythonExecutor runs the bundled Python interpreter directly and requires no Docker installation for the prepared demonstration task.",
            "The resource projection and page display the explicit local research-mode boundary and supported Python runtime before execution.",
        ],
        [FOCUSED, E2E],
        "评委无需 Docker 即可运行预置 Python 示例，同时页面明确说明本地研究模式不具备容器隔离。",
        "The task does not claim secure execution of untrusted code; Docker-grade isolation is outside the approved local competition demonstration scope.",
    ),
    "G16-R11": primary(
        [
            "complete_run_learning accepts only a success run for the current resource version with every required check passed, then records code_tests_passed.",
            "m5_resources.py projects completion only when the event payload resource_version_id matches the current saved version.",
        ],
        [f"{FOCUSED}; explicit completion, idempotency, failed-run rejection and old-version evidence isolation all pass.", f"{E2E}; completion creates exactly one event and refresh restores it."],
        "打开页面不会完成学习；只有当前保存版本真实运行并通过全部必需检查后，“完成学习”才可用。保存新版本后必须重新运行。",
        "Completion uses the shared learning-event and path-consumption protocols; no second mastery or progress store was added.",
    ),
    "G16-R12": primary(
        [
            "Code sandbox keeps its own code_sandbox artifact type, f6.code-sandbox.v1 schema and /workspace/code/:resourceId route.",
            "TrainingTaskWorkspace and InteractiveLabWorkspace retain separate artifact schemas, routes, completion rules and evidence types.",
        ],
        [REGRESSION, f"{E2E}; the code resource opens through its own formal deep link."],
        "实训任务书负责工程说明，可交互模型负责调参与观察，代码沙盒单独负责编辑、运行、调试和完成检查。",
        "The three resources share course/source links but are not merged into one page or one completion event.",
    ),
    "G16-R03": related(
        [
            "CodeSandboxWorkspace.vue binds the review tab to the selected real runAttemptId and displays an honest empty state instead of static review prose.",
            "The persisted run artifact already contains the code, input, stdout and stderr required by F6-T04.",
        ],
        [FOCUSED, E2E],
        "学生运行后可以确认点评将基于哪一次真实运行；当前不会看到伪造的问题、风险或改进建议。",
        "Real AI review generation and its issue/risk/improvement sections are uniquely owned by F6-T04.",
    ),
    "G16-R04": related(
        [
            "F6-T03 preserves a dedicated evidence-bound review surface without inventing a focus value or sending course/run data externally.",
        ],
        [f"{E2E}; external_model_called is false and the review surface cites a real runAttemptId."],
        "当前页面不会假装已接收点评重点；该输入将在真实点评能力接入时出现。",
        "The user-specified review focus belongs to F6-T04 because it changes the model request contract, not code execution.",
    ),
    "G16-R05": related(
        [
            "The editor, version save and rerun actions are complete, so F6-T04 can apply a reviewed code revision as a new version and rerun it through the same executor.",
        ],
        [FOCUSED, REGRESSION],
        "学生现在已经能够保存任意修改并再次真实运行；系统尚不把不存在的 AI 建议自动写入代码。",
        "Applying review suggestions and comparing the follow-up run requires F6-T04's real review result and is deliberately deferred.",
    ),
    "G16-R09": related(
        [
            "The right column reserves a distinct AI review tab while keeping output, error and plots available as the evidence source.",
            "No placeholder problem, risk, improved-code or recommendation text is persisted or displayed as if model-produced.",
        ],
        [VISUAL, E2E],
        "点评区域位置清晰且不会遮挡真实输出；在没有真实点评前只显示可理解的等待说明。",
        "Problem location, review focus, risk, improved code and application advice are the exact F6-T04 deliverables.",
    ),
    "G26-R01": related(
        [
            "Generated code-sandbox resources require a published course, knowledge point and frozen DBSourceRef identifiers from the prepared AI/ML course context.",
        ],
        [FOCUSED, f"{E2E}; the page shows the prepared course and source context without an upload prerequisite."],
        "代码任务直接使用团队预置的 AI/ML 课程与来源，学生无需先上传课程材料。",
        "Knowledge-base bookshelf construction and source admission remain owned by F7; F6-T03 consumes the frozen source contract.",
    ),
    "G26-R02": related(
        [
            "The prepared resource is an AI/ML engineering task about classifier threshold calibration, validation accuracy and confusion-matrix evaluation.",
        ],
        [FOCUSED, E2E],
        "学生运行的是人工智能/机器学习工程场景的分类阈值与责任评估任务。",
        "F6-T03 does not claim arbitrary-domain code generation; the approved primary domain remains AI/ML engineering skills.",
    ),
    "G26-R03": related(
        [
            "The code resource turns the current knowledge point into an executable task with input, metrics, required checks and a plot rather than another reading-only artifact.",
        ],
        [FOCUSED, E2E],
        "学生把分类阈值理论落实为可运行代码、指标计算、混淆矩阵和图表检查。",
        "Quiz and interactive-model evidence remain separate; code execution contributes its own code_tests_passed evidence only after explicit completion.",
    ),
    "G26-R04": related(
        [
            "The prepared task covers data arrays, threshold-based model decision logic, validation metrics, confusion-matrix output and visualization.",
            "Linked training-task and interactive-model resources remain available for the broader engineering steps that do not belong inside the code runner.",
        ],
        [REGRESSION, E2E],
        "学生能够修改决策阈值、重新评估结果、定位错误并比较图表变化。",
        "Full data preparation, model selection and training workflows require their own generated training tasks; F6-T03 implements the executable evaluation slice without overstating coverage.",
    ),
    "G26-R05": related(
        [
            "resource_bundles.py archives code_sandbox as one of the nine generated resource types with a canonical route and exact course/path context.",
            "Completion evidence references the exact resource version and is consumed by the existing path event processor.",
        ],
        [REGRESSION, E2E],
        "今日知识点生成的代码任务进入学习空间，完成后沿统一事件协议回流路径与任务状态。",
        "The path remains the source of task assignment and gating; the sandbox does not create a parallel plan or directly rewrite mastery.",
    ),
    "G26-R06": related(
        [
            "The sandbox resource contains runtime requirements, ordered checkpoints, expected results, required checks and explicit error states.",
            "TrainingTaskWorkspace retains submission artifacts and the complete scoring rubric rather than duplicating them inside the executor.",
        ],
        [REGRESSION, E2E],
        "代码页清楚显示环境边界、操作检查点、真实结果、错误和完成条件，并可跳转理解关联工程任务。",
        "Submission deliverables and the 100-point scoring standard are uniquely owned by F5-T05's training task; F6-T03 verifies executable checks.",
    ),
    "G26-R07": related(
        [
            "Training task, code sandbox and interactive model preserve separate schemas, routes, UIs and evidence types while sharing course and source references.",
        ],
        [REGRESSION, f"{E2E}; the sandbox formal route remains distinct and functional."],
        "学生先看任务书理解工程目标，在代码沙盒实际实现和运行，再用交互模型观察参数规律，三者职责清楚。",
        "The resources cooperate through common context and deep links, not by collapsing their responsibilities into one oversized workspace.",
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T03_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T03 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in REALIZATION]
    extra = [atom_id for atom_id in REALIZATION if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic realization mismatch: missing={missing}, extra={extra}")
    for entry in ledger["entries"]:
        entry["realization"] = REALIZATION[entry["atomic_requirement_id"]]

    primary_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"] if entry["role"] == "primary"]
    related_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"] if entry["role"] == "related"]
    batch = {
        "id": "F6-T03-B01",
        "status": "VERIFIED",
        "direct_atoms": primary_ids,
        "related_atoms": related_ids,
        "files": [
            "app/m5_resources.py",
            "app/resource_bundles.py",
            "app/code_sandbox.py",
            "app/code_sandbox_api.py",
            "app/main.py",
            "frontend/package.json",
            "frontend/package-lock.json",
            "frontend/src/api/codeSandbox.js",
            "frontend/src/views/CodeSandboxWorkspace.vue",
            "frontend/src/router/index.js",
            "tests/test_f6_t03_code_sandbox_resource.py",
            "scripts/e2e_f6_t03_code_sandbox.py",
        ],
        "interfaces": [
            "GET /api/v1/m5/resources/{artifact_id}",
            "POST /api/v1/m5/resources/{artifact_id}/versions",
            "GET /api/v1/m5/resources/{artifact_id}/compare",
            "POST /api/v1/m5/resources/{artifact_id}/restore",
            "POST /api/v1/code-sandbox/runs",
            "GET /api/v1/code-sandbox/runs/{run_id}",
            "POST /api/v1/code-sandbox/runs/{run_id}/stop",
            "POST /api/v1/code-sandbox/runs/{run_id}/complete",
        ],
        "states": [
            "ready", "saved_version", "queued", "running", "stopping", "success",
            "runtime_error", "timeout", "stopped", "output_truncated", "plot_captured",
            "checks_passed", "completion_recorded", "current_version_incomplete", "history_restored",
            "review_waiting_for_f6_t04",
        ],
        "verification": [
            FOCUSED,
            REGRESSION,
            BUILD,
            E2E,
            DATABASE,
            VISUAL,
            "python -m py_compile on F6-T03 Python impact files",
            "git diff --check",
        ],
        "protection_contracts": [
            "opening, browsing, editing and saving code do not create mastery evidence",
            "only explicit completion of a current-version run passing every required check creates code_tests_passed",
            "old-version completion evidence cannot complete a newly saved or restored version",
            "Artifact/ArtifactVersion remains the resource, run-artifact and history source of truth",
            "training task, code sandbox and interactive model remain separate resources",
            "external model calls are absent and AI review remains an honest F6-T04 boundary",
            "all E2E and fault tests use isolated SQLite and never modify the formal database",
        ],
        "evidence_summary": REPORT,
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T03")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T03",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F6-T03 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F6-T03 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
