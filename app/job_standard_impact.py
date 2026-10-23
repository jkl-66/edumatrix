"""Frozen synthetic job-standard impact previews and governed rescheduling."""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

from app.database import (
    DBCertification,
    DBCompetencyStandard,
    DBJobFamily,
    DBJobLevel,
    DBJobStandardImpactConfirmation,
    DBJobStandardImpactPreview,
    DBOrganizationMembership,
    DBRetrainingTask,
    DBTrainingAssignment,
    DBTrainingCohort,
    DBTrainingProgram,
    DBUser,
)
from app.m1_enterprise import organization_role, publish_job_standard_version
from app.m1_lifecycle import utcnow


STANDARD_SOURCE = "frozen_synthetic_competition_demo"


class JobStandardImpactError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise JobStandardImpactError(code, message)


def _canonical_hash(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _manager_role(db: Any, *, actor: DBUser, organization_id: str) -> str:
    role = organization_role(db, organization_id=organization_id, user_public_id=actor.public_id)
    if role not in {"manager", "admin"}:
        _fail("job_standard_impact_forbidden", "only organization managers or admins may manage standard upgrades")
    return role


def _level_context(db: Any, level_id: str) -> tuple[DBJobLevel, DBJobFamily]:
    level = db.query(DBJobLevel).filter_by(id=level_id).first()
    if level is None:
        _fail("job_standard_level_unknown", "job standard version does not exist")
    family = db.query(DBJobFamily).filter_by(id=level.job_family_id).one()
    return level, family


def _standard_rows(db: Any, level_id: str) -> list[DBCompetencyStandard]:
    return db.query(DBCompetencyStandard).filter_by(job_level_id=level_id).order_by(
        DBCompetencyStandard.skill_standard_id
    ).all()


def _standard_value(row: DBCompetencyStandard) -> dict[str, Any]:
    return {
        "id": row.id,
        "skill_standard_id": row.skill_standard_id,
        "version": row.version,
        "requirement_level": row.requirement_level,
        "mandatory": bool(row.mandatory),
        "risk_level": row.risk_level,
        "exemption_policy": row.exemption_policy,
        "evidence_requirements": list(row.evidence_requirements or []),
        "acceptance_rules": list(row.acceptance_rules or []),
    }


def structural_diff(db: Any, source: DBJobLevel, target: DBJobLevel) -> dict[str, Any]:
    old = {row.skill_standard_id: _standard_value(row) for row in _standard_rows(db, source.id)}
    new = {row.skill_standard_id: _standard_value(row) for row in _standard_rows(db, target.id)}
    fields = (
        "requirement_level", "mandatory", "risk_level", "exemption_policy",
        "evidence_requirements", "acceptance_rules",
    )
    changed = []
    for skill_id in sorted(old.keys() & new.keys()):
        changes = {
            field: {"before": old[skill_id][field], "after": new[skill_id][field]}
            for field in fields if old[skill_id][field] != new[skill_id][field]
        }
        if changes:
            changed.append({"skill_standard_id": skill_id, "changes": changes})
    return {
        "source": {"id": source.id, "version": source.version, "title": source.title},
        "target": {"id": target.id, "version": target.version, "title": target.title},
        "responsibilities": {
            "before": list(source.responsibilities or []),
            "after": list(target.responsibilities or []),
            "changed": list(source.responsibilities or []) != list(target.responsibilities or []),
        },
        "competencies": {
            "added": [new[key] for key in sorted(new.keys() - old.keys())],
            "removed": [old[key] for key in sorted(old.keys() - new.keys())],
            "changed": changed,
            "unchanged_count": len(old.keys() & new.keys()) - len(changed),
        },
    }


def _impact_snapshot(db: Any, *, organization_id: str, source_level_id: str) -> dict[str, Any]:
    programs = db.query(DBTrainingProgram).filter_by(
        organization_id=organization_id, target_job_level_id=source_level_id
    ).order_by(DBTrainingProgram.id).all()
    program_ids = [row.id for row in programs]
    cohorts = db.query(DBTrainingCohort).filter(
        DBTrainingCohort.training_program_id.in_(program_ids)
    ).order_by(DBTrainingCohort.id).all() if program_ids else []
    cohort_ids = [row.id for row in cohorts]
    assignments = db.query(DBTrainingAssignment).filter(
        DBTrainingAssignment.cohort_id.in_(cohort_ids)
    ).order_by(DBTrainingAssignment.id).all() if cohort_ids else []
    certifications = db.query(DBCertification).filter_by(
        organization_id=organization_id, job_level_id=source_level_id
    ).order_by(DBCertification.id).all()
    learners = sorted({row.learner_public_id for row in assignments} | {
        row.learner_public_id for row in certifications
    })
    return {
        "program_ids": program_ids,
        "cohort_ids": cohort_ids,
        "assignment_ids": [row.id for row in assignments],
        "certification_ids": [row.id for row in certifications],
        "learner_public_ids": learners,
        "counts": {
            "programs": len(programs), "cohorts": len(cohorts),
            "assignments": len(assignments), "certifications": len(certifications),
            "learners": len(learners),
        },
        "certification_status_counts": {
            status: sum(1 for row in certifications if row.status == status)
            for status in sorted({row.status for row in certifications})
        },
    }


def create_preview(
    db: Any, *, actor: DBUser, organization_id: str,
    source_job_level_id: str, target_job_level_id: str,
) -> tuple[DBJobStandardImpactPreview, bool]:
    _manager_role(db, actor=actor, organization_id=organization_id)
    source, source_family = _level_context(db, source_job_level_id)
    target, target_family = _level_context(db, target_job_level_id)
    if source_family.organization_id != organization_id or target_family.organization_id != organization_id:
        _fail("job_standard_impact_forbidden", "job standard belongs to another organization")
    if source.job_family_id != target.job_family_id or source.level_code != target.level_code:
        _fail("job_standard_pair_invalid", "source and target must be versions of the same job level")
    if source.id == target.id:
        _fail("job_standard_pair_invalid", "source and target versions must differ")
    existing = db.query(DBJobStandardImpactPreview).filter_by(
        organization_id=organization_id,
        source_job_level_id=source.id,
        target_job_level_id=target.id,
    ).first()
    if existing is not None:
        return existing, False
    diff = structural_diff(db, source, target)
    impact = _impact_snapshot(db, organization_id=organization_id, source_level_id=source.id)
    frozen = {
        "schema_version": "next.job-standard-impact.v1",
        "standard_source": STANDARD_SOURCE,
        "organization_id": organization_id,
        "diff": diff,
        "impact": impact,
    }
    row = DBJobStandardImpactPreview(
        organization_id=organization_id,
        source_job_level_id=source.id,
        target_job_level_id=target.id,
        created_by_public_id=actor.public_id,
        standard_source=STANDARD_SOURCE,
        diff_snapshot=diff,
        impact_snapshot=impact,
        preview_hash=_canonical_hash(frozen),
    )
    db.add(row)
    db.flush()
    return row, True


def prepare_demo_upgrade(
    db: Any, *, actor: DBUser, organization_id: str, source_job_level_id: str,
    target_version: str = "2026.2",
) -> tuple[DBJobLevel, bool]:
    role = _manager_role(db, actor=actor, organization_id=organization_id)
    if role != "admin":
        _fail("job_standard_publish_forbidden", "only organization admins may publish the synthetic target version")
    source, family = _level_context(db, source_job_level_id)
    if family.organization_id != organization_id:
        _fail("job_standard_impact_forbidden", "job standard belongs to another organization")
    existing = db.query(DBJobLevel).filter_by(
        job_family_id=source.job_family_id, level_code=source.level_code, version=target_version,
    ).first()
    if existing is not None:
        return existing, False
    responsibilities = list(source.responsibilities or [])
    addition = "执行模型可靠性评测与可追溯交付"
    if addition not in responsibilities:
        responsibilities.append(addition)
    target, standards = publish_job_standard_version(
        db, source_job_level=source, new_version=target_version,
        actor_public_id=actor.public_id, responsibilities=responsibilities,
    )
    if standards:
        first = standards[0]
        first.requirement_level = "advanced"
        first.risk_level = "high"
        requirements = list(first.evidence_requirements or [])
        if "artifact" not in requirements:
            requirements.append("artifact")
        first.evidence_requirements = requirements
        rules = list(first.acceptance_rules or [])
        rules.append({"rule": "reliability_report_required", "source": STANDARD_SOURCE})
        first.acceptance_rules = rules
    return target, True


def _target_snapshot(db: Any, target: DBJobLevel) -> dict[str, Any]:
    return {
        "job_level_id": target.id,
        "job_level_version": target.version,
        "standard_source": STANDARD_SOURCE,
        "competencies": [_standard_value(row) for row in _standard_rows(db, target.id)],
    }


def _schedule(db: Any, *, preview: DBJobStandardImpactPreview) -> dict[str, Any]:
    target = db.query(DBJobLevel).filter_by(id=preview.target_job_level_id).one()
    title = f"岗位标准升级复训 · {target.level_code}"
    program = db.query(DBTrainingProgram).filter_by(
        organization_id=preview.organization_id, title=title, version=target.version
    ).first()
    program_created = False
    if program is None:
        program = DBTrainingProgram(
            organization_id=preview.organization_id, target_job_level_id=target.id,
            title=title, version=target.version, status="published",
        )
        db.add(program); db.flush(); program_created = True
    cohort = db.query(DBTrainingCohort).filter_by(training_program_id=program.id).first()
    cohort_created = False
    if cohort is None:
        cohort = DBTrainingCohort(
            organization_id=preview.organization_id, training_program_id=program.id,
            standard_snapshot={**_target_snapshot(db, target), "impact_preview_id": preview.id},
            status="planned",
        )
        db.add(cohort); db.flush(); cohort_created = True
    active_members = {
        row.user_public_id for row in db.query(DBOrganizationMembership).filter_by(
            organization_id=preview.organization_id, status="active"
        ).all()
    }
    assignments_created = []
    skipped_learners = []
    for learner_id in preview.impact_snapshot.get("learner_public_ids", []):
        if learner_id not in active_members:
            skipped_learners.append(learner_id)
            continue
        assignment = db.query(DBTrainingAssignment).filter_by(
            cohort_id=cohort.id, learner_public_id=learner_id
        ).first()
        if assignment is None:
            assignment = DBTrainingAssignment(
                organization_id=preview.organization_id, cohort_id=cohort.id,
                learner_public_id=learner_id, assignment_source="retraining",
                source_reference=preview.id,
            )
            db.add(assignment); db.flush(); assignments_created.append(assignment.id)
    tasks_created = []
    eligible_certifications = db.query(DBCertification).filter(
        DBCertification.id.in_(preview.impact_snapshot.get("certification_ids", [])),
        DBCertification.status.in_(["active", "expired"]),
    ).order_by(DBCertification.id).all() if preview.impact_snapshot.get("certification_ids") else []
    trigger_key = f"job_standard_upgrade:{target.id}"
    now = utcnow()
    for certification in eligible_certifications:
        existing = db.query(DBRetrainingTask).filter_by(
            certification_id=certification.id, trigger_key=trigger_key
        ).first()
        if existing is not None:
            continue
        rule = dict(certification.retraining_rule or {})
        completion_days = max(1, min(int(rule.get("completion_days", 30)), 365))
        task = DBRetrainingTask(
            certification_id=certification.id, organization_id=preview.organization_id,
            learner_public_id=certification.learner_public_id,
            trigger_type="job_standard_upgrade", trigger_key=trigger_key,
            title=f"{target.title} {target.version} 标准升级复训",
            due_at=now + timedelta(days=completion_days),
            rule_snapshot={**rule, "impact_preview_id": preview.id, "target_job_level_id": target.id},
        )
        db.add(task); db.flush(); tasks_created.append(task.id)
    return {
        "program_id": program.id, "program_created": program_created,
        "cohort_id": cohort.id, "cohort_created": cohort_created,
        "assignment_ids_created": assignments_created,
        "retraining_task_ids_created": tasks_created,
        "skipped_inactive_learner_public_ids": skipped_learners,
    }


def confirm_preview(
    db: Any, *, actor: DBUser, preview_id: str, preview_hash: str, reason: str,
) -> tuple[DBJobStandardImpactPreview, DBJobStandardImpactConfirmation, bool]:
    preview = db.query(DBJobStandardImpactPreview).filter_by(id=preview_id).first()
    if preview is None:
        _fail("job_standard_preview_unknown", "impact preview does not exist")
    role = _manager_role(db, actor=actor, organization_id=preview.organization_id)
    if preview.preview_hash != preview_hash:
        _fail("job_standard_preview_stale", "preview hash does not match the frozen impact")
    existing = db.query(DBJobStandardImpactConfirmation).filter_by(preview_id=preview.id).first()
    if existing is not None:
        return preview, existing, False
    normalized_reason = reason.strip()
    if len(normalized_reason) < 4:
        _fail("job_standard_reason_invalid", "confirmation reason is too short")
    scheduling = _schedule(db, preview=preview)
    reason_hash = hashlib.sha256(normalized_reason.encode("utf-8")).hexdigest()
    evidence = {
        "preview_id": preview.id, "preview_hash": preview.preview_hash,
        "actor_public_id": actor.public_id, "actor_role": role,
        "reason_hash": reason_hash, "scheduling": scheduling,
    }
    confirmation = DBJobStandardImpactConfirmation(
        preview_id=preview.id, organization_id=preview.organization_id,
        actor_public_id=actor.public_id, actor_role=role,
        preview_hash=preview.preview_hash, reason=normalized_reason,
        reason_hash=reason_hash, scheduling_snapshot=scheduling,
        confirmation_hash=_canonical_hash(evidence),
    )
    db.add(confirmation); db.flush()
    preview.status = "confirmed"
    preview.confirmed_at = utcnow()
    return preview, confirmation, True


def _confirmation_payload(row: DBJobStandardImpactConfirmation | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id, "actor_public_id": row.actor_public_id,
        "actor_role": row.actor_role, "preview_hash": row.preview_hash,
        "reason": row.reason, "reason_hash": row.reason_hash,
        "scheduling": row.scheduling_snapshot, "confirmation_hash": row.confirmation_hash,
        "created_at": row.created_at.isoformat(),
    }


def preview_payload(db: Any, row: DBJobStandardImpactPreview) -> dict[str, Any]:
    confirmation = db.query(DBJobStandardImpactConfirmation).filter_by(preview_id=row.id).first()
    return {
        "id": row.id, "organization_id": row.organization_id,
        "source_job_level_id": row.source_job_level_id,
        "target_job_level_id": row.target_job_level_id,
        "standard_source": row.standard_source,
        "truth_label": "冻结合成岗位标准 · 比赛演示数据",
        "external_enterprise_standard_claimed": False,
        "diff": row.diff_snapshot, "impact": row.impact_snapshot,
        "preview_hash": row.preview_hash, "status": row.status,
        "created_by_public_id": row.created_by_public_id,
        "created_at": row.created_at.isoformat(),
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
        "confirmation": _confirmation_payload(confirmation),
    }


def workspace(db: Any, *, actor: DBUser, organization_id: str) -> dict[str, Any]:
    role = _manager_role(db, actor=actor, organization_id=organization_id)
    families = db.query(DBJobFamily).filter_by(organization_id=organization_id).order_by(DBJobFamily.code).all()
    family_ids = [row.id for row in families]
    levels = db.query(DBJobLevel).filter(DBJobLevel.job_family_id.in_(family_ids)).order_by(
        DBJobLevel.level_code, DBJobLevel.created_at
    ).all() if family_ids else []
    previews = db.query(DBJobStandardImpactPreview).filter_by(
        organization_id=organization_id
    ).order_by(DBJobStandardImpactPreview.created_at.desc()).all()
    family_by_id = {row.id: row for row in families}
    return {
        "schema_version": "next.job-standard-impact.v1",
        "organization_id": organization_id, "role": role,
        "truth_label": "冻结合成岗位标准 · 比赛演示数据",
        "disclaimer": "用于展示岗位标准升级治理，不宣称来自真实企业，也不自动作出调岗、晋升或淘汰决定。",
        "job_levels": [{
            "id": row.id, "job_family_id": row.job_family_id,
            "job_family_code": family_by_id[row.job_family_id].code,
            "job_family_title": family_by_id[row.job_family_id].title,
            "level_code": row.level_code, "version": row.version,
            "title": row.title, "status": row.status,
            "responsibilities": list(row.responsibilities or []),
        } for row in levels],
        "previews": [preview_payload(db, row) for row in previews],
    }
