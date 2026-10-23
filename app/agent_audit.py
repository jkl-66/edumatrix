"""Sanitized public audit snapshots for multi-Agent collaboration."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.database import DBAgentRun, DBGenerationTask, DBTaskEvent
from app.m1_repository import append_task_event
from app.m2_contracts import StrictModel


AGENT_AUDIT_EVENT = "agent.audit.snapshot"
AgentAuditStatus = Literal["pending", "running", "completed", "failed", "stopped"]
ChatAuditStatus = Literal["queued", "streaming", "completed", "failed", "stopped"]
PublicRunStatus = Literal["pending", "queued", "running", "completed", "failed", "stopped", "needs_input"]

PUBLIC_RUN_EVENT_TYPES = frozenset({
    "run.started",
    "run.retry",
    "run.completed",
    "run.failed",
    "run.stopped",
    "context.frozen",
    "stage.started",
    "stage.progress",
    "stage.completed",
    "stage.failed",
    "source.bound",
    "claim.checked",
    "resource.item.started",
    "resource.item.progress",
    "resource.item.completed",
    "resource.item.failed",
    "review_gate.started",
    "review_gate.passed",
    "review_gate.failed",
    "publish.completed",
})

_FORBIDDEN_KEY_PARTS = (
    "prompt",
    "api_key",
    "apikey",
    "secret",
    "credential",
    "raw_log",
    "rawlog",
    "raw_trace",
    "rawtrace",
    "chain_of_thought",
    "chainofthought",
    "private_reasoning",
    "privatereasoning",
    "reasoning_content",
    "reasoningcontent",
)
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*", re.IGNORECASE),
    re.compile(
        r"\b(?:api[_ -]?key|secret|password|token)\s*[:=]\s*[^\s,;]+",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:system[_ -]?prompt|user[_ -]?prompt|prompt|api[_ -]?key|raw[_ -]?log|"
        r"raw[_ -]?trace|chain[_ -]?of[_ -]?thought|private[_ -]?reasoning|reasoning[_ -]?content)\b",
        re.IGNORECASE,
    ),
)


class PublicAgentRun(StrictModel):
    """The only Agent execution shape exposed to product surfaces."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: str = Field(alias="runId")
    role: str
    input_refs: tuple[str, ...] = Field(alias="inputRefs")
    candidate_summary: str = Field(alias="candidateSummary")
    disagreement: str
    validation: str
    revision: str
    decision_summary: str = Field(alias="decisionSummary")
    status: AgentAuditStatus


class PublicAgentAudit(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(alias="schemaVersion", default="edumatrix.agent-audit.v1")
    run_id: str = Field(alias="runId")
    mode: Literal["live", "historical", "frozen_demo"] = "live"
    status: AgentAuditStatus
    items: tuple[PublicAgentRun, ...]
    historical_result: dict[str, Any] | None = Field(alias="historicalResult", default=None)
    events: tuple[dict[str, Any], ...] = Field(default_factory=tuple)


class PublicRunEvent(StrictModel):
    """Sanitized event projection shared by message cards and the inspector."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    event_id: str = Field(alias="eventId")
    run_id: str = Field(alias="runId")
    event_type: str = Field(alias="eventType")
    stage_id: str = Field(alias="stageId", default="")
    resource_item_id: str = Field(alias="resourceItemId", default="")
    public_status: PublicRunStatus = Field(alias="publicStatus", default="pending")
    owner: str = ""
    summary: str = ""
    input_refs: tuple[str, ...] = Field(alias="inputRefs", default_factory=tuple)
    output_refs: tuple[str, ...] = Field(alias="outputRefs", default_factory=tuple)
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    retryable: bool = False


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def _clean_text(value: Any) -> str:
    text = " ".join(str(value or "").split())
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text[:1200]


def sanitize_public_value(value: Any) -> Any:
    """Remove private execution material before it reaches an audit event."""

    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            normalized = _normalized_key(key)
            if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
                continue
            cleaned[str(key)] = sanitize_public_value(item)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [sanitize_public_value(item) for item in value]
    if isinstance(value, str):
        return _clean_text(value)
    return value


def _input_refs(values: Any) -> tuple[str, ...]:
    if not values:
        return ()
    cleaned = sanitize_public_value(values)
    flattened: list[Any] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif value is not None:
            flattened.append(value)

    collect(cleaned)
    return tuple(dict.fromkeys(_clean_text(value) for value in flattened if _clean_text(value)))


def build_public_run_event(
    *,
    event_id: str,
    run_id: str,
    event_type: str,
    stage_id: str = "",
    resource_item_id: str = "",
    public_status: PublicRunStatus = "pending",
    owner: str = "",
    summary: str = "",
    input_refs: Any = (),
    output_refs: Any = (),
    progress: float | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    """Create one allow-listed, sanitized event for every product projection."""
    if event_type not in PUBLIC_RUN_EVENT_TYPES:
        raise ValueError(f"unsupported_public_run_event:{event_type}")
    event = PublicRunEvent(
        eventId=_clean_text(event_id),
        runId=_clean_text(run_id),
        eventType=event_type,
        stageId=_clean_text(stage_id),
        resourceItemId=_clean_text(resource_item_id),
        publicStatus=public_status,
        owner=_clean_text(owner),
        summary=_clean_text(summary),
        inputRefs=_input_refs(input_refs),
        outputRefs=_input_refs(output_refs),
        progress=progress,
        retryable=bool(retryable),
    )
    return event.model_dump(mode="json", by_alias=True)


def append_public_run_event(
    checkpoint: dict[str, Any] | None,
    *,
    run_id: str,
    event_type: str,
    stage_id: str = "",
    resource_item_id: str = "",
    public_status: PublicRunStatus = "pending",
    owner: str = "",
    summary: str = "",
    input_refs: Any = (),
    output_refs: Any = (),
    progress: float | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    """Append a truthful event to the existing message checkpoint idempotently."""
    next_checkpoint = dict(checkpoint or {})
    stable_run_id = _clean_text(run_id)
    events = [dict(item) for item in (next_checkpoint.get("runEvents") or []) if isinstance(item, dict)]
    normalized_input_refs = list(_input_refs(input_refs))
    normalized_output_refs = list(_input_refs(output_refs))
    duplicate = any(
        item.get("runId") == stable_run_id
        and item.get("eventType") == event_type
        and item.get("stageId", "") == _clean_text(stage_id)
        and item.get("publicStatus") == public_status
        and (
            (not normalized_input_refs and not normalized_output_refs)
            or (
                list(item.get("inputRefs") or []) == normalized_input_refs
                and list(item.get("outputRefs") or []) == normalized_output_refs
            )
        )
        and item.get("resourceItemId", "") == _clean_text(resource_item_id)
        for item in events
    )
    if not duplicate:
        events.append(build_public_run_event(
            event_id=f"{stable_run_id}:event:{len(events) + 1}",
            run_id=stable_run_id,
            event_type=event_type,
            stage_id=stage_id,
            resource_item_id=resource_item_id,
            public_status=public_status,
            owner=owner,
            summary=summary,
            input_refs=input_refs,
            output_refs=output_refs,
            progress=progress,
            retryable=retryable,
        ))
    next_checkpoint["runId"] = stable_run_id
    next_checkpoint["runEvents"] = events
    return next_checkpoint


def public_run_events(values: Any) -> tuple[dict[str, Any], ...]:
    """Validate and sanitize persisted events before exposing them."""
    result: list[dict[str, Any]] = []
    for value in values or ():
        if isinstance(value, dict):
            result.append(PublicRunEvent.model_validate(value).model_dump(mode="json", by_alias=True))
    return tuple(result)


def build_public_agent_run(
    *,
    run_id: str,
    role: str,
    input_refs: Any = (),
    candidate_summary: Any = "",
    disagreement: Any = "",
    validation: Any = "",
    revision: Any = "",
    decision_summary: Any = "",
    status: AgentAuditStatus,
) -> PublicAgentRun:
    """Build the approved public shape from service facts without persistence side effects."""
    return PublicAgentRun(
        runId=_clean_text(run_id),
        role=_clean_text(role),
        inputRefs=_input_refs(input_refs),
        candidateSummary=_clean_text(sanitize_public_value(candidate_summary)),
        disagreement=_clean_text(sanitize_public_value(disagreement)),
        validation=_clean_text(sanitize_public_value(validation)),
        revision=_clean_text(sanitize_public_value(revision)),
        decisionSummary=_clean_text(sanitize_public_value(decision_summary)),
        status=status,
    )


def build_chat_agent_audit(
    *,
    message_id: str,
    status: ChatAuditStatus,
    input_refs: Any = (),
    source_count: int = 0,
    source_unavailable_count: int = 0,
    attachment_count: int = 0,
    received_characters: int = 0,
    answer_has_inline_citations: bool = False,
    failure_message: Any = "",
    historical_result: dict[str, Any] | None = None,
    has_real_run: bool = True,
    execution_mode: str = "",
    run_events: Any = (),
) -> dict[str, Any]:
    """Build a truthful four-stage audit from the canonical Chat state machine."""
    audit_id = f"chat-audit-{message_id}"
    # The chat message is the canonical answer run. Keep every public stage
    # tied to that stable run and its source snapshot; no second audit store
    # is introduced.
    stable_refs = [f"chat:{message_id}", f"run:{audit_id}", *(_input_refs(input_refs) or ())]
    generation_status: AgentAuditStatus = {
        "queued": "pending",
        "streaming": "running",
        "completed": "completed",
        "failed": "failed",
        "stopped": "stopped",
    }[status]
    later_status: AgentAuditStatus = "completed" if status == "completed" else "pending"
    audit_status: AgentAuditStatus = {
        "queued": "pending",
        "streaming": "running",
        "completed": "completed",
        "failed": "failed",
        "stopped": "stopped",
    }[status]
    generation_summary = {
        "queued": "已冻结本次输入，等待服务端开始生成回答。",
        "streaming": f"服务端正在流式生成回答，已保存 {max(0, received_characters)} 个字符。",
        "completed": f"流式回答已完成并保存，共 {max(0, received_characters)} 个字符。",
        "failed": "本次模型生成失败，已保留已接收内容和失败状态。",
        "stopped": "本次生成已按用户操作停止，已保留当前内容。",
    }[status]
    if execution_mode == "deterministic_local":
        generation_summary = f"本次使用 deterministic_local 确定性模式；{generation_summary}"
    elif execution_mode == "fallback":
        generation_summary = f"本次使用 fallback 降级结果；{generation_summary}"
    validation_summary = ""
    if status == "completed":
        if source_count <= 0:
            validation_summary = "未找到可核验课程来源；本次结果仅作为未审核草稿，不能标记为已审核或已发布。"
        elif source_unavailable_count > 0:
            validation_summary = f"{source_unavailable_count} 条来源不可用；本次结果降级为风险草稿，不能标记为已审核或已发布。"
        else:
            citation_state = "正文包含显式引用标记" if answer_has_inline_citations else "来源在回答旁作为可定位引用保留"
            validation_summary = f"已核对 {max(0, source_count)} 条课程来源；{citation_state}。"
    failed_reason = _clean_text(sanitize_public_value(failure_message)) if status == "failed" else ""
    items = (
        build_public_agent_run(
            run_id=f"{audit_id}:analysis",
            role="analysis",
            input_refs=stable_refs,
            candidate_summary=(
                f"服务端已确认本次问题上下文、{max(0, source_count)} 条课程来源"
                f"和 {max(0, attachment_count)} 个已解析附件。"
            ),
            validation="输入身份与可公开来源已经冻结。",
            decision_summary="进入回答生成。",
            status="completed",
        ),
        build_public_agent_run(
            run_id=f"{audit_id}:generation",
            role="generation",
            input_refs=stable_refs,
            candidate_summary=generation_summary,
            validation=failed_reason,
            decision_summary=("等待继续或重试。" if status in {"failed", "stopped"} else ""),
            status=generation_status,
        ),
        build_public_agent_run(
            run_id=f"{audit_id}:validation",
            role="validation",
            input_refs=stable_refs if status == "completed" else (),
            validation=validation_summary,
            decision_summary="来源状态与回答引用已形成公开校验摘要。" if status == "completed" else "",
            status=later_status,
        ),
        build_public_agent_run(
            run_id=f"{audit_id}:decision",
            role="decision",
            input_refs=stable_refs if status == "completed" else (),
            decision_summary=(
                "本次回答已保存；学生可查看来源并继续学习。"
                if status == "completed" and source_count > 0 and source_unavailable_count == 0
                else "本次回答仅保存为未审核风险草稿，需补充可用来源后再审核。"
                if status == "completed"
                else ""
            ),
            status=later_status,
        ),
    )
    if not has_real_run:
        items = tuple(
            item.model_copy(update={"status": "pending", "input_refs": ()})
            for item in items
        )
        audit_status = "pending"
        run_events = ()
    public_history = None
    if historical_result:
        public_history = {}
        for key in ("label", "messageId", "completedAt", "preview", "route"):
            value = historical_result.get(key)
            if value is not None and value != "":
                public_history[key] = sanitize_public_value(value)
    audit = PublicAgentAudit(
        runId=audit_id,
        status=audit_status,
        items=items,
        historicalResult=public_history,
        events=public_run_events(run_events),
    ).model_dump(mode="json", by_alias=True)
    assert_public_audit_is_sanitized(audit)
    return audit


def build_selection_agent_audit(
    *,
    selection_id: str,
    source_ref_id: str | None,
    answer_status: str,
    has_evidence: bool,
) -> dict[str, Any] | None:
    """Project the persisted selection-answer facts as a public audit summary."""
    if answer_status == "idle":
        return None
    audit_id = f"selection-audit-{selection_id}"
    input_refs = [f"selection:{selection_id}"]
    if source_ref_id:
        input_refs.append(f"source:{source_ref_id}")
    ready = answer_status == "ready" and has_evidence
    generation_status: AgentAuditStatus = "completed" if ready else "failed"
    later_status: AgentAuditStatus = "completed" if ready else "pending"
    audit = PublicAgentAudit(
        runId=audit_id,
        status="completed" if ready else "failed",
        items=(
            build_public_agent_run(
                run_id=f"{audit_id}:analysis",
                role="analysis",
                input_refs=input_refs,
                candidate_summary="服务端已读取当前选区及其冻结来源位置。",
                validation="选区身份与文档版本已经核对。",
                decision_summary="仅使用当前选区作为回答依据。",
                status="completed",
            ),
            build_public_agent_run(
                run_id=f"{audit_id}:generation",
                role="generation",
                input_refs=input_refs,
                candidate_summary=(
                    "已依据选区原文整理回答。"
                    if ready else "当前选区没有可验证文字，未生成无依据回答。"
                ),
                validation="" if ready else "图片 OCR 未提供可验证文字。",
                decision_summary="" if ready else "保留选区，等待重试 OCR 或重新框选。",
                status=generation_status,
            ),
            build_public_agent_run(
                run_id=f"{audit_id}:validation",
                role="validation",
                input_refs=input_refs if ready else (),
                validation="回答内容被限制在当前选区证据范围内。" if ready else "",
                decision_summary="来源引用可反向定位到原文。" if ready else "",
                status=later_status,
            ),
            build_public_agent_run(
                run_id=f"{audit_id}:decision",
                role="decision",
                input_refs=input_refs if ready else (),
                decision_summary="选区回答已保存，可查看来源或继续提问。" if ready else "",
                status=later_status,
            ),
        ),
    ).model_dump(mode="json", by_alias=True)
    assert_public_audit_is_sanitized(audit)
    return audit


def _owned_task(session: Any, task_id: str, owner_public_id: str) -> DBGenerationTask:
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if task is None:
        raise ValueError("task_not_found")
    if task.owner_public_id != owner_public_id:
        raise PermissionError("task_forbidden")
    return task


def record_agent_audit(
    session: Any,
    *,
    run: DBAgentRun,
    input_refs: Any = (),
    candidate_summary: Any = "",
    disagreement: Any = "",
    validation: Any = "",
    revision: Any = "",
    decision_summary: Any = "",
    status: AgentAuditStatus | None = None,
) -> PublicAgentRun:
    public = PublicAgentRun(
        runId=run.id,
        role=_clean_text(sanitize_public_value(run.role)),
        inputRefs=_input_refs(input_refs),
        candidateSummary=_clean_text(sanitize_public_value(candidate_summary)),
        disagreement=_clean_text(sanitize_public_value(disagreement)),
        validation=_clean_text(sanitize_public_value(validation)),
        revision=_clean_text(sanitize_public_value(revision)),
        decisionSummary=_clean_text(sanitize_public_value(decision_summary)),
        status=status or run.status,
    )
    append_task_event(
        session,
        task_id=run.task_id,
        event_type=AGENT_AUDIT_EVENT,
        payload=public.model_dump(mode="json", by_alias=True),
    )
    return public


def public_agent_runs(session: Any, *, task_id: str, owner_public_id: str) -> list[PublicAgentRun]:
    _owned_task(session, task_id, owner_public_id)
    events = (
        session.query(DBTaskEvent)
        .filter_by(task_id=task_id, event_type=AGENT_AUDIT_EVENT)
        .order_by(DBTaskEvent.sequence)
        .all()
    )
    latest: dict[str, PublicAgentRun] = {}
    order: list[str] = []
    for event in events:
        payload = sanitize_public_value(event.payload or {})
        item = PublicAgentRun.model_validate(payload)
        if item.run_id not in latest:
            order.append(item.run_id)
        latest[item.run_id] = item
    return [latest[run_id] for run_id in order]


def public_agent_audit_payload(session: Any, *, task_id: str, owner_public_id: str) -> dict[str, Any]:
    task = _owned_task(session, task_id, owner_public_id)
    items = public_agent_runs(session, task_id=task_id, owner_public_id=owner_public_id)
    return {
        "taskId": task.id,
        "traceId": task.trace_id,
        "status": task.status,
        "items": [item.model_dump(mode="json", by_alias=True) for item in items],
    }


def assert_public_audit_is_sanitized(payload: Any) -> None:
    """Test helper and defensive boundary for public audit DTOs."""

    encoded = json.dumps(payload, ensure_ascii=False).lower()
    forbidden = (
        "system_prompt",
        "user_prompt",
        "api_key",
        "raw_log",
        "raw_trace",
        "chain_of_thought",
        "private_reasoning",
        "reasoning_content",
        "bearer ",
    )
    found = [term for term in forbidden if term in encoded]
    if re.search(r"\bsk-[a-z0-9_-]{8,}\b", encoded, re.IGNORECASE):
        found.append("api_key_value")
    if found:
        raise ValueError(f"public_agent_audit_contains_private_material:{','.join(found)}")
