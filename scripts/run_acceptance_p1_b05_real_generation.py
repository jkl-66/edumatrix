"""Run the P1-B05 real-model diagnostic generation in an isolated SQLite database.

This is evidence production only.  It never uses the formal database and never
records private prompts, API credentials, reasoning content, or answer keys in
the public JSON summary.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.database as database
from app.competition_demo_seed import seed_competition_demo
from app.database import (
    Base,
    DBAssessmentQuestionVersion,
    DBLearningEvent,
    DBModelCall,
    DBProfileSnapshot,
    DBUser,
)
from app.diagnostic_generation import (
    DiagnosticBlueprintRequest,
    diagnostic_blueprint_payload,
    generate_diagnostic_blueprint,
)
from llm_client import build_async_llm


EVIDENCE_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "acceptance_feedback" / "P1-B05"
DB_PATH = EVIDENCE_DIR / "P1-B05_runtime.db"
REPORT_PATH = EVIDENCE_DIR / "real_deepseek_generation.json"
COURSE_ID = "demo-course-rag-trust-v1"


def _write_report(payload: dict) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{DB_PATH}{suffix}")
        if sidecar.exists():
            sidecar.unlink()

    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()

    # The gateway's model-call lifecycle normally opens the formal SessionLocal.
    # Redirect only this process to the isolated session so no official DB row is
    # touched while retaining the same audited gateway path.
    async def isolated_run_db_op(func, *args, **kwargs):
        return func(session, *args, **kwargs)

    database.run_db_op = isolated_run_db_op

    try:
        seed_competition_demo(session)
        session.commit()
        learner = session.query(DBUser).filter_by(username="lzz").one()
        before_profiles = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).count()
        before_events = session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count()

        llm = build_async_llm(
            provider="openai",
            model="deepseek-v4-flash",
            thinking_mode="enabled",
            reasoning_effort="max",
            allow_fallback=False,
        )
        if llm.__class__.__name__ != "AsyncOpenAIChatLLM":
            raise RuntimeError(f"unexpected real backend: {llm.__class__.__name__}")

        blueprint, created = generate_diagnostic_blueprint(
            session,
            user=learner,
            request=DiagnosticBlueprintRequest(
                COURSE_ID,
                "p1-b05-real-deepseek-15-20260824",
                15,
            ),
            llm=llm,
        )
        session.commit()
        public_payload = diagnostic_blueprint_payload(session, blueprint)
        serialized = json.dumps(public_payload, ensure_ascii=False).lower()
        profile_row = session.get(DBProfileSnapshot, blueprint.profile_snapshot_id)
        model_calls = session.query(DBModelCall).filter_by(owner_public_id=learner.public_id).all()
        report = {
            "schemaVersion": "p1-b05.real-deepseek-evidence.v1",
            "status": "passed",
            "isolatedDatabase": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
            "created": created,
            "modelPolicy": {
                "provider": "openai-compatible",
                "model": getattr(llm, "model", ""),
                "thinking": getattr(llm, "thinking_mode", ""),
                "reasoningEffort": getattr(llm, "reasoning_effort", ""),
                "allowFallback": False,
                "backendClass": llm.__class__.__name__,
            },
            "profile": {
                "beforeCount": before_profiles,
                "afterCount": session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).count(),
                "snapshotId": blueprint.profile_snapshot_id,
                "profileVersion": profile_row.profile_version if profile_row else None,
            },
            "learningEvents": {
                "beforeCount": before_events,
                "afterCount": session.query(DBLearningEvent).filter_by(owner_public_id=learner.public_id).count(),
            },
            "blueprint": {
                "id": blueprint.id,
                "questionCount": blueprint.question_count,
                "payloadQuestionCount": len(public_payload["questions"]),
                "questionTypes": sorted({item["questionType"] for item in public_payload["questions"]}),
                "diagnosticKinds": sorted({item["diagnosticKind"] for item in public_payload["questions"]}),
                "sourceRefCount": len(blueprint.source_refs),
                "knowledgePointCount": len(blueprint.knowledge_point_coverage),
                "reviewStatus": blueprint.review_decision.get("status"),
                "reviewModel": blueprint.review_decision.get("model"),
            },
            "modelCalls": [
                {
                    "id": call.id,
                    "status": call.status,
                    "provider": call.provider,
                    "model": call.model,
                    "capability": call.capability,
                    "inputSummary": call.input_summary,
                }
                for call in model_calls
            ],
            "publicAnswerHidden": not any(
                token in serialized for token in ("answer_key", "reference_answer", "scoring_rule")
            ),
        }
        _write_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        session.rollback()
        _write_report({
            "schemaVersion": "p1-b05.real-deepseek-evidence.v1",
            "status": "failed",
            "errorType": exc.__class__.__name__,
            "error": str(exc),
            "modelPolicy": {
                "model": "deepseek-v4-flash",
                "thinking": "enabled",
                "reasoningEffort": "max",
                "allowFallback": False,
            },
            "questionRowsAfterRollback": session.query(DBAssessmentQuestionVersion).count(),
        })
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
