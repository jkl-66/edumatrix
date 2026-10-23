from __future__ import annotations

import json
import sqlite3

import pytest
from sqlalchemy import create_engine, inspect, text

from app.auth import get_password_hash
from app.backup import create_backup, restore_backup
from app.database import Base, DBEvaluationCase, DBKnowledgeDocument, DBStudentProfile, DBUser, SessionLocal
from app.identity import new_public_id
from app.legacy_adapter import LegacyDataAdapter
from app.migrations import MIGRATIONS, apply_registered_migrations


def test_legacy_adapter_projects_without_mutating_legacy_rows():
    with SessionLocal() as session:
        student = DBUser(username=new_public_id("m1-legacy"), hashed_password=get_password_hash("test-password"))
        session.add(student)
        session.flush()
        session.add(DBStudentProfile(student_id=student.username))
        session.flush()
        document = DBKnowledgeDocument(
            id=new_public_id("legacy-doc"), student_id=student.username,
            filename="legacy.md", file_type="md", title="Legacy", content="# body"
        )
        session.add(document)
        session.commit()
        before = session.query(DBKnowledgeDocument).filter_by(id=document.id).one().content
        projected = LegacyDataAdapter(session).knowledge_documents(student.username)
        after = session.query(DBKnowledgeDocument).filter_by(id=document.id).one().content
        assert projected[0]["object_type"] == "source_document"
        assert projected[0]["legacy_id"] == document.id
        assert before == after


def test_backup_manifest_and_restore_verify_checksums(tmp_path):
    source_file = tmp_path / "materials" / "readme.txt"
    source_file.parent.mkdir()
    source_file.write_text("backup material", encoding="utf-8")
    archive = tmp_path / "edumatrix-backup.zip"
    create_backup(archive, file_roots=[source_file])
    target = tmp_path / "restored"
    manifest = restore_backup(archive, target)
    assert manifest["format"] == "edumatrix-backup-v1"
    assert (target / "database" / "database.sqlite3").exists()
    assert (target / "files" / "materials" / "readme.txt").read_text(encoding="utf-8") == "backup material"


def test_registered_migration_history_is_idempotent_and_checksumed():
    from app.database import engine
    first = apply_registered_migrations(engine)
    second = apply_registered_migrations(engine)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT version, checksum FROM schema_migrations ORDER BY version")).fetchall()
    assert second == []
    assert len(rows) >= 2
    assert all(len(row.checksum) == 64 for row in rows)


def test_database_triggers_reject_invalid_state():
    from app.database import engine
    with pytest.raises(Exception):
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO users(public_id, username, hashed_password, role) VALUES (:id,:name,:pw,:role)"),
                {"id": new_public_id("usr"), "name": new_public_id("invalid"), "pw": "hash", "role": "root"},
            )


def test_clean_database_migrations_and_checksum_tampering_failure(tmp_path):
    clean_engine = create_engine(f"sqlite:///{tmp_path / 'clean-m1.db'}")
    Base.metadata.create_all(clean_engine)
    applied = apply_registered_migrations(clean_engine)
    assert applied == [migration.version for migration in MIGRATIONS]
    tables = set(inspect(clean_engine).get_table_names())
    assert {
        "artifacts", "evaluation_cases", "evaluation_annotations", "evaluation_reports",
        "organizations", "training_cohorts", "profile_evidence_items",
    } <= tables
    with clean_engine.begin() as connection:
        connection.execute(text(
            "UPDATE schema_migrations SET checksum='tampered' WHERE version='20260723_001'"
        ))
    with pytest.raises(RuntimeError, match="Migration history changed"):
        apply_registered_migrations(clean_engine)
    clean_engine.dispose()


def test_registered_migrations_are_safe_under_concurrent_startup(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    database_path = tmp_path / "concurrent-startup.db"
    clean_engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"timeout": 30},
    )
    Base.metadata.create_all(clean_engine)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: apply_registered_migrations(clean_engine), range(4)))

    with clean_engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT version, COUNT(*) AS count FROM schema_migrations GROUP BY version"
        )).fetchall()
        integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()

    assert sorted(len(result) for result in results) == [0, 0, 0, len(MIGRATIONS)]
    assert len(rows) == len(MIGRATIONS)
    assert {row.version for row in rows} == {migration.version for migration in MIGRATIONS}
    assert all(row.count == 1 for row in rows)
    assert integrity == "ok"
    clean_engine.dispose()


def test_evaluation_cases_are_immutable_at_database_layer():
    from app.m1_evidence import seed_m0_evaluation_cases, seed_rag_domain_pack
    with SessionLocal() as session:
        domain = seed_rag_domain_pack(session)
        seed_m0_evaluation_cases(session, domain["domain_version_id"])
        case = session.query(DBEvaluationCase).order_by(DBEvaluationCase.id).first()
        case_id = case.id
        original = case.content_hash
        case.content_hash = "0" * 64
        with pytest.raises(Exception, match="evaluation case is immutable"):
            session.commit()
        session.rollback()
        case = session.query(DBEvaluationCase).filter_by(id=case_id).one()
        assert case.content_hash == original
        session.delete(case)
        with pytest.raises(Exception, match="evaluation case is immutable"):
            session.commit()
        session.rollback()
