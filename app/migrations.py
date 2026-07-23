"""Small versioned migration registry for the existing SQLite deployment.

The legacy additive migration remains as migration zero. Every M1+ change is
registered here with a stable checksum so startup can detect edited history.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Any

import sqlalchemy as sa


@dataclass(frozen=True)
class Migration:
    version: str
    description: str
    apply: Callable[[Any], None]

    @property
    def checksum(self) -> str:
        text = f"{self.version}:{self.description}:{self.apply.__name__}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record_m1_foundation(connection: Any) -> None:
    # Tables/columns are created by SQLAlchemy metadata plus the compatibility
    # migration before this registry runs. This version freezes that resulting
    # schema as the first reproducible M1 baseline.
    required = {
        "users", "course_memberships", "courses", "source_documents",
        "chapters", "knowledge_points", "source_refs", "artifacts",
        "generation_tasks", "learning_events", "audit_logs",
    }
    actual = set(sa.inspect(connection).get_table_names())
    missing = sorted(required - actual)
    if missing:
        raise RuntimeError(f"M1 schema migration missing tables: {missing}")


def _install_integrity_triggers(connection: Any) -> None:
    statements = (
        """CREATE TRIGGER IF NOT EXISTS trg_users_role_insert BEFORE INSERT ON users
        WHEN NEW.role NOT IN ('admin','teacher','assistant','student','visitor')
        BEGIN SELECT RAISE(ABORT, 'invalid user role'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_users_role_update BEFORE UPDATE OF role ON users
        WHEN NEW.role NOT IN ('admin','teacher','assistant','student','visitor')
        BEGIN SELECT RAISE(ABORT, 'invalid user role'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_task_state_insert BEFORE INSERT ON generation_tasks
        WHEN NEW.status NOT IN ('queued','running','completed','failed','cancelled') OR NEW.progress < 0 OR NEW.progress > 1
        BEGIN SELECT RAISE(ABORT, 'invalid generation task state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_task_state_update BEFORE UPDATE OF status, progress ON generation_tasks
        WHEN NEW.status NOT IN ('queued','running','completed','failed','cancelled') OR NEW.progress < 0 OR NEW.progress > 1
        BEGIN SELECT RAISE(ABORT, 'invalid generation task state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_artifact_state_insert BEFORE INSERT ON artifacts
        WHEN NEW.status NOT IN ('draft','reviewing','approved','published','archived','withdrawn') OR NEW.lock_version < 1
        BEGIN SELECT RAISE(ABORT, 'invalid artifact state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_artifact_state_update BEFORE UPDATE OF status, lock_version ON artifacts
        WHEN NEW.status NOT IN ('draft','reviewing','approved','published','archived','withdrawn') OR NEW.lock_version < 1
        BEGIN SELECT RAISE(ABORT, 'invalid artifact state'); END""",
    )
    for statement in statements:
        connection.execute(sa.text(statement))


def _install_m1_governance_triggers(connection: Any) -> None:
    statements = (
        """CREATE TRIGGER IF NOT EXISTS trg_evaluation_case_immutable_update
        BEFORE UPDATE ON evaluation_cases BEGIN
        SELECT RAISE(ABORT, 'evaluation case is immutable'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_evaluation_case_immutable_delete
        BEFORE DELETE ON evaluation_cases BEGIN
        SELECT RAISE(ABORT, 'evaluation case is immutable'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_org_member_valid_insert BEFORE INSERT ON organization_memberships
        WHEN NEW.role NOT IN ('learner','mentor','manager','admin')
          OR NEW.status NOT IN ('invited','active','suspended','removed')
        BEGIN SELECT RAISE(ABORT, 'invalid organization membership'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_org_member_valid_update BEFORE UPDATE OF role,status ON organization_memberships
        WHEN NEW.role NOT IN ('learner','mentor','manager','admin')
          OR NEW.status NOT IN ('invited','active','suspended','removed')
        BEGIN SELECT RAISE(ABORT, 'invalid organization membership'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_training_program_org_insert BEFORE INSERT ON training_programs
        WHEN NOT EXISTS (
          SELECT 1 FROM job_levels jl JOIN job_families jf ON jf.id=jl.job_family_id
          WHERE jl.id=NEW.target_job_level_id AND jf.organization_id=NEW.organization_id)
        BEGIN SELECT RAISE(ABORT, 'cross-organization training program'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_training_program_org_update BEFORE UPDATE OF organization_id,target_job_level_id ON training_programs
        WHEN NOT EXISTS (
          SELECT 1 FROM job_levels jl JOIN job_families jf ON jf.id=jl.job_family_id
          WHERE jl.id=NEW.target_job_level_id AND jf.organization_id=NEW.organization_id)
        BEGIN SELECT RAISE(ABORT, 'cross-organization training program'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_training_cohort_org_insert BEFORE INSERT ON training_cohorts
        WHEN NOT EXISTS (SELECT 1 FROM training_programs tp WHERE tp.id=NEW.training_program_id AND tp.organization_id=NEW.organization_id)
        BEGIN SELECT RAISE(ABORT, 'cross-organization training cohort'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_training_assignment_org_insert BEFORE INSERT ON training_assignments
        WHEN NOT EXISTS (SELECT 1 FROM training_cohorts tc WHERE tc.id=NEW.cohort_id AND tc.organization_id=NEW.organization_id)
        BEGIN SELECT RAISE(ABORT, 'cross-organization training assignment'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_exemption_org_insert BEFORE INSERT ON exemption_requests
        WHEN NOT EXISTS (SELECT 1 FROM training_assignments ta WHERE ta.id=NEW.assignment_id AND ta.organization_id=NEW.organization_id)
        BEGIN SELECT RAISE(ABORT, 'cross-organization exemption request'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_external_identity_member_insert BEFORE INSERT ON external_identity_mappings
        WHEN NOT EXISTS (SELECT 1 FROM organization_memberships om
                         WHERE om.organization_id=NEW.organization_id AND om.user_public_id=NEW.user_public_id AND om.status='active')
        BEGIN SELECT RAISE(ABORT, 'external identity user is not an active organization member'); END""",
    )
    for statement in statements:
        connection.execute(sa.text(statement))


def _create_profile_evidence_table(connection: Any) -> None:
    """Add the normalized profile-evidence projection to existing databases."""
    connection.execute(sa.text(
        """CREATE TABLE IF NOT EXISTS profile_evidence_items (
        id VARCHAR(64) PRIMARY KEY,
        owner_public_id VARCHAR(64) REFERENCES users(public_id) ON DELETE CASCADE,
        legacy_student_id VARCHAR(64) NOT NULL,
        legacy_key VARCHAR(64) NOT NULL,
        source_type VARCHAR(64) NOT NULL,
        source_object_id VARCHAR(64),
        features JSON,
        weight FLOAT NOT NULL DEFAULT 0,
        confidence FLOAT NOT NULL DEFAULT 0,
        evidence_summary TEXT DEFAULT '',
        observed_at DATETIME,
        status VARCHAR(32) NOT NULL DEFAULT 'active',
        evidence_version VARCHAR(32) NOT NULL DEFAULT '1',
        trace_id VARCHAR(64),
        created_at DATETIME,
        updated_at DATETIME,
        CONSTRAINT uq_profile_evidence_legacy_key UNIQUE (legacy_student_id, legacy_key),
        CONSTRAINT ck_profile_evidence_weight CHECK (weight >= 0 AND weight <= 1),
        CONSTRAINT ck_profile_evidence_confidence CHECK (confidence >= 0 AND confidence <= 1),
        CONSTRAINT ck_profile_evidence_status CHECK (
          status IN ('active','superseded','archived','legacy_unresolved'))
        )"""
    ))
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_profile_evidence_items_owner_public_id ON profile_evidence_items(owner_public_id)",
        "CREATE INDEX IF NOT EXISTS ix_profile_evidence_items_legacy_student_id ON profile_evidence_items(legacy_student_id)",
        "CREATE INDEX IF NOT EXISTS ix_profile_evidence_items_source_type ON profile_evidence_items(source_type)",
        "CREATE INDEX IF NOT EXISTS ix_profile_evidence_items_source_object_id ON profile_evidence_items(source_object_id)",
        "CREATE INDEX IF NOT EXISTS ix_profile_evidence_items_observed_at ON profile_evidence_items(observed_at)",
        "CREATE INDEX IF NOT EXISTS ix_profile_evidence_items_status ON profile_evidence_items(status)",
        "CREATE INDEX IF NOT EXISTS ix_profile_evidence_items_trace_id ON profile_evidence_items(trace_id)",
    ):
        connection.execute(sa.text(statement))


MIGRATIONS = (
    Migration("20260723_001", "M1 unified identity and domain-object baseline", _record_m1_foundation),
    Migration("20260723_002", "M1 role and lifecycle database integrity triggers", _install_integrity_triggers),
    Migration("20260723_003", "M1 immutable evaluation and enterprise tenant integrity", _install_m1_governance_triggers),
    Migration("20260723_004", "M1 normalized profile evidence projection", _create_profile_evidence_table),
)


def apply_registered_migrations(bind: Any) -> list[str]:
    applied_now: list[str] = []
    with bind.begin() as connection:
        connection.execute(sa.text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version VARCHAR(64) PRIMARY KEY, description VARCHAR(256) NOT NULL, "
            "checksum VARCHAR(64) NOT NULL, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        ))
        rows = connection.execute(sa.text("SELECT version, checksum FROM schema_migrations")).fetchall()
        applied = {version: checksum for version, checksum in rows}
        for migration in MIGRATIONS:
            if migration.version in applied:
                if applied[migration.version] != migration.checksum:
                    raise RuntimeError(f"Migration history changed: {migration.version}")
                continue
            migration.apply(connection)
            connection.execute(
                sa.text(
                    "INSERT INTO schema_migrations(version, description, checksum) "
                    "VALUES (:version, :description, :checksum)"
                ),
                {
                    "version": migration.version,
                    "description": migration.description,
                    "checksum": migration.checksum,
                },
            )
            applied_now.append(migration.version)
    return applied_now
