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


def _install_m4_evaluation_integrity(connection: Any) -> None:
    required = {"evaluation_annotations", "evaluation_reports"}
    actual = set(sa.inspect(connection).get_table_names())
    missing = sorted(required - actual)
    if missing:
        raise RuntimeError(f"M4 evaluation migration missing tables: {missing}")
    for statement in (
        """CREATE TRIGGER IF NOT EXISTS trg_evaluation_annotation_immutable_update
        BEFORE UPDATE ON evaluation_annotations BEGIN
        SELECT RAISE(ABORT, 'evaluation annotation is immutable'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_evaluation_annotation_immutable_delete
        BEFORE DELETE ON evaluation_annotations BEGIN
        SELECT RAISE(ABORT, 'evaluation annotation is immutable'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_evaluation_report_immutable_update
        BEFORE UPDATE ON evaluation_reports BEGIN
        SELECT RAISE(ABORT, 'evaluation report is immutable'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_evaluation_report_immutable_delete
        BEFORE DELETE ON evaluation_reports BEGIN
        SELECT RAISE(ABORT, 'evaluation report is immutable'); END""",
    ):
        connection.execute(sa.text(statement))


def _install_m5_model_call_integrity(connection: Any) -> None:
    if "model_calls" not in set(sa.inspect(connection).get_table_names()):
        raise RuntimeError("M5 model gateway migration missing table: model_calls")
    for statement in (
        """CREATE TRIGGER IF NOT EXISTS trg_model_call_state_insert BEFORE INSERT ON model_calls
        WHEN NEW.status NOT IN ('running','completed','failed')
          OR NEW.input_tokens < 0 OR NEW.output_tokens < 0 OR NEW.retry_count < 0
          OR NEW.estimated_cost < 0 OR NEW.duration_ms < 0
        BEGIN SELECT RAISE(ABORT, 'invalid model call state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_model_call_state_update
        BEFORE UPDATE OF status,input_tokens,output_tokens,retry_count,estimated_cost,duration_ms ON model_calls
        WHEN NEW.status NOT IN ('running','completed','failed')
          OR NEW.input_tokens < 0 OR NEW.output_tokens < 0 OR NEW.retry_count < 0
          OR NEW.estimated_cost < 0 OR NEW.duration_ms < 0
        BEGIN SELECT RAISE(ABORT, 'invalid model call state'); END""",
    ):
        connection.execute(sa.text(statement))


def _add_m5_model_call_course_scope(connection: Any) -> None:
    inspector = sa.inspect(connection)
    if "model_calls" not in set(inspector.get_table_names()):
        raise RuntimeError("M5 model policy migration missing table: model_calls")
    columns = {column["name"] for column in inspector.get_columns("model_calls")}
    if "course_id" not in columns:
        connection.execute(sa.text(
            "ALTER TABLE model_calls ADD COLUMN course_id VARCHAR(128) REFERENCES courses(id) ON DELETE SET NULL"
        ))
    connection.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_model_calls_course_id ON model_calls(course_id)"
    ))


def _install_m5_atomic_quota_buckets(connection: Any) -> None:
    if "model_quota_buckets" not in set(sa.inspect(connection).get_table_names()):
        raise RuntimeError("M5 quota migration missing table: model_quota_buckets")
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_model_quota_scope_type ON model_quota_buckets(scope_type)",
        "CREATE INDEX IF NOT EXISTS ix_model_quota_utc_day ON model_quota_buckets(utc_day)",
        """CREATE TRIGGER IF NOT EXISTS trg_model_quota_values_insert BEFORE INSERT ON model_quota_buckets
        WHEN NEW.scope_type NOT IN ('user','course','model') OR NEW.call_count < 0
          OR NEW.reserved_tokens < 0 OR NEW.reserved_cost < 0
        BEGIN SELECT RAISE(ABORT, 'invalid model quota bucket'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_model_quota_values_update
        BEFORE UPDATE OF call_count,reserved_tokens,reserved_cost ON model_quota_buckets
        WHEN NEW.call_count < 0 OR NEW.reserved_tokens < 0 OR NEW.reserved_cost < 0
        BEGIN SELECT RAISE(ABORT, 'invalid model quota bucket'); END""",
    ):
        connection.execute(sa.text(statement))


def _install_m5_learning_loop_schema(connection: Any) -> None:
    connection.execute(sa.text(
        """CREATE TABLE IF NOT EXISTS learning_event_consumptions (
        id VARCHAR(64) PRIMARY KEY,
        learning_event_id VARCHAR(64) NOT NULL REFERENCES learning_events(id) ON DELETE CASCADE,
        consumer VARCHAR(64) NOT NULL,
        processor_version VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        attempt INTEGER NOT NULL DEFAULT 1,
        result JSON,
        error_code VARCHAR(64) DEFAULT '',
        created_at DATETIME,
        processed_at DATETIME,
        CONSTRAINT uq_learning_event_consumer_version UNIQUE (learning_event_id,consumer,processor_version),
        CONSTRAINT ck_learning_event_consumption_status CHECK (status IN ('pending','processed','failed')),
        CONSTRAINT ck_learning_event_consumption_attempt CHECK (attempt >= 1))"""
    ))
    inspector = sa.inspect(connection)
    required = {"plan_drafts", "learning_paths", "path_nodes", "learning_events", "learning_event_consumptions"}
    missing = sorted(required - set(inspector.get_table_names()))
    if missing:
        raise RuntimeError(f"M5 learning-loop migration missing tables: {missing}")

    additions = {
        "plan_drafts": (
            ("idempotency_key", "VARCHAR(128)"),
            ("current_version_id", "VARCHAR(64)"),
            ("confirmed_version_id", "VARCHAR(64)"),
            ("confirmed_at", "DATETIME"),
        ),
        "learning_paths": (
            ("supersedes_path_id", "VARCHAR(64)"),
            ("lock_version", "INTEGER NOT NULL DEFAULT 1"),
            ("paused_at", "DATETIME"),
            ("archived_at", "DATETIME"),
            ("updated_at", "DATETIME"),
        ),
        "path_nodes": (
            ("node_key", "VARCHAR(128) NOT NULL DEFAULT ''"),
            ("is_extension", "BOOLEAN NOT NULL DEFAULT 0"),
            ("resource_status", "VARCHAR(32) NOT NULL DEFAULT 'existing'"),
            ("estimate_min_minutes", "INTEGER NOT NULL DEFAULT 1"),
            ("estimate_max_minutes", "INTEGER NOT NULL DEFAULT 1"),
            ("actual_minutes", "INTEGER"),
            ("blocked_reason", "VARCHAR(256) DEFAULT ''"),
        ),
        "learning_events": (
            ("idempotency_key", "VARCHAR(128)"),
            ("source", "VARCHAR(64) NOT NULL DEFAULT 'legacy'"),
        ),
    }
    for table, columns in additions.items():
        existing = {column["name"] for column in sa.inspect(connection).get_columns(table)}
        for name, definition in columns:
            if name not in existing:
                connection.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))

    statements = (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_plan_owner_idempotency ON plan_drafts(owner_public_id,idempotency_key) WHERE idempotency_key IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_plan_current_version ON plan_drafts(current_version_id)",
        "CREATE INDEX IF NOT EXISTS ix_plan_confirmed_version ON plan_drafts(confirmed_version_id)",
        "CREATE INDEX IF NOT EXISTS ix_path_supersedes ON learning_paths(supersedes_path_id)",
        "CREATE INDEX IF NOT EXISTS ix_path_node_key ON path_nodes(node_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_event_owner_idempotency ON learning_events(owner_public_id,idempotency_key) WHERE idempotency_key IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_learning_event_consumptions_event ON learning_event_consumptions(learning_event_id)",
        "CREATE INDEX IF NOT EXISTS ix_learning_event_consumptions_status ON learning_event_consumptions(status)",
        """CREATE TRIGGER IF NOT EXISTS trg_m5_plan_state_insert BEFORE INSERT ON plan_drafts
        WHEN NEW.status NOT IN ('draft','replan_pending','confirmed','abandoned') OR NEW.lock_version < 1
        BEGIN SELECT RAISE(ABORT, 'invalid M5 plan state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_m5_plan_state_update BEFORE UPDATE OF status,lock_version ON plan_drafts
        WHEN NEW.status NOT IN ('draft','replan_pending','confirmed','abandoned') OR NEW.lock_version < 1
        BEGIN SELECT RAISE(ABORT, 'invalid M5 plan state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_m5_path_state_insert BEFORE INSERT ON learning_paths
        WHEN NEW.status NOT IN ('active','paused','completed','archived') OR NEW.lock_version < 1
        BEGIN SELECT RAISE(ABORT, 'invalid M5 path state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_m5_path_state_update BEFORE UPDATE OF status,lock_version ON learning_paths
        WHEN NEW.status NOT IN ('active','paused','completed','archived') OR NEW.lock_version < 1
        BEGIN SELECT RAISE(ABORT, 'invalid M5 path state'); END""",
    )
    for statement in statements:
        connection.execute(sa.text(statement))


def _install_m5_tutor_context_schema(connection: Any) -> None:
    connection.execute(sa.text(
        """CREATE TABLE IF NOT EXISTS tutor_context_sessions (
        id VARCHAR(64) PRIMARY KEY,
        owner_public_id VARCHAR(64) NOT NULL REFERENCES users(public_id) ON DELETE CASCADE,
        course_id VARCHAR(128) REFERENCES courses(id) ON DELETE SET NULL,
        idempotency_key VARCHAR(128) NOT NULL,
        context_mode VARCHAR(32) NOT NULL DEFAULT 'current_resource',
        primary_object_type VARCHAR(32) NOT NULL,
        primary_object_id VARCHAR(64) NOT NULL,
        context_snapshot JSON NOT NULL,
        teaching_style VARCHAR(32) NOT NULL DEFAULT 'progressive',
        explanation_depth VARCHAR(16) NOT NULL DEFAULT 'standard',
        guidance_mode VARCHAR(16) NOT NULL DEFAULT 'socratic',
        status VARCHAR(16) NOT NULL DEFAULT 'active',
        lock_version INTEGER NOT NULL DEFAULT 1,
        last_used_at DATETIME,
        archived_at DATETIME,
        created_at DATETIME,
        updated_at DATETIME,
        CONSTRAINT uq_tutor_context_owner_idempotency UNIQUE (owner_public_id,idempotency_key),
        CONSTRAINT ck_tutor_context_mode CHECK (
          context_mode IN ('current_resource','current_course','personal_resources','external_allowed')),
        CONSTRAINT ck_tutor_context_status CHECK (status IN ('active','archived')),
        CONSTRAINT ck_tutor_context_lock_version CHECK (lock_version >= 1))"""
    ))
    if "tutor_context_sessions" not in set(sa.inspect(connection).get_table_names()):
        raise RuntimeError("M5 tutor context migration missing table: tutor_context_sessions")
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_tutor_context_owner_last_used ON tutor_context_sessions(owner_public_id,last_used_at)",
        "CREATE INDEX IF NOT EXISTS ix_tutor_context_primary_object ON tutor_context_sessions(primary_object_type,primary_object_id)",
        """CREATE TRIGGER IF NOT EXISTS trg_tutor_context_state_insert BEFORE INSERT ON tutor_context_sessions
        WHEN NEW.context_mode NOT IN ('current_resource','current_course','personal_resources','external_allowed')
          OR NEW.status NOT IN ('active','archived') OR NEW.lock_version < 1
        BEGIN SELECT RAISE(ABORT, 'invalid tutor context state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_tutor_context_state_update
        BEFORE UPDATE OF context_mode,status,lock_version ON tutor_context_sessions
        WHEN NEW.context_mode NOT IN ('current_resource','current_course','personal_resources','external_allowed')
          OR NEW.status NOT IN ('active','archived') OR NEW.lock_version < 1
        BEGIN SELECT RAISE(ABORT, 'invalid tutor context state'); END""",
    ):
        connection.execute(sa.text(statement))


def _install_m7_integration_outbox(connection: Any) -> None:
    connection.execute(sa.text(
        """CREATE TABLE IF NOT EXISTS integration_deliveries (
        id VARCHAR(64) PRIMARY KEY, organization_id VARCHAR(64) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        adapter_type VARCHAR(32) NOT NULL, adapter_version VARCHAR(32) NOT NULL, destination_key VARCHAR(128) NOT NULL,
        idempotency_key VARCHAR(128) NOT NULL, source_object_type VARCHAR(64) NOT NULL, source_object_id VARCHAR(64) NOT NULL,
        payload JSON NOT NULL, payload_hash VARCHAR(64) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0, last_error_code VARCHAR(64) DEFAULT '', next_attempt_at DATETIME,
        delivered_at DATETIME, created_at DATETIME, updated_at DATETIME,
        CONSTRAINT uq_integration_delivery_idempotency UNIQUE (organization_id,destination_key,idempotency_key),
        CONSTRAINT ck_integration_delivery_adapter CHECK (adapter_type IN ('xapi','webhook','lms','hr')),
        CONSTRAINT ck_integration_delivery_status CHECK (status IN ('pending','delivering','delivered','failed','dead_letter')),
        CONSTRAINT ck_integration_delivery_attempt CHECK (attempt_count >= 0))"""
    ))
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_integration_deliveries_status_next ON integration_deliveries(status,next_attempt_at)",
        "CREATE INDEX IF NOT EXISTS ix_integration_deliveries_source ON integration_deliveries(source_object_type,source_object_id)",
    ):
        connection.execute(sa.text(statement))


MIGRATIONS = (
    Migration("20260723_001", "M1 unified identity and domain-object baseline", _record_m1_foundation),
    Migration("20260723_002", "M1 role and lifecycle database integrity triggers", _install_integrity_triggers),
    Migration("20260723_003", "M1 immutable evaluation and enterprise tenant integrity", _install_m1_governance_triggers),
    Migration("20260723_004", "M1 normalized profile evidence projection", _create_profile_evidence_table),
    Migration("20260727_005", "M4 immutable evaluation annotations and reports", _install_m4_evaluation_integrity),
    Migration("20260727_006", "M5 model gateway call trace integrity", _install_m5_model_call_integrity),
    Migration("20260727_007", "M5 model call course-scoped policy accounting", _add_m5_model_call_course_scope),
    Migration("20260727_008", "M5 atomic daily model quota buckets", _install_m5_atomic_quota_buckets),
    Migration("20260727_009", "M5 versioned plans paths and replayable learning events", _install_m5_learning_loop_schema),
    Migration("20260727_010", "M5 restorable tutor resource contexts", _install_m5_tutor_context_schema),
    Migration("20260728_011", "M7 versioned integration delivery outbox", _install_m7_integration_outbox),
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
