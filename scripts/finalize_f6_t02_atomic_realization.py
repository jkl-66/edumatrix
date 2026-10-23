#!/usr/bin/env python3
"""Finalize F6-T02's per-atom implementation and verification evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "原系统融合重构执行"
CONTEXT_ROOT = OUTPUT / "evidence" / "context_recovery"
LEDGER_DIR = CONTEXT_ROOT / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
REPORT = "outputs/原系统融合重构执行/evidence/f6_t02_interactive_model/evidence_summary.md"
FOCUSED = "tests/test_f6_t02_interactive_model_resource.py and tests/test_next_interactive_lab.py (8 passed)"
REGRESSION = (
    "F4 path/profile/exam gates, F5 resource workspaces/history, F6 quiz/model and legacy video practice "
    "regression selection (68 passed)"
)
E2E = (
    "scripts/e2e_f6_t02_interactive_model.py; "
    "outputs/原系统融合重构执行/evidence/f6_t02_interactive_model/report.json; "
    "7 screenshots at 1440x900 and 1366x768"
)
BUILD = "frontend: npm run build (6222 modules transformed)"
VISUAL = "Impeccable detector returned []; every screenshot reports zero overflow, collision, clipping, small text, forbidden effects and forbidden colors"
DATABASE = "isolated f6_t02.sqlite3: integrity ok, 0 foreign-key violations, 1 observation event and 3 resource versions"


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
    "G03-R01": related(
        [
            "app/resource_bundles.py generates the interactive_model resource type with strict f6.interactive-model.v1 content.",
            "frontend/src/router/index.js and InteractiveLabWorkspace.vue provide /workspace/resources/models/:resourceId as a dedicated workspace.",
        ],
        [FOCUSED, f"{E2E}; formal resource screenshots show the dedicated model workspace."],
        "学生在讲义、思维导图、课件等既有资源之外，可以单独打开可交互模型并运行参数实验。",
        "PPT/网页课件继续由 F5-T06 的独立资源页负责；F6-T02 只实现可交互模型，不合并两种产物。",
    ),
    "G03-R02": related(
        [
            "resource_bundles.py freezes course, knowledge point, profile adaptation, mastery summary, recent events and source references into generated model content.",
            "interactive_lab.py binds each instance to the exact resource version and its profile/source context.",
        ],
        [FOCUSED, f"{E2E}; the page shows frozen profile adaptation and course source context."],
        "模型标题、目标、参数实验和观察问题均来自当前课程知识点与生成时画像，而不是通用固定页面。",
        "画像与掌握度的权威更新仍由统一学习事件聚合器负责；模型页面只消费冻结快照并提交有效观察证据。",
    ),
    "G03-R03": related(
        [
            "InteractiveLabWorkspace.vue uses a stable parameter/result/observation three-column desktop composition with chart, metrics and progressive detail.",
            "The visual implementation follows the fog-white, white-surface and dark-ink F1 token contract with Source Han typography and 14px minimum visible text.",
        ],
        [BUILD, VISUAL, E2E],
        "学生首先看到参数、结果曲线和观察结论，来源与画像适配保持在右侧，不会面对单一长文本墙。",
        "本原子主责的讲义排版仍由 F5-T03 保留；F6-T02 只验证交互模型也遵守同一专业易读标准。",
    ),
    "G03-R04": related(
        [
            "The formal model page creates an experiment only after the learner clicks 开始实验.",
            "Browsing, opening history and changing local sliders do not auto-create evidence or interrupt with unrelated dialogs.",
        ],
        [f"{E2E}; initial browse and slider edits leave observation event count at 0."],
        "打开资源只显示可操作工作区；只有点击开始实验才创建实例，页面没有无关生成弹窗。",
        "完整九类资源生成意图继续由 F5-T02 的资源包动作拥有，本页不重复触发整包生成。",
    ),
    "G03-R05": related(
        [
            "m5_resources.py projects the canonical catalog route, current version and complete version history from Artifact/ArtifactVersion.",
            "ResourceHistoryDrawer supports read-only selection, comparison and restore-as-new-version.",
        ],
        [FOCUSED, f"{E2E}; restoring v1 creates v3 while preserving all three versions.", DATABASE],
        "生成后的可交互模型可从资源中心再次打开，刷新恢复实验状态，并查看、比较或恢复历史版本。",
        "统一资源中心和版本事实源由 F5 共享协议负责；F6-T02 复用而不创建第二套历史表。",
    ),
    "G03-R06": related(
        [
            "resource_bundles.py keeps interactive_model as one of the nine independently archived bundle item types.",
            "The model resource has its own route, schema, completion rule and evidence type.",
        ],
        [REGRESSION, f"{E2E}; the model item opens through its formal resource deep link."],
        "一键资源包中的可交互模型有正式归档位置，并与其他八类资源分别打开和恢复。",
        "其他八类资源由各自 F5/F6 任务负责；本任务不复制讲义、沙盒、测验或费曼功能。",
    ),
    "G03-R07": related(
        [
            "F6-T02 leaves HandoutWorkspace and the f5.handout.v1 schema untouched.",
            "The model resource uses its own structured projection and cannot replace or masquerade as a handout.",
        ],
        [f"{REGRESSION}; F5-T03 handout workspace tests remain green."],
        "个性化讲义的完整高质量页面继续可用，可交互模型仅作为独立实验资源出现。",
        "本原子的主责实现已在 F5-T03；F6-T02 只证明新增模型能力没有削弱或混淆讲义。",
    ),
    "G03-R08": related(
        [
            "Interactive model content, instances, runs, observations and history persist in Artifact/ArtifactVersion rather than a chat message.",
            "The dedicated route restores state after refresh and exposes source/version identity.",
        ],
        [FOCUSED, f"{E2E}; refresh restores completion and the submitted observation.", DATABASE],
        "完整实验产物保存在学习空间资源页，重新进入仍能看到参数、结果、观察结论、来源和版本。",
        "智能对话只承担资源深链和紧凑入口；本任务没有把完整模型工作区嵌入聊天记录。",
    ),
    "G26-R01": related(
        [
            "Generated model resources require a published course, knowledge point and frozen DBSourceRef identifiers.",
            "The browser fixture uses the prepared demo-course-rag-trust-v1 knowledge base and demo-ref-07 source.",
        ],
        [FOCUSED, f"{E2E}; the page displays the frozen dataset and one traceable course source."],
        "学生运行的是绑定预置课程知识库来源的模型实验，不需要先上传自己的课程材料。",
        "知识库书架、许可和文档准入仍由 F7 负责；F6-T02 只消费已冻结的合法课程来源。",
    ),
    "G26-R02": related(
        [
            "The generated template is selected from AI/ML concepts such as hybrid retrieval tuning or classifier threshold calibration.",
            "Course and knowledge-point metadata remain attached to both the resource version and experiment instance.",
        ],
        [FOCUSED, f"{E2E}; screenshots show RAG application and responsible-evaluation course context."],
        "可交互模型围绕人工智能与机器学习工程中的混合检索或分类阈值进行参数探索。",
        "本任务不宣称泛化到任意专业；主领域继续固定为批准的 AI/ML 工程技能。",
    ),
    "G26-R03": related(
        [
            "interactive_lab.py deterministically computes result curves and metrics from validated parameters.",
            "A valid written observation binds parameters, metrics, source version and course context into one mastery-eligible event.",
        ],
        [FOCUSED, f"{E2E}; run creates no event and valid observation creates exactly one event."],
        "学生不只阅读理论，还能调参、比较曲线与指标，并用自己的观察结论形成可验证学习证据。",
        "正式测验与代码执行仍有独立证据类型；模型观察不会伪装成答题或代码运行成绩。",
    ),
    "G26-R04": related(
        [
            "The RAG template exposes keyword/vector weighting, recall count and rerank threshold with deterministic quality and latency outcomes.",
            "The classifier template exposes threshold, abstention and calibration parameters through the preserved legacy mode.",
        ],
        [FOCUSED, f"{E2E}; both formal RAG tuning and two legacy AI/ML templates remain reachable."],
        "学生可以观察检索、重排、分类阈值和校准等工程参数如何影响质量与延迟。",
        "数据处理、完整训练与排错任务由实训任务书和代码沙盒承载；交互模型专注可解释参数规律。",
    ),
    "G26-R05": related(
        [
            "resource_bundles.py creates the model from the current resource-generation job and assigns a canonical resource route.",
            "Completion evidence references the exact resource/version so the existing path aggregator can consume it.",
        ],
        [REGRESSION, f"{E2E}; the resource is generated, archived, completed and re-opened through its deep link."],
        "今日知识点生成资源包后，可交互模型进入对应资源空间；完成观察后通过统一事件回流既有学习闭环。",
        "路径安排和智能组卷门禁仍由 F4 聚合器判断，模型页面不直接改写路径或解锁状态。",
    ),
    "G26-R06": related(
        [
            "The page exposes frozen dataset context, server-validated constraints, observation steps, computed results, honest errors and a completion rule.",
            "Injected run and submit failures preserve parameter and observation drafts for recovery.",
        ],
        [FOCUSED, f"{E2E}; both injected 503 recovery branches pass without evidence writes."],
        "模型实验明确展示数据、参数约束、运行结果、错误恢复、观察提交条件和完成状态。",
        "完整工程环境、逐步检查点、提交物和 100 分评分表属于 F5-T05 实训任务书；模型页不重复其职责。",
    ),
    "G26-R07": related(
        [
            "Training tasks, code sandboxes and interactive models retain separate artifact types, routes and completion evidence.",
            "frontend/src/router/index.js keeps the formal model route and repairs /interactive-lab as a direct compatibility workspace without fake resource resolution.",
        ],
        [REGRESSION, f"{E2E}; the formal resource and legacy compatibility route both pass at desktop size."],
        "学生能分清任务书负责说明、沙盒负责写和运行代码、交互模型负责调参与观察；旧实验入口仍可使用。",
        "三类资源通过课程与来源关联协同，但不共享伪造的运行结果、完成条件或证据类型。",
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T02_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T02 ledger, found {len(matches)}")
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
        "id": "F6-T02-B01",
        "status": "VERIFIED",
        "direct_atoms": [],
        "related_atoms": actual_ids,
        "files": [
            "app/m5_resources.py",
            "app/resource_bundles.py",
            "app/interactive_lab.py",
            "app/interactive_lab_api.py",
            "frontend/src/views/InteractiveLabWorkspace.vue",
            "frontend/src/router/index.js",
            "tests/test_f6_t02_interactive_model_resource.py",
            "scripts/e2e_f6_t02_interactive_model.py",
        ],
        "interfaces": [
            "GET /api/v1/m5/resources/{artifact_id}",
            "POST /api/v1/m5/resources/{artifact_id}/versions",
            "GET /api/v1/m5/resources/{artifact_id}/compare",
            "POST /api/v1/m5/resources/{artifact_id}/restore",
            "GET/POST /api/v1/interactive-lab/instances",
            "POST /api/v1/interactive-lab/instances/{instance_id}/actions",
        ],
        "states": [
            "ready", "local_parameter_draft", "creating", "configured", "evaluated",
            "hinted", "run_failed_preserve_draft", "submit_failed_preserve_observation",
            "passed", "refresh_restored", "historical_readonly", "history_restore_as_new",
            "invalid_structured", "legacy_compatibility",
        ],
        "verification": [FOCUSED, REGRESSION, BUILD, E2E, DATABASE, VISUAL, "git diff --check"],
        "protection_contracts": [
            "parameter edits, browsing, runs, hints and resets do not create mastery evidence",
            "only a valid observation submission creates one interactive_model_observation_submitted event",
            "Artifact/ArtifactVersion remains the resource and history source of truth",
            "training task, code sandbox and interactive model remain separate resources",
            "legacy /interactive-lab remains usable without fake resource context resolution",
            "all E2E work uses isolated SQLite and the deterministic local provider",
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T02")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T02",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F6-T02 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F6-T02 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
