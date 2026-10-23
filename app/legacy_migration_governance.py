"""Static inventory and deletion gate for progressive legacy migration."""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import secrets
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from sqlalchemy import func

from app.database import (
    DBAuditLog,
    DBArtifact,
    DBArtifactVersion,
    DBAlignmentLog,
    DBCheckinLog,
    DBCodeExecution,
    DBConversationHistory,
    DBChapter,
    DBCourse,
    DBCourseDocument,
    DBCourseMembership,
    DBKnowledgeDocument,
    DBLegacyObjectMigration,
    DBLearningPath,
    DBNote,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBQuizRecord,
    DBQuizItem,
    DBReviewPlan,
    DBSourceDocument,
    DBSourceRef,
    DBStudentProfile,
    DBUser,
    DBWebSearchHistory,
    DBWrongQuestion,
    new_public_id,
)
from app.model_call_governance import scan_model_calls
from app.m1_repository import create_artifact_with_version


REGISTRY_VERSION = "2026-08-03.1"

CONSUMER_CHAINS: dict[str, tuple[str, ...]] = {
    "app/main.py": ("identity-profile-history",),
    "code_exec_api.py": ("activity-execution-search",),
    "flashcard_api.py": ("assessment-review-calibration",),
    "knowledge_api.py": ("knowledge-source-note",),
    "profile_api.py": ("identity-profile-history",),
    "quiz_api.py": ("assessment-review-calibration", "activity-execution-search"),
    "stream_api.py": ("knowledge-source-note",),
    "web_search_api.py": ("activity-execution-search",),
}

METHOD_CHAINS: dict[str, str] = {
    "user_by_username": "identity-profile-history", "student_profile": "identity-profile-history",
    "student_profile_ids": "identity-profile-history", "display_name": "identity-profile-history",
    "latest_alignment": "identity-profile-history", "quiz_history": "identity-profile-history",
    "personal_knowledge_documents": "identity-profile-history", "conversation_snapshot": "identity-profile-history",
    "quiz_record": "assessment-review-calibration", "available_quiz_items": "assessment-review-calibration",
    "quiz_history_desc": "assessment-review-calibration", "save_quiz_record": "assessment-review-calibration",
    "update_quiz_item_beta": "assessment-review-calibration", "create_wrong_question_if_missing": "assessment-review-calibration",
    "lower_review_priority": "assessment-review-calibration", "link_similar_quiz": "assessment-review-calibration",
    "wrong_questions": "assessment-review-calibration", "wrong_concept_stats": "assessment-review-calibration",
    "wrong_question": "assessment-review-calibration", "delete_wrong_question": "assessment-review-calibration",
    "toggle_wrong_question_pin": "assessment-review-calibration", "update_wrong_question_notes": "assessment-review-calibration",
    "mcmc_training_rows": "assessment-review-calibration", "update_calibrated_quiz_items": "assessment-review-calibration",
    "review_plan": "assessment-review-calibration", "due_review_plans": "assessment-review-calibration",
    "all_review_plans": "assessment-review-calibration", "delete_review_plan": "assessment-review-calibration",
    "knowledge_library_rows": "knowledge-source-note", "knowledge_document_context": "knowledge-source-note",
    "set_document_guide": "knowledge-source-note", "delete_knowledge_document": "knowledge-source-note",
    "knowledge_filenames": "knowledge-source-note", "upsert_generated_note": "knowledge-source-note",
    "checkins_between": "activity-execution-search", "save_checkin": "activity-execution-search",
    "commit": "activity-execution-search", "checkin_history": "activity-execution-search",
    "checkin_dates": "activity-execution-search", "code_history": "activity-execution-search",
    "web_search_history": "activity-execution-search",
}

# Deletion claims are intentionally empty until a separately generated proof passes.
DELETION_ELIGIBLE_DORMANT_KEYS: frozenset[str] = frozenset()
SENSITIVE_KEY_PARTS = ("answer", "content", "password", "prompt", "secret", "token", "api_key", "reason")
LEGACY_OBJECT_TYPES = {"profile", "path", "resource", "note", "wrong_question"}
TARGET_TYPES = {
    "profile": "profile_snapshot",
    "path": "learning_path",
    "resource": "source_document",
    "note": "artifact",
    "wrong_question": "wrong_question",
}


class LegacyMigrationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _migration_payload(row: DBLegacyObjectMigration) -> dict[str, object]:
    return {
        "id": row.id,
        "ownerPublicId": row.owner_public_id,
        "legacyStudentId": row.legacy_student_id,
        "oldType": row.old_type,
        "oldId": row.old_id,
        "targetType": row.target_type,
        "targetId": row.target_id,
        "version": row.version,
        "status": row.status,
        "error": row.error_code,
        "rollbackToken": row.rollback_token,
        "createdObjects": row.created_objects or [],
        "metadata": row.metadata_json or {},
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "verifiedAt": row.verified_at.isoformat() if row.verified_at else None,
        "rolledBackAt": row.rolled_back_at.isoformat() if row.rolled_back_at else None,
    }


def _legacy_owner(session: Any, owner_public_id: str) -> DBUser:
    user = session.query(DBUser).filter_by(public_id=owner_public_id).first()
    if user is None:
        raise LegacyMigrationError("legacy_migration_owner_unknown", "迁移所属用户不存在。")
    return user


def _source_row(session: Any, *, student_id: str, old_type: str, old_id: str) -> object:
    if old_type == "profile":
        row = (
            session.query(DBStudentProfile).filter_by(student_id=student_id).first()
            if str(old_id) == str(student_id)
            else None
        )
    elif old_type == "path":
        try:
            numeric_id = int(old_id)
        except ValueError as exc:
            raise LegacyMigrationError("legacy_migration_source_unknown", "旧路径对象不存在。") from exc
        row = session.query(DBReviewPlan).filter_by(id=numeric_id, student_id=student_id).first()
    elif old_type == "resource":
        row = session.query(DBKnowledgeDocument).filter_by(id=old_id, student_id=student_id).first()
    elif old_type == "note":
        row = session.query(DBNote).filter_by(id=old_id, student_id=student_id).first()
    elif old_type == "wrong_question":
        try:
            numeric_id = int(old_id)
        except ValueError as exc:
            raise LegacyMigrationError("legacy_migration_source_unknown", "旧错题对象不存在。") from exc
        row = session.query(DBWrongQuestion).filter_by(id=numeric_id, student_id=student_id).first()
    else:
        raise LegacyMigrationError("legacy_migration_type_unknown", "不支持的旧对象类型。")
    if row is None:
        raise LegacyMigrationError("legacy_migration_source_unknown", "旧对象不存在或不属于当前用户。")
    return row


def _personal_course(session: Any, *, owner: DBUser) -> DBCourse:
    course_id = f"personal-{owner.public_id}"
    course = session.get(DBCourse, course_id)
    if course is None:
        course = DBCourse(
            id=course_id,
            version="1",
            title="个人知识库（内部）",
            subject="personal-knowledge",
            description="旧个人学习对象迁移的规范课程边界",
            domain_pack="personal",
            language="zh-CN",
            content_origin="legacy-migration",
            license_text="user-provided",
            visibility="private",
            status="draft",
            owner_public_id=owner.public_id,
            manifest_version="personal-v1",
            manifest_data={"kind": "legacy_migration_boundary"},
        )
        session.add(course)
        session.flush()
    membership = session.query(DBCourseMembership).filter_by(
        course_id=course.id, user_public_id=owner.public_id,
    ).first()
    if membership is None:
        session.add(DBCourseMembership(
            course_id=course.id,
            user_public_id=owner.public_id,
            role="student",
            status="active",
        ))
        session.flush()
    return course


def _copy_profile(session: Any, row: DBStudentProfile, owner: DBUser) -> tuple[str, list[dict[str, str]]]:
    snapshot = {
        "targetCourse": row.target_course,
        "knowledgeBase": row.knowledge_base,
        "cognitiveStyle": row.cognitive_style,
        "motivationType": row.motivation_type,
        "weakPoints": row.weak_points or [],
        "learningGoals": row.learning_goals or [],
        "interactionPreferences": row.interaction_preferences or [],
        "conceptMastery": row.concept_mastery or {},
        "dimensionStates": row.dimension_states or {},
    }
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    target = DBProfileSnapshot(
        owner_public_id=owner.public_id,
        legacy_student_id=row.student_id,
        profile_version="legacy-migration-v1",
        snapshot=snapshot,
        content_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        trace_id=new_public_id("trace"),
    )
    session.add(target)
    session.flush()
    return target.id, [{"type": "profile_snapshot", "id": target.id}]


def _copy_path(session: Any, row: DBReviewPlan, owner: DBUser) -> tuple[str, list[dict[str, str]]]:
    course = _personal_course(session, owner=owner)
    plan = DBPlanDraft(
        owner_public_id=owner.public_id,
        course_id=course.id,
        title=f"旧复习路径：{row.concept}",
        status="confirmed",
        idempotency_key=f"legacy-path:{row.id}",
        confirmed_at=datetime.utcnow(),
    )
    session.add(plan)
    session.flush()
    content = {
        "origin": "legacy_review_plan",
        "legacyReviewPlanId": row.id,
        "nodes": [{
            "title": row.concept,
            "status": "pending",
            "intervalDays": row.interval_days,
            "nextReviewAt": row.next_review_at.isoformat() if row.next_review_at else None,
            "mastery": row.mastery,
        }],
    }
    rendered = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    version = DBPlanVersion(
        plan_draft_id=plan.id,
        version_number=1,
        content=content,
        content_hash=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        created_by_public_id=owner.public_id,
    )
    session.add(version)
    session.flush()
    plan.current_version_id = version.id
    plan.confirmed_version_id = version.id
    path = DBLearningPath(
        owner_public_id=owner.public_id,
        course_id=course.id,
        source_plan_version_id=version.id,
        status="active",
    )
    session.add(path)
    session.flush()
    node = DBPathNode(
        learning_path_id=path.id,
        node_key=f"legacy-review:{row.id}",
        sequence=1,
        node_type="review",
        target_object_id=str(row.id),
        title=row.concept,
        status="pending",
        estimate_min_minutes=5,
        estimate_max_minutes=max(5, int(row.interval_days or 1) * 5),
    )
    session.add(node)
    session.flush()
    created = [
        {"type": "path_node", "id": node.id},
        {"type": "learning_path", "id": path.id},
        {"type": "plan_version", "id": version.id},
        {"type": "plan_draft", "id": plan.id},
    ]
    return path.id, created


def _copy_resource(session: Any, row: DBKnowledgeDocument, owner: DBUser) -> tuple[str, list[dict[str, str]]]:
    course = _personal_course(session, owner=owner)
    existing = session.query(DBSourceDocument).filter_by(
        course_id=course.id, legacy_document_id=row.id,
    ).first()
    if existing is not None:
        return existing.id, []
    content = row.content or ""
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    source = DBSourceDocument(
        course_id=course.id,
        legacy_document_id=row.id,
        title=row.title or row.filename,
        filename=row.filename,
        file_format=row.file_type or "text",
        content_hash=digest,
        source_sha256=digest,
        processed_sha256=digest,
        file_size=row.file_size or len(content.encode("utf-8")),
        source_path=f"legacy://knowledge/{row.id}",
        license_text="user-provided",
        uploader_public_id=owner.public_id,
        parser_version="legacy-migration-v1",
        parser_metadata={"legacyStudentId": row.student_id, "tags": row.tags or []},
        processing_status="ready",
    )
    session.add(source)
    session.flush()
    return source.id, [{"type": "source_document", "id": source.id}]


def _copy_note(session: Any, row: DBNote, owner: DBUser) -> tuple[str, list[dict[str, str]]]:
    artifact, version = create_artifact_with_version(
        session,
        owner_public_id=owner.public_id,
        artifact_type="note",
        title=(row.content or "")[:80] or "旧笔记",
        content=row.content or "",
        content_format="markdown",
        metadata={
            "origin": "legacy_note",
            "legacyNoteId": row.id,
            "source": row.source,
            "tags": row.tags or [],
            "concepts": row.concepts or [],
        },
    )
    return artifact.id, [
        {"type": "artifact_version", "id": version.id},
        {"type": "artifact", "id": artifact.id},
    ]


def _map_wrong_question(session: Any, row: DBWrongQuestion, owner: DBUser) -> tuple[str, list[dict[str, str]]]:
    del session, owner
    return str(row.id), []


COPY_HANDLERS: dict[str, Callable[[Any, object, DBUser], tuple[str, list[dict[str, str]]]]] = {
    "profile": _copy_profile,
    "path": _copy_path,
    "resource": _copy_resource,
    "note": _copy_note,
    "wrong_question": _map_wrong_question,
}


def _verify_target(
    session: Any, *, old_type: str, target_id: str, owner: DBUser,
) -> object:
    if old_type == "profile":
        row = session.get(DBProfileSnapshot, target_id)
        owned = row is not None and row.owner_public_id == owner.public_id
    elif old_type == "path":
        row = session.get(DBLearningPath, target_id)
        owned = row is not None and row.owner_public_id == owner.public_id
    elif old_type == "resource":
        row = session.get(DBSourceDocument, target_id)
        course = session.get(DBCourse, row.course_id) if row is not None else None
        owned = row is not None and (
            row.uploader_public_id == owner.public_id
            or (course is not None and course.owner_public_id == owner.public_id)
        )
    elif old_type == "note":
        row = session.get(DBArtifact, target_id)
        owned = row is not None and row.owner_public_id == owner.public_id
    elif old_type == "wrong_question":
        try:
            numeric_id = int(target_id)
        except ValueError as exc:
            raise LegacyMigrationError(
                "legacy_migration_target_unknown", "Canonical target does not exist."
            ) from exc
        row = session.get(DBWrongQuestion, numeric_id)
        owned = row is not None and row.student_id == owner.username
    else:
        raise LegacyMigrationError(
            "legacy_migration_type_unknown", "Unsupported legacy object type."
        )
    if row is None:
        raise LegacyMigrationError(
            "legacy_migration_target_unknown", "Canonical target does not exist."
        )
    if not owned:
        raise LegacyMigrationError(
            "legacy_migration_target_forbidden", "Canonical target belongs to another user."
        )
    return row


def migrate_legacy_object(
    session: Any, *, owner_public_id: str, old_type: str, old_id: str, version: str = "1",
) -> dict[str, object]:
    old_type = old_type.strip().lower()
    if old_type not in LEGACY_OBJECT_TYPES:
        raise LegacyMigrationError("legacy_migration_type_unknown", "不支持的旧对象类型。")
    owner = _legacy_owner(session, owner_public_id)
    record = session.query(DBLegacyObjectMigration).filter_by(
        owner_public_id=owner.public_id,
        old_type=old_type,
        old_id=str(old_id),
        version=version,
    ).first()
    if record is None:
        record = DBLegacyObjectMigration(
            owner_public_id=owner.public_id,
            legacy_student_id=owner.username,
            old_type=old_type,
            old_id=str(old_id),
            target_type=TARGET_TYPES[old_type],
            version=version,
            status="pending",
            rollback_token=secrets.token_hex(24),
        )
        session.add(record)
        session.flush()
    if record.status == "verified":
        return _migration_payload(record)
    if record.status == "copied":
        try:
            _source_row(
                session, student_id=record.legacy_student_id,
                old_type=record.old_type, old_id=record.old_id,
            )
            _verify_target(
                session,
                old_type=record.old_type,
                target_id=str(record.target_id or ""),
                owner=owner,
            )
        except LegacyMigrationError as exc:
            record.status = "failed"
            record.error_code = exc.code
            session.flush()
            raise
        record.status = "verified"
        record.error_code = ""
        record.verified_at = datetime.utcnow()
        session.flush()
        return _migration_payload(record)
    if record.status == "rolled_back":
        record.status = "pending"
        record.target_id = None
        record.created_objects = []
        record.rolled_back_at = None
    record.error_code = ""
    record.verified_at = None
    try:
        source = _source_row(
            session, student_id=record.legacy_student_id,
            old_type=record.old_type, old_id=record.old_id,
        )
        record.status = "mapped"
        session.flush()
        with session.begin_nested():
            target_id, created_objects = COPY_HANDLERS[record.old_type](session, source, owner)
            record.target_id = target_id
            record.created_objects = created_objects
            record.status = "copied"
            session.flush()
            _source_row(
                session, student_id=record.legacy_student_id,
                old_type=record.old_type, old_id=record.old_id,
            )
            _verify_target(
                session, old_type=record.old_type, target_id=target_id, owner=owner,
            )
        record.status = "verified"
        record.verified_at = datetime.utcnow()
        session.flush()
        return _migration_payload(record)
    except LegacyMigrationError as exc:
        record.target_id = None
        record.created_objects = []
        record.status = "failed"
        record.error_code = exc.code
        session.flush()
        raise
    except Exception as exc:
        record.target_id = None
        record.created_objects = []
        record.status = "failed"
        record.error_code = "legacy_migration_copy_failed"
        session.flush()
        raise LegacyMigrationError("legacy_migration_copy_failed", "旧对象迁移失败，原数据保持不变。") from exc


ROLLBACK_MODELS = {
    "profile_snapshot": DBProfileSnapshot,
    "path_node": DBPathNode,
    "learning_path": DBLearningPath,
    "plan_version": DBPlanVersion,
    "plan_draft": DBPlanDraft,
    "source_document": DBSourceDocument,
    "artifact_version": DBArtifactVersion,
    "artifact": DBArtifact,
}


def _rollback_row(
    session: Any, *, object_type: str, object_id: str, owner_public_id: str,
) -> object | None:
    model = ROLLBACK_MODELS.get(object_type)
    if model is None:
        raise LegacyMigrationError(
            "legacy_migration_rollback_forbidden", "Recorded rollback object type is invalid."
        )
    row = session.get(model, object_id)
    if row is None:
        return None
    if object_type == "path_node":
        parent = session.get(DBLearningPath, row.learning_path_id)
        owned = parent is not None and parent.owner_public_id == owner_public_id
    elif object_type == "plan_version":
        parent = session.get(DBPlanDraft, row.plan_draft_id)
        owned = parent is not None and parent.owner_public_id == owner_public_id
    elif object_type == "artifact_version":
        parent = session.get(DBArtifact, row.artifact_id)
        owned = parent is not None and parent.owner_public_id == owner_public_id
    elif object_type == "source_document":
        course = session.get(DBCourse, row.course_id)
        owned = row.uploader_public_id == owner_public_id or (
            course is not None and course.owner_public_id == owner_public_id
        )
    else:
        owned = getattr(row, "owner_public_id", None) == owner_public_id
    if not owned:
        raise LegacyMigrationError(
            "legacy_migration_rollback_forbidden",
            "Recorded canonical object belongs to another user.",
        )
    return row


def rollback_legacy_object(
    session: Any, *, owner_public_id: str, migration_id: str, rollback_token: str,
) -> dict[str, object]:
    record = session.query(DBLegacyObjectMigration).filter_by(
        id=migration_id, owner_public_id=owner_public_id,
    ).first()
    if record is None:
        raise LegacyMigrationError("legacy_migration_unknown", "迁移记录不存在。")
    if not secrets.compare_digest(record.rollback_token, rollback_token):
        raise LegacyMigrationError("legacy_migration_rollback_forbidden", "回滚令牌无效。")
    if record.status == "rolled_back":
        return _migration_payload(record)
    with session.begin_nested():
        for item in record.created_objects or []:
            row = _rollback_row(
                session,
                object_type=str(item.get("type")),
                object_id=str(item.get("id")),
                owner_public_id=owner_public_id,
            )
            if row is not None:
                session.delete(row)
                session.flush()
        record.status = "rolled_back"
        record.rolled_back_at = datetime.utcnow()
        record.error_code = ""
        session.flush()
    return _migration_payload(record)


def legacy_object_migrations(session: Any, *, owner_public_id: str) -> list[dict[str, object]]:
    rows = session.query(DBLegacyObjectMigration).filter_by(
        owner_public_id=owner_public_id,
    ).order_by(DBLegacyObjectMigration.created_at, DBLegacyObjectMigration.id).all()
    return [_migration_payload(row) for row in rows]


@dataclass(frozen=True)
class LegacyConsumer:
    path: str
    function: str
    line: int
    chains: tuple[str, ...]

    def payload(self) -> dict[str, object]:
        return {"path": self.path, "function": self.function, "line": self.line, "chains": list(self.chains)}


def _source_files(root: Path) -> Iterable[Path]:
    yield from sorted(root.glob("*.py"))
    yield from sorted((root / "app").rglob("*.py"))


def _function_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return "<module>"


def scan_legacy_consumers(root: Path) -> list[LegacyConsumer]:
    consumers: list[LegacyConsumer] = []
    for path in _source_files(root):
        relative = path.relative_to(root).as_posix()
        if relative == "app/legacy_repositories.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "LegacyReadRepository":
                continue
            consumers.append(LegacyConsumer(
                path=relative, function=_function_name(node, parents), line=node.lineno,
                chains=CONSUMER_CHAINS.get(relative, ()),
            ))
    return sorted(consumers, key=lambda item: (item.path, item.line))


def repository_methods(root: Path) -> list[str]:
    path = root / "app" / "legacy_repositories.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.as_posix())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "LegacyReadRepository":
            return sorted(
                item.name for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not item.name.startswith("_")
            )
    return []


def legacy_governance_summary(root: Path) -> dict[str, object]:
    consumers = scan_legacy_consumers(root)
    methods = repository_methods(root)
    dormant = [item for item in scan_model_calls(root) if item.classification == "dormant_legacy"]
    unregistered_consumers = [item.payload() for item in consumers if not item.chains]
    unregistered_methods = sorted(set(methods) - set(METHOD_CHAINS))
    stale_method_policies = sorted(set(METHOD_CHAINS) - set(methods))
    dormant_keys = {item.key for item in dormant}
    invalid_deletion_claims = sorted(DELETION_ELIGIBLE_DORMANT_KEYS - dormant_keys)
    return {
        "schema_version": "next.legacy-migration-governance.v1",
        "registry_version": REGISTRY_VERSION,
        "consumer_count": len(consumers),
        "consumer_file_count": len({item.path for item in consumers}),
        "repository_method_count": len(methods),
        "dormant_model_call_count": len(dormant),
        "chain_counts": dict(sorted(Counter(chain for item in consumers for chain in item.chains).items())),
        "unregistered_consumer_count": len(unregistered_consumers),
        "unregistered_method_count": len(unregistered_methods),
        "stale_method_policy_count": len(stale_method_policies),
        "invalid_deletion_claim_count": len(invalid_deletion_claims),
        "unregistered_consumers": unregistered_consumers,
        "unregistered_methods": unregistered_methods,
        "stale_method_policies": stale_method_policies,
        "invalid_deletion_claims": invalid_deletion_claims,
        "deletion_eligible_dormant_keys": sorted(DELETION_ELIGIBLE_DORMANT_KEYS),
        "consumers": [item.payload() for item in consumers],
        "repository_methods": methods,
        "dormant_model_calls": [item.payload() for item in dormant],
    }


def _stable_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _stable_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple, set)):
        items = [_stable_value(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
    if hasattr(value, "id"):
        return {"type": value.__class__.__name__, "id": str(getattr(value, "id", ""))}
    return {"type": value.__class__.__name__}


def _fingerprint(value: object) -> str:
    rendered = json.dumps(_stable_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def compare_migration_results(chain_id: str, legacy_result: object, canonical_result: object) -> dict[str, object]:
    legacy_hash = _fingerprint(legacy_result)
    canonical_hash = _fingerprint(canonical_result)
    return {
        "schema_version": "next.legacy-shadow-comparison.v1",
        "chain_id": chain_id,
        "status": "matched" if legacy_hash == canonical_hash else "mismatched",
        "legacy_hash": legacy_hash,
        "canonical_hash": canonical_hash,
        "legacy_type": type(legacy_result).__name__,
        "canonical_type": type(canonical_result).__name__,
        "legacy_count": len(legacy_result) if isinstance(legacy_result, (dict, list, tuple, set)) else None,
        "canonical_count": len(canonical_result) if isinstance(canonical_result, (dict, list, tuple, set)) else None,
    }


def _result_count(value: object) -> int | None:
    return len(value) if isinstance(value, (dict, list, tuple, set)) else None


def _target_error_comparison(chain_id: str, legacy_result: object) -> dict[str, object]:
    return {
        "schema_version": "next.legacy-shadow-comparison.v1",
        "chain_id": chain_id,
        "status": "target_error",
        "legacy_hash": _fingerprint(legacy_result),
        "canonical_hash": "",
        "legacy_type": type(legacy_result).__name__,
        "canonical_type": "unavailable",
        "legacy_count": _result_count(legacy_result),
        "canonical_count": None,
    }


def _error_code(exc: Exception) -> str:
    name = exc.__class__.__name__
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in name).strip("_")
    return f"canonical_target_{normalized or 'error'}"[:64]


class ActivityExecutionSearchCanonicalReader:
    """Independent target reader for the first low-risk migration chain."""

    def __init__(self, session: object):
        self.session = session

    def checkin_history(self, student_id: str) -> list[dict[str, object]]:
        rows = self.session.query(
            DBCheckinLog.id,
            DBCheckinLog.checkin_date,
            DBCheckinLog.duration_minutes,
            DBCheckinLog.concepts_reviewed,
        ).filter_by(student_id=student_id).order_by(DBCheckinLog.checkin_date.asc()).all()
        return [
            {
                "id": row.id,
                "checkin_date": row.checkin_date,
                "duration_minutes": row.duration_minutes,
                "concepts_reviewed": row.concepts_reviewed or [],
            }
            for row in rows
        ]

    def checkin_dates(self, student_id: str) -> list[datetime]:
        rows = self.session.query(DBCheckinLog.checkin_date).filter_by(
            student_id=student_id
        ).order_by(DBCheckinLog.checkin_date.desc()).all()
        return [row[0] for row in rows if row[0]]

    def code_history(self, student_id: str, *, limit: int) -> list[dict[str, object]]:
        rows = self.session.query(
            DBCodeExecution.id,
            DBCodeExecution.code,
            DBCodeExecution.language,
            DBCodeExecution.output,
            DBCodeExecution.error,
            DBCodeExecution.execution_time_ms,
            DBCodeExecution.created_at,
        ).filter_by(student_id=student_id).order_by(
            DBCodeExecution.created_at.desc()
        ).limit(limit).all()
        return [dict(row._mapping) for row in rows]

    def web_search_history(self, student_id: str, *, limit: int) -> list[dict[str, object]]:
        rows = self.session.query(
            DBWebSearchHistory.id,
            DBWebSearchHistory.query,
            DBWebSearchHistory.source_type,
            DBWebSearchHistory.source_url,
            DBWebSearchHistory.title,
            DBWebSearchHistory.content_preview,
            DBWebSearchHistory.chunk_count,
            DBWebSearchHistory.created_at,
        ).filter_by(student_id=student_id).order_by(
            DBWebSearchHistory.created_at.desc()
        ).limit(limit).all()
        return [dict(row._mapping) for row in rows]


def project_model_row(row: object | None) -> dict[str, object] | None:
    if row is None:
        return None
    table = getattr(row, "__table__", None)
    if table is None:
        raise TypeError("legacy row has no SQLAlchemy table metadata")
    return {column.key: getattr(row, column.key) for column in table.columns}


def project_model_rows(rows: Iterable[object]) -> list[dict[str, object]]:
    return [project_model_row(row) or {} for row in rows]


class IdentityProfileHistoryCanonicalReader:
    """Column-level target reader for identity, profile, and history facts."""

    def __init__(self, session: object):
        self.session = session

    def _one(self, model, *, filters: dict[str, object], order_by=None):
        columns = list(model.__table__.columns)
        query = self.session.query(*columns).filter(
            *(getattr(model, key) == value for key, value in filters.items())
        )
        if order_by is not None:
            query = query.order_by(order_by)
        row = query.first()
        return dict(row._mapping) if row is not None else None

    def _many(self, model, *, filters: dict[str, object], order_by=None):
        columns = list(model.__table__.columns)
        query = self.session.query(*columns).filter(
            *(getattr(model, key) == value for key, value in filters.items())
        )
        if order_by is not None:
            query = query.order_by(order_by)
        return [dict(row._mapping) for row in query.all()]

    def user_by_username(self, username: str):
        return self._one(DBUser, filters={"username": username})

    def student_profile(self, student_id: str):
        return self._one(DBStudentProfile, filters={"student_id": student_id})

    def student_profile_ids(self) -> list[str]:
        rows = self.session.query(DBStudentProfile.student_id).order_by(
            DBStudentProfile.student_id
        ).all()
        return [row[0] for row in rows]

    def display_name(self, username: str) -> str:
        row = self.session.query(DBUser.display_name).filter_by(username=username).first()
        return row[0] if row and row[0] else username

    def latest_alignment(self, student_id: str):
        return self._one(
            DBAlignmentLog,
            filters={"student_id": student_id},
            order_by=DBAlignmentLog.timestamp.desc(),
        )

    def quiz_history(self, student_id: str):
        return self._many(
            DBQuizRecord,
            filters={"student_id": student_id},
            order_by=DBQuizRecord.created_at.asc(),
        )

    def personal_knowledge_documents(self, student_id: str):
        return self._many(DBKnowledgeDocument, filters={"student_id": student_id})

    def conversation_snapshot(self, student_id: str, conversation_id: int | str):
        return self._one(
            DBConversationHistory,
            filters={"student_id": student_id, "id": conversation_id},
        )


def project_model_tree(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str, date, datetime)):
        return value
    if isinstance(value, (list, tuple)):
        return [project_model_tree(item) for item in value]
    if getattr(value, "__table__", None) is not None:
        return project_model_row(value)
    return value


class KnowledgeSourceNoteCanonicalReader:
    """Independent target reader and post-write verifier for legacy knowledge facts."""

    def __init__(self, session: object):
        self.session = session

    def knowledge_library_rows(self, student_id: str):
        legacy = self.session.query(DBKnowledgeDocument).filter(
            DBKnowledgeDocument.student_id.in_([student_id, "public", "system"])
        ).order_by(DBKnowledgeDocument.created_at.desc()).all()
        course_query = self.session.query(
            DBCourseDocument, DBCourse, DBSourceDocument, DBSourceRef, DBChapter
        ).join(DBCourse, DBCourse.id == DBCourseDocument.course_id).outerjoin(
            DBSourceDocument,
            (DBSourceDocument.course_id == DBCourseDocument.course_id)
            & (DBSourceDocument.legacy_document_id == DBCourseDocument.id),
        ).outerjoin(
            DBSourceRef, DBSourceRef.source_document_id == DBSourceDocument.id
        ).outerjoin(
            DBChapter, DBChapter.id == DBSourceRef.chapter_id
        ).filter(
            DBCourse.status == "published", DBCourseDocument.status == "published",
            DBCourse.visibility == "public",
        )
        course = course_query.order_by(DBCourse.title, DBCourseDocument.chapter_order).all()
        return project_model_tree((legacy, course))

    def knowledge_document_context(self, doc_id: str, student_id: str):
        legacy = self.session.query(DBKnowledgeDocument).filter(
            DBKnowledgeDocument.id == doc_id,
            DBKnowledgeDocument.student_id.in_([student_id, "public", "system"]),
        ).first()
        if legacy:
            return project_model_tree(("legacy", legacy, None))
        course = self.session.query(
            DBCourseDocument, DBCourse, DBSourceDocument, DBSourceRef, DBChapter
        ).join(DBCourse, DBCourse.id == DBCourseDocument.course_id).outerjoin(
            DBSourceDocument,
            (DBSourceDocument.course_id == DBCourseDocument.course_id)
            & (DBSourceDocument.legacy_document_id == DBCourseDocument.id),
        ).outerjoin(
            DBSourceRef, DBSourceRef.source_document_id == DBSourceDocument.id
        ).outerjoin(
            DBChapter, DBChapter.id == DBSourceRef.chapter_id
        ).filter(
            DBCourseDocument.id == doc_id, DBCourseDocument.status == "published",
            DBCourse.status == "published", DBCourse.visibility == "public",
        ).first()
        return project_model_tree(("course", *course)) if course else None

    def knowledge_filenames(self, document_ids: list[str] | None = None) -> list[str]:
        query = self.session.query(DBKnowledgeDocument.filename)
        if document_ids is not None:
            query = query.filter(DBKnowledgeDocument.id.in_(document_ids))
        return [row[0] for row in query.all() if row[0]]

    def document_poststate(self, doc_id: str, student_id: str):
        columns = list(DBKnowledgeDocument.__table__.columns)
        row = self.session.query(*columns).filter_by(
            id=doc_id, student_id=student_id
        ).first()
        return dict(row._mapping) if row is not None else None

    def note_poststate(self, note_id: str, student_id: str):
        columns = list(DBNote.__table__.columns)
        row = self.session.query(*columns).filter_by(id=note_id, student_id=student_id).first()
        return dict(row._mapping) if row is not None else None

    def deletion_poststate(self, doc_id: str):
        document = self.session.query(DBKnowledgeDocument.id).filter_by(id=doc_id).first()
        source = self.session.query(DBSourceDocument.id).filter_by(legacy_document_id=doc_id).first()
        return {"document_exists": document is not None, "source_exists": source is not None}


class AssessmentReviewCalibrationCanonicalReader:
    """Independent target reads and post-write state checks for assessment facts."""

    def __init__(self, session: object):
        self.session = session

    def _one(self, model, filters: dict[str, object]):
        columns = list(model.__table__.columns)
        row = self.session.query(*columns).filter(
            *(getattr(model, key) == value for key, value in filters.items())
        ).first()
        return dict(row._mapping) if row is not None else None

    def _many(self, model, filters: dict[str, object], order_by=None, limit: int | None = None):
        columns = list(model.__table__.columns)
        query = self.session.query(*columns).filter(
            *(getattr(model, key) == value for key, value in filters.items())
        )
        if order_by is not None:
            query = query.order_by(*order_by) if isinstance(order_by, tuple) else query.order_by(order_by)
        if limit is not None:
            query = query.limit(limit)
        return [dict(row._mapping) for row in query.all()]

    def quiz_record(self, quiz_id: str, student_id: str | None = None):
        filters = {"id": quiz_id}
        if student_id is not None:
            filters["student_id"] = student_id
        return self._one(DBQuizRecord, filters)

    def available_quiz_items(self, concept: str, student_id: str):
        candidates = self.session.query(DBQuizItem).filter_by(concept=concept).all()
        answered = self.session.query(DBQuizRecord.question).filter(
            DBQuizRecord.student_id == student_id, DBQuizRecord.student_answer != "",
        ).all()
        answered_texts = {row[0].strip() for row in answered if row[0]}
        return project_model_rows(
            item for item in candidates if item.question.strip() not in answered_texts
        )

    def quiz_history_desc(self, student_id: str, limit: int):
        return self._many(
            DBQuizRecord, {"student_id": student_id}, DBQuizRecord.created_at.desc(), limit,
        )

    def quiz_items(self, item_ids: list[str]):
        columns = list(DBQuizItem.__table__.columns)
        rows = self.session.query(*columns).filter(
            DBQuizItem.id.in_(item_ids)
        ).order_by(DBQuizItem.id).all()
        return [dict(row._mapping) for row in rows]

    def wrong_questions(self, student_id: str, concept: str, limit: int):
        query = self.session.query(DBWrongQuestion).filter_by(student_id=student_id)
        if concept:
            query = query.filter_by(concept_name=concept)
        records = query.order_by(
            DBWrongQuestion.pinned.desc(), DBWrongQuestion.created_at.desc()
        ).limit(limit).all()
        result = []
        for record in records:
            quiz = self.session.query(DBQuizRecord).filter_by(id=record.quiz_record_id).first()
            result.append((record, quiz))
        return project_model_tree(result)

    def wrong_concept_stats(self, student_id: str):
        rows = self.session.query(
            DBWrongQuestion.concept_name, func.count(DBWrongQuestion.id),
        ).filter_by(student_id=student_id).group_by(
            DBWrongQuestion.concept_name
        ).order_by(func.count(DBWrongQuestion.id).desc()).all()
        return [list(row) for row in rows]

    def wrong_question(self, wrong_id: int, student_id: str):
        return self._one(DBWrongQuestion, {"id": wrong_id, "student_id": student_id})

    def wrong_question_by_quiz(self, student_id: str, quiz_record_id: str, concept: str):
        return self._one(DBWrongQuestion, {
            "student_id": student_id,
            "quiz_record_id": quiz_record_id,
            "concept_name": concept,
        })

    def checkins_between(self, student_id: str, start: datetime, end: datetime):
        rows = self.session.query(DBCheckinLog).filter(
            DBCheckinLog.student_id == student_id,
            DBCheckinLog.checkin_date >= start,
            DBCheckinLog.checkin_date <= end,
        ).all()
        return project_model_rows(rows)

    def mcmc_training_rows(self):
        students = self.session.query(DBStudentProfile).filter(
            DBStudentProfile.rl_q_table.isnot(None)
        ).all()
        items = self.session.query(DBQuizItem).all()
        student_ids = [student.student_id for student in students]
        records = self.session.query(DBQuizRecord).filter(
            DBQuizRecord.student_id.in_(student_ids)
        ).all() if student_ids else []
        return project_model_tree((students, items, records))

    def review_plan(self, student_id: str, concept: str):
        return self._one(DBReviewPlan, {"student_id": student_id, "concept": concept})

    def due_review_plans(self, student_id: str, now: datetime, limit: int):
        rows = self.session.query(DBReviewPlan).filter(
            DBReviewPlan.student_id == student_id,
            (DBReviewPlan.next_review_at.is_(None)) | (DBReviewPlan.next_review_at <= now),
        ).order_by(DBReviewPlan.next_review_at.asc()).limit(limit).all()
        return project_model_rows(rows)

    def all_review_plans(self, student_id: str):
        return self._many(DBReviewPlan, {"student_id": student_id})

    def model_poststate(self, model, filters: dict[str, object]):
        return self._one(model, filters)

def project_checkin_rows(rows: Iterable[DBCheckinLog]) -> list[dict[str, object]]:
    return [
        {
            "id": row.id,
            "checkin_date": row.checkin_date,
            "duration_minutes": row.duration_minutes,
            "concepts_reviewed": row.concepts_reviewed or [],
        }
        for row in rows
    ]


def project_code_rows(rows: Iterable[DBCodeExecution]) -> list[dict[str, object]]:
    return [
        {
            "id": row.id,
            "code": row.code,
            "language": row.language,
            "output": row.output,
            "error": row.error,
            "execution_time_ms": row.execution_time_ms,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def project_web_search_rows(rows: Iterable[DBWebSearchHistory]) -> list[dict[str, object]]:
    return [
        {
            "id": row.id,
            "query": row.query,
            "source_type": row.source_type,
            "source_url": row.source_url,
            "title": row.title,
            "content_preview": row.content_preview,
            "chunk_count": row.chunk_count,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def observe_legacy_shadow_read(
    session: object,
    *,
    chain_id: str,
    legacy_result: object,
    canonical_loader,
    legacy_projector=lambda value: value,
    actor_public_id: str | None = None,
    trace_id: str | None = None,
    mode: str = "shadow_read",
) -> dict[str, object]:
    """Compare an independent target read while leaving the legacy response untouched."""
    projected_legacy = legacy_projector(legacy_result)
    savepoint = session.begin_nested()
    try:
        canonical_result = canonical_loader()
        savepoint.commit()
        comparison = compare_migration_results(chain_id, projected_legacy, canonical_result)
        error_code = ""
        fallback_used = comparison["status"] != "matched"
    except Exception as exc:
        if savepoint.is_active:
            savepoint.rollback()
        comparison = _target_error_comparison(chain_id, projected_legacy)
        error_code = _error_code(exc)
        fallback_used = True
    record_migration_observation(
        session,
        chain_id=chain_id,
        mode=mode,
        comparison=comparison,
        actor_public_id=actor_public_id,
        trace_id=trace_id,
        error_code=error_code,
        fallback_used=fallback_used,
    )
    original_expire = getattr(session, "expire_on_commit", None)
    if original_expire is not None:
        session.expire_on_commit = False
    try:
        session.commit()
    finally:
        if original_expire is not None:
            session.expire_on_commit = original_expire
    return comparison


def record_migration_observation(
    session: object, *, chain_id: str, mode: str, comparison: dict[str, object],
    actor_public_id: str | None = None, trace_id: str | None = None,
    error_code: str = "", fallback_used: bool = False,
) -> DBAuditLog:
    allowed = {
        key: comparison.get(key) for key in (
            "schema_version", "status", "legacy_hash", "canonical_hash",
            "legacy_type", "canonical_type", "legacy_count", "canonical_count",
        )
    }
    metadata = {
        "chain_id": chain_id, "mode": mode, "fallback_used": bool(fallback_used),
        "error_code": str(error_code)[:64], **allowed,
    }
    rendered_keys = " ".join(metadata).lower()
    assert not any(part in rendered_keys for part in SENSITIVE_KEY_PARTS)
    row = DBAuditLog(
        actor_public_id=actor_public_id, action="legacy_migration_observation",
        object_type="legacy_migration_chain", object_id=chain_id,
        trace_id=trace_id or new_public_id("trace"),
        outcome="success" if comparison.get("status") == "matched" and not error_code else "failed",
        metadata_json=metadata,
    )
    session.add(row)
    session.flush()
    return row


def migration_runtime_summary(session: object, limit: int = 200) -> dict[str, object]:
    rows = session.query(DBAuditLog).filter_by(action="legacy_migration_observation").order_by(
        DBAuditLog.created_at.desc(), DBAuditLog.id.desc()
    ).limit(limit).all()
    by_chain: dict[str, Counter[str]] = {}
    for row in rows:
        metadata = row.metadata_json or {}
        chain_id = str(metadata.get("chain_id") or row.object_id)
        counter = by_chain.setdefault(chain_id, Counter())
        counter[str(metadata.get("status") or "unknown")] += 1
        if metadata.get("fallback_used"):
            counter["fallback"] += 1
    return {
        "schema_version": "next.legacy-migration-runtime.v1",
        "observation_count": len(rows),
        "raw_content_persisted": False,
        "chains": {key: dict(sorted(value.items())) for key, value in sorted(by_chain.items())},
    }
