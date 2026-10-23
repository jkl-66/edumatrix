from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, DBProfileSnapshot, DBStudentProfile, DBUser
from app.profile_adaptation import build_profile_adaptation
from app.profile_onboarding import (
    confirm_turn,
    finalize_initial_profile,
    get_or_create_session,
    onboarding_status,
    record_turn,
    session_payload,
)


def _db_user(suffix: str = "natural"):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    user = DBUser(
        public_id=f"usr-conversational-{suffix}",
        username=f"conversational-{suffix}",
        hashed_password="not-used",
        role="student",
        display_name="自然对话学生",
    )
    db.add(user)
    db.commit()
    return engine, db, user


def _send_and_confirm(db, user, turn_id: str, answer: str):
    current = get_or_create_session(db, user).current_dimension
    payload = record_turn(
        db,
        user,
        turn_id=turn_id,
        question_dimension=current,
        user_answer=answer,
    )
    turn = next(item for item in payload["turns"] if item["turnId"] == turn_id)
    fields = {
        field["key"]: field["value"]
        for field in turn["extractedCandidates"]["fields"]
    }
    return confirm_turn(db, user, turn_id=turn_id, fields=fields)


def test_opening_and_follow_up_are_contextual_not_form_questions():
    engine, db, user = _db_user("questions")
    try:
        session = get_or_create_session(db, user)
        first = session_payload(db, session)
        assert first["conversationMode"] == "adaptive"
        assert "不用按栏目" in first["question"]
        assert "学习背景" not in first["question"]

        after = _send_and_confirm(db, user, "q1", "我在公司做知识库问答项目，想把检索效果做稳。")
        assert "你刚才提到" in after["question"]
        assert "知识库问答项目" in after["question"]
        first_turn = after["turns"][0]
        assert first_turn["assistantReply"].startswith("我听到的是：")
        assert first_turn["question"]
    finally:
        db.close()
        engine.dispose()


def test_profile_demo_accounts_are_treated_as_already_finalized():
    engine, db, user = _db_user("profile_demo_beginner")
    try:
        user.username = "profile_demo_beginner"
        profile = DBStudentProfile(student_id=user.username)
        db.add(profile)
        profile.target_course = "机器学习基础与实践"
        profile.major = "数据科学"
        profile.customized_fields = ["major", "target_course", "learning_goals", "interaction_preferences"]
        snapshot = DBProfileSnapshot(
            id="profile-demo-snapshot",
            owner_public_id=user.public_id,
            legacy_student_id=user.username,
            profile_version="profile-demo.v1",
            snapshot={"kind": "profile_demo"},
            content_hash="a" * 64,
            trace_id="profile-demo-trace",
        )
        db.add(snapshot)
        db.commit()
        status = onboarding_status(db, user, feature_enabled=True)
        assert status["finalized"] is True
        assert status["profileSnapshotId"] == snapshot.id
    finally:
        db.close()
        engine.dispose()


def test_natural_signals_project_and_change_adaptation_controls():
    engine, db, user = _db_user("signals")
    try:
        _send_and_confirm(db, user, "s1", "我在公司做知识库问答项目，想把检索效果做稳并准备岗位面试。")
        _send_and_confirm(db, user, "s2", "希望能上线一个可用版本，最好能通过面试中的项目追问。")
        _send_and_confirm(db, user, "s3", "Python 和线性代数做过一些，但时间很碎，通勤时学习，基础有些断层。")
        _send_and_confirm(db, user, "s4", "我最容易在公式推导和概念区别上卡住，一看到长题就焦虑。")
        payload = _send_and_confirm(db, user, "s5", "先看一个真实例子，再画图解释，最后我自己写代码验证；每次短一点。")

        profile = db.get(DBStudentProfile, user.username)
        assert profile.motivation_type in {"项目/工作", "职业发展"}
        assert profile.cognitive_load >= 0.5
        assert profile.frustration_index >= 0.5
        assert profile.dimension_states
        assert any(item.get("label") == "学习情境" for item in profile.dimension_states.values())

        finalized = finalize_initial_profile(db, user)
        assert finalized["finalized"] is True
        assert payload["profileSignals"]
        assert any(signal["label"] == "学习节奏" for signal in payload["profileSignals"])

        novice = {
            "profile_projection": {
                "knowledge_base": "零基础",
                "learning_goals": ["理解核心概念"],
                "interaction_preferences": ["分步讲解"],
                "cognitive_load": 0.78,
                "frustration_index": 0.72,
            }
        }
        practitioner = {
            "profile_projection": {
                "knowledge_base": "熟练，有经验",
                "learning_goals": ["上线项目"],
                "interaction_preferences": ["代码实操"],
                "cognitive_load": 0.3,
                "frustration_index": 0.1,
            }
        }
        novice_plan = build_profile_adaptation(novice, knowledge_point={"title": "RAG"})
        practitioner_plan = build_profile_adaptation(practitioner, knowledge_point={"title": "RAG"})
        assert novice_plan["difficulty_band"] == "foundation"
        assert practitioner_plan["difficulty_band"] == "transfer"
        assert novice_plan["scaffolding_level"] == "high"
        assert practitioner_plan["scaffolding_level"] == "light"
        assert novice_plan["explanation_style"] != practitioner_plan["explanation_style"]
    finally:
        db.close()
        engine.dispose()
