from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_user
from app.database import Base, DBModelCall, DBUser
import app.main as main_module
from app.main import app


class Backend:
    model = "note-test-model"

    def __init__(self, output=None, *, error=None):
        self.output = output
        self.error = error

    async def generate(self, system_prompt, user_prompt, *, role):
        if self.error is not None:
            raise self.error
        return self.output


def _exercise(monkeypatch, backend, content):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    async def database_runner(operation, *args):
        return operation(session, *args)

    monkeypatch.setattr(main_module, "run_db_op", database_runner)
    monkeypatch.setattr(
        main_module,
        "build_swarm_from_headers",
        lambda headers: SimpleNamespace(llm=backend),
    )
    app.dependency_overrides[get_current_user] = lambda: DBUser(
        public_id="note-owner-public", username="note-owner",
        hashed_password="test", role="student", is_active=True,
    )
    try:
        response = TestClient(app).post("/api/notes/ai-polish", json={"content": content})
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    return session, response


def test_note_polish_records_owner_and_restores_protected_code(monkeypatch):
    source = "private note body\n```python\nprint('private-code')\n```"
    output = (
        "```mermaid\nmindmap\n  root((\"主题\"))\n```\n"
        "整理后的正文\n[CODE_BLOCK_PLACEHOLDER_0]\n"
        "===TAGS_AND_CONCEPTS===\nTags: machine-learning, notes\n"
        "Concepts: gradient\n========================"
    )
    session, response = _exercise(monkeypatch, Backend(output), source)
    row = session.query(DBModelCall).one()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "print('private-code')" in payload["polished_content"]
    assert payload["tags"] == ["machine-learning", "notes"]
    assert payload["concepts"] == ["gradient"]
    assert row.owner_public_id == "note-owner-public"
    assert row.prompt_version == "legacy_note_polish:1.0"
    assert (row.status, row.error_code) == ("completed", "")
    summary = str(row.input_summary)
    assert "private note body" not in summary
    assert "private-code" not in summary
    assert row.input_summary["protected_code_block_count"] == 1


def test_note_polish_provider_failure_is_audited_and_preserves_source(monkeypatch):
    source = "private fallback note"
    session, response = _exercise(
        monkeypatch, Backend(error=RuntimeError("provider unavailable")), source,
    )
    row = session.query(DBModelCall).one()

    assert response.status_code == 200, response.text
    assert source in response.json()["polished_content"]
    assert "provider unavailable" not in response.json()["polished_content"]
    assert (row.status, row.error_code) == (
        "failed", "note_polish_provider_failed",
    )
    assert source not in str(row.input_summary)
