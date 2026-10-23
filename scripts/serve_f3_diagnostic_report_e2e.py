"""Run the F3-T05 browser fixture on an isolated database and port."""

from __future__ import annotations

import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f3_t05_diagnostic_report"
DB_PATH = OUTPUT_DIR / "f3_t05_runtime.db"
FIXTURE_PATH = OUTPUT_DIR / "fixture.json"
PORT = int(os.getenv("EDUMATRIX_F3_T05_PORT", "8896"))
COURSE_ID = "demo-course-rag-trust-v1"


def prepare_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in (
        "f3_t05_runtime.db",
        "f3_t05_runtime.db-shm",
        "f3_t05_runtime.db-wal",
        "fixture.json",
        "backend.log",
        "report.json",
    ):
        (OUTPUT_DIR / name).unlink(missing_ok=True)
    for screenshot in OUTPUT_DIR.glob("*.png"):
        screenshot.unlink()


def wrong_answer(question_type: str, options: list[str], answer_key: dict) -> dict:
    if question_type == "single_choice":
        expected = str(answer_key.get("choice") or answer_key.get("value") or "A")
        labels = [chr(65 + index) for index in range(max(2, len(options)))]
        return {"choice": next(label for label in labels if label != expected)}
    if question_type == "multiple_choice":
        return {"choices": []}
    if question_type == "true_false":
        return {"value": not bool(answer_key.get("value"))}
    if question_type == "fill_blank":
        blanks = answer_key.get("blanks") or answer_key.get("answers") or [""]
        return {"blanks": ["错误答案"] * len(blanks)}
    return {"text": "高信心但不正确的诊断作答。"}


def seed_fixture() -> dict:
    from app.competition_demo_seed import seed_competition_demo
    from scripts.e2e_student_journey_master_course import DemoModel
    from app.database import (
        DBAssessmentQuestion,
        DBAssessmentQuestionVersion,
        DBUser,
        SessionLocal,
        init_db,
    )
    from app.diagnostic_generation import DiagnosticBlueprintRequest, generate_diagnostic_blueprint
    from app.diagnostic_session import (
        DiagnosticResponseInput,
        save_diagnostic_response,
        start_or_resume_diagnostic_session,
        submit_diagnostic_session,
    )

    init_db()
    session = SessionLocal()
    try:
        seed_competition_demo(session)
        learner = session.query(DBUser).filter_by(username="lzz").one()
        blueprint, _ = generate_diagnostic_blueprint(
            session,
            user=learner,
            request=DiagnosticBlueprintRequest(COURSE_ID, "f3-t05-browser-blueprint-001", 15),
            llm=DemoModel(),
        )
        work, _ = start_or_resume_diagnostic_session(session, user=learner, blueprint_id=blueprint.id)
        unknown_prompt = ""
        unknown_knowledge_point_id = ""
        for index, version_id in enumerate(blueprint.question_version_ids):
            version = session.get(DBAssessmentQuestionVersion, version_id)
            question = session.get(DBAssessmentQuestion, version.question_id)
            answer_key = dict(version.answer_key or {})
            understanding = "clear" if index == 0 else "mostly"
            confidence = 0.92 if index == 0 else 0.72
            if index == len(blueprint.question_version_ids) - 1:
                answer = {"text": "基于课程来源说明当前理解，但等待可靠评分。"}
                unknown_prompt = version.prompt
                unknown_knowledge_point_id = version.primary_knowledge_point_id
            elif index == 0:
                answer = wrong_answer(question.question_type, list(version.options or []), answer_key)
            else:
                answer = answer_key
            save_diagnostic_response(
                session,
                user=learner,
                session_id=work.id,
                question_version_id=version_id,
                response=DiagnosticResponseInput(
                    answer=answer,
                    understanding_level=understanding,
                    duration=35 + index,
                    confidence=confidence,
                    idempotency_key=f"f3-t05-browser-response-{index:03d}",
                    saved_at=datetime(2026, 8, 13, 2, 0, 0) + timedelta(seconds=index),
                ),
            )
        submit_diagnostic_session(
            session,
            user=learner,
            session_id=work.id,
            idempotency_key="f3-t05-browser-submit-001",
        )
        session.commit()
        fixture = {
            "courseId": COURSE_ID,
            "blueprintId": blueprint.id,
            "sessionId": work.id,
            "questionVersionId": blueprint.question_version_ids[0],
            "unknownPrompt": unknown_prompt,
            "unknownKnowledgePointId": unknown_knowledge_point_id,
        }
        FIXTURE_PATH.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return fixture
    finally:
        session.close()


def main() -> None:
    prepare_output()
    os.environ.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "f3-t05-isolated-secret",
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
    with (OUTPUT_DIR / "backend.log").open("w", encoding="utf-8") as log:
        with redirect_stdout(log), redirect_stderr(log):
            fixture = seed_fixture()
            print(json.dumps(fixture, ensure_ascii=False), flush=True)
            import uvicorn

            uvicorn.run(
                "app.main:app",
                host="127.0.0.1",
                port=PORT,
                reload=False,
                log_config=None,
                access_log=False,
                use_colors=False,
            )


if __name__ == "__main__":
    main()
