#!/usr/bin/env python3
"""Record F7-T01's independent per-atom product understanding."""

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
    "G11-R01": item(
        "知识库首页首先展示当前用户可直接学习的课程书架，并以课程而不是平铺文件作为入口。",
        [
            "首次进入不得要求学生上传课程材料；个人上传仅可作为低频兼容能力按需展开。",
            "首页顺序固定为我的书架、智能推荐、联网发现；浏览、搜索和展开不得写入掌握度或学习完成事件。",
            "F7-T01不实现F7-T02的宽阅读选区交互，也不实现F7-T03的完整联网准入和图谱工作台。",
        ],
        [
            "以现有已发布课程、课程成员关系、课程文档和来源状态组成书架聚合合同。",
            "重构/knowledge首屏，并让/knowledge/courses/:courseId显示课程、章节、文档、知识点和来源概览。",
        ],
        [
            "API测试新学生能看见至少一门预置课程，且书架条目不是平铺文档。",
            "双桌面尺寸检查首页顺序、唯一主动作、无上传前置和无普通浏览事件写入。",
        ],
    ),
    "G11-R02": item(
        "智能推荐区根据当前课程范围、已有书架、画像摘要或可解释的中性先验推荐尚未加入书架的本地审核课程。",
        [
            "没有画像证据时必须明确使用课程相邻性和本地课程目录，不得伪造个性化结论。",
            "本任务不调用外部模型，不把联网候选自动纳入推荐结果，也不因查看推荐改变掌握度。",
            "加入书架只能改变用户课程成员/书架状态，不得修改课程内容、来源版本或历史学习证据。",
        ],
        [
            "课程目录响应返回可解释推荐理由、书架状态、课程统计和来源健康状态。",
            "提供幂等加入书架动作，并在成功后把条目移动到书架且保留进入课程的下一步。",
        ],
        [
            "测试有/无现有成员关系、重复加入、无权限课程和公开课程推荐排序。",
            "在UI验证推荐理由可读、加入操作幂等、状态切换稳定且无外部请求。",
        ],
    ),
    "G11-R04": item(
        "书架中的课程可进入章节和文档，直接读取现有已解析正文，并在课程范围内检索可定位的正文结果。",
        [
            "F7-T01复用现有文档详情、来源定位和跨语言检索，不提前实现F7-T02的20/58/22阅读器、划选或框选。",
            "检索结果缺少课程、文档或来源定位时不得伪装成可打开的权威结果。",
            "来源撤回、解析失败或索引未就绪必须保留课程和已成功文档，并给出对应恢复动作。",
        ],
        [
            "课程页关联章节、课程文档、知识点和来源状态，并将核心文档作为唯一主动作。",
            "保留现有文档详情与正文检索API，在首页降噪后仍可从课程页到达。",
        ],
        [
            "测试课程到章节到正文不超过三步、来源定位一致、离线预置正文可读。",
            "验证解析中、部分失败、无结果、重试和正常状态均保留已成功内容。",
        ],
    ),
    "G11-R08": item(
        "交付运行时至少有一门经过文件白名单、许可审计、固定版本、章节拆分、知识点映射、解析和索引的AI/ML课程。",
        [
            "data/raw/github_repos中的仓库只是候选素材；只有清单逐文件列出且许可通过的data/curated内容可进入权威课程。",
            "不得用界面文案声称未验证的解析、索引、许可或来源状态；也不得修改正式edumatrix.db来制造通过证据。",
            "关闭网络后，已打包课程、章节、正文和本地检索仍必须可用。",
        ],
        [
            "从版本化课程清单和canonical数据库对象返回课程、章节、文档、知识点、来源许可、解析与索引状态。",
            "首页优先展示机器学习基础与实践等已审核课程，并显示可理解的来源状态而非内部哈希墙。",
        ],
        [
            "校验课程清单文件哈希、连续章节、知识点映射、许可文件和canonical来源数量。",
            "在临时测试数据库启动应用后验证新学生无需上传即可浏览，并在禁网条件下完成读取和检索。",
        ],
    ),
    "G20-R08": item(
        "知识库一级入口采用课程化书架，能继续进入宽阅读、边读边问、推荐和来源发现的完整产品链；F7-T01先交付课程化与推荐基座。",
        [
            "知识库保持学生八个一级入口之一，深链仍属于知识库，不新增独立技术工作台。",
            "宽阅读和选区问答由F7-T02/F7-T05主责，联网准入由F7-T03主责，本任务只提供自然入口和兼容数据。",
            "不得删除7.20已有文档、跨模态检索和知识图谱能力；低频能力可折叠或迁到课程上下文。",
        ],
        [
            "用单一Knowledge页面壳按路由呈现首页和课程详情，同时保留现有阅读、检索、来源和图谱入口。",
            "应用F1桌面设计系统，移除绿色、浅蓝、深色拼接、小字和卡片墙，首屏只突出当前课程下一步。",
        ],
        [
            "运行学生一级导航和深链回归，确认/knowledge及课程路由归属不变。",
            "在1440x900和1366x768检查无横向溢出、无小于14px文字、无绿色/浅蓝主题回归。",
        ],
    ),
    "G11-R03": item(
        "知识库必须保留明确的联网发现入口，后续可搜索教材和课程资料。",
        [
            "F7-T03才主责真实联网搜索、预览、下载、许可确认和导入；F7-T01不得发起外网请求或伪造搜索结果。",
            "网络不可用不能影响预置书架、课程正文或本地检索。",
        ],
        [
            "在首页第三段和/knowledge/discover保留来源发现入口、边界说明及后续安全工作流占位。",
            "保护现有web source API和个人资料，不改变其授权或导入语义。",
        ],
        [
            "验证发现入口可达、明确候选边界且不会自动写入权威库。",
            "断网打开知识库并确认书架与课程功能不降级。",
        ],
    ),
    "G11-R05": item(
        "课程解析完成后应能从课程上下文进入课程知识图谱。",
        [
            "完整75/25图谱画布、真实课程关系和布局失败回退由F7-T03主责。",
            "F7-T01不得把当前文档标签共现图伪装为已验证课程事实图。",
        ],
        [
            "课程页保留知识图谱摘要和/knowledge/graph/:courseId深链，并清楚区分已验证事实与派生浏览关系。",
        ],
        [
            "检查课程图谱入口携带正确courseId，普通浏览不写学习事件。",
            "运行既有图事实治理测试，确认标签共现仍标记derived_non_fact。",
        ],
    ),
    "G11-R06": item(
        "课程知识图谱的目标页面必须为大画布配右侧课程或节点概览。",
        [
            "F7-T01只保护路由、布局合同和所需课程摘要，不实现F7-T03的节点交互细节。",
            "学习画像掌握图谱与课程知识事实图不得合并为同一语义。",
        ],
        [
            "课程目录响应提供图谱摘要所需节点/关系/来源状态字段，保留后续75/25页面稳定接口。",
        ],
        [
            "合同测试确认课程图谱深链、右侧概览所需字段和事实/掌握边界未被破坏。",
        ],
    ),
    "G11-R07": item(
        "互联网资料在审核前始终是候选来源，不能因搜索、预览或点击加入而自动成为课程权威知识。",
        [
            "F7-T01的书架和推荐只能消费已发布、已许可审核的本地课程；不得读取raw仓库作为权威课程。",
            "本任务不新增自动下载、自动解析或无确认导入路径。",
        ],
        [
            "在课程目录和发现入口中保留authority_status/review_status边界，未批准候选不进入书架查询。",
        ],
        [
            "构造未审核候选并验证其不会出现在书架、课程正文或权威检索范围。",
        ],
    ),
    "G11-R09": item(
        "联网候选在加入书架前需要展示原站、作者或机构、格式、许可/用途提示及解析影响。",
        [
            "这些字段和确认流程由F7-T03主责；F7-T01只保证已审核课程保留同源元数据并为发现页预留协议。",
            "缺少许可或来源信息的候选不能用通用“已审核”标签掩盖。",
        ],
        [
            "保护来源元数据字段并在发现入口说明加入前审查内容，不提前实现候选导入按钮。",
        ],
        [
            "合同测试验证候选协议包含来源、机构/作者、格式、许可提示和解析影响，且缺项时不可准入。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F7-T01_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F7-T01 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F7-T01")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F7-T01",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F7-T01 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
