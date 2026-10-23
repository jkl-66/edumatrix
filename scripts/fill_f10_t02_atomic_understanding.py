#!/usr/bin/env python3
"""Fill F10-T02's task-local atomic understanding ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ROOT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "context_recovery"
PAYLOAD_PATH = (
    CONTEXT_ROOT
    / "loaded_context"
    / "v20260818T100653+0800"
    / "F10-T02"
    / "F10-T02.payload.json"
)
LEDGER_PATH = (
    CONTEXT_ROOT
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F9-F10-CONTEXT-SAFE-FUSION-COMPLETION"
    / "F10-T02_404D1D120CAB6E67E6B6C629420F8BA28D3585BDBB748FF93BABF5F4B38EB46A.json"
)
WORKLOG_PATH = ROOT / "outputs" / "原系统融合重构执行" / "02_融合重构_WORKLOG.md"

G01_IDS = [f"G01-R{index:02d}" for index in range(1, 8)]
G22_IDS = [f"G22-R{index:02d}" for index in range(1, 17)]
ALL_IDS = G01_IDS + G22_IDS


def item(
    product_meaning: str,
    required: str,
    prohibited: str,
    scope: str,
    verification: str,
) -> dict:
    return {
        "product_meaning": product_meaning,
        "behavior_boundaries": [required, prohibited],
        "implementation_scope": [
            scope,
            "F10-T02以验收和由本轮验收发现的最小修复为边界；不重做原主责任务，不新增第二套页面、数据对象或导航。",
        ],
        "verification_plan": [
            verification,
            "在1440x900与1366x768保存真实页面证据，记录route、account、fixture、expectedState、actualEvidence、screenshot和result；普通浏览前后比较受保护学习数据。",
        ],
        "confirmed": True,
    }


UNDERSTANDING = {
    "G01-R01": item(
        "全部正式桌面页面应共享雾白、白色内容面和墨蓝灰层级；辅助色只表达真实状态，不能重新成为品牌主题。",
        "检查学生、教师、管理员全部目标路由的背景、文字、主动作、选中态、警告和错误语义，并确保状态不只靠颜色表达。",
        "禁止绿色、棕色、浅蓝或蓝紫成为大面积主题，禁止低对比主按钮和白底弱灰正文。",
        "从50条目标路由生成逐页视觉清单，检测计算样式、主题色占比、按钮对比和角色应用壳一致性。",
        "CSS令牌扫描与50路由双尺寸截图均不得出现禁用主题回归或低对比主动作。",
    ),
    "G01-R02": item(
        "作品的技术感来自真实学习内容和状态，不依靠蓝紫渐变、发光、光球、散景或毛玻璃装饰。",
        "扫描目标页面可见节点和样式表中的gradient、filter、backdrop-filter、box-shadow与装饰背景，并结合截图判断业务必要性。",
        "禁止装饰性AI背景、无意义发光、离散渐变球和过量透明模糊；真实弹层阴影与必要遮罩不属于禁止项。",
        "在全路由视觉验收器中保存每页禁用效果命中项，真实命中必须定位到选择器和截图。",
        "所有目标路由的forbiddenEffects为空，且人工审阅代表性首屏未见装饰性AI视觉。",
    ),
    "G01-R03": item(
        "桌面信息密度不能通过缩小文字获得；正文、辅助说明、按钮、表格和图表标签必须在两种评委常用分辨率下清楚可读。",
        "可见辅助文字不得低于14px，正文以15至16px为主，字距为0，长标题可换行或稳定截断并提供全文。",
        "禁止负字距、随视口缩放字号、文字裁切、按钮文字遮挡和为塞入更多信息而使用不可读小字。",
        "测量50路由可见文本的计算字号、行高、容器边界和裁切，单独覆盖长标题与长文本fixture。",
        "两种桌面尺寸的smallText、clipped和文字碰撞均为0，字体栈符合思源黑体/少量思源宋体合同。",
    ),
    "G01-R04": item(
        "每页首屏先说明当前位置、当前任务、完成条件和下一步，详细分析、历史、技术证据与低频操作按需展开。",
        "逐页识别首屏唯一任务摘要和主动作，确认展开内容仍可访问且不删除7.20保护能力。",
        "禁止文本墙、重复功能说明、工程术语占据首屏，也禁止以减负为由删除画像、路径、笔记和错题的丰富能力。",
        "对50路由记录首屏标题、任务、完成条件、主动作、次动作和展开区；对完整学生旅程检查每一步下一动作。",
        "浏览器证据证明首屏无需阅读长说明即可继续，低频信息可展开，保护页能力清单不减少。",
    ),
    "G01-R05": item(
        "整体页面应像安静的专业学习工具，以页面带、分栏、列表和真实工具面组织，而不是把每段内容都包成漂浮卡片。",
        "检查内容层级、卡片嵌套、连续大圆角容器、过重阴影和无业务边界的重复面板。",
        "禁止卡片套卡片、装饰卡片墙、普通区块大圆角和营销式Hero占据业务页面；真正重复条目和工具面板可保留克制边界。",
        "全路由DOM与截图检测嵌套卡片、圆角、阴影和首屏面板数量，并人工复核高密度页面。",
        "自动检测无卡片嵌套或无依据大圆角，代表性页面在两尺寸下层级清楚且不显拥挤。",
    ),
    "G01-R06": item(
        "当前验收只证明桌面端质量，主要基准1440x900、最低基准1366x768，不用移动端结果稀释桌面闭环。",
        "全部F10-T02页面与旅程必须在两种桌面尺寸各自执行，固定侧栏、顶栏、工具栏和内容几何保持稳定。",
        "禁止把390x844、移动抽屉、触屏手势或响应式移动布局列为本任务完成门禁，也不得用单一桌面截图代替双尺寸。",
        "验收脚本只声明两个冻结桌面viewport，并对每条路由保存viewport维度和截图。",
        "报告中仅有1440x900与1366x768且两者覆盖集合一致；不存在移动端完成宣称。",
    ),
    "G01-R07": item(
        "视觉一致性必须来自可实施令牌而非主观描述：字体、字号、行高、颜色、边框、圆角、阴影、间距、宽度、导航、按钮和图表均有统一值。",
        "验证运行页面计算样式与F1冻结令牌一致，并检查共享应用壳、按钮层级、图表单位和空态。",
        "禁止页面私自恢复旧主题、任意圆角/阴影、未知字体或缺少单位与来源的图表；局部业务语义色必须可解释。",
        "读取全局设计令牌并在路由验收中采样关键节点计算样式，生成令牌偏差明细而不是只做截图主观判断。",
        "令牌合同测试、生产构建和双尺寸计算样式检查通过；任何例外都有业务原因和明确选择器。",
    ),
    "G22-R01": item(
        "学生首次进入一门新课程时，入学诊断是形成学习起点的正式步骤，不能直接跳到无依据路径。",
        "旅程从预置课程和自然语言画像进入诊断，完成作答后产生可解释报告与后续路径；已有有效诊断可恢复或查看。",
        "禁止用课程材料上传作为前置条件、静默生成诊断成绩或把普通浏览当作诊断证据。",
        "连续旅程覆盖/onboarding、/workspace/assessment/entry及报告结果，使用新学生隔离fixture验证状态写入。",
        "真实点击完成初始化诊断并获得报告；诊断前后事件、画像和路径变化与正式接口一致。",
    ),
    "G22-R02": item(
        "诊断和画像证据应转化为推荐知识点与可执行学习路径，学生能看见推荐理由、先后关系和下一步。",
        "验证/profile/learning与/workspace/path使用同一课程和画像版本，路径包含总路径、科目路径、今日任务与进入动作。",
        "禁止前端伪造推荐、跨课程混用画像或在无证据时声称已经掌握。",
        "在诊断完成后的同一学生会话检查画像快照、路径节点、推荐理由和课程上下文连续性。",
        "路径与画像来源一致，刷新和深链后不丢课程，普通查看路径不新增掌握事件。",
    ),
    "G22-R03": item(
        "配套资源必须结合当前课程、知识点、画像掌握证据和最近学习事件生成，而不是仅按固定模板或页面默认值。",
        "从今日知识点发起资源包，验证九类产物引用同一课程、知识点、来源和资源包版本。",
        "禁止固定accuracy/recall示例成为产品行为、跨课程来源或普通浏览触发自动生成。",
        "连续旅程在/workspace/path触发生成，并核对/workspace/resources及资源详情中的上下文与来源。",
        "生成请求、归档对象和页面显示的课程/知识点/版本一致，已有产物重复进入不创建重复包。",
    ),
    "G22-R04": item(
        "资源只有满足其正式完成条件并产生可信事件后，才自动勾选对应路径任务。",
        "选取正式必做资源完成动作，验证统一学习事件、路径节点状态和页面勾选同步；普通打开和展开保持只读。",
        "禁止仅点击、浏览、预览或无结果运行改变任务完成或掌握度，禁止重复完成重复累计。",
        "在同一隔离数据库比较资源完成前后及重复动作后的learning_events、path_nodes和掌握快照。",
        "显式完成精确产生预期事件并勾选一个任务；浏览与重复重放不增加业务事实。",
    ),
    "G22-R05": item(
        "智能组卷只在今日必做任务全部完成后解锁，可选资源不阻塞；解锁后学生有明确进入动作。",
        "连续旅程同时验证锁定、缺项减少和全部必做完成后的解锁状态，前后端门禁必须一致。",
        "禁止前端单独绕过授权、用可选资源数量锁定组卷或在缺项时仅显示含糊禁用按钮。",
        "在/workspace/assessment/exams与路径页记录missingRequiredTasks、按钮状态和服务端结果。",
        "未完成时入口禁用且列出缺项；完成后同一学生可进入组卷，篡改前端状态不能绕过后端。",
    ),
    "G22-R06": item(
        "智能组卷交卷后，报告必须通过可信学习事件更新画像、路径、下一日安排、错题和复习，而不是只展示分数。",
        "完成一份正式组卷并检查报告、统一反馈版本以及六个下游页面的同一事件/一致性令牌。",
        "禁止把交卷即完全掌握、固定分数增量或页面刷新当作反馈；失败时不得丢弃已完成测评。",
        "连续旅程从组卷作答到报告，再访问首页、画像、路径、错题、复习和历史核对同一反馈。",
        "交卷产生一次可信事件，各下游按证据更新且保持同一课程与版本，重复提交幂等。",
    ),
    "G22-R07": item(
        "错题本、复习中心、笔记本和资源中心共同承接测评后的深度学习，原版丰富功能必须继续可达。",
        "从报告或反馈分别进入/workspace/review/wrong-questions、/workspace/review、/workspace/notes和/workspace/resources，检查来源与返回路径。",
        "禁止用摘要占位页替代错题重做、日历复习、笔记版本和资源历史，也禁止普通查看写掌握度。",
        "对四个深度学习空间执行功能清单和双尺寸浏览，核对对象来源、历史与只读行为。",
        "四页均有真实数据、主动作、失败恢复和返回闭环，保护能力未减少且浏览零写入。",
    ),
    "G22-R08": item(
        "学习中的动态疑问进入智能对话；对话先回答当前问题，再由明确动作生成并归档相关资源。",
        "从资源、知识库或路径带上下文进入/learn，验证回答、来源、追问和生成资源动作，完整产物不在消息体中展开。",
        "禁止打开对话即创建空会话或学习证据，禁止把测验/代码执行重新塞入Chat，禁止暴露私有推理。",
        "在本地确定性fixture下验证/learn的上下文深链、回答流、资源动作与返回路径。",
        "对话上下文准确、主动作唯一、生成后返回资源深链；普通打开对话不写受保护表。",
    ),
    "G22-R09": item(
        "生成的完整讲义、导图、测验、任务书、沙盒任务、视频、课件、模型和费曼任务分别归档到学习空间，不形成聊天内第二资源库。",
        "对九类资源检查唯一对象、专用详情路由、来源、版本、历史和生成状态；Chat只显示摘要与深链。",
        "禁止在对话中渲染完整产物、复制资源对象或缺少归档位置的临时内容。",
        "资源包生成后遍历/workspace/resources及九类详情路由，并检查Chat生成结果投影。",
        "九类产物均可从资源中心找到且各有唯一归档；Chat不包含完整产物正文。",
    ),
    "G22-R10": item(
        "每种资源空间既能查看历史版本，也能针对自定义知识点发起新资源生成并恢复失败任务。",
        "验证资源中心分类、搜索、历史/版本入口和自定义知识点生成；失败只重试对应资源。",
        "禁止用一份全局历史代替分类历史、覆盖旧版本或无课程来源生成资源。",
        "抽取九类资源代表页执行历史查看、自定义生成、失败与恢复状态，并核对幂等键。",
        "历史版本持续可读，新生成有独立版本和来源，失败重试不删除已成功产物。",
    ),
    "G22-R11": item(
        "智能对话的AI过程展示应可审计但不泄露私有思维链：显示职责、输入来源、候选、分歧、校验、修订与最终摘要。",
        "检查/learn的过程面板、来源引用和错误状态使用业务语言，可按需展开并与最终回答对应。",
        "禁止展示系统提示词、私有推理、API Key、原始Agent日志、trace、worker或lease。",
        "用确定性审计fixture验证过程阶段、来源、修订与最终回答，扫描DOM和网络响应中的禁用敏感字段。",
        "过程面板可理解可追溯且无敏感原文；折叠时不淹没主回答和下一动作。",
    ),
    "G22-R12": item(
        "旧Chat测验、代码和联网搜索已经分别收口到测验题资源、代码沙盒和知识库，F10-T02必须验证用户只看到唯一正式归宿。",
        "从旧深链和新入口分别进入对应目标，检查上下文保持、返回路径和Chat无重复执行面。",
        "禁止恢复第二答题面、聊天内代码运行、独立联网搜索工作台或无提示404。",
        "复用F10-T01迁移合同并在双尺寸旅程中验证/workspace/resources/quizzes/:id、/workspace/code/:id与/knowledge。",
        "旧/新入口收敛到同一产品对象，Chat只做帮助与深链，普通浏览零写入。",
    ),
    "G22-R13": item(
        "完整学生闭环从自然语言多轮画像开始，课程知识来自团队预置知识库；个人资料上传只能是可选辅助。",
        "新学生无需上传课程材料即可完成/onboarding、诊断、路径和资源生成；可选附件不阻塞跳过。",
        "禁止强制上传教材、课件或大纲，禁止把单次表单冒充自然语言画像。",
        "使用无个人上传的新学生fixture完成首次旅程，并检查预置课程/知识库已可用。",
        "未上传资料时画像与诊断均可继续，系统主动多轮提问并逐步更新画像。",
    ),
    "G22-R14": item(
        "学生在总路径点击今日知识点一次生成并分发完整资源包，九类产物进入各自空间，生成过程可离开并恢复。",
        "验证总路径的知识点主动作、资源包进度、部分成功、单项重试、完成归档和重复点击幂等。",
        "禁止在Chat逐个堆产物、失败后清空成功项、重复点击生成第二个同知识点资源包。",
        "在/workspace/path执行生成并遍历/workspace/resources/bundles/:bundleId及九类详情路由。",
        "一次动作产生一个资源包与九类唯一对象，失败项可单独恢复，重复请求保持同一包。",
    ),
    "G22-R15": item(
        "组卷锁定时必须逐条展示未完成的今日必做任务、完成条件和直达入口，让学生知道如何解锁。",
        "验证锁定页缺项名称、资源类型、状态、进入动作以及完成后自动减少并最终解锁。",
        "禁止仅显示cannot revise、内部状态码或无解释禁用按钮，禁止把可选资源列为必做缺项。",
        "在/workspace/assessment/exams的锁定fixture和连续旅程中逐项点击缺失任务直达链接。",
        "每个缺项都能进入正确资源且返回后状态同步；全部必做完成后主动作解锁。",
    ),
    "G22-R16": item(
        "生成、保存、判分或事件聚合失败时，系统保留输入和已完成结果，从最近检查点只重试失败步骤并给出可理解下一步。",
        "至少覆盖资源包部分失败、组卷保存/判分失败和反馈聚合失败，验证幂等恢复与状态几何稳定。",
        "禁止整批清空、重复成功步骤、暴露replan_pending/trace/worker/lease或把部分失败显示为完全成功。",
        "使用隔离fixture注入精确失败，分别记录处理中、部分成功、失败、恢复和完成状态及数据库前后差异。",
        "恢复后成功项ID与版本不变、失败项单独完成、业务状态与页面说明一致且无重复学习事实。",
    ),
}


def atomic_write(path: Path, payload: dict) -> None:
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main() -> None:
    payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    contract = payload["task_atomic_execution_contract"]
    if contract.get("task_id") != "F10-T02":
        raise RuntimeError("F10-T02 task contract mismatch")
    if contract.get("primary_atomic_requirement_ids") != []:
        raise RuntimeError("F10-T02 unexpectedly has primary atoms")
    if contract.get("related_atomic_requirement_ids") != ALL_IDS:
        raise RuntimeError("F10-T02 related atom order mismatch")
    if (
        payload.get("exact_task_object", {}).get("source_images", []) != []
        or payload.get("images", []) != []
    ):
        raise RuntimeError("F10-T02 unexpectedly contains source images")

    source_by_id = {
        source["atomic_requirement_id"]: source
        for source in payload["related_atomic_requirements"]
    }
    entries = ledger.get("entries", [])
    if [entry.get("atomic_requirement_id") for entry in entries] != ALL_IDS:
        raise RuntimeError("F10-T02 ledger atom set or order mismatch")
    if len(set(ALL_IDS)) != 23 or set(UNDERSTANDING) != set(ALL_IDS):
        raise RuntimeError("F10-T02 understanding map is incomplete or duplicated")

    for entry in entries:
        atom_id = entry["atomic_requirement_id"]
        source = source_by_id[atom_id]
        if entry.get("role") != "related":
            raise RuntimeError(f"{atom_id} must be related")
        if entry.get("requirement_sha256") is None:
            raise RuntimeError(f"{atom_id} has no source hash")
        expected_paragraphs = [1] if atom_id.startswith("G01-") else [64, 65]
        if source.get("word_paragraphs") != expected_paragraphs:
            raise RuntimeError(f"{atom_id} Word paragraphs mismatch")
        if source.get("source_images") != []:
            raise RuntimeError(f"{atom_id} unexpectedly references an image")
        entry["understanding"] = UNDERSTANDING[atom_id]

    atomic_write(LEDGER_PATH, ledger)

    marker = "## WL-F10-T02-001 23条相关原子理解完成"
    worklog = WORKLOG_PATH.read_text(encoding="utf-8")
    if marker not in worklog:
        addition = f"""

{marker}

- 任务：`F10-T02 / NOT_STARTED`；任务合同为0条主责、23条相关原子，零主责不跳过完整合同。
- 来源：逐条读取Word第1、64、65段，P03/P04/P11/P28/P29、10号F10-T02合同与13号G01/G22；本任务source_images为0，没有漏读原图。
- G01：7条分别确认配色、禁用AI装饰、字号、首屏减负、容器层级、桌面范围和设计令牌的必须/禁止边界。
- G22：16条分别确认画像、诊断、路径、资源包、完成事件、组卷门禁、反馈、深度学习、Chat、归档、历史、审计、能力归宿和失败恢复的连续验收边界。
- 验收原则：不继承上一任务结论为本任务证据；F10-T02必须用自己的50路由、双桌面、完整旅程、数据零写入和失败恢复证据逐条核销。
- 下一步：运行原子理解门禁并转换到 `CONTEXT_VERIFIED`；未通过前不创建验收脚本或修改产品代码。
"""
        WORKLOG_PATH.write_text(worklog.rstrip() + addition + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "UNDERSTANDING_FILLED",
                "task": "F10-T02",
                "primary_atoms": 0,
                "related_atoms": len(ALL_IDS),
                "confirmed": sum(
                    entry["understanding"].get("confirmed") is True for entry in entries
                ),
                "images": 0,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
