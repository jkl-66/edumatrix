"""Compatibility projections from pre-M1 records.

The adapter keeps legacy rows readable and gives the current profile snapshot
protocol one explicit, versioned projection for old learner accounts.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any
import uuid

from app.database import (
    DBConversationHistory,
    DBKnowledgeDocument,
    DBNote,
    DBProfileSnapshot,
    DBReviewPlan,
    DBStudentProfile,
    DBUser,
    DBWrongQuestion,
)


PROFILE_MAPPING_VERSION = "legacy-profile-map.v1"
LEGACY_PROFILE_FIELD_MAP: dict[str, dict[str, str]] = {
    "major": {"canonical": "profile_projection.major", "algorithm": "legacy-profile-fields.v1"},
    "target_course": {"canonical": "profile_projection.target_course", "algorithm": "legacy-profile-fields.v1"},
    "knowledge_base": {"canonical": "profile_projection.knowledge_base", "algorithm": "legacy-profile-fields.v1"},
    "cognitive_style": {"canonical": "profile_projection.cognitive_style", "algorithm": "legacy-profile-fields.v1"},
    "motivation_type": {"canonical": "profile_projection.motivation_type", "algorithm": "legacy-profile-fields.v1"},
    "focus_level": {"canonical": "profile_projection.focus_level", "algorithm": "legacy-profile-fields.v1"},
    "cognitive_load": {"canonical": "profile_projection.cognitive_load", "algorithm": "legacy-profile-fields.v1"},
    "frustration_index": {"canonical": "profile_projection.frustration_index", "algorithm": "legacy-profile-fields.v1"},
    "weak_points": {"canonical": "profile_projection.weak_points", "algorithm": "legacy-weak-point.v1"},
    "learning_goals": {"canonical": "profile_projection.learning_goals", "algorithm": "legacy-profile-fields.v1"},
    "interaction_preferences": {"canonical": "profile_projection.interaction_preferences", "algorithm": "legacy-profile-fields.v1"},
    "concept_mastery": {"canonical": "profile_projection.concept_mastery", "algorithm": "legacy-mastery.v1"},
    "misconception_patterns": {"canonical": "profile_projection.misconception_patterns", "algorithm": "legacy-misconception.v1"},
    "dimension_states": {"canonical": "dimension_states", "algorithm": "legacy-ten-dimension.v1"},
    "learning_state_causes": {"canonical": "learning_state_causes", "algorithm": "legacy-cause-attribution.v1"},
    "knowledge_traces": {"canonical": "profile_projection.knowledge_traces", "algorithm": "legacy-knowledge-trace.v1"},
    "bkt_states": {"canonical": "profile_projection.bkt_states", "algorithm": "legacy-bkt.v1"},
    "dkt_bias": {"canonical": "profile_projection.dkt_bias", "algorithm": "legacy-dkt.v1"},
    "mental_state_history": {"canonical": "profile_projection.mental_state_history", "algorithm": "legacy-mental-history.v1"},
    "concept_layers": {"canonical": "profile_projection.concept_layers", "algorithm": "legacy-concept-layer.v1"},
    "cognitive_map": {"canonical": "profile_projection.cognitive_map", "algorithm": "legacy-cognitive-map.v1"},
    "fsm_mode": {"canonical": "profile_projection.fsm_mode", "algorithm": "legacy-fsm.v1"},
    "fsm_accuracy_history": {"canonical": "profile_projection.fsm_accuracy_history", "algorithm": "legacy-fsm.v1"},
    "rl_q_table": {"canonical": "profile_projection.rl_q_table", "algorithm": "legacy-rl.v1"},
    "history_logs": {"canonical": "profile_projection.history_logs", "algorithm": "legacy-history.v1"},
    "narrative_report": {"canonical": "profile_projection.narrative_report", "algorithm": "legacy-report-cache.v1"},
    "dashboard_report": {"canonical": "profile_projection.dashboard_report", "algorithm": "legacy-report-cache.v1"},
}

_INFLUENCE_BY_FIELD: dict[str, tuple[str, ...]] = {
    "weak_points": ("学习路径", "今日任务", "智能组卷", "讲义", "测验题"),
    "concept_mastery": ("学习路径", "今日任务", "智能组卷", "讲义", "测验题"),
    "knowledge_traces": ("学习路径", "今日任务", "智能组卷", "讲义", "测验题"),
    "bkt_states": ("学习路径", "今日任务", "智能组卷", "测验题"),
    "dimension_states": ("学习路径", "今日任务", "智能组卷", "讲义", "测验题"),
    "learning_state_causes": ("学习路径", "今日任务", "讲义", "测验题"),
    "cognitive_load": ("今日任务", "讲义", "测验题"),
    "frustration_index": ("今日任务", "讲义", "测验题"),
    "motivation_type": ("学习路径", "今日任务", "讲义"),
    "learning_goals": ("学习路径", "讲义", "测验题"),
    "cognitive_style": ("讲义", "测验题"),
    "interaction_preferences": ("讲义", "测验题"),
}


class LegacyProfileMigrationError(ValueError):
    """A migration request cannot be projected without changing legacy data."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _snapshot_course_id(row: DBProfileSnapshot) -> str | None:
    body = row.snapshot or {}
    return str(body.get("course_id") or (body.get("course_context") or {}).get("courseId") or "") or None


def _projection_from_snapshot(row: DBProfileSnapshot | None) -> dict[str, Any]:
    if row is None:
        return {}
    body = row.snapshot or {}
    projection = body.get("profile_projection")
    if isinstance(projection, dict):
        return dict(projection)
    return {
        key: body[key]
        for key in LEGACY_PROFILE_FIELD_MAP
        if key in body
    }


def _confirmed_profile_fields(rows: list[DBProfileSnapshot], profile: DBStudentProfile) -> set[str]:
    """Collect fields that a learner-confirmed canonical snapshot owns."""
    confirmed = {str(item) for item in (profile.customized_fields or []) if str(item)}
    for row in rows:
        body = row.snapshot or {}
        if body.get("kind") == "legacy_profile_migration":
            continue
        projection = body.get("profile_projection") or {}
        confirmed.update(str(key) for key in projection if str(key) in LEGACY_PROFILE_FIELD_MAP)
        for item in body.get("initial_fields") or []:
            if isinstance(item, dict) and item.get("key") in LEGACY_PROFILE_FIELD_MAP:
                confirmed.add(str(item["key"]))
        for item in (body.get("self_report") or {}).values():
            if not isinstance(item, dict):
                continue
            confirmed.update(str(key) for key in (item.get("values") or {}) if str(key) in LEGACY_PROFILE_FIELD_MAP)
    return confirmed


def _legacy_profile_values(profile: DBStudentProfile) -> dict[str, Any]:
    return {
        key: deepcopy(getattr(profile, key, None))
        for key in LEGACY_PROFILE_FIELD_MAP
    }


def _migration_influence(diff: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in diff:
        field = item["legacy_field"]
        targets = _INFLUENCE_BY_FIELD.get(field)
        if not targets or item["status"] in {"legacy_empty", "canonical_only"}:
            continue
        result.append({
            "field": field,
            "fieldLabel": item["field_label"],
            "status": item["status"],
            "algorithmVersion": item["algorithm_version"],
            "usedBy": list(targets),
            "reason": f"{item['field_label']}以 {item['algorithm_version']} 的迁移证据进入当前画像；下游按同一画像版本调整内容。",
        })
    return result


class LegacyDataAdapter:
    def __init__(self, session: Any):
        self.session = session

    def _owner_and_profile(self, owner_public_id: str) -> tuple[DBUser, DBStudentProfile]:
        owner = self.session.query(DBUser).filter_by(public_id=owner_public_id).first()
        if owner is None:
            raise LegacyProfileMigrationError("profile_owner_not_found", "画像所属用户不存在。")
        profile = self.session.query(DBStudentProfile).filter_by(student_id=owner.username).first()
        if profile is None:
            raise LegacyProfileMigrationError("legacy_profile_not_found", "没有可回放的旧画像记录。")
        return owner, profile

    def profile_projection(self, student_id: str) -> dict[str, Any]:
        """Return a complete, read-only field map from the old profile row."""
        profile = self.session.query(DBStudentProfile).filter_by(student_id=student_id).first()
        if profile is None:
            raise LegacyProfileMigrationError("legacy_profile_not_found", "没有可回放的旧画像记录。")
        values = _legacy_profile_values(profile)
        return {
            "mapping_version": PROFILE_MAPPING_VERSION,
            "source": {
                "student_id": profile.student_id,
                "object_type": "DBStudentProfile",
                "algorithm_versions": {
                    key: meta["algorithm"] for key, meta in LEGACY_PROFILE_FIELD_MAP.items()
                },
            },
            "profile_projection": values,
            "dimension_states": deepcopy(values.get("dimension_states") or {}),
            "learning_state_causes": deepcopy(values.get("learning_state_causes") or {}),
            "legacy_fields": [
                {
                    "legacy_field": key,
                    "canonical_path": meta["canonical"],
                    "algorithm_version": meta["algorithm"],
                    "present": _has_value(values.get(key)),
                }
                for key, meta in LEGACY_PROFILE_FIELD_MAP.items()
            ],
        }

    def profile_migration_report(
        self, owner_public_id: str, *, course_id: str | None = None,
    ) -> dict[str, Any]:
        """Build migration and influence evidence without writing any row."""
        owner, profile = self._owner_and_profile(owner_public_id)
        rows = self.session.query(DBProfileSnapshot).filter_by(
            owner_public_id=owner.public_id,
        ).order_by(DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc()).all()
        visible_rows = [
            row for row in rows
            if not course_id or _snapshot_course_id(row) in {None, course_id}
        ]
        canonical_rows = [
            row for row in rows
            if (row.snapshot or {}).get("kind") != "legacy_profile_migration"
            and (not course_id or _snapshot_course_id(row) in {None, course_id})
        ]
        migration_rows = [row for row in rows if (row.snapshot or {}).get("kind") == "legacy_profile_migration"]
        current = canonical_rows[0] if canonical_rows else None
        visible_current = visible_rows[0] if visible_rows else None
        canonical = _projection_from_snapshot(current)
        confirmed = _confirmed_profile_fields(canonical_rows, profile)
        legacy = _legacy_profile_values(profile)
        diff: list[dict[str, Any]] = []
        for key, meta in LEGACY_PROFILE_FIELD_MAP.items():
            legacy_value = deepcopy(legacy.get(key))
            canonical_value = deepcopy(canonical.get(key))
            if not _has_value(legacy_value):
                status = "legacy_empty" if not _has_value(canonical_value) else "canonical_only"
            elif key in confirmed and _has_value(canonical_value) and canonical_value != legacy_value:
                status = "preserved_confirmed"
            elif _has_value(canonical_value) and canonical_value == legacy_value:
                status = "unchanged"
            elif _has_value(canonical_value):
                status = "conflict"
            else:
                status = "imported"
            diff.append({
                "legacy_field": key,
                "field_label": key,
                "canonical_path": meta["canonical"],
                "algorithm_version": meta["algorithm"],
                "legacy_value": legacy_value,
                "canonical_value": canonical_value,
                "status": status,
                "confirmed_value_wins": status == "preserved_confirmed",
            })

        effective = {
            key: deepcopy(canonical.get(key)) if key in confirmed and _has_value(canonical.get(key))
            else deepcopy(legacy.get(key)) if _has_value(legacy.get(key))
            else deepcopy(canonical.get(key))
            for key in LEGACY_PROFILE_FIELD_MAP
        }
        relevant = [item for item in diff if item["status"] not in {"legacy_empty", "canonical_only"}]
        status = "verified" if current and not any(item["status"] in {"conflict", "imported"} for item in relevant) else (
            "conflict" if any(item["status"] == "conflict" for item in relevant) else "mapped"
        )
        latest_migration = migration_rows[0] if migration_rows else None
        return {
            "schema_version": "profile.legacy-migration-report.v1",
            "status": status,
            "mapping_version": PROFILE_MAPPING_VERSION,
            "owner_public_id": owner.public_id,
            "legacy_student_id": profile.student_id,
            "course_id": course_id,
            "source_profile": {
                "object_type": "DBStudentProfile",
                "student_id": profile.student_id,
                "last_updated": profile.last_updated.isoformat() if profile.last_updated else None,
            },
            "canonical_snapshot": {
                "id": visible_current.id if visible_current else None,
                "version": visible_current.profile_version if visible_current else None,
                "kind": (visible_current.snapshot or {}).get("kind") if visible_current else None,
            },
            "latest_migration": {
                "id": latest_migration.id if latest_migration else None,
                "version": latest_migration.profile_version if latest_migration else None,
            },
            "confirmed_fields": sorted(confirmed),
            "diff": diff,
            "influence": _migration_influence(diff),
            "effective_projection": effective,
            "read_only": True,
            "boundary": "查看迁移映射和差异不会写入画像；只有明确执行回放才创建一个带版本的 canonical 快照。",
        }

    def project_profile_snapshot(
        self, owner_public_id: str, *, course_id: str | None = None,
    ) -> DBProfileSnapshot:
        """Replay one legacy profile into the existing canonical snapshot table.

        Replaying the same source and effective projection returns the existing
        migration snapshot, so it cannot create a second profile truth.
        """
        owner, profile = self._owner_and_profile(owner_public_id)
        report = self.profile_migration_report(owner.public_id, course_id=course_id)
        projection = report["effective_projection"]
        data = {
            "kind": "legacy_profile_migration",
            "owner_public_id": owner.public_id,
            "legacy_student_id": profile.student_id,
            "course_id": course_id,
            "source_profile_id": profile.student_id,
            "mapping_version": PROFILE_MAPPING_VERSION,
            "profile_projection": projection,
            "dimension_states": deepcopy(projection.get("dimension_states") or {}),
            "learning_state_causes": deepcopy(projection.get("learning_state_causes") or {}),
            "weak_points": list(projection.get("weak_points") or []),
            "weak_knowledge_point_ids": list(projection.get("weak_points") or []),
            "concept_mastery": deepcopy(projection.get("concept_mastery") or {}),
            "knowledge_traces": deepcopy(projection.get("knowledge_traces") or {}),
            "bkt_states": deepcopy(projection.get("bkt_states") or {}),
            "legacy_migration": {
                "mapping_version": PROFILE_MAPPING_VERSION,
                "source": report["source_profile"],
                "confirmed_fields": report["confirmed_fields"],
                "diff": report["diff"],
                "influence": report["influence"],
            },
            "profile_version": None,
        }
        identity = deepcopy(data)
        identity["profile_version"] = ""
        digest = _content_hash(identity)
        existing = next(
            (
                row for row in self.session.query(DBProfileSnapshot).filter_by(
                    owner_public_id=owner.public_id,
                    content_hash=digest,
                ).all()
                if (row.snapshot or {}).get("kind") == "legacy_profile_migration"
            ),
            None,
        )
        if existing is not None:
            return existing

        versions = []
        for row in self.session.query(DBProfileSnapshot).filter_by(owner_public_id=owner.public_id).all():
            marker = str(row.profile_version or "")
            if marker.startswith("profile.legacy-migration.v"):
                try:
                    versions.append(int(marker.rsplit("v", 1)[1]))
                except ValueError:
                    continue
        version = f"profile.legacy-migration.v{(max(versions) if versions else 0) + 1}"
        data["profile_version"] = version
        row = DBProfileSnapshot(
            id=f"ps-legacy-profile-{uuid.uuid5(uuid.NAMESPACE_URL, owner.public_id + ':' + version).hex[:24]}",
            owner_public_id=owner.public_id,
            legacy_student_id=profile.student_id,
            profile_version=version,
            snapshot=data,
            content_hash=digest,
            trace_id=f"legacy-profile-replay:{profile.student_id}:{version}",
        )
        self.session.add(row)
        self.session.flush()
        return row

    def knowledge_documents(self, student_id: str) -> list[dict[str, Any]]:
        rows = (
            self.session.query(DBKnowledgeDocument)
            .filter(DBKnowledgeDocument.student_id == student_id)
            .order_by(DBKnowledgeDocument.created_at, DBKnowledgeDocument.id)
            .all()
        )
        return [
            {
                "legacy_id": row.id,
                "owner_legacy_student_id": row.student_id,
                "object_type": "source_document",
                "title": row.title or row.filename,
                "filename": row.filename,
                "content": row.content or "",
                "metadata": {
                    "file_type": row.file_type,
                    "file_size": row.file_size,
                    "tags": row.tags or [],
                    "chunk_count": row.chunk_count,
                },
            }
            for row in rows
        ]

    def notes(self, student_id: str) -> list[dict[str, Any]]:
        rows = (
            self.session.query(DBNote)
            .filter(DBNote.student_id == student_id)
            .order_by(DBNote.created_at, DBNote.id)
            .all()
        )
        return [
            {
                "legacy_id": row.id,
                "owner_legacy_student_id": row.student_id,
                "object_type": "artifact",
                "artifact_type": "note",
                "title": (row.content or "")[:80] or "Legacy note",
                "content": row.content or "",
                "metadata": {"source": row.source, "tags": row.tags or [], "concepts": row.concepts or []},
            }
            for row in rows
        ]

    def review_plans(self, student_id: str) -> list[dict[str, Any]]:
        rows = (
            self.session.query(DBReviewPlan)
            .filter(DBReviewPlan.student_id == student_id)
            .order_by(DBReviewPlan.created_at, DBReviewPlan.id)
            .all()
        )
        return [
            {
                "legacy_id": str(row.id),
                "owner_legacy_student_id": row.student_id,
                "object_type": "path_node",
                "title": row.concept,
                "status": "scheduled",
                "metadata": {
                    "interval_days": row.interval_days,
                    "next_review_at": row.next_review_at.isoformat() if row.next_review_at else None,
                    "mastery": row.mastery,
                },
            }
            for row in rows
        ]

    def conversations(self, student_id: str) -> list[dict[str, Any]]:
        rows = (
            self.session.query(DBConversationHistory)
            .filter(DBConversationHistory.student_id == student_id)
            .order_by(DBConversationHistory.created_at, DBConversationHistory.id)
            .all()
        )
        return [
            {
                "legacy_id": str(row.id),
                "owner_legacy_student_id": row.student_id,
                "object_type": "conversation",
                "query": row.query or "",
                "response_summary": row.response_summary or "",
                "target": row.target or "",
                "profile_snapshot": row.profile_snapshot,
            }
            for row in rows
        ]

    def wrong_questions(self, student_id: str) -> list[dict[str, Any]]:
        rows = (
            self.session.query(DBWrongQuestion)
            .filter(DBWrongQuestion.student_id == student_id)
            .order_by(DBWrongQuestion.created_at, DBWrongQuestion.id)
            .all()
        )
        return [
            {
                "legacy_id": str(row.id),
                "owner_legacy_student_id": row.student_id,
                "object_type": "wrong_question",
                "quiz_record_id": row.quiz_record_id,
                "concept": row.concept_name or "",
                "wrong_reason_category": row.wrong_reason_category,
                "pinned": bool(row.pinned),
                "notes": row.notes or "",
            }
            for row in rows
        ]
