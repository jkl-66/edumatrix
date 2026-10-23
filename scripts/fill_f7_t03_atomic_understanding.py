#!/usr/bin/env python3
"""Record F7-T03's independent per-atom product understanding."""

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
    "G11-R03": item(
        "知识库的联网发现页必须真正发起教材或课程资料搜索，并把带真实原站地址的结果保存为可检查的候选来源；网络不可用时明确失败且不影响预置课程。",
        [
            "只接受带可解析HTTP(S)原站地址的搜索结果；旧搜索器生成的无URL保底文案不能成为候选、书架内容或权威来源。",
            "搜索、预览和保存候选不得创建DBSourceRef、DBSourceDocument、DBCourseDocument或改变课程manifest；也不得调用未获授权的外部模型做摘要。",
            "断网、超时或发现功能关闭时保留搜索词和既有候选，预置书架、课程正文、课程内检索和F7-T02阅读器继续可用。",
        ],
        [
            "在/knowledge/discover提供搜索、来源类型/许可筛选、候选列表和预览；服务端复用既有联网检索但在准入边界前过滤无真实URL结果。",
            "新增owner-scoped候选来源协议，保存查询、标题、URL、摘要、原站、作者或机构、格式、许可、用途提示、解析影响、trustLevel、reviewStatus和importedVersion。",
        ],
        [
            "API测试搜索成功、无结果、无URL过滤、网络失败、所有者隔离和搜索不写权威来源表。",
            "双桌面E2E从发现页搜索并保存候选，确认失败可重试且断网后仍能返回预置书架阅读课程。",
        ],
    ),
    "G11-R05": item(
        "已解析课程必须有独立课程知识图谱页面，依据课程章节、知识点、先修关系和可定位来源展示可检查的课程事实，而不是文档标签共现图。",
        [
            "课程图谱只使用当前用户可访问课程的canonical章节、知识点、prerequisites、DBSourceDocument和DBSourceRef；候选或派生共现关系不得伪装成已验证边。",
            "学习画像掌握度只可作为可选只读覆盖层，不改变课程事实图，也不能因浏览、搜索、筛选或选择节点写学习事件。",
            "图谱为空、来源部分缺失或布局失败时诚实显示课程层级列表；不得回退到raw GitHub素材或另一门课程。",
        ],
        [
            "新增课程图谱读取服务和鉴权API，返回稳定节点ID、章节/知识点类型、关系类型、来源定位、图例、统计及层级回退数据。",
            "让/knowledge/graph/:courseId挂载独立KnowledgeGraphWorkspace，复用并扩展KnowledgeGraphExplorer的搜索、筛选、缩放和节点选择能力。",
        ],
        [
            "API测试课程鉴权、节点/边去重、先修关系、来源可解析、候选排除、空图和层级回退。",
            "E2E确认大画布非空，筛选和节点来源下钻可用，并从节点进入F7-T02原文定位。",
        ],
    ),
    "G11-R06": item(
        "课程知识图谱采用约75/25的大画布与右侧概览，未选节点时解释课程范围，选中节点后显示节点类型、关系、来源和进入原文或学习资源的动作。",
        [
            "图14只提供布局、信息顺序和交互参考，不复制米黄配色、品牌、模糊小字或弹层式唯一入口；正式路由仍属于知识库。",
            "同一状态最多一个视觉主动作；概览不得展示内部图算法参数、原始坐标、哈希墙或不可解释置信字段。",
            "右侧概览读取真实课程/节点数据；来源不存在、撤回或无权限时禁用进入原文并说明原因。",
        ],
        [
            "KnowledgeGraphWorkspace使用稳定75/25桌面网格，顶部提供搜索、章节/关系/掌握筛选、图例和投影视图切换。",
            "节点侧栏显示课程/节点摘要、节点与关系数量、前置/后继、来源状态、正文定位和归属学习空间的深链。",
        ],
        [
            "前端合同测试检查独立路由、75/25结构、右侧概览字段、唯一主动作和来源禁用状态。",
            "1440x900与1366x768截图验证画布/侧栏稳定、文字不小于14px、无溢出碰撞和浅蓝/绿色主题回退。",
        ],
    ),
    "G11-R07": item(
        "联网材料从搜索到审核通过前始终是候选对象，与课程权威来源彻底分离；只有满足许可、用途和范围条件的明确准入动作才能产生导入版本。",
        [
            "搜索、打开原站、预览、保存候选和修改候选说明都不得创建权威sourceRefs或让资源生成、RAG、课程图谱引用该材料。",
            "许可未知、禁止再分发、原站无效或审核未通过时准入动作必须拒绝；不得用通用已审核标签掩盖缺失字段。",
            "撤回候选或已导入版本时保留审计事实和历史资源来源状态，不静默删除或继续当作有效权威来源。",
        ],
        [
            "新增来源候选持久化模型和source_admission服务，集中校验状态转换、许可、trustLevel、reviewStatus、importedVersion及所有者。",
            "提供候选创建、列表/筛选、确认准入和撤回API；个人确认只进入个人书架范围，权威课程准入必须满足批准状态并通过单一路径生成版本化来源。",
        ],
        [
            "状态机测试覆盖pending_review、license_required、approved/imported、rejected和withdrawn，验证非法跳转与重复请求。",
            "在准入前后分别查询DBSourceRef、课程检索和资源来源，证明未准入候选不可引用且合法导入有唯一importedVersion。",
        ],
    ),
    "G11-R09": item(
        "每条联网候选在加入书架或申请准入前必须把原站、作者或机构、格式、许可/用途提示、解析影响、可信等级和审核状态完整展示给用户。",
        [
            "缺少作者可以明确显示未提供，但原站URL、格式、许可状态和解析影响不能省略；未知许可必须显示阻塞而不是默认为可用。",
            "解析影响必须说明正文、图片、公式、表格或视频中哪些内容可解析，不能用模糊的可导入承诺替代。",
            "候选详情不得暴露爬虫缓存、内部异常栈、worker、trace、私有提示词或API密钥。",
        ],
        [
            "发现页结果行显示来源机构/域名、作者、格式、许可状态、trustLevel和reviewStatus，右侧预览显示用途提示与解析影响。",
            "准入确认区逐项核对许可和用途，按钮根据真实阻塞条件禁用；成功后显示importedVersion、归档范围和下一步。",
        ],
        [
            "API契约测试逐字段校验候选序列化、未知许可阻塞、导入版本和撤回状态。",
            "E2E查看完整候选元数据，确认许可不明时不可准入，补齐/选择允许用途后状态与下一步清楚。",
        ],
    ),
    "G20-R06": item(
        "原智能对话中的双曲流形圆盘不再作为独立对话工具，而是在课程知识图谱内成为次级的关系投影视图，用于观察中心节点与邻接层级。",
        [
            "默认仍是易读的课程关系图；关系投影只能通过图谱顶部模式切换进入，不新增学生一级入口或智能对话按钮。",
            "投影视图使用与默认图相同的节点、边、来源和选择状态，不创建第二份图事实，也不声称普通环形布局具有未实现的严格双曲数学性质。",
            "切换投影、缩放和选点均为只读浏览，不能改变掌握度或学习完成状态。",
        ],
        [
            "在KnowledgeGraphExplorer增加明确的默认关系图/关系投影模式；投影使用稳定的层级径向布局并保留节点搜索、筛选和侧栏。",
            "检查Chat不再承载可见圆盘入口，学生八个一级入口和知识库深链归属保持不变。",
        ],
        [
            "前端合同测试模式切换只改变布局且数据集合不变，导航测试确认无新增一级入口和Chat圆盘入口。",
            "双尺寸E2E切换投影后节点、边、图例和右侧来源仍可读，刷新恢复到可解释默认视图。",
        ],
    ),
    "G10-R01": item(
        "F7-T03扩展共享图谱组件时必须保留学习画像按章节或知识簇组织节点的现有表现。",
        [
            "图12属于/profile/learning画像图谱，不得被课程图谱路由、来源图例或课程统计替代。",
            "不得删除分类、搜索、现有画像标签或已关闭F4-T02的首屏减负结构。",
        ],
        [
            "共享KnowledgeGraphExplorer新增能力采用可选props并保持画像调用默认行为；StudentAnalysis不做任务外重构。",
        ],
        [
            "运行F4画像合同测试并在画像页确认分类节点数量与标签不变。",
        ],
    ),
    "G10-R02": item(
        "学习画像中的关联边继续表达课程先修或技能关系，课程图谱新增关系类型不能破坏画像边语义。",
        [
            "不得把来源边、章节包含边或联网候选边混入画像掌握关系图。",
            "共享组件必须继续接受现有source/target边并保持邻接高亮。",
        ],
        [
            "为课程图谱关系图例和筛选使用显式relationType，同时保留画像edges的现有默认渲染。",
        ],
        [
            "前端单元/合同测试验证画像边渲染与邻接搜索，课程来源边只出现在课程图谱。",
        ],
    ),
    "G10-R03": item(
        "学习画像节点继续显示由可信学习证据聚合出的掌握度；课程图谱只把它作为可选只读覆盖层。",
        [
            "课程事实图不能自行计算或写入掌握度，也不能用来源可信度替代掌握度。",
            "未知、冲突和已有掌握区间的视觉语义必须保持，不能仅靠颜色区分。",
        ],
        [
            "共享组件继续兼容mastery/masteryBand，课程图谱API默认不提供掌握覆盖或只读取现有画像摘要。",
        ],
        [
            "画像回归检查掌握数字与未知/冲突状态；课程图谱浏览前后画像快照与学习事件不变。",
        ],
    ),
    "G10-R04": item(
        "画像页点击节点后仍在右侧显示具体分析、判断依据和下一步建议，课程图谱侧栏不能覆盖这一已关闭能力。",
        [
            "课程图谱的来源/节点概览与画像的证据/建议侧栏是不同语义，不能复用同一状态对象或相互跳转后丢失上下文。",
            "共享组件的node-select事件签名必须保持兼容。",
        ],
        [
            "只扩展图谱组件的可选布局/筛选接口，保留StudentAnalysis现有selected node和右栏渲染。",
        ],
        [
            "画像E2E选择节点后核对分析、依据和建议仍出现，返回课程图谱后侧栏只显示课程来源信息。",
        ],
    ),
    "G10-R05": item(
        "课程图谱上线后，7.20的十维画像、详细视图、趋势、建议、编辑和资源动作仍与画像知识图谱共同存在。",
        [
            "不得为了统一图谱工作区删除、隐藏到不可达位置或空洞化原版画像能力。",
            "F7-T03只允许针对共享组件做兼容适配，不重排画像产品结构。",
        ],
        [
            "将/profile/learning列为保护路由，保持F4-T02实现文件和现有标签/渐进展开区不变。",
        ],
        [
            "运行F4-T02画像回归并静态检查原版实质动作仍存在。",
        ],
    ),
    "G10-R06": item(
        "课程图谱和画像图谱的所有浏览交互都必须保持只读，只有题目、复述、代码、实验、复习等有效证据才可改变掌握度。",
        [
            "图谱搜索、筛选、投影切换、拖拽、缩放、选点、打开来源和列表回退均不得创建学习事件或画像快照。",
            "不得用页面停留时长、节点访问次数或候选准入状态作为掌握证据。",
        ],
        [
            "课程图谱接口仅提供GET读取；候选写入单独来源准入表，不调用学习聚合器。",
        ],
        [
            "隔离数据库记录浏览前后学习事件、画像快照、路径节点和组卷门禁摘要完全一致。",
        ],
    ),
    "G10-R07": item(
        "F7-T03必须保护7.20画像维度、丰富分析、个性化建议、画像编辑和一键生成资源等实质动作。",
        [
            "不得把课程图谱作为新的画像替代页，也不得把原版能力降为只有摘要文字的占位。",
            "若共享样式或组件变化导致原版动作不可见、不可键盘访问或低于14px，任务验收失败。",
        ],
        [
            "把StudentAnalysis和画像API作为保护面，只做共享组件向后兼容验证。",
        ],
        [
            "浏览器检查画像维度切换、编辑、建议和生成资源入口；F4保护测试与双尺寸视觉抽查通过。",
        ],
    ),
    "G11-R01": item(
        "F7-T03必须保持F7-T01已交付的我的书架为知识库首段，发现页和图谱页只能从书架自然下钻。",
        [
            "不得让联网候选列表取代首页书架，也不得把未准入候选混进shelf响应。",
            "学生首次使用仍无需上传课程资料，普通导航顺序不变。",
        ],
        [
            "复用/knowledge/courses响应和KnowledgeCourseShelf；新增发现/图谱深链但不改书架事实源。",
        ],
        [
            "F7-T01书架回归确认预置课程仍位于首段、候选不出现且加入已审核课程幂等。",
        ],
    ),
    "G11-R02": item(
        "F7-T03必须保持基于课程和画像证据或中性先验的本地已审核教材推荐，联网搜索结果不得自动进入推荐区。",
        [
            "推荐只消费published、authoritative且审核允许的课程；候选trustLevel不能冒充学习画像依据。",
            "网络失败不能改变推荐排序或清空现有推荐。",
        ],
        [
            "保持F7-T01推荐API与UI不变，来源准入只在合法导入并形成新课程版本后才可能被后续推荐消费。",
        ],
        [
            "F7-T01推荐回归覆盖画像证据、中性先验和未审核候选排除。",
        ],
    ),
    "G11-R04": item(
        "F7-T03图谱节点的来源下钻必须进入F7-T02已有大阅读器，并保持课程内正文检索与定位可用。",
        [
            "不得恢复Knowledge.vue窄预览作为正式原文入口，也不得为图谱另建第二套阅读器。",
            "候选资料在准入前没有权威正文深链；撤回或无权限来源必须明确禁用。",
        ],
        [
            "图谱节点返回canonical sourceDocumentId/sourceRefId/chapterId并深链到/knowledge/documents/:documentId。",
        ],
        [
            "F7-T02回归和E2E从图谱节点打开原文，核对课程、章节和来源定位一致。",
        ],
    ),
    "G11-R08": item(
        "F7-T03必须以团队预先整理的12章AI/ML课程作为默认可用图谱和离线书架来源，而不是依赖联网结果才能展示完整产品。",
        [
            "data/raw/github_repos仍是候选素材，不得绕过F7-T01许可清单和curated manifest进入课程图谱或权威检索。",
            "不得修改正式edumatrix.db制造图谱证据；测试和E2E使用隔离数据库。",
        ],
        [
            "课程图谱从F7-T01已经固化的DBCourse/Chapter/KnowledgePoint/SourceDocument/SourceRef读取并在断网时完整工作。",
        ],
        [
            "课程清单、章节连续性、来源哈希和离线图谱API/E2E回归通过。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F7-T03_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F7-T03 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F7-T03")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F7-T03",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F7-T03 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
