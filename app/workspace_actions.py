"""Structured R2 workspace actions over existing tutor, task, note, and path facts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import func

from app.database import (
    DBArtifact,
    DBLearningPath,
    DBNote,
    DBPathNode,
    DBStudentProfile,
    DBTutorContextSession,
)
from app.m1_lifecycle import record_audit
from app.m2_contracts import StrictModel
from app.m5_capabilities import (
    Capability,
    CapabilityContract,
    OutputConstraints,
    QualityMode,
    RoutingRequest,
    RuntimeAvailability,
)
from app.m5_tasks import create_capability_task
from app.m5_workspace import TutorPromptPreflight, tutor_prompt_envelope, workspace_overview


WorkspaceAction = Literal["explain", "example", "quiz", "experiment", "add_note", "add_path"]


class WorkspaceActionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class WorkspaceActionRequest(StrictModel):
    schema_version: Literal["r2.workspace-action.v1"] = "r2.workspace-action.v1"
    context_session_id: str = Field(min_length=1, max_length=64)
    action: WorkspaceAction
    idempotency_key: str = Field(min_length=8, max_length=128)
    instruction: str = Field(default="", max_length=2000)


def _fail(code: str, message: str) -> None:
    raise WorkspaceActionError(code, message)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:48]}"


def _load_context(
    session: Any, *, current_user: Any, request: WorkspaceActionRequest,
) -> tuple[DBTutorContextSession, dict[str, Any], dict[str, Any]]:
    row = session.query(DBTutorContextSession).filter_by(id=request.context_session_id).first()
    if row is None:
        _fail("workspace_action_context_unknown", "当前学习上下文不存在，请重新选择学习对象。")
    if row.owner_public_id != current_user.public_id:
        _fail("workspace_action_context_forbidden", "当前学习上下文属于其他用户。")
    if row.status != "active":
        _fail("workspace_action_context_archived", "当前学习上下文已归档，请重新创建上下文。")
    if row.primary_object_type != "workspace_object" or not row.course_id:
        _fail("workspace_action_context_invalid", "请先在学习空间选择一个当前学习对象。")

    overview = workspace_overview(session, current_user=current_user, course_id=row.course_id)
    current_object = next((
        item for item in overview.get("learning_objects", [])
        if item.get("id") == row.primary_object_id
    ), None)
    if current_object is None:
        _fail("workspace_action_object_unavailable", "当前学习对象已不可用，请刷新后重新选择。")
    snapshot = row.context_snapshot or {}
    if snapshot.get("course_id") != row.course_id:
        _fail("workspace_action_context_conflict", "学习上下文与当前课程不一致，请重新创建上下文。")
    return row, current_object, snapshot


def _prompt(action: WorkspaceAction, current_object: dict[str, Any], instruction: str) -> str:
    if instruction.strip():
        return instruction.strip()
    title = str(current_object.get("title") or "当前学习对象")
    prompts = {
        "explain": f"请结合当前课程来源，清晰解释“{title}”。",
        "example": f"请结合当前课程，为“{title}”给出一个具体、可验证的例子。",
        "quiz": f"请围绕“{title}”生成一组与当前章节匹配的练习题。",
        "experiment": f"请围绕“{title}”生成一个可交互、可验证的教学实验。",
    }
    return prompts.get(action, title)


def _quick_action(
    session: Any, *, row: DBTutorContextSession, request: WorkspaceActionRequest,
    current_object: dict[str, Any],
) -> dict[str, Any]:
    prompt = _prompt(request.action, current_object, request.instruction)
    envelope = tutor_prompt_envelope(
        session,
        row=row,
        owner_public_id=row.owner_public_id,
        request=TutorPromptPreflight(
            question=prompt,
            intent="example" if request.action == "example" else "explain",
        ),
    )
    return {
        "schema_version": "r2.workspace-action-result.v1",
        "action": request.action,
        "execution_mode": "chat",
        "capability": Capability.ANSWER.value,
        "capability_locked": True,
        "task_created": False,
        "context_session_id": row.id,
        "chat": {
            "route": "/learn",
            "prompt": prompt,
            "intent": envelope["intent"],
        },
    }


def _generation_action(
    session: Any, *, current_user: Any, row: DBTutorContextSession,
    current_object: dict[str, Any], snapshot: dict[str, Any],
    request: WorkspaceActionRequest, runtime: RuntimeAvailability, model: str,
) -> dict[str, Any]:
    capability = Capability.QUIZ if request.action == "quiz" else Capability.EXPERIMENT
    if capability == Capability.EXPERIMENT and runtime.sandbox_mode == "disabled":
        _fail("workspace_action_runtime_unavailable", "当前未启用交互实验运行环境。")

    source_document_ids = tuple(dict.fromkeys(
        str(item.get("source_document_id"))
        for item in snapshot.get("sources", [])
        if item.get("source_document_id")
    ))
    artifact = session.query(DBArtifact).filter_by(id=current_object.get("id")).first()
    active_artifact_ids = (
        (artifact.id,) if artifact is not None and artifact.owner_public_id == current_user.public_id else ()
    )
    constraints = OutputConstraints(
        format="json" if capability == Capability.QUIZ else "interactive_artifact",
        runtime_mode=runtime.sandbox_mode if capability == Capability.EXPERIMENT else None,
        safety_boundary=(
            "Use only the configured research runtime; do not claim external-lab execution."
            if capability == Capability.EXPERIMENT else ""
        ),
    )
    contract = CapabilityContract(
        capability=capability,
        quality_mode=QualityMode.STANDARD,
        course_id=row.course_id,
        active_artifact_ids=active_artifact_ids,
        source_document_ids=source_document_ids,
        output_constraints=constraints,
        idempotency_key=request.idempotency_key,
    )
    task, created = create_capability_task(
        session,
        owner_public_id=current_user.public_id,
        request=RoutingRequest(
            contract=contract,
            message=_prompt(request.action, current_object, request.instruction),
        ),
        runtime=runtime,
        model=model,
    )
    record_audit(
        session,
        actor_public_id=current_user.public_id,
        action="workspace_action.task_created" if created else "workspace_action.task_reused",
        object_type="generation_task",
        object_id=task.id,
        metadata={"workspace_action": request.action, "capability": capability.value, "course_id": row.course_id},
    )
    return {
        "schema_version": "r2.workspace-action-result.v1",
        "action": request.action,
        "execution_mode": "background_task",
        "capability": capability.value,
        "capability_locked": True,
        "task_created": created,
        "context_session_id": row.id,
        "task": {
            "task_id": task.id,
            "status": task.status,
            "progress": task.progress,
            "capability": task.capability,
            "model": task.model,
        },
    }


def _note_action(
    session: Any, *, current_user: Any, row: DBTutorContextSession,
    current_object: dict[str, Any], snapshot: dict[str, Any], request: WorkspaceActionRequest,
) -> dict[str, Any]:
    profile = session.query(DBStudentProfile).filter_by(student_id=current_user.username).first()
    if profile is None:
        _fail("workspace_action_note_profile_required", "请先完成学习画像初始化，再加入笔记。")
    note_id = _stable_id("r2note", current_user.public_id, row.id, request.idempotency_key)
    title = str(current_object.get("title") or "当前学习对象")
    selected_text = str(snapshot.get("selected_text") or "").strip()
    body = request.instruction.strip() or selected_text or f"记录“{title}”的关键概念、证据和待复习问题。"
    content = f"{title}\n\n{body}\n\n课程：{snapshot.get('course_title') or row.course_id}"
    tags = ["学习空间", row.course_id, str(current_object.get("object_type") or "resource")]
    concepts = list((snapshot.get("profile_summary") or {}).get("weak_knowledge_points") or [])[:3]
    existing = session.query(DBNote).filter_by(id=note_id).first()
    if existing is not None:
        if (
            existing.student_id != current_user.username
            or existing.source != "learning_workspace"
            or existing.content != content
            or list(existing.tags or []) != tags
            or list(existing.concepts or []) != concepts
        ):
            _fail("workspace_action_idempotency_conflict", "该操作标识已经绑定到另一条笔记。")
        note = existing
        created = False
    else:
        note = DBNote(
            id=note_id,
            student_id=current_user.username,
            source="learning_workspace",
            content=content,
            tags=tags,
            concepts=concepts,
        )
        session.add(note)
        session.flush()
        created = True
        record_audit(
            session,
            actor_public_id=current_user.public_id,
            action="workspace_action.note_added",
            object_type="note",
            object_id=note.id,
            metadata={"course_id": row.course_id, "context_session_id": row.id},
        )
    return {
        "schema_version": "r2.workspace-action-result.v1",
        "action": request.action,
        "execution_mode": "deterministic_write",
        "capability": "note",
        "capability_locked": True,
        "task_created": False,
        "context_session_id": row.id,
        "note": {"id": note.id, "created": created, "source": note.source},
    }


def _path_action(
    session: Any, *, current_user: Any, row: DBTutorContextSession,
    current_object: dict[str, Any], request: WorkspaceActionRequest,
) -> dict[str, Any]:
    path = session.query(DBLearningPath).filter(
        DBLearningPath.owner_public_id == current_user.public_id,
        DBLearningPath.course_id == row.course_id,
        DBLearningPath.status == "active",
    ).order_by(DBLearningPath.updated_at.desc(), DBLearningPath.id).first()
    if path is None:
        _fail("workspace_action_active_path_required", "当前没有进行中的学习路径，请先恢复或确认学习路径。")

    node_id = _stable_id("r2node", current_user.public_id, path.id, row.id, request.idempotency_key)
    title = request.instruction.strip() or f"继续学习：{current_object.get('title') or '当前对象'}"
    node_key = f"workspace-action:{hashlib.sha256(node_id.encode('utf-8')).hexdigest()[:24]}"
    existing = session.query(DBPathNode).filter_by(id=node_id).first()
    if existing is not None:
        if (
            existing.learning_path_id != path.id
            or existing.node_key != node_key
            or existing.target_object_id != current_object.get("id")
            or existing.title != title[:256]
        ):
            _fail("workspace_action_idempotency_conflict", "该操作标识已经绑定到另一项路径任务。")
        node = existing
        created = False
    else:
        next_sequence = int(session.query(func.max(DBPathNode.sequence)).filter_by(
            learning_path_id=path.id,
        ).scalar() or 0) + 1
        node = DBPathNode(
            id=node_id,
            learning_path_id=path.id,
            node_key=node_key,
            sequence=next_sequence,
            node_type="workspace_action",
            target_object_id=str(current_object.get("id") or "") or None,
            title=title[:256],
            status="pending",
            prerequisites=[],
            is_extension=True,
            resource_status="existing",
            estimate_min_minutes=10,
            estimate_max_minutes=20,
        )
        session.add(node)
        path.lock_version += 1
        path.updated_at = _now()
        session.flush()
        created = True
        record_audit(
            session,
            actor_public_id=current_user.public_id,
            action="workspace_action.path_item_added",
            object_type="path_node",
            object_id=node.id,
            metadata={"path_id": path.id, "course_id": row.course_id, "context_session_id": row.id},
        )
    return {
        "schema_version": "r2.workspace-action-result.v1",
        "action": request.action,
        "execution_mode": "deterministic_write",
        "capability": "path",
        "capability_locked": True,
        "task_created": False,
        "context_session_id": row.id,
        "path": {
            "path_id": path.id,
            "node_id": node.id,
            "status": node.status,
            "created": created,
        },
    }


def execute_workspace_action(
    session: Any,
    *,
    current_user: Any,
    request: WorkspaceActionRequest,
    runtime: RuntimeAvailability,
    model: str = "",
) -> dict[str, Any]:
    row, current_object, snapshot = _load_context(
        session, current_user=current_user, request=request,
    )
    if request.action in {"explain", "example"}:
        return _quick_action(
            session, row=row, request=request, current_object=current_object,
        )
    if request.action in {"quiz", "experiment"}:
        return _generation_action(
            session,
            current_user=current_user,
            row=row,
            current_object=current_object,
            snapshot=snapshot,
            request=request,
            runtime=runtime,
            model=model,
        )
    if request.action == "add_note":
        return _note_action(
            session,
            current_user=current_user,
            row=row,
            current_object=current_object,
            snapshot=snapshot,
            request=request,
        )
    return _path_action(
        session,
        current_user=current_user,
        row=row,
        current_object=current_object,
        request=request,
    )
