"""Produce FB-07 real-model evidence in an isolated SQLite database."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import (  # noqa: E402
    Base,
    DBAssessmentAttempt,
    DBDiagnosticReport,
    DBLearningEvent,
    DBModelCall,
    DBProfileSnapshot,
)
from app.diagnostic_report import diagnostic_report_payload, generate_diagnostic_report  # noqa: E402
from llm_client import build_async_llm  # noqa: E402
from tests.test_f3_diagnostic_report import _submitted_diagnostic  # noqa: E402


EVIDENCE_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "acceptance_feedback" / "P1-B07"
DB_PATH = EVIDENCE_DIR / "P1-B07_runtime.db"
REPORT_PATH = EVIDENCE_DIR / "real_deepseek_explanations.json"


def _write_report(payload: dict) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove_isolated_database() -> None:
    for path in (DB_PATH, Path(f"{DB_PATH}-wal"), Path(f"{DB_PATH}-shm")):
        if path.exists():
            path.unlink()


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    _remove_isolated_database()
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()

    try:
        learner, blueprint, work, _ = _submitted_diagnostic(session)
        blueprint.generation_stages = [{"key": "p1_b05", "label": "真实生成", "status": "completed"}]
        session.commit()
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

        row, created = generate_diagnostic_report(
            session,
            user=learner,
            session_id=work.id,
            idempotency_key="p1-b07-real-deepseek-report-20260824",
            llm=llm,
        )
        session.commit()
        payload = diagnostic_report_payload(session, user=learner, row=row)
        public_text = json.dumps(payload, ensure_ascii=False).lower()
        model_calls = session.query(DBModelCall).filter_by(owner_public_id=learner.public_id).all()
        items = payload["evidence"]
        if not created or payload["evaluation"]["status"] != "completed":
            raise RuntimeError("real diagnostic explanation report was not completed")
        if payload["evaluation"]["completedCount"] != len(items):
            raise RuntimeError("real diagnostic explanation count does not match report evidence")
        for item in items:
            evaluation = item.get("evaluation") or {}
            allowed_sources = {source["id"] for source in item.get("sources", [])}
            if not str(evaluation.get("claim", "")).strip():
                raise RuntimeError(f"missing claim for {item['questionVersionId']}")
            if not str(item.get("judgmentBasis", "")).strip() or not str(item.get("explanation", "")).strip():
                raise RuntimeError(f"missing generated explanation for {item['questionVersionId']}")
            if not set(evaluation.get("sourceRefIds", [])).issubset(allowed_sources):
                raise RuntimeError(f"source mismatch for {item['questionVersionId']}")

        integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
        foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()
        report = {
            "schemaVersion": "p1-b07.real-deepseek-evidence.v1",
            "status": "passed",
            "isolatedDatabase": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
            "modelPolicy": {
                "provider": "openai-compatible",
                "model": getattr(llm, "model", ""),
                "thinking": getattr(llm, "thinking_mode", ""),
                "reasoningEffort": getattr(llm, "reasoning_effort", ""),
                "allowFallback": False,
                "backendClass": llm.__class__.__name__,
            },
            "report": {
                "id": row.id,
                "created": created,
                "evaluationStatus": payload["evaluation"]["status"],
                "questionCount": len(items),
                "completedCount": payload["evaluation"]["completedCount"],
                "model": payload["evaluation"]["model"],
                "itemBindings": [
                    {
                        "questionVersionId": item["questionVersionId"],
                        "attemptId": item["attemptId"],
                        "status": item["evaluation"]["status"],
                        "confidence": item["evaluation"]["confidence"],
                        "sourceRefIds": item["evaluation"]["sourceRefIds"],
                        "sourceSubsetValid": set(item["evaluation"]["sourceRefIds"]).issubset(
                            {source["id"] for source in item["sources"]}
                        ),
                        "claimLength": len(item["evaluation"]["claim"]),
                        "judgmentBasisLength": len(item["judgmentBasis"]),
                        "explanationLength": len(item["explanation"]),
                    }
                    for item in items
                ],
            },
            "persistence": {
                "reportCount": session.query(DBDiagnosticReport).filter_by(session_id=work.id).count(),
                "attemptCount": session.query(DBAssessmentAttempt).filter(
                    DBAssessmentAttempt.id.in_(row.attempt_ids)
                ).count(),
                "profilesBefore": before_profiles,
                "profilesAfter": session.query(DBProfileSnapshot).filter_by(
                    owner_public_id=learner.public_id
                ).count(),
                "learningEventsBefore": before_events,
                "learningEventsAfter": session.query(DBLearningEvent).filter_by(
                    owner_public_id=learner.public_id
                ).count(),
            },
            "modelCalls": [
                {
                    "id": call.id,
                    "traceId": call.trace_id,
                    "status": call.status,
                    "provider": call.provider,
                    "model": call.model,
                    "capability": call.capability,
                    "inputSummary": call.input_summary,
                }
                for call in model_calls
            ],
            "publicPayloadPrivateFieldsAbsent": not any(
                token in public_text for token in ("reasoning_content", "system_prompt", "api_key", "raw_response")
            ),
            "database": {"integrityCheck": integrity, "foreignKeyViolationCount": len(foreign_keys)},
        }
        _write_report(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        session.rollback()
        _write_report({
            "schemaVersion": "p1-b07.real-deepseek-evidence.v1",
            "status": "failed",
            "errorType": exc.__class__.__name__,
            "error": str(exc),
            "modelPolicy": {
                "model": "deepseek-v4-flash",
                "thinking": "enabled",
                "reasoningEffort": "max",
                "allowFallback": False,
            },
        })
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
