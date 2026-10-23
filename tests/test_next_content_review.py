import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.auth import get_current_user,get_password_hash
from app.content_review import ContentReviewError,case_payload,submit_review,transition
from app.database import Base,DBArtifact,DBArtifactVersion,DBChapter,DBClaimCheck,DBContentReviewDecision,DBCourse,DBCourseMembership,DBQualityCheck,DBSourceDocument,DBSourceRef,DBUser
from app.main import app
import app.content_review_api as review_api

def fixture():
    engine=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool);Base.metadata.create_all(engine);db=sessionmaker(bind=engine)()
    teacher=DBUser(public_id='cr-teacher',username='cr-teacher',hashed_password=get_password_hash('pw'),role='teacher',display_name='Teacher')
    student=DBUser(public_id='cr-student',username='cr-student',hashed_password=get_password_hash('pw'),role='student',display_name='Student')
    outsider=DBUser(public_id='cr-outsider',username='cr-outsider',hashed_password=get_password_hash('pw'),role='teacher',display_name='Outsider')
    course=DBCourse(id='cr-course',version='1',title='Review',visibility='private',manifest_version='1',owner_public_id=teacher.public_id)
    db.add_all([teacher,student,outsider,course]);db.flush();db.add_all([DBCourseMembership(course_id=course.id,user_public_id=teacher.public_id,role='teacher',status='active'),DBCourseMembership(course_id=course.id,user_public_id=student.public_id,role='student',status='active')])
    content='Evidence-backed RAG lesson';version=DBArtifactVersion(id='cr-v1',artifact_id='cr-art',version_number=1,content=content,content_hash=hashlib.sha256(content.encode()).hexdigest(),created_by_public_id=student.public_id)
    artifact=DBArtifact(id='cr-art',owner_public_id=student.public_id,course_id=course.id,artifact_type='lesson',title='RAG Lesson',status='draft',current_version_id=version.id)
    db.add(artifact);db.flush();db.add(version);db.flush()
    document=DBSourceDocument(id='cr-doc',course_id=course.id,title='RAG 课程讲义',filename='rag-course.md',file_format='markdown',content_hash='doc-hash',source_sha256='source-hash',processed_sha256='processed-hash',uploader_public_id=teacher.public_id)
    db.add(document);db.flush()
    chapter=DBChapter(id='cr-chapter',course_id=course.id,source_document_id=document.id,stable_key='rag-evaluation',title='检索增强生成评测',position=1)
    db.add(chapter);db.flush()
    source_ref=DBSourceRef(id='cr-ref',source_document_id=document.id,chapter_id=chapter.id,parser_version='parser-v1',page_number=12,location_kind='page',location_label='第 12 页 · 评测指标',content_hash='ref-hash',quote='混合检索结合关键词与向量召回，以提高证据覆盖。')
    db.add(source_ref);db.flush()
    db.add_all([DBQualityCheck(id='cr-qc',artifact_version_id=version.id,trace_id='trace',check_type='citation',checker_version='1',status='passed',score=.9,details={'private_note':'do-not-expose'},source_ref_ids=[source_ref.id]),DBClaimCheck(id='cr-claim',artifact_version_id=version.id,trace_id='trace',atomic_claim='Hybrid retrieval improves recall',source_ref_id=source_ref.id,support_status='supported',verdict='supported',rationale='internal-only-rationale')]);db.commit();return db,engine,teacher,student,outsider,artifact,version

def test_full_review_publish_withdraw_preserves_evidence():
    db,_,teacher,student,_,artifact,version=fixture();case=submit_review(db,actor=student,artifact_id=artifact.id,version_id=version.id,submission_note='submit evidence lesson');assert case.evidence_snapshot['summary']=={'quality_total':1,'quality_passed':1,'claims_total':1,'claims_supported':1}
    case=transition(db,actor=teacher,case_id=case.id,action='approve',reason='evidence checks passed',expected_version=case.lock_version);assert artifact.status=='approved'
    case=transition(db,actor=teacher,case_id=case.id,action='publish',reason='approved for course release',expected_version=case.lock_version);assert artifact.status=='published'
    case=transition(db,actor=teacher,case_id=case.id,action='withdraw',reason='superseded content withdrawal',expected_version=case.lock_version);db.commit();assert artifact.status=='withdrawn' and db.query(DBQualityCheck).count()==1 and db.query(DBContentReviewDecision).count()==4

def test_changes_requested_requires_new_version_for_resubmission():
    db,_,teacher,student,_,artifact,version=fixture();case=submit_review(db,actor=student,artifact_id=artifact.id,version_id=version.id,submission_note='submit first version');transition(db,actor=teacher,case_id=case.id,action='request_changes',reason='add a canonical source',expected_version=case.lock_version);assert artifact.status=='draft'
    with pytest.raises(ContentReviewError):submit_review(db,actor=student,artifact_id=artifact.id,version_id=version.id,submission_note='same version retry')

def test_student_and_outsider_cannot_review():
    db,_,_,student,outsider,artifact,version=fixture();case=submit_review(db,actor=student,artifact_id=artifact.id,version_id=version.id,submission_note='submit for teacher review')
    for actor in (student,outsider):
        with pytest.raises(ContentReviewError) as exc:transition(db,actor=actor,case_id=case.id,action='approve',reason='unauthorized approval',expected_version=case.lock_version)
        assert exc.value.code=='review_forbidden'

def test_http_queue_decisions_and_cross_course_visibility(monkeypatch):
    db,_,teacher,student,outsider,artifact,version=fixture();identity={'user':student}
    async def fake(operation):return operation(db)
    monkeypatch.setattr(review_api,'run_db_op',fake);app.dependency_overrides[get_current_user]=lambda:identity['user'];client=TestClient(app)
    try:
        created=client.post('/api/v1/content-review/cases',json={'artifact_id':artifact.id,'version_id':version.id,'submission_note':'submit through API'});assert created.status_code==201
        case=created.json();identity['user']=teacher
        approved=client.post(f"/api/v1/content-review/cases/{case['id']}/decisions",json={'action':'approve','reason':'quality evidence accepted','expected_version':case['lock_version']});assert approved.status_code==200
        conflict=client.post(f"/api/v1/content-review/cases/{case['id']}/decisions",json={'action':'publish','reason':'stale review attempt','expected_version':case['lock_version']});assert conflict.status_code==409 and conflict.json()['detail']['code']=='review_version_conflict'
        identity['user']=outsider;assert client.get('/api/v1/content-review/queue').json()['items']==[]
        assert client.get(f"/api/v1/content-review/cases/{case['id']}").status_code==404
    finally:app.dependency_overrides.pop(get_current_user,None)

def test_decisions_are_database_immutable():
    db,engine,_,student,_,artifact,version=fixture();case=submit_review(db,actor=student,artifact_id=artifact.id,version_id=version.id,submission_note='immutable decision test');db.commit()
    with engine.begin() as c:c.exec_driver_sql("CREATE TRIGGER IF NOT EXISTS trg_content_review_decision_no_update BEFORE UPDATE ON content_review_decisions BEGIN SELECT RAISE(ABORT, 'content review decision is immutable'); END")
    with pytest.raises(DatabaseError):db.query(DBContentReviewDecision).filter_by(review_case_id=case.id).update({'reason':'changed'})

def test_case_payload_exposes_locatable_sources_and_public_agent_whitelist():
    db,_,_,student,_,artifact,version=fixture();case=submit_review(db,actor=student,artifact_id=artifact.id,version_id=version.id,submission_note='review source-backed lesson')
    payload=case_payload(db,case);source=payload['evidence']['sources'][0]
    assert source=={'id':'cr-ref','available':True,'document_id':'cr-doc','document_title':'RAG 课程讲义','filename':'rag-course.md','chapter_title':'检索增强生成评测','page_number':12,'location_label':'第 12 页 · 评测指标','quote':'混合检索结合关键词与向量召回，以提高证据覆盖。'}
    assert payload['evidence']['quality_checks'][0]['source_ref_ids']==['cr-ref']
    assert payload['evidence']['claim_checks'][0]['source_ref_id']=='cr-ref'
    assert payload['submission_note']=='review source-backed lesson'
    allowed={'runId','role','inputRefs','candidateSummary','disagreement','validation','revision','decisionSummary','status'}
    assert payload['agent_audit']['items'] and all(set(item)==allowed for item in payload['agent_audit']['items'])
    encoded=json.dumps(payload,ensure_ascii=False).lower()
    for private_value in ('do-not-expose','internal-only-rationale'):
        assert private_value not in encoded
