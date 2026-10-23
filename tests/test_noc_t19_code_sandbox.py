from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from app.database import DBCodeExecution, DBStudentProfile, DBUser, SessionLocal
import pytest

from app.resource_bundles import ResourceBundleError, _llm_resource_content, _real_model_payload_async
from app.main import app  # noqa: F401 - keeps the route import contract exercised
from code_exec_api import SANDBOX_RUNNER, run_code


def _manifest() -> dict:
    return {
        "context": {
            "course_title": "机器学习导论",
            "knowledge_point_title": "混合检索",
        },
        "input_snapshot": {
            "source_snapshots": {
                "code_sandbox": [{"source_ref_id": "ref-retrieval"}],
            },
        },
    }


def _steps() -> list[dict[str, str]]:
    return [
        {
            "title": f"步骤 {index}",
            "instruction": "按课程来源执行本步骤。",
            "expectedResult": "得到可核对的结果。",
            "errorGuidance": "回到来源检查前提。",
        }
        for index in range(1, 5)
    ]


def test_legacy_run_returns_execution_when_profile_is_not_initialized(monkeypatch):
    username = f"noc-t19-no-profile-{uuid.uuid4().hex[:10]}"
    user = DBUser(username=username, role="student")
    monkeypatch.setattr(SANDBOX_RUNNER, "mode", "trusted_local")

    result = asyncio.run(run_code({"code": "print(6 * 7)", "language": "python"}, user))

    assert result["output"].strip() == "42"
    assert result["error"] == ""
    assert result["history_saved"] is False
    assert result["history_status"] == "student_profile_not_initialized"
    assert result["canonical_evidence"] is None


def test_legacy_syntax_error_has_explicit_unsaved_history_status():
    username = f"noc-t19-syntax-{uuid.uuid4().hex[:10]}"
    user = DBUser(username=username, role="student")

    result = asyncio.run(run_code({"code": "def broken(:\n    pass", "language": "python"}, user))

    assert "语法错误" in result["error"]
    assert result["history_saved"] is False
    assert result["history_status"] == "not_saved_syntax_error"
    assert result["canonical_evidence"] is None


def test_legacy_run_keeps_history_and_non_mastery_evidence_with_profile():
    username = f"noc-t19-profile-{uuid.uuid4().hex[:10]}"
    public_id = f"usr-{uuid.uuid4().hex[:16]}"
    with SessionLocal() as db:
        user = DBUser(public_id=public_id, username=username, hashed_password="test", role="student")
        db.add_all([user, DBStudentProfile(student_id=username)])
        db.commit()

    try:
        result = asyncio.run(run_code(
            {"code": "print('saved')", "language": "python"},
            DBUser(public_id=public_id, username=username, role="student"),
        ))
        assert result["history_saved"] is True
        assert result["history_status"] == "saved"
        with SessionLocal() as db:
            row = db.get(DBCodeExecution, result["exec_id"])
            assert row is not None and row.student_id == username
    finally:
        with SessionLocal() as db:
            row = db.get(DBStudentProfile, username)
            if row is not None:
                db.delete(row)
            owner = db.query(DBUser).filter_by(username=username).first()
            if owner is not None:
                db.delete(owner)
            db.commit()


def test_generated_code_retries_once_with_same_model_when_validate_code_rejects():
    calls: list[tuple[str, str]] = []
    invalid = {
        "summary": "模型摘要",
        "learningGoal": "理解混合检索",
        "narrative": "依据课程来源生成的正文。",
        "practiceSteps": _steps(),
        "starterCode": "import os\nos.system('echo unsafe')",
        "requiredChecks": [{"id": "stdout", "label": "输出", "kind": "stdout_contains", "expectedText": "ok"}],
    }
    corrected = {
        **invalid,
        "starterCode": "from collections import Counter\nprint(Counter(['keyword', 'vector']))",
    }

    class Backend:
        async def generate(self, system, user, *, role):
            calls.append((system, role))
            return json.dumps(invalid if len(calls) == 1 else corrected, ensure_ascii=False)

    result = asyncio.run(_real_model_payload_async(
        Backend(),
        resource_type="code_sandbox",
        item={"title": "混合检索实验"},
        manifest=_manifest(),
        source_snapshots=[{
            "source_ref_id": "ref-retrieval",
            "title": "课程教材",
            "location_label": "第 1 节",
            "quote": "混合检索结合关键词与向量检索。",
        }],
    ))

    assert result["starterCode"] == corrected["starterCode"]
    assert len(calls) == 2
    assert "starterCode 无法在代码沙盒中执行" in calls[1][0]
    assert calls[0][1] == calls[1][1] == "resource_generator"


def test_generated_code_stops_after_one_correction_when_model_remains_invalid():
    calls: list[str] = []
    payload = {
        "summary": "模型摘要",
        "learningGoal": "理解混合检索",
        "narrative": "依据课程来源生成的正文。",
        "practiceSteps": _steps(),
        "starterCode": "import os\nprint('unsafe')",
        "requiredChecks": [{"id": "stdout", "label": "输出", "kind": "stdout_contains", "expectedText": "ok"}],
    }

    class Backend:
        async def generate(self, system, user, *, role):
            calls.append(system)
            return json.dumps(payload, ensure_ascii=False)

    with pytest.raises(ResourceBundleError) as exc_info:
        asyncio.run(_real_model_payload_async(
            Backend(),
            resource_type="code_sandbox",
            item={"title": "混合检索实验"},
            manifest=_manifest(),
            source_snapshots=[{"source_ref_id": "ref-retrieval", "title": "教材", "location_label": "第 1 节", "quote": "混合检索"}],
        ))
    assert len(calls) == 2
    assert exc_info.value.code == "resource_generation.model_output_invalid"
    assert "starterCode 无法在代码沙盒中执行" in str(exc_info.value)


def test_final_code_sandbox_content_check_rejects_invalid_starter_code():
    with pytest.raises(ResourceBundleError) as exc_info:
        _llm_resource_content(
            resource_type="code_sandbox",
            item={"title": "混合检索实验"},
            manifest=_manifest(),
            source_snapshots=[{"source_ref_id": "ref-retrieval", "title": "教材", "location_label": "第 1 节", "quote": "混合检索"}],
            linked_resource_ids=[],
            llm_payload={
                "summary": "模型摘要",
                "learningGoal": "理解混合检索",
                "narrative": "依据课程来源生成的正文。",
                "practiceSteps": _steps(),
                "starterCode": "def broken(:\n    pass",
                "requiredChecks": [{"id": "stdout", "label": "输出", "kind": "stdout_contains", "expectedText": "ok"}],
            },
        )
    assert exc_info.value.code == "resource_generation.model_output_invalid"
    assert "未通过可执行性检查" in str(exc_info.value)


def test_validate_code_rejects_invalid_generated_code_without_local_rewrite():
    from app.code_sandbox import validate_code

    assert validate_code("import os\nprint('unsafe')")
    assert validate_code("def broken(:\n    pass")
    assert validate_code("from collections import Counter\nprint(Counter(['a']))") is None


def test_legacy_sandbox_components_extract_structured_error_messages():
    root = Path(__file__).resolve().parents[1]
    visualizer = (root / "frontend/src/components/SandboxVisualizer.vue").read_text(encoding="utf-8")
    console = (root / "frontend/src/components/SandboxConsole.vue").read_text(encoding="utf-8")

    for source in (visualizer, console):
        assert "function readableRunError" in source
        assert "detail.message" in source
        assert "detail.error" in source
        assert "[object Object]" not in source
