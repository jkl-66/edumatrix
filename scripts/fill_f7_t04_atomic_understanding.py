#!/usr/bin/env python3
"""Record F7-T04's independent per-atom product understanding."""

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
    "G04-R06": item(
        "智能对话回答中出现一道可作答题时，学生无需切页即可选择答案、提交、查看服务端判分和解析；题目身份、作答历史和后续追问仍归属于学习空间的canonical测验题资源。",
        [
            "对话只嵌一张紧凑题卡，不恢复整套测验工作台、题组导航或测评中心入口；完整题组必须通过资源深链打开。",
            "题目必须来自当前课程、知识点、画像、证据和最近事件驱动的已有测验资源，不在前端硬编码示例，也不由聊天文本临时伪造答案。",
            "只有服务端接受并判分的attempt可以形成学习证据；打开题卡、选择选项、查看来源或追问本身不改变掌握度。",
        ],
        [
            "在Chat主对话中复用F6-T01的InlineQuizCard和canonical quiz attempt协议，以resourceLink和questionVersionId装载单题。",
            "移除Chat顶部测验工作台和斜杠命令的页面切换，把完整题组入口改为/workspace/resources/quizzes/:resourceId深链；保留旧query深链的兼容转向。",
        ],
        [
            "前后端合同测试验证题卡身份、服务端判分、修改重答、来源、追问和完整资源深链，且Chat没有整套测验标签页。",
            "双桌面E2E在对话内完成单题并确认作答历史与F6资源一致，普通打开和选择答案前学习事件不变。",
        ],
    ),
    "G12-R01": item(
        "智能对话输入区允许添加图片、PDF、PPTX、DOCX和文本/Markdown附件，每个附件先形成所有者隔离的解析对象，再由学生决定是否随本次问题发送。",
        [
            "不支持旧二进制PPT时必须给出明确转换提示；格式、大小或内容无效不得伪装成解析成功，也不得把客户端提供的API密钥发送到后端。",
            "附件只在当前所有者和会话范围可见，不能因上传自动变成团队预置课程、canonical课程事实或掌握证据。",
            "解析测试使用本地确定性解析器；未获用户授权不得把附件内容发给外部模型，正式回答沿用当前后端模型配置和真实失败语义。",
        ],
        [
            "新增app/chat_api.py及持久化附件解析协议，复用现有document_parser能力但建立独立chat attachment边界；在app/main.py注册路由。",
            "在frontend/src/api新增chat接口并重构Chat.vue输入队列，保留7.20图片问答、会话历史、来源选择和流式回答。",
        ],
        [
            "API测试五类附件、拒绝格式、大小门禁、所有者隔离、刷新恢复和上传不写课程/学习事实。",
            "E2E同时上传图片与PDF，观察解析完成后发送；双尺寸检查附件名、状态和移除动作完整可读。",
        ],
    ),
    "G12-R02": item(
        "附件在解析进入终态前不能作为消息上下文发送；只有ready附件进入回答，失败附件必须被明确排除、重试或移除后才能继续。",
        [
            "queued或parsing附件存在时发送按钮禁用并说明具体阻塞项；不得把原始文件、空摘要或旧附件缓存静默传给模型。",
            "partial_failed只表示附件内部部分内容不可用；必须列出可用与失败范围，学生确认后才可按可用部分发送。",
            "重复点击发送使用同一幂等键恢复同一消息，不创建重复附件引用、用户消息或回答任务。",
        ],
        [
            "附件状态机和消息创建接口校验owner、conversation、attachmentParseIds及终态；消息冻结实际参与的解析版本和context refs。",
            "Chat composer根据每项状态计算唯一发送动作，解析中保持输入与附件，失败提供单项重试和移除。",
        ],
        [
            "API覆盖未解析发送拒绝、部分失败确认、失败排除、重复幂等提交和刷新后的相同附件版本。",
            "E2E注入解析失败后确认输入不丢、发送被阻止，单项重试成功后同一问题可发送。",
        ],
    ),
    "G12-R03": item(
        "学生在输入区直接看到每个附件当前解析阶段、已完成内容、失败位置和面向业务的原因，并能只重试失败步骤。",
        [
            "错误不得直出trace、worker、绝对路径、提示词或供应商密钥；失败信息要指出文件、阶段和下一步。",
            "一个附件失败不能清空其他已成功附件或问题草稿；重试不得重新上传和重跑已成功步骤。",
            "解析过程展示确定性业务阶段，不伪造模型思考动画或已完成百分比。",
        ],
        [
            "解析对象保存stage、progress、warnings、errorCode、errorMessage、retryable和checkpoint；API返回稳定业务状态。",
            "Chat附件行显示解析文本/页数/幻灯片等摘要、失败原因、重试与移除，状态切换不改变输入区几何。",
        ],
        [
            "单元/API测试各阶段、可重试错误、不可重试错误、失败步骤重放和错误清洗。",
            "双桌面E2E注入单个PDF解析错误，确认其他图片仍ready、草稿保留且重试后恢复。",
        ],
    ),
    "G12-R06": item(
        "每个附件必须可区分等待解析、解析中、可发送、部分失败、失败可重试和已移除六类用户状态，并在刷新后恢复到同一状态。",
        [
            "状态不能只靠颜色区分，必须同时有文字、图标/进度和可执行动作；可见辅助文字不低于14px。",
            "removed是显式终态，已移除附件不得再出现在消息context或后续资源来源中；恢复必须基于服务端事实而非localStorage猜测。",
            "同一附件的状态转换只允许合法前进或失败重试，旧请求不能覆盖较新的版本。",
        ],
        [
            "为附件解析状态、lockVersion和幂等键建立单一服务端状态机，并提供列表/读取、重试、确认部分结果和移除接口。",
            "在Chat composer实现稳定附件队列、状态标签、Tooltip、键盘焦点、单项动作及刷新恢复。",
        ],
        [
            "API状态机测试全部合法/非法转换、旧版本冲突、owner隔离和removed不可参与消息。",
            "1440x900与1366x768截图覆盖ready、parsing、partial_failed、failed和removed恢复，无溢出、碰撞或低于14px文字。",
        ],
    ),
    "G12-R08": item(
        "附件解析、回答引用和由回答触发的资源生成共享可定位上下文：课程、文档/附件版本、页/幻灯片/字符范围、sourceRef和对话消息都能反向打开来源。",
        [
            "F7-T04负责保存并展示定位字段和深链，F7-T05才统一治理跨产物来源与公开Agent审计；本任务不得提前宣称完整审计完成。",
            "回答不得引用不存在、无权限、已移除或版本漂移的附件位置；来源失效时保留引用文本并明确不可用。",
            "完整生成产物只能归档到学习空间；对话保存资源摘要、状态、resourceId和深链，不保存或展开完整正文。",
        ],
        [
            "消息协议保存contextRefs、attachmentParseIds、sourceRefs、resourceLinks和streamCheckpoint；app/chat_api.py提供owner-scoped读取和恢复。",
            "stream_api.py作为发现的现有流式集成面只接收已验证上下文并在complete事件返回来源/资源定位；Chat.vue渲染来源卡与资源深链。",
        ],
        [
            "API测试来源版本冻结、owner鉴权、失效来源、资源归档和对话响应不含完整资源正文。",
            "E2E从回答来源回到F7-T02原文位置，并从资源摘要进入对应学习空间，返回后对话上下文保持。",
        ],
    ),
    "G20-R05": item(
        "智能对话一级入口只承担会话、附件、回答、引用、紧凑单题和资源摘要；代码沙盒、完整测验和联网发现不再是Chat内部标签页或工作台。",
        [
            "不得删除对应能力：代码进入/workspace/resources/sandbox/:resourceId，测验进入/workspace/resources/quizzes/:resourceId，联网发现进入/knowledge/discover。",
            "旧tab、quiz_resource_id或命令入口需要给出明确兼容深链，不能保留第二套可编辑工作台，也不能静默失效。",
            "学生八个一级入口和统一应用壳保持不变，不新增Agent、代码或搜索一级导航。",
        ],
        [
            "保护性拆分Chat.vue，删除quiz/code/websearch tab及右侧沙箱/可视化工具面板，保留必要的上下文与来源侧栏。",
            "将旧斜杠命令和query参数适配为对应空间的资源查找/深链，并用导航保护测试证明能力仍可达。",
        ],
        [
            "静态合同测试拒绝Chat中的测验、代码、联网标签页和旧工作台组件，同时验证对应正式路由深链。",
            "双桌面E2E首屏只见对话主线，分别从兼容入口到测验、沙盒和联网发现且返回上下文不丢。",
        ],
    ),
    "G20-R07": item(
        "学生从固定的智能对话一级入口直接使用多模态问答，附件能力与当前课程、画像和页面上下文共同参与回答。",
        [
            "多模态是对话能力而不是新增一级入口、独立演示页或必须配置客户端供应商密钥的设置项。",
            "无可用视觉模型时必须显示真实限制并保留已解析文本/本地来源，不得伪装看见图片内容。",
            "多模态上传和解析不改变八项导航、课程上下文或掌握证据边界。",
        ],
        [
            "在/learn的同一composer支持五类附件和当前ContextRef；后端按现有安全模型配置决定是否调用视觉能力。",
            "保留原7.20会话、历史、流式和图片问答兼容，同时统一为新的附件解析对象。",
        ],
        [
            "导航与鉴权测试确认/learn仍是唯一智能对话入口，owner与课程上下文正确。",
            "E2E在有/无视觉模型的确定性场景验证真实状态、文本回退和不伪造图片理解。",
        ],
    ),
    "G21-R04": item(
        "学习空间的资源和测评页面能把当前课程、知识点、资源版本、题目或选区以ContextRef带入智能对话，学生到达后可直接追问且能返回原位置。",
        [
            "本任务建立统一深链接收和恢复，不逐页重构F4-F6或未来F8页面；既有已关闭页面只能做最小兼容验证。",
            "普通打开智能对话或引用资源不创建掌握证据；只有对应资源自身已批准的正式作答/完成事件可回流。",
            "无权限、已撤回或版本漂移的上下文不能被静默替换为相似资源，必须显示失效并允许移除。",
        ],
        [
            "定义/learn可接收的context_ref或既有prompt/query适配协议，服务端解析owner、course、resource、source与returnTo。",
            "Chat右侧上下文区显示当前引用、来源位置和返回动作；对F6测验、沙盒、费曼及F7阅读器的既有入口做保护测试。",
        ],
        [
            "API/前端合同测试有效、无权限、失效和版本漂移ContextRef及返回链接。",
            "E2E从一个资源页和测评报告进入对话、追问、打开来源并返回，确认学习事件计数不因引用变化。",
        ],
    ),
    "G22-R08": item(
        "学生提出动态问题后先获得可读、可引用的流式回答，再从最多三项轻量动作选择生成学习资源；生成任务和完整产物归档到学习空间而不铺满对话。",
        [
            "普通chat请求不能自动生成九类完整资源或修改学习计划；只有学生点击明确资源动作才创建GenerationJob。",
            "回答中的资源动作必须基于当前课程、知识点、画像、最近事件和来源；不得把/matrix或固定示例作为默认行为。",
            "生成失败保留回答和问题，单项重试只重放失败任务；完整资源正文、版本历史和编辑器只在学习空间显示。",
        ],
        [
            "stream_api.py保持先回答路径，并返回可解释的action candidates；app/chat_api.py把确认动作映射到现有GenerationJob/Resource协议。",
            "Chat.vue只展示紧凑资源摘要、生成状态、失败重试与workspace深链，删除旧内嵌完整resource content展开。",
        ],
        [
            "API测试回答与生成动作分离、幂等GenerationJob、部分失败和资源内容不进入chat payload。",
            "E2E先完成问答，再生成单一资源，确认对话只见摘要且正式资源空间保存历史、版本与来源。",
        ],
    ),
    "G04-R01": item(
        "F7-T04嵌入单题时必须继续使用F6-T01已经交付的真实可交互题目与服务端attempt协议，不能退化为Markdown题干。",
        [
            "不得复制或改写题目评分逻辑，也不得在聊天前端判断正确性。",
            "F6完整测验资源路由、历史和刷新恢复保持可用。",
        ],
        [
            "复用InlineQuizCard和resource/question identity，只新增Chat紧凑承载与深链适配。",
        ],
        [
            "重跑F6-T01合同/API测试并验证Chat题卡提交调用相同接口。",
        ],
    ),
    "G04-R02": item(
        "对话单题提交后仍由F6服务端即时判分，并原位显示正确答案、解析和来源。",
        [
            "提交失败必须保留选择并可重试；未提交前不得泄露答案。",
            "Chat不得创建第二种判分结果或静态成功动画。",
        ],
        [
            "保持InlineQuizCard submitted结果结构和来源回调，只适配紧凑对话布局。",
        ],
        [
            "F6回归与E2E验证正确/错误、失败重试和解析原位展开。",
        ],
    ),
    "G04-R03": item(
        "学生在对话内修改答案再次提交时，F6不可变attempt历史仍保留每次服务端结果。",
        [
            "重新选择不覆盖旧attempt，不重复写同一幂等提交，也不把第二次提交冒充首次结果。",
            "刷新后以服务端最新attempt恢复，同时完整历史仍在测验资源。",
        ],
        [
            "复用InlineQuizCard的重答动作和F6 attempt修订机制，不在Chat另存答案。",
        ],
        [
            "F6保护测试与Chat E2E连续提交两次并核对历史、最新状态和事件幂等性。",
        ],
    ),
    "G04-R04": item(
        "学生可把题干、自己的答案、服务端结果和解析作为结构化上下文继续在智能对话中追问。",
        [
            "追问是普通question事件，不得重新评分或直接改变掌握度；不得只拼接不可定位的长文本。",
            "题目或来源无权限/失效时保留问题草稿并提示重新选择上下文。",
        ],
        [
            "将InlineQuizCard follow-up事件转换为带resourceId、questionVersionId、attemptId和sourceRefs的ContextRef。",
        ],
        [
            "合同/API测试上下文身份与权限；E2E从判分结果追问并返回同一题。",
        ],
    ),
    "G04-R05": item(
        "对话单题的正式判分结果继续通过F6/F2可信事件聚合到画像、错题和复习，Chat自身不直接写这些下游对象。",
        [
            "打开、选择、追问、查看解析或资源深链都不能创建学习证据。",
            "重复提交和页面恢复不得重复聚合；失败attempt不能伪装为有效完成。",
        ],
        [
            "保持F6 attempt消费者和F2聚合器不变，只验证Chat调用同一正式端点。",
        ],
        [
            "隔离SQLite比较提交前后事件、画像、错题和复习，并验证幂等重放。",
        ],
    ),
    "G04-R07": item(
        "Chat只展示由F6生成协议依据当前课程、知识点、画像、掌握证据和最近事件产生的题目，示例题绝不成为固定产品行为。",
        [
            "不得在Chat.vue、测试fixture以外的生产代码或默认消息中硬编码题干/答案。",
            "没有匹配的canonical题目时显示去学习空间生成资源，而不是本地拼题。",
        ],
        [
            "Chat题卡只接受resourceId/questionVersionId，缺失时提供资源生成深链。",
        ],
        [
            "静态合同扫描固定题干并用两种课程/画像fixture验证题目身份不同。",
        ],
    ),
    "G04-R08": item(
        "对话内只承载当前单题的紧凑交互；完整题组、历史、版本和继续练习入口始终归档在学习空间测验题资源。",
        [
            "不得在Chat保留canonical quiz标签页、题组strip或题组查找工作台。",
            "对话历史只保存resourceLink和单题结果摘要，不复制整份题组数据。",
        ],
        [
            "删除Chat完整测验tab并保留明确的/workspace/resources/quizzes/:resourceId深链。",
        ],
        [
            "前端合同检查无题组工作台，E2E验证深链恢复同一资源历史。",
        ],
    ),
    "G12-R04": item(
        "F7-T04必须为F7-T05保留真实问答阶段、来源和状态数据，使后续可展示公开AI工作摘要，但本任务不把内部progress文本伪装成完整Agent审计。",
        [
            "不得展示私有推理、系统提示词、原始日志或未发生的候选/分歧。",
            "F7-T05仍是职责、候选、分歧、校验、修订和决策摘要的唯一主责任务。",
        ],
        [
            "保存streamCheckpoint和结构化公开阶段接口；Chat右栏只显示当前上下文/来源及诚实的基础处理状态。",
        ],
        [
            "静态与API测试确认字段可供F7-T05扩展且当前UI无伪造审计结论。",
        ],
    ),
    "G12-R05": item(
        "智能对话无论附件解析或流式回答都不能声称展示模型私有思维链，只能呈现可审计的职责、输入、输出和校验事实。",
        [
            "禁止向客户端返回prompt、secret、raw trace、chain_of_thought、reasoning_content或供应商原始日志。",
            "Word中的详细思考过程按批准决策解释为公开处理摘要，不改变F7-T05主责。",
        ],
        [
            "在新chat API、stream事件和前端渲染中执行字段白名单；保留F7-T05的公开摘要扩展点。",
        ],
        [
            "敏感字段合同测试和响应递归扫描；E2E确认错误/展开区无内部信息。",
        ],
    ),
    "G12-R07": item(
        "F7-T04继续提供真正的增量流式回答、停止和恢复checkpoint，并为F7-T05的结构化四阶段公开摘要保留稳定关联。",
        [
            "停止只中断当前流，不写完成事件；恢复从已保存内容继续，不重复用户消息和已接收片段。",
            "本任务不虚构候选、分歧、校验或修订；完整四阶段展示在F7-T05逐原子实施后才可宣称完成。",
        ],
        [
            "扩展chat store/stream API的messageId、streamCheckpoint、stop/retry/continue协议，并保持旧流式内容兼容。",
        ],
        [
            "流中断、主动停止、刷新恢复和重复事件测试；保护F7-T05字段关联且无私有推理。",
        ],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F7-T04_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F7-T04 ledger, found {len(matches)}")
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
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F7-T04")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F7-T04",
        entries=expected,
    )
    failures.extend(validate_understanding(ledger, expected))
    if failures:
        raise RuntimeError("F7-T04 understanding validation failed: " + ", ".join(failures))
    print(f"updated {ledger_path.relative_to(ROOT).as_posix()} ({len(expected)} atoms)")


if __name__ == "__main__":
    main()
