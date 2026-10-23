#!/usr/bin/env python3
"""Classify current backend routes and ORM models for fusion planning.

The output is a planning artifact. It does not delete, migrate, or modify
runtime objects. Classification is intentionally conservative: core learning
objects are reusable, enterprise/integration/media production objects remain
hidden or deferred until a later product decision.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def scope(
    disposition: str,
    destination: str,
    phase: str,
    role: str,
    user_value: str,
    boundary: str,
) -> dict[str, str]:
    return {
        "disposition": disposition,
        "destination": destination,
        "phase": phase,
        "role": role,
        "user_value": user_value,
        "boundary": boundary,
    }


def classify_m5(path: str) -> dict[str, str]:
    if any(token in path for token in ("model-governance", "model-operations", "legacy-migration")):
        return scope("管理员后台复用", "管理员/模型配置与系统状态", "F9", "管理员", "保证模型调用和旧数据迁移可监控、可恢复", "不得展示给学生或作为学习掌握证据")
    if path.endswith("/capabilities") or path.endswith("/route"):
        return scope("内部基础设施", "统一能力路由与请求预检", "F2", "系统", "把页面动作路由到已有能力并在调用前发现缺失条件", "只作为聚合层，不生成独立页面")
    if "/resources" in path:
        return scope("核心闭环复用", "学习空间/资源中心与资源详情", "F5", "学生/教师", "检索、打开、比较、修订、导出和归档个性化资源", "编辑产生版本；查看和导出不直接改变掌握度")
    if any(token in path for token in ("/plans", "/paths", "planning-targets", "textbook-path-draft", "/today")):
        return scope("核心闭环复用", "学习空间/学习路径与首页今日任务", "F4", "学生/教师", "生成、确认、调整并执行可恢复的个性化路径", "路径状态必须合法迁移并保留历史版本")
    if "/learning-events" in path:
        return scope("统一底座适配", "统一学习事件处理器", "F2", "系统", "让资源、测评、实操和复习动作产生一致的跨页更新", "事件必须幂等，重放不能重复计分")
    if any(token in path for token in ("assessment", "review-queue", "review-export", "retest", "workspace/exercises")):
        return scope("核心闭环复用", "入学诊断、测验题资源、智能组卷、错题与复习", "F3/F6/F8", "学生/教师", "完成诊断、资源内即时练习、正式组卷、错因确认和复测", "测评中心只保留入学诊断和智能组卷；候选错因不得代替学生确认，评分证据需回链题目版本")
    if "profile-summary" in path:
        return scope("核心闭环复用", "首页/个人中心/学习画像摘要", "F4/F8", "学生/教师", "提供一致的掌握、证据和下一步摘要", "摘要只读统一画像事实，不单独计算第二套掌握度")
    if "/tutor-contexts" in path:
        return scope("闭环子能力", "智能对话/学习对象 AI 伙伴", "F7", "学生", "携带课程、来源和当前资源上下文继续提问", "上下文预检与对话事件分开记录")
    if "/workspace" in path:
        return scope("核心闭环复用", "统一学习空间", "F5/F6", "学生", "恢复今日任务、资源、练习和本地实操动作", "工作区任务状态不能作为掌握度，只有完成证据可更新画像")
    if "/tasks" in path:
        return scope("统一底座适配", "资源生成任务与四阶段进度", "F5", "系统/学生查看", "创建、启动、恢复、重试和局部返工生成任务", "工程步骤默认折叠，失败必须可恢复")
    return scope("内部基础设施", "M5 聚合服务兼容层", "F2-F8", "系统", "承接现有学习平台内核并迁移到正式产品模块", "不得以 M5 名称或通用工作台暴露给用户")


def classify_route(path: str, file: str) -> dict[str, str]:
    route = path.lower()
    haystack = f"{route} {file.lower()}"

    if route.startswith("/api/v1/m5/"):
        return classify_m5(route)
    if route.startswith("/api/v1/m1/") or "/api/v1/objects" in route:
        return scope("统一底座适配", "课程/画像/来源/资源/事件统一对象层", "F2", "系统", "为跨页闭环提供稳定对象身份、权限和证据关系", "内部对象接口不得直接成为学生页面")
    if route.startswith("/api/v1/m2/"):
        return scope("统一底座适配", "学习空间/资源生成任务兼容层", "F2/F5", "系统/学生查看", "复用冻结上下文、生成、质量检查、反馈和资源包能力", "迁移后不保留 golden/M2 产品术语")
    if route.startswith("/api/v1/m3/"):
        if any(token in route for token in ("profiles", "diagnose", "matching-report")):
            return scope("核心闭环复用", "首次引导/诊断与学习画像", "F3/F4", "学生", "根据差异化背景定位盲区并生成匹配报告", "画像结论必须带来源和证据，不覆盖用户可编辑背景")
        if "/interactive/" in route:
            return scope("闭环子能力", "学习空间/交互模型与实操证据", "F6", "学生", "记录参数实验动作和可验证结果", "交互动作必须完成后才能作为画像证据")
        return scope("核心闭环复用", "多 Agent 生成、校验、决策与资源包", "F3/F5/F7", "学生/系统", "完成分析-生成-校验-决策并产出可追溯资源", "只展示结构化阶段、来源、分歧和决定，不展示私有思维链")
    if route.startswith("/api/v1/m4/"):
        return scope("内部评测保留", "内部量化评测与盲测证据", "系统完成后", "内部评测者", "运行冻结样例、标注和报告以验证赛题指标", "当前不启动评测；gold 和标注不得进入产品输入")
    if route.startswith("/api/v1/m6/"):
        if "/teacher/interventions" in route:
            return scope("教师后台复用", "教师/测评与干预", "F9", "教师", "把学生证据转成可跟踪干预并复核结果", "教师任务不直接改掌握度，学生完成后才更新")
        return scope("后台/延期", "企业培训可选扩展", "F9 后", "内部演示/未来企业管理员", "用合成岗位标准演示能力差距与培训任务", "不宣称真实企业验证、专家认证或真实岗位数据")
    if route.startswith("/api/v1/m7/") or any(token in route for token in ("/integration-", "/local-sso", "/local-hr", "/local-lms", "/local-webhook")):
        return scope("后台/延期", "企业集成与可靠性证据", "F9 后", "管理员/内部测试者", "验证 SSO、HR、LMS、LRS、webhook、对账和故障恢复", "只操作冻结合成/本地模拟数据，不改原学习事实")
    if route.startswith("/api/v1/m8/"):
        return scope("内部证据/延期", "部署预检与系统硬化", "F10 后", "管理员/开发者", "在交付阶段检查运行依赖和安全边界", "当前方案阶段不启动部署或硬化验收")
    if route.startswith("/api/v1/next/core/memor") or "memory-" in route:
        return scope("闭环子能力", "设置/个人记忆与画像上下文", "F2/F8", "学生", "让用户查看、撤回和控制长期学习记忆", "敏感记忆默认私有，可撤回，不能替代画像证据")
    if "cross-language-search" in route:
        return scope("闭环子能力", "知识库/跨语言检索", "F7", "学生/教师", "在中英文课程资料中找到同一知识点来源", "检索结果仍需来源定位和权限检查")

    if route.startswith("/api/auth"):
        return scope("核心闭环复用", "登录、注册与身份", "F1/F2", "访客/三类角色", "安全进入正确角色工作区", "只允许学生、教师、管理员正式入口；权限在后端验证")
    if route.startswith("/api/v1/courses/"):
        return scope("核心闭环复用", "全局课程上下文与课程大纲", "F2/F3/F7", "学生/教师", "为诊断、路径、知识库和资源提供同一门课程及章节结构", "课程 ID 与权限必须统一，不能在各页面自建课程副本")
    if route.startswith("/api/v1/internal/"):
        return scope("内部证据/延期", "内部对象、关系与调用追踪检查", "F0/F10", "开发者/授权评委", "只读核对课程、资源、任务和 trace 的一致性", "不进入普通导航，不写业务对象或学习事件")
    if route.startswith("/api/v1/generation-tasks"):
        return scope("统一底座适配", "学习空间/资源生成任务", "F2/F5", "系统/学生查看", "创建、查询和恢复统一生成任务", "任务步骤是运行状态，不等同于学习掌握证据")
    if route.startswith("/api/v1/artifacts"):
        return scope("核心闭环复用", "学习空间/统一资源对象与版本", "F2/F5", "学生/教师", "创建、读取和版本化讲义、实训任务书、测验题、课件等学习资源", "资源版本不可覆盖历史；来源与质量状态必须可查")
    if route == "/":
        return scope("内部基础设施", "SPA/服务入口", "F1", "系统", "提供应用入口与前端静态资源", "不是产品功能端点，不写业务数据")
    if route == "/api/v1/video/stream":
        return scope("闭环子能力", "知识库/学习空间视频播放", "F5/F7", "学生/教师", "以受控方式播放课程视频资源", "播放位置与完成/微测事件分开记录，路径需校验")
    if route.startswith("/api/teacher") or "course-governance" in route or "teaching-analytics" in route:
        return scope("教师后台复用", "教师/教学总览、课程资源、学生学情、测评干预", "F9", "教师", "查看班级证据、维护课程任务、生成报告并发起干预", "查看和报告不改学生掌握度；干预须显式发布")
    if "content-review" in route:
        return scope("管理员后台复用", "管理员/内容审核", "F9", "管理员", "审核资源来源、质量和风险后决定发布状态", "审核只改变资源可见性，不改学习事实")
    if "model-operations" in route or route in {"/api/llm/test", "/api/llm/test-vision", "/api/metrics", "/api/health"}:
        return scope("管理员后台复用", "管理员/模型配置与系统状态", "F9", "管理员", "检查模型连接、错误、配额和系统健康", "不得在学生页面展示调用日志或密钥")
    if route.startswith("/api/profile") or route.startswith("/api/v1/profile") or route.startswith("/api/progress"):
        return scope("核心闭环复用", "学习画像/个人中心", "F2/F4/F8", "学生/教师按权限", "查看或维护背景、掌握、证据、建议和成长报告", "用户字段与推断字段分离；画像变化必须可解释")
    if route.startswith("/api/knowledge") or route.startswith("/api/v1/source-refs") or route.startswith("/api/web"):
        return scope("核心闭环复用", "知识库/文档阅读、来源与联网发现", "F7", "学生/教师", "导入、检索、阅读、定位来源并从资料生成学习资源", "联网内容先作为候选来源，不能直接污染权威课程库")
    if route.startswith("/api/quiz"):
        return scope("核心闭环复用", "入学诊断、学习空间/测验题资源、错题和复习", "F3/F6/F8", "学生", "生成题目、即时判分、错题归因、相似题和复习打卡", "资源内题组不进入测评中心；答案、题目版本和来源必须可追溯")
    if route.startswith("/api/notes") or "export-notes" in route:
        return scope("核心闭环复用", "学习空间/笔记本", "F8", "学生", "创建、编辑、排版、导出并关联课程知识点", "普通编辑不直接提高掌握度")
    if route.startswith("/api/review") or route.startswith("/api/flashcard"):
        return scope("核心闭环复用", "学习空间/复习中心与笔记闪卡", "F8", "学生", "按日历和间隔重复完成复习并形成长期反馈", "打卡和评分需幂等，不能重复计分")
    if route.startswith("/api/code"):
        return scope("闭环子能力", "学习空间/代码沙盒", "F6", "学生", "运行代码、保存结果并获得基于运行证据的点评", "受限运行；代码成功不等于概念已掌握")
    if route.startswith("/api/stream") or route == "/api/process" or route.startswith("/api/history") or route.startswith("/api/sessions"):
        return scope("核心闭环复用", "智能对话与历史", "F5/F7", "学生/教师", "流式问答、启发式解释、恢复会话并发起资源生成", "回答必须来源约束和失败降级；历史查看不改画像")
    if route.startswith("/api/behavior") or route.startswith("/api/feedback"):
        return scope("统一底座适配", "学习行为与产品反馈采集", "F2/F10", "学生/系统", "记录明确学习动作或用户反馈供聚合和体验改进", "行为日志最小化、脱敏并与掌握证据分权")
    if route.startswith("/api/datasets"):
        return scope("内部证据/延期", "冻结演示/测试数据索引", "F0/F10", "内部操作者", "列出可复现的领域数据和差异化画像样例", "不向普通用户暴露数据文件或真实个人信息")

    if "interactive-lab" in route:
        return scope("闭环子能力", "学习空间/可交互模型资源", "F6", "学生", "使用参数、滑块和图表运行机器学习实验并比较现象", "不保留独立参数实验页面；运行结果与观察题共同构成技能证据")
    if "media-context" in route or "media-ocr" in route:
        return scope("闭环子能力", "智能对话/知识库多模态上下文", "F7", "学生/教师", "解析图片、文档、代码或视频并保存可恢复上下文", "解析成功后才能提问；位置事件不直接提分")
    if "/speech" in route:
        return scope("闭环子能力", "学习空间/费曼复述的可选语音输入", "F6", "学生", "录音、转写并提交口述练习", "文本必须作为稳定回退；语音能力不作为核心闭环依赖")
    if "resource-bundles" in route:
        return scope("闭环子能力", "学习空间/九类资源包", "F5", "学生/教师", "从今日知识点批量生成、版本化和恢复九类学习资源", "资源项分别归档和记录完成；只有今日必做任务参与组卷门禁，资源包不重复计分")
    if "web-decks" in route:
        return scope("闭环子能力", "学习空间/PPT 与网页课件", "F5", "学生/教师", "预览、编辑、版本化和导出个性化课件", "学习完成后才写掌握证据")
    if any(token in route for token in ("chapter-videos", "video-practices", "video-catalog")):
        return scope("闭环子能力", "知识库/学习空间视频资源", "F5/F7", "学生/教师", "发现、绑定、观看课程视频并连接微测或实验", "视频来源和许可可查；视频生成不阻塞主线")
    if "video-imports" in route:
        return scope("教师后台复用", "教师/课程视频导入", "F9", "教师", "导入本地视频和字幕并绑定课程来源", "导入不等于学习完成")
    if "video-projects" in route or "wrong-question-videos" in route:
        return scope("内部证据/延期", "视频生成与错题视频扩展", "核心完成后", "教师/内部制作者", "生成和版本化微课视频产物", "视频生成明确后置，不得阻塞三类必需资源")
    if "teaching-animations" in route or "/animations" in route:
        return scope("闭环子能力", "学习空间/可交互模型资源", "F5/F6", "学生/教师", "把动画和参数变化作为可交互模型的一种呈现模板", "不保留独立教学动画入口；完成观察题后才形成掌握证据")
    if "marketplace" in route and "organization-marketplace" not in route:
        return scope("轻量产品保留", "学习市场", "F9", "学生/教师", "发布、搜索、预览、收藏和保存资源/路径副本", "复杂举报、版本分叉和责任事件默认后台化")
    if "course-sharing" in route:
        return scope("轻量产品保留", "学习市场/发布与副本更新", "F9", "学生/教师", "发布带来源许可的课程副本并处理上游更新", "保存副本不改变掌握度")
    if "organization-marketplace" in route:
        return scope("后台/延期", "组织私有市场扩展", "F9 后", "内部演示/未来组织管理员", "演示组织内资源发布和获取", "不进入当前校内轻市场")
    if any(token in route for token in ("enterprise-risk", "certification-lifecycle", "job-standard-impact", "multilevel-review")):
        return scope("后台/延期", "企业治理或高级审核扩展", "F9 后", "内部演示/未来管理员", "用合成数据演示风险、认证、岗位变化或多级审核", "不宣称真实专家/企业认证，不阻塞比赛闭环")
    if "/plugins" in route or "spatial-workspaces" in route or "local-adapters" in route:
        return scope("内部证据/延期", "高级扩展与可迁移性证据", "F10 后", "管理员/开发者", "验证领域插件、空间实验或本地适配器", "不进入普通导航，不取代统一学习空间或代码沙盒")
    if "competition-" in route:
        return scope("内部证据/延期", "比赛演示控制与评委旅程", "系统完成后", "管理员/评委", "初始化冻结演示数据并按旅程查看闭环证据", "演示访问与真实学习事件隔离")

    return scope("未分类", "未确定", "F0 复核", "待定", "待根据调用链确定", "不得进入实施或普通产品")


CORE_MODEL_GROUPS: list[tuple[set[str], dict[str, str]]] = [
    ({"DBUser", "DBCourse", "DBCourseMembership"}, scope("核心事实源", "身份与课程上下文", "F1/F2", "系统/三类角色", "统一用户、角色、课程和成员权限", "后端权限校验，页面不得信任前端角色")),
    ({"DBStudentProfile", "DBAlignmentLog", "DBProfileSnapshot", "DBProfileEvidence", "DBConceptCoordinate"}, scope("核心事实源", "学习画像与掌握证据", "F2/F3/F4", "学生/教师按权限", "表达背景、掌握、证据、图谱位置和可解释变化", "用户字段与推断字段分离；坐标缓存不作为掌握证据")),
    ({"DBConversationHistory", "DBMemoryItem", "DBMemorySubscription"}, scope("闭环子能力", "智能对话历史与可控长期记忆", "F2/F7/F8", "学生", "恢复对话和受控学习上下文", "记忆可撤回、过期和审计，不替代正式画像证据")),
    ({"DBNote", "DBFlashcard", "DBFlashcardVersion", "DBReviewPlan", "DBCheckinLog"}, scope("核心事实源", "笔记、闪卡与复习", "F8", "学生", "保存个人沉淀并安排可追踪复习", "打卡与评分幂等，笔记编辑不直接提分")),
    ({"DBCourseDocument", "DBSourceDocument", "DBKnowledgeDocument", "DBChapter", "DBKnowledgePoint", "DBChapterKnowledgePoint", "DBSourceRef"}, scope("核心事实源", "课程知识库、章节、知识点与来源", "F2/F7", "学生/教师", "提供可定位、可检索的领域知识和生成依据", "候选联网来源与课程权威来源分层")),
    ({"DBGenerationTask", "DBArtifact", "DBArtifactVersion", "DBArtifactRelation", "DBTaskStep", "DBTaskEvent", "DBTutorContextSession"}, scope("核心事实源", "资源、生成任务、版本和学习上下文", "F2/F5/F7", "学生/教师", "让生成产物可保存、修改、追踪、恢复和继续学习", "任务步骤不等于学习证据，资源修改不覆盖历史")),
    ({"DBPlanDraft", "DBPlanVersion", "DBLearningPath", "DBPathNode", "DBLearningEvent", "DBLearningEventConsumption"}, scope("核心事实源", "路径、计划与统一学习事件", "F2/F4-F8", "学生/系统", "驱动今日任务和跨页一致更新", "路径保留版本；事件消费必须幂等")),
    ({"DBQuizRecord", "DBQuizItem", "DBAssessmentQuestion", "DBAssessmentQuestionVersion", "DBAssessmentAttempt", "DBAssessmentGradingResult", "DBAssessmentAbilityState", "DBAssessmentSelectionTrace", "DBAssessmentExam", "DBAssessmentExamVersion", "DBAssessmentExamItem", "DBAssessmentExamSitting", "DBAssessmentExamResponse", "DBAssessmentReviewCase", "DBAssessmentExamReport", "DBMisconceptionReview", "DBAssessmentRetestTask", "DBWrongQuestion"}, scope("核心事实源", "诊断、练习、考试、错题和复测", "F3/F6/F8", "学生/教师", "记录题目版本、作答、评分、误区和后续验证", "候选错因需确认；题目与答案来源可追溯")),
    ({"DBCodeExecution"}, scope("闭环子能力", "代码沙箱与实操证据", "F6", "学生", "保留代码、输出和错误用于 AI 点评与技能判断", "受限执行；成功运行不自动等于理解")),
    ({"DBAgentRun", "DBQualityCheck", "DBClaimCheck", "DBDebateRound", "DBDecisionRecord"}, scope("核心事实源", "多 Agent 运行、交叉验证与决策证据", "F3/F5/F7", "学生查看摘要/系统", "证明分析-生成-校验-决策、来源核查和动态动作选择", "不公开私有思维链、提示词或无关内部日志")),
    ({"DBDomainPack", "DBDomainVersion", "DBJobTask", "DBSkillStandard"}, scope("核心事实源", "垂直领域包、工程任务和技能标准", "F2/F5/F6", "学生/教师", "把 AI/ML 理论知识连接到工程任务、证据和验收标准", "首版使用冻结演示标准，不宣称来自真实企业")),
]


def classify_model(name: str, table: str) -> dict[str, str]:
    for names, result in CORE_MODEL_GROUPS:
        if name in names:
            return result
    lower = f"{name} {table}".lower()
    if name in {"DBReviewDecision", "DBPublication", "DBAuditLog", "DBSchemaMigration"}:
        return scope("治理事实源", "资源审核、发布与系统审计", "F2/F9", "管理员/系统", "控制资源发布并保留可追溯决定", "审核不改变学习掌握；迁移记录不暴露给普通用户")
    if name in {"DBModelCall", "DBModelQuotaBucket", "DBModelPriceVersion", "DBWorkerLease"}:
        return scope("管理员后台复用", "模型配置、配额与任务运行", "F9", "管理员/系统", "追踪模型调用成本、失败、容量和工作任务恢复", "密钥、原始提示和敏感输入不得在页面泄露")
    if name.startswith("DBEvaluation"):
        return scope("内部评测保留", "量化评测、标注与报告", "系统完成后", "内部评测者", "验证幻觉防控、适配和覆盖指标", "当前不运行；gold 与模型输入严格隔离")
    if name.startswith("DBTeaching") or name in {"DBCourseWithdrawal", "DBContentReviewCase", "DBContentReviewDecision"}:
        return scope("教师/管理员后台复用", "课程治理、教学分析与内容审核", "F9", "教师/管理员", "维护班级课程、教学任务、报告和资源审核", "后台决定与学生学习证据分层")
    if name.startswith("DBCourseShare") or name.startswith("DBCourseDerived"):
        return scope("轻量产品保留", "学习市场/课程分享与副本", "F9", "学生/教师", "发布可追溯课程副本并处理更新或撤回", "保存副本不改变画像")
    if name.startswith("DBMarketplace"):
        if any(token in name for token in ("Report", "CommentEvent", "ReviewEvent", "Impact", "Fork")):
            return scope("市场后台/简化", "学习市场后台治理与版本历史", "F9 后", "管理员/高级发布者", "保留举报、影响通知、事件和分叉证据", "普通市场只展示发布、预览、收藏和保存")
        return scope("轻量产品保留", "学习市场", "F9", "学生/教师", "支持条目发布、评论、收藏、评价、推荐和保存副本", "市场互动与学习掌握分开")
    if name.startswith("DBOrganizationResource"):
        return scope("后台/延期", "组织私有市场", "F9 后", "内部演示/未来组织管理员", "演示组织内资源发布和获取", "不进入当前校内轻市场")
    if name.startswith("DBOrganization") or any(token in name for token in ("Department", "JobFamily", "JobLevel", "CompetencyStandard", "TrainingProgram", "TrainingCohort", "TrainingAssignment", "ExemptionRequest", "SkillEvidence", "Certification", "RetrainingTask", "LocalNotification", "JobStandardImpact", "EnterpriseRisk")):
        return scope("后台/延期", "企业培训与治理可选扩展", "F9 后", "内部演示/未来企业管理员", "用合成组织、岗位、培训和技能证据演示企业拓展", "不宣称真实企业、真人专家或正式认证")
    if name.startswith("DBMultilevelReview"):
        return scope("后台/延期", "高级内容审核状态机", "F9 后", "管理员/内部审核者", "保留多级审核和不可变决定", "不新增普通用户页面")
    if any(token in name for token in ("ExternalIdentity", "LocalSSO", "HRField", "HRSync", "HREmployee", "LocalLMS", "LMS", "IntegrationDelivery", "LocalLRS", "Cmi5", "LocalWebhook", "Webhook", "IntegrationReconciliation", "IntegrationRepair", "IntegrationFault")):
        return scope("后台/延期", "企业本地集成与可靠性", "F9 后", "管理员/内部测试者", "支持 SSO、HR、LMS、LRS、webhook、对账和故障恢复演示", "冻结合成/本地模拟数据，不反向篡改学习事实")
    if name.startswith("DBCompetitionJourney") or name == "DBMarketplaceJourneySearchVerification":
        return scope("内部证据/延期", "比赛演示旅程", "系统完成后", "管理员/评委", "记录评委旅程运行和访问证据", "与真实学习事件隔离")
    if name.startswith("DBSpeech"):
        return scope("闭环子能力", "费曼复述的可选语音输入", "F6", "学生", "保存录音转写和字幕片段", "文本回退必需；原始音频按隐私规则管理")
    if name.startswith("DBMedia"):
        return scope("闭环子能力", "多模态阅读和对话上下文", "F7", "学生/教师", "保存媒体资源、阅读位置和上下文会话", "位置和播放本身不自动提高掌握度")
    if name.startswith("DBVideo") or name.startswith("DBWrongQuestionVideo"):
        return scope("媒体扩展/延期", "课程视频、练习绑定与视频生成", "F5/F7 后", "学生/教师", "管理视频来源、版本、观看、微测与可选生成", "视频生成后置；观看与练习证据分开")
    if name.startswith("DBChapterVideo") or name.startswith("DBVideoPractice"):
        return scope("闭环子能力", "章节视频与微测/实验联动", "F5/F7", "学生/教师", "把视频绑定课程来源并记录观看、微测和实验关系", "完成事件按实际动作分别记录")
    if name.startswith("DBTeachingAnimation"):
        return scope("闭环子能力", "可交互模型资源", "F5/F6", "学生/教师", "作为交互模型模板版本化参数动画并保存实验状态", "不新增独立动画页面；仅观看不等于掌握")
    if name.startswith("DBWebDeck") or name == "DBWebSlide":
        return scope("闭环子能力", "PPT/网页课件资源", "F5", "学生/教师", "保存可编辑课件、页面和版本", "完成学习后才写掌握证据")
    if name.startswith("DBResourceBundle"):
        return scope("闭环子能力", "学习空间/九类资源包", "F5", "学生/教师", "聚合九类产物并保留生成状态、必做标记、顺序和版本", "包进度聚合不得重复计分；可选资源不阻塞智能组卷")
    if name.startswith("DBSpatial") or name.startswith("DBPlugin") or name.startswith("DBLocalAdapter"):
        return scope("内部证据/延期", "高级体验、插件与本地适配器", "F10 后", "管理员/开发者", "验证可迁移性和高级交互实现", "不进入普通导航，不取代学习空间/代码沙盒")
    if name in {"DBWebSearchHistory", "DBArxivCache"}:
        return scope("闭环子能力", "知识库/联网教材发现与检索历史", "F7", "学生/教师", "保存联网搜索操作和 arXiv 候选来源缓存，便于恢复和减少重复请求", "候选来源未审核前不能进入课程权威知识库；历史按用户隔离")
    return scope("未分类", "未确定", "F0 复核", "待定", "待根据调用链确定", "不得据模型存在新增页面或同义表")


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def render_scope_markdown(
    route_rows: list[dict[str, str]], model_rows: list[dict[str, str]]
) -> str:
    lines = [
        "# EduMatrix 后端端点与数据模型逐项归宿地图",
        "",
        "> 本文件由当前代码事实生成，用于未来融合实施规划。`代码存在/端点已注册/模型存在` 不等于产品已完成；处置、角色和边界均是目标产品约束。",
        "",
        f"- 已注册后端端点：{len(route_rows)} 个，全部有明确处置。",
        f"- ORM 数据模型：{len(model_rows)} 个，全部有明确处置。",
        "- 机器可读全量字段见 `fusion_scope_matrix.json`，CSV 便于筛选。",
        "",
        "## 端点逐项地图",
        "",
        "| 方法与最终路径 | 代码事实 | 处置与最终模块 | 角色与用户价值 | 数据/行为边界 | 阶段 |",
        "|---|---|---|---|---|---|",
    ]
    for row in route_rows:
        code = f"`{row['file']}:{row['line']}` `{row['function']}`"
        disposition = f"{row['disposition']} -> {row['destination']}"
        role_value = f"{row['role']}：{row['user_value']}"
        lines.append(
            f"| `{row['method']} {row['final_path']}` | {code} | {disposition} | {role_value} | {row['boundary']} | {row['phase']} |"
        )
    lines.extend(
        [
            "",
            "## 数据模型逐项地图",
            "",
            "| 模型与表 | 代码事实 | 处置与最终模块 | 角色与用户价值 | 数据边界 | 阶段 |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in model_rows:
        code = f"`{row['file']}:{row['line']}`"
        disposition = f"{row['disposition']} -> {row['destination']}"
        role_value = f"{row['role']}：{row['user_value']}"
        lines.append(
            f"| `{row['name']}` / `{row['table']}` | {code} | {disposition} | {role_value} | {row['boundary']} | {row['phase']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    routes = load_csv(args.evidence / "current_backend_routes.csv")
    models = load_csv(args.evidence / "current_data_models.csv")
    route_rows = [{**route, **classify_route(route["final_path"], route["file"])} for route in routes]
    model_rows = [{**model, **classify_model(model["name"], model["table"])} for model in models]
    unclassified_routes = [row["final_path"] for row in route_rows if row["disposition"] == "未分类"]
    unclassified_models = [row["name"] for row in model_rows if row["disposition"] == "未分类"]
    if unclassified_routes or unclassified_models:
        raise SystemExit(
            "Unclassified audit objects: routes="
            + ", ".join(unclassified_routes)
            + "; models="
            + ", ".join(unclassified_models)
        )
    report = {
        "schema_version": "1.0",
        "source": str(args.evidence.resolve()),
        "route_count": len(route_rows),
        "model_count": len(model_rows),
        "routes": route_rows,
        "models": model_rows,
    }
    (args.output / "fusion_scope_matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for filename, rows, fields in [
        (
            "current_backend_scope.csv",
            route_rows,
            [
                "method", "final_path", "file", "line", "function", "disposition",
                "destination", "role", "user_value", "boundary", "phase",
            ],
        ),
        (
            "current_data_model_scope.csv",
            model_rows,
            [
                "name", "table", "file", "line", "disposition", "destination",
                "role", "user_value", "boundary", "phase",
            ],
        ),
    ]:
        with (args.output / filename).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows({field: row.get(field, "") for field in fields} for row in rows)
    summary_lines = [
        "# 当前后端路由与数据模型融合归宿矩阵",
        "",
        "> 本文件是 F0 规划证据。处置标签不代表已完成代码改造；未标记为核心的能力保留代码但不进入学生普通导航。",
        "",
        "## 路由分类",
        "",
        "| 处置 | 数量 |",
        "|---|---:|",
    ]
    route_counts: dict[str, int] = {}
    for row in route_rows:
        route_counts[row["disposition"]] = route_counts.get(row["disposition"], 0) + 1
    for key in sorted(route_counts):
        summary_lines.append(f"| {key} | {route_counts[key]} |")
    summary_lines += ["", "## 数据模型分类", "", "| 处置 | 数量 |", "|---|---:|"]
    model_counts: dict[str, int] = {}
    for row in model_rows:
        model_counts[row["disposition"]] = model_counts.get(row["disposition"], 0) + 1
    for key in sorted(model_counts):
        summary_lines.append(f"| {key} | {model_counts[key]} |")
    summary_lines += [
        "",
        "## 强制规则",
        "",
        "1. F2 前不新增同义模型；先复用课程、画像、路径、资源、测评、事件和来源事实源。",
        "2. 后台/延期对象不进入学生一级导航；视频生成、企业集成、认证、空间和复杂市场治理不阻塞学生闭环。",
        "3. 生成器遇到未分类端点或模型会直接失败；不能以兜底标签默认进入产品。",
    ]
    (args.output / "fusion_scope_matrix.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    (args.output / "backend_model_destination_map.md").write_text(
        render_scope_markdown(route_rows, model_rows), encoding="utf-8"
    )
    print(json.dumps({"routes": len(route_rows), "models": len(model_rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
