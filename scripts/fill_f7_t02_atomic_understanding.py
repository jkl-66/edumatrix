#!/usr/bin/env python3
"""Record F7-T02's independent per-atom product understanding."""

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


def item(
    meaning: str,
    boundaries: list[str],
    scope: list[str],
    verification: list[str],
) -> dict[str, object]:
    return {
        "product_meaning": meaning,
        "behavior_boundaries": boundaries,
        "implementation_scope": scope,
        "verification_plan": verification,
    }


UNDERSTANDING = {
    "G07-R01": item(
        "文档详情必须是知识库内部结构清楚的独立阅读工作区，左侧目录、中间原文、右侧来源与问答各司其职，学生进入后立即知道当前文档和下一步。",
        [
            "继承图7的三栏阅读关系而不复制竞品品牌、紫色标签、绿色强调或说明卡；正文始终是最大视觉主体。",
            "不得继续把正式文档深链实现为Knowledge.vue上的窄预览弹窗，也不得新增知识库之外的并列技术工作台。",
            "普通打开、翻页、搜索、缩放、选择和展开只保存阅读状态，不产生掌握度、学习完成或组卷解锁证据。",
        ],
        [
            "让/knowledge/documents/:documentId挂载独立KnowledgeDocumentReader，并从F7-T01课程目录和检索结果自然进入。",
            "使用桌面20/58/22稳定三栏和现有浅色极简令牌，保留返回书架、当前课程/章节、完成条件和下一动作。",
        ],
        [
            "前端合同测试确认独立路由、三栏语义、唯一主动作和旧弹窗不再承载正式文档深链。",
            "在1440x900与1366x768检查三栏可读、正文最大、无小字/溢出/碰撞/禁用配色回退。",
        ],
    ),
    "G07-R02": item(
        "课程Markdown与已有个人PDF都应在中央大阅读器中完整阅读，而不是缩成预览卡；加载或局部解析失败时仍保留可读正文。",
        [
            "预置课程继续读取F7-T01已校验哈希的canonical正文；个人PDF继续受所有者权限和既有OCR脱敏边界保护。",
            "不得伪造不存在的原始PDF、页数或图片；Markdown使用章节/语义页，PDF使用真实OCR页和页图。",
            "来源撤回、哈希漂移或无权限时必须诚实失败，不能回退到未审核raw仓库或另一份同名文件。",
        ],
        [
            "统一文档详情响应为阅读器提供文档版本、格式、正文、章节、页信息、来源和处理状态。",
            "中央区域按文档类型渲染可选择正文或真实页图，并在加载、空、失败、恢复状态保持几何稳定。",
        ],
        [
            "API测试canonical正文哈希、课程权限、个人文档所有者隔离、可读降级和错误码。",
            "浏览器验证长正文、PDF页图、加载失败重试及返回后恢复，不出现卡片式小预览。",
        ],
    ),
    "G07-R03": item(
        "学生可在原文中划选文字或在PDF页图上拖出图片区域，形成带精确来源的SelectionContext后提问；两种选择都在附近出现紧凑操作条。",
        [
            "文本选区必须保存文档版本、章节/页码、字符起止和原文引用；图片选区保存页码、页尺寸、0到1归一化坐标、裁剪引用和OCR结果。",
            "图片拖框只作用于可授权读取的真实页面，拒绝越界、零面积、NaN、过小区域和跨用户selectionId；缩放只改变显示坐标，不改变归一化事实。",
            "OCR失败必须保留选区和页图，允许重试或继续基于截图提问；F7-T02不宣称已经完成F7-T05的统一Agent审计与跨产物引用治理。",
        ],
        [
            "新增owner-scoped SelectionContext模型/服务/API，负责创建、读取、更新OCR和恢复文本或图片选区。",
            "新增SelectionToolbar和阅读器文字selection/图片pointer拖框交互；问答先提供本地、来源约束的可验证路径，不调用未授权外部模型。",
        ],
        [
            "单元/API测试字符范围、归一化、跨缩放恢复、区域校验、OCR成功/失败重试、所有者隔离和幂等请求。",
            "E2E依次完成文字划选提问与图片框选提问，刷新和缩放后核对同一页码、引用和矩形。",
        ],
    ),
    "G07-R04": item(
        "阅读器提供明确导出动作，让学生获取当前有权限文档的真实原文或诚实的解析文本导出，并保留可识别文件名与来源说明。",
        [
            "导出不得绕过课程成员/公开课程权限、个人文档所有者隔离、来源撤回或路径边界检查。",
            "没有保存原始二进制时只能标注并导出解析文本，不能伪装成原始PDF/DOCX；导出失败不影响当前阅读位置和选区。",
            "导出属于只读动作，不写学习事件、完成证据或掌握度。",
        ],
        [
            "复用当前文档详情和来源元数据，提供类型准确的下载/客户端文本导出入口及失败重试。",
            "将导出放在阅读器工具栏次级动作，不与针对选区提问争夺主动作层级。",
        ],
        [
            "测试导出文件名、MIME、字节/文本内容、权限、来源撤回和失败不丢状态。",
            "浏览器验证下载可触发，失败提示使用业务语言，导出前后学习事件数量不变。",
        ],
    ),
    "G07-R05": item(
        "右侧来源区持续显示当前文档、课程版本、章节/页码、许可和解析状态，并能从回答或选区回到原文准确位置。",
        [
            "只展示canonical来源事实和经验证定位；哈希、块ID、索引内部字段默认隐藏在按需详情中。",
            "来源撤回或定位漂移必须标记不可用并阻止权威引用，不得静默继续显示为有效来源。",
            "查看来源和定位属于只读行为，不写掌握证据。",
        ],
        [
            "阅读器响应整合现有DBSourceDocument、DBSourceRef、章节与许可字段，右栏按当前页/选区更新定位。",
            "提供来源详情、返回定位和失败恢复；复用F2/F5来源事实源，不创建第二套来源身份。",
        ],
        [
            "API测试文档/课程/来源引用一致、哈希漂移和撤回状态；前端合同测试来源字段与定位动作。",
            "E2E从来源条目跳回对应章节/页码和高亮区域，并确认普通查看不改变学习状态。",
        ],
    ),
    "G07-R06": item(
        "学生可基于当前文档或当前有效选区发起学习资源生成，任务沿用F2/F4/F5统一资源协议并最终进入资源中心，而不是把完整产物堆在阅读器。",
        [
            "生成上下文必须冻结当前课程、文档版本、sourceRefId/selectionId和允许的知识点，不能引用未审核来源或另一位用户的选区。",
            "F7-T02只提供文件级/选区级生成入口和真实任务归档；不得创建第二套资源表、伪造立即成功或在问答栏内渲染完整讲义。",
            "重复提交使用同一幂等语义；局部失败保留选区和已成功任务，可进入资源中心重试。",
        ],
        [
            "SelectionContext可转换为既有GenerationJob/Artifact上下文，支持讲义、思维导图、测验题和实训任务书等已落地类型。",
            "右栏提供受控资源类型菜单、生成状态、归档位置和资源深链，页面恢复后继续显示真实任务状态。",
        ],
        [
            "API测试来源/所有者校验、幂等任务、资源类型白名单、失败恢复和Artifact来源引用。",
            "E2E从当前文件/选区发起生成，确认资源进入既有资源中心且生成动作本身不产生掌握证据。",
        ],
    ),
    "G07-R08": item(
        "阅读器通过页码、章节目录、文内搜索和当前位置标记帮助学生定位长文档，并把同一位置用于选区、来源和刷新恢复。",
        [
            "Markdown章节与语义页、PDF真实页必须明确区分；搜索结果必须来自当前授权文档并能回到有效位置。",
            "目录跳转、搜索、缩放和翻页只更新阅读位置，不自动完成学习；无结果时保持当前位置和查询词。",
            "路由query只能作为可分享初始定位，服务端owner-scoped状态是恢复事实，不能信任客户端伪造的课程或来源身份。",
        ],
        [
            "阅读器建立统一Location协议，保存page/section/charOffset/scrollRatio/zoom与文档版本，并提供目录、页码、搜索、缩放控件。",
            "课程目录、检索结果和来源深链进入同一定位协议，避免旧弹窗与新页面两套恢复逻辑。",
        ],
        [
            "测试章节/页码边界、搜索定位、无结果、旧版本失效和刷新/离开恢复。",
            "双尺寸E2E验证目录跳转、搜索命中、缩放、翻页与当前位置提示均稳定且可键盘操作。",
        ],
    ),
    "G07-R10": item(
        "刷新、离开或局部故障后，学生应回到同一文档版本、页码/章节、缩放和选区；OCR失败保留截图、坐标和用户问题并允许只重试OCR。",
        [
            "恢复必须校验用户、文档版本、页尺寸和坐标；文档更新或来源撤回时显示选区过期，不把旧坐标无声套到新版本。",
            "失败重试只重放失败的页加载、OCR、问答或生成步骤，不清空已加载正文、有效选区、笔记草稿或成功任务。",
            "恢复状态是阅读辅助，不是学习完成或掌握证据；内部trace/worker/lease不得直接暴露给学生。",
        ],
        [
            "持久化每位用户每份文档的ReadingPosition和SelectionContext版本，前端在挂载时恢复并显示最近检查点。",
            "实现页加载、OCR和问答的独立状态与重试控制；退出时取消临时对象URL和进行中的本地操作。",
        ],
        [
            "故障注入测试页加载/OCR/问答失败、服务重启、文档版本漂移、重复恢复和只重试失败步骤。",
            "E2E刷新、离开再返回、缩放后核对页码与矩形，确认OCR失败截图和问题草稿仍在。",
        ],
    ),
    "G07-R07": item(
        "F7-T02产生的每次选区问答都必须携带可反查的selectionId、文档版本和来源定位，为F7-T05统一回答出处与Agent审计提供真实输入。",
        [
            "F7-T05仍是回答统一sourceRefId/selectionId、Agent候选/分歧/校验与最终摘要的唯一主责任务，F7-T02不得把局部问答写成该任务已完成。",
            "当前问答不得引用选区之外的文档、隐藏提示词、私有思维链或原始Agent日志；无可验证来源时必须诚实拒答。",
        ],
        [
            "SelectionContext和问答记录保留F7-T05需要的来源、定位、问题、状态和公开结果字段，界面预留来源回跳。",
        ],
        [
            "兼容测试确认选区问答始终带selectionId/sourceRefId或明确的未统一状态，并扫描响应不含私有字段。",
        ],
    ),
    "G07-R09": item(
        "F7-T02需把有效文本或图片选区连同文档、页码/章节和区域引用交给既有笔记能力，使F8-T03可以在不迁移第二套数据的前提下完成来源笔记联动。",
        [
            "F8-T03仍唯一主责笔记本中的完整来源卡、历史、搜索和来源失效体验；F7-T02只负责阅读器侧创建入口与兼容来源元数据。",
            "保存失败必须保留笔记正文和选区；来源失效不得删除用户正文；保存笔记不能改变掌握度。",
        ],
        [
            "从SelectionContext建立笔记草稿/保存调用，把selectionId、sourceRefId、文档版本、页码/章节、quote或normalizedRect作为来源元数据传递给现有笔记事实源。",
            "选择工具条提供记笔记动作，成功后显示笔记入口，失败只重试保存。",
        ],
        [
            "兼容测试确认笔记仍写入既有owner-scoped事实源、来源元数据完整、失败保留草稿且学习事件不变。",
            "E2E从文字和图片选区各保存一条笔记，并验证刷新后选区引用仍可恢复。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F7-T02_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F7-T02 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    for entry in ledger["entries"]:
        entry["understanding"] = {
            "confirmed": True,
            **UNDERSTANDING[entry["atomic_requirement_id"]],
        }
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    sys.path.insert(0, str(ROOT / "scripts"))
    from context_recovery_atomic_gate import (
        expected_entries,
        load_task_payload,
        validate_ledger_identity,
        validate_understanding,
    )

    active = json.loads((CONTEXT_ROOT / "active_manifest.json").read_text(encoding="utf-8"))
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F7-T02")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F7-T02",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F7-T02 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
