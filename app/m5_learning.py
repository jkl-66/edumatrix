"""Versioned plans, confirmed learning paths, and replayable M5 learning events."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal
import uuid

from pydantic import Field, model_validator

from app.database import (
    DBArtifact,
    DBChapter,
    DBLearningEvent,
    DBLearningEventConsumption,
    DBLearningPath,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
)
from app.m1_lifecycle import record_audit
from app.m2_contracts import StrictModel


class M5LearningError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise M5LearningError(code, message)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class PlanNodeSpec(StrictModel):
    node_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")
    node_type: Literal["chapter", "artifact", "assessment", "interactive", "review", "extension"]
    target_object_id: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    prerequisites: tuple[str, ...] = ()
    resource_status: Literal["existing", "to_generate", "external_dependency"]
    estimate_min_minutes: int = Field(ge=1, le=10080)
    estimate_max_minutes: int = Field(ge=1, le=10080)
    extension_reason: str = Field(default="", max_length=1000)
    required: bool = True
    risk_level: Literal["normal", "high"] = "normal"

    @model_validator(mode="after")
    def valid_estimate_and_target(self) -> "PlanNodeSpec":
        if self.estimate_max_minutes < self.estimate_min_minutes:
            raise ValueError("estimate_max_minutes must be >= estimate_min_minutes")
        if self.node_type == "extension":
            if not self.extension_reason:
                raise ValueError("extension nodes require extension_reason")
        elif not self.target_object_id:
            raise ValueError("formal plan nodes require target_object_id")
        return self


class PlanSpec(StrictModel):
    schema_version: Literal["m5.plan.v1"] = "m5.plan.v1"
    goal: str = Field(min_length=1, max_length=2000)
    deadline: datetime | None = None
    assumptions: tuple[str, ...] = ()
    nodes: tuple[PlanNodeSpec, ...] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def ordered_acyclic_nodes(self) -> "PlanSpec":
        keys = [item.node_key for item in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("plan node keys must be unique")
        seen = set()
        for item in self.nodes:
            if item.node_key in item.prerequisites:
                raise ValueError("plan node cannot depend on itself")
            unknown_or_late = set(item.prerequisites) - seen
            if unknown_or_late:
                raise ValueError(f"prerequisites must reference earlier nodes: {sorted(unknown_or_late)}")
            seen.add(item.node_key)
        return self


LearningEventType = Literal[
    "resource_opened", "reading_started", "reading_threshold",
    "video_started", "video_threshold", "video_completed",
    "explanation_started", "explanation_completed", "note_created",
    "quiz_answered", "code_run", "code_tests_passed",
    "wrong_question_reviewed", "delayed_retest_passed",
    "user_marked_complete", "teacher_confirmed",
]


class LearningEventInput(StrictModel):
    schema_version: Literal["m5.learning-event.v1"] = "m5.learning-event.v1"
    idempotency_key: str = Field(min_length=8, max_length=128)
    event_type: LearningEventType
    course_id: str | None = Field(default=None, max_length=128)
    object_type: str = Field(min_length=1, max_length=64)
    object_id: str = Field(min_length=1, max_length=64)
    source: Literal["frontend", "backend", "sandbox", "media_player", "teacher", "migration"]
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def event_specific_fields(self) -> "LearningEventInput":
        if self.event_type in {"reading_threshold", "video_threshold"}:
            if int(self.payload.get("active_seconds", 0)) <= 0:
                raise ValueError("threshold event requires positive active_seconds")
        if self.event_type == "quiz_answered":
            if not isinstance(self.payload.get("correct"), bool):
                raise ValueError("quiz_answered requires boolean correct")
            confidence = self.payload.get("confidence")
            if confidence is not None and not 0 <= float(confidence) <= 1:
                raise ValueError("quiz confidence must be within [0,1]")
        if self.event_type == "code_tests_passed":
            passed = int(self.payload.get("passed_count", 0))
            total = int(self.payload.get("total_count", 0))
            if total < 1 or passed != total:
                raise ValueError("code_tests_passed requires all tests to pass")
        if self.event_type == "teacher_confirmed" and not self.payload.get("scope"):
            raise ValueError("teacher_confirmed requires an evidence scope")
        return self


def _validate_plan_targets(session: Any, *, owner_public_id: str, course_id: str | None, spec: PlanSpec) -> None:
    for node in spec.nodes:
        if node.node_type == "extension":
            continue
        if node.node_type == "chapter":
            chapter = session.query(DBChapter).filter_by(id=node.target_object_id).first()
            if chapter is None or (course_id and chapter.course_id != course_id):
                _fail("plan_chapter_invalid", f"chapter is not in the confirmed course: {node.node_key}")
            continue
        artifact = session.query(DBArtifact).filter_by(id=node.target_object_id).first()
        if artifact is None or artifact.owner_public_id != owner_public_id:
            _fail("plan_artifact_invalid", f"artifact is unavailable to the plan owner: {node.node_key}")
        if course_id and artifact.course_id not in {None, course_id}:
            _fail("plan_artifact_invalid", f"artifact belongs to another course: {node.node_key}")


def _add_version(
    session: Any,
    *,
    plan: DBPlanDraft,
    spec: PlanSpec,
    actor_public_id: str,
    profile_snapshot_id: str | None,
) -> DBPlanVersion:
    latest = session.query(DBPlanVersion).filter_by(plan_draft_id=plan.id).order_by(
        DBPlanVersion.version_number.desc(),
    ).first()
    payload = spec.model_dump(mode="json")
    version = DBPlanVersion(
        plan_draft_id=plan.id,
        version_number=(latest.version_number + 1) if latest else 1,
        profile_snapshot_id=profile_snapshot_id,
        content=payload,
        content_hash=_hash(payload),
        created_by_public_id=actor_public_id,
    )
    session.add(version)
    session.flush()
    plan.current_version_id = version.id
    return version


def create_plan_draft(
    session: Any,
    *,
    owner_public_id: str,
    course_id: str | None,
    title: str,
    idempotency_key: str,
    spec: PlanSpec,
    profile_snapshot_id: str | None = None,
) -> tuple[DBPlanDraft, DBPlanVersion, bool]:
    _validate_plan_targets(session, owner_public_id=owner_public_id, course_id=course_id, spec=spec)
    existing = session.query(DBPlanDraft).filter_by(
        owner_public_id=owner_public_id, idempotency_key=idempotency_key,
    ).first()
    if existing is not None:
        version = session.query(DBPlanVersion).filter_by(id=existing.current_version_id).first()
        if (
            version is None or version.content_hash != _hash(spec.model_dump(mode="json"))
            or existing.title != title or existing.course_id != course_id
        ):
            _fail("plan_idempotency_conflict", "idempotency key is bound to another plan draft")
        return existing, version, False
    plan = DBPlanDraft(
        owner_public_id=owner_public_id,
        course_id=course_id,
        title=title,
        status="draft",
        idempotency_key=idempotency_key,
    )
    session.add(plan)
    session.flush()
    version = _add_version(
        session, plan=plan, spec=spec, actor_public_id=owner_public_id,
        profile_snapshot_id=profile_snapshot_id,
    )
    record_audit(
        session, actor_public_id=owner_public_id, action="plan.draft_created",
        object_type="plan_draft", object_id=plan.id,
        metadata={"version_id": version.id, "node_count": len(spec.nodes)},
    )
    session.flush()
    return plan, version, True


def plan_version_diff(left: DBPlanVersion, right: DBPlanVersion) -> dict[str, Any]:
    left_nodes = {item["node_key"]: (index, item) for index, item in enumerate(left.content.get("nodes", []))}
    right_nodes = {item["node_key"]: (index, item) for index, item in enumerate(right.content.get("nodes", []))}
    added = sorted(set(right_nodes) - set(left_nodes))
    removed = sorted(set(left_nodes) - set(right_nodes))
    moved = sorted(
        key for key in set(left_nodes) & set(right_nodes)
        if left_nodes[key][0] != right_nodes[key][0]
    )
    changed = sorted(
        key for key in set(left_nodes) & set(right_nodes)
        if left_nodes[key][1] != right_nodes[key][1]
    )
    return {
        "from_version_id": left.id,
        "to_version_id": right.id,
        "added": added,
        "removed": removed,
        "moved": moved,
        "changed": changed,
        "deadline_changed": left.content.get("deadline") != right.content.get("deadline"),
    }


def propose_plan_revision(
    session: Any,
    *,
    plan: DBPlanDraft,
    owner_public_id: str,
    expected_lock_version: int,
    spec: PlanSpec,
    profile_snapshot_id: str | None = None,
) -> tuple[DBPlanVersion, dict[str, Any]]:
    if plan.owner_public_id != owner_public_id:
        _fail("plan_forbidden", "plan belongs to another owner")
    if plan.lock_version != expected_lock_version:
        _fail("plan_version_conflict", "plan lock version changed")
    if plan.status not in {"draft", "confirmed"}:
        _fail("plan_not_revisable", f"cannot revise plan from {plan.status}")
    _validate_plan_targets(session, owner_public_id=owner_public_id, course_id=plan.course_id, spec=spec)
    previous = session.query(DBPlanVersion).filter_by(id=plan.current_version_id).one()
    version = _add_version(
        session, plan=plan, spec=spec, actor_public_id=owner_public_id,
        profile_snapshot_id=profile_snapshot_id,
    )
    diff = plan_version_diff(previous, version)
    plan.status = "draft" if plan.confirmed_version_id is None else "replan_pending"
    plan.lock_version += 1
    record_audit(
        session, actor_public_id=owner_public_id, action="plan.revision_proposed",
        object_type="plan_draft", object_id=plan.id,
        metadata={"version_id": version.id, "diff": diff},
    )
    session.flush()
    return version, diff


def _publish_path(
    session: Any, *, plan: DBPlanDraft, version: DBPlanVersion, previous_path: DBLearningPath | None,
) -> DBLearningPath:
    spec = PlanSpec.model_validate(version.content)
    path = DBLearningPath(
        owner_public_id=plan.owner_public_id,
        course_id=plan.course_id,
        source_plan_version_id=version.id,
        supersedes_path_id=previous_path.id if previous_path else None,
        status="active",
    )
    session.add(path)
    session.flush()
    for sequence, node in enumerate(spec.nodes, start=1):
        session.add(DBPathNode(
            learning_path_id=path.id,
            node_key=node.node_key,
            sequence=sequence,
            node_type=node.node_type,
            target_object_id=node.target_object_id,
            title=node.title,
            prerequisites=list(node.prerequisites),
            is_extension=node.node_type == "extension",
            resource_status=node.resource_status,
            estimate_min_minutes=node.estimate_min_minutes,
            estimate_max_minutes=node.estimate_max_minutes,
        ))
    session.flush()
    return path


def confirm_plan(
    session: Any,
    *,
    plan: DBPlanDraft,
    owner_public_id: str,
    expected_lock_version: int,
) -> DBLearningPath:
    if plan.owner_public_id != owner_public_id:
        _fail("plan_forbidden", "plan belongs to another owner")
    if plan.lock_version != expected_lock_version:
        _fail("plan_version_conflict", "plan lock version changed")
    if plan.status not in {"draft", "replan_pending"}:
        _fail("plan_not_confirmable", f"cannot confirm plan from {plan.status}")
    version = session.query(DBPlanVersion).filter_by(id=plan.current_version_id).one()
    _validate_plan_targets(
        session, owner_public_id=owner_public_id, course_id=plan.course_id,
        spec=PlanSpec.model_validate(version.content),
    )
    previous = session.query(DBLearningPath).join(
        DBPlanVersion, DBPlanVersion.id == DBLearningPath.source_plan_version_id,
    ).filter(
        DBLearningPath.owner_public_id == owner_public_id,
        DBLearningPath.course_id == plan.course_id,
        DBPlanVersion.plan_draft_id == plan.id,
        DBLearningPath.status.in_(("active", "paused")),
    ).order_by(DBLearningPath.created_at.desc()).first()
    if previous is not None:
        previous.status = "archived"
        previous.archived_at = _now()
        previous.lock_version += 1
    path = _publish_path(session, plan=plan, version=version, previous_path=previous)
    plan.status = "confirmed"
    plan.confirmed_version_id = version.id
    plan.confirmed_at = _now()
    plan.lock_version += 1
    record_audit(
        session, actor_public_id=owner_public_id, action="plan.confirmed",
        object_type="plan_draft", object_id=plan.id,
        metadata={"version_id": version.id, "path_id": path.id, "supersedes_path_id": path.supersedes_path_id},
    )
    session.flush()
    return path


def transition_path(
    session: Any,
    *,
    path: DBLearningPath,
    owner_public_id: str,
    target_status: Literal["active", "paused", "archived"],
    expected_lock_version: int,
) -> DBLearningPath:
    if path.owner_public_id != owner_public_id:
        _fail("path_forbidden", "path belongs to another owner")
    if path.lock_version != expected_lock_version:
        _fail("path_version_conflict", "path lock version changed")
    allowed = {
        "active": {"paused", "archived"},
        "paused": {"active", "archived"},
        "completed": {"archived"},
        "archived": set(),
    }
    if target_status == path.status:
        return path
    if target_status not in allowed.get(path.status, set()):
        _fail("path_transition_invalid", f"cannot transition {path.status} to {target_status}")
    path.status = target_status
    path.lock_version += 1
    path.updated_at = _now()
    path.paused_at = _now() if target_status == "paused" else None
    if target_status == "archived":
        path.archived_at = _now()
    record_audit(
        session, actor_public_id=owner_public_id, action=f"learning_path.{target_status}",
        object_type="learning_path", object_id=path.id,
    )
    session.flush()
    return path


def record_learning_event(
    session: Any,
    *,
    owner_public_id: str,
    event: LearningEventInput,
) -> tuple[DBLearningEvent, bool]:
    payload = event.model_dump(mode="json")
    existing = session.query(DBLearningEvent).filter_by(
        owner_public_id=owner_public_id,
        idempotency_key=event.idempotency_key,
    ).first()
    if existing is not None:
        existing_payload = {
            "schema_version": existing.schema_version,
            "idempotency_key": existing.idempotency_key,
            "event_type": existing.event_type,
            "course_id": existing.course_id,
            "object_type": existing.object_type,
            "object_id": existing.object_id,
            "source": existing.source,
            "occurred_at": existing.occurred_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            "payload": existing.payload or {},
        }
        if _hash(existing_payload) != _hash(payload):
            _fail("learning_event_idempotency_conflict", "event idempotency key is bound to different data")
        return existing, False
    row = DBLearningEvent(
        owner_public_id=owner_public_id,
        course_id=event.course_id,
        event_type=event.event_type,
        schema_version=event.schema_version,
        idempotency_key=event.idempotency_key,
        source=event.source,
        trace_id=f"learn-{uuid.uuid4().hex}",
        object_type=event.object_type,
        object_id=event.object_id,
        payload=event.payload,
        occurred_at=event.occurred_at.astimezone(timezone.utc).replace(tzinfo=None),
    )
    session.add(row)
    session.flush()
    return row, True


def process_path_event(
    session: Any,
    *,
    event: DBLearningEvent,
    processor_version: str = "m5.path-events.v1",
) -> DBLearningEventConsumption:
    consumption = session.query(DBLearningEventConsumption).filter_by(
        learning_event_id=event.id,
        consumer="learning_path",
        processor_version=processor_version,
    ).first()
    if consumption is not None and consumption.status == "processed":
        return consumption
    if consumption is None:
        consumption = DBLearningEventConsumption(
            learning_event_id=event.id,
            consumer="learning_path",
            processor_version=processor_version,
            status="pending",
        )
        session.add(consumption)
        session.flush()
    elif consumption.status == "failed":
        consumption.attempt += 1
        consumption.status = "pending"
        consumption.error_code = ""
    try:
        path = session.query(DBLearningPath).filter(
            DBLearningPath.owner_public_id == event.owner_public_id,
            DBLearningPath.course_id == event.course_id,
            DBLearningPath.status == "active",
        ).order_by(DBLearningPath.created_at.desc()).first()
        node = None
        if path is not None:
            node = session.query(DBPathNode).filter_by(
                learning_path_id=path.id,
                target_object_id=event.object_id,
            ).first()
        old_status = node.status if node else None
        prerequisite_blocked = False
        if node is not None and node.prerequisites:
            completed_keys = {
                item.node_key for item in session.query(DBPathNode).filter_by(
                    learning_path_id=node.learning_path_id, status="completed",
                ).all()
            }
            prerequisite_blocked = not set(node.prerequisites).issubset(completed_keys)
        strong = event.event_type in {"code_tests_passed", "delayed_retest_passed", "teacher_confirmed"}
        contact = event.event_type in {
            "resource_opened", "reading_started", "reading_threshold", "video_started",
            "video_threshold", "video_completed", "explanation_started", "explanation_completed",
            "note_created", "quiz_answered", "code_run", "wrong_question_reviewed",
        }
        if node is not None and strong and not prerequisite_blocked:
            node.status = "completed"
        elif node is not None and contact and node.status == "pending":
            node.status = "in_progress"
        actual_minutes = event.payload.get("actual_minutes") if event.payload else None
        if node is not None and actual_minutes is not None:
            node.actual_minutes = max(0, int(actual_minutes))
        if path is not None:
            nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).all()
            if nodes and all(item.status == "completed" for item in nodes):
                path.status = "completed"
                path.completed_at = _now()
                path.lock_version += 1
        consumption.status = "processed"
        consumption.processed_at = _now()
        consumption.result = {
            "path_id": path.id if path else None,
            "node_id": node.id if node else None,
            "old_status": old_status,
            "new_status": node.status if node else None,
            "prerequisite_blocked": prerequisite_blocked,
            "mastery_changed": False,
        }
        session.flush()
        return consumption
    except Exception as exc:
        consumption.status = "failed"
        consumption.error_code = f"path_event_{type(exc).__name__.lower()}"
        consumption.result = {}
        session.flush()
        raise


def today_work_items(session: Any, *, owner_public_id: str) -> tuple[dict[str, Any], ...]:
    paths = session.query(DBLearningPath).filter_by(owner_public_id=owner_public_id, status="active").all()
    output = []
    for path in paths:
        nodes = session.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()
        completed_keys = {item.node_key for item in nodes if item.status == "completed"}
        for node in nodes:
            if node.status == "completed" or not set(node.prerequisites or []).issubset(completed_keys):
                continue
            output.append({
                "path_id": path.id,
                "course_id": path.course_id,
                "node_id": node.id,
                "node_key": node.node_key,
                "title": node.title,
                "status": node.status,
                "resource_status": node.resource_status,
                "estimate_minutes": [node.estimate_min_minutes, node.estimate_max_minutes],
            })
    return tuple(output)
