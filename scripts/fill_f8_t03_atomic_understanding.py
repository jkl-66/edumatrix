#!/usr/bin/env python3
"""Record F8-T03's independent per-atom product understanding."""

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
    "G07-R09": item(
        "文档正文中的文本划选或图片框选可以直接沉淀为个人笔记；笔记必须保存可反查的文档版本、页码或章节、文本范围或图片区域、selectionId和sourceRefId，而不是只复制一段无来源文字。",
        [
            "保留F7-T02已经交付的20/58/22大阅读器和紧凑选区工具条；F8-T03只接通笔记本归档、来源预览和回链，不重做PDF阅读、OCR或选区问答。",
            "保存失败或来源撤回时保留用户正文、未保存草稿和历史来源快照；不得因为原文失效删除或覆盖用户内容。",
            "选区笔记保存必须归属当前登录学生并保持幂等；普通划选、框选、定位和查看来源不得写掌握度或路径完成事件。",
        ],
        [
            "扩展笔记读写协议，使现有knowledge_selection笔记的source_metadata、selectionId、sourceRefId、文档版本、页码/章节、字符范围或归一化矩形完整返回并可解析。",
            "在/workspace/notes显示来源预览、失效状态和返回/定位原文动作；文档阅读器保存成功后提供进入该笔记的稳定深链。",
            "保留现有app/document_selection.py稳定noteId和所有F7选区字段，不建立第二套selection、sourceRef或文档事实源。",
        ],
        [
            "隔离数据库覆盖文本选区与图片选区创建、重复幂等、跨用户拒绝、完整来源字段、来源删除后的正文保留和来源失效投影。",
            "从文档选区保存并进入笔记本，再从来源侧栏回到精确页码/章节/区域；刷新后笔记、位置和草稿恢复。",
            "运行F7-T02/F7-T05保护回归和双桌面E2E，确认阅读器几何、OCR恢复、来源回答及普通浏览零掌握写入未回归。",
        ],
    ),
    "G07-R01": item(
        "F8-T03接入笔记后，课程知识库仍保持清晰的目录、正文和上下文结构，笔记动作只是选区工具条与右栏中的一个自然出口。",
        [
            "不得把笔记列表或编辑器塞进文档正文，也不得增加独立技术工作台、重复目录或第二套知识库导航。",
            "笔记回链必须恢复原文上下文，不能让用户从笔记跳回一个无课程、无文档位置的通用页面。",
        ],
        ["保护KnowledgeDocumentReader既有三栏结构，只补保存结果到笔记本的深链和Notes来源回跳消费。"],
        ["F7阅读器前端合同与双尺寸截图确认正文仍是视觉主体，笔记入口不增加首屏认知负担。"],
    ),
    "G07-R02": item(
        "来源笔记回到文档时必须继续在大窗口阅读原文件，而不是在笔记侧栏或卡片中复制一个缩小PDF。",
        [
            "Notes右栏只显示来源摘要、引用片段和定位信息；完整文件始终由/knowledge/documents/:documentId负责。",
            "来源失效时显示历史引用与不可用说明，不伪造文档预览。",
        ],
        ["构造带documentId、sourceRefId、page/chapter/region和returnTo的来源深链，复用F7阅读器。"],
        ["E2E从笔记来源进入大阅读器并返回，检查大窗口布局、精确定位和失效来源状态。"],
    ),
    "G07-R03": item(
        "文本划选和图片框选仍可提问，同时两种选区都能以同一SelectionContext保存带来源笔记。",
        [
            "图片笔记必须保留归一化矩形、页尺寸关联和OCR/截图引用；文本笔记必须保留字符范围和quote。",
            "F8-T03不得把提问结果自动改写为用户正文，也不得因保存笔记清除选区问答历史。",
        ],
        ["复用F7 document-selection API和source_metadata，在笔记读模型中统一投影text/image两类来源。"],
        ["后端与浏览器分别验证文本和图片选区的提问、记笔记、刷新恢复、回链定位及字段不串型。"],
    ),
    "G07-R04": item(
        "文档原有导出能力与笔记自身的Markdown/PDF导出并存，二者职责清楚且都不因来源联动被删除。",
        [
            "文档导出仍导出原文件；笔记导出只导出用户笔记和可读来源说明，不能冒充或复制受许可约束的完整原文。",
            "导出失败保留当前编辑内容，不写学习完成或掌握证据。",
        ],
        ["保护文档导出；让笔记导出包含来源标题、位置和历史引用状态，同时保留7.20 Markdown/PDF动作。"],
        ["文档与笔记两类导出回归，检查文件非空、来源说明正确、失败后正文和编辑状态不丢。"],
    ),
    "G07-R05": item(
        "每条带来源笔记都能查看来源身份、位置和可用状态，并从来源侧栏回到原文。",
        [
            "来源数据来自既有sourceRef、document、artifact或review对象，不允许前端显示字符串成为第二事实源。",
            "来源撤回、版本变化或对象不存在时保留创建时快照并明确标记当前不可用。",
        ],
        ["增加所有权受控的笔记来源投影，返回live locator与历史snapshot；Notes右栏按来源类型显示。"],
        ["API覆盖可用、版本变化、撤回/删除和跨用户来源；E2E验证查看来源与返回位置。"],
    ),
    "G07-R06": item(
        "从知识文件生成资源的既有能力继续由文档阅读器和资源中心负责，笔记只保存来源并提供归属页面深链。",
        [
            "F8-T03不得在笔记表中复制讲义、思维导图、测验题或实训任务书正文，也不得新增第二个生成协议。",
            "来源失效或未准入时不能从笔记绕过F7/F5准入和幂等门禁生成资源。",
        ],
        ["保护F7文件级生成动作；Notes来源侧栏只链接当前文件和既有资源，不实现平行生成器。"],
        ["F7文件级资源生成和F5资源归档回归，验证从笔记来源回到原页面后仍遵循准入与幂等。"],
    ),
    "G07-R07": item(
        "来源问答和带来源笔记都必须能说明依据；用户正文、AI建议和引用证据在数据与界面上分开。",
        [
            "不得把AI生成建议覆盖成用户原文，不得显示无sourceRef的回答为有出处，也不得展示私有提示词或思维链。",
            "用户可选择应用AI建议，但应用后形成明确的新笔记版本并保留此前正文。",
        ],
        ["为笔记保存独立aiSuggestion/authorType与版本历史；来源侧栏复用F7公开sourceRef投影。"],
        ["测试AI建议成功、失败、未应用、应用成新版本及来源可追溯；扫描响应无私有推理字段。"],
    ),
    "G07-R08": item(
        "从笔记回到知识库时，阅读器继续支持页码、章节、搜索和当前位置恢复，并优先定位该笔记引用的位置。",
        [
            "回链参数只用于定位，不得覆盖用户更新后的阅读位置；无效参数回退到可读文档并显示说明。",
            "笔记页面不复制阅读器搜索、缩放或章节导航控件。",
        ],
        ["根据source_metadata构造F7既有page、chapter_id、source_ref_id、char_start与区域定位query。"],
        ["文本页、PDF页和无效定位三类回链测试，确认刷新、返回和搜索状态可恢复。"],
    ),
    "G07-R10": item(
        "笔记来源联动不能破坏F7阅读位置恢复和OCR局部失败恢复；来源暂不可读时笔记仍可编辑、搜索和导出。",
        [
            "不得在Notes重新触发OCR或伪造OCR成功；重试仍由文档阅读器处理。",
            "来源不可用不阻塞用户正文保存、历史恢复或AI建议查看。",
        ],
        ["Notes把来源失败建模为独立状态并保留历史locator；回到阅读器后使用现有OCR重试和位置恢复。"],
        ["故障注入OCR失败、来源撤回和阅读器暂不可达，验证笔记正文/历史不丢且恢复入口诚实。"],
    ),
    "G21-R01": item(
        "笔记本继续是学习空间内的沉淀模块，与测评、路径、九类资源、复习和错题共享同一课程上下文。",
        [
            "不得把笔记本提升为新的学生一级入口或新增平行工作台；旧/notes只能重定向到/workspace/notes。",
            "所有7.20笔记创建、编辑、删除、分类、搜索、AI排版、闪卡、复习和导出能力必须可达。",
        ],
        ["保护/workspace/notes目标路由与/notes兼容重定向，重排Notes为学习空间三栏工作区并保持二级导航。"],
        ["路由、导航和四页保护回归逐项核对笔记本八类核心能力和课程上下文。"],
    ),
    "G21-R02": item(
        "笔记来源和衍生活动必须通过各自专用页面深链：文档回阅读器、讲义回讲义、代码回沙盒、复习回复习任务。",
        [
            "Notes只显示来源摘要和关联动作，不复制完整讲义、代码运行器、复习日历或测验页面。",
            "未知或失效深链显示诚实不可用状态，不能跳到错误资源或默认课程。",
        ],
        ["建立统一note source locator并在Notes右栏按类型生成受控深链，来源页面使用同一带来源草稿协议。"],
        ["从四类来源创建笔记并逐一回跳，验证目标路由、返回位置、失效状态和跨用户隔离。"],
    ),
    "G21-R03": item(
        "笔记与来源页面共享courseId、knowledgePointId、taskId、resourceId/sourceRefId，不在笔记本生成同义课程或资源对象。",
        [
            "来源上下文只能引用既有对象；保存冲突或课程不一致时必须阻止错误绑定并保留草稿。",
            "切换课程不会静默丢弃未保存笔记，也不能把其他课程笔记误归当前课程。",
        ],
        ["在笔记协议中保存规范上下文引用与来源快照；Notes按课程/标签/知识点筛选并处理未保存切换。"],
        ["API身份一致性、课程冲突、刷新恢复和跨课程筛选测试；相关F2上下文回归通过。"],
    ),
    "G21-R04": item(
        "笔记内容不明白时仍可带当前笔记、来源和课程上下文进入智能对话，完整产物继续归档资源空间。",
        [
            "普通求助或查看AI建议不直接提高掌握度，也不得在Notes首屏展示Agent技术日志。",
            "对话只能接收公开上下文引用，不发送私有来源、API Key或原始思维链。",
        ],
        ["保留既有笔记到智能对话/测验联动，统一为携带note/source context与returnTo的深链。"],
        ["跨页E2E验证上下文、返回位置和零掌握写入；F7对话与审计敏感字段回归。"],
    ),
    "G21-R05": item(
        "笔记中的练习入口仍归测验题资源，正式测评中心只保留入学诊断和智能组卷。",
        [
            "不得把笔记练习、闪卡或AI排版新增为测评中心模块，也不得生成独立正式成绩。",
            "笔记保存本身不是答题证据，只有测验提交与判分才进入掌握聚合。",
        ],
        ["保护测评中心两模块合同；笔记生成练习使用既有测验题资源深链或任务。"],
        ["模块列表、路由归属、笔记练习提交和普通保存零掌握写入测试。"],
    ),
    "G21-R06": item(
        "笔记可以从总路径、科目路径和今日任务进入并返回，但不能自行维护或修改路径状态。",
        [
            "创建、浏览、编辑或导出笔记不得自动勾选路径任务；满足既有完成规则的闪卡/测验结果才可影响。",
            "F8-T03不得重构路径预算、节奏、重规划或今日门禁。",
        ],
        ["保存路径/task引用用于返回；只消费现有路径和任务状态，不写平行完成字段。"],
        ["路径深链往返与保护回归；比较笔记浏览/保存前后路径状态保持不变。"],
    ),
    "G21-R07": item(
        "从复习任务可创建带复习来源的笔记，笔记也能把概念加入现有复习计划并返回真实日历。",
        [
            "F8-T03不得改变F8-T01真实月历、课程筛选、到期状态或普通浏览零写入规则。",
            "来源复习任务失效时保留笔记正文和历史任务说明，不伪造当前计划。",
        ],
        ["在Review提供带reviewTaskId/concept/course的笔记草稿入口；Notes保留7.20加入复习和闪卡能力。"],
        ["从复习创建笔记、回跳日历、失效任务和F8-T01保护回归。"],
    ),
    "G21-R08": item(
        "从复习或笔记进入资源生成与智能组卷时继续使用既有资源协议和后端门禁。",
        [
            "笔记不能绕过今日必做门禁解锁组卷，也不能在自身表中复制九类资源或组卷状态。",
            "来源失效或资源未准入时只显示可执行替代，不伪造成功。",
        ],
        ["Notes只提供既有资源/测验/复习深链并读取真实门禁，不实现第二套生成或考试流程。"],
        ["资源幂等、组卷锁定/解锁和笔记来源深链保护测试。"],
    ),
    "G21-R09": item(
        "复习完成仍由真实复习提交反馈画像；从复习创建或保存笔记只记录沉淀行为，不等同完成复习。",
        [
            "不能因为打开复习来源、创建笔记或勾选标签而完成任务或提高掌握度。",
            "闪卡评分和测验提交继续由原有服务端证据规则处理。",
        ],
        ["把note_saved作为非掌握事件；保护review/flashcard强证据与F8-T01完成事件。"],
        ["隔离数据库比较创建笔记与真实复习提交的事件、画像和日历差异。"],
    ),
    "G21-R10": item(
        "讲义等资源仍保留历史和按知识点生成能力；笔记只引用具体资源版本并保存来源快照。",
        [
            "不得把资源正文或版本历史复制进DBNote；资源恢复旧版本不会静默改写已保存笔记来源。",
            "笔记来源应显示创建时版本与当前可用版本差异。",
        ],
        ["讲义/沙盒笔记保存linkedResourceId与resourceVersion，并通过F5资源详情深链查看历史。"],
        ["资源版本变化、历史恢复、来源失效和笔记快照稳定性测试；F5历史回归。"],
    ),
    "G21-R11": item(
        "笔记中生成的即时练习继续归测验题资源，不改变测评中心只含入学诊断和智能组卷的边界。",
        [
            "AI排版、闪卡和笔记练习不能显示为第三类正式测评，也不能自动写正式报告。",
            "示例问题不得固化为产品行为，题目由当前课程、知识点和证据动态生成。",
        ],
        ["保护既有测验题资源入口和测评中心模块合同；笔记只传当前知识点上下文。"],
        ["静态路由/文案检查与F4/F6测评保护回归。"],
    ),
    "G21-R12": item(
        "来自实训任务书、代码沙盒和可交互模型的笔记必须保留明确来源类型，三类资源仍各自承担指导、运行和实验职责。",
        [
            "笔记来源侧栏不能把三类资源合并为通用实训，也不能在笔记页运行代码或模型。",
            "本任务只要求代码沙盒带来源草稿；实训任务书和交互模型保持可兼容扩展且不被破坏。",
        ],
        ["为代码沙盒创建笔记入口并使用统一linkedResourceId/version协议；保护三类专用路由。"],
        ["代码运行后创建来源笔记并回跳沙盒；F5/F6三类资源职责与路由回归。"],
    ),
    "G21-R13": item(
        "全部资源可被笔记引用，但智能组卷仍只以总路径中的今日必做任务为解锁条件。",
        [
            "不得要求完成所有笔记、全部可选资源或AI建议才解锁组卷；笔记也不能手工改门禁。",
            "笔记保存和来源浏览与正式组卷门禁、掌握度分离。",
        ],
        ["只保留与既有resource/task身份的引用，保护authoritative exam gate和missing required tasks响应。"],
        ["组卷门禁回归验证笔记保存不解锁、不阻塞，可选资源不进入缺失清单。"],
    ),
    "G24-R01": item(
        "显式创建、保存新版本、恢复历史和应用AI建议属于可审计的笔记行为；普通浏览、搜索、筛选和展开保持只读。",
        [
            "笔记事件只记录公开身份、来源和版本，不保存API Key、提示词或私有思维链。",
            "浏览类动作即使有技术遥测也不得进入掌握、路径或复习聚合。",
        ],
        ["复用DBLearningEvent记录幂等note_created/note_version_saved/note_version_restored等非掌握事件，不新增事件总线。"],
        ["逐动作比较事件增量，验证显式保存可追溯、浏览/搜索为零业务写入且payload不含敏感字段。"],
    ),
    "G24-R02": item(
        "笔记行为可以进入个人学习历史和后续上下文，但保存正文不直接改变画像掌握度、路径和学习计划；关联闪卡或测验结果仍按原证据聚合。",
        [
            "前端不能因笔记长度、AI排版或标签数量推断掌握度，也不能显示虚假已同步。",
            "聚合失败时保留笔记版本并显示真实待恢复状态。",
        ],
        ["将笔记保存事件标记为non-mastery；关联强证据继续使用既有F2聚合链，个人动态读取同一eventId。"],
        ["核对保存笔记后的历史可见但画像/路径不变；闪卡/测验提交仍按既有规则更新。"],
    ),
    "G24-R03": item(
        "笔记创建、AI建议、历史恢复、闪卡评分和测验提交必须按事件类型与证据强度区别处理。",
        [
            "AI建议、用户应用建议、普通保存和查看来源都不能冒充答题正确或强掌握证据。",
            "客户端不得自行指定高证据强度；只有服务端判分结果可产生强证据。",
        ],
        ["使用既有服务端事件分类，笔记事件固定为非掌握；闪卡和测验沿用原权威接口。"],
        ["权限和事件分类测试比较各动作payload、evidenceStrength及聚合结果。"],
    ),
    "G24-R04": item(
        "浏览笔记、切换分类、搜索、预览来源、查看历史和导出不能无依据提高掌握度。",
        [
            "无结果搜索、来源失效或导出失败也不得写完成；普通点击不能打勾路径任务。",
            "视觉状态与前端本地选择不是学习事实源。",
        ],
        ["确保Notes所有只读动作不调用学习完成/聚合接口；后端读模型无副作用。"],
        ["双桌面完整浏览前后比较learning events、profile snapshots、path nodes和review状态，要求掌握类写入为零。"],
    ),
    "G24-R05": item(
        "个人动态和来源投影可从不可变笔记版本及统一事件重放恢复，当前编辑器状态不是唯一事实源。",
        [
            "不得用前端缓存覆盖数据库历史；恢复旧版本必须另存新版本而不是改写历史。",
            "重放不能重复创建笔记版本、来源引用或个人动态。",
        ],
        ["建立不可变note version历史和eventId/version关联；恢复操作生成新版本并保留来源快照。"],
        ["隔离数据库删除派生投影后重放，验证版本链、当前正文、来源和个人动态一致且无重复。"],
    ),
    "G24-R06": item(
        "笔记保存可成为今日任务的非掌握完成证据（仅当任务合同明确要求笔记），但知识掌握只能由合格强证据改变。",
        [
            "普通手动笔记、AI排版或来源预览不能自动完成任意路径任务；没有taskId和完成规则时只进入个人动态。",
            "本任务不扩展今日任务完成规则，必须沿用F4已有合同。",
        ],
        ["笔记事件携带可选taskId和completion_effect=none/contractual；不直接写mastery。"],
        ["测试无任务笔记、明确笔记任务保存和闪卡/测验三类行为的完成与掌握差异。"],
    ),
    "G24-R07": item(
        "笔记创建、保存版本、来源草稿和事件写入必须使用稳定幂等键与乐观版本，重复点击或恢复不能重复版本或个人动态。",
        [
            "跨用户笔记、来源和幂等键不得串用；保存冲突必须返回可理解冲突并保留本地草稿。",
            "来源页面重复创建同一草稿可复用已有对象，但内容不同的同键请求必须拒绝。",
        ],
        ["为笔记CRUD增加expectedVersion、不可变版本记录和事务内幂等事件；沿用文档选区稳定noteId。"],
        ["重复/并发保存、同键异内容、服务重启、历史恢复和跨用户访问测试，核对版本数、事件数与数据库完整性。"],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F8-T03_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F8-T03 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    if len(actual_ids) != len(set(actual_ids)):
        raise RuntimeError("F8-T03 ledger contains duplicate atomic requirement IDs")

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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F8-T03")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F8-T03",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F8-T03 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
