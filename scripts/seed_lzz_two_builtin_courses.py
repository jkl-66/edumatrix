"""Idempotent local demo data for lzz and the two built-in AI courses.

This seed intentionally does not call the historical RAG/embedded-course seeds.
It reads the published course graph already present in the database and writes
only lzz-owned, course-scoped learning projections.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import (
    DBAssessmentAttempt, DBAssessmentExam, DBAssessmentExamItem,
    DBAssessmentExamSitting, DBAssessmentExamVersion,
    DBAssessmentQuestion, DBAssessmentQuestionVersion, DBArtifact,
    DBArtifactVersion, DBChatConversation, DBChatMessage, DBChapter,
    DBChapterKnowledgePoint, DBCourseMembership, DBGenerationTask,
    DBLearningEvent, DBLearningPath, DBNote, DBNoteVersion, DBPathNode,
    DBPlanDraft, DBPlanVersion, DBProfileEvidence, DBProfileSnapshot,
    DBQuizRecord, DBReviewPlan, DBSourceDocument, DBSourceRef,
    DBStudentProfile, DBUser, DBWrongQuestion, SessionLocal,
)
from app.resource_bundles import _deterministic_demo_content
from app.learning_aggregation import aggregate_learning_event

COURSES = (
    "course-machine-learning-foundations-v1",
    "course-ai-deep-learning-agents-v1",
)
SCOPE = "lzz-two-builtin-courses-demo-v1"
FROZEN_AT = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
RESOURCE_TYPES = (
    ("handout", "学习讲义"), ("mind_map", "知识结构图"), ("quiz", "知识点测验"),
    ("training_task", "实践任务书"), ("code_sandbox", "代码练习"),
    ("video", "课程导览"), ("deck", "网页课件"),
    ("interactive_model", "交互实验"), ("feynman", "费曼复述"),
)


def digest(value: Any) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sid(course_id: str) -> str:
    return "ml" if course_id == COURSES[0] else "ai"


def ident(course_id: str, kind: str, suffix: str = "") -> str:
    value = f"lzzdemo03-{sid(course_id)}-{kind}"
    return value + (f"-{suffix}" if suffix else "")


def repair(db: Any, model: Any, row_id: Any, values: dict[str, Any], identities: tuple[str, ...] = ()) -> int:
    row = db.get(model, row_id)
    if row is None:
        db.add(model(id=row_id, **values)); db.flush(); return 1
    for field in identities:
        if getattr(row, field) != values[field]:
            raise ValueError(f"identity conflict: {model.__name__}:{row_id}:{field}")
    changed = 0
    for field, value in values.items():
        current = getattr(row, field)
        if isinstance(current, datetime) and isinstance(value, datetime):
            current = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current
            value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        if current != value:
            setattr(row, field, value); changed = 1
    if changed: db.flush()
    return changed


def course_context(db: Any, course_id: str) -> dict[str, Any]:
    course = db.get(__import__("app.database", fromlist=["DBCourse"]).DBCourse, course_id)
    if course is None or course.status != "published": raise ValueError(f"published course unavailable: {course_id}")
    points = db.query(__import__("app.database", fromlist=["DBKnowledgePoint"]).DBKnowledgePoint).filter_by(domain_pack=course.domain_pack, status="active").order_by(__import__("app.database", fromlist=["DBKnowledgePoint"]).DBKnowledgePoint.code).all()
    # Keep one row per code; some curated chapters teach the same point repeatedly.
    by_code = {}
    for point in points: by_code.setdefault(point.code, point)
    if not by_code: raise ValueError(f"knowledge point projection unavailable: {course_id}")
    sources = db.query(DBSourceDocument).filter_by(course_id=course_id, processing_status="ready").order_by(DBSourceDocument.id).limit(2).all()
    refs = []
    for source in sources:
        ref = db.query(DBSourceRef).filter_by(source_document_id=source.id).order_by(DBSourceRef.id).first()
        if ref: refs.append(ref)
    if not refs: raise ValueError(f"source references unavailable: {course_id}")
    chapters = {row.id: row for row in db.query(DBChapter).filter(DBChapter.id.in_([r.chapter_id for r in refs if r.chapter_id] or ["-"])).all()}
    snapshots = []
    for ref in refs:
        source = db.get(DBSourceDocument, ref.source_document_id); chapter = chapters.get(ref.chapter_id)
        snapshots.append({"source_ref_id": ref.id, "source_document_id": source.id, "title": source.title, "location_kind": ref.location_kind, "location_label": ref.location_label or (chapter.title if chapter else source.title), "quote": ref.quote, "content_hash": ref.content_hash})
    return {"course": course, "points": list(by_code.values()), "by_code": by_code, "refs": refs, "snapshots": snapshots}


def profile_snapshot(ctx: dict[str, Any], index: int) -> dict[str, Any]:
    points = ctx["points"]
    scores = [0.82 - i * 0.025 for i in range(len(points))]
    return {"schema_version":"lzz.demo.profile.v1", "scope":SCOPE, "course_id":ctx["course"].id, "course_title":ctx["course"].title, "mastery":round(sum(scores)/len(scores), 3), "concept_mastery":{p.id: round(scores[i], 3) for i,p in enumerate(points)}, "weak_points":[p.id for p in points[-2:]], "learning_style":["先看结构", "再做练习", "最后复述"], "confidence":0.86, "sequence":index, "truthfulness":"local_deterministic_demo"}


def ensure_course(db: Any, owner: DBUser, ctx: dict[str, Any], course_index: int) -> tuple[int, dict[str, Any]]:
    cid, tag, course, points, refs = ctx["course"].id, sid(ctx["course"].id), ctx["course"], ctx["points"], ctx["refs"]
    changed = 0; source_ids = [r.id for r in refs]; primary = points[min(1, len(points)-1)]
    membership_id = ident(cid, "membership")
    existing = db.query(DBCourseMembership).filter_by(course_id=cid, user_public_id=owner.public_id).first()
    if existing is None:
        changed += repair(db, DBCourseMembership, membership_id, {"course_id":cid,"user_public_id":owner.public_id,"role":"student","status":"active","created_at":FROZEN_AT,"updated_at":FROZEN_AT}, ("course_id","user_public_id"))
    elif existing.role != "student" or existing.status != "active":
        existing.role, existing.status = "student", "active"; db.flush(); changed += 1

    snap_id = ident(cid, "profile")
    snap = profile_snapshot(ctx, course_index)
    changed += repair(db, DBProfileSnapshot, snap_id, {"owner_public_id":owner.public_id,"legacy_student_id":owner.username,"profile_version":"lzz.demo.profile.v1","snapshot":snap,"content_hash":digest(snap),"trace_id":ident(cid,"trace"),"created_at":FROZEN_AT}, ("owner_public_id",))
    evidence_id = ident(cid, "profile-evidence")
    changed += repair(db, DBProfileEvidence, evidence_id, {"owner_public_id":owner.public_id,"legacy_student_id":owner.username,"legacy_key":evidence_id,"source_type":"learning_journey","source_object_id":snap_id,"features":["resource_completion","assessment","conversation","feynman"],"weight":0.92,"confidence":0.86,"evidence_summary":"来自课程学习、练习、测验和复述行为的演示证据。","observed_at":FROZEN_AT,"status":"active","evidence_version":"1","trace_id":ident(cid,"trace")}, ("legacy_student_id","legacy_key"))

    task_id = ident(cid, "generation-task")
    changed += repair(db, DBGenerationTask, task_id, {"owner_public_id":owner.public_id,"course_id":cid,"trace_id":ident(cid,"trace"),"status":"completed","progress":1.0,"capability":"resource_bundle","model":"local-demo","idempotency_key":f"{SCOPE}:{task_id}","estimated_cost":0.0,"actual_cost":0.0,"started_at":FROZEN_AT,"completed_at":FROZEN_AT+timedelta(minutes=8)}, ("owner_public_id","course_id"))
    resource_ids = []
    for rindex, (rtype, label) in enumerate(RESOURCE_TYPES):
        rid, vid = ident(cid, "resource", rtype), ident(cid, "resource-version", rtype); resource_ids.append(rid)
        title = f"{primary.title} · {label}"
        manifest = {"knowledge_point_id":primary.id,"context":{"course_title":course.title,"knowledge_point_title":primary.title,"learning_goal":"理解课程核心概念并能用练习、测验和复述验证。","profile_adaptation":"为 lzz 提供结构图、代码和循序练习。","mastery_summary":"基础概念已建立，迁移练习仍需巩固。","recent_learning_summary":"已完成导论阅读，正在进行练习。"}}
        item = {"title":title,"source_ref_ids":source_ids,"completion_rule":"完成页面中的阅读、运行或提交动作。"}
        content = json.dumps({"title":title,"resource_type":rtype,"knowledge_point":primary.title,"sections":[{"heading":"学习目标","body":"把概念讲清楚，并能在一个小案例中验证。"},{"heading":"练习与检查","body":"先观察输入，再运行或回答，最后用一句话说明结果。"}],"source_ref_ids":source_ids}, ensure_ascii=False) if rtype == "quiz" else _deterministic_demo_content(resource_type=rtype,item=item,manifest=manifest,source_snapshots=ctx["snapshots"],linked_resource_ids=[])
        fmt = "markdown" if rtype == "feynman" else "json"
        changed += repair(db, DBArtifact, rid, {"owner_public_id":owner.public_id,"course_id":cid,"artifact_type":rtype,"title":title,"status":"approved","current_version_id":vid,"creating_task_id":task_id,"lock_version":1,"archived_at":None}, ("owner_public_id","course_id"))
        changed += repair(db, DBArtifactVersion, vid, {"artifact_id":rid,"version_number":1,"content":content,"content_format":fmt,"content_hash":digest(content),"metadata_json":{"resource_type":rtype,"knowledge_point_id":primary.id,"source_ref_ids":source_ids,"generation_state":"succeeded","demo_scope":SCOPE},"created_by_public_id":owner.public_id,"created_task_id":task_id,"created_at":FROZEN_AT+timedelta(minutes=rindex)}, ("artifact_id",))

    # Path nodes must target canonical course chapters. Older demo data used
    # resource ids and a legacy schema, which left the current context resolver
    # without a knowledge-point/source mapping and disabled generation.
    chapter_by_point = {}
    chapter_rows = db.query(DBChapter).join(
        DBChapterKnowledgePoint, DBChapterKnowledgePoint.chapter_id == DBChapter.id,
    ).filter(DBChapter.course_id == cid).order_by(DBChapter.position, DBChapter.id).all()
    for chapter in chapter_rows:
        links = db.query(DBChapterKnowledgePoint).filter_by(chapter_id=chapter.id).all()
        for link in links:
            chapter_by_point.setdefault(link.knowledge_point_id, chapter)
    default_chapter = chapter_rows[0] if chapter_rows else None
    if default_chapter is None:
        raise ValueError(f"chapter projection unavailable: {cid}")
    plan_id, planv_id, path_id = ident(cid,"plan"), ident(cid,"plan-version"), ident(cid,"path")
    node_specs=[]
    for i, rid in enumerate(resource_ids):
        point = points[i % len(points)]
        chapter = chapter_by_point.get(point.id) or default_chapter
        node_specs.append({"key":f"{tag}-step-{i+1:02d}","title":f"{point.title} · {RESOURCE_TYPES[i][1]}","point":point,"chapter":chapter,"rid":rid,"status":"completed" if i < 2 else ("in_progress" if i == 2 else "pending"),"minutes":12+i*3})
    plan_content={"schema_version":"m5.plan.v1","goal":f"完成{course.title}的理解、练习、测验与复述闭环","assumptions":[],"nodes":[{"node_key":n["key"],"node_type":"chapter","target_object_id":n["chapter"].id,"title":n["title"],"prerequisites":[] if i==0 else [node_specs[i-1]["key"]],"resource_status":"existing","estimate_min_minutes":n["minutes"],"estimate_max_minutes":n["minutes"],"difficulty":0.45+i*0.04,"rationale":f"围绕{n['point'].title}安排{RESOURCE_TYPES[i][1]}，先建立概念，再通过练习验证。","required":i<3} for i,n in enumerate(node_specs)]}
    changed += repair(db, DBPlanDraft, plan_id, {"owner_public_id":owner.public_id,"course_id":cid,"title":f"{course.title}学习计划","status":"confirmed","idempotency_key":f"{SCOPE}:{plan_id}","current_version_id":planv_id,"confirmed_version_id":planv_id,"confirmed_at":FROZEN_AT,"lock_version":1}, ("owner_public_id","course_id"))
    changed += repair(db, DBPlanVersion, planv_id, {"plan_draft_id":plan_id,"version_number":1,"profile_snapshot_id":snap_id,"content":plan_content,"content_hash":digest(plan_content),"created_by_public_id":owner.public_id,"created_at":FROZEN_AT}, ("plan_draft_id",))
    changed += repair(db, DBLearningPath, path_id, {"owner_public_id":owner.public_id,"course_id":cid,"source_plan_version_id":planv_id,"status":"active","lock_version":1}, ("owner_public_id","course_id"))
    for i,n in enumerate(node_specs,1):
        changed += repair(db, DBPathNode, ident(cid,"path-node",f"{i:02d}"), {"learning_path_id":path_id,"node_key":n["key"],"sequence":i,"node_type":"chapter","target_object_id":n["chapter"].id,"title":n["title"],"status":n["status"],"prerequisites":[] if i==1 else [node_specs[i-2]["key"]],"resource_status":"existing","estimate_min_minutes":n["minutes"],"estimate_max_minutes":n["minutes"],"actual_minutes":n["minutes"] if n["status"]=="completed" else None,"created_at":FROZEN_AT+timedelta(minutes=i)}, ("learning_path_id",))

    qids=[]; attempts=[]
    for i in range(min(3,len(points))):
        qid,qvid=ident(cid,"question",f"{i+1:02d}"),ident(cid,"question-version",f"{i+1:02d}"); prompt=f"关于“{points[i].title}”，哪项说法最能说明学习者真正掌握了它？"; options=["能复述概念并在小案例中应用","只记住名词缩写","只看结论不看输入输出","跳过验证步骤"]; answer={"choice":"A"}
        payload={"prompt":prompt,"options":options,"answer_key":answer,"explanation":f"真正掌握需要把{points[i].title}讲清楚，并能在具体输入输出上验证，而不是只背名词。","primary_knowledge_point_id":points[i].id,"source_ref_ids":source_ids}
        changed += repair(db, DBAssessmentQuestion, qid, {"course_id":cid,"owner_public_id":owner.public_id,"question_type":"single_choice","origin":"derived","status":"approved","current_version_id":qvid}, ("course_id","owner_public_id"))
        changed += repair(db, DBAssessmentQuestionVersion, qvid, {"question_id":qid,"version_number":1,"prompt":prompt,"options":options,"answer_key":answer,"scoring_rule":{"correct_threshold":1.0},"explanation":payload["explanation"],"misconception_tags":["conceptual_gap"],"primary_knowledge_point_id":points[i].id,"secondary_knowledge_point_ids":[],"bloom_level":"apply","expert_difficulty":0.45+i*0.08,"irt_parameters":{"alpha":1.1,"beta":0.2,"gamma":0.25},"sample_size":0,"source_ref_ids":source_ids,"content_hash":digest(payload),"created_by_public_id":owner.public_id,"created_at":FROZEN_AT}, ("question_id",))
        attempt_id=ident(cid,"attempt",f"{i+1:02d}"); correct=i!=1; answer_value={"choice":"A" if correct else "B"}; attempts.append((attempt_id,qvid,correct))
        changed += repair(db, DBAssessmentAttempt, attempt_id, {"owner_public_id":owner.public_id,"course_id":cid,"question_version_id":qvid,"idempotency_key":f"{SCOPE}:{attempt_id}","mode":"practice","answer":answer_value,"score":1.0 if correct else 0.0,"correct":correct,"confidence":0.82 if correct else 0.58,"duration_seconds":38+i*9,"grading_status":"graded","feedback_policy":"immediate","submitted_at":FROZEN_AT+timedelta(minutes=40+i)}, ("owner_public_id","question_version_id"))
        quiz_id=ident(cid,"quiz-record",f"{i+1:02d}"); changed += repair(db, DBQuizRecord, quiz_id, {"student_id":owner.username,"question":prompt,"student_answer":answer_value["choice"],"correct_answer":"A","ai_confidence":0.92,"student_confidence":0.82 if correct else 0.58,"accuracy_score":1.0 if correct else 0.0,"target_concept":points[i].title,"feedback":payload["explanation"],"next_action":"advance" if correct else "review","attempt_number":1,"session_id":ident(cid,"session"),"options":options,"created_at":FROZEN_AT+timedelta(minutes=40+i)}, ("student_id",))
        if not correct:
            existing_wrong=db.query(DBWrongQuestion).filter_by(student_id=owner.username, source_object_id=qvid).first()
            if existing_wrong is None:
                db.add(DBWrongQuestion(student_id=owner.username,quiz_record_id=quiz_id,source_object_id=qvid,concept_name=points[i].title,wrong_reason_category="概念边界混淆",pinned=True,notes="建议先复述定义，再用一个小例子验证。",created_at=FROZEN_AT)); db.flush(); changed+=1
            review_marker=f"{SCOPE}:{qvid}"; review=db.query(DBReviewPlan).filter_by(student_id=owner.username).filter(DBReviewPlan.similar_quiz_ids.contains(review_marker)).first()
            if review is None:
                db.add(DBReviewPlan(student_id=owner.username,concept=points[i].title,interval_days=1,next_review_at=FROZEN_AT+timedelta(days=1),mastery=0.42,review_count=0,easiness_factor=2.2,last_quality=2,similar_quiz_ids=[review_marker],priority=0.35,created_at=FROZEN_AT)); db.flush(); changed+=1

    exam_id,exv_id,sit_id=ident(cid,"exam"),ident(cid,"exam-version"),ident(cid,"exam-sitting")
    config={"course_id":cid,"question_count":len(qids) or min(3,len(points)),"knowledge_point_ids":[p.id for p in points[:3]],"difficulty":"adaptive_demo","idempotency_key":f"{SCOPE}:{exam_id}"}
    changed += repair(db, DBAssessmentExam, exam_id, {"course_id":cid,"owner_public_id":owner.public_id,"generation_key":f"{SCOPE}:{exam_id}","title":f"{course.title}智能组卷","status":"open","current_version_id":exv_id,"duration_minutes":25,"lock_version":1}, ("course_id","owner_public_id"))
    changed += repair(db, DBAssessmentExamVersion, exv_id, {"exam_id":exam_id,"version_number":1,"instructions":"完成题目后提交，系统会给出逐题解析并更新学习建议。","feedback_policy":"after_submission","total_points":30.0,"manifest_hash":digest(config),"configuration":config,"generation_context":{"profile_snapshot_id":snap_id,"path_id":path_id,"demo_scope":SCOPE},"coverage":{"knowledge_points":[p.id for p in points[:3]],"question_count":3},"created_by_public_id":owner.public_id,"created_at":FROZEN_AT}, ("exam_id",))
    for i in range(min(3,len(points))): changed += repair(db, DBAssessmentExamItem, ident(cid,"exam-item",f"{i+1:02d}"), {"exam_version_id":exv_id,"question_version_id":ident(cid,"question-version",f"{i+1:02d}"),"position":i+1,"points":10.0,"required":True,"created_at":FROZEN_AT}, ("exam_version_id","question_version_id"))
    changed += repair(db, DBAssessmentExamSitting, sit_id, {"exam_id":exam_id,"exam_version_id":exv_id,"owner_public_id":owner.public_id,"status":"assigned","lock_version":1,"created_at":FROZEN_AT,"updated_at":FROZEN_AT}, ("exam_id","owner_public_id"))

    note_id,nv_id=ident(cid,"note"),ident(cid,"note-version"); note_text=f"今天学习{primary.title}：先用结构图梳理概念，再通过代码或小练习验证，最后用自己的话复述。"
    changed += repair(db, DBNote, note_id, {"student_id":owner.username,"source":"course_reader","content":note_text,"tags":["学习笔记",tag],"concepts":[primary.title],"source_metadata":{"course_id":cid,"source_ref_ids":source_ids,"demo_scope":SCOPE},"lock_version":1,"current_version_number":1,"ai_suggestion":"补充一个输入、过程、输出的最小例子。","ai_suggestion_metadata":{"demo_scope":SCOPE},"created_at":FROZEN_AT,"updated_at":FROZEN_AT}, ("student_id",))
    changed += repair(db, DBNoteVersion, nv_id, {"note_id":note_id,"version_number":1,"content":note_text,"tags":["学习笔记",tag],"concepts":[primary.title],"source":"course_reader","source_metadata":{"course_id":cid},"change_type":"saved","created_at":FROZEN_AT}, ("note_id",))
    conv_id=ident(cid,"chat"); changed += repair(db, DBChatConversation, conv_id, {"owner_public_id":owner.public_id,"course_id":cid,"title":f"{primary.title}学习讨论","status":"active","lock_version":1,"created_at":FROZEN_AT,"updated_at":FROZEN_AT}, ("owner_public_id","course_id"))
    chat_refs=[{"sourceRefId": ref_id, "courseId": cid} for ref_id in source_ids]
    messages=[("user",f"我怎样判断自己真的理解了{primary.title}？",[]),("assistant",f"可以用三步检查：先不用术语说清楚它解决什么问题，再拿一个具体输入走一遍过程，最后解释结果变化的原因。如果能完成这三步，并指出一个边界情况，说明理解已经从记忆走向应用。",chat_refs)]
    for i,(role,content,refs2) in enumerate(messages,1): changed += repair(db, DBChatMessage, ident(cid,"chat-message",f"{i:02d}"), {"conversation_id":conv_id,"owner_public_id":owner.public_id,"reply_to_message_id":ident(cid,"chat-message","01") if i==2 else None,"sequence":i,"role":role,"status":"completed","content":content,"content_sha256":digest(content),"idempotency_key":f"{SCOPE}:{ident(cid,'chat-message',f'{i:02d}')}","context_refs":[{"course_id":cid,"knowledge_point_id":primary.id}],"attachment_ids":[],"source_refs":refs2,"resource_links":[],"stream_checkpoint":{"completed":True,"deterministic_demo":True},"lock_version":1,"created_at":FROZEN_AT+timedelta(minutes=80+i),"updated_at":FROZEN_AT+timedelta(minutes=80+i),"completed_at":FROZEN_AT+timedelta(minutes=80+i)}, ("conversation_id","owner_public_id"))
    event_specs=[("resource_opened",resource_ids[0],"open",False,0.0,"none",{}),("quiz_answered",ident(cid,"question-version","02"),"submit",True,0.4,"progress",{"score":0.0,"correct":False,"knowledge_point_id":points[min(1,len(points)-1)].id}),("code_tests_passed",resource_ids[4],"run",True,0.7,"progress",{"knowledge_point_id":primary.id}),("feynman_submitted",resource_ids[8],"submit",True,0.64,"progress",{"knowledge_point_id":primary.id,"rubric_score":0.64}),("interactive_experiment_completed",resource_ids[7],"submit",True,0.75,"progress",{"knowledge_point_id":primary.id,"passed_checks":3,"total_checks":4}),("conversation_completed",conv_id,"complete",False,0.0,"none",{})]
    for i,(etype,obj,action,eligible,strength,effect,extra_payload) in enumerate(event_specs,1):
        obj_type = "artifact" if obj in resource_ids else ("assessment_question_version" if etype == "quiz_answered" else "conversation")
        eid=ident(cid,"event",f"{i:02d}"); changed += repair(db, DBLearningEvent,eid,{"owner_public_id":owner.public_id,"legacy_student_id":owner.username,"course_id":cid,"event_type":etype,"schema_version":"lzz.demo.learning-event.v1","idempotency_key":f"{SCOPE}:{eid}","source":"seed","trace_id":ident(cid,"trace"),"object_type":obj_type,"object_id":obj,"action":action,"context_ref":{"profile_snapshot_id":snap_id,"path_id":path_id,"knowledge_point_id":primary.id},"evidence_strength":strength,"evidence_status":"accepted" if eligible else "none","evidence_reason":"演示学习证据" if eligible else "普通浏览行为","mastery_eligible":eligible,"completion_effect":effect,"payload_version":"1","payload":{"demo_scope":SCOPE,"course_id":cid,"knowledge_point_ids":[primary.id],**extra_payload},"occurred_at":FROZEN_AT+timedelta(minutes=100+i),"recorded_at":FROZEN_AT+timedelta(minutes=100+i)}, ("owner_public_id","course_id"))
    return changed, {"course_id":cid,"path_id":path_id,"resource_ids":resource_ids,"profile_id":snap_id,"exam_id":exam_id,"conversation_id":conv_id,"event_count":len(event_specs)}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--dry-run",action="store_true"); args=parser.parse_args()
    db=SessionLocal(); result={"scope":SCOPE,"status":"unchanged","courses":[],"changed":0}
    try:
        owner=db.query(DBUser).filter_by(username="lzz").one()
        if owner.role != "student": raise ValueError("lzz must remain student")
        contexts=[course_context(db,cid) for cid in COURSES]
        for index,ctx in enumerate(contexts):
            delta, summary=ensure_course(db,owner,ctx,index); result["changed"] += delta; result["courses"].append(summary)
        profile=db.get(DBStudentProfile,owner.username)
        if profile is None: profile=DBStudentProfile(student_id=owner.username); db.add(profile); db.flush(); result["changed"]+=1
        merged_mastery={}
        weak=[]
        for ctx in contexts:
            for point in ctx["points"]: merged_mastery[point.title]=round(0.82,2)
            weak.extend(p.title for p in ctx["points"][-2:])
        desired={"target_course":"；".join(ctx["course"].title for ctx in contexts),"knowledge_base":"已开始系统学习机器学习与深度学习，正在通过练习巩固迁移。","cognitive_style":"结构图 + 代码验证 + 复述","motivation_type":"掌握与应用驱动","frustration_index":0.18,"focus_level":0.84,"cognitive_load":0.48,"weak_points":weak,"learning_goals":["建立两门人工智能基础课程的完整知识结构","能用练习和测验解释概念并发现边界","形成稳定的复述与复习习惯"],"interaction_preferences":["先看结构","边做边验证","最后复述"],"concept_mastery":merged_mastery,"misconception_patterns":{"只背定义不验证":0.32,"忽略边界条件":0.28},"dimension_states":{"知识理解":{"score":0.74,"confidence":0.86},"迁移应用":{"score":0.61,"confidence":0.72},"学习投入":{"score":0.83,"confidence":0.9}},"learning_state_causes":{"练习证据正在增加":{"label":"练习证据正在增加","percentage":46},"复述与复习仍需持续":{"label":"复述与复习仍需持续","percentage":31},"跨课程迁移刚开始":{"label":"跨课程迁移刚开始","percentage":23}},"history_logs":"已在两门人工智能基础课程中完成阅读、练习、测验、复述和对话演示。","narrative_report":"你已经建立了两门课程的学习起点，接下来继续用小练习和复述把理解变成稳定能力。","dashboard_report":"两门内置课程均已建立学习路径和演示行为记录，当前建议优先完成进行中的代码练习和错题复习。","major":"人工智能"}
        for field,value in desired.items():
            if getattr(profile,field)!=value: setattr(profile,field,value); result["changed"]+=1
        if args.dry_run: db.rollback()
        else:
            db.commit()
            # Project accepted behavior events into the same profile/path/review
            # read models used by the student pages.
            agg_db = SessionLocal()
            try:
                events = agg_db.query(DBLearningEvent).filter(
                    DBLearningEvent.owner_public_id == owner.public_id,
                    DBLearningEvent.course_id.in_(COURSES),
                    DBLearningEvent.mastery_eligible.is_(True),
                ).order_by(DBLearningEvent.occurred_at, DBLearningEvent.id).all()
                for event in events:
                    aggregate_learning_event(agg_db, event=event)
            finally:
                agg_db.close()
        result["status"]="repaired" if result["changed"] else "unchanged"
    except Exception:
        db.rollback(); raise
    finally: db.close()
    print(json.dumps(result,ensure_ascii=False,indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
