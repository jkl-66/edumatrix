#!/usr/bin/env python3
"""Finalize F6-T04 per-atom implementation and verification evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "原系统融合重构执行"
CONTEXT_ROOT = OUTPUT / "evidence" / "context_recovery"
LEDGER_DIR = CONTEXT_ROOT / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
SUMMARY = "outputs/原系统融合重构执行/evidence/f6_t04_code_review/evidence_summary.md"
FOCUSED = "tests/test_f6_t04_code_review.py (5 passed)"
SANDBOX_REGRESSION = "tests/test_f6_t03_code_sandbox_resource.py (7 passed)"
REGRESSION = "F2/F4/F5/F6 related regression selection (107 passed)"
BUILD = "frontend npm run build (6928 modules transformed; existing large-chunk warning only)"
E2E = (
    "scripts/e2e_f6_t04_code_review.py; report.json status passed; five screenshots at "
    "1440x900 and 1366x768; runtime error -> review -> new version -> rerun -> history comparison"
)
VISUAL = "Impeccable detector returned []; bounded screenshot review found no material visual defect"
DATABASE = (
    "isolated f6_t04.sqlite3: integrity ok, 0 foreign-key violations, 4 resource versions, "
    "2 run artifacts, 1 review artifact and 0 completion events"
)


def realized(
    *,
    role: str,
    implementation: list[str],
    verification: list[str],
    visible: str,
    rationale: str,
) -> dict[str, object]:
    return {
        "status": "IMPLEMENTED_AND_VERIFIED" if role == "primary" else "COORDINATION_VERIFIED",
        "implementation_evidence": implementation,
        "verification_evidence": verification,
        "user_visible_result": visible,
        "compatibility_or_defer_rationale": rationale,
    }


REALIZATION = {
    "G16-R03": realized(
        role="primary",
        implementation=[
            "app/code_review.py accepts only success/runtime_error/timeout run artifacts and binds every review to the exact run, resource version, code hash, input/output/error hashes, exit code and failed checks.",
            "CodeReviewPanel.vue renders concrete findings and risks from that persisted evidence rather than placeholder prose.",
        ],
        verification=[FOCUSED, E2E, DATABASE],
        visible="学生只能对一条已经结束的真实运行生成点评，并能看到错误位置、运行证据和可核对的改进方向。",
        rationale="Queued, running, stopped, missing, stale and foreign runs remain ineligible; F6-T03 run snapshots are referenced without mutation.",
    ),
    "G16-R04": realized(
        role="primary",
        implementation=[
            "CodeReviewPanel.vue provides an optional bounded focus textarea and stable idempotency key derived from the run and focus.",
            "app/code_review.py sanitizes the focus before persistence and adds it as emphasis without changing the immutable run evidence.",
        ],
        verification=[FOCUSED, f"{E2E}; the learner focus is persisted and displayed."],
        visible="学生可以填写点评重点，也可以留空使用通用审阅；重点会显示在点评结果中。",
        rationale="The focus changes review emphasis only and cannot alter code, runtime output, source context or mastery evidence.",
    ),
    "G16-R05": realized(
        role="primary",
        implementation=[
            "apply_review creates a new current DBArtifactVersion with revision_origin=ai_code_review and preserves the source version and original run artifact.",
            "CodeSandboxWorkspace.vue reloads the applied resource version, reruns through the existing executor and retains both attempts in run history.",
        ],
        verification=[FOCUSED, SANDBOX_REGRESSION, E2E, DATABASE],
        visible="学生点击“应用建议并另存新版本”后得到新代码版本，可再次运行并在左侧历史比较原报错与新结果。",
        rationale="Application never overwrites a newer learner draft and review/apply/rerun alone never records learning completion.",
    ),
    "G16-R09": realized(
        role="primary",
        implementation=[
            "CodeReviewPanel.vue separates 问题定位、点评重点、潜在风险、改进代码 and 应用建议 into five explicit sections in the existing result column.",
            "The panel includes loading, unavailable, generating, failure, completed, applying and applied states plus progressive public audit disclosure.",
        ],
        verification=[FOCUSED, BUILD, E2E, VISUAL],
        visible="右栏点评内容按五个区块顺序呈现，学生先核对问题和风险，再决定是否应用改进代码。",
        rationale="The five sections stay subordinate to the real output/error/plot tabs and do not replace the completion action.",
    ),
    "G16-R01": realized(
        role="related",
        implementation=["F6-T04 reuses CodeSandboxWorkspace.vue, its Monaco editor and the existing startCodeSandboxRun path; no second editor or executor was added."],
        verification=[SANDBOX_REGRESSION, REGRESSION, E2E],
        visible="点评后的代码仍在原代码沙盒中编辑和运行，操作位置与 F6-T03 保持一致。",
        rationale="Editing and execution remain uniquely owned by the F6-T03 sandbox contract.",
    ),
    "G16-R02": realized(
        role="related",
        implementation=["Review evidence stores hashes and references for stdout, stderr, plots/checks and exit state while leaving the persisted run artifact unchanged."],
        verification=[FOCUSED, SANDBOX_REGRESSION, E2E],
        visible="输出、错误和图表仍在原标签查看；点评只引用本次运行证据，不覆盖真实结果。",
        rationale="Review is a derived artifact, not a replacement truth source for execution output.",
    ),
    "G16-R06": realized(
        role="related",
        implementation=["CodeReviewPanel is mounted inside the existing 28-percent result column and CodeSandboxWorkspace retains grid-template-columns: 22fr 50fr 28fr."],
        verification=[BUILD, f"{E2E}; both viewports measured 0.22/0.50/0.28.", VISUAL],
        visible="任务/历史、编辑器/输入和结果/点评三栏职责与比例保持稳定。",
        rationale="F6-T04 adds content to the reserved review surface without restructuring the sandbox.",
    ),
    "G16-R07": realized(
        role="related",
        implementation=["Review creation and application do not enter the runner lifecycle or alter stop, timeout, polling and process-tree cleanup code."],
        verification=[SANDBOX_REGRESSION, REGRESSION],
        visible="运行、停止、超时和错误处理继续独立工作，点评失败不会阻塞代码运行。",
        rationale="The review path operates only after eligible terminal evidence exists.",
    ),
    "G16-R08": realized(
        role="related",
        implementation=["The review records bounded output/error hashes and failed-check identifiers while existing head-tail truncation, stderr separation and plot storage remain unchanged."],
        verification=[SANDBOX_REGRESSION, FOCUSED],
        visible="大输出、错误和图表继续按原规则展示，点评能引用它们但不会把内容混成一段文本。",
        rationale="Bounded evidence references preserve traceability without duplicating unbounded terminal data.",
    ),
    "G16-R10": realized(
        role="related",
        implementation=["The review baseline is deterministic and local, and the existing trusted-local Python executor remains the only runtime."],
        verification=[f"{E2E}; external_model_called=false.", SANDBOX_REGRESSION],
        visible="评委无需 Docker 或外部模型即可演示运行与点评，页面同时明确本地研究模式边界。",
        rationale="No security or isolation claim was expanded; untrusted-code execution remains unsupported.",
    ),
    "G16-R11": realized(
        role="related",
        implementation=["create_review and apply_review write no DBLearningEvent; completion remains exclusively guarded by complete_run_learning and current-version required checks."],
        verification=[FOCUSED, SANDBOX_REGRESSION, DATABASE],
        visible="得到点评、应用建议或重跑都不会自动完成学习；仍需满足原完成规则并由学生主动提交。",
        rationale="The shared learning-event protocol remains the only mastery/completion path.",
    ),
    "G16-R12": realized(
        role="related",
        implementation=["The review artifact references one code_sandbox resource; training-task and interactive-model schemas, routes and evidence remain separate."],
        verification=[REGRESSION, FOCUSED],
        visible="代码点评只出现在代码沙盒，不会把实训任务书或可交互模型合并成同一资源。",
        rationale="Cross-resource context is referenced through existing IDs without collapsing resource responsibilities.",
    ),
    "G27-R01": realized(
        role="related",
        implementation=["Review creation derives owner, course and source resource context from the authenticated run and resource; it does not create a second profile snapshot or personalization store."],
        verification=[FOCUSED, REGRESSION],
        visible="点评使用当前学生、课程和代码任务上下文，不要求再次选择画像或上传资料。",
        rationale="Personalization remains frozen in the generated code resource; review adds no new learner evidence claim.",
    ),
    "G27-R02": realized(
        role="related",
        implementation=["app/code_review.py emits sanitized public Agent summaries for evidence inspection, improvement candidate and decision orchestration responsibilities."],
        verification=[FOCUSED, E2E],
        visible="学生可展开协作摘要，查看各角色如何读取证据、提出候选改进并形成最终建议。",
        rationale="The summary exposes responsibilities and decisions only, not private reasoning.",
    ),
    "G27-R03": realized(
        role="related",
        implementation=["Public Agent records include disagreement, validation and revision fields explaining why automatic changes stay conservative and why rerun evidence is required."],
        verification=[FOCUSED],
        visible="协作摘要会说明运行错误、静态风险和保守修订之间的分歧与取舍。",
        rationale="Disagreement is a concise audit statement, not hidden chain-of-thought.",
    ),
    "G27-R04": realized(
        role="related",
        implementation=["CodeReviewEvidenceRefs binds runAttemptId, resource/version IDs, code/input/stdout/stderr hashes, status, exit code and failed checks."],
        verification=[FOCUSED, E2E],
        visible="点评底部显示运行和错误哈希引用，后端保留完整证据绑定供复核。",
        rationale="Hash references support exact traceability while avoiding raw log duplication.",
    ),
    "G27-R05": realized(
        role="related",
        implementation=["The public Agent audit is an optional details disclosure below the actionable review sections and does not create a separate route or workflow."],
        verification=[BUILD, E2E, VISUAL],
        visible="学生先处理代码问题，需要时再展开协作摘要，不会被 Agent 日志淹没。",
        rationale="The learner's review, apply and rerun actions remain primary.",
    ),
    "G27-R06": realized(
        role="related",
        implementation=["agent_audit sanitization is applied to every public role record and the review focus; secrets, prompt fields, raw logs and private reasoning are rejected or redacted."],
        verification=[f"{FOCUSED}; secret and private-field sanitization assertions pass."],
        visible="页面只显示职责、输入引用、候选、分歧、校验、修订和决策摘要。",
        rationale="Private prompts, API keys, chain-of-thought and raw Agent logs remain forbidden.",
    ),
    "G27-R07": realized(
        role="related",
        implementation=["The shipped reviewer is deterministic_local with modelState=not_requested, and CodeReviewPanel explicitly states that no external model is called."],
        verification=[FOCUSED, E2E, DATABASE],
        visible="即使外部模型不可用，代码运行和本地证据点评仍可演示；页面不会伪装成外部模型结果。",
        rationale="External-model enhancement remains outside current authorization and cannot block the reliable local baseline.",
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T04_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T04 ledger, found {len(matches)}")
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
        "id": "F6-T04-B01",
        "status": "VERIFIED",
        "direct_atoms": primary_ids,
        "related_atoms": related_ids,
        "files": [
            "app/code_review.py",
            "app/code_sandbox_api.py",
            "frontend/src/api/codeSandbox.js",
            "frontend/src/components/CodeReviewPanel.vue",
            "frontend/src/views/CodeSandboxWorkspace.vue",
            "tests/test_f6_t04_code_review.py",
            "tests/test_f2_resource_generation_protocol.py",
            "scripts/e2e_f6_t04_code_review.py",
            "scripts/finalize_f6_t04_atomic_realization.py",
            SUMMARY,
        ],
        "interfaces": [
            "GET /api/v1/code-sandbox/resources/{resource_id}/reviews/latest",
            "POST /api/v1/code-sandbox/resources/{resource_id}/reviews",
            "GET /api/v1/code-sandbox/reviews/{review_id}",
            "POST /api/v1/code-sandbox/reviews/{review_id}/apply",
        ],
        "states": [
            "no_run", "running", "stopped", "eligible", "loading", "generating", "failed",
            "completed", "applying", "applied", "rerun_success", "history_compared",
        ],
        "verification": [
            FOCUSED,
            SANDBOX_REGRESSION,
            REGRESSION,
            BUILD,
            E2E,
            VISUAL,
            DATABASE,
            "python -m py_compile on F6-T04 Python impact files",
            "git diff --check",
        ],
        "protection_contracts": [
            "review requires one eligible terminal real run and exact evidence binding",
            "original code versions and run snapshots remain immutable",
            "applying advice creates a new resource version and rejects stale learner drafts",
            "review, application and rerun do not create mastery or completion evidence",
            "F6-T03 editor, executor, stop, timeout, output, plot and 22/50/28 contracts remain authoritative",
            "private prompts, secrets, chain-of-thought and raw Agent logs remain hidden",
            "no external model or formal database is used by verification",
        ],
        "evidence_summary": SUMMARY,
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T04")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T04",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F6-T04 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F6-T04 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
