from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import DatabaseError

from app.database import Base
from app.migrations import (
    _install_f9_marketplace_learning_objects,
    apply_registered_migrations,
)


def _engine(path):
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def _create_legacy_marketplace(connection) -> None:
    connection.execute(text(
        "CREATE TABLE users (public_id VARCHAR(64) PRIMARY KEY)"
    ))
    connection.execute(text(
        "CREATE TABLE courses (id VARCHAR(128) PRIMARY KEY)"
    ))
    connection.execute(text(
        """CREATE TABLE marketplace_listings (
        id VARCHAR(64) PRIMARY KEY,
        course_id VARCHAR(128) NOT NULL REFERENCES courses(id) ON DELETE RESTRICT,
        course_version VARCHAR(64) NOT NULL,
        title VARCHAR(256) NOT NULL,
        summary TEXT NOT NULL,
        category VARCHAR(128) NOT NULL,
        tags JSON NOT NULL,
        snapshot_data JSON NOT NULL,
        license_snapshot JSON NOT NULL,
        snapshot_hash VARCHAR(64) NOT NULL,
        owner_public_id VARCHAR(64) NOT NULL REFERENCES users(public_id) ON DELETE RESTRICT,
        status VARCHAR(24) NOT NULL DEFAULT 'pending',
        lock_version INTEGER NOT NULL DEFAULT 1,
        created_at DATETIME,
        published_at DATETIME,
        withdrawn_at DATETIME
        )"""
    ))
    connection.execute(text(
        "INSERT INTO users(public_id) VALUES ('owner-1'), ('learner-1')"
    ))
    connection.execute(text(
        "INSERT INTO courses(id) VALUES ('course-1')"
    ))
    connection.execute(
        text(
            "INSERT INTO marketplace_listings("
            "id,course_id,course_version,title,summary,category,tags,"
            "snapshot_data,license_snapshot,snapshot_hash,owner_public_id,created_at"
            ") VALUES ("
            "'listing-1','course-1','v1','课程快照','摘要','人工智能',"
            ":tags,:snapshot,:license,'snapshot-1','owner-1',CURRENT_TIMESTAMP)"
        ),
        {
            "tags": json.dumps(["AI"]),
            "snapshot": json.dumps({"course_id": "course-1"}),
            "license": json.dumps({"course_license": "CC BY 4.0"}),
        },
    )


def test_f9_marketplace_migration_upgrades_legacy_listing_and_freezes_copy_identity(tmp_path):
    engine = _engine(tmp_path / "f9-marketplace-upgrade.db")
    with engine.begin() as connection:
        _create_legacy_marketplace(connection)
        _install_f9_marketplace_learning_objects(connection)

    inspector = inspect(engine)
    listing_columns = {column["name"] for column in inspector.get_columns("marketplace_listings")}
    assert {"item_type", "source_object_id", "source_version_id"} <= listing_columns
    assert "marketplace_personal_copies" in inspector.get_table_names()

    with engine.begin() as connection:
        listing = connection.execute(text(
            "SELECT item_type,source_object_id,source_version_id "
            "FROM marketplace_listings WHERE id='listing-1'"
        )).mappings().one()
        assert dict(listing) == {
            "item_type": "course",
            "source_object_id": "course-1",
            "source_version_id": "v1",
        }
        connection.execute(text(
            "INSERT INTO marketplace_personal_copies("
            "id,listing_id,recipient_public_id,item_type,copy_object_id,copy_version_id,"
            "open_route,listing_snapshot_hash,provenance_snapshot,source_status,created_at"
            ") VALUES ("
            "'copy-1','listing-1','learner-1','resource','resource-copy-1','resource-version-1',"
            "'/workspace/resources/handouts/resource-copy-1','snapshot-1',:provenance,"
            "'available',CURRENT_TIMESTAMP)"
        ), {"provenance": json.dumps({"license": "CC BY 4.0"})})

    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE marketplace_personal_copies SET source_status='withdrawn' WHERE id='copy-1'"
        ))
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE marketplace_personal_copies SET copy_object_id='replaced' WHERE id='copy-1'"
            ))
    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.execute(text(
                "DELETE FROM marketplace_personal_copies WHERE id='copy-1'"
            ))

    with engine.connect() as connection:
        copy = connection.execute(text(
            "SELECT copy_object_id,source_status,provenance_snapshot "
            "FROM marketplace_personal_copies WHERE id='copy-1'"
        )).mappings().one()
        assert copy["copy_object_id"] == "resource-copy-1"
        assert copy["source_status"] == "withdrawn"
        assert json.loads(copy["provenance_snapshot"])["license"] == "CC BY 4.0"
        assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


def test_f9_marketplace_migration_is_registered_and_replay_is_noop(tmp_path):
    engine = _engine(tmp_path / "f9-marketplace-fresh.db")
    Base.metadata.create_all(engine)
    applied = apply_registered_migrations(engine)
    assert "20260817_076" in applied
    assert apply_registered_migrations(engine) == []

    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT version FROM schema_migrations WHERE version='20260817_076'"
        )).scalar_one() == "20260817_076"
        assert connection.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()
