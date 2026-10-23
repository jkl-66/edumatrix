"""Small versioned migration registry for the existing SQLite deployment.

The legacy additive migration remains as migration zero. Every M1+ change is
registered here with a stable checksum so startup can detect edited history.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable, Any

import sqlalchemy as sa

from app.database import (
    DBAssessmentExam, DBAssessmentExamItem, DBAssessmentExamReport,
    DBAssessmentExamResponse, DBAssessmentExamResponseDraft, DBAssessmentExamSitting,
    DBAssessmentExamVersion,
    DBAssessmentReviewCase,
    DBSpeechSession, DBSpeechSegment,
    DBMediaContextResource, DBMediaReadingPosition, DBMediaConversation, DBMediaMessage,
    DBTeachingClass, DBTeachingGroup, DBTeachingClassMember, DBTeachingTask, DBCourseWithdrawal,
    DBTeachingAnalyticsReport,
    DBContentReviewCase, DBContentReviewDecision,
    DBCertification, DBCertificationLifecycleEvent, DBRetrainingTask, DBLocalNotification,
    DBMultilevelReviewCase, DBMultilevelReviewDecision,
    DBJobStandardImpactPreview, DBJobStandardImpactConfirmation,
    DBEnterpriseRiskReport, DBEnterpriseRiskDecision,
    DBCourseShareRelease, DBCourseDerivedCopy, DBCourseShareDecision,
    DBMarketplaceListing, DBMarketplaceDecision, DBMarketplaceReport, DBMarketplaceAcquisition,
    DBMarketplacePersonalCopy,
    DBMarketplaceComment, DBMarketplaceCommentEvent, DBMarketplaceCommentReport,
    DBMarketplaceFavorite, DBMarketplaceReview, DBMarketplaceReviewEvent,
    DBMarketplaceImpactEvent, DBMarketplaceImpactNotification,
    DBMarketplaceFork, DBMarketplaceForkVersion, DBMarketplaceForkDecision,
    DBMarketplaceRecommendationRun, DBMarketplaceRecommendationResult,
    DBOrganizationResourceListing, DBOrganizationResourceAcquisition,
    DBSpatialWorkspace, DBSpatialLayoutVersion,
    DBPluginRegistration, DBPluginLifecycleEvent,
    DBVideoAsset, DBVideoAssetVersion, DBWrongQuestionVideoLink, DBChapterVideoLink,
    DBVideoPracticeSet, DBVideoPracticeVersion, DBVideoWatchProgress, DBVideoPracticeAttemptLink,
    DBVideoPracticeLabLink,
    DBTeachingAnimation, DBTeachingAnimationVersion,
    DBWebDeck, DBWebSlide, DBWebDeckVersion,
    DBLocalAdapterSession, DBLocalAdapterEvent,
    DBResourceBundle, DBResourceBundleVersion, DBResourceBundleItem,
    DBFlashcard, DBFlashcardVersion,
    DBLocalSSOProvider, DBLocalSSOMappingVersion, DBLocalSSOSession, DBLocalSSOEvent,
    DBHRFieldMappingVersion, DBHRSyncBatch, DBHREmployeeProjection, DBHRSyncRecord,
    DBLocalLMSConnection, DBLMSCatalogExport, DBLMSAssignmentExchange,
    DBLMSGradeSummary, DBLMSSyncEvent,
    DBLocalLRSStatement, DBIntegrationDeliveryEvent, DBCmi5Session, DBCmi5SessionEvent,
    DBLocalWebhookEndpoint, DBWebhookEvent, DBWebhookAcceptedNonce, DBWebhookReceipt,
    DBIntegrationReconciliationRun, DBIntegrationRepairDecision,
    DBIntegrationFaultDrill, DBIntegrationFaultDrillStep,
    DBCompetitionJourneyRun, DBCompetitionJourneyVisit, DBMarketplaceJourneySearchVerification,
    DBVideoProject, DBVideoScriptVersion, DBVideoRenderTask, DBVideoOutputVersion,
    DBLegacyObjectMigration, DBOnboardingPersonalEvidence, DBDiagnosticBlueprint,
    DBDiagnosticSession, DBDiagnosticResponseDraft, DBDiagnosticReport,
    DBDocumentReadingPosition, DBDocumentSelection, DBWebSourceCandidate,
    DBChatConversation, DBChatAttachment, DBChatMessage,
)


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


def _install_f2_learning_event_protocol(connection: Any) -> None:
    if "learning_events" not in set(sa.inspect(connection).get_table_names()):
        raise RuntimeError("F2 learning event migration missing table: learning_events")
    additions = (
        ("action", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("context_ref", "JSON"),
        ("evidence_strength", "FLOAT NOT NULL DEFAULT 0.0"),
        ("evidence_status", "VARCHAR(16) NOT NULL DEFAULT 'none'"),
        ("evidence_reason", "VARCHAR(256) DEFAULT ''"),
        ("mastery_eligible", "BOOLEAN NOT NULL DEFAULT 0"),
        ("completion_effect", "VARCHAR(16) NOT NULL DEFAULT 'none'"),
        ("payload_version", "VARCHAR(32) NOT NULL DEFAULT '1'"),
    )
    existing = {column["name"] for column in sa.inspect(connection).get_columns("learning_events")}
    for name, definition in additions:
        if name not in existing:
            connection.execute(sa.text(f"ALTER TABLE learning_events ADD COLUMN {name} {definition}"))
    connection.execute(sa.text(
        "UPDATE learning_events SET action = event_type WHERE action IS NULL OR action = ''"
    ))
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_learning_events_action ON learning_events(action)",
        "CREATE INDEX IF NOT EXISTS ix_learning_events_evidence_status ON learning_events(evidence_status)",
        "CREATE INDEX IF NOT EXISTS ix_learning_events_mastery_eligible ON learning_events(mastery_eligible)",
        """CREATE TRIGGER IF NOT EXISTS trg_f2_learning_event_protocol_insert
        BEFORE INSERT ON learning_events
        WHEN NEW.evidence_strength < 0 OR NEW.evidence_strength > 1
          OR NEW.evidence_status NOT IN ('none','accepted','rejected')
          OR NEW.completion_effect NOT IN ('none','progress','complete')
          OR (NEW.mastery_eligible = 1 AND (NEW.evidence_status != 'accepted' OR NEW.evidence_strength <= 0))
          OR (NEW.evidence_status = 'accepted' AND NEW.mastery_eligible != 1)
        BEGIN SELECT RAISE(ABORT, 'invalid F2 learning event protocol'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_f2_learning_event_protocol_update
        BEFORE UPDATE OF evidence_strength,evidence_status,mastery_eligible,completion_effect ON learning_events
        WHEN NEW.evidence_strength < 0 OR NEW.evidence_strength > 1
          OR NEW.evidence_status NOT IN ('none','accepted','rejected')
          OR NEW.completion_effect NOT IN ('none','progress','complete')
          OR (NEW.mastery_eligible = 1 AND (NEW.evidence_status != 'accepted' OR NEW.evidence_strength <= 0))
          OR (NEW.evidence_status = 'accepted' AND NEW.mastery_eligible != 1)
        BEGIN SELECT RAISE(ABORT, 'invalid F2 learning event protocol'); END""",
    ):
        connection.execute(sa.text(statement))


def _install_f2_replayable_aggregation(connection: Any) -> None:
    tables = set(sa.inspect(connection).get_table_names())
    missing = sorted({"learning_events", "wrong_questions"} - tables)
    if missing:
        raise RuntimeError(f"F2 replayable aggregation migration missing tables: {missing}")
    columns = {
        column["name"] for column in sa.inspect(connection).get_columns("wrong_questions")
    }
    if "source_event_id" not in columns:
        connection.execute(sa.text(
            "ALTER TABLE wrong_questions ADD COLUMN source_event_id VARCHAR(64) "
            "REFERENCES learning_events(id) ON DELETE SET NULL"
        ))
    connection.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_wrong_questions_source_event_id "
        "ON wrong_questions(source_event_id) WHERE source_event_id IS NOT NULL"
    ))


def _install_f2_legacy_object_migration(connection: Any) -> None:
    DBLegacyObjectMigration.__table__.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_legacy_migration_owner_status ON legacy_object_migrations(owner_public_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_legacy_migration_source ON legacy_object_migrations(old_type,old_id)",
        """CREATE TRIGGER IF NOT EXISTS trg_legacy_object_migration_insert
        BEFORE INSERT ON legacy_object_migrations
        WHEN NEW.status NOT IN ('pending','mapped','copied','verified','failed','rolled_back')
        BEGIN SELECT RAISE(ABORT, 'invalid legacy object migration state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_legacy_object_migration_update
        BEFORE UPDATE OF status ON legacy_object_migrations
        WHEN NEW.status NOT IN ('pending','mapped','copied','verified','failed','rolled_back')
        BEGIN SELECT RAISE(ABORT, 'invalid legacy object migration state'); END""",
    ):
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


def _install_m5_assessment_schema(connection: Any) -> None:
    required = {
        "assessment_questions", "assessment_question_versions",
        "assessment_attempts", "misconception_reviews",
    }
    actual = set(sa.inspect(connection).get_table_names())
    missing = sorted(required - actual)
    if missing:
        raise RuntimeError(f"M5 assessment migration missing tables: {missing}")
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_assessment_attempt_owner_time ON assessment_attempts(owner_public_id,submitted_at)",
        "CREATE INDEX IF NOT EXISTS ix_misconception_owner_status ON misconception_reviews(owner_public_id,status)",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_question_version_no_update BEFORE UPDATE ON assessment_question_versions BEGIN SELECT RAISE(ABORT, 'assessment question version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_question_version_no_delete BEFORE DELETE ON assessment_question_versions BEGIN SELECT RAISE(ABORT, 'assessment question version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_attempt_no_update BEFORE UPDATE ON assessment_attempts BEGIN SELECT RAISE(ABORT, 'assessment attempt is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_attempt_no_delete BEFORE DELETE ON assessment_attempts BEGIN SELECT RAISE(ABORT, 'assessment attempt is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_m5_retest_schedule(connection: Any) -> None:
    if "assessment_retest_tasks" not in set(sa.inspect(connection).get_table_names()):
        raise RuntimeError("M5 retest migration missing table: assessment_retest_tasks")
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_assessment_retest_owner_due ON assessment_retest_tasks(owner_public_id,due_at)",
        "CREATE INDEX IF NOT EXISTS ix_assessment_retest_owner_status ON assessment_retest_tasks(owner_public_id,status)",
        """CREATE TRIGGER IF NOT EXISTS trg_assessment_retest_state_insert BEFORE INSERT ON assessment_retest_tasks
        WHEN NEW.status NOT IN ('scheduled','due','completed','cancelled')
        BEGIN SELECT RAISE(ABORT, 'invalid assessment retest state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_assessment_retest_state_update BEFORE UPDATE OF status ON assessment_retest_tasks
        WHEN NEW.status NOT IN ('scheduled','due','completed','cancelled')
        BEGIN SELECT RAISE(ABORT, 'invalid assessment retest state'); END""",
    ):
        connection.execute(sa.text(statement))


def _install_next_cost_worker_schema(connection: Any) -> None:
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    required = {"model_calls", "model_price_versions", "worker_leases"}
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(f"NEXT cost/worker migration missing tables: {missing}")
    columns = {column["name"] for column in inspector.get_columns("model_calls")}
    additions = {
        "pricing_version": "VARCHAR(64) NOT NULL DEFAULT 'unpriced'",
        "cost_currency": "VARCHAR(8) NOT NULL DEFAULT 'USD'",
        "cost_basis": "VARCHAR(32) NOT NULL DEFAULT 'estimate'",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(sa.text(f"ALTER TABLE model_calls ADD COLUMN {name} {definition}"))
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_model_price_provider_model ON model_price_versions(provider,model)",
        "CREATE INDEX IF NOT EXISTS ix_worker_lease_status_until ON worker_leases(status,leased_until)",
        """CREATE TRIGGER IF NOT EXISTS trg_worker_lease_state_insert BEFORE INSERT ON worker_leases
        WHEN NEW.status NOT IN ('active','released','expired','cancelled') OR NEW.attempt < 1
        BEGIN SELECT RAISE(ABORT, 'invalid worker lease'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_worker_lease_state_update BEFORE UPDATE OF status,attempt ON worker_leases
        WHEN NEW.status NOT IN ('active','released','expired','cancelled') OR NEW.attempt < 1
        BEGIN SELECT RAISE(ABORT, 'invalid worker lease'); END""",
    ):
        connection.execute(sa.text(statement))


def _install_next_document_migration_schema(connection: Any) -> None:
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    required = {"source_documents", "source_refs"}
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(f"NEXT document migration missing tables: {missing}")
    additions = {
        "source_documents": (
            ("source_sha256", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("processed_sha256", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("parser_metadata", "JSON"),
            ("parse_warnings", "JSON"),
            ("processing_error_code", "VARCHAR(64) DEFAULT ''"),
        ),
        "source_refs": (
            ("location_kind", "VARCHAR(32) NOT NULL DEFAULT 'section'"),
            ("location_index", "INTEGER"),
            ("location_label", "VARCHAR(256) DEFAULT ''"),
            ("location_metadata", "JSON"),
        ),
    }
    for table, columns in additions.items():
        existing = {column["name"] for column in sa.inspect(connection).get_columns(table)}
        for name, definition in columns:
            if name not in existing:
                connection.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
    connection.execute(sa.text(
        "UPDATE source_documents SET source_sha256=content_hash "
        "WHERE source_sha256 IS NULL OR source_sha256=''"
    ))
    connection.execute(sa.text(
        "UPDATE source_documents SET processed_sha256=content_hash "
        "WHERE processed_sha256 IS NULL OR processed_sha256=''"
    ))
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_source_documents_source_sha256 ON source_documents(source_sha256)",
        "CREATE INDEX IF NOT EXISTS ix_source_documents_processed_sha256 ON source_documents(processed_sha256)",
        "CREATE INDEX IF NOT EXISTS ix_source_refs_location_kind ON source_refs(location_kind)",
        """CREATE TRIGGER IF NOT EXISTS trg_source_document_processing_insert
        BEFORE INSERT ON source_documents
        WHEN NEW.processing_status NOT IN ('pending','ready','failed')
        BEGIN SELECT RAISE(ABORT, 'invalid source document processing state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_source_document_processing_update
        BEFORE UPDATE OF processing_status ON source_documents
        WHEN NEW.processing_status NOT IN ('pending','ready','failed')
        BEGIN SELECT RAISE(ABORT, 'invalid source document processing state'); END""",
    ):
        connection.execute(sa.text(statement))


def _install_next_memory_governance_schema(connection: Any) -> None:
    inspector = sa.inspect(connection)
    if "memory_items" not in set(inspector.get_table_names()):
        raise RuntimeError("NEXT memory governance migration missing table: memory_items")
    columns = {column["name"] for column in inspector.get_columns("memory_items")}
    additions = {
        "memory_key": "VARCHAR(192) NOT NULL DEFAULT ''",
        "title": "VARCHAR(256) NOT NULL DEFAULT ''",
        "lock_version": "INTEGER NOT NULL DEFAULT 1",
        "withdrawn_at": "DATETIME",
        "withdrawal_reason": "TEXT DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in columns:
            connection.execute(sa.text(f"ALTER TABLE memory_items ADD COLUMN {name} {definition}"))
    connection.execute(sa.text(
        "UPDATE memory_items SET memory_key='legacy:' || id WHERE memory_key IS NULL OR memory_key=''"
    ))
    connection.execute(sa.text(
        """CREATE TABLE IF NOT EXISTS memory_subscriptions (
        id VARCHAR(64) PRIMARY KEY,
        owner_public_id VARCHAR(64) NOT NULL REFERENCES users(public_id) ON DELETE CASCADE,
        subscriber_type VARCHAR(32) NOT NULL DEFAULT 'tutor',
        subscriber_key VARCHAR(128) NOT NULL DEFAULT 'default',
        profile_fields JSON NOT NULL,
        memory_types JSON NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'active',
        lock_version INTEGER NOT NULL DEFAULT 1,
        last_synced_at DATETIME,
        revoked_at DATETIME,
        revoke_reason TEXT DEFAULT '',
        created_at DATETIME,
        updated_at DATETIME,
        CONSTRAINT uq_memory_subscription_owner_consumer UNIQUE (owner_public_id,subscriber_type,subscriber_key),
        CONSTRAINT ck_memory_subscription_status CHECK (status IN ('active','revoked')),
        CONSTRAINT ck_memory_subscription_lock_version CHECK (lock_version >= 1))"""
    ))
    for statement in (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_owner_key ON memory_items(owner_public_id,memory_key)",
        "CREATE INDEX IF NOT EXISTS ix_memory_items_withdrawn_at ON memory_items(withdrawn_at)",
        "CREATE INDEX IF NOT EXISTS ix_memory_subscriptions_owner ON memory_subscriptions(owner_public_id)",
        "CREATE INDEX IF NOT EXISTS ix_memory_subscriptions_status ON memory_subscriptions(status)",
        """CREATE TRIGGER IF NOT EXISTS trg_memory_item_state_insert BEFORE INSERT ON memory_items
        WHEN NEW.status NOT IN ('active','withdrawn','archived') OR NEW.lock_version < 1
          OR NEW.confidence < 0 OR NEW.confidence > 1
        BEGIN SELECT RAISE(ABORT, 'invalid memory item state'); END""",
        """CREATE TRIGGER IF NOT EXISTS trg_memory_item_state_update
        BEFORE UPDATE OF status,lock_version,confidence ON memory_items
        WHEN NEW.status NOT IN ('active','withdrawn','archived') OR NEW.lock_version < 1
          OR NEW.confidence < 0 OR NEW.confidence > 1
        BEGIN SELECT RAISE(ABORT, 'invalid memory item state'); END""",
    ):
        connection.execute(sa.text(statement))


def _install_next_assessment_complete_schema(connection: Any) -> None:
    connection.execute(sa.text(
        """CREATE TABLE IF NOT EXISTS assessment_grading_results (
        id VARCHAR(64) PRIMARY KEY,
        attempt_id VARCHAR(64) NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
        owner_public_id VARCHAR(64) NOT NULL REFERENCES users(public_id) ON DELETE CASCADE,
        grader_type VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'completed',
        rubric_version VARCHAR(64) NOT NULL DEFAULT 'deterministic-v1',
        rubric_snapshot JSON NOT NULL,
        criterion_results JSON NOT NULL,
        score FLOAT,
        correct BOOLEAN,
        confidence FLOAT,
        evidence JSON NOT NULL,
        feedback TEXT DEFAULT '',
        improvement_advice JSON NOT NULL,
        trace_id VARCHAR(64) NOT NULL DEFAULT '',
        content_hash VARCHAR(64) NOT NULL,
        created_by_public_id VARCHAR(64) REFERENCES users(public_id) ON DELETE SET NULL,
        created_at DATETIME,
        CONSTRAINT uq_assessment_grade_attempt_rubric UNIQUE (attempt_id,grader_type,rubric_version),
        CONSTRAINT ck_assessment_grade_type CHECK (grader_type IN ('deterministic','ai','code','human')),
        CONSTRAINT ck_assessment_grade_status CHECK (status IN ('completed','failed','needs_review')),
        CONSTRAINT ck_assessment_grade_score CHECK (score IS NULL OR (score >= 0.0 AND score <= 1.0)),
        CONSTRAINT ck_assessment_grade_confidence CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)))"""
    ))
    connection.execute(sa.text(
        """CREATE TABLE IF NOT EXISTS assessment_ability_states (
        id VARCHAR(64) PRIMARY KEY,
        owner_public_id VARCHAR(64) NOT NULL REFERENCES users(public_id) ON DELETE CASCADE,
        course_scope VARCHAR(128) NOT NULL DEFAULT '__global__',
        theta JSON NOT NULL,
        theta_std JSON NOT NULL,
        theta_cov JSON NOT NULL,
        response_count INTEGER NOT NULL DEFAULT 0,
        lock_version INTEGER NOT NULL DEFAULT 1,
        last_attempt_id VARCHAR(64) REFERENCES assessment_attempts(id) ON DELETE SET NULL,
        updated_at DATETIME,
        CONSTRAINT uq_assessment_ability_owner_course UNIQUE (owner_public_id,course_scope),
        CONSTRAINT ck_assessment_ability_versions CHECK (response_count >= 0 AND lock_version >= 1))"""
    ))
    connection.execute(sa.text(
        """CREATE TABLE IF NOT EXISTS assessment_selection_traces (
        id VARCHAR(64) PRIMARY KEY,
        owner_public_id VARCHAR(64) NOT NULL REFERENCES users(public_id) ON DELETE CASCADE,
        course_scope VARCHAR(128) NOT NULL DEFAULT '__global__',
        selected_question_version_id VARCHAR(64) NOT NULL REFERENCES assessment_question_versions(id) ON DELETE RESTRICT,
        algorithm_version VARCHAR(64) NOT NULL DEFAULT 'mirt-d-optimal-v1',
        ability_before JSON NOT NULL,
        candidate_metrics JSON NOT NULL,
        excluded_version_ids JSON NOT NULL,
        trace_hash VARCHAR(64) NOT NULL,
        created_at DATETIME)"""
    ))
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_assessment_grade_owner ON assessment_grading_results(owner_public_id)",
        "CREATE INDEX IF NOT EXISTS ix_assessment_grade_attempt ON assessment_grading_results(attempt_id)",
        "CREATE INDEX IF NOT EXISTS ix_assessment_ability_owner ON assessment_ability_states(owner_public_id)",
        "CREATE INDEX IF NOT EXISTS ix_assessment_selection_owner ON assessment_selection_traces(owner_public_id)",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_grade_no_update BEFORE UPDATE ON assessment_grading_results BEGIN SELECT RAISE(ABORT, 'assessment grading result is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_grade_no_delete BEFORE DELETE ON assessment_grading_results BEGIN SELECT RAISE(ABORT, 'assessment grading result is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_selection_no_update BEFORE UPDATE ON assessment_selection_traces BEGIN SELECT RAISE(ABORT, 'assessment selection trace is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_selection_no_delete BEFORE DELETE ON assessment_selection_traces BEGIN SELECT RAISE(ABORT, 'assessment selection trace is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _allow_pending_assessment_scores(connection: Any) -> None:
    """Allow subjective attempts to remain scoreless until AI grading completes."""
    if connection.dialect.name == "postgresql":
        connection.execute(sa.text(
            "ALTER TABLE assessment_attempts ALTER COLUMN score DROP NOT NULL"
        ))
        return
    if connection.dialect.name != "sqlite":
        return
    row = connection.execute(sa.text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='assessment_attempts'"
    )).scalar()
    if not row or not re.search(r"\bscore\s+float\s+not\s+null\b", row, flags=re.IGNORECASE):
        return
    updated = re.sub(
        r"(\bscore\s+float)\s+not\s+null\b",
        r"\1",
        row,
        count=1,
        flags=re.IGNORECASE,
    )
    # SQLite has no ALTER COLUMN DROP NOT NULL.  Updating sqlite_master keeps
    # the existing table, rows, foreign keys and immutable triggers intact;
    # bumping schema_version makes the new definition visible immediately.
    connection.exec_driver_sql("PRAGMA writable_schema=ON")
    try:
        connection.execute(
            sa.text("UPDATE sqlite_master SET sql=:sql WHERE type='table' AND name='assessment_attempts'"),
            {"sql": updated},
        )
    finally:
        connection.exec_driver_sql("PRAGMA writable_schema=OFF")
    schema_version = connection.exec_driver_sql("PRAGMA schema_version").scalar()
    connection.exec_driver_sql(f"PRAGMA schema_version={int(schema_version or 0) + 1}")


def _install_next_formal_exam_schema(connection: Any) -> None:
    # SQLAlchemy creates these tables for fresh databases; this path upgrades existing SQLite files.
    for table in (
        DBAssessmentExam.__table__, DBAssessmentExamVersion.__table__, DBAssessmentExamItem.__table__,
        DBAssessmentExamSitting.__table__, DBAssessmentExamResponse.__table__,
        DBAssessmentReviewCase.__table__, DBAssessmentExamReport.__table__,
    ):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_assessment_exam_course_status ON assessment_exams(course_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_assessment_sitting_owner_status ON assessment_exam_sittings(owner_public_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_assessment_review_status ON assessment_review_cases(status,reviewer_public_id)",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_exam_version_no_update BEFORE UPDATE ON assessment_exam_versions BEGIN SELECT RAISE(ABORT, 'assessment exam version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_exam_version_no_delete BEFORE DELETE ON assessment_exam_versions BEGIN SELECT RAISE(ABORT, 'assessment exam version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_exam_item_no_update BEFORE UPDATE ON assessment_exam_items BEGIN SELECT RAISE(ABORT, 'assessment exam item is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_exam_item_no_delete BEFORE DELETE ON assessment_exam_items BEGIN SELECT RAISE(ABORT, 'assessment exam item is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_exam_response_no_update BEFORE UPDATE ON assessment_exam_responses BEGIN SELECT RAISE(ABORT, 'assessment exam response is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_exam_response_no_delete BEFORE DELETE ON assessment_exam_responses BEGIN SELECT RAISE(ABORT, 'assessment exam response is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_exam_report_no_update BEFORE UPDATE ON assessment_exam_reports BEGIN SELECT RAISE(ABORT, 'assessment exam report is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_assessment_exam_report_no_delete BEFORE DELETE ON assessment_exam_reports BEGIN SELECT RAISE(ABORT, 'assessment exam report is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_offline_speech_schema(connection: Any) -> None:
    for table in (DBSpeechSession.__table__, DBSpeechSegment.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_speech_session_owner_status ON speech_sessions(owner_public_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_speech_segment_session_start ON speech_segments(session_id,start_ms)",
        "CREATE TRIGGER IF NOT EXISTS trg_speech_segment_no_update BEFORE UPDATE ON speech_segments BEGIN SELECT RAISE(ABORT, 'speech segment is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_speech_segment_no_delete BEFORE DELETE ON speech_segments BEGIN SELECT RAISE(ABORT, 'speech segment is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_media_context_schema(connection: Any) -> None:
    for table in (
        DBMediaContextResource.__table__, DBMediaReadingPosition.__table__,
        DBMediaConversation.__table__, DBMediaMessage.__table__,
    ):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_media_resource_owner_type ON media_context_resources(owner_public_id,resource_type)",
        "CREATE INDEX IF NOT EXISTS ix_media_conversation_resource_status ON media_conversations(resource_id,status)",
        "CREATE TRIGGER IF NOT EXISTS trg_media_resource_no_update BEFORE UPDATE ON media_context_resources BEGIN SELECT RAISE(ABORT, 'media resource is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_media_message_no_update BEFORE UPDATE ON media_messages BEGIN SELECT RAISE(ABORT, 'media message is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_media_message_no_delete BEFORE DELETE ON media_messages BEGIN SELECT RAISE(ABORT, 'media message is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_video_render_schema(connection: Any) -> None:
    for table in (
        DBVideoProject.__table__, DBVideoScriptVersion.__table__,
        DBVideoRenderTask.__table__, DBVideoOutputVersion.__table__,
    ):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_video_project_owner_status ON video_projects(owner_public_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_video_render_owner_status ON video_render_tasks(owner_public_id,status)",
        "CREATE TRIGGER IF NOT EXISTS trg_video_script_no_update BEFORE UPDATE ON video_script_versions BEGIN SELECT RAISE(ABORT, 'video script version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_video_script_no_delete BEFORE DELETE ON video_script_versions BEGIN SELECT RAISE(ABORT, 'video script version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_video_output_no_update BEFORE UPDATE ON video_output_versions BEGIN SELECT RAISE(ABORT, 'video output version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_video_output_no_delete BEFORE DELETE ON video_output_versions BEGIN SELECT RAISE(ABORT, 'video output version is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_video_import_schema(connection: Any) -> None:
    for table in (DBVideoAsset.__table__, DBVideoAssetVersion.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_video_asset_owner_status ON video_assets(owner_public_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_video_asset_course_chapter ON video_assets(course_id,chapter_id)",
        "CREATE INDEX IF NOT EXISTS ix_video_asset_version_owner_hash ON video_asset_versions(owner_public_id,source_sha256,subtitle_sha256)",
        "CREATE TRIGGER IF NOT EXISTS trg_video_asset_version_no_update BEFORE UPDATE ON video_asset_versions BEGIN SELECT RAISE(ABORT, 'video asset version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_video_asset_version_no_delete BEFORE DELETE ON video_asset_versions BEGIN SELECT RAISE(ABORT, 'video asset version is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_wrong_question_video_schema(connection: Any) -> None:
    DBWrongQuestionVideoLink.__table__.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_wrong_question_video_student_source ON wrong_question_video_links(student_id,source_wrong_question_id)",
        "CREATE TRIGGER IF NOT EXISTS trg_wrong_question_video_no_update BEFORE UPDATE ON wrong_question_video_links BEGIN SELECT RAISE(ABORT, 'wrong question video link is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_wrong_question_video_no_delete BEFORE DELETE ON wrong_question_video_links BEGIN SELECT RAISE(ABORT, 'wrong question video link is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_chapter_video_schema(connection: Any) -> None:
    DBChapterVideoLink.__table__.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_chapter_video_course_chapter ON chapter_video_links(course_id,chapter_id)",
        "CREATE TRIGGER IF NOT EXISTS trg_chapter_video_no_update BEFORE UPDATE ON chapter_video_links BEGIN SELECT RAISE(ABORT, 'chapter video link is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_chapter_video_no_delete BEFORE DELETE ON chapter_video_links BEGIN SELECT RAISE(ABORT, 'chapter video link is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_video_practice_schema(connection: Any) -> None:
    for table in (
        DBVideoPracticeSet.__table__, DBVideoPracticeVersion.__table__,
        DBVideoWatchProgress.__table__, DBVideoPracticeAttemptLink.__table__,
        DBVideoPracticeLabLink.__table__,
    ):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_video_practice_set_course ON video_practice_sets(course_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_video_practice_attempt_owner_link ON video_practice_attempt_links(owner_public_id,chapter_video_link_id)",
        "CREATE TRIGGER IF NOT EXISTS trg_video_practice_version_no_update BEFORE UPDATE ON video_practice_versions BEGIN SELECT RAISE(ABORT, 'video practice version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_video_practice_version_no_delete BEFORE DELETE ON video_practice_versions BEGIN SELECT RAISE(ABORT, 'video practice version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_video_practice_attempt_no_update BEFORE UPDATE ON video_practice_attempt_links BEGIN SELECT RAISE(ABORT, 'video practice attempt link is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_video_practice_attempt_no_delete BEFORE DELETE ON video_practice_attempt_links BEGIN SELECT RAISE(ABORT, 'video practice attempt link is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_video_practice_lab_no_update BEFORE UPDATE ON video_practice_lab_links BEGIN SELECT RAISE(ABORT, 'video practice lab link is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_video_practice_lab_no_delete BEFORE DELETE ON video_practice_lab_links BEGIN SELECT RAISE(ABORT, 'video practice lab link is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_teaching_animation_schema(connection: Any) -> None:
    for table in (DBTeachingAnimation.__table__, DBTeachingAnimationVersion.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_teaching_animation_owner_updated ON teaching_animations(owner_public_id,updated_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_teaching_animation_version_no_update BEFORE UPDATE ON teaching_animation_versions BEGIN SELECT RAISE(ABORT, 'teaching animation version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_teaching_animation_version_no_delete BEFORE DELETE ON teaching_animation_versions BEGIN SELECT RAISE(ABORT, 'teaching animation version is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_web_deck_schema(connection: Any) -> None:
    for table in (DBWebDeck.__table__, DBWebSlide.__table__, DBWebDeckVersion.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_web_deck_owner_updated ON web_decks(owner_public_id,updated_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_web_slide_identity_frozen BEFORE UPDATE OF deck_id,stable_key,created_by_public_id,created_at ON web_slides BEGIN SELECT RAISE(ABORT, 'web slide identity is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_web_deck_version_no_update BEFORE UPDATE ON web_deck_versions BEGIN SELECT RAISE(ABORT, 'web deck version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_web_deck_version_no_delete BEFORE DELETE ON web_deck_versions BEGIN SELECT RAISE(ABORT, 'web deck version is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_local_adapter_schema(connection: Any) -> None:
    for table in (DBLocalAdapterSession.__table__, DBLocalAdapterEvent.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_local_adapter_owner_status ON local_adapter_sessions(owner_public_id,status,updated_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_local_adapter_event_no_update BEFORE UPDATE ON local_adapter_events BEGIN SELECT RAISE(ABORT, 'local adapter event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_local_adapter_event_no_delete BEFORE DELETE ON local_adapter_events BEGIN SELECT RAISE(ABORT, 'local adapter event is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_resource_bundle_schema(connection: Any) -> None:
    for table in (DBResourceBundle.__table__, DBResourceBundleVersion.__table__, DBResourceBundleItem.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_resource_bundle_owner_course ON resource_bundles(owner_public_id,course_id,status)",
        "CREATE TRIGGER IF NOT EXISTS trg_resource_bundle_version_no_update BEFORE UPDATE ON resource_bundle_versions BEGIN SELECT RAISE(ABORT, 'resource bundle version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_resource_bundle_version_no_delete BEFORE DELETE ON resource_bundle_versions BEGIN SELECT RAISE(ABORT, 'resource bundle version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_resource_bundle_item_no_update BEFORE UPDATE ON resource_bundle_items BEGIN SELECT RAISE(ABORT, 'resource bundle item is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_resource_bundle_item_no_delete BEFORE DELETE ON resource_bundle_items BEGIN SELECT RAISE(ABORT, 'resource bundle item is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_marketplace_comment_schema(connection: Any) -> None:
    for table in (DBMarketplaceComment.__table__, DBMarketplaceCommentEvent.__table__, DBMarketplaceCommentReport.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_marketplace_comment_listing_status ON marketplace_comments(listing_id,status,created_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_comment_binding_frozen BEFORE UPDATE OF listing_id,listing_snapshot_hash,course_version,author_public_id,created_at,edit_deadline ON marketplace_comments BEGIN SELECT RAISE(ABORT, 'marketplace comment binding is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_comment_no_delete BEFORE DELETE ON marketplace_comments BEGIN SELECT RAISE(ABORT, 'marketplace comment uses soft delete'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_comment_event_no_update BEFORE UPDATE ON marketplace_comment_events BEGIN SELECT RAISE(ABORT, 'marketplace comment event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_comment_event_no_delete BEFORE DELETE ON marketplace_comment_events BEGIN SELECT RAISE(ABORT, 'marketplace comment event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_comment_report_evidence_frozen BEFORE UPDATE OF comment_id,listing_id,reporter_public_id,category,description,evidence_snapshot,evidence_hash,created_at ON marketplace_comment_reports BEGIN SELECT RAISE(ABORT, 'marketplace comment report evidence is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_marketplace_engagement_schema(connection: Any) -> None:
    for table in (DBMarketplaceFavorite.__table__, DBMarketplaceReview.__table__, DBMarketplaceReviewEvent.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_marketplace_review_listing_status ON marketplace_reviews(listing_id,status,created_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_favorite_binding_frozen BEFORE UPDATE OF listing_id,listing_snapshot_hash,owner_public_id,created_at ON marketplace_favorites BEGIN SELECT RAISE(ABORT, 'marketplace favorite binding is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_review_binding_frozen BEFORE UPDATE OF listing_id,listing_snapshot_hash,course_version,owner_public_id,acquisition_id,derived_course_id,created_at ON marketplace_reviews BEGIN SELECT RAISE(ABORT, 'marketplace review binding is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_review_evidence_frozen BEFORE UPDATE OF evidence_snapshot,evidence_hash ON marketplace_reviews BEGIN SELECT RAISE(ABORT, 'marketplace review evidence is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_review_event_no_update BEFORE UPDATE ON marketplace_review_events BEGIN SELECT RAISE(ABORT, 'marketplace review event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_review_event_no_delete BEFORE DELETE ON marketplace_review_events BEGIN SELECT RAISE(ABORT, 'marketplace review event is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_marketplace_impact_notification_schema(connection: Any) -> None:
    for table in (DBMarketplaceImpactEvent.__table__, DBMarketplaceImpactNotification.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_marketplace_impact_notice_owner_status ON marketplace_impact_notifications(owner_public_id,status,created_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_impact_event_no_update BEFORE UPDATE ON marketplace_impact_events BEGIN SELECT RAISE(ABORT, 'marketplace impact event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_impact_event_no_delete BEFORE DELETE ON marketplace_impact_events BEGIN SELECT RAISE(ABORT, 'marketplace impact event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_impact_notice_binding_frozen BEFORE UPDATE OF impact_event_id,acquisition_id,owner_public_id,source_listing_id,target_listing_id,notification_type,idempotency_key,title,body,source_route,created_at ON marketplace_impact_notifications BEGIN SELECT RAISE(ABORT, 'marketplace impact notification binding is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_impact_notice_no_delete BEFORE DELETE ON marketplace_impact_notifications BEGIN SELECT RAISE(ABORT, 'marketplace impact notification is durable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_marketplace_fork_schema(connection: Any) -> None:
    for table in (DBMarketplaceFork.__table__, DBMarketplaceForkVersion.__table__, DBMarketplaceForkDecision.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_marketplace_fork_owner_status ON marketplace_forks(owner_public_id,upstream_status,updated_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_fork_binding_frozen BEFORE UPDATE OF acquisition_id,source_listing_id,derived_course_id,owner_public_id,created_at ON marketplace_forks BEGIN SELECT RAISE(ABORT, 'marketplace fork binding is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_fork_version_no_update BEFORE UPDATE ON marketplace_fork_versions BEGIN SELECT RAISE(ABORT, 'marketplace fork version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_fork_version_no_delete BEFORE DELETE ON marketplace_fork_versions BEGIN SELECT RAISE(ABORT, 'marketplace fork version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_fork_decision_no_update BEFORE UPDATE ON marketplace_fork_decisions BEGIN SELECT RAISE(ABORT, 'marketplace fork decision is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_fork_decision_no_delete BEFORE DELETE ON marketplace_fork_decisions BEGIN SELECT RAISE(ABORT, 'marketplace fork decision is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_marketplace_recommendation_schema(connection: Any) -> None:
    for table in (DBMarketplaceRecommendationRun.__table__, DBMarketplaceRecommendationResult.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_marketplace_recommendation_owner_created ON marketplace_recommendation_runs(owner_public_id,created_at)",
        "CREATE INDEX IF NOT EXISTS ix_marketplace_recommendation_result_run_rank ON marketplace_recommendation_results(run_id,rank)",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_recommendation_run_no_update BEFORE UPDATE ON marketplace_recommendation_runs BEGIN SELECT RAISE(ABORT, 'marketplace recommendation run is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_recommendation_run_no_delete BEFORE DELETE ON marketplace_recommendation_runs BEGIN SELECT RAISE(ABORT, 'marketplace recommendation run is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_recommendation_result_no_update BEFORE UPDATE ON marketplace_recommendation_results BEGIN SELECT RAISE(ABORT, 'marketplace recommendation result is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_recommendation_result_no_delete BEFORE DELETE ON marketplace_recommendation_results BEGIN SELECT RAISE(ABORT, 'marketplace recommendation result is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_course_governance_schema(connection: Any) -> None:
    for table in (
        DBTeachingClass.__table__, DBTeachingGroup.__table__, DBTeachingClassMember.__table__,
        DBTeachingTask.__table__, DBCourseWithdrawal.__table__,
    ):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_teaching_class_course_status ON teaching_classes(course_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_teaching_member_class_status ON teaching_class_members(class_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_teaching_task_class_status ON teaching_tasks(class_id,status)",
        "CREATE TRIGGER IF NOT EXISTS trg_course_withdrawal_no_update BEFORE UPDATE ON course_withdrawals BEGIN SELECT RAISE(ABORT, 'course withdrawal is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_course_withdrawal_no_delete BEFORE DELETE ON course_withdrawals BEGIN SELECT RAISE(ABORT, 'course withdrawal is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_teaching_analytics_schema(connection: Any) -> None:
    DBTeachingAnalyticsReport.__table__.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_teaching_analytics_class_period ON teaching_analytics_reports(class_id,period_start,period_end)",
        "CREATE TRIGGER IF NOT EXISTS trg_teaching_analytics_no_update BEFORE UPDATE ON teaching_analytics_reports BEGIN SELECT RAISE(ABORT, 'teaching analytics report is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_teaching_analytics_no_delete BEFORE DELETE ON teaching_analytics_reports BEGIN SELECT RAISE(ABORT, 'teaching analytics report is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_content_review_schema(connection: Any) -> None:
    for table in (DBContentReviewCase.__table__, DBContentReviewDecision.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_content_review_course_status ON content_review_cases(course_id,status)",
        "CREATE TRIGGER IF NOT EXISTS trg_content_review_decision_no_update BEFORE UPDATE ON content_review_decisions BEGIN SELECT RAISE(ABORT, 'content review decision is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_content_review_decision_no_delete BEFORE DELETE ON content_review_decisions BEGIN SELECT RAISE(ABORT, 'content review decision is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_certification_lifecycle_schema(connection: Any) -> None:
    columns = {item["name"] for item in sa.inspect(connection).get_columns("certifications")}
    if "revoked_at" not in columns:
        connection.execute(sa.text("ALTER TABLE certifications ADD COLUMN revoked_at DATETIME"))
    if "lock_version" not in columns:
        connection.execute(sa.text("ALTER TABLE certifications ADD COLUMN lock_version INTEGER NOT NULL DEFAULT 1"))
    for table in (DBCertificationLifecycleEvent.__table__, DBRetrainingTask.__table__, DBLocalNotification.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE TRIGGER IF NOT EXISTS trg_cert_lifecycle_event_no_update BEFORE UPDATE ON certification_lifecycle_events BEGIN SELECT RAISE(ABORT, 'certification lifecycle event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_cert_lifecycle_event_no_delete BEFORE DELETE ON certification_lifecycle_events BEGIN SELECT RAISE(ABORT, 'certification lifecycle event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_local_notification_no_delete BEFORE DELETE ON local_notifications BEGIN SELECT RAISE(ABORT, 'local notification is durable'); END",
    ):
        connection.execute(sa.text(statement))

def _install_next_multilevel_review_schema(connection: Any) -> None:
    for table in (DBMultilevelReviewCase.__table__,DBMultilevelReviewDecision.__table__):table.create(connection,checkfirst=True)
    for statement in ("CREATE TRIGGER IF NOT EXISTS trg_multilevel_decision_no_update BEFORE UPDATE ON multilevel_review_decisions BEGIN SELECT RAISE(ABORT, 'multilevel review decision is immutable'); END","CREATE TRIGGER IF NOT EXISTS trg_multilevel_decision_no_delete BEFORE DELETE ON multilevel_review_decisions BEGIN SELECT RAISE(ABORT, 'multilevel review decision is immutable'); END"):connection.execute(sa.text(statement))


def _install_next_job_standard_impact_schema(connection: Any) -> None:
    for table in (DBJobStandardImpactPreview.__table__, DBJobStandardImpactConfirmation.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_job_standard_impact_org_status ON job_standard_impact_previews(organization_id,status)",
        "CREATE TRIGGER IF NOT EXISTS trg_job_standard_confirmation_no_update BEFORE UPDATE ON job_standard_impact_confirmations BEGIN SELECT RAISE(ABORT, 'job standard impact confirmation is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_job_standard_confirmation_no_delete BEFORE DELETE ON job_standard_impact_confirmations BEGIN SELECT RAISE(ABORT, 'job standard impact confirmation is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_job_standard_preview_frozen_fields BEFORE UPDATE OF organization_id,source_job_level_id,target_job_level_id,created_by_public_id,standard_source,diff_snapshot,impact_snapshot,preview_hash,created_at ON job_standard_impact_previews BEGIN SELECT RAISE(ABORT, 'job standard impact preview evidence is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_job_standard_preview_no_delete BEFORE DELETE ON job_standard_impact_previews BEGIN SELECT RAISE(ABORT, 'job standard impact preview is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_enterprise_risk_schema(connection: Any) -> None:
    for table in (DBEnterpriseRiskReport.__table__, DBEnterpriseRiskDecision.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_enterprise_risk_org_period ON enterprise_risk_reports(organization_id,period_start,period_end)",
        "CREATE TRIGGER IF NOT EXISTS trg_enterprise_risk_report_frozen BEFORE UPDATE OF organization_id,period_start,period_end,metric_version,minimum_sample,report_data,content_hash,created_by_public_id,created_at ON enterprise_risk_reports BEGIN SELECT RAISE(ABORT, 'enterprise risk report evidence is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_enterprise_risk_report_no_delete BEFORE DELETE ON enterprise_risk_reports BEGIN SELECT RAISE(ABORT, 'enterprise risk report is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_enterprise_risk_decision_no_update BEFORE UPDATE ON enterprise_risk_decisions BEGIN SELECT RAISE(ABORT, 'enterprise risk decision is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_enterprise_risk_decision_no_delete BEFORE DELETE ON enterprise_risk_decisions BEGIN SELECT RAISE(ABORT, 'enterprise risk decision is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_course_sharing_schema(connection: Any) -> None:
    for table in (DBCourseShareRelease.__table__, DBCourseDerivedCopy.__table__, DBCourseShareDecision.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_course_share_target ON course_share_releases(target_type,target_id,status)",
        "CREATE TRIGGER IF NOT EXISTS trg_course_share_release_frozen BEFORE UPDATE OF source_course_id,source_course_version,source_manifest_version,target_type,target_id,title,snapshot_data,license_snapshot,snapshot_hash,created_by_public_id,created_at ON course_share_releases BEGIN SELECT RAISE(ABORT, 'course share release evidence is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_course_share_release_no_delete BEFORE DELETE ON course_share_releases BEGIN SELECT RAISE(ABORT, 'course share release is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_course_share_decision_no_update BEFORE UPDATE ON course_share_decisions BEGIN SELECT RAISE(ABORT, 'course share decision is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_course_share_decision_no_delete BEFORE DELETE ON course_share_decisions BEGIN SELECT RAISE(ABORT, 'course share decision is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_marketplace_schema(connection: Any) -> None:
    for table in (DBMarketplaceListing.__table__, DBMarketplaceDecision.__table__, DBMarketplaceReport.__table__, DBMarketplaceAcquisition.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_marketplace_public_search ON marketplace_listings(status,category,title)",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_listing_frozen BEFORE UPDATE OF course_id,course_version,title,summary,category,tags,snapshot_data,license_snapshot,snapshot_hash,owner_public_id,created_at ON marketplace_listings BEGIN SELECT RAISE(ABORT, 'marketplace listing evidence is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_listing_no_delete BEFORE DELETE ON marketplace_listings BEGIN SELECT RAISE(ABORT, 'marketplace listing is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_decision_no_update BEFORE UPDATE ON marketplace_decisions BEGIN SELECT RAISE(ABORT, 'marketplace decision is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_decision_no_delete BEFORE DELETE ON marketplace_decisions BEGIN SELECT RAISE(ABORT, 'marketplace decision is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_report_frozen BEFORE UPDATE OF listing_id,reporter_public_id,category,description,evidence_snapshot,evidence_hash,created_at ON marketplace_reports BEGIN SELECT RAISE(ABORT, 'marketplace report evidence is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_acquisition_no_update BEFORE UPDATE OF listing_id,recipient_public_id,derived_course_id,listing_snapshot_hash,created_at ON marketplace_acquisitions BEGIN SELECT RAISE(ABORT, 'marketplace acquisition identity is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_acquisition_no_delete BEFORE DELETE ON marketplace_acquisitions BEGIN SELECT RAISE(ABORT, 'marketplace acquisition is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_organization_marketplace_schema(connection: Any) -> None:
    for table in (DBOrganizationResourceListing.__table__, DBOrganizationResourceAcquisition.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_org_resource_catalog ON organization_resource_listings(organization_id,status,category)",
        "CREATE TRIGGER IF NOT EXISTS trg_org_resource_listing_frozen BEFORE UPDATE OF organization_id,course_id,course_version,title,summary,category,tags,snapshot_data,license_snapshot,snapshot_hash,policy_snapshot,owner_public_id,created_at ON organization_resource_listings BEGIN SELECT RAISE(ABORT, 'organization resource listing evidence is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_org_resource_listing_no_delete BEFORE DELETE ON organization_resource_listings BEGIN SELECT RAISE(ABORT, 'organization resource listing is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_org_resource_acquisition_no_update BEFORE UPDATE OF listing_id,organization_id,recipient_public_id,derived_course_id,listing_snapshot_hash,created_at ON organization_resource_acquisitions BEGIN SELECT RAISE(ABORT, 'organization resource acquisition is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_org_resource_acquisition_no_delete BEFORE DELETE ON organization_resource_acquisitions BEGIN SELECT RAISE(ABORT, 'organization resource acquisition is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_spatial_workspace_schema(connection: Any) -> None:
    for table in (DBSpatialWorkspace.__table__, DBSpatialLayoutVersion.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_spatial_workspace_owner_status ON spatial_workspaces(owner_public_id,status,updated_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_spatial_layout_immutable_update BEFORE UPDATE ON spatial_layout_versions BEGIN SELECT RAISE(ABORT, 'spatial layout version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_spatial_layout_immutable_delete BEFORE DELETE ON spatial_layout_versions BEGIN SELECT RAISE(ABORT, 'spatial layout version is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_next_plugin_registry_schema(connection: Any) -> None:
    for table in (DBPluginRegistration.__table__, DBPluginLifecycleEvent.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE TRIGGER IF NOT EXISTS trg_plugin_event_no_update BEFORE UPDATE ON plugin_lifecycle_events BEGIN SELECT RAISE(ABORT, 'plugin lifecycle event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_plugin_event_no_delete BEFORE DELETE ON plugin_lifecycle_events BEGIN SELECT RAISE(ABORT, 'plugin lifecycle event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_plugin_evidence_frozen BEFORE UPDATE OF plugin_id,plugin_version,domain_key,title,manifest_snapshot,verification_snapshot,package_hash,license,attribution,source_url,source_version,allowed_actions,created_at ON plugin_registrations BEGIN SELECT RAISE(ABORT, 'plugin registration evidence is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_flashcard_schema(connection: Any) -> None:
    for table in (DBFlashcard.__table__, DBFlashcardVersion.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_flashcard_owner_status ON flashcards(owner_public_id,status,updated_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_flashcard_version_no_update BEFORE UPDATE ON flashcard_versions BEGIN SELECT RAISE(ABORT, 'flashcard version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_flashcard_version_no_delete BEFORE DELETE ON flashcard_versions BEGIN SELECT RAISE(ABORT, 'flashcard version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_flashcard_identity_frozen BEFORE UPDATE OF owner_public_id,student_id,review_plan_id,concept,source_quiz_id,identity_hash,created_at ON flashcards BEGIN SELECT RAISE(ABORT, 'flashcard identity is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_local_sso_schema(connection: Any) -> None:
    for table in (
        DBLocalSSOProvider.__table__, DBLocalSSOMappingVersion.__table__,
        DBLocalSSOSession.__table__, DBLocalSSOEvent.__table__,
    ):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_local_sso_provider_org_status ON local_sso_providers(organization_id,status)",
        "CREATE INDEX IF NOT EXISTS ix_local_sso_session_org_status ON local_sso_sessions(organization_id,status,expires_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_local_sso_mapping_no_update BEFORE UPDATE ON local_sso_mapping_versions BEGIN SELECT RAISE(ABORT, 'local SSO mapping version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_local_sso_mapping_no_delete BEFORE DELETE ON local_sso_mapping_versions BEGIN SELECT RAISE(ABORT, 'local SSO mapping version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_local_sso_event_no_update BEFORE UPDATE ON local_sso_events BEGIN SELECT RAISE(ABORT, 'local SSO event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_local_sso_event_no_delete BEFORE DELETE ON local_sso_events BEGIN SELECT RAISE(ABORT, 'local SSO event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_local_sso_session_identity_frozen BEFORE UPDATE OF organization_id,provider_id,mapping_id,user_public_id,assertion_id,assertion_hash,resolved_organization_role,login_mode,issued_at,expires_at ON local_sso_sessions BEGIN SELECT RAISE(ABORT, 'local SSO session identity is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_hr_sync_schema(connection: Any) -> None:
    for table in (
        DBHRFieldMappingVersion.__table__, DBHRSyncBatch.__table__,
        DBHREmployeeProjection.__table__, DBHRSyncRecord.__table__,
    ):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_hr_batch_org_source_sequence ON hr_sync_batches(organization_id,source_key,source_sequence)",
        "CREATE INDEX IF NOT EXISTS ix_hr_employee_org_status ON hr_employee_projections(organization_id,employment_status)",
        "CREATE TRIGGER IF NOT EXISTS trg_hr_mapping_no_update BEFORE UPDATE ON hr_field_mapping_versions BEGIN SELECT RAISE(ABORT, 'HR mapping version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_hr_mapping_no_delete BEFORE DELETE ON hr_field_mapping_versions BEGIN SELECT RAISE(ABORT, 'HR mapping version is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_hr_batch_frozen BEFORE UPDATE OF organization_id,source_key,source_snapshot_id,source_sequence,mapping_version_id,source_snapshot,preview_snapshot,source_hash,created_by_public_id,created_at ON hr_sync_batches BEGIN SELECT RAISE(ABORT, 'HR sync preview is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_hr_batch_no_delete BEFORE DELETE ON hr_sync_batches BEGIN SELECT RAISE(ABORT, 'HR sync batch is durable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_hr_record_no_update BEFORE UPDATE ON hr_sync_records BEGIN SELECT RAISE(ABORT, 'HR sync record is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_hr_record_no_delete BEFORE DELETE ON hr_sync_records BEGIN SELECT RAISE(ABORT, 'HR sync record is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_local_lms_schema(connection: Any) -> None:
    for table in (
        DBLocalLMSConnection.__table__, DBLMSCatalogExport.__table__,
        DBLMSAssignmentExchange.__table__, DBLMSGradeSummary.__table__,
        DBLMSSyncEvent.__table__,
    ):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_lms_catalog_org_connection ON lms_catalog_exports(organization_id,connection_id,created_at)",
        "CREATE INDEX IF NOT EXISTS ix_lms_grade_org_candidate ON lms_grade_summaries(organization_id,evidence_status,created_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_lms_catalog_no_update BEFORE UPDATE ON lms_catalog_exports BEGIN SELECT RAISE(ABORT, 'LMS catalog export is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_lms_catalog_no_delete BEFORE DELETE ON lms_catalog_exports BEGIN SELECT RAISE(ABORT, 'LMS catalog export is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_lms_grade_no_update BEFORE UPDATE ON lms_grade_summaries BEGIN SELECT RAISE(ABORT, 'LMS grade summary is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_lms_grade_no_delete BEFORE DELETE ON lms_grade_summaries BEGIN SELECT RAISE(ABORT, 'LMS grade summary is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_lms_event_no_update BEFORE UPDATE ON lms_sync_events BEGIN SELECT RAISE(ABORT, 'LMS sync event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_lms_event_no_delete BEFORE DELETE ON lms_sync_events BEGIN SELECT RAISE(ABORT, 'LMS sync event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_lms_assignment_identity_frozen BEFORE UPDATE OF organization_id,connection_id,training_assignment_id,external_assignment_key ON lms_assignment_exchanges BEGIN SELECT RAISE(ABORT, 'LMS assignment identity is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_local_lrs_cmi5_schema(connection: Any) -> None:
    for table in (
        DBLocalLRSStatement.__table__, DBIntegrationDeliveryEvent.__table__,
        DBCmi5Session.__table__, DBCmi5SessionEvent.__table__,
    ):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_local_lrs_org_received ON local_lrs_statements(organization_id,received_at)",
        "CREATE INDEX IF NOT EXISTS ix_cmi5_org_status ON cmi5_sessions(organization_id,status,launched_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_local_lrs_statement_no_update BEFORE UPDATE ON local_lrs_statements BEGIN SELECT RAISE(ABORT, 'local LRS statement is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_local_lrs_statement_no_delete BEFORE DELETE ON local_lrs_statements BEGIN SELECT RAISE(ABORT, 'local LRS statement is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_integration_delivery_event_no_update BEFORE UPDATE ON integration_delivery_events BEGIN SELECT RAISE(ABORT, 'integration delivery event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_integration_delivery_event_no_delete BEFORE DELETE ON integration_delivery_events BEGIN SELECT RAISE(ABORT, 'integration delivery event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_cmi5_session_identity_frozen BEFORE UPDATE OF organization_id,learner_public_id,course_id,registration,launch_key,created_by_public_id,launched_at ON cmi5_sessions BEGIN SELECT RAISE(ABORT, 'cmi5 session identity is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_cmi5_event_no_update BEFORE UPDATE ON cmi5_session_events BEGIN SELECT RAISE(ABORT, 'cmi5 event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_cmi5_event_no_delete BEFORE DELETE ON cmi5_session_events BEGIN SELECT RAISE(ABORT, 'cmi5 event is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_signed_webhook_schema(connection: Any) -> None:
    for table in (
        DBLocalWebhookEndpoint.__table__, DBWebhookEvent.__table__,
        DBWebhookAcceptedNonce.__table__, DBWebhookReceipt.__table__,
    ):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_webhook_event_org_created ON webhook_events(organization_id,created_at)",
        "CREATE INDEX IF NOT EXISTS ix_webhook_receipt_org_received ON webhook_receipts(organization_id,received_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_webhook_event_no_update BEFORE UPDATE ON webhook_events BEGIN SELECT RAISE(ABORT, 'webhook event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_webhook_event_no_delete BEFORE DELETE ON webhook_events BEGIN SELECT RAISE(ABORT, 'webhook event is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_webhook_nonce_no_update BEFORE UPDATE ON webhook_accepted_nonces BEGIN SELECT RAISE(ABORT, 'webhook replay guard is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_webhook_nonce_no_delete BEFORE DELETE ON webhook_accepted_nonces BEGIN SELECT RAISE(ABORT, 'webhook replay guard is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_webhook_receipt_no_update BEFORE UPDATE ON webhook_receipts BEGIN SELECT RAISE(ABORT, 'webhook receipt is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_webhook_receipt_no_delete BEFORE DELETE ON webhook_receipts BEGIN SELECT RAISE(ABORT, 'webhook receipt is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_webhook_endpoint_identity_frozen BEFORE UPDATE OF organization_id,destination_key,signing_secret,secret_fingerprint,created_by_public_id,created_at ON local_webhook_endpoints BEGIN SELECT RAISE(ABORT, 'webhook endpoint identity is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_integration_reconciliation_schema(connection: Any) -> None:
    for table in (
        DBIntegrationReconciliationRun.__table__, DBIntegrationRepairDecision.__table__,
    ):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_reconciliation_org_created ON integration_reconciliation_runs(organization_id,created_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_reconciliation_identity_frozen BEFORE UPDATE OF organization_id,run_key,schema_version,mapping_versions,source_preview,count_snapshot,discrepancies,snapshot_hash,created_by_public_id,created_at ON integration_reconciliation_runs BEGIN SELECT RAISE(ABORT, 'reconciliation snapshot is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_reconciliation_no_delete BEFORE DELETE ON integration_reconciliation_runs BEGIN SELECT RAISE(ABORT, 'reconciliation run cannot be deleted'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_integration_repair_no_update BEFORE UPDATE ON integration_repair_decisions BEGIN SELECT RAISE(ABORT, 'integration repair decision is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_integration_repair_no_delete BEFORE DELETE ON integration_repair_decisions BEGIN SELECT RAISE(ABORT, 'integration repair decision is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_integration_fault_drill_schema(connection: Any) -> None:
    for table in (DBIntegrationFaultDrill.__table__, DBIntegrationFaultDrillStep.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_integration_fault_drill_org_created ON integration_fault_drills(organization_id,created_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_fault_drill_identity_frozen BEFORE UPDATE OF organization_id,run_key,authority_before_hash,scenario_plan,created_by_public_id,created_at ON integration_fault_drills BEGIN SELECT RAISE(ABORT, 'fault drill identity is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_fault_drill_no_delete BEFORE DELETE ON integration_fault_drills BEGIN SELECT RAISE(ABORT, 'fault drill cannot be deleted'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_fault_drill_step_no_update BEFORE UPDATE ON integration_fault_drill_steps BEGIN SELECT RAISE(ABORT, 'fault drill step is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_fault_drill_step_no_delete BEFORE DELETE ON integration_fault_drill_steps BEGIN SELECT RAISE(ABORT, 'fault drill step is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_fc_competition_journey_schema(connection: Any) -> None:
    for table in (DBCompetitionJourneyRun.__table__, DBCompetitionJourneyVisit.__table__):
        table.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_competition_journey_owner_created ON competition_journey_runs(owner_public_id,created_at)",
        "CREATE TRIGGER IF NOT EXISTS trg_competition_journey_identity_frozen BEFORE UPDATE OF owner_public_id,course_id,journey_type,run_key,baseline_snapshot,baseline_hash,created_at ON competition_journey_runs BEGIN SELECT RAISE(ABORT, 'competition journey identity is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_competition_journey_visit_no_update BEFORE UPDATE ON competition_journey_visits BEGIN SELECT RAISE(ABORT, 'competition journey visit is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_competition_journey_visit_no_delete BEFORE DELETE ON competition_journey_visits BEGIN SELECT RAISE(ABORT, 'competition journey visit is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _expand_fc_competition_journey_types(connection: Any) -> None:
    """Rebuild the two journey tables while preserving all FC5-01A evidence."""
    if connection.dialect.name != "sqlite":
        return
    for trigger in (
        "trg_competition_journey_identity_frozen",
        "trg_competition_journey_visit_no_update",
        "trg_competition_journey_visit_no_delete",
    ):
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
    for index in (
        "ix_competition_journey_owner_created",
        "ix_competition_journey_runs_owner_public_id",
        "ix_competition_journey_runs_course_id",
        "ix_competition_journey_runs_journey_type",
        "ix_competition_journey_runs_status",
        "ix_competition_journey_visits_run_id",
        "ix_competition_journey_visits_owner_public_id",
    ):
        connection.execute(sa.text(f"DROP INDEX IF EXISTS {index}"))
    connection.execute(sa.text("ALTER TABLE competition_journey_visits RENAME TO competition_journey_visits_055"))
    connection.execute(sa.text("ALTER TABLE competition_journey_runs RENAME TO competition_journey_runs_055"))
    DBCompetitionJourneyRun.__table__.create(connection, checkfirst=False)
    DBCompetitionJourneyVisit.__table__.create(connection, checkfirst=False)
    run_columns = "id,owner_public_id,course_id,journey_type,run_key,status,baseline_snapshot,baseline_hash,lock_version,created_at,updated_at,completed_at"
    visit_columns = "id,run_id,owner_public_id,step_key,route,evidence_snapshot,evidence_hash,created_at"
    connection.execute(sa.text(f"INSERT INTO competition_journey_runs({run_columns}) SELECT {run_columns} FROM competition_journey_runs_055"))
    connection.execute(sa.text(f"INSERT INTO competition_journey_visits({visit_columns}) SELECT {visit_columns} FROM competition_journey_visits_055"))
    connection.execute(sa.text("DROP TABLE competition_journey_visits_055"))
    connection.execute(sa.text("DROP TABLE competition_journey_runs_055"))
    _install_fc_competition_journey_schema(connection)


def _expand_fc_teacher_journey_type(connection: Any) -> None:
    """Preserve student/media runs while adding the teacher journey contract."""
    if connection.dialect.name != "sqlite":
        return
    for trigger in (
        "trg_competition_journey_identity_frozen",
        "trg_competition_journey_visit_no_update",
        "trg_competition_journey_visit_no_delete",
    ):
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
    for index in (
        "ix_competition_journey_owner_created",
        "ix_competition_journey_runs_owner_public_id",
        "ix_competition_journey_runs_course_id",
        "ix_competition_journey_runs_journey_type",
        "ix_competition_journey_runs_status",
        "ix_competition_journey_visits_run_id",
        "ix_competition_journey_visits_owner_public_id",
    ):
        connection.execute(sa.text(f"DROP INDEX IF EXISTS {index}"))
    connection.execute(sa.text("ALTER TABLE competition_journey_visits RENAME TO competition_journey_visits_056"))
    connection.execute(sa.text("ALTER TABLE competition_journey_runs RENAME TO competition_journey_runs_056"))
    DBCompetitionJourneyRun.__table__.create(connection, checkfirst=False)
    DBCompetitionJourneyVisit.__table__.create(connection, checkfirst=False)
    run_columns = "id,owner_public_id,course_id,journey_type,run_key,status,baseline_snapshot,baseline_hash,lock_version,created_at,updated_at,completed_at"
    visit_columns = "id,run_id,owner_public_id,step_key,route,evidence_snapshot,evidence_hash,created_at"
    connection.execute(sa.text(f"INSERT INTO competition_journey_runs({run_columns}) SELECT {run_columns} FROM competition_journey_runs_056"))
    connection.execute(sa.text(f"INSERT INTO competition_journey_visits({visit_columns}) SELECT {visit_columns} FROM competition_journey_visits_056"))
    connection.execute(sa.text("DROP TABLE competition_journey_visits_056"))
    connection.execute(sa.text("DROP TABLE competition_journey_runs_056"))
    _install_fc_competition_journey_schema(connection)


def _expand_fc_enterprise_journey_type(connection: Any) -> None:
    """Preserve the first three journeys while adding enterprise training."""
    if connection.dialect.name != "sqlite":
        return
    for trigger in (
        "trg_competition_journey_identity_frozen",
        "trg_competition_journey_visit_no_update",
        "trg_competition_journey_visit_no_delete",
    ):
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
    for index in (
        "ix_competition_journey_owner_created",
        "ix_competition_journey_runs_owner_public_id",
        "ix_competition_journey_runs_course_id",
        "ix_competition_journey_runs_journey_type",
        "ix_competition_journey_runs_status",
        "ix_competition_journey_visits_run_id",
        "ix_competition_journey_visits_owner_public_id",
    ):
        connection.execute(sa.text(f"DROP INDEX IF EXISTS {index}"))
    connection.execute(sa.text("ALTER TABLE competition_journey_visits RENAME TO competition_journey_visits_057"))
    connection.execute(sa.text("ALTER TABLE competition_journey_runs RENAME TO competition_journey_runs_057"))
    DBCompetitionJourneyRun.__table__.create(connection, checkfirst=False)
    DBCompetitionJourneyVisit.__table__.create(connection, checkfirst=False)
    run_columns = "id,owner_public_id,course_id,journey_type,run_key,status,baseline_snapshot,baseline_hash,lock_version,created_at,updated_at,completed_at"
    visit_columns = "id,run_id,owner_public_id,step_key,route,evidence_snapshot,evidence_hash,created_at"
    connection.execute(sa.text(f"INSERT INTO competition_journey_runs({run_columns}) SELECT {run_columns} FROM competition_journey_runs_057"))
    connection.execute(sa.text(f"INSERT INTO competition_journey_visits({visit_columns}) SELECT {visit_columns} FROM competition_journey_visits_057"))
    connection.execute(sa.text("DROP TABLE competition_journey_visits_057"))
    connection.execute(sa.text("DROP TABLE competition_journey_runs_057"))
    _install_fc_competition_journey_schema(connection)


def _expand_fc_marketplace_journey_type(connection: Any) -> None:
    """Preserve four completed journeys and add marketplace search proof."""
    if connection.dialect.name != "sqlite":
        DBMarketplaceJourneySearchVerification.__table__.create(connection, checkfirst=True)
        return
    # Metadata creation runs before registered migrations. Remove the new,
    # necessarily empty table so SQLite cannot retarget its FK to the temporary
    # journey table during ALTER TABLE RENAME.
    connection.execute(sa.text("DROP TABLE IF EXISTS marketplace_journey_search_verifications"))
    for trigger in (
        "trg_competition_journey_identity_frozen",
        "trg_competition_journey_visit_no_update",
        "trg_competition_journey_visit_no_delete",
    ):
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
    for index in (
        "ix_competition_journey_owner_created",
        "ix_competition_journey_runs_owner_public_id",
        "ix_competition_journey_runs_course_id",
        "ix_competition_journey_runs_journey_type",
        "ix_competition_journey_runs_status",
        "ix_competition_journey_visits_run_id",
        "ix_competition_journey_visits_owner_public_id",
    ):
        connection.execute(sa.text(f"DROP INDEX IF EXISTS {index}"))
    connection.execute(sa.text("ALTER TABLE competition_journey_visits RENAME TO competition_journey_visits_058"))
    connection.execute(sa.text("ALTER TABLE competition_journey_runs RENAME TO competition_journey_runs_058"))
    DBCompetitionJourneyRun.__table__.create(connection, checkfirst=False)
    DBCompetitionJourneyVisit.__table__.create(connection, checkfirst=False)
    run_columns = "id,owner_public_id,course_id,journey_type,run_key,status,baseline_snapshot,baseline_hash,lock_version,created_at,updated_at,completed_at"
    visit_columns = "id,run_id,owner_public_id,step_key,route,evidence_snapshot,evidence_hash,created_at"
    connection.execute(sa.text(f"INSERT INTO competition_journey_runs({run_columns}) SELECT {run_columns} FROM competition_journey_runs_058"))
    connection.execute(sa.text(f"INSERT INTO competition_journey_visits({visit_columns}) SELECT {visit_columns} FROM competition_journey_visits_058"))
    connection.execute(sa.text("DROP TABLE competition_journey_visits_058"))
    connection.execute(sa.text("DROP TABLE competition_journey_runs_058"))
    _install_fc_competition_journey_schema(connection)
    DBMarketplaceJourneySearchVerification.__table__.create(connection, checkfirst=True)
    for statement in (
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_journey_search_no_update BEFORE UPDATE ON marketplace_journey_search_verifications BEGIN SELECT RAISE(ABORT, 'marketplace journey search proof is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_journey_search_no_delete BEFORE DELETE ON marketplace_journey_search_verifications BEGIN SELECT RAISE(ABORT, 'marketplace journey search proof is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _repair_fc_marketplace_search_proof_fk(connection: Any) -> None:
    """Repair databases that applied 059 before the SQLite FK ordering fix."""
    if connection.dialect.name != "sqlite":
        return
    tables = set(sa.inspect(connection).get_table_names())
    if "marketplace_journey_search_verifications" not in tables:
        DBMarketplaceJourneySearchVerification.__table__.create(connection, checkfirst=True)
    else:
        foreign_keys = connection.execute(sa.text("PRAGMA foreign_key_list(marketplace_journey_search_verifications)")).fetchall()
        run_target = next((row[2] for row in foreign_keys if row[3] == "run_id"), None)
        if run_target != "competition_journey_runs":
            for trigger in ("trg_marketplace_journey_search_no_update", "trg_marketplace_journey_search_no_delete"):
                connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
            connection.execute(sa.text("ALTER TABLE marketplace_journey_search_verifications RENAME TO marketplace_journey_search_verifications_059"))
            for index in connection.execute(sa.text("PRAGMA index_list(marketplace_journey_search_verifications_059)")).fetchall():
                if index[1] and not str(index[1]).startswith("sqlite_autoindex"):
                    connection.execute(sa.text(f'DROP INDEX IF EXISTS "{index[1]}"'))
            DBMarketplaceJourneySearchVerification.__table__.create(connection, checkfirst=False)
            columns = "id,run_id,listing_id,listing_snapshot_hash,recipient_public_id,query,result_snapshot,result_hash,verified_by_public_id,created_at"
            connection.execute(sa.text(f"INSERT INTO marketplace_journey_search_verifications({columns}) SELECT {columns} FROM marketplace_journey_search_verifications_059"))
            connection.execute(sa.text("DROP TABLE marketplace_journey_search_verifications_059"))
    for statement in (
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_journey_search_no_update BEFORE UPDATE ON marketplace_journey_search_verifications BEGIN SELECT RAISE(ABORT, 'marketplace journey search proof is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_journey_search_no_delete BEFORE DELETE ON marketplace_journey_search_verifications BEGIN SELECT RAISE(ABORT, 'marketplace journey search proof is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _expand_fc_integration_journey_type(connection: Any) -> None:
    """Preserve five completed journeys and marketplace proof while adding integration."""
    if connection.dialect.name != "sqlite":
        return
    for trigger in (
        "trg_marketplace_journey_search_no_update",
        "trg_marketplace_journey_search_no_delete",
        "trg_competition_journey_identity_frozen",
        "trg_competition_journey_visit_no_update",
        "trg_competition_journey_visit_no_delete",
    ):
        connection.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
    for index in (
        "ix_marketplace_journey_search_verifications_run_id",
        "ix_marketplace_journey_search_verifications_listing_id",
        "ix_marketplace_journey_search_verifications_recipient_public_id",
        "ix_competition_journey_owner_created",
        "ix_competition_journey_runs_owner_public_id",
        "ix_competition_journey_runs_course_id",
        "ix_competition_journey_runs_journey_type",
        "ix_competition_journey_runs_status",
        "ix_competition_journey_visits_run_id",
        "ix_competition_journey_visits_owner_public_id",
    ):
        connection.execute(sa.text(f"DROP INDEX IF EXISTS {index}"))
    proof_exists = "marketplace_journey_search_verifications" in set(sa.inspect(connection).get_table_names())
    if proof_exists:
        connection.execute(sa.text("ALTER TABLE marketplace_journey_search_verifications RENAME TO marketplace_journey_search_verifications_060"))
    connection.execute(sa.text("ALTER TABLE competition_journey_visits RENAME TO competition_journey_visits_060"))
    connection.execute(sa.text("ALTER TABLE competition_journey_runs RENAME TO competition_journey_runs_060"))
    DBCompetitionJourneyRun.__table__.create(connection, checkfirst=False)
    DBCompetitionJourneyVisit.__table__.create(connection, checkfirst=False)
    run_columns = "id,owner_public_id,course_id,journey_type,run_key,status,baseline_snapshot,baseline_hash,lock_version,created_at,updated_at,completed_at"
    visit_columns = "id,run_id,owner_public_id,step_key,route,evidence_snapshot,evidence_hash,created_at"
    connection.execute(sa.text(f"INSERT INTO competition_journey_runs({run_columns}) SELECT {run_columns} FROM competition_journey_runs_060"))
    connection.execute(sa.text(f"INSERT INTO competition_journey_visits({visit_columns}) SELECT {visit_columns} FROM competition_journey_visits_060"))
    DBMarketplaceJourneySearchVerification.__table__.create(connection, checkfirst=True)
    if proof_exists:
        columns = "id,run_id,listing_id,listing_snapshot_hash,recipient_public_id,query,result_snapshot,result_hash,verified_by_public_id,created_at"
        connection.execute(sa.text(f"INSERT INTO marketplace_journey_search_verifications({columns}) SELECT {columns} FROM marketplace_journey_search_verifications_060"))
        connection.execute(sa.text("DROP TABLE marketplace_journey_search_verifications_060"))
    connection.execute(sa.text("DROP TABLE competition_journey_visits_060"))
    connection.execute(sa.text("DROP TABLE competition_journey_runs_060"))
    _install_fc_competition_journey_schema(connection)
    for statement in (
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_journey_search_no_update BEFORE UPDATE ON marketplace_journey_search_verifications BEGIN SELECT RAISE(ABORT, 'marketplace journey search proof is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_journey_search_no_delete BEFORE DELETE ON marketplace_journey_search_verifications BEGIN SELECT RAISE(ABORT, 'marketplace journey search proof is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_f3_onboarding_personal_evidence(connection: Any) -> None:
    DBOnboardingPersonalEvidence.__table__.create(connection, checkfirst=True)


def _install_f3_diagnostic_blueprint(connection: Any) -> None:
    DBDiagnosticBlueprint.__table__.create(connection, checkfirst=True)


def _install_f3_diagnostic_sessions(connection: Any) -> None:
    DBDiagnosticSession.__table__.create(connection, checkfirst=True)
    DBDiagnosticResponseDraft.__table__.create(connection, checkfirst=True)


def _install_f3_diagnostic_response_ordering(connection: Any) -> None:
    columns = {
        column["name"]
        for column in sa.inspect(connection).get_columns("diagnostic_response_drafts")
    }
    if "client_saved_at" not in columns:
        connection.execute(sa.text(
            "ALTER TABLE diagnostic_response_drafts ADD COLUMN client_saved_at DATETIME"
        ))
    connection.execute(sa.text(
        "UPDATE diagnostic_response_drafts "
        "SET client_saved_at = saved_at "
        "WHERE client_saved_at IS NULL"
    ))


def _install_f3_diagnostic_reports(connection: Any) -> None:
    DBDiagnosticReport.__table__.create(connection, checkfirst=True)
    connection.execute(sa.text(
        "CREATE TRIGGER IF NOT EXISTS trg_diagnostic_report_no_update "
        "BEFORE UPDATE ON diagnostic_reports BEGIN "
        "SELECT RAISE(ABORT, 'diagnostic report is immutable'); END"
    ))
    connection.execute(sa.text(
        "CREATE TRIGGER IF NOT EXISTS trg_diagnostic_report_no_delete "
        "BEFORE DELETE ON diagnostic_reports BEGIN "
        "SELECT RAISE(ABORT, 'diagnostic report is immutable'); END"
    ))


def _install_f6_formal_exam_learning_schema(connection: Any) -> None:
    tables = set(sa.inspect(connection).get_table_names())
    missing = sorted({"assessment_exams", "assessment_exam_versions", "wrong_questions"} - tables)
    if missing:
        raise RuntimeError(f"F6 formal exam migration missing tables: {missing}")

    exam_columns = {column["name"] for column in sa.inspect(connection).get_columns("assessment_exams")}
    if "generation_key" not in exam_columns:
        connection.execute(sa.text(
            "ALTER TABLE assessment_exams ADD COLUMN generation_key VARCHAR(128)"
        ))

    version_columns = {
        column["name"] for column in sa.inspect(connection).get_columns("assessment_exam_versions")
    }
    for name in ("configuration", "generation_context", "coverage"):
        if name not in version_columns:
            connection.execute(sa.text(
                f"ALTER TABLE assessment_exam_versions ADD COLUMN {name} JSON NOT NULL DEFAULT '{{}}'"
            ))

    wrong_columns = {column["name"] for column in sa.inspect(connection).get_columns("wrong_questions")}
    if "source_object_id" not in wrong_columns:
        connection.execute(sa.text(
            "ALTER TABLE wrong_questions ADD COLUMN source_object_id VARCHAR(64)"
        ))

    DBAssessmentExamResponseDraft.__table__.create(connection, checkfirst=True)
    for statement in (
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_assessment_exam_owner_generation "
        "ON assessment_exams(owner_public_id,generation_key) WHERE generation_key IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS ix_exam_response_draft_sitting_item "
        "ON assessment_exam_response_drafts(sitting_id,exam_item_id,revision)",
        "CREATE INDEX IF NOT EXISTS ix_wrong_questions_source_object_id "
        "ON wrong_questions(source_object_id)",
        "DROP INDEX IF EXISTS ix_wrong_questions_source_event_id",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_wrong_questions_event_object "
        "ON wrong_questions(source_event_id,COALESCE(source_object_id,'')) "
        "WHERE source_event_id IS NOT NULL",
        "CREATE TRIGGER IF NOT EXISTS trg_exam_response_draft_no_update "
        "BEFORE UPDATE ON assessment_exam_response_drafts BEGIN "
        "SELECT RAISE(ABORT, 'assessment exam response draft is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_exam_response_draft_no_delete "
        "BEFORE DELETE ON assessment_exam_response_drafts BEGIN "
        "SELECT RAISE(ABORT, 'assessment exam response draft is immutable'); END",
    ):
        connection.execute(sa.text(statement))


def _install_f7_document_reader_schema(connection: Any) -> None:
    note_columns = {column["name"] for column in sa.inspect(connection).get_columns("notes")}
    if "source_metadata" not in note_columns:
        connection.execute(sa.text(
            "ALTER TABLE notes ADD COLUMN source_metadata JSON NOT NULL DEFAULT '{}'"
        ))
    DBDocumentReadingPosition.__table__.create(connection, checkfirst=True)
    DBDocumentSelection.__table__.create(connection, checkfirst=True)


def _install_f7_web_source_candidate_schema(connection: Any) -> None:
    DBWebSourceCandidate.__table__.create(connection, checkfirst=True)


def _install_f7_chat_schema(connection: Any) -> None:
    DBChatConversation.__table__.create(connection, checkfirst=True)
    DBChatAttachment.__table__.create(connection, checkfirst=True)
    DBChatMessage.__table__.create(connection, checkfirst=True)


def _machine_exam_note(value: Any) -> bool:
    if not value:
        return False
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    machine_keys = {"exam_id", "sitting_id", "position", "score"}
    return bool(payload.get("exam_id") or payload.get("sitting_id")) and set(payload) <= machine_keys


def _install_f8_canonical_wrong_question_identity(connection: Any) -> None:
    tables = set(sa.inspect(connection).get_table_names())
    required = {"wrong_questions", "quiz_records", "assessment_attempts", "users"}
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(f"F8 wrong-question migration missing tables: {missing}")

    columns = {
        column["name"] for column in sa.inspect(connection).get_columns("wrong_questions")
    }
    if "source_object_id" not in columns:
        connection.execute(sa.text(
            "ALTER TABLE wrong_questions ADD COLUMN source_object_id VARCHAR(64)"
        ))

    # Legacy quiz rows predate canonical question versions. Bind only rows for
    # which the trusted legacy-attempt bridge already provides an exact match.
    connection.execute(sa.text(
        "UPDATE wrong_questions AS w SET source_object_id = ("
        "SELECT a.question_version_id FROM assessment_attempts a "
        "JOIN users u ON u.public_id = a.owner_public_id "
        "WHERE u.username = w.student_id "
        "AND substr(a.idempotency_key, 1, length('legacy-quiz-attempt:' || "
        "COALESCE(w.quiz_record_id, w.source_object_id) || ':')) = "
        "'legacy-quiz-attempt:' || COALESCE(w.quiz_record_id, w.source_object_id) || ':' "
        "ORDER BY a.submitted_at, a.id LIMIT 1) "
        "WHERE COALESCE(w.quiz_record_id, w.source_object_id) IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM assessment_attempts a "
        "JOIN users u ON u.public_id = a.owner_public_id "
        "WHERE u.username = w.student_id "
        "AND substr(a.idempotency_key, 1, length('legacy-quiz-attempt:' || "
        "COALESCE(w.quiz_record_id, w.source_object_id) || ':')) = "
        "'legacy-quiz-attempt:' || COALESCE(w.quiz_record_id, w.source_object_id) || ':')"
    ))
    connection.execute(sa.text("DROP INDEX IF EXISTS ix_wrong_questions_event_object"))

    rows = connection.execute(sa.text(
        "SELECT id, student_id, quiz_record_id, source_event_id, source_object_id, "
        "wrong_reason_category, pinned, notes, created_at "
        "FROM wrong_questions ORDER BY student_id, source_object_id, created_at, id"
    )).mappings().all()
    grouped: dict[tuple[str, str], list[Any]] = {}
    for row in rows:
        note = "" if _machine_exam_note(row["notes"]) else str(row["notes"] or "")
        if note != str(row["notes"] or ""):
            connection.execute(
                sa.text("UPDATE wrong_questions SET notes = '' WHERE id = :id"),
                {"id": row["id"]},
            )
        student_id = str(row["student_id"] or "").strip()
        question_version_id = str(row["source_object_id"] or "").strip()
        if student_id and question_version_id:
            grouped.setdefault((student_id, question_version_id), []).append({**row, "notes": note})

    has_video_links = "wrong_question_video_links" in tables
    for duplicate_rows in grouped.values():
        if len(duplicate_rows) < 2:
            continue
        survivor = duplicate_rows[0]
        duplicate_ids = [row["id"] for row in duplicate_rows[1:]]
        confirmed_reason = next(
            (
                str(row["wrong_reason_category"])
                for row in duplicate_rows
                if row["wrong_reason_category"]
                and row["wrong_reason_category"] != "pending_confirmation"
            ),
            str(survivor["wrong_reason_category"] or "pending_confirmation"),
        )
        preserved_note = next((str(row["notes"]) for row in duplicate_rows if row["notes"]), "")
        connection.execute(
            sa.text(
                "UPDATE wrong_questions SET quiz_record_id = :quiz_record_id, "
                "source_event_id = :source_event_id, wrong_reason_category = :reason, "
                "pinned = :pinned, notes = :notes, created_at = :created_at WHERE id = :id"
            ),
            {
                "id": survivor["id"],
                "quiz_record_id": next(
                    (row["quiz_record_id"] for row in duplicate_rows if row["quiz_record_id"]),
                    None,
                ),
                "source_event_id": next(
                    (row["source_event_id"] for row in duplicate_rows if row["source_event_id"]),
                    None,
                ),
                "reason": confirmed_reason,
                "pinned": any(bool(row["pinned"]) for row in duplicate_rows),
                "notes": preserved_note,
                "created_at": survivor["created_at"],
            },
        )
        if has_video_links:
            connection.execute(
                sa.text(
                    "UPDATE wrong_question_video_links SET wrong_question_id = :survivor_id "
                    "WHERE wrong_question_id IN :duplicate_ids"
                ).bindparams(sa.bindparam("duplicate_ids", expanding=True)),
                {"survivor_id": survivor["id"], "duplicate_ids": duplicate_ids},
            )
        connection.execute(
            sa.text("DELETE FROM wrong_questions WHERE id IN :duplicate_ids").bindparams(
                sa.bindparam("duplicate_ids", expanding=True)
            ),
            {"duplicate_ids": duplicate_ids},
        )

    connection.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_wrong_questions_student_question_version "
        "ON wrong_questions(student_id, source_object_id) "
        "WHERE source_object_id IS NOT NULL AND source_object_id <> ''"
    ))


def _install_f8_note_workspace_schema(connection: Any) -> None:
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if "notes" not in tables:
        raise RuntimeError("F8 note workspace migration missing table: notes")
    columns = {column["name"] for column in inspector.get_columns("notes")}
    for name, ddl in (
        ("lock_version", "ALTER TABLE notes ADD COLUMN lock_version INTEGER NOT NULL DEFAULT 1"),
        ("current_version_number", "ALTER TABLE notes ADD COLUMN current_version_number INTEGER NOT NULL DEFAULT 1"),
        ("ai_suggestion", "ALTER TABLE notes ADD COLUMN ai_suggestion TEXT NOT NULL DEFAULT ''"),
        ("ai_suggestion_metadata", "ALTER TABLE notes ADD COLUMN ai_suggestion_metadata JSON DEFAULT '{}'"),
    ):
        if name not in columns:
            connection.execute(sa.text(ddl))
    connection.execute(sa.text(
        """CREATE TABLE IF NOT EXISTS note_versions (
        id VARCHAR(64) PRIMARY KEY,
        note_id VARCHAR(64) NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
        version_number INTEGER NOT NULL CHECK (version_number >= 1),
        content TEXT NOT NULL,
        tags JSON,
        concepts JSON,
        source VARCHAR(128) NOT NULL DEFAULT 'manual',
        source_metadata JSON,
        change_type VARCHAR(32) NOT NULL DEFAULT 'saved',
        restored_from_version INTEGER,
        event_id VARCHAR(64),
        created_at DATETIME,
        CONSTRAINT uq_note_version_number UNIQUE (note_id, version_number)
        )"""
    ))
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_note_versions_note_id ON note_versions(note_id)",
        "CREATE INDEX IF NOT EXISTS ix_note_versions_event_id ON note_versions(event_id)",
        """CREATE TRIGGER IF NOT EXISTS trg_note_version_immutable_update
        BEFORE UPDATE ON note_versions BEGIN
        SELECT RAISE(ABORT, 'note version is immutable'); END""",
    ):
        connection.execute(sa.text(statement))

    rows = connection.execute(sa.text(
        "SELECT id, content, tags, concepts, source, source_metadata, created_at "
        "FROM notes WHERE NOT EXISTS (SELECT 1 FROM note_versions nv WHERE nv.note_id = notes.id)"
    )).mappings().all()
    for row in rows:
        digest = hashlib.sha256(f"legacy-note-version:{row['id']}:1".encode("utf-8")).hexdigest()[:40]
        connection.execute(
            sa.text(
                "INSERT INTO note_versions(id, note_id, version_number, content, tags, concepts, source, "
                "source_metadata, change_type, created_at) VALUES (:id, :note_id, 1, :content, :tags, "
                ":concepts, :source, :source_metadata, 'legacy_baseline', :created_at)"
            ),
            {
                "id": f"notev-{digest}",
                "note_id": row["id"],
                "content": row["content"] or "",
                "tags": row["tags"] or "[]",
                "concepts": row["concepts"] or "[]",
                "source": row["source"] or "manual",
                "source_metadata": row["source_metadata"] or "{}",
                "created_at": row["created_at"],
            },
        )
    connection.execute(sa.text("UPDATE notes SET lock_version = 1 WHERE lock_version IS NULL OR lock_version < 1"))


def _install_f8_note_restore_pointer_schema(connection: Any) -> None:
    """Separate the current history pointer from the optimistic lock counter."""
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    if "notes" not in tables:
        raise RuntimeError("F8 note restore pointer migration missing table: notes")
    columns = {column["name"] for column in inspector.get_columns("notes")}
    if "current_version_number" not in columns:
        connection.execute(
            sa.text(
                "ALTER TABLE notes ADD COLUMN current_version_number INTEGER NOT NULL DEFAULT 1"
            )
        )
    if "note_versions" in tables:
        connection.execute(
            sa.text(
                "UPDATE notes SET current_version_number = COALESCE("
                "(SELECT MAX(version_number) FROM note_versions WHERE note_versions.note_id = notes.id), 1)"
            )
        )
    else:
        connection.execute(sa.text("UPDATE notes SET current_version_number = 1"))


def _install_f9_marketplace_learning_objects(connection: Any) -> None:
    inspector = sa.inspect(connection)
    if "marketplace_listings" not in set(inspector.get_table_names()):
        raise RuntimeError("F9 marketplace migration missing table: marketplace_listings")
    columns = {column["name"] for column in inspector.get_columns("marketplace_listings")}
    for name, ddl in (
        ("item_type", "ALTER TABLE marketplace_listings ADD COLUMN item_type VARCHAR(32) NOT NULL DEFAULT 'course'"),
        ("source_object_id", "ALTER TABLE marketplace_listings ADD COLUMN source_object_id VARCHAR(128)"),
        ("source_version_id", "ALTER TABLE marketplace_listings ADD COLUMN source_version_id VARCHAR(128)"),
    ):
        if name not in columns:
            connection.execute(sa.text(ddl))
    connection.execute(sa.text(
        "UPDATE marketplace_listings SET item_type = 'course', "
        "source_object_id = COALESCE(source_object_id, course_id), "
        "source_version_id = COALESCE(source_version_id, course_version) "
        "WHERE item_type IS NULL OR item_type = 'course'"
    ))
    DBMarketplacePersonalCopy.__table__.create(connection, checkfirst=True)
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_marketplace_listing_item_search ON marketplace_listings(status,item_type,category,title)",
        "CREATE INDEX IF NOT EXISTS ix_marketplace_copy_owner ON marketplace_personal_copies(recipient_public_id,created_at)",
        "DROP TRIGGER IF EXISTS trg_marketplace_listing_frozen",
        "CREATE TRIGGER trg_marketplace_listing_frozen BEFORE UPDATE OF course_id,course_version,item_type,source_object_id,source_version_id,title,summary,category,tags,snapshot_data,license_snapshot,snapshot_hash,owner_public_id,created_at ON marketplace_listings BEGIN SELECT RAISE(ABORT, 'marketplace listing evidence is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_listing_item_type_insert BEFORE INSERT ON marketplace_listings WHEN NEW.item_type NOT IN ('course','resource','resource_bundle','learning_path') BEGIN SELECT RAISE(ABORT, 'invalid marketplace item type'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_personal_copy_frozen BEFORE UPDATE OF listing_id,recipient_public_id,item_type,copy_object_id,copy_version_id,open_route,listing_snapshot_hash,provenance_snapshot,created_at ON marketplace_personal_copies BEGIN SELECT RAISE(ABORT, 'marketplace personal copy identity is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS trg_marketplace_personal_copy_no_delete BEFORE DELETE ON marketplace_personal_copies BEGIN SELECT RAISE(ABORT, 'marketplace personal copy is immutable'); END",
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
    Migration("20260802_012", "M5 canonical assessment attempts and misconception confirmation", _install_m5_assessment_schema),
    Migration("20260802_013", "M5 learner-confirmed delayed retest scheduling", _install_m5_retest_schedule),
    Migration("20260803_014", "NEXT versioned model cost and worker lease lifecycle", _install_next_cost_worker_schema),
    Migration("20260803_015", "NEXT unified document provenance and precise source locations", _install_next_document_migration_schema),
    Migration("20260803_016", "NEXT owner-scoped memory governance and profile subscriptions", _install_next_memory_governance_schema),
    Migration("20260803_017", "NEXT complete assessment grading and canonical CAT state", _install_next_assessment_complete_schema),
    Migration("20260803_018", "NEXT formal exam lifecycle, review and immutable reports", _install_next_formal_exam_schema),
    Migration("20260803_019", "NEXT owner-scoped offline speech sessions and immutable subtitle segments", _install_next_offline_speech_schema),
    Migration("20260804_020", "NEXT owner-scoped media resources positions and immutable conversations", _install_next_media_context_schema),
    Migration("20260804_021", "NEXT teaching classes groups tasks and immutable course withdrawal impact", _install_next_course_governance_schema),
    Migration("20260804_022", "NEXT explainable immutable teaching analytics period reports", _install_next_teaching_analytics_schema),
    Migration("20260804_023", "NEXT governed content review cases and immutable decisions", _install_next_content_review_schema),
    Migration("20260804_024", "NEXT certification revocation expiry retraining and local notifications", _install_next_certification_lifecycle_schema),
    Migration("20260804_025", "NEXT separated multilevel demonstration review queue", _install_next_multilevel_review_schema),
    Migration("20260804_026", "NEXT frozen synthetic job standard impact and confirmation", _install_next_job_standard_impact_schema),
    Migration("20260804_027", "NEXT explainable privacy-gated enterprise risk reports", _install_next_enterprise_risk_schema),
    Migration("20260804_028", "NEXT immutable course sharing derived copies and upstream decisions", _install_next_course_sharing_schema),
    Migration("20260804_029", "NEXT governed public learning marketplace reports and acquisitions", _install_next_marketplace_schema),
    Migration("20260804_030", "NEXT organization-private resource catalog and policy acquisitions", _install_next_organization_marketplace_schema),
    Migration("20260804_031", "NEXT owner spatial workspace immutable layout history and recovery", _install_next_spatial_workspace_schema),
    Migration("20260804_032", "NEXT verified data plugin registry lifecycle and failure isolation", _install_next_plugin_registry_schema),
    Migration("20260804_033", "NEXT offline reproducible video projects render tasks outputs and recovery", _install_next_video_render_schema),
    Migration("20260804_034", "FC owner scoped imported video assets immutable media and subtitle versions", _install_fc_video_import_schema),
    Migration("20260804_035", "FC immutable wrong question evidence to explanation video links", _install_fc_wrong_question_video_schema),
    Migration("20260804_036", "FC immutable source bound personalized chapter video links", _install_fc_chapter_video_schema),
    Migration("20260804_037", "FC versioned video practice binding weak watch and strong assessment evidence", _install_fc_video_practice_schema),
    Migration("20260804_038", "FC deterministic parameter driven teaching animation versions and recovery", _install_fc_teaching_animation_schema),
    Migration("20260804_039", "FC browser deck stable slides immutable versions playback and exports", _install_fc_web_deck_schema),
    Migration("20260804_040", "FC deterministic local enterprise adapter sessions faults recovery and evidence", _install_fc_local_adapter_schema),
    Migration("20260804_041", "FC typed immutable multimedia resource bundle versions and evidence snapshots", _install_fc_resource_bundle_schema),
    Migration("20260804_042", "FC version bound marketplace comments edit window soft delete reports and moderation audit", _install_fc_marketplace_comment_schema),
    Migration("20260804_043", "FC separate marketplace favorites verified use ratings immutable history and minimum sample aggregation", _install_fc_marketplace_engagement_schema),
    Migration("20260804_044", "FC immutable marketplace impacts idempotent local inbox read and action lifecycle", _install_fc_marketplace_impact_notification_schema),
    Migration("20260804_045", "FC marketplace fork independent versions three way diff and explicit non destructive update decisions", _install_fc_marketplace_fork_schema),
    Migration("20260804_046", "FC immutable explainable marketplace recommendation runs and feature evidence", _install_fc_marketplace_recommendation_schema),
    Migration("20260804_047", "FC owner flashcards immutable content versions source snapshots and recovery", _install_fc_flashcard_schema),
    Migration("20260805_048", "FC local SSO providers immutable mapping versions sessions and decision events", _install_fc_local_sso_schema),
    Migration("20260805_049", "FC synthetic HR mapping preview idempotent projections offboarding and audit", _install_fc_hr_sync_schema),
    Migration("20260805_050", "FC local LMS catalog assignment exchange and immutable candidate grade summaries", _install_fc_local_lms_schema),
    Migration("20260805_051", "FC local LRS immutable statements delivery lifecycle and cmi5 subset sessions", _install_fc_local_lrs_cmi5_schema),
    Migration("20260805_052", "FC signed minimal webhook events replay guard and immutable local receipts", _install_fc_signed_webhook_schema),
    Migration("20260805_053", "FC immutable cross adapter reconciliation snapshots and repair decisions", _install_fc_integration_reconciliation_schema),
    Migration("20260805_054", "FC recoverable seven scenario integration fault drills and immutable evidence", _install_fc_integration_fault_drill_schema),
    Migration("20260805_055", "FC owner scoped evidence derived student competition journey and immutable visits", _install_fc_competition_journey_schema),
    Migration("20260805_056", "FC preserved competition journey expansion for multimedia creation evidence", _expand_fc_competition_journey_types),
    Migration("20260805_057", "FC preserved competition journey expansion for evidence derived teacher workflow", _expand_fc_teacher_journey_type),
    Migration("20260805_058", "FC preserved competition journey expansion for enterprise training lifecycle evidence", _expand_fc_enterprise_journey_type),
    Migration("20260805_059", "FC preserved competition journey expansion and immutable marketplace search proof", _expand_fc_marketplace_journey_type),
    Migration("20260805_060", "FC repair marketplace journey search proof foreign key after SQLite table rebuild", _repair_fc_marketplace_search_proof_fk),
    Migration("20260805_061", "FC preserved competition journey expansion for local integration lifecycle evidence", _expand_fc_integration_journey_type),
    Migration("20260812_062", "F2 evidence classified learning event protocol", _install_f2_learning_event_protocol),
    Migration("20260812_063", "F2 replayable learning aggregation wrong question idempotency", _install_f2_replayable_aggregation),
    Migration("20260812_064", "F2 recoverable legacy object migration mappings", _install_f2_legacy_object_migration),
    Migration("20260812_065", "F3 owner scoped optional onboarding personal evidence", _install_f3_onboarding_personal_evidence),
    Migration("20260812_066", "F3 owner scoped traceable entry diagnostic blueprints", _install_f3_diagnostic_blueprint),
    Migration("20260812_067", "F3 recoverable owner scoped entry diagnostic response drafts", _install_f3_diagnostic_sessions),
    Migration("20260812_068", "F3 diagnostic draft stale response ordering", _install_f3_diagnostic_response_ordering),
    Migration("20260813_069", "F3 immutable diagnostic reports and initial path evidence", _install_f3_diagnostic_reports),
    Migration("20260814_070", "F6 recoverable learner formal exam drafts and frozen generation context", _install_f6_formal_exam_learning_schema),
    Migration("20260815_071", "F7 owner scoped document positions and source selections", _install_f7_document_reader_schema),
    Migration("20260815_072", "F7 owner scoped web source candidates and explicit admission", _install_f7_web_source_candidate_schema),
    Migration("20260815_073", "F7 owner scoped recoverable chat messages and parsed attachments", _install_f7_chat_schema),
    Migration("20260816_074", "F8 one canonical wrong question per learner and question version", _install_f8_canonical_wrong_question_identity),
    Migration("20260816_075", "F8 owner scoped source bound note versions and separate AI suggestions", _install_f8_note_workspace_schema),
    Migration("20260817_076", "F9 typed marketplace learning objects and owner scoped personal copies", _install_f9_marketplace_learning_objects),
    Migration("20260825_077", "F8 note restore pointer separate from lock version", _install_f8_note_restore_pointer_schema),
    Migration("20260829_078", "NOC diagnostic and intelligent exam pending subjective score nullability", _allow_pending_assessment_scores),
)


def apply_registered_migrations(bind: Any) -> list[str]:
    applied_now: list[str] = []
    connection = bind.connect()
    transaction = None
    try:
        if connection.dialect.name == "sqlite":
            # SQLite starts deferred transactions by default, allowing two
            # processes to observe the same migration as pending. Serialize
            # migration discovery and application before reading history.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            transaction = connection.begin()
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
        if transaction is not None:
            transaction.commit()
        else:
            connection.commit()
    except Exception:
        if transaction is not None:
            transaction.rollback()
        else:
            connection.rollback()
        raise
    finally:
        connection.close()
    return applied_now
