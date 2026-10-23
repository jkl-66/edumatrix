from collections import Counter
from pathlib import Path

import pytest

import app.diagnostic_generation as diagnostic_generation
from app.competition_demo_seed import seed_competition_demo
from app.database import Base, DBProfileSnapshot, DBCourse, DBUser
from app.diagnostic_generation import _generation_scope, _question_type_quotas, _validate_generated_set
from app.knowledge_graph import build_course_graph
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]
GRAPH_VIEW = ROOT / "frontend" / "src" / "views" / "KnowledgeGraphWorkspace.vue"
COURSE_ID = "demo-course-rag-trust-v1"


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    seed_competition_demo(session)
    learner = session.query(DBUser).filter_by(username="lzz").one()
    return engine, session, learner


def _generated_payload(scope: dict, count: int) -> dict:
    quotas = _question_type_quotas(count)
    ordered_types = [kind for kind, total in quotas.items() for _ in range(total)]
    questions = []
    counts = Counter()
    for index, question_type in enumerate(ordered_types):
        point = scope["knowledgePoints"][index % len(scope["knowledgePoints"])]
        source = next(item for item in scope["sources"] if point["id"] in item["knowledgePointIds"])
        counts[point["id"]] += 1
        item = {
            "item_id": f"B10-Q{index + 1:02d}",
            "question_type": question_type,
            "prompt": f"请依据来源解释 {point['title']}（第 {index + 1} 题）。",
            "primary_knowledge_point_id": point["id"],
            "source_ref_id": source["sourceRefId"],
            "diagnostic_dimension": ("theory", "application", "engineering_judgment")[index % 3],
            "bloom_level": "apply",
            "difficulty": 0.5,
            "explanation": "依据冻结课程来源进行判断。",
        }
        if question_type == "true_false":
            item["answer"] = True
        elif question_type == "single_choice":
            item["options"] = ["A", "B", "C", "D"]
            item["answer"] = "A"
        else:
            item["reference_answer"] = "请结合课程来源说明判断依据。"
            item["rubric"] = [{"id": "evidence", "label": "有来源证据", "weight": 1.0}]
        questions.append(item)
    return {
        "profile_adaptation_summary": "覆盖全部课程知识点并为关键点保留交叉证据。",
        "coverage_plan": [
            {"knowledge_point_id": point["id"], "question_count": counts[point["id"]], "rationale": "全点覆盖与交叉证据。"}
            for point in scope["knowledgePoints"]
        ],
        "questions": questions,
    }


def test_scope_requires_all_diagnosable_points_and_marks_cross_evidence_targets():
    engine, session, learner = _session()
    try:
        course = session.get(DBCourse, COURSE_ID)
        profile = session.query(DBProfileSnapshot).filter_by(owner_public_id=learner.public_id).first()
        scope = _generation_scope(session, course=course, profile=profile, question_count=15, self_rating="advanced")
        assert scope["coverageGap"] == []
        assert len(scope["knowledgePoints"]) == 12
        assert scope["crossEvidencePointIds"]
        assert all(item["minimumQuestionCount"] == 1 for item in scope["knowledgePoints"])
        assert all(item["crossEvidenceTarget"] in (1, 2) for item in scope["knowledgePoints"])
        generated = _validate_generated_set(
            _generated_payload(scope, 15),
            count=15,
            quotas=_question_type_quotas(15),
            scope=scope,
        )
        counts = Counter(item.primary_knowledge_point_id for item in generated.questions)
        assert set(counts) == {item["id"] for item in scope["knowledgePoints"]}
        assert all(counts[point_id] >= 2 for point_id in scope["crossEvidencePointIds"])
    finally:
        session.close()
        engine.dispose()


def test_course_graph_exposes_read_only_mastery_evidence_fields():
    engine, session, learner = _session()
    try:
        graph = build_course_graph(session, learner, COURSE_ID)
        points = [node for node in graph["nodes"] if node["nodeType"] == "knowledge_point"]
        assert graph["masterySnapshot"]["status"] == "not_available"
        assert points and all(node["masteryStatus"] == "unknown" for node in points)

        snapshot = DBProfileSnapshot(
            owner_public_id=learner.public_id,
            profile_version="b10-graph-evidence-v1",
            snapshot={
                "kind": "diagnostic_evidence_snapshot",
                "course_id": COURSE_ID,
                "mastery_by_knowledge_point": {
                    points[0]["knowledgePointId"]: {
                        "title": points[0]["name"],
                        "score": 0.75,
                        "status": "known",
                        "label": "基本掌握",
                        "evidence_item_count": 2,
                        "source_ref_ids": ["src-b10"],
                        "question_version_ids": ["qv-1", "qv-2"],
                        "cross_evidence": True,
                    },
            },
            "mastery_status": "initial_evidence_snapshot",
        },
        content_hash="b10".ljust(64, "0"),
        trace_id="trace-b10-graph",
    )
        session.add(snapshot)
        session.commit()
        graph = build_course_graph(session, learner, COURSE_ID)
        node = next(item for item in graph["nodes"] if item.get("knowledgePointId") == points[0]["knowledgePointId"])
        assert graph["masterySnapshot"]["status"] == "available"
        assert node["masteryStatus"] == "known"
        assert node["masteryEvidenceCount"] == 2
        assert node["masteryCrossEvidence"] is True
    finally:
        session.close()
        engine.dispose()


def test_graph_frontend_explains_unknown_and_read_only_mastery_evidence():
    source = GRAPH_VIEW.read_text(encoding="utf-8")
    for marker in (
        "初始掌握证据",
        "交叉证据",
        "graph-mastery-boundary",
        "查看图谱不会修改掌握度",
        "尚无足够诊断证据",
    ):
        assert marker in source
    assert "event_name" not in source
