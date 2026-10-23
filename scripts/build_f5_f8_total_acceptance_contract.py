#!/usr/bin/env python3
"""Build the standalone F5-F8 total-acceptance recovery contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence"
OUTPUT = EVIDENCE / "f5_f8_total_acceptance"
LEDGER = OUTPUT / "atomic_execution_ledger.json"
GOAL = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery" / "goal_contract.md"
SOURCE_TEXT = """F8 完成后执行 F5-F8 总联合旅程：

总路径选择知识点
-> 九类资源生成和失败恢复
-> 资源中心检索
-> 阅读讲义和思维导图
-> 完成测验题
-> 操作交互模型
-> 代码运行和 AI 点评
-> 五阶段费曼
-> 智能组卷和报告
-> 文档划选/框选提问
-> 创建笔记
-> 进入错题和复习日历
-> 检查首页、画像、路径、错题、复习和历史一致更新。

必须验证刷新、重复点击、模型失败、网络中断、服务重启、部分聚合失败和恢复；检查普通浏览不会改变掌握度。"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def atom(
    atom_id: str,
    title: str,
    atomic_text: str,
    product_meaning: str,
    boundaries: list[str],
    scope: list[str],
    verification: list[str],
    evidence_refs: list[str],
    confirmed: bool,
) -> dict:
    return {
        "atomic_requirement_id": atom_id,
        "role": "primary",
        "source": {
            "authority": "outputs/原系统融合重构执行/evidence/context_recovery/goal_contract.md#十四、阶段联合验收",
            "full_original_words": SOURCE_TEXT,
            "atomic_text": atomic_text,
            "title": title,
            "source_images": [],
            "image_context": "N/A: this is a goal-level continuous-acceptance obligation; the underlying closed tasks retain their own Word/image ledgers.",
        },
        "understanding": {
            "product_meaning": product_meaning,
            "behavior_boundaries": boundaries,
            "implementation_scope": scope,
            "verification_plan": verification,
            "confirmed": confirmed,
        },
        "closed_stage_evidence_refs": evidence_refs,
        "total_realization": {
            "status": "PENDING",
            "implementation_or_protection_evidence": [],
            "verification_evidence": [],
            "user_visible_result": "",
            "compatibility_or_defer_rationale": "",
        },
    }


def build(confirmed: bool) -> dict:
    shared_boundaries = [
        "只验证 F5-F8 已关闭能力的连续性，不重做、重命名或扩张产品功能。",
        "所有动态数据使用冻结合成课程、匿名学生和隔离 SQLite；不得修改正式数据库。",
        "普通浏览、搜索、展开、预览、筛选、下载和来源查看不得写掌握证据。",
        "不得调用外部模型或依赖公网；不得读取、规划或实施 F9/F10。",
    ]
    shared_scope = [
        "允许新增总验收脚本、隔离夹具、报告、截图、总验收账本和恢复状态记录。",
        "产品代码只有在总旅程证明是本轮造成的真实回归时才允许最小修复，并必须回到相应原子合同。",
    ]
    shared_verify = [
        "在同一隔离 SQLite、同一服务生命周期和同一 Chromium 中按目标顺序完成总旅程。",
        "在 1440x900 和 1366x768 检查 0 溢出、0 裁切、0真实碰撞、0 小于14px文字、0禁用主题色和0渐变。",
        "为本原子单独记录动作、接口/页面、数据库前后状态、截图和用户可见结果；总体测试数不能替代逐项证据。",
    ]
    specs = [
        (
            "F5F8-R01", "总验收隔离与连续运行前提", "F8 完成后执行 F5-F8 总联合旅程。",
            "总验收从全部 F5-F8 已关闭事实继续，在一个隔离环境中验证连续产品，而不是把各阶段报告拼成通过结论。",
            ["F5-F8 已关闭实现和阶段报告只作为基线；总旅程必须产生新的连续证据。", "服务重启只能发生在同一隔离数据库与同一验收所有权下，清理不得影响用户进程。"],
            ["验证活动目标、F8 阶段 PASS、隔离路径、端口、服务和 Chromium 所有权。"],
            ["启动前检查端口与数据库归属；结束后确认端口无监听、进程已清理、正式数据库哈希/状态未变化。"],
            ["evidence/f8_phase_acceptance/phase_report.json"],
        ),
        (
            "F5F8-R02", "总路径选择今日知识点并触发资源包", "总路径选择知识点 -> 九类资源生成。",
            "学生从总路径的今日安排选择一个知识点，看到必做/可选、预计时长和完成条件，并主动创建同一个九类资源包。",
            ["不得从内部工作台、固定 URL 或测试后门直接跳过总路径。", "生成成功不等于学习完成，也不能提前解锁智能组卷。"],
            ["从正式总路径进入知识点和资源生成工作区。"],
            ["验证一个稳定生成任务、九个不同资源类型、路径/画像/掌握度生成前后不变。"],
            ["evidence/f5_t02_resource_bundle/report.json", "evidence/f4_t04_resource_generation/"],
        ),
        (
            "F5F8-R03", "九类资源生成失败、幂等与重启恢复", "九类资源生成和失败恢复。",
            "九项资源独立生成、校验和归档；一项失败只重试自身，刷新、重复点击和服务重启恢复同一个任务与成功结果。",
            ["不得清空成功项、复制生成任务或用全量重跑掩盖单项失败。", "模型不可用必须显示真实失败/本地确定性结果，不能伪装外部模型成功。"],
            ["复用正式 GenerationJob/Resource/Version 事实源和 F5 资源包页面。"],
            ["故障注入单项失败，刷新并重复点击，再重启服务；核对任务 ID、成功版本、失败项重试次数和最终归档。"],
            ["evidence/f5_t02_resource_bundle/report.json", "evidence/f5_t07_resource_history/report.json"],
        ),
        (
            "F5F8-R04", "资源中心检索、预览、历史与来源", "资源中心检索。",
            "学生在统一资源中心按类型、课程、知识点、状态和来源检索刚生成的资源，预览并进入专用页面，历史与版本仍可找回。",
            ["完整资源不得堆回智能对话；普通检索、筛选、预览和下载不得写学习证据。"],
            ["验证 /workspace/resources 及九类专用深链。"],
            ["检索新资源、切换筛选与布局、打开历史/来源/版本，核对普通浏览零写入。"],
            ["evidence/f5_t01_resource_center/report.json", "evidence/f5_t07_resource_history/report.json"],
        ),
        (
            "F5F8-R05", "个性化讲义与思维导图深度学习", "阅读讲义和思维导图。",
            "学生阅读结构化讲义并使用可搜索、缩放、折叠和来源下钻的思维导图；两者保持同一知识点、画像和来源上下文。",
            ["讲义不得退化为文本墙；导图查看和布局调整不得改变掌握度。", "损坏旧内容必须诚实降级并保留原文，不能补造结构。"],
            ["验证正式讲义与思维导图专用页面、版本和来源。"],
            ["检查讲义完整章节、脚注和导出；检查导图导航、详情、来源和层级回退；双桌面零视觉缺陷。"],
            ["evidence/f5_t03_handout/report.json", "evidence/f5_t04_mindmap/report.json"],
        ),
        (
            "F5F8-R06", "其余资源归宿与三类技能边界", "九类资源生成。",
            "实训任务书、视频推荐、PPT/网页课件、代码沙盒、交互模型和费曼任务都有独立正式归宿，职责清楚且可从同一资源包进入。",
            ["实训任务书、代码沙盒和可交互模型不得合并。", "视频只推荐/播放有来源材料，不生成视频文件；PPT/网页课件保留版本和导出。"],
            ["检查九类资源目录和专用深链，不重复实现各工作区。"],
            ["逐项打开资源，核对类型、来源、状态、历史和下一动作；验证视频没有生成文件。"],
            ["evidence/f5_t05_training_task/report.json", "evidence/f5_t06_video_deck/report.json"],
        ),
        (
            "F5F8-R07", "测验题资源提交与即时反馈", "完成测验题。",
            "学生在测验题资源中修改答案、提交、查看即时判分、解析、来源和追问；只有正式提交形成可信证据。",
            ["测验题仍属于学习空间资源，不进入测评中心。", "浏览、改答案草稿和查看解析不能提前写掌握证据。"],
            ["复用 F6-T01 正式测验题资源和统一事件聚合。"],
            ["验证刷新恢复、提交失败重试、重复提交幂等、历史版本和一次可信事件。"],
            ["evidence/f6_t01_quiz_resource/browser_report.json"],
        ),
        (
            "F5F8-R08", "可交互模型实验与观察证据", "操作交互模型。",
            "学生调节参数、运行实验、观察图表并提交自己的观察；只有有效观察提交形成学习证据。",
            ["调参、运行和提示只保存草稿，不改变掌握度。", "画布失败必须保留表格/静态回退和草稿。"],
            ["复用 F6-T02 正式资源、版本和确定性实验。"],
            ["验证参数草稿、运行、失败恢复、观察提交、版本恢复和恰好一条可信事件。"],
            ["evidence/f6_t02_interactive_model/report.json"],
        ),
        (
            "F5F8-R09", "代码真实运行、AI 点评与重跑", "代码运行和 AI 点评。",
            "学生在三栏沙盒真实运行代码，查看输出/错误/图表，再获得绑定 runAttemptId 的点评，应用建议为新版本后重跑。",
            ["没有真实运行不得生成点评；外部模型不可用不能影响本地代码运行。", "运行失败、超时、停止和大输出必须诚实显示并清理子进程。"],
            ["复用 F6-T03/T04 正式执行器、资源版本、运行产物和点评产物。"],
            ["覆盖正常、报错、超时/停止、大输出、绘图、点评、应用建议和重跑；确认无遗留子进程。"],
            ["evidence/f6_t03_code_sandbox/report.json", "evidence/f6_t04_code_review/report.json"],
        ),
        (
            "F5F8-R10", "费曼五阶段不可跳步闭环", "五阶段费曼。",
            "学生依次完成第一轮、评价、真实追问与来源回答、第二轮、评价、对比和最终应用。",
            ["不得跳过真实追问，不得固定题目或伪造提分。", "只有最终应用形成一条可信事件。"],
            ["复用 F6-T05 正式状态机和来源协议。"],
            ["尝试越级并确认拒绝；验证失败恢复、草稿刷新、两轮原文/评价保留和最终事件唯一。"],
            ["evidence/f6_t05_feynman/report.json"],
        ),
        (
            "F5F8-R11", "智能组卷、作答、报告与五类反馈", "智能组卷和报告。",
            "今日必做证据齐备后解锁智能组卷，学生配置、作答、刷新恢复、交卷并查看报告；同一交卷更新画像、路径、次日、错题和复习。",
            ["不得绕过 F4 服务端门禁，不得因重复提交重复计分。", "未完成必做时必须显示缺失项，教师/历史试卷仍可读。"],
            ["复用 F4 门禁和 F6-T06 正式试卷、作答、报告与可恢复聚合。"],
            ["验证锁定/解锁、逐题保存、刷新、交卷、报告、五类反馈、部分失败恢复和事件唯一。"],
            ["evidence/f6_t06_formal_exam/report.json", "evidence/f4_t05_exam_gate/"],
        ),
        (
            "F5F8-R12", "预置知识库与文本/图片选区提问", "文档划选/框选提问。",
            "学生无需上传课程材料即可从预置书架进入大阅读器，完成文本划选和图片框选/OCR提问，并反查精确来源。",
            ["未经准入的联网候选不能污染权威课程。", "刷新、缩放和失败恢复必须保留页码及选区坐标，普通阅读不改掌握度。"],
            ["复用 F7 预置书架、文档阅读器、来源引用和准入边界。"],
            ["验证新账号进入课程、文本/图片选区、OCR失败重试、来源回跳和选区恢复。"],
            ["evidence/f7_phase_acceptance/phase_report.json"],
        ),
        (
            "F5F8-R13", "来源笔记创建、冲突与历史恢复", "创建笔记。",
            "学生把文档选区及讲义、沙盒、复习上下文保存为带来源笔记，用户正文、AI建议和历史版本保持分离。",
            ["来源撤回或冲突不能删除用户正文；普通查看和编辑草稿不改变掌握度。"],
            ["复用 F8-T03 笔记事实源、版本和精确来源回链。"],
            ["验证四类来源、陈旧版本409、本地草稿、AI建议应用、历史恢复另存和双桌面。"],
            ["evidence/f8_t03_notes/report.json", "evidence/f8_phase_acceptance/phase_report.json"],
        ),
        (
            "F5F8-R14", "错题深度学习与真实复习日历", "进入错题和复习日历。",
            "学生从统一错题查看双来源历史、错因、来源和重做，再从真实月历选择日期并完成复习/复测。",
            ["同题只保留一个对象并追加尝试；错因由学生确认。", "复习月历浏览只读，真实完成后才写一次幂等事件。"],
            ["复用 F8-T01/T02 正式页面、来源、重做和聚合。"],
            ["验证同题合并、来源回跳、错因确认、重做、42格月历、课程筛选、完成和延迟复测。"],
            ["evidence/f8_phase_acceptance/phase_report.json"],
        ),
        (
            "F5F8-R15", "首页至历史六页同版本持续反馈", "检查首页、画像、路径、错题、复习和历史一致更新。",
            "六类可信学习事件完成后，首页、画像、路径、错题、复习和历史读取同一事件、快照版本、次日安排和真实聚合进度。",
            ["页面之间不能互相直接写状态；完整同步前不得显示虚假全绿。", "原版结果和历史继续可见，反馈层不得复制成长报告。"],
            ["复用 F8-T05 统一事件、五步聚合、反馈组件和六页消费者。"],
            ["逐页核对 event/token/version/next-day 完全相同；注入部分失败并恢复后确认无重复消费。"],
            ["evidence/f8_t05_learning_feedback/report.json", "evidence/f8_phase_acceptance/phase_report.json"],
        ),
        (
            "F5F8-R16", "刷新、重复、失败、断网、重启和部分恢复", "必须验证刷新、重复点击、模型失败、网络中断、服务重启、部分聚合失败和恢复。",
            "跨 F5-F8 的长旅程在前端刷新、重复动作、确定性模型失败、网络请求中断、服务重启和聚合部分失败后继续同一任务，不丢输入、不复制事实。",
            ["只重试失败步骤；成功状态、草稿、历史、来源和旧快照必须保留。", "不得用全局忽略错误、自动伪成功或清库重跑让测试变绿。"],
            ["在总验收测试器中按精确操作窗口登记故障，其他错误继续 fail-closed。"],
            ["验证每类故障的精确端点/状态、可见恢复动作、服务重启和最终幂等计数；意外错误列表必须为空。"],
            ["evidence/f5_t02_resource_bundle/report.json", "evidence/f8_phase_acceptance/continuous_report.json"],
        ),
        (
            "F5F8-R17", "只读、原版保护、数据、视觉和错误总门禁", "检查普通浏览不会改变掌握度。",
            "总旅程的所有普通浏览保持零学习状态写入，四个7.20保护页仍有实质能力；双桌面、数据库、权限和浏览器错误门禁同时通过。",
            ["不得把测试总数、页面存在或历史截图当作保护能力证据。", "正式数据库、真实用户数据、外部模型、Git和交付包不得改变。"],
            ["比较总旅程多个只读窗口的事件、画像、路径、门禁、错题、复习和笔记状态。"],
            ["逐页动作检查四个保护页；SQLite完整性/外键、双桌面视觉、owner隔离和意外HTTP/控制台错误均 fail-closed。"],
            ["evidence/f8_phase_acceptance/phase_report.json", "evidence/f7_phase_acceptance/phase_report.json"],
        ),
        (
            "F5F8-R18", "最终回归、交叉校验、构建、Impeccable与恢复断点", "完成 F8 全部任务、阶段联合验收和视觉验收后暂停，只把下一断点推进到 F9 / F9-T01 / NOT_STARTED，不得读取、规划或实施 F9。",
            "总旅程通过后仍要运行12号交叉校验、F2-F8相关回归、生产构建、最终Impeccable与代表性双桌面截图，再重建验证恢复版本并停在F9未开始。",
            ["任何总旅程、回归、构建、视觉、数据库、恢复包或逐原子证据失败都阻止推进断点。", "断点可以指向F9但不得读取F9合同、代码范围或任务内容。"],
            ["生成总验收报告、逐原子核销、最终恢复版本和进程清理记录。"],
            ["12号校验PASS；F2-F8回归PASS；构建PASS；Impeccable无未核实问题；active_manifest VERIFIED；最终端口/进程清理。"],
            ["outputs/原系统融合重构执行/12_方案交叉校验报告.md", "evidence/context_recovery/active_manifest.json"],
        ),
    ]
    entries = []
    for atom_id, title, atomic_text, meaning, boundaries, scope, verify, refs in specs:
        entries.append(atom(
            atom_id,
            title,
            atomic_text,
            meaning,
            shared_boundaries + boundaries,
            shared_scope + scope,
            shared_verify + verify,
            refs,
            confirmed,
        ))
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "schema_version": "f5-f8.total-acceptance-ledger.v1",
        "goal_id": "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        "task_id": "F5-F8-TOTAL-ACCEPTANCE",
        "phase": "F5-F8",
        "state": "CONTEXT_VERIFIED" if confirmed else "NOT_STARTED",
        "created_at": now,
        "updated_at": now,
        "checkpoint_authority": {
            "path": "outputs/原系统融合重构执行/evidence/context_recovery/current_checkpoint.json",
            "source_task": "F8-T05",
            "source_state": "CLOSED",
            "authorized_next_step": "F8 phase acceptance and F5-F8 total acceptance; F9 remains forbidden until both pass.",
        },
        "source_hashes": {
            "goal_contract": {"path": GOAL.relative_to(ROOT).as_posix(), "sha256": sha256(GOAL)},
            "f8_phase_report": {"path": "outputs/原系统融合重构执行/evidence/f8_phase_acceptance/phase_report.json", "sha256": sha256(EVIDENCE / "f8_phase_acceptance" / "phase_report.json")},
        },
        "task_atomic_execution_contract": {
            "schema_version": "context-recovery.task-atomic-contract.v1",
            "task_id": "F5-F8-TOTAL-ACCEPTANCE",
            "scope_is_task_local": True,
            "standalone_total_acceptance_contract": True,
            "primary_atomic_requirement_ids": [item[0] for item in specs],
            "related_atomic_requirement_ids": [],
            "required_understanding_fields": ["product_meaning", "behavior_boundaries", "implementation_scope", "verification_plan"],
            "required_primary_realization_fields": ["implementation_or_protection_evidence", "verification_evidence", "user_visible_result", "compatibility_or_defer_rationale"],
            "must_read_every_primary_and_related_atom": True,
            "must_correlate_word_paragraphs_and_full_size_images_when_referenced": True,
            "previous_task_understanding_or_evidence_cannot_substitute": True,
            "context_verified_requires_per_atom_understanding": True,
            "editing_forbidden_before_context_verified": True,
            "every_edit_batch_requires_atom_or_protection_mapping": True,
            "ledger_must_be_updated_after_each_edit_or_test_batch": True,
            "ledger_must_remain_active_during_planning_editing_testing_and_review": True,
            "conflicts_require_authoritative_source_recheck": True,
            "evidence_verified_requires_per_atom_realization": True,
            "closure_requires_per_atom_reconciliation_without_group_substitution": True,
            "next_task_forbidden_before_current_task_closed": True,
            "resume_must_continue_from_incomplete_ledger_entries": True,
            "task_close_requires_realization_gate": True,
        },
        "protection_contracts": {
            "legacy_profile": "7.20学习画像维度、证据和完整页面保持可达；普通浏览零写入。",
            "legacy_path": "7.20学习路径、今日必做与智能组卷门禁保持可达且不被总验收脚本绕过。",
            "legacy_notes": "7.20笔记编辑、分类、搜索、历史和正文保持可用；来源失效不删正文。",
            "legacy_wrong_questions": "7.20错题筛选、解析、反思、相似题、备注、固定、闪卡、重做与导出保持可用。",
            "read_only_browsing": "普通浏览不改变学习事件、掌握度、画像、路径、组卷门禁或复习完成。",
            "data_integrity": "总验收只用隔离SQLite；integrity_check=ok、外键违规0，正式数据库不修改。",
            "visual": "1440x900与1366x768均为0溢出、0裁切、0碰撞、0小字、0禁用主题色、0渐变。",
            "recovery_consistency": "账本、报告、00、11、WORKLOG、checkpoint与active_manifest必须指向同一真实断点。",
            "external_and_scope": "不调用外部模型，不依赖公网，不执行Git/交付包，不读取或实施F9/F10。",
        },
        "entries": entries,
        "execution_batches": [
            {
                "batch": "total-acceptance-contract-build",
                "status": "CONTEXT_VERIFIED" if confirmed else "BUILT_NOT_CONFIRMED",
                "mapped_atoms": [item[0] for item in specs],
                "protection_contracts": ["recovery_consistency", "external_and_scope"],
                "changed_files": [
                    "scripts/build_f5_f8_total_acceptance_contract.py",
                    "outputs/原系统融合重构执行/evidence/f5_f8_total_acceptance/atomic_execution_ledger.json",
                ],
                "result": "The standalone total-acceptance task now has 18 goal-derived atomic obligations and an independent fail-closed ledger.",
                "verification": "Every entry contains the exact goal source, task-local meaning, behavior boundaries, implementation scope, verification plan and closed-stage evidence references. Confirmation is explicit and cannot inherit F8 phase understanding.",
            }
        ],
        "final_acceptance": {
            "status": "PENDING",
            "required_outcomes": [item[1] for item in specs],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="Mark per-atom understanding confirmed after human/model source review.")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    payload = build(args.confirm)
    LEDGER.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"F5-F8 total acceptance contract: {len(payload['entries'])} atoms, state={payload['state']}")


if __name__ == "__main__":
    main()
