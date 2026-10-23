#!/usr/bin/env python3
"""Record F9-T01's independent per-atom product understanding."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ROOT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
LEDGER_DIR = (
    CONTEXT_ROOT
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION"
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
    "G14-R01": item(
        "学习者或教师可把自己账号中一个有当前冻结版本的单份学习资源、一个资源包或一条学习路径提交到轻量学习市场；三类对象保持各自身份，不被包装成整门课程。",
        [
            "发布者只能选择自己拥有且仍可用的对象；单份资源、资源包和学习路径不能混为一种无类型快照。",
            "发布冻结副本，不修改个人原件；来源或许可不完整时不能公开发布。",
            "保留既有整门课程市场接口和审核测试作为兼容路径，但课程不是新学生首屏的主要发布类型。",
            "不增加价格、交易、组织市场、责任链或企业治理字段。",
        ],
        [
            "在既有 marketplace listing 上增加 item_type、source_object_id 和 source_version_id，并由同一发布/审核生命周期承载三类新对象。",
            "后端按资源、资源包和学习路径分别验证所有者、冻结当前版本及课程来源；workspace 返回当前账号可发布对象。",
            "前端 /marketplace/publish 使用三步向导完成类型、对象与元数据、预览发布；旧课程提交 API 保持兼容。",
        ],
        [
            "隔离 SQLite 分别创建三类自有对象，提交后核对冻结快照、类型、来源版本和待审核状态；越权对象必须拒绝。",
            "运行既有课程市场测试，证明旧 course_id 提交、审核、公开搜索和整课获取不回归。",
            "浏览器在两个桌面尺寸完成三类选择器和三步发布，验证无小字、溢出、低对比或主题色回归。",
        ],
    ),
    "G14-R02": item(
        "学习市场是八个学生一级空间中的轻社区发现页，学生通过搜索、类型标签、课程/难度等少量筛选发现可学习内容，而不是进入治理后台。",
        [
            "首屏不展示评论审核、举报处置、责任事件、三方差异、原始哈希、价格或组织字段。",
            "营销横幅不能抢占首屏；真实条目、搜索筛选和下一动作优先。",
            "搜索、筛选、排序、收藏和浏览均为只读行为，不创建掌握证据、完成任务或改变路径。",
        ],
        [
            "扩展 public_search/workspace 返回类型、课程、难度、标签、作者、来源和保存状态，并支持 item_type 筛选与稳定排序。",
            "重构 MarketplaceWorkspace 的发现视图为紧凑列表和右侧预览，治理能力继续留在后端或后续管理员内容审核页。",
            "提供加载、空市场、筛选无结果、失败重试和恢复状态，首屏只保留一个主动作。",
        ],
        [
            "API 测试搜索词、三类筛选、排序、空结果、跨用户可见性和浏览前后学习事件/画像/路径不变。",
            "双桌面 E2E 检查搜索、筛选、清空筛选、空态和恢复；截图复核 74/26 结构与信息减负。",
        ],
    ),
    "G14-R03": item(
        "用户在市场中选中条目即可查看该冻结发布版本的可理解预览，包括内容摘要、组成、适用对象和来源，而不必先保存或跳出市场。",
        [
            "预览只能读取已发布冻结快照，不能读取发布者后来修改的当前对象。",
            "测验等受限内容的预览不能泄露答案、评分规则、私有提示词、原始 Agent 日志或敏感内部字段。",
            "预览和查看来源不产生学习证据；条目下架后不再向未保存用户提供公共预览。",
        ],
        [
            "为三类市场快照生成受控 preview：资源显示内容节选与类型，资源包显示有序组成，路径显示阶段/节点与预计学习量。",
            "公共 payload 只暴露安全预览、来源许可和必要展示元数据；完整冻结数据仅用于服务端克隆个人副本。",
            "在 /marketplace 和 /marketplace/items/:itemId 的右侧详情中呈现预览、来源和保存动作。",
        ],
        [
            "API 测试三类预览来自冻结版本，上游原件修改后预览不变，并扫描响应不含答案、提示词、密钥和原始日志字段。",
            "E2E 逐类选择条目，确认无需保存即可看到组成、来源和适用信息，普通预览前后业务表不变。",
        ],
    ),
    "G14-R04": item(
        "学生保存市场条目后，系统在当前账号中创建真实、所有者隔离且可打开的个人资源、资源包或学习路径副本，并明确给出学习空间入口。",
        [
            "不能只记录一个看似成功但无法打开的收藏或冻结 JSON；个人副本必须落到现有学习对象模型和对应工作区。",
            "保存同一条目必须幂等，不能重复克隆；副本只能由当前登录用户读取或编辑。",
            "保存本身不改变掌握度、今日任务或智能组卷门禁；只有之后的可信学习行为才进入聚合。",
            "旧整门课程获取继续使用既有 acquisition/derived_course 路径，新三类对象使用独立 personal-copy 身份记录。",
        ],
        [
            "新增 owner-scoped marketplace personal copy 记录，绑定 listing、冻结哈希、克隆对象/版本、学习空间路由和上游状态。",
            "单资源克隆 Artifact/ArtifactVersion；资源包克隆 Bundle/Version/Items 及其可用资源；学习路径克隆 PlanDraft/PlanVersion/Path/Nodes。",
            "workspace/mine 返回发布、收藏和个人副本；前端完成态显示已加入个人空间和可点击的真实内部路由。",
            "LearningPathGraph 接受受控 path_id 深链，以便打开保存的路径副本而不覆盖其他路径选择。",
        ],
        [
            "隔离 SQLite 用第二账号分别保存三类条目，核对克隆对象所有者、版本哈希、路由可达和重复保存返回同一 copy id。",
            "对资源包执行一次个人修改并新增版本，证明副本不是不可用占位；检查保存前后学习事件和掌握快照不变。",
            "双账号浏览器 E2E 从市场保存资源包，进入真实学习空间并在我的内容中再次打开。",
        ],
    ),
    "G14-R05": item(
        "发现页约 74% 用于列表或网格，约 26% 用于所选条目的固定右侧概览；未选中时右侧显示轻量引导而不是空白或治理面板。",
        [
            "右栏不能被我的审核队列、举报证据或责任记录占用；复杂详情按需进入详情深链。",
            "选中条目时列表区域和整体几何保持稳定；右栏信息不能用小于 14px 的字塞入。",
            "1366x768 仍保持可用桌面分栏，内容过长在栏内滚动或稳定截断并可查看全文。",
        ],
        [
            "MarketplaceWorkspace 发现态使用 minmax(0, 74fr) / minmax(300px, 26fr) 稳定布局，选择状态同步到 itemId 深链。",
            "右侧依次显示类型、标题、作者/课程、摘要、包含内容、来源许可、保存状态和唯一主动作。",
            "实现未选、加载、失败、已保存、上游下架和个人副本可用等右栏状态。",
        ],
        [
            "前端合同检查 74/26 网格、右侧概览和未选轻空态存在，治理字段不在发现首屏。",
            "1440x900 与 1366x768 截图测量无横向溢出、碰撞、裁切、小字或布局跳动。",
        ],
    ),
    "G14-R06": item(
        "发布使用同一个三步向导，但第一步选择发布类型后，第二步必须切换到该类型对应的个人对象选择器，第三步统一预览来源和公开信息后提交。",
        [
            "单份资源只能单选；资源包选择一个已冻结资源包；学习路径选择一条个人路径，不能用同一 course 下拉框伪装三类对象。",
            "切换类型时清除不兼容的旧选择，但保留仍适用的标题、标签和说明草稿；失败后不得清空用户输入。",
            "底部只保留取消、上一步/下一步和最终发布，不能增加价格、责任链或分叉参数。",
        ],
        [
            "workspace 返回按 item_type 分组的 publishable_sources 与来源完整性，前端根据类型渲染稳定对象列表。",
            "发布视图实现步骤 1 类型、步骤 2 对象与元数据、步骤 3 预览与来源确认，提交使用稳定幂等快照判断。",
            "无可发布对象、来源不完整、提交中、提交失败、恢复草稿和待审核完成均有明确状态。",
        ],
        [
            "组件测试验证三种选择器、类型切换清理、步骤门禁、草稿保留和来源不完整时禁用发布。",
            "E2E 分别走到三类发布预览，完整提交至少一个资源包，并检查固定底部动作和键盘焦点。",
        ],
    ),
    "G14-R07": item(
        "保存后的个人副本拥有独立对象和版本线；上游发布者更新、撤回或下架时只能改变来源提示，绝不能静默修改、删除或使个人副本不可用。",
        [
            "上游变化不能覆盖个人内容、版本、笔记、完成记录或学习事件；接受更新必须是未来显式动作。",
            "撤回公共条目后禁止新保存，但既有个人副本及其学习空间路由仍可用。",
            "不能依赖源对象继续存在才能读取副本；克隆内容来自发布时冻结快照。",
        ],
        [
            "个人副本保存 source_snapshot_hash 与 source_status，克隆对象内容和版本不引用发布者的可变当前版本。",
            "市场 withdraw 更新个人副本 source_status/提示但不触碰 copy_object_id、copy_version_id 或克隆学习对象。",
            "我的内容将上游变化简化为提示和继续打开个人副本，不显示三方 diff、原始哈希或责任链。",
        ],
        [
            "测试保存资源包后修改个人版本，再修改并下架上游，断言个人版本哈希、内容、所有者和路由不变。",
            "测试下架后新用户保存失败、原用户仍能打开，且没有新增掌握事件或路径完成。",
            "E2E 显示‘来源已下架，个人副本仍可使用’并成功进入副本。",
        ],
    ),
    "G14-R08": item(
        "市场列表、预览、发布确认和保存确认都必须显示课程来源、许可证或明确的演示数据标签；来源信息不完整时阻止进入公开发布状态。",
        [
            "许可证展示只是来源完整性说明，不宣称系统完成法律裁决或专家认证。",
            "不得用空字符串、未知来源或自动生成字样冒充完整来源；演示/合成数据必须显式标注。",
            "来源不足的草稿可以保留并修正，但不能由管理员绕过门禁直接发布。",
        ],
        [
            "从对象所属课程和冻结版本生成 provenance snapshot，包括课程、来源地址/说明、许可证、演示标识、完整性和缺失字段。",
            "submit 与 publish 两个服务端边界都校验 provenance complete；公共 payload 和个人副本均保存冻结来源。",
            "前端对象选择、第三步预览、右侧详情和保存完成态使用可理解标签展示来源及许可。",
        ],
        [
            "API 测试缺来源、缺许可证、演示来源和完整来源，确认缺失项阻止提交/发布且错误可定位。",
            "验证发布后修改课程来源不改变既有市场冻结来源；保存副本继承相同 provenance snapshot。",
            "双桌面截图检查来源标签可见、对比足够且不以颜色作为唯一状态表达。",
        ],
    ),
    "G20-R09": item(
        "学习市场继续作为学生固定八个一级入口之一，承担轻社区发现、预览、发布和个人副本管理；所有详情、发布和我的内容深链仍归属于同一学习市场空间。",
        [
            "不得新增独立技术工作台、组织市场或商业市场为学生一级入口，也不得改变其余七个已冻结入口。",
            "深链必须继承统一应用壳、导航高亮、身份和返回路径；直接访问未知条目要显示可理解失效页而不是无提示 404。",
            "教师或管理员治理入口由 F9-T02/F9-T03 各自负责，F9-T01 不把治理导航塞入学生市场。",
        ],
        [
            "保留 /marketplace 一级路由及 /items/:itemId、/publish、/mine 三个所属深链，复用 F1 AppShell 和 STUDENT 导航合同。",
            "MarketplaceWorkspace 根据当前路由呈现发现、详情、发布或我的内容状态，并保持同一市场导航上下文。",
            "路由保护和旧 marketplace 深链继续工作，未找到或已下架条目提供返回市场动作。",
        ],
        [
            "导航合同断言八个学生一级入口不变、学习市场高亮正确、三个深链归属正确且旧链接不出现无提示 404。",
            "双桌面 E2E 从应用壳进入市场，再访问详情、发布、我的内容并返回，检查导航、标题、主动作和错误恢复一致。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F9-T01_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F9-T01 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    if len(actual_ids) != len(set(actual_ids)):
        raise RuntimeError("F9-T01 ledger contains duplicate atomic requirement IDs")

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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F9-T01")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION",
        task="F9-T01",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F9-T01 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
