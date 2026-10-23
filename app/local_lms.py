"""Deterministic local LMS exchange with candidate-only inbound grades."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from app.database import (
    DBAssessmentAttempt, DBAssessmentExamReport, DBAssessmentAbilityState,
    DBCertification, DBCourse, DBLMSAssignmentExchange, DBLMSCatalogExport,
    DBLMSGradeSummary, DBLMSSyncEvent, DBLocalLMSConnection,
    DBOrganization, DBOrganizationMembership, DBSkillEvidence,
    DBTrainingAssignment, DBTrainingCohort, DBTrainingProgram, DBUser,
)
from app.identity import normalize_role
from app.m1_lifecycle import record_audit
from app.m6_enterprise import bootstrap_competition_training_demo


TRUTHFULNESS = {
    "mode": "local_lms_simulation",
    "data_label": "冻结合成 LMS 交换数据 · 本地适配器",
    "network_sent": False,
    "real_lms_connected": False,
    "interoperability_certified": False,
    "external_grades_are_authoritative": False,
    "disclaimer": "用于演示课程、批次、分配、完成和成绩摘要交换；未连接真实 LMS，外部成绩仅为候选证据，不覆盖内部画像、测评或认证事实。",
}


class LMSSyncError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _require_admin(session: Any, actor: DBUser, organization_id: str) -> DBOrganization:
    if normalize_role(actor.role) != "admin":
        raise LMSSyncError("lms_sync_forbidden", "只有管理员可以管理 LMS 同步", status_code=403)
    organization = session.query(DBOrganization).filter_by(id=organization_id, status="active").first()
    membership = session.query(DBOrganizationMembership).filter_by(
        organization_id=organization_id, user_public_id=actor.public_id, role="admin", status="active",
    ).first()
    if organization is None or membership is None:
        raise LMSSyncError("lms_sync_forbidden", "管理员不属于该组织或组织不可用", status_code=403)
    return organization


def _event(
    session: Any, *, connection: DBLocalLMSConnection, actor: DBUser,
    action: str, outcome: str, object_type: str, object_id: str, evidence: dict[str, Any],
) -> DBLMSSyncEvent:
    row = DBLMSSyncEvent(
        organization_id=connection.organization_id, connection_id=connection.id,
        actor_public_id=actor.public_id, action=action, outcome=outcome,
        object_type=object_type, object_id=object_id,
        evidence_snapshot=evidence, evidence_hash=_hash(evidence),
    )
    session.add(row)
    return row


def ensure_connection(
    session: Any, *, actor: DBUser, organization_id: str,
    connection_key: str = "competition-local-lms", display_name: str = "比赛演示 LMS",
) -> tuple[DBLocalLMSConnection, bool]:
    _require_admin(session, actor, organization_id)
    existing = session.query(DBLocalLMSConnection).filter_by(
        organization_id=organization_id, connection_key=connection_key,
    ).first()
    if existing:
        return existing, False
    row = DBLocalLMSConnection(
        organization_id=organization_id, connection_key=connection_key,
        display_name=display_name, created_by_public_id=actor.public_id,
    )
    session.add(row)
    session.flush()
    _event(session, connection=row, actor=actor, action="connection.create", outcome="created",
           object_type="connection", object_id=row.id, evidence={"adapter_version": row.adapter_version, "network_sent": False})
    record_audit(session, actor_public_id=actor.public_id, action="local_lms.connection_create",
                 object_type="local_lms_connection", object_id=row.id, metadata={"organization_id": organization_id})
    session.commit()
    return row, True


def bootstrap_demo(session: Any, *, actor: DBUser) -> dict[str, Any]:
    training = bootstrap_competition_training_demo(session, actor=actor)
    connection, created = ensure_connection(session, actor=actor, organization_id=training["organization_id"])
    return {**training, "connection_id": connection.id, "connection_created": created}


def _connection(session: Any, actor: DBUser, organization_id: str, connection_id: str) -> DBLocalLMSConnection:
    _require_admin(session, actor, organization_id)
    row = session.query(DBLocalLMSConnection).filter_by(id=connection_id, organization_id=organization_id).first()
    if row is None:
        raise LMSSyncError("lms_connection_not_found", "LMS 连接不存在", status_code=404)
    if row.status != "active":
        raise LMSSyncError("lms_connection_disabled", "LMS 连接已停用")
    return row


def _cohort_course_ids(cohort: DBTrainingCohort) -> list[str]:
    values = cohort.course_versions or []
    return [str(value).split("@", 1)[0] for value in values]


def export_catalog(
    session: Any, *, actor: DBUser, organization_id: str, connection_id: str,
    source_type: str, source_object_id: str,
) -> tuple[DBLMSCatalogExport, bool]:
    connection = _connection(session, actor, organization_id, connection_id)
    if source_type == "course":
        course = session.query(DBCourse).filter_by(id=source_object_id).first()
        if course is None:
            raise LMSSyncError("lms_course_not_found", "课程不存在", status_code=404)
        from course_catalog import course_is_selectable
        if not course_is_selectable(session, course):
            raise LMSSyncError("lms_course_unavailable", "课程已停止发布或没有可用学习资料", status_code=409)
        cohorts = session.query(DBTrainingCohort).filter_by(organization_id=organization_id).all()
        if not any(course.id in _cohort_course_ids(item) for item in cohorts):
            raise LMSSyncError("lms_course_outside_organization", "课程未被该组织培训批次引用", status_code=403)
        snapshot = {
            "schema": "edumatrix.lms.course.v1", "course_id": course.id,
            "version": course.version, "manifest_version": course.manifest_version,
            "title": course.title, "subject": course.subject, "language": course.language,
            "status": course.status, "content_origin": course.content_origin,
        }
    elif source_type == "cohort":
        cohort = session.query(DBTrainingCohort).filter_by(id=source_object_id, organization_id=organization_id).first()
        if cohort is None:
            raise LMSSyncError("lms_cohort_not_found", "培训批次不存在", status_code=404)
        program = session.query(DBTrainingProgram).filter_by(id=cohort.training_program_id).one()
        snapshot = {
            "schema": "edumatrix.lms.cohort.v1", "cohort_id": cohort.id,
            "program_id": program.id, "program_title": program.title, "program_version": program.version,
            "course_versions": cohort.course_versions or [], "starts_at": _dt(cohort.starts_at),
            "ends_at": _dt(cohort.ends_at), "status": cohort.status,
        }
    else:
        raise LMSSyncError("lms_source_type_invalid", "source_type 只能是 course 或 cohort", status_code=422)
    snapshot_hash = _hash(snapshot)
    existing = session.query(DBLMSCatalogExport).filter_by(
        connection_id=connection.id, source_type=source_type,
        source_object_id=source_object_id, snapshot_hash=snapshot_hash,
    ).first()
    if existing:
        return existing, False
    row = DBLMSCatalogExport(
        organization_id=organization_id, connection_id=connection.id,
        source_type=source_type, source_object_id=source_object_id,
        external_catalog_key=f"edumatrix:{source_type}:{source_object_id}",
        snapshot=snapshot, snapshot_hash=snapshot_hash, created_by_public_id=actor.public_id,
    )
    session.add(row)
    _event(session, connection=connection, actor=actor, action="catalog.export", outcome="exported",
           object_type=source_type, object_id=source_object_id,
           evidence={"snapshot_hash": snapshot_hash, "external_catalog_key": row.external_catalog_key})
    session.commit()
    return row, True


def sync_assignment(
    session: Any, *, actor: DBUser, organization_id: str,
    connection_id: str, training_assignment_id: str,
) -> tuple[DBLMSAssignmentExchange, bool]:
    connection = _connection(session, actor, organization_id, connection_id)
    assignment = session.query(DBTrainingAssignment).filter_by(
        id=training_assignment_id, organization_id=organization_id,
    ).first()
    if assignment is None:
        raise LMSSyncError("lms_assignment_not_found", "培训分配不存在", status_code=404)
    cohort = session.query(DBTrainingCohort).filter_by(id=assignment.cohort_id, organization_id=organization_id).one()
    payload = {
        "schema": "edumatrix.lms.assignment.v1", "assignment_id": assignment.id,
        "cohort_id": cohort.id, "learner_public_id": assignment.learner_public_id,
        "course_versions": cohort.course_versions or [], "status": assignment.status,
        "assigned_at": _dt(assignment.assigned_at),
    }
    payload_hash = _hash(payload)
    existing = session.query(DBLMSAssignmentExchange).filter_by(
        connection_id=connection.id, training_assignment_id=assignment.id,
    ).first()
    if existing and existing.payload_hash == payload_hash:
        return existing, False
    if existing:
        existing.payload = payload
        existing.payload_hash = payload_hash
        existing.status = "withdrawn" if assignment.status in {"cancelled", "withdrawn"} else "assigned"
        existing.lock_version += 1
        existing.synced_at = _now()
        row = existing
        outcome = "updated"
    else:
        row = DBLMSAssignmentExchange(
            organization_id=organization_id, connection_id=connection.id,
            training_assignment_id=assignment.id,
            external_assignment_key=f"edumatrix:assignment:{assignment.id}",
            payload=payload, payload_hash=payload_hash,
        )
        session.add(row)
        outcome = "created"
    _event(session, connection=connection, actor=actor, action="assignment.sync", outcome=outcome,
           object_type="training_assignment", object_id=assignment.id,
           evidence={"payload_hash": payload_hash, "learner_public_id": assignment.learner_public_id})
    session.commit()
    return row, True


def import_grade_summary(
    session: Any, *, actor: DBUser, organization_id: str, connection_id: str,
    external_record_key: str, training_assignment_id: str, course_id: str | None,
    completion_status: str, score: float | None, occurred_at: datetime,
) -> tuple[DBLMSGradeSummary, bool]:
    connection = _connection(session, actor, organization_id, connection_id)
    assignment = session.query(DBTrainingAssignment).filter_by(
        id=training_assignment_id, organization_id=organization_id,
    ).first()
    if assignment is None:
        raise LMSSyncError("lms_assignment_not_found", "培训分配不存在", status_code=404)
    cohort = session.query(DBTrainingCohort).filter_by(id=assignment.cohort_id, organization_id=organization_id).one()
    if course_id:
        course = session.query(DBCourse).filter_by(id=course_id).first()
        if course is None:
            raise LMSSyncError("lms_course_not_found", "课程不存在", status_code=404)
        from course_catalog import course_is_selectable
        if not course_is_selectable(session, course):
            raise LMSSyncError("lms_course_unavailable", "课程已停止发布或没有可用学习资料", status_code=409)
    if course_id and course_id not in _cohort_course_ids(cohort):
        raise LMSSyncError("lms_course_assignment_mismatch", "课程不属于该培训分配", status_code=422)
    payload = {
        "external_record_key": external_record_key,
        "training_assignment_id": training_assignment_id,
        "learner_public_id": assignment.learner_public_id,
        "course_id": course_id,
        "completion_status": completion_status,
        "score": score,
        "occurred_at": occurred_at.isoformat(),
    }
    payload_hash = _hash(payload)
    existing = session.query(DBLMSGradeSummary).filter_by(
        connection_id=connection.id, external_record_key=external_record_key,
    ).first()
    if existing:
        if existing.payload_hash != payload_hash:
            _event(session, connection=connection, actor=actor, action="grade.import", outcome="conflict",
                   object_type="external_grade", object_id=external_record_key,
                   evidence={"existing_hash": existing.payload_hash, "incoming_hash": payload_hash})
            session.commit()
            raise LMSSyncError("lms_grade_idempotency_conflict", "同一外部成绩键对应不同载荷，已拒绝覆盖")
        return existing, False
    row = DBLMSGradeSummary(
        organization_id=organization_id, connection_id=connection.id,
        external_record_key=external_record_key, training_assignment_id=assignment.id,
        learner_public_id=assignment.learner_public_id, course_id=course_id,
        completion_status=completion_status, score=score, occurred_at=occurred_at,
        source_payload=payload, payload_hash=payload_hash, evidence_status="candidate",
    )
    session.add(row)
    session.flush()
    _event(session, connection=connection, actor=actor, action="grade.import", outcome="candidate_recorded",
           object_type="external_grade", object_id=external_record_key,
           evidence={"payload_hash": payload_hash, "evidence_status": "candidate", "canonical_tables_written": []})
    record_audit(session, actor_public_id=actor.public_id, action="local_lms.grade_candidate_import",
                 object_type="lms_grade_summary", object_id=row.id,
                 metadata={"organization_id": organization_id, "external_record_key": external_record_key,
                           "authoritative": False})
    session.commit()
    return row, True


def authority_counts(session: Any, *, learner_public_id: str) -> dict[str, int]:
    return {
        "assessment_attempts": session.query(DBAssessmentAttempt).filter_by(owner_public_id=learner_public_id).count(),
        # Reports are not directly owner-scoped; the global count is still a
        # useful before/after invariant proving that LMS import wrote none.
        "assessment_reports": session.query(DBAssessmentExamReport).count(),
        "ability_states": session.query(DBAssessmentAbilityState).filter_by(owner_public_id=learner_public_id).count(),
        "skill_evidence": session.query(DBSkillEvidence).filter_by(learner_public_id=learner_public_id).count(),
        "certifications": session.query(DBCertification).filter_by(learner_public_id=learner_public_id).count(),
    }


def workspace(session: Any, *, actor: DBUser, organization_id: str | None = None) -> dict[str, Any]:
    if normalize_role(actor.role) != "admin":
        raise LMSSyncError("lms_sync_forbidden", "只有管理员可以查看 LMS 同步工作台", status_code=403)
    memberships = session.query(DBOrganizationMembership).filter_by(
        user_public_id=actor.public_id, role="admin", status="active",
    ).all()
    organizations = []
    for member in memberships:
        org = session.query(DBOrganization).filter_by(id=member.organization_id, status="active").first()
        if org:
            organizations.append({"id": org.id, "name": org.name})
    if not organizations:
        return {"truthfulness": TRUTHFULNESS, "organizations": [], "selected": None}
    selected_id = organization_id or organizations[0]["id"]
    organization = _require_admin(session, actor, selected_id)
    connections = session.query(DBLocalLMSConnection).filter_by(organization_id=selected_id).order_by(DBLocalLMSConnection.created_at).all()
    cohorts = session.query(DBTrainingCohort).filter_by(organization_id=selected_id).order_by(DBTrainingCohort.created_at).all()
    assignments = session.query(DBTrainingAssignment).filter_by(organization_id=selected_id).order_by(DBTrainingAssignment.assigned_at).all()
    course_ids = sorted({course_id for cohort in cohorts for course_id in _cohort_course_ids(cohort)})
    courses = session.query(DBCourse).filter(DBCourse.id.in_(course_ids)).all() if course_ids else []
    from course_catalog import course_is_selectable
    courses = [row for row in courses if course_is_selectable(session, row)]
    exports = session.query(DBLMSCatalogExport).filter_by(organization_id=selected_id).order_by(DBLMSCatalogExport.created_at.desc()).limit(30).all()
    exchanges = session.query(DBLMSAssignmentExchange).filter_by(organization_id=selected_id).order_by(DBLMSAssignmentExchange.synced_at.desc()).all()
    grades = session.query(DBLMSGradeSummary).filter_by(organization_id=selected_id).order_by(DBLMSGradeSummary.created_at.desc()).all()
    events = session.query(DBLMSSyncEvent).filter_by(organization_id=selected_id).order_by(DBLMSSyncEvent.created_at.desc()).limit(40).all()
    learner_counts = {item.learner_public_id: authority_counts(session, learner_public_id=item.learner_public_id) for item in assignments}
    return {
        "truthfulness": TRUTHFULNESS, "organizations": organizations,
        "selected": {
            "organization": {"id": organization.id, "name": organization.name},
            "connections": [{"id": row.id, "connection_key": row.connection_key, "display_name": row.display_name,
                             "adapter_version": row.adapter_version, "status": row.status, "lock_version": row.lock_version} for row in connections],
            "courses": [{"id": row.id, "title": row.title, "version": row.version, "status": row.status} for row in courses],
            "cohorts": [{"id": row.id, "program_id": row.training_program_id, "course_versions": row.course_versions,
                         "status": row.status, "starts_at": _dt(row.starts_at), "ends_at": _dt(row.ends_at)} for row in cohorts],
            "assignments": [{"id": row.id, "cohort_id": row.cohort_id, "learner_public_id": row.learner_public_id,
                             "status": row.status, "assigned_at": _dt(row.assigned_at),
                             "authority_counts": learner_counts[row.learner_public_id]} for row in assignments],
            "exports": [{"id": row.id, "source_type": row.source_type, "source_object_id": row.source_object_id,
                         "external_catalog_key": row.external_catalog_key, "snapshot_hash": row.snapshot_hash,
                         "created_at": _dt(row.created_at)} for row in exports],
            "assignment_exchanges": [{"id": row.id, "training_assignment_id": row.training_assignment_id,
                                      "external_assignment_key": row.external_assignment_key, "status": row.status,
                                      "payload_hash": row.payload_hash, "lock_version": row.lock_version,
                                      "synced_at": _dt(row.synced_at)} for row in exchanges],
            "grade_summaries": [{"id": row.id, "external_record_key": row.external_record_key,
                                 "training_assignment_id": row.training_assignment_id,
                                 "learner_public_id": row.learner_public_id, "course_id": row.course_id,
                                 "completion_status": row.completion_status, "score": row.score,
                                 "evidence_status": row.evidence_status, "occurred_at": _dt(row.occurred_at),
                                 "payload_hash": row.payload_hash} for row in grades],
            "events": [{"id": row.id, "action": row.action, "outcome": row.outcome,
                        "object_type": row.object_type, "object_id": row.object_id,
                        "evidence_hash": row.evidence_hash, "created_at": _dt(row.created_at)} for row in events],
        },
    }
