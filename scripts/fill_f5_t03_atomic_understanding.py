#!/usr/bin/env python3
"""Fill and validate F5-T03's task-local atomic understanding ledger."""

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
    product_meaning: str,
    behavior_boundaries: list[str],
    implementation_scope: list[str],
    verification_plan: list[str],
) -> dict[str, object]:
    return {
        "confirmed": True,
        "product_meaning": product_meaning,
        "behavior_boundaries": behavior_boundaries,
        "implementation_scope": implementation_scope,
        "verification_plan": verification_plan,
    }


UNDERSTANDING = {
    "G03-R03": item(
        "个性化讲义必须成为清晰、专业、适合持续阅读的独立学习产物，通过稳定目录、宽正文、分节层级和有限辅助面板消除长文本墙。",
        [
            "完整讲义只在专用深链中呈现，资源中心和对话只显示摘要与打开入口。",
            "沿用浅色极简令牌，不照搬图3的紫色主题、十二个大胶囊按钮或营销式产物墙。",
            "普通阅读、滚动、目录定位、查看来源和切换版本不写入掌握度。",
        ],
        [
            "新增HandoutWorkspace并把handout路由从通用资源中心切换到专用页面。",
            "使用左侧目录、中间阅读正文、右侧AI伙伴/来源/进度的稳定桌面布局。",
            "为旧Markdown讲义提供结构化兼容解析，但不伪造缺失来源或学习证据。",
        ],
        [
            "专项契约测试断言专用路由、结构化分区和非文本墙门禁。",
            "1440x900与1366x768真实浏览器检查阅读层级、溢出、字号、对比度和唯一主动作。",
            "检查普通浏览前后学习事件、画像和路径状态不变。",
        ],
    ),
    "G03-R07": item(
        "讲义页面必须完整提供标题与适配摘要、目录、关键概念、图表或公式、正反例、代码、小测、来源脚注、AI伙伴、学习进度、编辑、新版本历史和导出。",
        [
            "不能把所有内容压回一个不可区分的长text字段或只展示Markdown源码。",
            "来源不足时如实阻止发布态，不得补造脚注；图表局部失败不得遮挡其他正文。",
            "编辑保存必须创建新版本并保留旧版本；F5-T03不提前实现F6代码运行、正式测验计分或F7完整对话。",
        ],
        [
            "在m5_resources中提供可验证的HandoutContent结构化读取与旧Markdown适配。",
            "讲义页实现稳定正文顺序、目录定位、局部图表/公式回退、小测交互、来源脚注、AI提问上下文、进度、编辑和导出。",
            "复用现有统一资源详情、createM5ResourceVersion、compareM5ResourceVersions和exportM5Resource接口。",
        ],
        [
            "后端测试覆盖结构字段完整性、旧Markdown适配、来源阻断、非法JSON和单长字段拒绝。",
            "前端测试覆盖全部规定区域、保存新版本、历史只读、冲突反馈和导出失败重试。",
            "E2E完整执行目录定位、查看脚注、编辑一节另存版本、完成小测、导出并回看旧版本。",
        ],
    ),
    "G03-R01": item(
        "完整资源体系仍包含独立的可交互模型和PPT/网页课件，讲义页不能吞并或伪装这两类资源。",
        [
            "F5-T03只实现handout专用页面，不实现模型实验或课件编辑器。",
            "保持interactive_model和deck的类型、归档和深链不变。",
            "不在讲义首屏重建图3的十二类入口按钮墙。",
        ],
        [
            "只修改handout路由与讲义数据适配。",
            "资源中心和资源包中的模型、课件条目继续指向既有专用路由。",
        ],
        [
            "路由与资源类型回归确认interactive_model和deck仍独立存在。",
            "检查讲义页面没有模型或课件的伪实现和按钮墙。",
        ],
    ),
    "G03-R02": item(
        "讲义内容和可见适配说明必须绑定当前画像、知识点和学习目标，使术语深度、支架、例子与学习者当前状态一致。",
        [
            "页面读取冻结版本中的profileAdaptation、知识点与学习目标，不在浏览时重新生成或改写画像。",
            "不得显示内部画像快照ID、提示词或私有推理。",
            "缺失个性化字段时显示诚实的通用适配说明，不宣称已针对不存在的数据定制。",
        ],
        [
            "HandoutContent保留profileAdaptation并在标题区和右侧目标区可见。",
            "复用资源metadata中的course、knowledge_point、profile_snapshot和来源关联。",
        ],
        [
            "测试结构化讲义返回适配字段且来源/知识点保持版本一致。",
            "E2E确认首屏能解释本讲义为何适合当前学生且不暴露内部ID。",
        ],
    ),
    "G03-R04": item(
        "学生明确从路径或资源中心打开既有讲义后才进入学习，页面加载、滚动或查看详情不能自动触发新一轮生成。",
        [
            "F5-T03不新增自动生成弹窗、页面加载POST或无关引导打断。",
            "来源缺失或资源不存在时只给一个可执行返回/重试动作，不要求学生上传课程材料。",
            "重新生成讲义仍由既有资源包和后续统一资源历史能力负责。",
        ],
        [
            "专用页面只读取resourceId对应的统一资源详情。",
            "加载、失败和恢复动作均不调用资源生成端点。",
        ],
        [
            "浏览器网络记录确认打开、刷新、目录跳转无生成POST。",
            "错误态确认没有无关弹窗且能够返回资源中心或重试读取。",
        ],
    ),
    "G03-R05": item(
        "讲义继续由统一资源中心归档、检索和再次打开，专用阅读页是资源详情而不是第二套资源库。",
        [
            "不得复制资源记录、另建讲义列表或改变F5-T01的搜索筛选事实源。",
            "返回资源中心后原有课程、类型和搜索能力保持可用。",
            "归档资源的course、knowledge point、version和source关联保持不变。",
        ],
        [
            "复用DBArtifact/DBArtifactVersion和现有M5资源接口。",
            "资源中心handout条目继续使用稳定深链打开HandoutWorkspace。",
        ],
        [
            "资源目录测试确认讲义仍可按handout检索并返回同一artifact ID。",
            "E2E从资源中心打开讲义并返回，确认没有新增平行列表。",
        ],
    ),
    "G03-R06": item(
        "个性化讲义保持九类完整资源包中的一个独立产物，讲义实现不能改变另外八项的编排、状态或深链。",
        [
            "F5-T03只消费handout资源，不修改九类资源包固定集合。",
            "讲义完成或编辑不能自动标记其他资源完成。",
            "不提前实现思维导图、测验、任务书、沙盒、视频、课件、模型或费曼的专用交互。",
        ],
        [
            "保留F5-T02生成任务和资源包状态协议。",
            "讲义路由只根据resourceId读取单个handout artifact。",
        ],
        [
            "F5-T02回归确认九项数量、类型、成功资源ID和深链均未变化。",
            "检查讲义交互不写入兄弟资源状态。",
        ],
    ),
    "G03-R08": item(
        "讲义完整正文、来源、状态和版本历史必须保存在学习空间资源对象中，对话或其他入口只携带紧凑摘要和深链。",
        [
            "不修改Chat以承载完整讲义，也不复制内容到浏览器本地作为第二事实源。",
            "历史、来源和版本从后端统一资源协议读取。",
            "私有提示词、API Key、原始Agent日志和内部Schema不展示。",
        ],
        [
            "HandoutWorkspace读取统一artifact versions与resource.source_refs。",
            "编辑和导出继续经M5资源端点，页面只保留未保存草稿。",
        ],
        [
            "接口与DOM检查确认完整正文只出现在讲义专用路由。",
            "安全回归检查响应和页面不含私有模型信息。",
        ],
    ),
    "G08-R01": item(
        "讲义沿用生成即进入统一资源中心的自动归档结果，专用页面显示归档状态而不另做手动入库。",
        [
            "F5-T03不创建第二份讲义artifact或重复归档。",
            "归档失败由资源包状态处理，页面不得假装资源已发布。",
        ],
        [
            "读取resource.status、generation_state、version和catalog元数据。",
            "页面显示资源归档位置及当前可读状态。",
        ],
        [
            "后端测试确认详情读取不新增artifact/version。",
            "E2E确认从资源中心打开的是已归档的同一讲义。",
        ],
    ),
    "G08-R02": item(
        "统一资源中心继续承担按类型和关键词查找讲义，专用页面提供清晰返回入口但不重复搜索界面。",
        [
            "F5-T03不重做F5-T01的筛选搜索或更改其查询语义。",
            "讲义页不放置与阅读任务无关的大型资源筛选工具栏。",
        ],
        [
            "保持ResourceCenter的handout筛选和搜索结果不变。",
            "讲义页标题区提供返回资源中心的次要导航。",
        ],
        [
            "F5-T01资源中心回归覆盖handout类型筛选和关键词搜索。",
            "E2E确认从筛选结果进入并可返回资源中心。",
        ],
    ),
    "G08-R03": item(
        "程序类资源仍有独立文件夹、类型和入口；讲义专用页不能让代码沙盒或实验资源与讲义混为同类。",
        [
            "F5-T03不修改code_sandbox、interactive_model或training_task的类型映射。",
            "讲义中的代码片段只用于阅读和复制，真实运行留给代码沙盒。",
        ],
        [
            "代码片段在讲义正文中明确提供复制与进入沙盒的语义边界。",
            "资源中心程序类分类和深链保持原状。",
        ],
        [
            "类型映射回归确认程序类资源未被归为handout。",
            "浏览器确认讲义代码片段不会伪造运行结果。",
        ],
    ),
    "G08-R04": item(
        "学生可以在当前讲义版本基础上编辑具体结构化章节，而不是只能重新生成整份讲义。",
        [
            "编辑只作用于当前选定版本的可编辑副本，取消时不写后端。",
            "来源、脚注身份和系统字段不能被普通正文编辑悄悄删除或伪造。",
            "页面保持一个明确的保存新版本主动作。",
        ],
        [
            "讲义页提供章节级编辑模式和草稿状态。",
            "保存前把结构化内容序列化为统一版本content并携带锁版本与源版本。",
        ],
        [
            "前端测试覆盖进入编辑、修改一节、取消和保存。",
            "API测试确认修改内容来自当前版本且不改变旧版本内容。",
        ],
    ),
    "G08-R05": item(
        "每次讲义编辑保存都创建新版本，旧稿和来源引用保持可读，绝不原地覆盖。",
        [
            "必须使用expected_lock_version和source_version_id检测并发冲突。",
            "冲突时保留本地草稿并提示重新载入或建立新分支，不自动覆盖他人版本。",
            "新版本继续继承可信来源与画像上下文。",
        ],
        [
            "复用createM5ResourceVersion及DBArtifactVersion追加版本协议。",
            "保存成功后刷新详情并把新版本设为当前阅读版本；历史列表保留旧版本。",
        ],
        [
            "后端测试断言版本数递增、旧内容不变、metadata来源保留。",
            "冲突测试断言409后草稿仍在且没有覆盖当前版本。",
            "E2E保存v2后回看v1。",
        ],
    ),
    "G08-R06": item(
        "讲义页面需要显示版本历史、允许只读切换旧版本并比较差异；恢复旧版本的统一另存规则由F5-T07最终收口。",
        [
            "F5-T03必须保证旧版本可读和可比较，但不调用会直接改current_version_id的旧恢复接口。",
            "查看旧版本时编辑默认从该版本建立新版本，不改变历史记录。",
            "完整跨资源恢复策略仍由F5-T07主责，不能在讲义页建立特殊恢复语义。",
        ],
        [
            "使用artifact.versions建立版本列表与只读查看。",
            "复用compareM5ResourceVersions显示选定版本与当前版本差异。",
            "不在F5-T03暴露破坏统一另存规则的直接恢复按钮。",
        ],
        [
            "E2E切换v1/v2并确认正文和版本标记同步。",
            "比较接口测试确认差异可用且旧版本未被改写。",
            "检查页面不存在直接覆盖式恢复动作。",
        ],
    ),
    "G08-R07": item(
        "讲义详情必须如实显示生成中、正文补全、局部失败、来源不足、保存冲突、导出失败和恢复完成状态，同时保留已成功正文与草稿。",
        [
            "图表或公式失败只降级对应区块，不能清空整篇讲义。",
            "保存或导出失败保留当前阅读内容和未保存草稿，并允许只重试失败动作。",
            "讲义详情不得修改资源包中其他成功资源的状态或版本。",
        ],
        [
            "把resource.generation_state、source状态和本地编辑/导出状态映射为中文业务反馈。",
            "为局部图表、来源、编辑和导出提供就近错误与重试；保持三栏几何稳定。",
        ],
        [
            "状态测试覆盖加载、生成中、来源不足、局部渲染失败、冲突和导出失败。",
            "E2E故障注入确认正文、草稿和成功兄弟资源不丢失。",
            "双桌面截图确认状态切换无布局跳动。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F5-T03_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F5-T03 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    for entry in ledger["entries"]:
        entry["understanding"] = UNDERSTANDING[entry["atomic_requirement_id"]]
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F5-T03")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F5-T03",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError(f"F5-T03 atomic understanding gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F5-T03 atomic understandings: {ledger_path}")


if __name__ == "__main__":
    main()
