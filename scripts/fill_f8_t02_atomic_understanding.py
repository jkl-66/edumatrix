#!/usr/bin/env python3
"""Record F8-T02's independent per-atom product understanding."""

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
    "G22-R07": item(
        "错题本是正式测验和学习中测验之后的深度学习入口：同一道规范题只保留一个错题对象，并持续追加测验题资源与智能组卷的作答历史、来源、错因确认、关联资源、复习和重做结果。",
        [
            "完整保留7.20错题列表与筛选、题目/答案/解析、错因与反思、相似题、备注、固定、闪卡、重做/复测和导出；只允许重排与渐进披露，不能删成功能摘要页。",
            "候选错因必须由学生确认；普通查看、筛选、展开、来源下钻和导出不得改变掌握度，只有提交并判分的强证据可进入统一事件聚合。",
            "同一questionVersion的重复错误追加attempt历史，不能按每次事件复制孤立错题；来源撤回或解析缺失保留历史内容并诚实标记，不删除用户备注。",
        ],
        [
            "在/workspace/review/wrong-questions建立测验题资源与智能组卷双来源的统一错题投影，复用既有assessment attempt、sourceRef、review和learning-event协议。",
            "把页面收敛为顶部筛选与克制摘要、中部错题列表/详情、右侧按需展开错误模式、来源、关联讲义/视频和复习；重做是唯一主动作。",
            "保持旧WrongQuestion数据和路由可读，聚合增强可回退；不创建第二套题目、成绩、复习或资源事实源。",
        ],
        [
            "聚焦测试测验/组卷双来源、同题合并、历史追加、候选错因确认、来源撤回、关联资源、重做幂等和强证据写入。",
            "保护测试逐项覆盖7.20八类能力，验证普通浏览零业务写入、重做后画像/路径/复习使用同一事件且不重复计分。",
            "在1440x900与1366x768完成真实浏览器E2E和截图，制造两类错题、筛选、看来源、确认错因并重做，确认历史尝试仍在。",
        ],
    ),
    "G21-R01": item(
        "F8-T02必须继续处在学习空间统一二级结构内，错题本与测评、路径、九类资源、复习和笔记共享同一课程上下文。",
        [
            "不得把错题本提升为新的学生一级入口，也不得删改已关闭模块或新增独立技术工作台。",
            "页面只消费统一courseId、knowledgePointId、taskId和resource/attempt身份，不创建同义课程或题目对象。",
        ],
        ["保护/workspace二级导航和课程上下文；错题详情深链返回原测验、组卷报告、资源、复习或笔记。"],
        ["导航和刷新测试确认所有既有学习空间入口仍可达，错题深链前后课程上下文一致。"],
    ),
    "G21-R02": item(
        "错题详情中的讲义、视频、测验和复习入口必须打开各自专用学习页，而不是在错题页复制完整资源。",
        [
            "错题页只显示紧凑关联资源摘要和深链；不得内嵌第二份讲义、视频播放器或测验成绩历史。",
            "不存在或已撤回的目标要显示诚实状态和替代入口，不能创建虚假资源。",
        ],
        ["复用既有resourceId、sourceRefId和route query协议，为错题关联资源生成可恢复深链。"],
        ["前端合同与E2E逐个打开可用关联资源，验证撤回/缺失资源状态和返回错题位置。"],
    ),
    "G21-R03": item(
        "错题本只增强统一学习上下文中的深度学习，不改变已关闭模块各自职责或建立并行状态。",
        [
            "课程、知识点、任务、题目版本、作答和来源必须来自既有事实源；同一行为不能在错题本重新生成第二份成绩。",
            "跨模块状态以统一事件和聚合结果为准，前端不能猜测掌握度或完成状态。",
        ],
        ["对接F2上下文与聚合协议，使错题、重做、复习和关联资源使用相同身份字段。"],
        ["API契约验证上下文字段一致、跨用户隔离且没有平行对象；相关F2-F7回归通过。"],
    ),
    "G21-R04": item(
        "学生查看错题或解析时可以携带当前题目、答案、来源和错因上下文进入既有智能对话即时求助。",
        [
            "求助只读或普通提问不直接更新掌握度、路径或错题完成；完整生成产物仍归档资源空间。",
            "不得展示私有思维链或把技术审计面板复制进错题首屏。",
        ],
        ["复用F7-T04的contextRef和returnTo协议，在错题详情提供克制的智能对话深链。"],
        ["E2E从错题进入对话并返回，确认题目上下文和筛选/选中项恢复，普通求助零掌握写入。"],
    ),
    "G21-R05": item(
        "错题本要同时接收学习中测验题资源和正式智能组卷的错误，但不改变测评中心只含入学诊断与智能组卷的边界。",
        [
            "不得把错题重做、相似题或学习中测验重新列为测评中心第三模块。",
            "双来源都必须保留真实mode、exam/report或resource引用，不能仅靠显示文案区分。",
        ],
        ["统一投影quiz-resource attempt与formal exam response/attempt到同一错题对象，并提供来源筛选。"],
        ["造数并验证两类来源各一题、筛选结果、来源回链和测评中心保护合同。"],
    ),
    "G21-R06": item(
        "错题重做和复习结果只能通过统一事件影响既有总路径、科目路径和每日任务，不能在错题本维护另一套路径状态。",
        [
            "普通打开、固定、备注和导出不打勾路径；只有满足既有完成/证据规则的提交可以更新。",
            "本任务不得重构F4路径预算、节奏、推荐或重建状态机。",
        ],
        ["重做完成后复用F2聚合器和既有路径任务映射，展示聚合进度或可恢复失败。"],
        ["保护回归确认路径能力未变；隔离数据库核对重做事件只更新目标知识点和关联任务一次。"],
    ),
    "G21-R07": item(
        "错题本必须与已经完成的真实复习日历协同，学生可从错题进入对应复习任务并返回。",
        [
            "F8-T02不得改写F8-T01的42格月历、58/42布局、课程筛选或普通浏览零写入规则。",
            "没有复习任务时提供创建/进入复习的单一动作，不伪造计划。",
        ],
        ["复用F8-T01 reviewTaskId和复习深链，在错题详情按需展示当前复习状态。"],
        ["重跑F8-T01保护测试，并在E2E从错题进入月历/任务再返回。"],
    ),
    "G21-R08": item(
        "错题深度学习可打开关联资源或复习任务，并在既有门禁允许时进入智能组卷。",
        [
            "错题页不能绕过F4后端组卷门禁；锁定时必须显示缺失必做任务和直达链接。",
            "从错题生成资源必须复用现有九类资源任务和幂等键，不能在错题页生成第二套产物。",
        ],
        ["复用resource bundle与exam gate查询，只展示真实可用动作。"],
        ["测试锁定/解锁两态、重复生成幂等、关联资源状态和门禁不可通过URL绕过。"],
    ),
    "G21-R09": item(
        "错题重做或复习只有在真实提交后才形成证据并反馈画像；显示历史或切换筛选不是完成。",
        [
            "前端不能因打开详情、接受筛选或查看解析直接写完成/掌握事件。",
            "候选错因确认是元认知记录，不等同答题正确，也不能单独提高掌握度。",
        ],
        ["把真实重做判分attempt交给统一聚合；错因确认单独记录可审计事件但标记为非掌握强证据。"],
        ["隔离数据库比较浏览、错因确认、错误重做和正确重做后的事件类型、证据强度及聚合差异。"],
    ),
    "G21-R10": item(
        "错题关联资源继续使用F5已交付的历史、版本、来源和自定义生成能力，错题页只做深链和上下文预填。",
        [
            "不得在错题对象中复制资源正文或覆盖资源历史；来源撤回后不能基于该来源生成新版本。",
            "资源生成、查看和导出规则保持F5合同，普通打开不更新掌握度。",
        ],
        ["用既有resourceId/version/sourceRefs关联讲义、视频、测验和复习资源。"],
        ["F5资源历史/来源/生成回归和错题关联深链E2E通过。"],
    ),
    "G21-R11": item(
        "错题重做和相似题仍属于测验题资源或复习，不进入正式测评中心模块列表。",
        [
            "测评中心保持两类正式测评；错题页不得增加第三类入口或独立正式分数。",
            "正式组卷来源可回链报告，但学习中重做不能伪装成新正式考试。",
        ],
        ["复用F6测验attempt/evaluation协议和F6正式考试报告身份，按mode准确显示来源。"],
        ["路由和模块列表保护测试，验证重做历史归入同一错题而非新正式考试。"],
    ),
    "G21-R12": item(
        "实训任务书、代码沙盒和可交互模型继续是三种独立资源；错题只能关联它们，不能合并职责。",
        [
            "错题详情不得把运行代码、调整模型参数或工程任务步骤塞进一个通用面板。",
            "关联资源缺失时显示无关联，不自动制造固定演示内容。",
        ],
        ["使用既有resource type和专用路由显示可选的关联实训/沙盒/模型入口。"],
        ["F5/F6三类资源保护测试及错题关联类型路由检查。"],
    ),
    "G21-R13": item(
        "错题深度学习可以利用全部已归档资源，但只有总路径标记的今日必做任务参与智能组卷解锁。",
        [
            "不能要求学生清空全部错题或完成所有关联资源才解锁组卷，也不能由错题页面自行改门禁。",
            "可选关联讲义、视频、闪卡和相似题保持可选，完成状态与正式门禁分离。",
        ],
        ["错题页只读取F4 authoritative exam gate和missing task列表，并保留可选资源标记。"],
        ["门禁回归验证可选错题活动不阻塞，必做未完成仍锁定且直达链接正确。"],
    ),
    "G22-R01": item(
        "新增课程仍从已完成的入学诊断开始；F8-T02只接收诊断或后续测评产生的错误，不重做初始化。",
        ["不得从错题本创建课程、初始化画像或绕过诊断；旧诊断记录保持可追溯。"],
        ["保护诊断attempt/source身份在错题投影中可显示但不改变F3流程。"],
        ["F3诊断保护回归和诊断来源错题只读显示测试。"],
    ),
    "G22-R02": item(
        "错题深度学习产生的强证据通过既有画像和路径规划链路影响后续推荐，不在错题页直接计算推荐。",
        ["不得用前端错因标签直接改画像或重排路径；聚合失败时不能显示已同步。"],
        ["复用统一学习事件与F2聚合快照；页面显示真实同步状态和恢复动作。"],
        ["故障注入聚合失败/恢复，核对画像和路径只消费同一eventId。"],
    ),
    "G22-R03": item(
        "关联错题资源必须沿用当前画像、知识点掌握和最近事件生成的既有资源版本，错题页只提供上下文入口。",
        ["不得生成固定accuracy/recall示例或忽略当前题目/课程；重复请求必须复用任务。"],
        ["把canonical question、course、knowledgePoint和attempt refs传给既有资源包或单类生成接口。"],
        ["验证上下文引用、重复生成幂等、部分失败保留与资源历史。"],
    ),
    "G22-R04": item(
        "错题重做满足真实完成条件后可由统一事件更新关联路径任务，但浏览和备注不能自动打勾。",
        ["不得由前端直接修改路径状态；错误重做与正确重做按现有证据规则区别处理。"],
        ["重做提交保存attempt后调用现有聚合链，显示真实路径更新或待恢复状态。"],
        ["测试未提交、再次错误、正确重做和重复提交四态的路径变化与幂等。"],
    ),
    "G22-R05": item(
        "从错题前往智能组卷必须继续遵循今日必做门禁，错题本本身不是自动解锁条件。",
        ["不得把有错题、完成相似题或固定错题当作组卷解锁捷径。"],
        ["只读取后端exam gate并显示锁定缺项或可进入动作。"],
        ["锁定与解锁API/深链保护测试。"],
    ),
    "G22-R06": item(
        "F8-T02为后续F8-T05保留可追溯重做事件和错题状态，使正式测评完成后的画像与学习计划更新仍来自统一聚合。",
        ["本任务不提前重构F8-T05跨页面总同步，也不能伪造已同步状态。"],
        ["保存稳定questionVersionId、attemptId、eventId和reviewTaskId供后续聚合消费。"],
        ["验证错题投影可按eventId反查，F6组卷交卷反馈回归不受损。"],
    ),
    "G22-R08": item(
        "错题中的即时疑问继续进入智能对话，回答后可按现有协议生成相关资源并归档。",
        ["Chat只显示紧凑深链，不能在错题页或对话页堆出完整生成产物；普通提问不改掌握度。"],
        ["提供携带question/source/attempt上下文的Chat入口并复用资源生成协议。"],
        ["跨页E2E验证回答、返回、资源深链和零浏览写入。"],
    ),
    "G22-R09": item(
        "错题关联的完整讲义、视频、测验或其他资源始终保存到学习空间，错题详情只展示摘要和入口。",
        ["不得把完整资源正文写入WrongQuestion或复制版本；资源失败不影响错题历史。"],
        ["关联既有resource/version记录并显示生成状态。"],
        ["数据测试确认无资源内容复制，页面状态测试覆盖可用、生成中、失败和撤回。"],
    ),
    "G22-R10": item(
        "错题关联资源可查看历史并按当前题目知识点自定义生成，所有结果继续由F5资源协议管理。",
        ["不得覆盖旧版本或绕过来源准入；恢复旧版本必须保留资源历史规则。"],
        ["复用资源历史和自定义生成深链，不在错题表增加平行版本字段。"],
        ["资源历史保护回归及错题上下文预填验证。"],
    ),
    "G22-R11": item(
        "从错题进入智能对话时仍可看到真实、脱敏的Agent协作摘要，但错题本首屏不展示技术日志。",
        ["禁止提示词、API Key、私有思维链和原始日志；没有真实run就不显示已完成审计。"],
        ["复用F7 AgentAudit公开投影，错题页只传递contextRef。"],
        ["敏感字段扫描和Chat回归，确认错题页面没有独立Agent工作台。"],
    ),
    "G22-R12": item(
        "旧Chat测验、代码和联网搜索的既定归宿不能因错题增强而回流到对话或错题页。",
        ["测验仍归测验题资源，代码仍归代码沙盒，联网搜索仍归知识库；本轮不实施F10迁移。"],
        ["保护现有深链与模块归属，错题只引用对应目标。"],
        ["路由归属静态检查和相关页面导航回归。"],
    ),
    "G22-R13": item(
        "错题深度学习处在已完成的自然语言画像与预置知识库闭环之后，不要求学生上传课程材料。",
        ["错题空态不能要求上传教材；只能引导去测验题、智能组卷或现有课程学习。"],
        ["使用现有课程、画像和来源上下文，不新增上传前置。"],
        ["新学生/无错题空态E2E确认只有闭环内可执行入口。"],
    ),
    "G22-R14": item(
        "从今日知识点生成的完整资源包仍由总路径一次创建和分发，错题页只在需要深度学习时打开或请求关联资源。",
        ["不得把错题入口变成第二个默认九类资源包主流程，也不得在Chat堆产物。"],
        ["重用已有bundle/resource identity；仅为错题提供关联资源摘要和深链。"],
        ["F4/F5资源包幂等回归和错题关联验证。"],
    ),
    "G22-R15": item(
        "错题页进入智能组卷时必须展示真实门禁状态；锁定时逐条给出未完成今日必做任务和直达动作。",
        ["不能用前端按钮隐藏代替后端授权，也不能把可选错题活动列为缺失必做项。"],
        ["复用exam gate响应及route action，不在WrongQuestion中存门禁副本。"],
        ["直接URL、锁定缺项、完成后解锁和重复刷新一致性测试。"],
    ),
    "G22-R16": item(
        "错题加载、来源解析、重做判分或聚合失败时必须保留题目、答案、备注、历史和已完成结果，并从失败步骤继续。",
        [
            "重试只重放失败步骤并复用同一幂等键；不能清空成功attempt或显示虚假已掌握。",
            "错误文案使用业务语言，不直出trace、schema、worker或内部状态码。",
        ],
        ["实现稳定加载/空/筛选无结果/解析缺失/来源撤回/重做中/再次错误/已掌握/聚合更新状态。"],
        ["故障注入来源、判分和聚合失败，验证刷新恢复、单步重试、历史不丢和布局不跳动。"],
    ),
    "G24-R01": item(
        "错题本只把有业务意义的提交、错因确认、重做和复习行为写入统一学习事件；纯浏览保持只读。",
        ["事件类型、对象和证据强度必须诚实；不能为提升展示数据记录虚假完成。"],
        ["复用DBLearningEvent与既有action/evidence协议，不新增错题专属事件总线。"],
        ["隔离数据库逐动作核对事件增量、payload和owner/course/question身份。"],
    ),
    "G24-R02": item(
        "经确认和判分的错题事件可以由统一聚合影响画像、掌握度、路径和学习计划，页面本身不直接改这些投影。",
        ["只有满足证据资格的事件可改变掌握度；失败聚合保持待恢复而不是局部伪成功。"],
        ["重做attempt写入后调用现有五步聚合并保存checkpoint。"],
        ["按eventId核对画像、路径、复习和首页投影版本一致。"],
    ),
    "G24-R03": item(
        "错题相关事件必须按既有证据类型和强度处理：正式判分/重做结果与元认知确认、备注、查看具有不同权重。",
        ["不能把候选错因接受、笔记或固定等同答对；不能由前端传入任意强证据。"],
        ["使用服务端判分生成accepted evidence，客户端普通动作保持non-mastery。"],
        ["权限与证据测试拒绝客户端伪造强证据，并比较各行为聚合效果。"],
    ),
    "G24-R04": item(
        "错题列表浏览、筛选、展开详情、查看来源、固定和导出不得无依据提高掌握度。",
        ["这些动作即使记录普通审计也必须mastery_eligible=false；无结果点击不写完成。"],
        ["前端移除任何只读操作的完成/掌握写入，后端投影忽略非证据事件。"],
        ["浏览全流程前后比较learning events、profile snapshots和path状态，要求业务写入为零。"],
    ),
    "G24-R05": item(
        "错题、画像、路径和复习投影必须能够从原始attempt与学习事件重放恢复。",
        ["不得把前端显示状态或聚合表当不可追溯的第二事实源；重放不能重复创建错题。"],
        ["以questionVersionId和owner作为稳定错题身份，聚合checkpoint复用F2-T03。"],
        ["删除隔离投影后重放，验证错题对象、attempt历史、画像和复习结果一致。"],
    ),
    "G24-R06": item(
        "错题对象的学习/复习完成与知识掌握证据必须分离：可完成一次复习任务，但只有合格判分证据改变掌握度。",
        ["备注、错因确认、查看解析和手动固定不能直接改变掌握；错误重做不能伪装为掌握提升。"],
        ["沿用completion_effect与evidence_strength字段，并在UI分别显示任务完成和掌握变化。"],
        ["测试完成但无强证据、再次错误和正确提交三种投影差异。"],
    ),
    "G24-R07": item(
        "错题创建、同题追加attempt、重做提交和聚合恢复都必须使用稳定幂等键，重复请求不能复制对象或重复计分。",
        ["同一owner与questionVersion只有一个规范错题对象；不同题目、不同owner不得错误合并。"],
        ["在统一错题投影和重做接口复用questionVersion/attempt/event幂等身份与数据库唯一性边界。"],
        ["并发/重复提交、服务重启和聚合重放测试，核对对象数、attempt数、有效计分与外键完整性。"],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F8-T02_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F8-T02 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    if len(actual_ids) != len(set(actual_ids)):
        raise RuntimeError("F8-T02 ledger contains duplicate atomic requirement IDs")

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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F8-T02")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F8-T02",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F8-T02 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
