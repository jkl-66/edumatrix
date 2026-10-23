from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / (
    "outputs/原系统融合重构执行/evidence/context_recovery/atomic_requirement_ledgers/"
    "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION/"
    "F8-T01_4DD116A982DD1C022025A2169A9456871085BB11410CEBF9FE256DAB2FED3049.json"
)

PRIMARY = {
    "G15-R01", "G15-R02", "G15-R03", "G15-R04", "G15-R05", "G15-R06",
    "G21-R07", "G21-R08", "G21-R09",
}
RELATED = {
    "G21-R01", "G21-R02", "G21-R03", "G21-R04", "G21-R05",
    "G21-R06", "G21-R10", "G21-R11", "G21-R12", "G21-R13",
}

UNDERSTANDING = {
    "G15-R01": {
        "product_meaning": "复习中心首屏必须是真实公历月视图，不是连续打卡、统计卡或按掌握度分组的列表；月历与选中日任务列表在桌面端并列。",
        "behavior_boundaries": [
            "月历按真实年月、星期和跨月占位渲染，支持上月、下月和回到今天；不得伪造日期或只展示数字摘要。",
            "采用图21的58/42信息关系而非复制竞品品牌和颜色；顶部课程筛选保留，视觉遵循雾白、白色内容面和墨蓝灰令牌。",
            "查看、切月和选日均为只读行为，不写学习事件、掌握度、打卡或完成状态。",
        ],
        "implementation_scope": [
            "由后端复习日程投影汇总既有复习计划、复测任务和真实完成记录。",
            "重构Review与RevisionCalendar的首屏为共享真实月历和选中日任务区，并把原版丰富能力保留在后续分组或渐进展开区。",
        ],
        "verification_plan": [
            "API测试平年、闰年、跨月和时区边界；前端测试真实42格月历和月份切换。",
            "双桌面E2E确认58/42布局、课程筛选、月历与任务列表同时可见且普通浏览不写证据。",
        ],
    },
    "G15-R02": {
        "product_meaning": "每个日期格要显示该日真实待复习数量及语义状态，让学生不打开日期也能判断哪天有多少任务。",
        "behavior_boundaries": [
            "数量来自同一日程投影，必须与右侧任务数一致；状态至少区分今日、逾期、已完成和未来。",
            "状态不能只靠颜色，日期格还要有文字、数量或图标；无任务日期不得显示虚假计数。",
            "同一来源任务不能重复计数，课程筛选后日期计数必须同步重算。",
        ],
        "implementation_scope": [
            "在日程响应中提供逐日计数和状态汇总，在日历单元格中稳定渲染。",
        ],
        "verification_plan": [
            "构造今日、逾期、完成、未来和重复来源任务，校验逐日计数与去重。",
            "浏览器逐日点击并比对日期格数量和右栏条数。",
        ],
    },
    "G15-R03": {
        "product_meaning": "学生点击某个日期后，右侧立即列出该日具体复习安排，包括知识点、到期时间、状态、类型、原因和下一动作。",
        "behavior_boundaries": [
            "选日只切换只读视图，不自动开始、完成或生成任务。",
            "选中日无任务时显示明确空态和一个可执行返回动作；加载或失败时保留月历和当前选日。",
            "列表顺序按到期时间、优先级和稳定ID确定，刷新后不随机跳动。",
        ],
        "implementation_scope": [
            "把选中日期作为稳定页面状态，过滤同一日程响应并渲染42%任务栏。",
        ],
        "verification_plan": [
            "测试多任务排序、空日、刷新恢复和接口失败保留选中日期。",
            "双尺寸点击多个日期，核对标题日期、任务内容和数量一致。",
        ],
    },
    "G15-R04": {
        "product_meaning": "每条安排必须有明确的去复习或开始动作，并进入该任务真正负责的学习界面，而不是只能查看统计。",
        "behavior_boundaries": [
            "SM-2任务进入回忆反馈，延迟复测进入真实题目，已有资源进入其专用深链；未知或未到期任务必须解释为何不能开始。",
            "开始失败保留当前日期、任务和已加载数据，并允许重试；不得把点击开始本身当作完成证据。",
            "不得删除原版闪卡、复测、历史曲线和任务详情能力。",
        ],
        "implementation_scope": [
            "为统一任务投影提供可执行action及稳定深链，在Review中承接需要内联完成的复习动作。",
        ],
        "verification_plan": [
            "API与前端测试各任务类型的动作、禁用原因、失败恢复和返回日历。",
            "E2E从日期任务直接开始一次真实复习。",
        ],
    },
    "G15-R05": {
        "product_meaning": "日历必须用业务状态区分今日、逾期、已完成和未来安排，并允许按当前课程筛选全部日期与任务。",
        "behavior_boundaries": [
            "状态由真实dueAt、完成记录和当前日期计算；已完成记录不能因下一次SM-2日期更新而从历史日期消失。",
            "课程筛选只显示用户可访问课程；未归类旧计划要诚实标记，不能偷偷归入当前课程。",
            "状态使用文字和图形共同表达，禁用绿色主题、浅蓝主题和低对比选中态。",
        ],
        "implementation_scope": [
            "后端解析任务课程归属并返回课程列表、状态和逐日聚合；前端筛选后同步月历与任务栏。",
        ],
        "verification_plan": [
            "测试跨课程隔离、未归类旧计划、逾期边界和完成历史保留。",
            "双尺寸E2E切换课程并确认月历计数、图例和右栏同步。",
        ],
    },
    "G15-R06": {
        "product_meaning": "复习任务详情要按上下文提供打开已有资源、生成完整复习资源包或进入已解锁智能组卷的动作；真实完成后写一次幂等统一学习事件。",
        "behavior_boundaries": [
            "资源生成必须复用F5统一生成协议、来源和画像快照；前置上下文不足时显示具体缺口，不能伪造成功。",
            "智能组卷仍由F4今日必做门禁决定，复习页不得绕过、复制或放宽门禁。",
            "只有服务端确认并带有效回忆结果的完成才可提交review_completed；浏览、开始和普通打卡不能提高掌握度。",
        ],
        "implementation_scope": [
            "在复习日程服务中解析资源生成上下文、组卷门禁和任务完成协议，并复用现有资源生成及学习聚合服务。",
            "前端只显示当前任务可用动作、处理中状态、失败重试、完成证据和归档/下一步。",
        ],
        "verification_plan": [
            "测试资源上下文齐备/缺失、组卷锁定/解锁、完成幂等冲突和统一聚合结果。",
            "E2E完成任务后返回月历，核对状态变化、事件只增加一次以及画像/路径通过统一聚合更新。",
        ],
    },
    "G21-R07": {
        "product_meaning": "学习空间中的复习中心必须首先呈现可执行的日历和选中日安排，原版高级复习工具后置但仍可达。",
        "behavior_boundaries": [
            "首屏不得继续以诊疗导出、手工添加、技术队列或统计卡作为主线。",
            "保留统一课程上下文和学习空间二级导航，兼容旧/review与/revision-calendar深链。",
        ],
        "implementation_scope": [
            "重排Review和RevisionCalendar的信息顺序，不删除既有SM-2、闪卡、复测、历史与筛选能力。",
        ],
        "verification_plan": [
            "静态合同和E2E确认首屏先见日历/安排，旧能力仍可从渐进区进入。",
        ],
    },
    "G21-R08": {
        "product_meaning": "复习知识点应能在当前上下文齐备时一键生成九类配套资源包，或在组卷门禁通过时进入智能组卷。",
        "behavior_boundaries": [
            "资源生成复用已关闭F5的九类资源、历史、版本、来源和部分失败恢复，不新建平行产物仓库。",
            "组卷按钮必须展示锁定原因并服从F4门禁；无课程、知识点、画像或来源时明确缺口。",
        ],
        "implementation_scope": [
            "从复习任务解析课程、知识点、最新画像和可用来源，调用统一资源生成；读取而不改写智能组卷门禁。",
        ],
        "verification_plan": [
            "测试九类生成请求的幂等性、归档路由、失败恢复和组卷锁定保护。",
        ],
    },
    "G21-R09": {
        "product_meaning": "完成真实复习后，任务要可见打勾，并通过统一事件和聚合链反馈到画像、路径、复习队列、动态和首页。",
        "behavior_boundaries": [
            "打勾是服务端完成结果的呈现，不是任意客户端勾选；重复提交不能重复计数。",
            "只有accepted mastery evidence改变掌握度，失败或被拒证据保留状态和原因。",
        ],
        "implementation_scope": [
            "复用review_completed事件和learning_aggregation五步投影，返回事件、聚合和下一次复习日期。",
        ],
        "verification_plan": [
            "隔离SQLite测试完成、重复、冲突、聚合失败恢复及前后画像/路径/日历状态。",
        ],
    },
    "G21-R01": {
        "product_meaning": "F8-T01只能在既有完整学习空间中改造复习入口，不能删除或改名测评、路径、九类资源、笔记、错题和资源中心。",
        "behavior_boundaries": ["保持F1已交付的二级导航和全部目标路由可达，不新增学生一级技术工作台。"],
        "implementation_scope": ["只验证并保护学习空间导航；复习页使用现有应用壳。"],
        "verification_plan": ["重跑路由/导航保护测试并从学习空间进入复习中心。"],
    },
    "G21-R02": {
        "product_meaning": "复习任务打开资源时必须使用F5/F6已交付的专用资源深链，不能把完整资源重新堆到复习页。",
        "behavior_boundaries": ["复习页只展示任务摘要和动作；资源正文、历史和版本仍由各专用页面负责。"],
        "implementation_scope": ["复用统一资源路由和context query，验证返回路径。"],
        "verification_plan": ["逐类检查深链格式并抽样浏览器往返。"],
    },
    "G21-R03": {
        "product_meaning": "复习日历必须继承同一课程、知识点和任务ContextRef，刷新或跨模块后不能丢失上下文。",
        "behavior_boundaries": ["不得通过标题猜测覆盖已有稳定ID；旧SM-2标题无法唯一映射时标记未归类。"],
        "implementation_scope": ["复用courseContext和后端owner/course权限解析，任务响应携带稳定上下文。"],
        "verification_plan": ["测试刷新、课程切换、无权课程和旧标题歧义。"],
    },
    "G21-R04": {
        "product_meaning": "复习页若提供即时解答，只能把当前复习上下文引用到既有智能对话，不在本任务复制聊天或Agent工作区。",
        "behavior_boundaries": ["保留F7来源和公开Agent审计边界；不得显示私有思维链或伪造过程。"],
        "implementation_scope": ["保护现有/learn深链和上下文参数，本任务不重写Chat。"],
        "verification_plan": ["重跑F7 Chat前端保护合同并检查复习上下文深链。"],
    },
    "G21-R05": {
        "product_meaning": "复习页进入测评时，测评中心仍只包含入学诊断和智能组卷。",
        "behavior_boundaries": ["不得新增学习中练习入口或把复测伪装成测评中心第三类。"],
        "implementation_scope": ["只读取F4智能组卷门禁并跳转现有正式组卷路由。"],
        "verification_plan": ["重跑F4测评边界与组卷门禁测试。"],
    },
    "G21-R06": {
        "product_meaning": "复习完成只能通过统一事件协同既有总路径和科目路径，不得重建或简化原路径。",
        "behavior_boundaries": ["路径今日必做、完成条件和重规划规则继续由F4负责。"],
        "implementation_scope": ["向现有聚合器提供ContextRef/taskId，验证路径投影。"],
        "verification_plan": ["重跑路径投影、先决条件和组卷门禁保护测试。"],
    },
    "G21-R10": {
        "product_meaning": "从复习任务生成的资源仍进入F5资源历史与版本体系，学生也仍可在资源中心按自定义知识点生成。",
        "behavior_boundaries": ["不得在复习页建立第二套历史、版本或下载协议。"],
        "implementation_scope": ["调用统一generation job并只保存任务链接/状态。"],
        "verification_plan": ["重跑F5资源历史、来源和幂等生成测试。"],
    },
    "G21-R11": {
        "product_meaning": "复习页不得改变两类测评中心边界；复习中的回忆反馈和延迟复测留在复习中心。",
        "behavior_boundaries": ["学习中练习继续归测验题资源，复习动作不得出现在测评中心导航。"],
        "implementation_scope": ["保护AssessmentWorkspace与FormalExamWorkspace现有结构。"],
        "verification_plan": ["静态扫描和浏览器确认测评中心仍只有入学诊断、智能组卷。"],
    },
    "G21-R12": {
        "product_meaning": "复习资源包继续把实训任务书、代码沙盒和可交互模型作为三种独立资源。",
        "behavior_boundaries": ["不得合并名称、路由、完成规则或产物类型。"],
        "implementation_scope": ["复用F5/F6九类资源类型常量和专用路由。"],
        "verification_plan": ["校验生成清单含三种独立类型并重跑相关资源合同。"],
    },
    "G21-R13": {
        "product_meaning": "复习资源包即使生成全部九类，也不能把全部可选资源强制加入智能组卷解锁条件。",
        "behavior_boundaries": ["组卷只看总路径标记的今日必做任务；复习页不得追加隐藏门禁。"],
        "implementation_scope": ["资源生成与exam gate保持分离，仅展示现有门禁结果。"],
        "verification_plan": ["构造可选资源未完成但今日必做已完成场景，确认组卷仍解锁。"],
    },
}

PLANNED_BATCHES = {
    "schedule-protocol": {
        "atoms": sorted(PRIMARY | {"G21-R03", "G21-R05", "G21-R06", "G21-R10", "G21-R11", "G21-R12", "G21-R13"}),
        "files": [
            "app/review_schedule.py", "app/review_schedule_api.py", "app/main.py",
            "frontend/src/api/path.js", "tests/test_f8_t01_review_schedule.py",
        ],
        "result": "One owner-scoped read model aggregates persisted SM-2 plans, delayed retests and real completion history into course-filtered calendar days and actionable review tasks.",
    },
    "calendar-workspace": {
        "atoms": sorted(PRIMARY | RELATED),
        "files": [
            "frontend/src/components/ReviewScheduleBoard.vue",
            "frontend/src/views/Review.vue", "frontend/src/views/RevisionCalendar.vue",
        ],
        "result": "Review and calendar routes share a 58/42 real month calendar and selected-day task rail while preserving legacy review tools behind progressive disclosure.",
    },
    "review-actions": {
        "atoms": sorted({"G15-R04", "G15-R06", "G21-R08", "G21-R09"} | RELATED),
        "files": [
            "app/review_schedule.py", "app/review_schedule_api.py",
            "frontend/src/components/ReviewScheduleBoard.vue", "frontend/src/views/Review.vue",
            "tests/test_f8_t01_review_schedule.py",
        ],
        "result": "Task actions start the correct review flow, reuse resource generation and exam-gate contracts, and record one trusted idempotent completion event before calendar refresh.",
    },
    "verification": {
        "atoms": sorted(PRIMARY | RELATED),
        "files": [
            "tests/test_f8_t01_review_schedule.py",
            "tests/test_f8_t01_review_frontend_contract.py",
            "scripts/e2e_f8_t01_review_calendar.py",
        ],
        "result": "Focused API, compatibility, build and dual-desktop browser checks reconcile every F8-T01 atom without external models or formal database writes.",
    },
    "exam-gate-fixture": {
        "atoms": ["G15-R06", "G21-R05", "G21-R06", "G21-R08", "G21-R11", "G21-R13"],
        "files": [
            "scripts/e2e_f8_t01_review_calendar.py",
        ],
        "result": "The isolated browser fixture freezes one real pending Today-required path task so the review page must display the authoritative F4 locked-exam state.",
    },
    "unclassified-filter": {
        "atoms": ["G15-R05", "G21-R03"],
        "files": [
            "frontend/src/components/ReviewScheduleBoard.vue",
            "tests/test_f8_t01_review_frontend_contract.py",
            "scripts/e2e_f8_t01_review_calendar.py",
        ],
        "result": "The unclassified legacy-plan filter uses a review-only query key and cannot be mistaken for a real course context.",
    },
    "completion-notice": {
        "atoms": ["G15-R04", "G15-R06", "G21-R03", "G21-R09"],
        "files": [
            "frontend/src/components/ReviewScheduleBoard.vue",
            "tests/test_f8_t01_review_frontend_contract.py",
            "scripts/e2e_f8_t01_review_calendar.py",
        ],
        "result": "A successful review or delayed retest keeps one visible confirmation across the route-key remount that clears the completed task query.",
    },
    "retest-remount": {
        "atoms": ["G15-R04", "G15-R06", "G21-R03", "G21-R09"],
        "files": [
            "frontend/src/components/ReviewScheduleBoard.vue",
            "tests/test_f8_t01_review_frontend_contract.py",
            "scripts/e2e_f8_t01_review_calendar.py",
        ],
        "result": "Opening a delayed retest loads it only in the route-authoritative component, preventing a remount from discarding the selected answer.",
    },
    "retest-due-fixture": {
        "atoms": ["G15-R04", "G15-R05", "G21-R03"],
        "files": [
            "scripts/e2e_f8_t01_review_calendar.py",
        ],
        "result": "The isolated delayed-retest fixture is due from the start of the current Shanghai day, so the browser can truthfully submit a task that the calendar presents as actionable.",
    },
}

BATCH_RESULTS = {
    "schedule-protocol": {
        "implementation": (
            "app/review_schedule.py and app/review_schedule_api.py add one owner-scoped F8 read/action protocol over existing "
            "DBReviewPlan, DBAssessmentRetestTask and DBLearningEvent records. It renders a real 42-day calendar, keeps "
            "unclassified legacy plans explicit, exposes direct review/retest actions, reuses the F5 nine-resource generation "
            "job, reads the F4 exam gate, and records trusted idempotent review_completed evidence through the existing five-step "
            "learning aggregation. app/main.py registers the router and frontend/src/api/path.js exposes the three client calls."
        ),
        "verification": (
            ".venv/Scripts/python.exe -m pytest tests/test_f8_t01_review_schedule.py -q -> 5 passed in 1.27s. "
            "The isolated SQLite suite verifies 42 real dates, leap/cross-month behavior, date/task count identity, course and "
            "unclassified filtering, zero writes during browsing, owner isolation, trusted completion idempotency, one check-in, "
            "five-step aggregation, canonical SM-2 continuation, nine distinct resource types and no added exam-gate rule."
        ),
        "user_result": (
            "The backend can now return one truthful month calendar with actionable review tasks and can persist one real review "
            "completion without duplicate evidence; the shared desktop calendar UI is the next batch and this task is not closed."
        ),
        "compatibility": (
            "Existing resource history, three distinct practical resource types, the two-item assessment-center boundary, the "
            "server-owned Today-required exam gate, legacy SM-2 plans, delayed retests, ContextRef ownership and the five-step "
            "learning aggregator remain the only authorities; no table, migration, formal database or external model was added."
        ),
    },
    "calendar-workspace": {
        "implementation": (
            "frontend/src/components/ReviewScheduleBoard.vue provides the shared real-month review calendar, selected-day "
            "task rail, course filter, month navigation, direct SM-2/retest/resource/chat/exam actions and persistent URL "
            "context. frontend/src/views/Review.vue and frontend/src/views/RevisionCalendar.vue place that shared calendar "
            "first and retain the legacy flashcard, retest, check-in, plan, chart and history capabilities behind progressive "
            "disclosure instead of deleting them."
        ),
        "verification": (
            "The calendar-workspace source batch is registered against all 19 F8-T01 atoms so the recovery loader can "
            "validate the changed-file scope. npm run build in frontend -> PASS, 6937 modules transformed and production "
            "assets built in 44.35s with no Vue template or import error. Frontend contract tests and dual-desktop browser "
            "evidence remain pending; this record does not claim final verification or task completion."
        ),
        "user_result": (
            "Both review entry routes now lead with one shared real calendar and an actionable selected-day schedule, while "
            "the original advanced review tools remain reachable in a secondary section. This batch still requires build and "
            "browser verification before it can be accepted."
        ),
        "compatibility": (
            "The implementation keeps the learning-space secondary navigation, legacy /review and /revision-calendar routes, "
            "dedicated resource pages, existing chat handoff, the two-item assessment-center boundary, path ownership, F5 "
            "resource history/version authority and three distinct practical resource types. Ordinary calendar browsing remains "
            "read-only and no private Agent reasoning is rendered."
        ),
    },
    "review-actions": {
        "implementation": (
            "app/review_schedule.py now resolves both owner-scoped review-plan and delayed-retest task IDs into the same "
            "canonical course, knowledge-point, profile-snapshot and source-ref resource context before calling the existing "
            "nine-item generation job. ReviewScheduleBoard.vue retains the failed operation kind and task ID so completion, "
            "retest load, retest submit and resource generation each retry the exact failed action with the same idempotency key."
        ),
        "verification": (
            "Focused backend and frontend contract tests have been extended for delayed-retest resource generation, owner "
            "isolation and exact failed-action retry. .venv/Scripts/python.exe -m pytest "
            "tests/test_f8_t01_review_schedule.py tests/test_f8_t01_review_frontend_contract.py -q -> 10 passed in 1.51s. "
            "frontend npm run build after the action fixes -> PASS, 6937 modules transformed in 1.84s."
        ),
        "user_result": (
            "A review task with complete canonical context can generate the same nine-resource bundle whether it came from "
            "SM-2 or delayed retest, and an operation failure now offers a working retry without losing the date, task or answer."
        ),
        "compatibility": (
            "The change reuses F5 generation jobs, existing retest ownership, the F4 exam gate and existing idempotency keys; "
            "it adds no resource store, exam rule, database table, migration or client-authored mastery evidence."
        ),
    },
    "verification": {
        "implementation": (
            "tests/test_f8_t01_review_schedule.py now covers the review and delayed-retest resource paths, and "
            "tests/test_f8_t01_review_frontend_contract.py statically protects the real calendar, task actions, legacy tool "
            "reachability, route boundaries, read-only copy and frozen light visual contract. "
            "scripts/e2e_f8_t01_review_calendar.py defines one isolated service and Chromium journey for both desktop "
            "viewports, zero-write browsing, resource generation, SM-2 completion, delayed retest and legacy-tool access. "
            "Its secondary-view preservation check now verifies the actual legacy capabilities 连续打卡天数、复习时长记录 and "
            "全部复习计划 instead of the unused label 连续复习. Evidence captures now wait for the resource workspace and "
            "calendar refresh to settle and scroll each opened legacy section into view before taking its screenshot. "
            "scripts/finalize_f8_t01_atomic_realization.py validates the final browser report, screenshots, visual metrics, exact "
            "database deltas and error boundaries before it can reconcile every primary and related atom independently."
        ),
        "verification": (
            ".venv/Scripts/python.exe -m pytest tests/test_f8_t01_review_schedule.py "
            "tests/test_f8_t01_review_frontend_contract.py -q -> 10 passed in 1.51s. Browser evidence and final per-atom "
            "reconciliation remain pending, so this batch is not yet final. frontend npm run build -> PASS, 6937 modules "
            "transformed in 1.84s after the resource/retry changes. F4 exam/path, F5 resource bundle/training/history, F6 "
            "interactive model/code sandbox/formal exam, F7 chat frontend, learning aggregation and navigation protection "
            "regression -> 56 passed in 47.61s with only five pre-existing framework deprecation warnings. After adding "
            "stable browser selectors and the E2E script: py_compile passed; focused tests -> 10 passed in 1.99s; production "
            "build -> 6937 modules in 1.93s."
            " First E2E launch failed before service/browser startup because the standalone script did not add the repository "
            "root to sys.path (ModuleNotFoundError: app); no product behavior or formal data was exercised."
            " Second E2E run started and cleaned the isolated service but stopped at the locked-exam copy assertion because "
            "the fixture had no pending F4 Today-required task, so the authoritative exam gate correctly returned unlocked; "
            "the fixture must seed the existing gate contract rather than force a frontend state. The isolated fixture now "
            "seeds that contract, the lock copy passed after the real task workspace opened, and the next selector was scoped "
            "to the calendar-header Today button because the empty agenda exposes a second legitimate same-name action. The "
            "following run exposed a real context-boundary defect: the unclassified review filter was written as course_id, "
            "so the global course resolver rejected the pseudo-course and left the review route; the filter needs its own "
            "review_course query key while real courses continue to use course_id. The next full rerun passed resource generation "
            "and one real SM-2 completion, then the delayed-retest submit returned HTTP 409 and no success notice. The isolated "
            "report recorded three screenshots, zero-write browsing, SQLite integrity ok before actions and complete process cleanup; "
            "the retest conflict must be diagnosed before final acceptance. After the due-time fixture and awaited route cleanup "
            "fixes, the next full rerun passed both desktop layouts, resource generation, one real SM-2 completion and one delayed "
            "retest completion with zero browser/HTTP/external-request errors and correct database deltas. It stopped only at the "
            "final secondary-view legacy-capability text assertion because the opened calendar legacy section did not contain the "
            "expected label 连续复习; six of seven screenshots were saved and final acceptance remains pending."
            " The assertion is now aligned to three substantive legacy capabilities; py_compile passed for both F8 operational "
            "scripts. The final full E2E rerun passed with status=passed, seven screenshots, both 1440x900 and 1366x768 "
            "layouts, 42 calendar cells, 58/42 ratios, zero overflow/collision/clipping/small-text/theme hits, zero HTTP/request/" 
            "page/console/external errors, zero business writes during browsing, SQLite integrity ok, zero foreign-key violations, "
            "and exact action deltas of +2 learning events, +1 check-in, +1 assessment attempt and +1 generation task."
            " Impeccable detect over ReviewScheduleBoard.vue, Review.vue and RevisionCalendar.vue returned one gray-on-color "
            "warning at Review.vue:186; source review confirmed it is a ternary-parser false positive because the due branch is "
            "bg-red-50 text-red-700 and the separate non-due branch is bg-slate-100 text-slate-700. No UI defect was accepted."
            " py_compile passed after adding stable target-page waits and legacy-section scrolling. The next clean rerun saved the "
            "initial calendar and settled resource-bundle screenshots but timed out waiting for the SM-2 completion notice; the "
            "report remained free of HTTP/request/page/console/external errors and the intermittent notice race remained open at "
            "that point. After ordering startTask before route-owned workspace state and stabilizing evidence capture, the final "
            "clean E2E passed with seven accepted full-opacity screenshots, both completion notices, exact database deltas, zero "
            "ordinary-browse writes, integrity_check=ok, zero foreign-key violations and no browser/HTTP/external errors. The "
            "focused suite remained 10 passed, production build remained 6937 modules, and the F4-F7 protection regression passed "
            "68 tests in 70.85s with only five existing framework deprecation warnings. git diff --check exited 0 with no whitespace "
            "errors; it emitted only the repository's existing Windows LF-to-CRLF conversion warnings. py_compile passed for the "
            "E2E, ledger-update and per-atom finalization scripts."
        ),
        "user_result": (
            "Students now receive one real, course-filtered monthly review calendar with actionable day tasks, durable review and "
            "retest completion feedback, nine-resource generation, protected exam gating and reachable original review tools."
        ),
        "compatibility": (
            "The tests explicitly preserve the learning-space routes, two-item assessment center, dedicated resource surfaces, "
            "legacy review tools, exam gate and the prohibition on evidence writes from ordinary calendar browsing."
        ),
    },
    "exam-gate-fixture": {
        "implementation": (
            "scripts/e2e_f8_t01_review_calendar.py now seeds an isolated confirmed plan/version, the latest active course path, "
            "one pending non-extension Today-required node and a resource_generation.requested event carrying the existing "
            "f4.intelligent-exam-gate.v1 snapshot. The browser must therefore observe the real required_tasks_incomplete state "
            "instead of a frontend-forced lock."
        ),
        "verification": (
            "py_compile passed for scripts/e2e_f8_t01_review_calendar.py and scripts/update_f8_t01_atomic_ledger.py. "
            ".venv/Scripts/python.exe -m pytest tests/test_f4_exam_gate.py -q -> 8 passed with five existing framework "
            "deprecation warnings. The next E2E run proved the real required_tasks_incomplete copy after expanding a task, "
            "then stopped on an ambiguous same-name Today button selector; product behavior did not fail and the selector "
            "must be scoped to the calendar header."
        ),
        "user_result": (
            "The E2E environment now contains the same locked-exam relationship used by the accepted F4 contract, while the "
            "production gate and formal database remain unchanged."
        ),
        "compatibility": (
            "Only the disposable F8 browser database is seeded. The F4 server-owned gate, Today-required path authority and "
            "two-item assessment-center boundary are reused without adding or bypassing any unlock rule."
        ),
    },
    "unclassified-filter": {
        "implementation": (
            "ReviewScheduleBoard.vue reads the review-only review_course query before course_id and writes "
            "review_course=unclassified for the legacy-plan pseudo-filter, while real courses continue to use course_id. "
            "The frontend contract and browser journey protect the separation and wait for each real schedule response."
        ),
        "verification": (
            ".venv/Scripts/python.exe -m pytest tests/test_f8_t01_review_schedule.py "
            "tests/test_f8_t01_review_frontend_contract.py -q -> 10 passed in 2.04s. frontend npm run build -> PASS, 6937 "
            "modules transformed in 1.87s. py_compile passed for both F8 operational scripts; browser rerun remains pending."
        ),
        "user_result": (
            "Students can switch to unclassified legacy review plans and back without leaving the review calendar or entering "
            "the global course-recovery page."
        ),
        "compatibility": (
            "Real course IDs still use the shared course_id contract, and the review-only pseudo-filter is never presented to "
            "the global context resolver as a course."
        ),
    },
    "completion-notice": {
        "implementation": (
            "The browser run proved the completion POST returned 200 and the isolated database stored one accepted, "
            "mastery-eligible review_completed event, but App.vue keys the route component by fullPath, so clearing the "
            "review_task query remounted the page and discarded the in-memory success notice. A one-shot sessionStorage bridge "
            "passed once but failed when consecutive fullPath remounts consumed it too early. ReviewScheduleBoard.vue now uses "
            "a non-sensitive review_notice enum in the same route query, cleared by the next explicit user navigation, without "
            "repeating the completion request. The next run proved an unawaited router.replace raced the old component's explicit "
            "schedule refresh, which restored the stale query. syncQuery now returns the navigation promise; completion and retest "
            "await that single route transition and let the route-authoritative new component refresh the schedule. A later clean "
            "run exposed the remaining entry-side race: startTask opened the workspace in the old component before its review_task "
            "route update had settled, so that late navigation could overwrite the completion notice. startTask now awaits route "
            "synchronization and returns before mutating workspace state; only the route-authoritative mounted component re-enters "
            "with sync=false and opens the task. The browser journey now waits for that authoritative workspace and reacquires the "
            "task locator before checking the existing exam-gate copy or starting resource generation. Its final legacy-tool "
            "captures also wait for the expanded details transition and reacquire the connected element before scrolling. Every "
            "capture now additionally waits until App.vue has removed page-fade enter/leave classes, preventing dim transition "
            "frames from being stored as final visual evidence."
        ),
        "verification": (
            "The defect was reproduced with a real service and database. The one-remount bridge passed focused tests and build "
            "but remained timing-dependent in the next browser run, so it is not accepted. After the deterministic route-enum "
            "fix, the focused F8 suite passed 10 tests in 1.86s and frontend npm run build passed with 6937 modules transformed "
            "in 1.78s. The next full browser rerun still timed out waiting for the review-completed notice, so the route-enum "
            "implementation was not accepted. After correcting the query-cleanup race, the focused F8 suite passed 10 tests "
            "in 1.58s and frontend npm run build passed with 6937 modules transformed in 1.83s. The full browser rerun remains "
            "pending, so that evidence did not close the defect. The final full browser rerun passed both the SM-2 and delayed-"
            "retest completion notices without duplicate requests; report.json was status=passed with no browser or HTTP errors. "
            "A subsequent clean rerun after strengthening screenshot waits again timed out on the SM-2 复习已完成 notice, proving "
            "the race is still intermittent and the earlier pass cannot close it. The entry-side ordering fix is recorded in source "
            "and contract tests now require syncQuery to be awaited before activeTaskId is assigned; focused tests, production build "
            "and a full clean browser rerun remain pending, so no final pass is claimed. After that ordering fix, "
            ".venv/Scripts/python.exe -m pytest tests/test_f8_t01_review_schedule.py "
            "tests/test_f8_t01_review_frontend_contract.py -q passed 10 tests in 1.63s; production build and a full clean browser "
            "rerun remain pending. frontend npm run build then passed with 6937 modules transformed in 1.76s; the full clean browser "
            "rerun remains pending. The next clean browser run stopped before resource generation because the acceptance script "
            "read the old task locator immediately after startTask intentionally remounted the route; no completion action or "
            "formal database was reached. The script must wait for the route-authoritative task workspace before asserting the "
            "server-owned exam-gate copy, so this run is recorded as failed and is not product acceptance evidence. That wait is "
            "now implemented; py_compile passed for scripts/e2e_f8_t01_review_calendar.py and "
            "scripts/update_f8_t01_atomic_ledger.py. The next full clean browser rerun passed with status=passed and seven "
            "screenshots: both completion notices remained visible, ordinary browsing left every database counter unchanged, "
            "learning events increased by exactly two, check-ins by one, assessment attempts by one and generation tasks by one, "
            "with integrity_check=ok and zero foreign-key violations. A second consecutive clean rerun remains pending before "
            "the intermittent race is considered closed. The second clean run again passed both completion notices and database "
            "checks, then failed only while scrolling the expanded legacy-tools element for its final screenshot because a route "
            "transition detached that element. This is recorded as a failed evidence run; the capture step must wait for the "
            "route-authoritative expanded section and reacquire its locator before scrolling. That capture stabilization is now "
            "implemented; py_compile passed for both F8 operational scripts. The next full clean run passed status=passed with all "
            "seven screenshots and the same exact database deltas. Full-size review then found the resource, review-completed and "
            "retest-completed images were captured during App.vue's 120ms page-fade opacity transition; business behavior is valid, "
            "but those three images are not accepted as final visual evidence until capture waits for transition classes to clear. "
            "That stable-capture gate is now implemented; py_compile passed for both F8 operational scripts and one final clean "
            "E2E run remains pending. The final clean run passed with seven screenshots, both desktop viewports, both durable "
            "completion notices, exact database deltas, zero ordinary-browse writes, integrity_check=ok and zero foreign-key, HTTP, "
            "request, page, console or external-request errors. Full-size inspection accepted all seven images; the resource bundle, "
            "review completion and retest completion are now captured at final opacity with no overlap, clipping or theme drift. "
            "The bounded Impeccable detector over ReviewScheduleBoard.vue, Review.vue and RevisionCalendar.vue returned only its "
            "known Review.vue:186 gray-on-color warning; source inspection confirmed a ternary-parser false positive because "
            "bg-red-50 text-red-700 and bg-slate-100 text-slate-700 are separate branches. No visual defect was accepted."
        ),
        "user_result": (
            "A student can start a real review or delayed retest, complete it once, and keep a clear completion confirmation while "
            "the calendar refreshes to the server-owned next state; repeated clean browser journeys no longer lose that feedback."
        ),
        "compatibility": (
            "The existing route cleanup, server-owned completion, idempotency key and five-step aggregation remain authoritative; "
            "the UI must not submit or count a second event to restore feedback."
        ),
    },
    "retest-remount": {
        "implementation": (
            "The browser journey showed two GETs for one delayed retest: the old component loaded immediately after writing "
            "retest_id, then App.vue remounted by fullPath and the route-authoritative component loaded again. An answer selected "
            "during that overlap was discarded, leaving the new submit button disabled. The old instance now stops after "
            "route synchronization so only the mounted route instance loads the question."
        ),
        "verification": (
            "The duplicate-load failure was reproduced with the real browser and service. After the route-authoritative loading "
            "fix, the focused F8 suite passed 10 tests in 1.95s and frontend npm run build passed with 6937 modules transformed "
            "in 1.77s. The final full browser journey submitted the delayed retest successfully and displayed its completion "
            "notice with no duplicate-load or disabled-submit failure."
        ),
        "user_result": (
            "The delayed-retest question will no longer flicker or lose a quickly selected answer while the task deep link is "
            "being established."
        ),
        "compatibility": (
            "The existing retest API, owner check, answer payload, server grading and route deep link remain unchanged; only the "
            "duplicate client request before remount is removed."
        ),
    },
    "retest-due-fixture": {
        "implementation": (
            "The failed browser run showed the fixture scheduled its delayed retest for 11:00 Asia/Shanghai while the run occurred "
            "around 04:33, so the production API correctly returned retest_not_due. The disposable fixture now uses 00:00 of the "
            "same Shanghai calendar day, preserving the intended Today date while making the task truthfully due."
        ),
        "verification": (
            "The diagnosis used the failed browser report, server log and read-only isolated SQLite inspection: the task remained "
            "status=due with no retest attempt, and due_at was later than the API current UTC time. py_compile passed for both F8 "
            "operational scripts, and the focused F8 suite passed 10 tests in 1.50s. The final full browser rerun completed the "
            "truthfully due task and increased assessment attempts by exactly one."
        ),
        "user_result": (
            "The acceptance journey will no longer invite the student to submit a fixture that has not reached its actual due time."
        ),
        "compatibility": (
            "Only the disposable E2E database seed changes; production due-time validation, Shanghai calendar projection, owner "
            "checks and formal data remain unchanged."
        ),
    },
}


def atomic_write(path: Path, payload: dict) -> None:
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def register_context(payload: dict) -> None:
    entries = {entry["atomic_requirement_id"]: entry for entry in payload["entries"]}
    if set(entries) != PRIMARY | RELATED:
        raise RuntimeError("F8-T01 ledger atom set changed")
    for atom_id, understanding in UNDERSTANDING.items():
        entries[atom_id]["understanding"] = {**understanding, "confirmed": True}
    batches = payload.setdefault("execution_batches", [])
    now = datetime.now(timezone.utc).isoformat()
    for batch_id, definition in PLANNED_BATCHES.items():
        record = next((item for item in batches if item.get("id") == batch_id), None)
        if record is None:
            record = {"id": batch_id, "verification": []}
            batches.append(record)
        record.update(definition)
        record["status"] = "PLANNED_ATOM_MAPPED"
        record["updated_at"] = now


def append_unique(values: list, value: str) -> None:
    if value not in values:
        values.append(value)


def record_batch(payload: dict, batch_id: str) -> None:
    result = BATCH_RESULTS[batch_id]
    batches = payload.get("execution_batches") or []
    batch = next((item for item in batches if item.get("id") == batch_id), None)
    if batch is None:
        batch = {"id": batch_id, "verification": []}
        batches.append(batch)
    batch.update(PLANNED_BATCHES[batch_id])
    expected_atoms = set(PLANNED_BATCHES[batch_id]["atoms"])
    entries = {
        entry["atomic_requirement_id"]: entry
        for entry in payload["entries"]
    }
    if not expected_atoms.issubset(entries):
        raise RuntimeError(f"batch {batch_id} atom set changed")
    for atom_id in sorted(expected_atoms):
        realization = entries[atom_id]["realization"]
        append_unique(realization["implementation_evidence"], result["implementation"])
        append_unique(realization["verification_evidence"], result["verification"])
        realization["user_visible_result"] = result["user_result"]
        realization["status"] = "IN_PROGRESS"
        if entries[atom_id]["role"] == "related":
            realization["compatibility_or_defer_rationale"] = result["compatibility"]
    append_unique(batch.setdefault("verification", []), result["verification"])
    batch["status"] = "IMPLEMENTED_PENDING_FINAL_VERIFICATION"
    batch["updated_at"] = datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--register-context", action="store_true")
    group.add_argument("--record-batch", choices=sorted(BATCH_RESULTS))
    args = parser.parse_args()
    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    if args.register_context:
        register_context(payload)
        status = "CONTEXT_RECORDED"
    else:
        record_batch(payload, args.record_batch)
        status = "BATCH_RECORDED"
    atomic_write(LEDGER, payload)
    print(json.dumps({"status": status, "atoms": len(payload["entries"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
