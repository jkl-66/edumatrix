from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.competition_demo_seed import seed_competition_demo
from app.crud import load_student_profile
from app.database import Base, DBStudentProfile, DBUser
from app.role_landing import resolve_login_landing


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/auth/login", "headers": []})


def _form(username: str, password: str) -> OAuth2PasswordRequestForm:
    return OAuth2PasswordRequestForm(
        grant_type="password", username=username, password=password,
        scope="", client_id=None, client_secret=None,
    )


def test_server_role_landing_contract_and_competition_student_membership():
    engine, session = _session()
    try:
        seed_competition_demo(session)
        expected = {
            "lzz": "/",
            "teacher": "/teacher/overview",
            "demo-admin": "/admin/system",
            "demo-assistant": "/landing",
            "demo-visitor": "/landing",
        }
        for username, path in expected.items():
            user = session.query(DBUser).filter_by(username=username).one()
            assert resolve_login_landing(session, user) == path

        outside = DBUser(
            public_id="usr-outside-student", username="outside-student",
            hashed_password="x", role="student", display_name="普通学生",
        )
        session.add(outside)
        session.commit()
        assert resolve_login_landing(session, outside) is None
    finally:
        session.close()
        engine.dispose()


def test_login_response_uses_real_role_credentials_and_landing(monkeypatch):
    engine, session = _session()
    try:
        seed_competition_demo(session)

        async def fake_run_db_op(func, *args, **kwargs):
            return func(session, *args, **kwargs)

        monkeypatch.setattr(main_module, "run_db_op", fake_run_db_op)
        cases = [
            ("lzz", "404404aA", "student", "/"),
            ("teacher", "admin123", "teacher", "/teacher/overview"),
            ("demo-admin", "EduMatrix-Demo-2026", "admin", "/admin/system"),
            ("demo-assistant", "EduMatrix-Demo-2026", "assistant", "/landing"),
            ("demo-visitor", "EduMatrix-Demo-2026", "visitor", "/landing"),
        ]
        for username, password, role, landing in cases:
            response = asyncio.run(main_module.login_for_access_token(_request(), _form(username, password)))
            assert response["username"] == username
            assert response["role"] == role
            assert response["landing_path"] == landing
            assert response["access_token"]
    finally:
        session.close()
        engine.dispose()


def test_competition_seed_respects_immediate_sqlite_foreign_keys(tmp_path: Path):
    database_path = tmp_path / "competition-demo-fk.db"
    engine = create_engine(
        f"sqlite:///{database_path}", connect_args={"check_same_thread": False},
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(bind=connection)
    session = sessionmaker(bind=engine)()
    try:
        seed_competition_demo(session)
        profiles = session.query(DBStudentProfile).order_by(DBStudentProfile.student_id).all()
        assert len(profiles) == 15
        for row in profiles:
            profile = load_student_profile(session, row.student_id)
            assert profile.profile_evidence
            assert profile.profile_evidence[0].source.value == "performance_signal"
        main_module._seed_demo_class(session)
        assert session.query(DBStudentProfile).count() == 15
        violations = session.connection().exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        assert violations == []
    finally:
        session.close()
        engine.dispose()
