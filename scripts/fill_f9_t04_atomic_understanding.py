#!/usr/bin/env python3
"""Record F9-T04's independent per-atom product understanding."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ROOT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
GOAL_ID = "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION"
LEDGER_DIR = CONTEXT_ROOT / "atomic_requirement_ledgers" / GOAL_ID


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
    "G23-R05": item(
        "教师和管理员只使用已经收敛的教学总览、课程与学生观察、测评干预、账号、模型、内容审核和系统状态；F9-T04 为这些简单工作区补齐服务端身份、对象范围和审计边界，不再增加新后台模块。",
        [
            "教师仅能读取有服务端课程成员关系或所有权的课程和学生；管理员只能执行四项已批准管理任务。",
            "后台技术细节和审计详情默认不进入普通首屏，且不得重新引入企业治理、专家认证或组织集成。",
            "前端角色值只用于提前引导；最终允许或拒绝必须由服务端用户、正式角色和课程关系决定。",
        ],
        [
            "统一 app/auth.py 与 app/authorization.py 的学生、教师、管理员正式角色和课程范围判断。",
            "用最小脱敏审计模块承载教师/管理员高风险写操作；只在 frontend/src/router/index.js 收口正式角色元数据，不重做 F9-T02/F9-T03 页面。",
            "保留 F9-T02/F9-T03 已关闭页面、接口和视觉结果，只修复当前任务发现的授权、数据最小化或审计缺口。",
        ],
        [
            "三账号与越权课程/学生矩阵验证服务端 401/403/404 边界，篡改 localStorage 不能获得数据。",
            "复跑教师和管理员专项回归及双桌面旅程，确认现有最小工作区仍简洁可用且没有新增入口。",
            "检查普通教师/管理员读取前后学习事件、画像、路径和掌握度计数不变。",
        ],
    ),
    "G23-R06": item(
        "教师和管理员只看到完成当前任务所需的公开摘要、业务错误和下一动作；密钥、原始输入、内部追踪、私有 Agent 信息及历史企业工作台不得成为可见信息。",
        [
            "审计必须保留 actor、action、object、结果、前后摘要和时间所需的最小信息，但不能保存 API Key、令牌、密码、提示词、真实敏感原文、私有思维链或原始日志。",
            "错误响应不得泄露数据库字段、trace、lease token 或供应商原始响应；授权详情只在有权范围内返回。",
            "精简不能删除账号、模型、内容审核、系统恢复或教师证据下钻的实质动作。",
        ],
        [
            "新增递归、允许摘要式的后台审计写入入口，并替换 F9 管理操作中的临时审计拼装。",
            "收口正式角色路由元数据和后端响应字段，继续复用已有教师/管理员页面，不增加视觉卡片或说明文本。",
            "为审计失败、高风险写入失败、权限撤销和敏感字段嵌套建立确定性测试。",
        ],
        [
            "对审计行、API 响应和浏览器 DOM 执行敏感词及嵌套敏感值扫描。",
            "验证高风险后台写入在审计无法落库时整体失败并回滚，普通只读页面仍可给出业务化错误。",
            "复跑 F9-T03 E2E，确认四项管理员入口和教师工作区没有企业、专家、组织或内部阶段噪音。",
        ],
    ),
    "G23-R01": item(
        "未登录打开产品仍先到作品展示页；F9-T04 的授权收口不能把公开入口改成后台登录或无提示错误。",
        [
            "展示页保持公开且不依赖教师、管理员或课程权限。",
            "已有有效三角色会话可以按服务端身份落到对应工作区；无效或非正式角色不能越过展示/登录边界。",
        ],
        [
            "保护 /landing 路由和公开首屏，不改 F1 已关闭视觉；仅验证服务端身份恢复与角色落点兼容。",
        ],
        [
            "无 token 访问根路由和受保护路由分别回到展示/登录流程；三类有效 token 落到各自工作区。",
            "双桌面 E2E 检查展示页仍是公开第一入口。",
        ],
    ),
    "G23-R02": item(
        "展示页的进入动作仍把用户带到登录页，F9-T04 不增加访客后台、角色选择绕行或直接进入管理页的旁路。",
        [
            "未认证用户不能通过深链跳过登录；登录过期后回到可理解的登录流程并保留安全返回位置。",
            "展示页到登录页不产生学习事件、掌握证据或后台审计噪音。",
        ],
        [
            "保护 /landing 到 /login 的既有导航和全局守卫；验证身份错误时不出现死路。",
        ],
        [
            "浏览器点击展示页主动作进入 /login，未认证深链被同一流程接管，业务表计数不变。",
        ],
    ),
    "G23-R03": item(
        "登录和正式授权只承认学生、教师、管理员三类产品角色；服务端返回角色是唯一权威，前端选择不得提升权限。",
        [
            "assistant、visitor、企业、评委、集成等历史值可以作为兼容数据存在，但不能获得正式学生、教师或管理员工作区权限。",
            "普通学生不能进入教师/管理员接口；教师不能进入管理员接口；管理员访问教师聚合时仍遵循产品允许的审计边界。",
        ],
        [
            "收口认证依赖、对象授权和正式路由 roles 元数据，保留 Login.vue 已关闭的三段角色界面。",
            "用 /api/auth/me 返回的服务端角色校验路由，测试 localStorage 伪造和旧角色 token。",
        ],
        [
            "学生/教师/管理员/assistant 四类身份执行教师和管理员 API 权限矩阵，只有合同允许的组合成功。",
            "静态检查登录选项与目标路由只含三类正式角色，浏览器篡改本地角色仍被服务端拒绝。",
        ],
    ),
    "G23-R04": item(
        "助教、企业、集成、评委和访客不再作为可选择登录角色或正式后台权限来源；历史账号不需要破坏性删除，但默认无正式工作区权限。",
        [
            "不能通过删除历史角色破坏旧数据、消息中的 assistant 内容角色或原版回滚能力。",
            "管理员账号列表只管理三类正式角色，新建或变更不能赋予历史扩展角色。",
        ],
        [
            "从正式前端角色元数据和通用教师依赖中移除账号型 assistant 授权；不修改聊天消息的 assistant 内容角色。",
            "保留数据库兼容枚举，依靠服务端正式角色门禁阻止旧账号进入后台。",
        ],
        [
            "静态区分账号角色与聊天消息角色，确认只收口前者；旧 assistant 账号访问正式路由返回 403。",
            "管理员账号 API 继续只列出并只允许 student/teacher/admin。",
        ],
    ),
    "G24-R01": item(
        "学生有证据意义的作答、实操、复述和学习完成继续形成统一学习事件；F9 后台授权、浏览和审计操作不是学生学习行为。",
        [
            "教师读取、管理员查看、账号变更、内容审核和系统恢复不得写 DBLearningEvent。",
            "教师发布干预可以创建待办路径，但不能伪造成学生已经完成的学习事件。",
        ],
        [
            "保护 F2 学习事件写入链；F9-T04 只增加独立 DBAuditLog 记录和权限守卫。",
        ],
        [
            "后台读写前后比较学习事件计数与内容，只有既有学生可信动作允许变化。",
        ],
    ),
    "G24-R02": item(
        "统一事件对画像、掌握度、路径和计划的影响继续由既有聚合器决定；F9 权限与审计不能直接写这些结论。",
        [
            "管理员或教师的主观账号操作、审核决定和系统重试不构成掌握证据。",
            "教师干预只成为学生待完成任务，学生产生真实证据后才进入既有聚合。",
        ],
        [
            "保护 DBProfileSnapshot、DBStudentProfile、DBLearningPath 和聚合接口；授权测试覆盖零越权写入。",
        ],
        [
            "执行教师/管理员动作前后核对画像、掌握度和学习计划未被直接修改，并复跑可信事件聚合回归。",
        ],
    ),
    "G24-R03": item(
        "不同学习事件的证据类型和强度仍由 F2 聚合规则加权，F9 后台审计日志不能参与证据权重。",
        [
            "DBAuditLog 与 DBLearningEvent 保持不同事实表和语义；任何 action 名称都不能被误投影为掌握证据。",
        ],
        [
            "不改证据权重算法；用独立审计写入和回归断言保护事件分类。",
        ],
        [
            "写入教师/管理员审计后重放学习聚合，断言证据输入、权重和掌握结果不变。",
        ],
    ),
    "G24-R04": item(
        "页面浏览、筛选、展开以及教师/管理员只读访问保持零掌握度影响；授权检查失败同样不能产生学习结果。",
        [
            "无权限请求不得留下部分业务写入；只读请求即使成功也只能产生必要访问日志，不能产生学习事件。",
        ],
        [
            "为三角色矩阵和 F9 页面只读旅程记录业务表前后快照，保护普通浏览零写入合同。",
        ],
        [
            "比较 DBLearningEvent、画像、路径节点和掌握度，覆盖成功读取、403、404 和前端篡改四类场景。",
        ],
    ),
    "G24-R05": item(
        "学习聚合结论继续可由原始学习事件重放；后台任务重试和审计重试不能改变或替代原始事件。",
        [
            "系统任务恢复只恢复失败步骤并复用原任务幂等身份，不能创建重复学习证据。",
            "审计日志用于责任追踪，不成为重放的第二事实源。",
        ],
        [
            "保护 F2 聚合重放与 F9-T03 管理任务幂等行为，新增跨表不污染断言。",
        ],
        [
            "重复执行管理员任务恢复并重放聚合，断言原始事件、聚合结果和已有产物均不重复。",
        ],
    ),
    "G24-R06": item(
        "资源或教师干预任务的完成状态继续与知识掌握证据分离；F9 后台只能安排、审核或恢复对象，不能替学生证明掌握。",
        [
            "教师发布干预可增加路径/任务，教师关闭干预不能直接提高掌握度。",
            "管理员批准资源只改变可见性，账号或模型操作不改变学生任务完成状态。",
        ],
        [
            "保护 m6_teacher 的只安排不改掌握规则和内容审核可见性边界；新审计只记录最小后台摘要。",
        ],
        [
            "发布干预、审核资源和恢复任务后分别核对路径变化与掌握度不变，学生可信完成后再验证既有聚合。",
        ],
    ),
    "G24-R07": item(
        "后台高风险写操作、干预发布和失败任务恢复继续使用幂等或并发版本门禁；失败重试不得重复计分、重复任务或重复审计。",
        [
            "账号版本冲突返回 409；任务重试只重放失败步骤；相同干预幂等键返回同一对象。",
            "审计与业务写入必须在同一事务中成功或一起回滚，不能业务成功而审计丢失。",
        ],
        [
            "统一后台审计写入后复用现有账号 expected_version、任务状态和干预 idempotency_key。",
        ],
        [
            "重复、并发冲突和审计故障测试分别核对业务对象、步骤、学习事件与审计行数量。",
        ],
    ),
    "G27-R01": item(
        "既有画像驱动的难度、表达和资源组合差异继续由学生闭环产生；F9 后台只能观察脱敏摘要，不能把教师或管理员偏好写回学生画像。",
        [
            "教师看到证据化差异但不能直接改掌握度或伪造个性化结果。",
            "后台授权收口不得把三画像或冻结演示结果冒充真实学生成绩。",
        ],
        [
            "保护 F2/F3/F7 个性化协议和教师只读画像接口；本任务不改生成算法。",
        ],
        [
            "三画像保护回归与教师只读快照比较，确认后台动作不改变个性化输入或结果。",
        ],
    ),
    "G27-R02": item(
        "分析、生成、校验和决策的多 Agent 协作继续通过批准的公开摘要结构展示，后台审计只记录操作责任，不复制私有执行日志。",
        [
            "Agent 职责与候选摘要可以展示，系统提示词、隐藏推理、原始工具日志和供应商输入不能展示或写审计。",
        ],
        [
            "复用 agent_audit 的公开投影；新后台审计模块对所有嵌套摘要执行敏感字段清洗。",
        ],
        [
            "公开 Agent payload 字段集合测试与审计递归扫描同时通过。",
        ],
    ),
    "G27-R03": item(
        "用户只看到交叉校验发现了什么分歧、如何修订和最终决定，不看到私有推理过程；F9 教师详情与内容审核继续使用该公开投影。",
        [
            "分歧和修订必须是简短业务摘要，不能塞入完整候选正文、真实学生敏感原文或 trace。",
        ],
        [
            "保护 teacher_api 和内容审核的公开 Agent 字段；审计只引用公开摘要或对象 ID。",
        ],
        [
            "教师详情、内容审核和审计行扫描确认仅含 approved public audit fields。",
        ],
    ),
    "G27-R04": item(
        "来源引用和审核结果继续作为缓解幻觉的可见证据；授权收口必须确保教师只看本课程来源、管理员按职责审核。",
        [
            "跨课程来源与审核对象不得通过 IDOR 泄露；来源缺失不能伪装成审核通过。",
            "审核决定不产生学习掌握事件。",
        ],
        [
            "课程范围守卫覆盖教师来源/学生详情，管理员审核使用管理员角色；保护现有来源和审核 payload。",
        ],
        [
            "跨课程对象 ID、未授权审核和来源缺失用例分别验证 403/404、诚实状态及零学习写入。",
        ],
    ),
    "G27-R05": item(
        "Agent 协作信息继续嵌在真实问答、资源、教师证据和审核流程中；F9-T04 不新增独立技术说明页或审计工作台入口。",
        [
            "后台审计默认是授权详情，不成为学生、教师一级导航或营销说明。",
            "已有真实任务中的 Agent 摘要可见性不能因安全收口被全部删除。",
        ],
        [
            "只调整权限和数据投影，保护 /learn、教师详情和内容审核中的已有嵌入位置。",
        ],
        [
            "路由/导航静态检查不存在新增 Agent 技术页，浏览器仍能在原业务位置查看公开协作摘要。",
        ],
    ),
    "G27-R06": item(
        "任何教师、管理员、审计或 Agent API 都不得返回或持久化私有思维链、系统提示词、API Key、令牌、密码、真实敏感原文和冗长原始日志。",
        [
            "清洗必须递归处理不同大小写、连字符/下划线、嵌套字典和数组，不能只检查顶层精确键。",
            "安全清洗不能通过把原文换个键名继续保存；允许的 before/after 只能是字段级或状态级摘要。",
            "发现不安全审计内容时高风险写入必须失败回滚，不能静默丢审计后继续成功。",
        ],
        [
            "新增 app/audit_log.py 作为后台审计唯一写入路径，使用允许摘要和递归拒绝/清洗策略。",
            "迁移 F9 管理写操作与教师干预到统一审计入口，并为 API 响应、数据库审计和 DOM 建立敏感扫描。",
        ],
        [
            "构造顶层、嵌套、数组、大小写和同义敏感字段，验证不会进入 DBAuditLog 或响应。",
            "模拟审计写入失败，确认账号、任务和干预等高风险业务事务回滚。",
        ],
    ),
    "G27-R07": item(
        "外部模型容量、认证、限流或超时必须显示真实失败或降级状态；已有资源可继续使用，但不能伪装 Agent 已完成。",
        [
            "F9-T04 不调用外部模型；模型状态只读取已有脱敏分类和冻结结果。",
            "失败详情不得包含供应商原文、密钥、提示词或私有 trace，系统任务重试保留已有成功产物。",
        ],
        [
            "保护管理员模型/系统状态的错误分类和已有结果保留，统一审计只记录 failure category 与动作摘要。",
        ],
        [
            "容量、认证、限流和超时夹具验证状态区分、敏感信息缺失、已有产物保留和未调用外部网络。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F9-T04_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F9-T04 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in UNDERSTANDING]
    extra = [atom_id for atom_id in UNDERSTANDING if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic understanding mismatch: missing={missing}, extra={extra}")
    if len(actual_ids) != len(set(actual_ids)):
        raise RuntimeError("F9-T04 ledger contains duplicate atomic requirement IDs")

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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F9-T04")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id=GOAL_ID,
        task="F9-T04",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F9-T04 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
