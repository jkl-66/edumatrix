#!/usr/bin/env python3
"""Record F8-T04's independent per-atom product understanding."""

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
    "G19-R01": item(
        "个人中心必须显示可追溯的今日、近7日和所选周期学习时长；学习时长只累计事件payload中明确上报的actual_minutes、duration_minutes或active_seconds，并向用户说明周期、计算口径和来源事件。",
        [
            "不得根据页面打开时长、点击次数、事件数量或默认常量推测学习分钟数；没有明确时长证据时显示0和口径说明。",
            "统计必须按当前登录用户隔离，并可按已授权课程筛选；读取个人中心或历史页不得新增学习事件。",
        ],
        [
            "在app/profile_summary.py建立统一只读个人活动投影，返回今日、近7日和周期总分钟数、时间范围、口径及sourceEventIds。",
            "在app/m5_api.py和frontend/src/api/m5.js暴露同一投影；ProfileDashboard.vue用顶部统计区展示真实时长。",
        ],
        [
            "隔离数据库覆盖三种合法时长字段、非法/缺失/负值、课程筛选、所有者隔离和无数据口径。",
            "双桌面浏览器核对今日、近7日和周期值，读取前后learning_events数量及掌握状态不变。",
        ],
    ),
    "G19-R02": item(
        "个人中心以最近30日真实活动热力图呈现学习日期，并根据连续的有效活动日期计算连续学习天数；日期格可查看当日事件数、有效学习分钟和证据状态。",
        [
            "连续学习和热力图只使用明确学习行为事件；普通浏览可进入历史动态，但不能成为热力图活跃日或连续学习依据。",
            "无活动日期必须保留为0，不得填充演示颜色；日期和连续天数按统一时区与自然日计算。",
        ],
        [
            "在个人活动投影中返回固定日期窗、逐日eventCount/activeMinutes/sourceEventIds和从今天向前计算的streakDays。",
            "ProfileDashboard.vue用稳定网格显示30日热力图、连续学习统计和日期详情，不建立第二套热力图数据源。",
        ],
        [
            "测试跨日、当天无事件、日期断档、普通浏览事件、课程筛选和空账号的热力图与连续天数。",
            "在1440x900和1366x768检查日期格、图例、Tooltip与统计一致且无伪造色块。",
        ],
    ),
    "G19-R03": item(
        "个人中心显示所选周期内由已处理学习事件聚合结果形成的真实掌握趋势，并允许按7、30、90日切换；没有合格聚合结果时显示解释性空态。",
        [
            "趋势只读取DBLearningEventConsumption中processed结果的steps.dashboard.summary.mastery_average，不允许用旧画像、答题数或随机数据补线。",
            "周期切换只改变只读投影，不修改画像、路径、复习或学习事件；同日多条结果采用时间上最新的真实投影。",
        ],
        [
            "复用app/dashboard_summary.py现有趋势口径并在profile_summary投影中返回label/value/sourceEventId/occurredAt。",
            "LearningTrendChart.vue删除棕色与面积渐变，使用冻结墨蓝灰折线；ProfileDashboard.vue承载周期筛选、加载、空态和部分失败态。",
        ],
        [
            "测试processed/pending/failed消费、重复日期、周期边界、课程隔离与空数组。",
            "浏览器对比首页与个人中心同一课程、同一周期的来源事件和趋势值，图表标签在两种桌面尺寸不重叠。",
        ],
    ),
    "G19-R04": item(
        "个人中心展示最近学习动态，历史页按课程、周期和对象类型分页找回对话、资源、测评、复习、笔记及其他真实学习事件，并以业务语言说明发生了什么。",
        [
            "动态来自统一DBLearningEvent时间线并按所有者隔离；不得继续以旧对话接口作为个人学习历史唯一事实源。",
            "不得展示1+3+5 Swarm、认知流形、trace、worker等工程术语，也不得保留无审计依据的画像回滚。",
            "普通浏览事件可显示但必须标记不计入掌握；筛选、分页、展开和查看历史均为只读。",
        ],
        [
            "个人活动投影返回分页items、total/offset/limit、业务标签、摘要、证据状态、对象类型、课程和目标深链。",
            "ProfileDashboard.vue显示最近动态摘要；History.vue重构为左筛选、中时间线、右来源/上下文摘要的历史工作区。",
        ],
        [
            "API覆盖稳定倒序、分页不重不漏、课程/周期/对象筛选、所有者隔离、普通浏览标记和无数据。",
            "E2E从个人中心进入历史、组合筛选、分页和展开对象，检查无工程文案及零业务写入。",
        ],
    ),
    "G19-R05": item(
        "个人中心底部只显示学习画像摘要和阶段报告入口，帮助学生理解最近变化并进入完整画像；完整十维画像、知识图谱和详细证据仍由/profile/learning负责。",
        [
            "不得在个人中心复制完整画像页、算法名、数据库计数或未经证据支持的判断。",
            "阶段报告是确定性只读快照，冻结周期、生成时间、统计口径和sourceEventIds；生成失败不影响查看已有个人活动。",
        ],
        [
            "复用build_profile_summary的三画像摘要与nextAction，个人活动投影增加周期报告对象和可返回学习对象的动作。",
            "ProfileDashboard.vue下部展示三个画像摘要、完整画像入口、阶段报告摘要以及路径/复习等下一步。",
        ],
        [
            "测试画像摘要授权、无画像、报告周期/来源冻结和相同输入确定性；普通读取无写入。",
            "浏览器从摘要进入/profile/learning，从报告动作返回真实路径、复习或学习对象。",
        ],
    ),
    "G19-R06": item(
        "个人中心和历史页在保留资料、统计、收藏、动态和报告等7.20实质能力的前提下，以图29的上统计、中双列、下画像/报告结构降低认知负担。",
        [
            "视觉固定为雾白、白色内容面和墨蓝灰；可见文字至少14px、圆角不超过8px，禁止绿色、棕色、浅蓝或蓝紫主题、渐变、卡片嵌套和卡片墙。",
            "首屏必须先说明当前位置、当前可查看内容和下一步；低频口径、来源ID和完整历史按需展开，不能以简化为由删除实质能力。",
        ],
        [
            "重构ProfileDashboard.vue、History.vue和LearningTrendChart.vue的结构与样式，保留单一应用壳和既有正式路由。",
            "使用稳定桌面分栏、语义HTML、键盘焦点、明确空/加载/失败/恢复状态和唯一主动作。",
        ],
        [
            "运行前端合同、生产构建、Impeccable layout detector和无禁用配色/渐变/小字扫描。",
            "在1440x900与1366x768执行截图、溢出、碰撞、裁切、字号、对比、焦点和阅读顺序验收。",
        ],
    ),
    "G19-R07": item(
        "个人中心的所有时间、连续天数、热力图、趋势、动态和报告数字必须能从当前用户的真实学习事件与聚合结果重算，并公开时间范围、口径和sourceEventIds。",
        [
            "新账号或筛选后无数据必须显示诚实空态，不得用模拟数字、旧页面本地状态或前端随机值装饰。",
            "部分数据源失败时仅标记对应模块不可用，其他已验证事实继续展示；不得把失败解释为0增长或已完成。",
        ],
        [
            "后端集中完成事件归一、时间窗、时长、热力图、趋势、动态和报告投影，前端只消费返回值。",
            "每个统计模块显示或可展开查看calculation/period/sourceEventIds，并对空数据和部分不可用状态有独立文案。",
        ],
        [
            "用固定事件集手工重算并断言API值、时间窗和sourceEventIds；新用户断言趋势为空、热力图全0、时长0。",
            "比较首页、个人中心和历史同一周事实；检测前端无硬编码学习数字和伪造曲线。",
        ],
    ),
    "G19-R08": item(
        "最近动态、阶段报告和画像摘要必须携带稳定的业务深链，使学生能返回对应会话、资源、测评、复习、笔记、知识点、路径或完整画像并恢复原上下文。",
        [
            "深链由受控对象类型和既有路由生成，不能信任事件payload中的任意外部URL；对象失效时保留事件摘要并说明无法打开原因。",
            "打开来源不写学习事件、不改变掌握度；继续提问、继续学习或提交任务后才按其既有证据规则记录。",
        ],
        [
            "在个人活动投影中按object_type/context_ref生成内部target与availability；ProfileDashboard和History统一消费。",
            "历史右栏展示来源身份、事件证据状态、上下文和一个主要继续动作，画像/报告入口使用正式路由。",
        ],
        [
            "后端测试所有支持对象类型、恶意/未知目标、撤回对象和跨用户对象；只返回允许的内部深链。",
            "E2E逐类点击代表动态并核对目标路由、课程/对象参数、返回位置、失效说明和浏览零写入。",
        ],
    ),
    "G20-R03": item(
        "个人中心保持八个学生一级入口之一，职责是汇总真实学习时间、坚持、趋势、动态、画像摘要和报告；历史作为个人中心深链，不另建一级入口或独立技术工作台。",
        [
            "不得改变首页、学习画像、学习空间、智能对话、知识库、学习市场和设置的一级入口职责，也不得增加重复侧栏入口。",
            "个人中心不取代完整画像、路径、复习、资源或对话页面；所有深链按所属空间进入并保留返回上下文。",
        ],
        [
            "保留/profile一级路由、/profile/history二级路由和旧/history重定向，只替换两页内部信息架构与数据源。",
            "运行应用壳、学生八入口和四个7.20保护页面回归，确保F8-T04只影响个人中心和历史职责。",
        ],
        [
            "路由与导航合同检查八个一级入口数量、标签、选中态、权限和历史二级归属。",
            "双桌面从首页进入个人中心、再进入历史/画像/学习对象并返回，确认应用壳稳定且其他入口无回归。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F8-T04_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F8-T04 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    if len(actual_ids) != len(set(actual_ids)):
        raise RuntimeError("F8-T04 ledger contains duplicate atomic requirement IDs")

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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F8-T04")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F8-T04",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F8-T04 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
