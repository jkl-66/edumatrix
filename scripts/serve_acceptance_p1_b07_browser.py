"""Serve FB-07 browser evidence from a copied isolated database."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVIDENCE_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "acceptance_feedback" / "P1-B07"
SOURCE_DB = EVIDENCE_DIR / "P1-B07_runtime.db"
BROWSER_DB = EVIDENCE_DIR / "P1-B07_browser_runtime.db"
FIXTURE_PATH = EVIDENCE_DIR / "browser_fixture.json"
PORT = int(os.getenv("EDUMATRIX_P1_B07_PORT", "8917"))


def _copy_database() -> None:
    if not SOURCE_DB.exists():
        raise RuntimeError("run the FB-07 real-model evidence script before browser evidence")
    for path in (BROWSER_DB, Path(f"{BROWSER_DB}-wal"), Path(f"{BROWSER_DB}-shm")):
        if path.exists():
            path.unlink()
    shutil.copy2(SOURCE_DB, BROWSER_DB)


def _prepare_legacy_fixture() -> dict[str, str]:
    from app.database import (
        DBDiagnosticBlueprint,
        DBDiagnosticReport,
        DBDiagnosticResponseDraft,
        DBDiagnosticSession,
        DBUser,
        SessionLocal,
        init_db,
    )
    from app.diagnostic_report import generate_diagnostic_report
    from app.diagnostic_session import (
        DiagnosticResponseInput,
        save_diagnostic_response,
        start_or_resume_diagnostic_session,
        submit_diagnostic_session,
    )

    init_db()
    session = SessionLocal()
    try:
        learner = session.query(DBUser).filter_by(username="lzz").one()
        ready_report = session.query(DBDiagnosticReport).filter_by(owner_public_id=learner.public_id).first()
        ready_session = session.get(DBDiagnosticSession, ready_report.session_id)
        ready_blueprint = session.get(DBDiagnosticBlueprint, ready_session.blueprint_id)
        legacy = session.query(DBDiagnosticBlueprint).filter_by(
            owner_public_id=learner.public_id,
            course_id=ready_blueprint.course_id,
            idempotency_key="p1-b07-browser-legacy-blueprint",
        ).first()
        if legacy is None:
            legacy = DBDiagnosticBlueprint(
                owner_public_id=learner.public_id,
                course_id=ready_blueprint.course_id,
                idempotency_key="p1-b07-browser-legacy-blueprint",
                version_number=1,
                status="ready",
                profile_snapshot_id=ready_blueprint.profile_snapshot_id,
                question_version_ids=list(ready_blueprint.question_version_ids or []),
                knowledge_point_coverage=list(ready_blueprint.knowledge_point_coverage or []),
                difficulty_bands=dict(ready_blueprint.difficulty_bands or {}),
                source_refs=list(ready_blueprint.source_refs or []),
                review_decision={"status": "approved", "decisionSummary": "FB-07 legacy browser compatibility fixture."},
                generation_stages=[{"key": "legacy", "label": "历史题组", "status": "completed"}],
                question_count=ready_blueprint.question_count,
                estimated_minutes=ready_blueprint.estimated_minutes,
                content_hash="p1-b07-browser-legacy".ljust(64, "0"),
            )
            session.add(legacy)
            session.flush()

        legacy_work, created = start_or_resume_diagnostic_session(
            session, user=learner, blueprint_id=legacy.id,
        )
        if created:
            ready_responses = {
                item.question_version_id: item
                for item in session.query(DBDiagnosticResponseDraft).filter_by(session_id=ready_session.id).all()
            }
            now = datetime.now(timezone.utc)
            for index, question_version_id in enumerate(legacy.question_version_ids or []):
                source = ready_responses[question_version_id]
                save_diagnostic_response(
                    session,
                    user=learner,
                    session_id=legacy_work.id,
                    question_version_id=question_version_id,
                    response=DiagnosticResponseInput(
                        answer=dict(source.answer or {}),
                        understanding_level=source.understanding_level,
                        duration=source.duration_seconds,
                        confidence=source.confidence,
                        idempotency_key=f"p1-b07-browser-legacy-response-{index:02d}",
                        saved_at=now,
                    ),
                )
            submit_diagnostic_session(
                session,
                user=learner,
                session_id=legacy_work.id,
                idempotency_key="p1-b07-browser-legacy-submit",
            )
        legacy_report, _ = generate_diagnostic_report(
            session,
            user=learner,
            session_id=legacy_work.id,
            idempotency_key="p1-b07-browser-legacy-report",
        )
        session.commit()
        return {
            "courseId": ready_blueprint.course_id,
            "readyBlueprintId": ready_blueprint.id,
            "readyQuestionVersionId": ready_blueprint.question_version_ids[0],
            "readyReportId": ready_report.id,
            "legacyBlueprintId": legacy.id,
            "legacyQuestionVersionId": legacy.question_version_ids[0],
            "legacyReportId": legacy_report.id,
        }
    finally:
        session.close()


def main() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    _copy_database()
    os.environ.update({
        "EDUMATRIX_DB_PATH": str(BROWSER_DB),
        "EDUMATRIX_AUTH_SECRET_KEY": "p1-b07-browser-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
    })
    fixture = _prepare_legacy_fixture()
    FIXTURE_PATH.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")

    from app.main import app

    @app.middleware("http")
    async def fb07_evidence_delay(request, call_next):
        if request.url.path.endswith("/report") and request.headers.get("x-fb07-delay-ms"):
            await asyncio.sleep(min(3.0, int(request.headers["x-fb07-delay-ms"]) / 1000))
        return await call_next(request)

    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=PORT,
        reload=False,
        log_config=None,
        access_log=False,
        use_colors=False,
    )


if __name__ == "__main__":
    main()
