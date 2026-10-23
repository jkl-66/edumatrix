from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import (
    Base,
    DBCourse,
    DBCourseMembership,
    DBOnboardingPersonalEvidence,
    DBOnboardingSession,
    DBOnboardingTurn,
    DBProfileSnapshot,
    DBStudentProfile,
    DBUser,
)
from app.profile_onboarding import (
    DIMENSIONS,
    confirm_personal_evidence,
    confirm_turn,
    discard_personal_evidence,
    finalize_initial_profile,
    get_or_create_session,
    record_turn,
    session_payload,
    upload_personal_evidence,
)
from app.auth import get_current_user
from app.main import app


ROOT = Path(__file__).resolve().parents[1]


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def _learner(db, suffix: str = "main"):
    user = DBUser(
        public_id=f"usr-f3-onboarding-{suffix}",
        username=f"f3-onboarding-{suffix}",
        hashed_password="not-used",
        role="student",
        display_name="画像测试学生",
    )
    course = DBCourse(
        id=f"course-f3-onboarding-{suffix}",
        version="1",
        title="机器学习导论",
        status="published",
        manifest_version="1",
    )
    db.add_all([user, course])
    db.flush()
    db.add(DBCourseMembership(
        course_id=course.id,
        user_public_id=user.public_id,
        role="student",
        status="active",
    ))
    db.add(DBStudentProfile(student_id=user.username, target_course=course.title))
    db.commit()
    return user


def _confirm_current(db, user, turn_id: str, answer: str):
    session = get_or_create_session(db, user)
    result = record_turn(
        db,
        user,
        turn_id=turn_id,
        question_dimension=session.current_dimension,
        user_answer=answer,
    )
    turn = next(item for item in result["turns"] if item["turnId"] == turn_id)
    fields = {
        item["key"]: item["value"].split("\n") if item.get("kind") == "list" else item["value"]
        for item in turn["extractedCandidates"]["fields"]
    }
    return confirm_turn(db, user, turn_id=turn_id, fields=fields)


def _complete_conversation(db, user):
    answers = (
        "我在华东理工大学读人工智能专业大二。",
        "通过课程考试，并完成一个可信 RAG 项目。",
        "学过 Python、线性代数和概率论。",
        "最容易卡在公式推导和相似概念辨析。",
        "我喜欢先看例子，再写代码验证。",
    )
    for index, answer in enumerate(answers):
        _confirm_current(db, user, f"complete-{index}", answer)


def test_five_dimensions_progress_in_order_and_project_existing_profile_fields():
    engine, db = _session()
    try:
        user = _learner(db)
        answers = (
            "我在华东理工大学读人工智能专业大二。",
            "先通过机器学习课程考试，再完成一个可信 RAG 项目。",
            "学过 Python、线性代数和概率论，模型评估基础一般。",
            "最容易卡在公式推导和相似概念辨析。",
            "我喜欢先看例子，再分步推导，最后写代码验证。",
        )
        payload = None
        for index, answer in enumerate(answers):
            payload = _confirm_current(db, user, f"turn-{index + 1}", answer)
            assert payload["checkpoint"] == index + 1
        assert payload["status"] == "confirmed"
        assert payload["missingFields"] == []
        assert [item["key"] for item in payload["dimensions"]] == list(DIMENSIONS)
        assert all(item["status"] == "confirmed" for item in payload["dimensions"])
        assert payload["courseContext"]["title"] == "机器学习导论"

        profile = db.get(DBStudentProfile, user.username)
        assert profile.major == "人工智能"
        assert profile.learning_goals
        assert "Python" in profile.knowledge_base
        assert profile.weak_points
        assert profile.misconception_patterns == {"概念辨析": 0.62}
        assert payload["confirmedFields"]["difficulty"]["values"]["misconception_patterns"] == profile.misconception_patterns
        assert profile.interaction_preferences
        assert profile.cognitive_style == "代码实操导向"
    finally:
        db.close()
        engine.dispose()


def test_answer_is_committed_before_extraction_and_refresh_restores_pending_candidate():
    engine, db = _session()
    try:
        user = _learner(db, "save-first")
        onboarding = get_or_create_session(db, user)

        def committed_extractor(dimension, answer):
            saved = db.query(DBOnboardingTurn).filter_by(
                session_id=onboarding.id, turn_id="turn-save-first",
            ).one()
            assert saved.status == "saved"
            assert saved.user_answer == answer
            return {
                "dimension": dimension,
                "summary": answer,
                "fields": [{"key": "major", "label": "专业方向", "value": "人工智能", "kind": "text"}],
            }

        first = record_turn(
            db,
            user,
            turn_id="turn-save-first",
            question_dimension="background",
            user_answer="我是人工智能专业学生。",
            extractor=committed_extractor,
        )
        restored = session_payload(db, db.get(DBOnboardingSession, onboarding.id))
        assert restored == first
        assert restored["turns"][0]["status"] == "awaiting_confirmation"
        assert restored["questionDimension"] == "background"
    finally:
        db.close()
        engine.dispose()


def test_duplicate_turn_id_is_idempotent_and_does_not_create_a_second_answer():
    engine, db = _session()
    try:
        user = _learner(db, "duplicate")
        session = get_or_create_session(db, user)
        first = record_turn(
            db, user, turn_id="duplicate-turn", question_dimension="background",
            user_answer="我学人工智能。",
        )
        second = record_turn(
            db, user, turn_id="duplicate-turn", question_dimension="background",
            user_answer="这段不同文本不得覆盖第一次回答。",
        )
        assert first == second
        turns = db.query(DBOnboardingTurn).filter_by(session_id=session.id).all()
        assert len(turns) == 1
        assert turns[0].user_answer == "我学人工智能。"
    finally:
        db.close()
        engine.dispose()


def test_conflict_requires_explicit_resolution_before_overwriting_confirmed_dimension():
    engine, db = _session()
    try:
        user = _learner(db, "conflict")
        _confirm_current(db, user, "background-1", "我是人工智能专业学生。")
        conflict = record_turn(
            db,
            user,
            turn_id="background-2",
            question_dimension="background",
            user_answer="我想把专业背景改为软件工程。",
        )
        turn = next(item for item in conflict["turns"] if item["turnId"] == "background-2")
        assert turn["status"] == "conflict"

        try:
            confirm_turn(db, user, turn_id="background-2", fields={"major": "软件工程"})
        except Exception as error:
            assert getattr(error, "code", "") == "field_conflict"
        else:
            raise AssertionError("conflict confirmation must require explicit resolution")

        resolved = confirm_turn(
            db,
            user,
            turn_id="background-2",
            fields={"major": "软件工程"},
            resolve_conflict=True,
        )
        assert resolved["confirmedFields"]["background"]["values"]["major"] == "软件工程"
        assert db.get(DBStudentProfile, user.username).major == "软件工程"
    finally:
        db.close()
        engine.dispose()


def test_extraction_failure_keeps_answer_and_allows_manual_confirmation():
    engine, db = _session()
    try:
        user = _learner(db, "manual")

        def fail_extraction(dimension, answer):
            raise RuntimeError("model unavailable")

        payload = record_turn(
            db,
            user,
            turn_id="manual-turn",
            question_dimension="background",
            user_answer="我在计算机学院学习人工智能。",
            extractor=fail_extraction,
        )
        turn = payload["turns"][0]
        assert turn["status"] == "extraction_failed"
        assert turn["userAnswer"] == "我在计算机学院学习人工智能。"
        assert turn["extractedCandidates"]["fields"][0]["key"] == "major"

        confirmed = confirm_turn(
            db, user, turn_id="manual-turn", fields={"major": "人工智能"},
        )
        assert confirmed["checkpoint"] == 1
        assert db.get(DBStudentProfile, user.username).major == "人工智能"
    finally:
        db.close()
        engine.dispose()


def test_profile_projection_failure_preserves_answer_for_retry():
    engine, db = _session()
    try:
        user = _learner(db, "projection")
        record_turn(
            db,
            user,
            turn_id="projection-turn",
            question_dimension="background",
            user_answer="我是人工智能专业学生。",
        )

        def fail_projection(*_args, **_kwargs):
            raise RuntimeError("database temporarily unavailable")

        failed = confirm_turn(
            db,
            user,
            turn_id="projection-turn",
            fields={"major": "人工智能"},
            projector=fail_projection,
        )
        turn = failed["turns"][0]
        assert turn["status"] == "projection_failed"
        assert turn["userAnswer"] == "我是人工智能专业学生。"
        assert failed["checkpoint"] == 0

        retried = confirm_turn(
            db, user, turn_id="projection-turn", fields={"major": "人工智能"},
        )
        assert retried["checkpoint"] == 1
        assert db.get(DBStudentProfile, user.username).major == "人工智能"
    finally:
        db.close()
        engine.dispose()


def test_frontend_contract_has_conversation_live_profile_and_no_course_upload_gate():
    onboarding = (ROOT / "frontend/src/views/Onboarding.vue").read_text(encoding="utf-8")
    panel = (ROOT / "frontend/src/components/ProfileSummaryPanel.vue").read_text(encoding="utf-8")
    login = (ROOT / "frontend/src/views/Login.vue").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api/onboarding.js").read_text(encoding="utf-8")

    for marker in (
        'data-testid="onboarding-v2"',
        'data-testid="onboarding-progress"',
        'data-testid="onboarding-conversation"',
        'data-testid="onboarding-candidate-editor"',
        "不需要上传课程材料",
        "grid-template-columns: minmax(0, 68fr) minmax(350px, 32fr)",
    ):
        assert marker in onboarding
    assert 'data-testid="onboarding-profile-summary"' in panel
    assert "只记录你确认过的信息" in panel
    assert "getOnboardingStatus" in login
    assert "/v1/onboarding/session" in api
    assert "knowledge/upload" not in onboarding
    for forbidden_gate in ("请先上传课程", "上传课程后继续", "必须上传课程", "上传后才能"):
        assert forbidden_gate not in onboarding


def test_authenticated_api_rejects_non_student_and_exposes_feature_status(monkeypatch):
    student = DBUser(
        public_id="usr-f3-api-student",
        username="f3-api-student",
        hashed_password="not-used",
        role="student",
    )
    teacher = DBUser(
        public_id="usr-f3-api-teacher",
        username="f3-api-teacher",
        hashed_password="not-used",
        role="teacher",
    )

    import app.profile_onboarding_api as onboarding_api

    async def fake_run_db_op(operation, *args, **kwargs):
        class FakeQuery:
            def filter_by(self, **_kwargs):
                return self

            def first(self):
                return None

        class FakeDb:
            def query(self, _model):
                return FakeQuery()

            def get(self, _model, _key):
                return None

        return operation(FakeDb(), *args, **kwargs)

    monkeypatch.setattr(onboarding_api, "run_db_op", fake_run_db_op)
    app.dependency_overrides[get_current_user] = lambda: teacher
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/onboarding/status").status_code == 403
    finally:
        app.dependency_overrides.clear()

    app.dependency_overrides[get_current_user] = lambda: student
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/onboarding/status")
            assert response.status_code == 200
            assert response.json() == {
                "featureEnabled": True,
                "exists": False,
                "status": None,
                "finalized": False,
                "profileSnapshotId": None,
                "legacyComplete": False,
            }
    finally:
        app.dependency_overrides.clear()


def test_legacy_evidence_profile_can_skip_reonboarding_but_a_fresh_course_member_cannot():
    engine, db = _session()
    try:
        experienced = _learner(db, "legacy-evidence")
        profile = db.get(DBStudentProfile, experienced.username)
        profile.profile_evidence = [{"source": "performance_signal", "text": "冻结演示证据"}]
        db.commit()

        from app.profile_onboarding import onboarding_status

        experienced_status = onboarding_status(db, experienced, feature_enabled=True)
        assert experienced_status["legacyComplete"] is True
        assert experienced_status["exists"] is False

        fresh = _learner(db, "fresh-member")
        fresh_status = onboarding_status(db, fresh, feature_enabled=True)
        assert fresh_status["legacyComplete"] is False
        assert fresh_status["exists"] is False
    finally:
        db.close()
        engine.dispose()


def test_no_attachment_can_finalize_one_initial_snapshot_without_mastery_evidence():
    engine, db = _session()
    try:
        user = _learner(db, "no-attachment")
        profile = db.get(DBStudentProfile, user.username)
        profile.concept_mastery = {"线性回归": 0.35}
        db.commit()
        _complete_conversation(db, user)

        first = finalize_initial_profile(db, user)
        second = finalize_initial_profile(db, user)
        assert first["finalized"] is True
        assert second["profileSnapshotId"] == first["profileSnapshotId"]
        snapshots = db.query(DBProfileSnapshot).filter_by(owner_public_id=user.public_id).all()
        assert len(snapshots) == 1
        assert snapshots[0].snapshot["mastery_status"] == "awaiting_admission_assessment"
        assert snapshots[0].snapshot["mastery_evidence"] == []
        assert db.get(DBStudentProfile, user.username).concept_mastery == {"线性回归": 0.35}
        try:
            upload_personal_evidence(
                db, user, evidence_type="transcript", filename="补充成绩单.txt", raw="GPA：3.7".encode(),
            )
        except Exception as error:
            assert getattr(error, "code", "") == "profile_already_finalized"
        else:
            raise AssertionError("finalized initial profile must be immutable")
    finally:
        db.close()
        engine.dispose()


def test_transcript_candidates_keep_value_confidence_source_and_confirmation_time():
    engine, db = _session()
    try:
        user = _learner(db, "transcript")
        _complete_conversation(db, user)
        payload = upload_personal_evidence(
            db,
            user,
            evidence_type="transcript",
            filename="个人成绩单.txt",
            raw="华东理工大学\n专业：人工智能\nGPA：3.62\n线性代数 91\n概率论 88".encode(),
        )
        item = payload["personalEvidence"][0]
        assert item["status"] == "parsed"
        assert {field["key"] for field in item["candidates"]} >= {"school", "major", "gpa", "completed_courses"}
        assert all(field["confidence"] > 0 for field in item["candidates"])
        assert all(field["sourceType"] == "transcript" for field in item["candidates"])
        assert all(field["sourceRef"] for field in item["candidates"])
        major = next(field for field in item["candidates"] if field["key"] == "major")
        assert major["conflict"] is False

        fields = {field["key"]: field["value"] for field in item["candidates"]}
        confirmed = confirm_personal_evidence(db, user, evidence_id=item["evidenceId"], fields=fields)
        saved = confirmed["personalEvidence"][0]
        assert saved["status"] == "confirmed"
        assert all(field["confirmedAt"] for field in saved["confirmedFields"])
        assert db.get(DBStudentProfile, user.username).concept_mastery == {}
        finalized = finalize_initial_profile(db, user)
        snapshot = db.get(DBProfileSnapshot, finalized["profileSnapshotId"])
        assert snapshot.snapshot["personal_evidence"][0]["evidence_type"] == "transcript"
    finally:
        db.close()
        engine.dispose()


def test_timetable_can_be_confirmed_and_duplicate_upload_is_idempotent():
    engine, db = _session()
    try:
        user = _learner(db, "timetable")
        raw = "周一 08:00 机器学习\n周三 14:00 数据结构\n周五 10:00 概率论".encode()
        first = upload_personal_evidence(
            db, user, evidence_type="timetable", filename="本学期课程表.md", raw=raw,
        )
        second = upload_personal_evidence(
            db, user, evidence_type="timetable", filename="本学期课程表.md", raw=raw,
        )
        assert first == second
        assert db.query(DBOnboardingPersonalEvidence).count() == 1
        item = first["personalEvidence"][0]
        fields = {field["key"]: field["value"] for field in item["candidates"]}
        confirmed = confirm_personal_evidence(db, user, evidence_id=item["evidenceId"], fields=fields)
        assert confirmed["personalEvidence"][0]["status"] == "confirmed"
    finally:
        db.close()
        engine.dispose()


def test_course_material_is_rejected_and_parse_failure_does_not_block_finalization():
    engine, db = _session()
    try:
        user = _learner(db, "failure")
        try:
            upload_personal_evidence(
                db, user, evidence_type="transcript", filename="机器学习课程大纲.pdf", raw=b"not empty",
            )
        except Exception as error:
            assert getattr(error, "code", "") == "course_material_not_allowed"
        else:
            raise AssertionError("course material must be rejected")

        failed = upload_personal_evidence(
            db, user, evidence_type="transcript", filename="损坏的成绩单.pdf", raw=b"not-a-pdf",
        )
        item = failed["personalEvidence"][0]
        assert item["status"] == "parse_failed"
        assert item["error"] == "文件无法解析，请确认格式正确，或重新导出后再试。"
        _complete_conversation(db, user)
        discard_personal_evidence(db, user, evidence_id=item["evidenceId"])
        finalized = finalize_initial_profile(db, user)
        assert finalized["finalized"] is True
    finally:
        db.close()
        engine.dispose()


def test_personal_evidence_is_owner_scoped_and_unconfirmed_candidates_block_finalization():
    engine, db = _session()
    try:
        owner = _learner(db, "owner")
        other = _learner(db, "other")
        payload = upload_personal_evidence(
            db,
            owner,
            evidence_type="transcript",
            filename="个人成绩单.txt",
            raw="专业：人工智能\nGPA：3.5".encode(),
        )
        item = payload["personalEvidence"][0]
        try:
            confirm_personal_evidence(db, other, evidence_id=item["evidenceId"], fields={"gpa": "3.5"})
        except Exception as error:
            assert getattr(error, "code", "") == "evidence_forbidden"
        else:
            raise AssertionError("another learner must not confirm owner evidence")

        _complete_conversation(db, owner)
        try:
            finalize_initial_profile(db, owner)
        except Exception as error:
            assert getattr(error, "code", "") == "evidence_confirmation_required"
        else:
            raise AssertionError("parsed candidates require confirm or discard")
    finally:
        db.close()
        engine.dispose()


def test_document_conflict_exposes_current_and_document_sources_before_confirmation():
    engine, db = _session()
    try:
        user = _learner(db, "document-conflict")
        _confirm_current(db, user, "background", "我目前是人工智能专业学生。")
        payload = upload_personal_evidence(
            db,
            user,
            evidence_type="transcript",
            filename="个人成绩单.txt",
            raw="专业：软件工程\nGPA：3.4".encode(),
        )
        major = next(field for field in payload["personalEvidence"][0]["candidates"] if field["key"] == "major")
        assert major["conflict"] is True
        assert major["currentValue"] == "人工智能"
        assert major["currentSource"] == "学生自述并确认"
        assert major["currentSourceRef"] == "background"
        assert major["value"] == "软件工程"
        assert major["sourceRef"]
    finally:
        db.close()
        engine.dispose()
