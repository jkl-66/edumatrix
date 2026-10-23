from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.diagnostic_api as diagnostic_api
from app.auth import get_current_user
from app.database import Base, DBCourse, DBUser
from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def test_preflight_accepts_frontend_query_string_and_keeps_invalid_count_blocked(monkeypatch):
    engine, db = _session()
    user = DBUser(
        public_id="usr-noc-t08",
        username="noc-t08",
        hashed_password="unused",
        role="student",
        is_active=True,
    )
    db.add_all([
        user,
        DBCourse(
            id="course-noc-t08",
            version="1",
            title="入学诊断测试课程",
            status="published",
            visibility="public",
            manifest_version="1",
        ),
    ])
    db.commit()

    async def isolated_run_db_op(operation, *args, **kwargs):
        return operation(db, *args, **kwargs)

    monkeypatch.setattr(diagnostic_api, "run_db_op", isolated_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    try:
        valid = client.get(
            "/api/v1/diagnostics/preflight",
            params={"course_id": "course-noc-t08", "question_count": "15", "self_rating": "foundation"},
        )
        assert valid.status_code == 200, valid.text
        assert valid.json()["requestedQuestionCount"] == 15
        assert valid.json()["canGenerate"] is False
        assert any("画像" in blocker for blocker in valid.json()["blockers"])

        invalid = client.get(
            "/api/v1/diagnostics/preflight",
            params={"course_id": "course-noc-t08", "question_count": "10", "self_rating": "foundation"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "diagnostic_question_count_invalid"
        assert "15、20 或 25" in invalid.json()["detail"]["message"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        db.close()
        engine.dispose()


def test_entry_diagnostic_uses_shared_error_text_and_never_renders_raw_error_object():
    entry = (ROOT / "frontend/src/views/EntryDiagnostic.vue").read_text(encoding="utf-8")
    common = (ROOT / "frontend/src/api/common.js").read_text(encoding="utf-8")
    assert "errorMessageText" in entry
    assert "errorMessageText(detail" in entry
    assert "errorMessageText(item.error" in entry
    assert "[object Object]" in entry
    assert "export function errorMessageText" in common
    assert "'msg'" in common
