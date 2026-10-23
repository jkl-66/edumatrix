"""Evidence-derived, owner-scoped competition presentation journeys."""
from __future__ import annotations
import json
from app.database import (
    DBAssessmentAttempt, DBAssessmentExamReport, DBAssessmentExamSitting, DBAssessmentRetestTask,
    DBArtifact, DBArtifactVersion, DBCompetitionJourneyRun, DBCompetitionJourneyVisit,
    DBChapterVideoLink, DBCourse, DBCourseMembership, DBLearningEvent, DBLearningPath,
    DBPathNode, DBPlanDraft, DBPlanVersion, DBProfileSnapshot, DBUser,
    DBTeachingAnalyticsReport, DBTeachingClass, DBTeachingGroup, DBTeachingTask,
    DBContentReviewCase,
    DBCertification, DBCompetencyStandard, DBJobLevel, DBLocalAdapterSession,
    DBMultilevelReviewCase, DBOrganization, DBOrganizationMembership, DBRetrainingTask,
    DBSkillEvidence, DBTrainingAssignment, DBTrainingCohort, DBTrainingProgram,
    DBMarketplaceAcquisition, DBMarketplaceDecision, DBMarketplaceFavorite,
    DBMarketplaceFork, DBMarketplaceImpactEvent, DBMarketplaceImpactNotification,
    DBMarketplaceJourneySearchVerification, DBMarketplaceListing, DBMarketplaceReview,
    DBExternalIdentityMapping, DBHRSyncBatch, DBHRSyncRecord, DBIntegrationDelivery,
    DBIntegrationDeliveryEvent, DBIntegrationFaultDrill, DBIntegrationFaultDrillStep,
    DBIntegrationReconciliationRun, DBLMSAssignmentExchange, DBLocalLRSStatement,
    DBLocalSSOSession, DBWebhookReceipt,
    DBResourceBundle, DBResourceBundleItem, DBResourceBundleVersion, DBSpeechSession,
    DBVideoOutputVersion, DBVideoPracticeSet, DBVideoPracticeVersion, DBVideoProject,
    DBVideoRenderTask, DBWebDeck, DBWebDeckVersion,
)
from app.m7_integrations import _hash,_now
from app.marketplace import public_search

STEPS=[
 {"key":"profile","label":"学习画像","route":"/student-analysis","purpose":"查看版本化画像与证据"},
 {"key":"diagnosis","label":"能力诊断","route":"/assessment","purpose":"完成诊断测评并更新能力状态"},
 {"key":"path","label":"个性路径","route":"/workspace","purpose":"确认面向当前课程的学习路径"},
 {"key":"resource","label":"学习资源","route":"/golden-loop","purpose":"生成并检查版本化学习资源"},
 {"key":"lab","label":"交互实验","route":"/interactive-lab","purpose":"运行本地实验并通过隐藏验收"},
 {"key":"formal_exam","label":"正式测评","route":"/formal-exams","purpose":"提交正式考试并获得发布报告"},
 {"key":"retest","label":"错因复测","route":"/wrong-questions","purpose":"确认错因并完成延迟复测"},
 {"key":"path_update","label":"路径更新","route":"/workspace","purpose":"根据新证据更新路径版本或节点状态"},
]
MEDIA_STEPS=[
 {"key":"chapter","label":"课程章节","route":"/chapter-videos","purpose":"选择同一课程的规范章节与来源"},
 {"key":"handout","label":"版本化讲义","route":"/resources","purpose":"准备与课程绑定的讲义版本"},
 {"key":"deck","label":"网页课件","route":"/web-decks","purpose":"创建可播放和导出的网页 PPT"},
 {"key":"avatar_audio","label":"数字人 / 音频","route":"/speech-training","purpose":"形成真实离线语音或诚实披露的音轨状态"},
 {"key":"video","label":"课程视频","route":"/video-studio","purpose":"渲染带字幕和质量报告的视频输出"},
 {"key":"video_practice","label":"视频后练习","route":"/chapter-videos","purpose":"绑定版本化视频后练习"},
 {"key":"bundle","label":"学习资源包","route":"/resource-bundles","purpose":"冻结讲义、课件、视频等精确版本"},
]
TEACHER_STEPS=[
 {"key":"course","label":"课程治理","route":"/course-governance","purpose":"确认当前课程的教师管理权限"},
 {"key":"class_group","label":"班级 / 分组","route":"/course-governance","purpose":"建立同一课程的活动班级与教学分组"},
 {"key":"task","label":"任务发布","route":"/course-governance","purpose":"向班级或分组发布正式教学任务"},
 {"key":"analytics","label":"学情分析","route":"/teaching-analytics","purpose":"冻结可解释的班级周期分析报告"},
 {"key":"intervention","label":"教师干预","route":"/teacher/interventions","purpose":"发布干预并由学习者举证、教师确认完成"},
 {"key":"content_review","label":"内容审核","route":"/content-review","purpose":"完成同课程内容的审核或发布"},
 {"key":"effect_review","label":"效果回看","route":"/teaching-analytics","purpose":"在干预确认后生成新的冻结分析报告"},
]
ENTERPRISE_STEPS=[
 {"key":"job_standard","label":"合成岗位标准","route":"/enterprise-training","purpose":"确认冻结、版本化的演示岗位能力标准"},
 {"key":"role_gap","label":"转岗能力差距","route":"/enterprise-training","purpose":"冻结目标岗位与当前有效证据之间的差距"},
 {"key":"training_cohort","label":"培训批次","route":"/enterprise-training","purpose":"确认学员已进入绑定标准快照的培训批次"},
 {"key":"practical","label":"本地实操","route":"/local-adapter-lab","purpose":"通过本地模拟实验隐藏验收并回链技能证据"},
 {"key":"demo_signoff","label":"演示角色签核","route":"/multilevel-review","purpose":"由分离的演示角色完成三级责任审核"},
 {"key":"certification","label":"演示认证","route":"/enterprise-training","purpose":"基于完整证据签发绑定岗位快照的本地认证"},
 {"key":"retraining","label":"到期复训","route":"/certification-lifecycle","purpose":"到期扫描后生成可追责复训任务与本地通知"},
]
MARKETPLACE_STEPS=[
 {"key":"submission","label":"课程发布申请","route":"/marketplace","purpose":"确认冻结课程版本已提交公共市场审核"},
 {"key":"review_publish","label":"管理员审核发布","route":"/marketplace","purpose":"读取同一条目的批准与发布决策"},
 {"key":"search","label":"真实搜索验证","route":"/marketplace","purpose":"用冻结标题执行服务端搜索并固化命中证据"},
 {"key":"engagement","label":"收藏 / 使用后评价","route":"/marketplace","purpose":"验证指定体验学员的收藏与有证据评价"},
 {"key":"acquisition","label":"课程导入","route":"/marketplace","purpose":"导入为指定学员的可追溯派生课程"},
 {"key":"fork","label":"资源分叉","route":"/marketplace/forks","purpose":"基于同一获取记录建立独立版本线"},
 {"key":"update_notification","label":"上游更新通知","route":"/marketplace/forks","purpose":"接收同一来源后续版本的持久化影响通知"},
 {"key":"withdrawal_impact","label":"撤回影响","route":"/marketplace","purpose":"验证正式撤回决策、影响事件与本地通知"},
]
INTEGRATION_STEPS=[
 {"key":"sso","label":"模拟 SSO","route":"/local-sso","purpose":"完成同一合成组织与学员的本地身份映射和登录"},
 {"key":"hr_lms","label":"HR / LMS 同步","route":"/local-hr","purpose":"应用合成 HR 快照并同步同一学员的培训分配"},
 {"key":"xapi_webhook","label":"xAPI / Webhook","route":"/integration-sandbox","purpose":"将学习事件和培训事件送达本地 LRS 与签名接收端"},
 {"key":"fault","label":"故障演练","route":"/integration-fault-drills","purpose":"执行重复、乱序、撤销、冲突、断连、超时和死信场景"},
 {"key":"retry","label":"显式重试","route":"/integration-fault-drills","purpose":"验证同一死信投递经过显式重入队后恢复送达"},
 {"key":"reconciliation","label":"同步对账","route":"/integration-reconciliation","purpose":"在恢复后冻结并解决跨适配器差异"},
]
JOURNEY_STEPS={"student":STEPS,"media":MEDIA_STEPS,"teacher":TEACHER_STEPS,"enterprise":ENTERPRISE_STEPS,"marketplace":MARKETPLACE_STEPS,"integration":INTEGRATION_STEPS}
class JourneyError(ValueError):
 def __init__(self,code,message,status_code=409):super().__init__(message);self.code=code;self.status_code=status_code
def fail(code,message,status=409):raise JourneyError(code,message,status)
def _course(db,course_id):
 if not course_id:return None
 row=db.get(DBCourse,course_id)
 if not row:fail('journey_course_not_found','course does not exist',404)
 from course_catalog import course_is_selectable
 if not course_is_selectable(db,row):fail('journey_course_unavailable','course is not currently available for selection',409)
 return row
def _path_signature(db,owner,course_id):
 q=db.query(DBLearningPath).filter_by(owner_public_id=owner)
 if course_id:q=q.filter_by(course_id=course_id)
 rows=q.order_by(DBLearningPath.created_at).all();nodes=db.query(DBPathNode).filter(DBPathNode.learning_path_id.in_([x.id for x in rows] or ['-'])).all()
 return {'count':len(rows),'max_lock':max([x.lock_version for x in rows] or [0]),'node_states':sorted([f'{x.learning_path_id}:{x.id}:{x.status}' for x in nodes])}
def baseline(db,owner,course_id):return {'path':_path_signature(db,owner,course_id),'created_at':_now().isoformat()}

def _teacher_course_role(db,actor,course_id):
 if actor.role=='admin':return 'admin'
 course=db.get(DBCourse,course_id) if course_id else None
 if course and course.owner_public_id==actor.public_id:return 'owner'
 member=db.query(DBCourseMembership).filter_by(course_id=course_id,user_public_id=actor.public_id,status='active').first() if course_id else None
 return member.role if member else None

def _require_teacher_course(db,actor,course_id):
 if actor.role not in {'teacher','admin'}:fail('journey_forbidden','teacher journey requires a teacher or admin role',403)
 if not course_id:fail('journey_course_required','teacher journey requires a course',422)
 _course(db,course_id)
 if _teacher_course_role(db,actor,course_id) not in {'admin','owner','teacher','assistant'}:fail('journey_forbidden','active course management permission is required',403)

def _enterprise_role(db,actor,organization_id):
 member=db.query(DBOrganizationMembership).filter_by(organization_id=organization_id,user_public_id=actor.public_id,status='active').first()
 return member.role if member else None

def _require_enterprise_context(db,actor,organization_id,learner_public_id):
 if actor.role not in {'teacher','admin'}:fail('journey_forbidden','enterprise journey requires a teacher or admin role',403)
 org=db.get(DBOrganization,organization_id) if organization_id else None
 if not org or org.status!='active':fail('journey_organization_not_found','active organization does not exist',404)
 if _enterprise_role(db,actor,organization_id) not in {'manager','admin'}:fail('journey_forbidden','organization manager or admin permission is required',403)
 learner=db.query(DBOrganizationMembership).filter_by(organization_id=organization_id,user_public_id=learner_public_id,role='learner',status='active').first()
 if not learner:fail('journey_learner_not_found','active learner does not belong to organization',404)

def _assignment_context(db,organization_id,learner_public_id):
 assignment=db.query(DBTrainingAssignment).filter_by(organization_id=organization_id,learner_public_id=learner_public_id).order_by(DBTrainingAssignment.assigned_at.desc()).first()
 if not assignment:return None
 cohort=db.get(DBTrainingCohort,assignment.cohort_id);program=db.get(DBTrainingProgram,cohort.training_program_id) if cohort else None
 level=db.get(DBJobLevel,program.target_job_level_id) if program else None
 return {'assignment':assignment,'cohort':cohort,'program':program,'level':level}

def _frozen_assignment_context(db,base):
 assignment=db.get(DBTrainingAssignment,base.get('assignment_id')) if base.get('assignment_id') else None
 cohort=db.get(DBTrainingCohort,base.get('cohort_id')) if base.get('cohort_id') else None
 program=db.get(DBTrainingProgram,cohort.training_program_id) if cohort else None
 level=db.get(DBJobLevel,base.get('job_level_id')) if base.get('job_level_id') else None
 coherent=bool(
  assignment and cohort and program and level
  and assignment.organization_id==base.get('organization_id')
  and assignment.learner_public_id==base.get('learner_public_id')
  and assignment.cohort_id==cohort.id
  and cohort.organization_id==base.get('organization_id')
  and program.organization_id==base.get('organization_id')
  and program.target_job_level_id==level.id
  and level.version==base.get('job_level_version')
  and _hash(cohort.standard_snapshot or {})==base.get('standard_snapshot_hash')
 )
 return {'assignment':assignment,'cohort':cohort,'program':program,'level':level,'coherent':coherent}

def _enterprise_baseline(db,actor,organization_id,learner_public_id):
 _require_enterprise_context(db,actor,organization_id,learner_public_id)
 context=_assignment_context(db,organization_id,learner_public_id)
 if not context or not context['cohort'] or not context['level']:fail('journey_training_assignment_required','enterprise journey requires a training assignment',409)
 standards=db.query(DBCompetencyStandard).filter_by(job_level_id=context['level'].id,mandatory=True).order_by(DBCompetencyStandard.id).all()
 evidence=db.query(DBSkillEvidence).filter_by(organization_id=organization_id,learner_public_id=learner_public_id,result='passed').all()
 valid={row.competency_standard_id for row in evidence if row.valid_until is None or row.valid_until>=_now()}
 gaps=[row.id for row in standards if row.id not in valid]
 return {'organization_id':organization_id,'learner_public_id':learner_public_id,'assignment_id':context['assignment'].id,'cohort_id':context['cohort'].id,'job_level_id':context['level'].id,'job_level_version':context['level'].version,'standard_snapshot_hash':_hash(context['cohort'].standard_snapshot or {}),'standard_ids':[row.id for row in standards],'gap_standard_ids':gaps,'gap_count':len(gaps),'data_class':'frozen_synthetic_demo','created_at':_now().isoformat()}

def _intervention_confirmation(db,actor,course_id):
 versions=db.query(DBPlanVersion).filter_by(created_by_public_id=actor.public_id).order_by(DBPlanVersion.created_at.desc()).all()
 for version in versions:
  plan=db.query(DBPlanDraft).filter_by(id=version.plan_draft_id,course_id=course_id).first()
  if not plan or not plan.title.startswith('教师干预：'):continue
  path=db.query(DBLearningPath).filter_by(source_plan_version_id=version.id,status='completed').order_by(DBLearningPath.created_at.desc()).first()
  if not path:continue
  confirmations=db.query(DBLearningEvent).filter_by(owner_public_id=path.owner_public_id,course_id=course_id,event_type='teacher_confirmed').order_by(DBLearningEvent.occurred_at.desc()).all()
  for confirmation in confirmations:
   data=confirmation.payload or {}
   if data.get('teacher_public_id')!=actor.public_id:continue
   learner_event=db.get(DBLearningEvent,data.get('learner_event_id')) if data.get('learner_event_id') else None
   if learner_event and (learner_event.payload or {}).get('path_id')==path.id:
    return {'plan':plan,'path':path,'event':confirmation}
 return None
def _lab_evidence(db,owner,course_id):
 q=db.query(DBArtifact).filter_by(owner_public_id=owner,artifact_type='interactive_lab_instance')
 if course_id:q=q.filter((DBArtifact.course_id==course_id)|(DBArtifact.course_id.is_(None)))
 for artifact in q.all():
  version=db.get(DBArtifactVersion,artifact.current_version_id)
  if not version:continue
  try:data=json.loads(version.content)
  except Exception:continue
  if data.get('status')=='passed' and (data.get('hidden_acceptance') or {}).get('passed') is True:return {'artifact_id':artifact.id,'version_id':version.id,'status':'passed'}
 return None
def evidence(db,run):
 if run.journey_type=='media':return media_evidence(db,run)
 if run.journey_type=='teacher':return teacher_evidence(db,run)
 if run.journey_type=='enterprise':return enterprise_evidence(db,run)
 if run.journey_type=='marketplace':return marketplace_evidence(db,run)
 if run.journey_type=='integration':return integration_evidence(db,run)
 owner=run.owner_public_id;course=run.course_id
 profile=db.query(DBProfileSnapshot).filter_by(owner_public_id=owner).order_by(DBProfileSnapshot.created_at.desc()).first()
 diagnosis=db.query(DBAssessmentAttempt).filter_by(owner_public_id=owner,mode='diagnostic',grading_status='graded').order_by(DBAssessmentAttempt.submitted_at.desc()).first()
 pathq=db.query(DBLearningPath).filter_by(owner_public_id=owner)
 if course:pathq=pathq.filter_by(course_id=course)
 path=pathq.filter(DBLearningPath.status.in_(['active','completed'])).order_by(DBLearningPath.created_at.desc()).first()
 resources=db.query(DBArtifact).filter(DBArtifact.owner_public_id==owner,DBArtifact.artifact_type.in_(['lesson','lab_guide','tiered_quiz']),DBArtifact.current_version_id.is_not(None)).all()
 if course:resources=[x for x in resources if x.course_id in (None,course)]
 sittingq=db.query(DBAssessmentExamSitting).filter_by(owner_public_id=owner,status='released')
 sitting=sittingq.order_by(DBAssessmentExamSitting.released_at.desc()).first();report=db.query(DBAssessmentExamReport).filter_by(sitting_id=sitting.id).first() if sitting else None
 retestq=db.query(DBAssessmentRetestTask).filter_by(owner_public_id=owner,status='completed')
 if course:retestq=retestq.filter_by(course_id=course)
 retest=retestq.order_by(DBAssessmentRetestTask.completed_at.desc()).first()
 current_path=_path_signature(db,owner,course);base_path=(run.baseline_snapshot or {}).get('path') or {}
 if int(base_path.get('count') or 0)==0:
  path_changed=current_path['count']>=2 or current_path['max_lock']>=2 or any(not item.endswith(':pending') for item in current_path['node_states'])
 else:path_changed=current_path!=base_path
 values={
  'profile':{'complete':bool(profile),'evidence_id':profile.id if profile else None,'summary':'画像快照已冻结' if profile else '尚无画像快照'},
  'diagnosis':{'complete':bool(diagnosis),'evidence_id':diagnosis.id if diagnosis else None,'summary':'诊断测评已评分' if diagnosis else '需要完成诊断测评'},
  'path':{'complete':bool(path),'evidence_id':path.id if path else None,'summary':'个性路径已确认' if path else '需要确认学习路径'},
  'resource':{'complete':len({x.artifact_type for x in resources})>=3,'evidence_id':','.join(sorted(x.id for x in resources)),'summary':f"已就绪 {len({x.artifact_type for x in resources})}/3 类资源"},
  'lab':{'complete':bool(_lab_evidence(db,owner,course)),'evidence_id':(_lab_evidence(db,owner,course) or {}).get('version_id'),'summary':'实验隐藏验收已通过' if _lab_evidence(db,owner,course) else '需要通过实验隐藏验收'},
  'formal_exam':{'complete':bool(report),'evidence_id':report.id if report else None,'summary':'正式成绩报告已发布' if report else '需要完成正式考试并发布报告'},
  'retest':{'complete':bool(retest),'evidence_id':retest.id if retest else None,'summary':'错因复测已完成' if retest else '需要确认错因并完成复测'},
  'path_update':{'complete':path_changed,'evidence_id':_hash(current_path) if path_changed else None,'summary':'路径已根据新证据更新' if path_changed else '需要在本旅程中更新路径'},
 }
 return [{**step,**values[step['key']]} for step in STEPS]
def media_evidence(db,run):
 owner=run.owner_public_id;course=run.course_id
 chapterq=db.query(DBChapterVideoLink).filter_by(owner_public_id=owner)
 if course:chapterq=chapterq.filter_by(course_id=course)
 chapter=chapterq.order_by(DBChapterVideoLink.created_at.desc()).first()
 handoutq=db.query(DBArtifact).filter(DBArtifact.owner_public_id==owner,DBArtifact.artifact_type.in_(['lesson','lecture_note','handout']),DBArtifact.current_version_id.is_not(None))
 if course:handoutq=handoutq.filter(DBArtifact.course_id==course)
 handout=handoutq.order_by(DBArtifact.created_at.desc()).first()
 deckq=db.query(DBWebDeck).filter_by(owner_public_id=owner,status='active')
 if course:deckq=deckq.filter_by(course_id=course)
 deck=deckq.filter(DBWebDeck.current_version_id.is_not(None)).order_by(DBWebDeck.created_at.desc()).first()
 speech=db.query(DBSpeechSession).filter_by(owner_public_id=owner,status='completed',truth_state='real_offline').order_by(DBSpeechSession.completed_at.desc()).first()
 projectq=db.query(DBVideoProject).filter_by(owner_public_id=owner,status='active')
 if course:projectq=projectq.filter_by(course_id=course)
 projects=projectq.all();project_ids=[x.id for x in projects]
 output=db.query(DBVideoOutputVersion).filter(DBVideoOutputVersion.project_id.in_(project_ids or ['-'])).order_by(DBVideoOutputVersion.created_at.desc()).first()
 task=db.get(DBVideoRenderTask,output.render_task_id) if output else None
 audio=bool(speech or (task and task.status=='completed' and task.audio_status in {'sapi','text_only','unavailable'}))
 practiceq=db.query(DBVideoPracticeSet).filter_by(owner_public_id=owner,status='active')
 if course:practiceq=practiceq.filter_by(course_id=course)
 practice=practiceq.filter(DBVideoPracticeSet.current_version_id.is_not(None)).order_by(DBVideoPracticeSet.created_at.desc()).first()
 bundleq=db.query(DBResourceBundle).filter_by(owner_public_id=owner,status='active')
 if course:bundleq=bundleq.filter_by(course_id=course)
 bundle=bundleq.filter(DBResourceBundle.current_version_id.is_not(None)).order_by(DBResourceBundle.created_at.desc()).first()
 bundle_types=set()
 if bundle:bundle_types={x.resource_type for x in db.query(DBResourceBundleItem).filter_by(bundle_version_id=bundle.current_version_id).all()}
 bundle_complete=bool(bundle and {'handout','ppt','video'}.issubset(bundle_types))
 values={
  'chapter':{'complete':bool(chapter),'evidence_id':chapter.id if chapter else None,'summary':'章节与视频项目已形成不可变链接' if chapter else '需要建立章节视频链接'},
  'handout':{'complete':bool(handout),'evidence_id':handout.current_version_id if handout else None,'summary':'讲义不可变版本已就绪' if handout else '需要准备课程讲义'},
  'deck':{'complete':bool(deck),'evidence_id':deck.current_version_id if deck else None,'summary':'网页课件版本已就绪' if deck else '需要创建网页课件'},
  'avatar_audio':{'complete':audio,'evidence_id':speech.id if speech else (task.id if task else None),'summary':('真实离线语音已完成' if speech else f"视频音轨状态已披露：{task.audio_status}" if task else '需要完成离线语音或视频音轨')},
  'video':{'complete':bool(output and (output.quality_report or {}).get('passed')),'evidence_id':output.id if output else None,'summary':'视频输出与质量报告已就绪' if output else '需要渲染课程视频'},
  'video_practice':{'complete':bool(practice),'evidence_id':practice.current_version_id if practice else None,'summary':'视频后练习版本已绑定' if practice else '需要绑定视频后练习'},
  'bundle':{'complete':bundle_complete,'evidence_id':bundle.current_version_id if bundle_complete else None,'summary':f"资源包已冻结 {len(bundle_types)} 类资源" if bundle_complete else '需要冻结至少讲义、课件和视频版本'},
 }
 return [{**step,**values[step['key']]} for step in MEDIA_STEPS]

def teacher_evidence(db,run):
 actor=db.query(DBUser).filter_by(public_id=run.owner_public_id).first()
 _require_teacher_course(db,actor,run.course_id)
 course_id=run.course_id
 classes=db.query(DBTeachingClass).filter_by(course_id=course_id,status='active').order_by(DBTeachingClass.created_at).all()
 class_ids=[row.id for row in classes]
 groups=db.query(DBTeachingGroup).filter(DBTeachingGroup.class_id.in_(class_ids or ['-']),DBTeachingGroup.status=='active').all()
 grouped_class_ids={row.class_id for row in groups}
 coherent_classes=[row for row in classes if row.id in grouped_class_ids]
 coherent_ids=[row.id for row in coherent_classes]
 task=db.query(DBTeachingTask).filter(DBTeachingTask.class_id.in_(coherent_ids or ['-']),DBTeachingTask.status=='published').order_by(DBTeachingTask.published_at.desc()).first()
 reports=db.query(DBTeachingAnalyticsReport).filter(DBTeachingAnalyticsReport.class_id.in_(coherent_ids or ['-']),DBTeachingAnalyticsReport.course_id==course_id,DBTeachingAnalyticsReport.status=='frozen').order_by(DBTeachingAnalyticsReport.created_at).all()
 report=reports[-1] if reports else None
 intervention=_intervention_confirmation(db,actor,course_id)
 review=db.query(DBContentReviewCase).filter(DBContentReviewCase.course_id==course_id,DBContentReviewCase.status.in_(['approved','published'])).order_by(DBContentReviewCase.resolved_at.desc()).first()
 confirmation_at=intervention['event'].occurred_at if intervention else None
 effect=next((item for item in reversed(reports) if confirmation_at and item.created_at and item.created_at>confirmation_at),None)
 managed=_teacher_course_role(db,actor,course_id) in {'admin','owner','teacher','assistant'}
 values={
  'course':{'complete':managed,'evidence_id':course_id if managed else None,'summary':'课程教师管理权限有效' if managed else '需要课程教师管理权限'},
  'class_group':{'complete':bool(coherent_classes),'evidence_id':','.join(row.id for row in coherent_classes),'summary':f'已形成 {len(coherent_classes)} 个含活动分组的班级' if coherent_classes else '需要活动班级和活动分组'},
  'task':{'complete':bool(task),'evidence_id':task.id if task else None,'summary':'教学任务已正式发布' if task else '需要发布班级或分组任务'},
  'analytics':{'complete':bool(report),'evidence_id':report.id if report else None,'summary':'学情周期报告已冻结' if report else '需要生成冻结学情报告'},
  'intervention':{'complete':bool(intervention),'evidence_id':intervention['event'].id if intervention else None,'summary':'干预已由学习者举证并经教师确认' if intervention else '需要完成强证据干预闭环'},
  'content_review':{'complete':bool(review),'evidence_id':review.id if review else None,'summary':f'课程内容审核已达到 {review.status}' if review else '需要批准或发布课程内容'},
  'effect_review':{'complete':bool(effect),'evidence_id':effect.id if effect else None,'summary':'干预后的新分析报告已冻结' if effect else '需要在干预确认后生成新的分析报告'},
 }
 return [{**step,**values[step['key']]} for step in TEACHER_STEPS]

def enterprise_evidence(db,run):
 actor=db.query(DBUser).filter_by(public_id=run.owner_public_id).first();base=run.baseline_snapshot or {}
 org=base.get('organization_id');learner=base.get('learner_public_id');_require_enterprise_context(db,actor,org,learner)
 context=_frozen_assignment_context(db,base);assignment=context['assignment'];cohort=context['cohort']
 baseline_assignment=context['coherent']
 standard_ids=base.get('standard_ids') or []
 standard=bool(baseline_assignment and base.get('job_level_id') and base.get('job_level_version') and base.get('standard_snapshot_hash') and standard_ids)
 gap=standard and isinstance(base.get('gap_standard_ids'),list) and int(base.get('gap_count',-1))==len(base.get('gap_standard_ids'))
 sessions=db.query(DBLocalAdapterSession).filter_by(owner_public_id=learner,status='passed',environment='local_simulation').all()
 session_ids={row.id for row in sessions if (row.hidden_acceptance or {}).get('passed') is True}
 practical_evidence=db.query(DBSkillEvidence).filter(DBSkillEvidence.organization_id==org,DBSkillEvidence.learner_public_id==learner,DBSkillEvidence.source_object_id.in_(session_ids or ['-']),DBSkillEvidence.result=='passed').order_by(DBSkillEvidence.observed_at.desc()).first()
 signoff=db.query(DBMultilevelReviewCase).filter_by(organization_id=org,object_type='training_assignment',object_id=base.get('assignment_id'),object_version=base.get('standard_snapshot_hash'),status='signed').order_by(DBMultilevelReviewCase.resolved_at.desc()).first()
 certs=db.query(DBCertification).filter_by(organization_id=org,learner_public_id=learner,job_level_id=base.get('job_level_id')).filter(DBCertification.status.in_(['active','expired'])).order_by(DBCertification.issued_at.desc()).all()
 cert=next((row for row in certs if (row.standard_snapshot or {}).get('job_level_version')==base.get('job_level_version') and practical_evidence and practical_evidence.id in (row.evidence_ids or [])),None)
 retraining=db.query(DBRetrainingTask).filter_by(certification_id=cert.id,organization_id=org,learner_public_id=learner,trigger_type='expired').order_by(DBRetrainingTask.created_at.desc()).first() if cert else None
 values={
  'job_standard':{'complete':standard,'evidence_id':base.get('standard_snapshot_hash') if standard else None,'summary':f"岗位标准 {base.get('job_level_version')} 已冻结" if standard else '需要冻结岗位标准快照'},
  'role_gap':{'complete':gap,'evidence_id':_hash(base.get('gap_standard_ids')) if gap else None,'summary':f"启动时识别 {base.get('gap_count',0)} 项转岗差距" if gap else '需要形成转岗差距快照'},
  'training_cohort':{'complete':baseline_assignment,'evidence_id':assignment.id if baseline_assignment else None,'summary':'培训分配与批次标准快照一致' if baseline_assignment else '需要有效培训批次与学员分配'},
  'practical':{'complete':bool(practical_evidence),'evidence_id':practical_evidence.id if practical_evidence else None,'summary':'本地实操隐藏验收及技能证据已通过' if practical_evidence else '需要通过本地实操并回链技能证据'},
  'demo_signoff':{'complete':bool(signoff),'evidence_id':signoff.id if signoff else None,'summary':'三级演示角色责任签核已完成' if signoff else '需要完成角色分离的三级演示签核'},
  'certification':{'complete':bool(cert and signoff),'evidence_id':cert.id if cert and signoff else None,'summary':f'演示认证状态：{cert.status}' if cert and signoff else '需要在演示签核后基于完整证据签发演示认证'},
  'retraining':{'complete':bool(retraining),'evidence_id':retraining.id if retraining else None,'summary':'认证到期复训任务已生成' if retraining else '需要认证到期扫描生成复训任务'},
 }
 return [{**step,**values[step['key']]} for step in ENTERPRISE_STEPS]

def _marketplace_listing(db,base):
 listing=db.get(DBMarketplaceListing,base.get('listing_id')) if base.get('listing_id') else None
 if not listing or listing.course_id!=base.get('course_id') or listing.course_version!=base.get('course_version') or listing.snapshot_hash!=base.get('listing_snapshot_hash'):
  fail('journey_marketplace_context_invalid','frozen marketplace listing no longer matches its identity',409)
 recipient=db.query(DBUser).filter_by(public_id=base.get('recipient_public_id')).first()
 if not recipient:fail('journey_marketplace_recipient_not_found','frozen marketplace recipient does not exist',404)
 return listing,recipient

def _marketplace_baseline(db,actor,listing_id,recipient_public_id):
 if actor.role!='admin':fail('journey_forbidden','marketplace journey creation requires an administrator',403)
 listing=db.get(DBMarketplaceListing,listing_id)
 if not listing:fail('journey_marketplace_listing_not_found','marketplace listing does not exist',404)
 if listing.status not in {'pending','approved','published'}:fail('journey_marketplace_listing_invalid','listing must be submitted and not withdrawn',409)
 submitted=db.query(DBMarketplaceDecision).filter_by(listing_id=listing.id,action='submit').first()
 if not submitted:fail('journey_marketplace_submission_required','listing has no persisted submission decision',409)
 recipient=db.query(DBUser).filter_by(public_id=recipient_public_id).first()
 if not recipient or recipient.role not in {'student','teacher','admin'}:fail('journey_marketplace_recipient_not_found','experience recipient does not exist',404)
 if recipient.public_id==listing.owner_public_id:fail('journey_marketplace_recipient_invalid','publisher cannot be the frozen experience recipient',422)
 return {'listing_id':listing.id,'course_id':listing.course_id,'course_version':listing.course_version,'listing_snapshot_hash':listing.snapshot_hash,'listing_title':listing.title,'publisher_public_id':listing.owner_public_id,'recipient_public_id':recipient.public_id,'data_class':'frozen_synthetic_demo','created_at':_now().isoformat()}

def marketplace_evidence(db,run):
 base=run.baseline_snapshot or {};listing,recipient=_marketplace_listing(db,base)
 decisions=db.query(DBMarketplaceDecision).filter_by(listing_id=listing.id).order_by(DBMarketplaceDecision.created_at).all()
 submission=next((row for row in decisions if row.action=='submit' and row.to_status=='pending'),None)
 approved=next((row for row in decisions if row.action=='approve' and row.to_status=='approved'),None)
 published=next((row for row in decisions if row.action=='publish' and row.to_status=='published'),None)
 withdrawn=next((row for row in decisions if row.action=='withdraw' and row.to_status=='withdrawn'),None)
 search=db.query(DBMarketplaceJourneySearchVerification).filter_by(run_id=run.id,listing_id=listing.id,listing_snapshot_hash=base.get('listing_snapshot_hash'),recipient_public_id=recipient.public_id).first()
 acquisition=db.query(DBMarketplaceAcquisition).filter_by(listing_id=listing.id,recipient_public_id=recipient.public_id,listing_snapshot_hash=base.get('listing_snapshot_hash')).first()
 favorite=db.query(DBMarketplaceFavorite).filter_by(listing_id=listing.id,owner_public_id=recipient.public_id,status='active',listing_snapshot_hash=base.get('listing_snapshot_hash')).first()
 review=db.query(DBMarketplaceReview).filter_by(listing_id=listing.id,owner_public_id=recipient.public_id,status='active',listing_snapshot_hash=base.get('listing_snapshot_hash')).first()
 usage_count=db.query(DBLearningEvent).filter_by(owner_public_id=recipient.public_id,course_id=acquisition.derived_course_id).count() if acquisition else 0
 review_ok=bool(review and acquisition and review.acquisition_id==acquisition.id and review.derived_course_id==acquisition.derived_course_id and usage_count>0)
 fork=db.query(DBMarketplaceFork).filter_by(acquisition_id=acquisition.id,source_listing_id=listing.id,owner_public_id=recipient.public_id).first() if acquisition else None
 updates=db.query(DBMarketplaceImpactEvent).filter_by(source_listing_id=listing.id).filter(DBMarketplaceImpactEvent.impact_type.in_(['new_version','severe_fix','license_changed'])).all()
 update_notice=None
 withdrawal_event=None;withdrawal_notice=None
 if acquisition:
  for event in updates:
   notice=db.query(DBMarketplaceImpactNotification).filter_by(impact_event_id=event.id,acquisition_id=acquisition.id,owner_public_id=recipient.public_id,source_listing_id=listing.id).first()
   if notice:update_notice=notice;break
  withdrawal_event=db.query(DBMarketplaceImpactEvent).filter_by(source_listing_id=listing.id,impact_type='withdrawn').order_by(DBMarketplaceImpactEvent.created_at.desc()).first()
  if withdrawal_event:withdrawal_notice=db.query(DBMarketplaceImpactNotification).filter_by(impact_event_id=withdrawal_event.id,acquisition_id=acquisition.id,owner_public_id=recipient.public_id,source_listing_id=listing.id,notification_type='withdrawn').first()
 values={
  'submission':{'complete':bool(submission),'evidence_id':submission.id if submission else None,'summary':'发布申请及冻结版本已持久化' if submission else '需要提交同一课程版本'},
  'review_publish':{'complete':bool(approved and published),'evidence_id':published.id if approved and published else None,'summary':'管理员批准与正式发布决策完整' if approved and published else '需要管理员批准并发布'},
  'search':{'complete':bool(search),'evidence_id':search.id if search else None,'summary':'冻结标题已通过真实公共搜索命中' if search else '需要执行服务端搜索验证'},
  'engagement':{'complete':bool(favorite and review_ok),'evidence_id':','.join(x for x in [favorite.id if favorite else '',review.id if review_ok else ''] if x) or None,'summary':f'指定体验学员已收藏、评价并产生 {usage_count} 条学习事件' if favorite and review_ok else '需要收藏、导入、学习并完成使用后评价'},
  'acquisition':{'complete':bool(acquisition),'evidence_id':acquisition.id if acquisition else None,'summary':'派生课程与获取身份已固化' if acquisition else '需要指定学员导入课程'},
  'fork':{'complete':bool(fork),'evidence_id':fork.id if fork else None,'summary':'同一获取记录已建立独立分叉' if fork else '需要基于本次导入建立分叉'},
  'update_notification':{'complete':bool(update_notice),'evidence_id':update_notice.id if update_notice else None,'summary':'后续版本影响已写入指定学员本地收件箱' if update_notice else '需要发布后续版本并生成影响通知'},
  'withdrawal_impact':{'complete':bool(withdrawn and withdrawal_event and withdrawal_notice),'evidence_id':withdrawal_notice.id if withdrawn and withdrawal_event and withdrawal_notice else None,'summary':'正式撤回决策、影响事件与通知完整' if withdrawn and withdrawal_event and withdrawal_notice else '需要正式撤回源条目并生成影响通知'},
 }
 return [{**step,**values[step['key']]} for step in MARKETPLACE_STEPS]

def create_marketplace_run(db,*,actor,listing_id,recipient_public_id,run_key):
 snap=_marketplace_baseline(db,actor,listing_id,recipient_public_id)
 old=db.query(DBCompetitionJourneyRun).filter_by(owner_public_id=actor.public_id,journey_type='marketplace',run_key=run_key).first()
 if old:
  old_base=old.baseline_snapshot or {}
  if old_base.get('listing_id')!=listing_id or old_base.get('recipient_public_id')!=recipient_public_id:fail('journey_run_key_conflict','run key is bound to another marketplace context')
  return old,False
 row=DBCompetitionJourneyRun(owner_public_id=actor.public_id,course_id=snap['course_id'],journey_type='marketplace',run_key=run_key,baseline_snapshot=snap,baseline_hash=_hash(snap));db.add(row);db.commit();return row,True

def _integration_baseline(db,actor,organization_id,learner_public_id):
 _require_enterprise_context(db,actor,organization_id,learner_public_id)
 if actor.role!='admin':fail('journey_forbidden','integration journey requires a system administrator',403)
 org=db.get(DBOrganization,organization_id);learner=db.query(DBUser).filter_by(public_id=learner_public_id).first()
 return {'organization_id':org.id,'organization_name':org.name,'learner_public_id':learner.public_id,'learner_display_name':learner.display_name,'started_at':_now().isoformat(),'data_class':'frozen_synthetic_local_integration','network_sent':False,'real_enterprise_connected':False}

def integration_evidence(db,run):
 base=run.baseline_snapshot or {};org=base.get('organization_id');learner=base.get('learner_public_id')
 actor=db.query(DBUser).filter_by(public_id=run.owner_public_id).first();_require_enterprise_context(db,actor,org,learner)
 if actor.role!='admin':fail('journey_forbidden','integration journey requires a system administrator',403)
 started=run.created_at
 sso=db.query(DBLocalSSOSession).filter_by(organization_id=org,user_public_id=learner,status='active').filter(DBLocalSSOSession.issued_at>=started).order_by(DBLocalSSOSession.issued_at.desc()).first()
 identity=db.get(DBExternalIdentityMapping,sso.mapping_id) if sso and sso.mapping_id else None
 hr_records=db.query(DBHRSyncRecord).filter_by(organization_id=org,user_public_id=learner).filter(DBHRSyncRecord.outcome.in_(['created','updated','unchanged']),DBHRSyncRecord.created_at>=started).order_by(DBHRSyncRecord.created_at.desc()).all()
 hr=next((db.get(DBHRSyncBatch,row.batch_id) for row in hr_records if db.get(DBHRSyncBatch,row.batch_id) and db.get(DBHRSyncBatch,row.batch_id).status=='applied'),None)
 lms=db.query(DBLMSAssignmentExchange).filter_by(organization_id=org,status='assigned').filter(DBLMSAssignmentExchange.synced_at>=started).order_by(DBLMSAssignmentExchange.synced_at.desc()).first()
 if lms:
  assignment=db.get(DBTrainingAssignment,lms.training_assignment_id)
  if not assignment or assignment.learner_public_id!=learner:lms=None
 lrs=db.query(DBLocalLRSStatement).filter_by(organization_id=org,actor_public_id=learner).filter(DBLocalLRSStatement.received_at>=started).order_by(DBLocalLRSStatement.received_at.desc()).first()
 receipt=db.query(DBWebhookReceipt).filter_by(organization_id=org,outcome='accepted').filter(DBWebhookReceipt.received_at>=started).order_by(DBWebhookReceipt.received_at.desc()).first()
 drill=db.query(DBIntegrationFaultDrill).filter_by(organization_id=org,status='passed').filter(DBIntegrationFaultDrill.created_at>=started).order_by(DBIntegrationFaultDrill.completed_at.desc()).first()
 drill_steps=db.query(DBIntegrationFaultDrillStep).filter_by(drill_id=drill.id).order_by(DBIntegrationFaultDrillStep.scenario_index).all() if drill else []
 fault=bool(drill and len(drill_steps)==7 and all(row.outcome=='passed' for row in drill_steps))
 dead=next((row for row in drill_steps if row.scenario_key=='dead_letter' and (row.after_snapshot or {}).get('status')=='dead_letter'),None)
 retry=bool(dead and (dead.recovery_snapshot or {}).get('action')=='explicit_requeue' and (dead.recovery_snapshot or {}).get('status')=='delivered')
 reconq=db.query(DBIntegrationReconciliationRun).filter_by(organization_id=org,status='resolved').filter(DBIntegrationReconciliationRun.created_at>=started)
 if drill and drill.completed_at:reconq=reconq.filter(DBIntegrationReconciliationRun.created_at>=drill.completed_at)
 recon=reconq.order_by(DBIntegrationReconciliationRun.created_at.desc()).first()
 values={
  'sso':{'complete':bool(sso and identity and identity.status=='active'),'evidence_id':sso.id if sso and identity and identity.status=='active' else None,'summary':'本地身份映射与模拟登录已完成' if sso and identity and identity.status=='active' else '需要为冻结学员完成本地 SSO 绑定和登录'},
  'hr_lms':{'complete':bool(hr and lms),'evidence_id':','.join(x for x in [hr.id if hr else '',lms.id if lms else ''] if x) or None,'summary':'合成 HR 入站与 LMS 培训分配同步完整' if hr and lms else '需要应用 HR 快照并同步同一学员的 LMS 分配'},
  'xapi_webhook':{'complete':bool(lrs and receipt),'evidence_id':','.join(x for x in [lrs.id if lrs else '',receipt.id if receipt else ''] if x) or None,'summary':'xAPI 已送达本地 LRS，签名 Webhook 已接收' if lrs and receipt else '需要完成 xAPI 与签名 Webhook 的本地双投递'},
  'fault':{'complete':fault,'evidence_id':drill.id if fault else None,'summary':'七类故障场景及权威数据保护已通过' if fault else '需要完成七场景集成故障演练'},
  'retry':{'complete':retry,'evidence_id':dead.id if retry else None,'summary':'同一死信已显式重入队并恢复送达' if retry else '需要形成 dead_letter 到 delivered 的恢复证据'},
  'reconciliation':{'complete':bool(recon and retry),'evidence_id':recon.id if recon and retry else None,'summary':'恢复后跨适配器对账已冻结并解决' if recon and retry else '需要在故障恢复后完成同步对账'},
 }
 return [{**step,**values[step['key']]} for step in INTEGRATION_STEPS]

def create_integration_run(db,*,actor,organization_id,learner_public_id,run_key):
 snap=_integration_baseline(db,actor,organization_id,learner_public_id)
 old=db.query(DBCompetitionJourneyRun).filter_by(owner_public_id=actor.public_id,journey_type='integration',run_key=run_key).first()
 if old:
  old_base=old.baseline_snapshot or {}
  if old_base.get('organization_id')!=organization_id or old_base.get('learner_public_id')!=learner_public_id:fail('journey_run_key_conflict','run key is bound to another integration context')
  return old,False
 row=DBCompetitionJourneyRun(owner_public_id=actor.public_id,course_id=None,journey_type='integration',run_key=run_key,baseline_snapshot=snap,baseline_hash=_hash(snap));db.add(row);db.commit();return row,True

def verify_marketplace_search(db,*,actor,run_id):
 row=_owned(db,actor,run_id)
 if row.journey_type!='marketplace':fail('journey_type_mismatch','journey is not a marketplace run',404)
 if actor.role!='admin':fail('journey_forbidden','marketplace search verification requires an administrator',403)
 base=row.baseline_snapshot or {};listing,recipient=_marketplace_listing(db,base)
 existing=db.query(DBMarketplaceJourneySearchVerification).filter_by(run_id=row.id).first()
 if existing:return existing,False
 matches=public_search(db,query=base.get('listing_title',''),actor=recipient)
 match=next((item for item in matches if item['id']==listing.id and item['snapshot_hash']==base.get('listing_snapshot_hash')),None)
 if not match:fail('journey_marketplace_search_miss','frozen listing is not discoverable through public search',409)
 snap={'listing_id':listing.id,'snapshot_hash':listing.snapshot_hash,'query':base.get('listing_title',''),'matched_ids':[item['id'] for item in matches],'matched_count':len(matches)}
 proof=DBMarketplaceJourneySearchVerification(run_id=row.id,listing_id=listing.id,listing_snapshot_hash=listing.snapshot_hash,recipient_public_id=recipient.public_id,query=base.get('listing_title',''),result_snapshot=snap,result_hash=_hash(snap),verified_by_public_id=actor.public_id);db.add(proof);db.commit();return proof,True

def create_enterprise_run(db,*,actor,organization_id,learner_public_id,run_key):
 snap=_enterprise_baseline(db,actor,organization_id,learner_public_id)
 old=db.query(DBCompetitionJourneyRun).filter_by(owner_public_id=actor.public_id,journey_type='enterprise',run_key=run_key).first()
 if old:
  old_base=old.baseline_snapshot or {}
  if old_base.get('organization_id')!=organization_id or old_base.get('learner_public_id')!=learner_public_id:fail('journey_run_key_conflict','run key is bound to another enterprise context')
  return old,False
 row=DBCompetitionJourneyRun(owner_public_id=actor.public_id,course_id=None,journey_type='enterprise',run_key=run_key,baseline_snapshot=snap,baseline_hash=_hash(snap));db.add(row);db.commit();return row,True
def create_run(db,*,actor:DBUser,course_id,run_key,journey_type='student'):
 if journey_type not in JOURNEY_STEPS:fail('journey_type_invalid','journey type is unsupported',422)
 if journey_type=='teacher':_require_teacher_course(db,actor,course_id)
 elif actor.role not in {'student','admin','teacher'}:fail('journey_forbidden','role cannot start this journey',403)
 _course(db,course_id);old=db.query(DBCompetitionJourneyRun).filter_by(owner_public_id=actor.public_id,journey_type=journey_type,run_key=run_key).first()
 if old:
  if old.course_id!=course_id:fail('journey_run_key_conflict','run key is bound to another course')
  return old,False
 snap=baseline(db,actor.public_id,course_id);row=DBCompetitionJourneyRun(owner_public_id=actor.public_id,course_id=course_id,journey_type=journey_type,run_key=run_key,baseline_snapshot=snap,baseline_hash=_hash(snap));db.add(row);db.commit();return row,True
def _owned(db,actor,run_id):
 row=db.get(DBCompetitionJourneyRun,run_id)
 if not row:fail('journey_not_found','journey run does not exist',404)
 if row.owner_public_id!=actor.public_id:fail('journey_forbidden','journey belongs to another owner',403)
 return row
def refresh_run(db,*,actor:DBUser,run_id):
 row=_owned(db,actor,run_id);steps=evidence(db,row);complete=all(x['complete'] for x in steps)
 if complete and row.status!='completed':row.status='completed';row.completed_at=_now();row.lock_version+=1;db.commit()
 return row,steps
def record_visit(db,*,actor:DBUser,run_id,step_key,route):
 row,steps=refresh_run(db,actor=actor,run_id=run_id);step=next((x for x in steps if x['key']==step_key),None)
 if not step:fail('journey_step_not_found','journey step does not exist',404)
 if route!=step['route']:fail('journey_route_mismatch','route does not match frozen step contract',422)
 snap={'step_key':step_key,'route':route,'complete_at_visit':step['complete'],'evidence_id':step['evidence_id']};visit=DBCompetitionJourneyVisit(run_id=row.id,owner_public_id=actor.public_id,step_key=step_key,route=route,evidence_snapshot=snap,evidence_hash=_hash(snap));db.add(visit);db.commit();return visit
def payload(db,actor,row):
 row,steps=refresh_run(db,actor=actor,run_id=row.id);visits=db.query(DBCompetitionJourneyVisit).filter_by(run_id=row.id).order_by(DBCompetitionJourneyVisit.created_at).all();done=sum(1 for x in steps if x['complete'])
 result={'id':row.id,'journey_type':row.journey_type,'course_id':row.course_id,'run_key':row.run_key,'status':row.status,'lock_version':row.lock_version,'progress':{'completed':done,'total':len(steps),'percent':round(done/len(steps)*100)},'steps':steps,'visits':[{'id':x.id,'step_key':x.step_key,'route':x.route,'evidence_snapshot':x.evidence_snapshot,'evidence_hash':x.evidence_hash,'created_at':x.created_at.isoformat()} for x in visits],'baseline_hash':row.baseline_hash,'created_at':row.created_at.isoformat(),'completed_at':row.completed_at.isoformat() if row.completed_at else None}
 if row.journey_type=='enterprise':
  base=row.baseline_snapshot or {};result['enterprise_context']={'organization_id':base.get('organization_id'),'learner_public_id':base.get('learner_public_id'),'assignment_id':base.get('assignment_id'),'cohort_id':base.get('cohort_id'),'job_level_id':base.get('job_level_id'),'job_level_version':base.get('job_level_version'),'standard_snapshot_hash':base.get('standard_snapshot_hash'),'data_class':base.get('data_class')}
 if row.journey_type=='marketplace':
   base=row.baseline_snapshot or {};result['marketplace_context']={'listing_id':base.get('listing_id'),'course_id':base.get('course_id'),'course_version':base.get('course_version'),'listing_snapshot_hash':base.get('listing_snapshot_hash'),'listing_title':base.get('listing_title'),'publisher_public_id':base.get('publisher_public_id'),'recipient_public_id':base.get('recipient_public_id'),'data_class':base.get('data_class')}
 if row.journey_type=='integration':
  base=row.baseline_snapshot or {};result['integration_context']={'organization_id':base.get('organization_id'),'organization_name':base.get('organization_name'),'learner_public_id':base.get('learner_public_id'),'learner_display_name':base.get('learner_display_name'),'data_class':base.get('data_class'),'network_sent':base.get('network_sent'),'real_enterprise_connected':base.get('real_enterprise_connected')}
 return result
def workspace(db,*,actor:DBUser,journey_type='student'):
 from course_catalog import course_is_selectable
 if journey_type=='teacher' and actor.role not in {'teacher','admin'}:fail('journey_forbidden','teacher journey requires a teacher or admin role',403)
 course_rows=[x for x in db.query(DBCourse).order_by(DBCourse.title).all() if course_is_selectable(db,x)]
 if journey_type=='teacher':course_rows=[x for x in course_rows if _teacher_course_role(db,actor,x.id) in {'admin','owner','teacher','assistant'}]
 courses=[{'id':x.id,'title':x.title,'version':x.version} for x in course_rows]
 rows=db.query(DBCompetitionJourneyRun).filter_by(owner_public_id=actor.public_id,journey_type=journey_type).order_by(DBCompetitionJourneyRun.created_at.desc()).limit(20).all()
 return {'courses':courses,'runs':[payload(db,actor,x) for x in rows],'truthfulness':{'completion_rule':'server_observed_evidence','visit_is_completion':False,'disclaimer':'旅程访问记录不等于功能完成；每一步只由当前用户的持久化业务证据判定。'}}

def enterprise_workspace(db,*,actor):
 if actor.role not in {'teacher','admin'}:fail('journey_forbidden','enterprise journey requires a teacher or admin role',403)
 memberships=db.query(DBOrganizationMembership).filter_by(user_public_id=actor.public_id,status='active').all()
 memberships=[row for row in memberships if row.role in {'manager','admin'}]
 organizations=[]
 for member in memberships:
  org=db.get(DBOrganization,member.organization_id)
  if not org or org.status!='active':continue
  learners=db.query(DBOrganizationMembership).filter_by(organization_id=org.id,role='learner',status='active').all()
  users={row.public_id:row for row in db.query(DBUser).filter(DBUser.public_id.in_([x.user_public_id for x in learners] or ['-'])).all()}
  organizations.append({'id':org.id,'name':org.name,'role':member.role,'learners':[{'public_id':x.user_public_id,'display_name':users[x.user_public_id].display_name} for x in learners if x.user_public_id in users]})
 rows=db.query(DBCompetitionJourneyRun).filter_by(owner_public_id=actor.public_id,journey_type='enterprise').order_by(DBCompetitionJourneyRun.created_at.desc()).limit(20).all()
 return {'organizations':organizations,'runs':[payload(db,actor,row) for row in rows],'truthfulness':{'completion_rule':'server_observed_evidence','visit_is_completion':False,'data_label':'冻结合成岗位标准 · 比赛演示数据','review_label':'演示角色签核，不代表真实企业或外部专家认证'}}

def marketplace_workspace(db,*,actor):
 if actor.role!='admin':fail('journey_forbidden','marketplace journey requires an administrator',403)
 listings=[]
 for row in db.query(DBMarketplaceListing).order_by(DBMarketplaceListing.created_at.desc()).all():
  submitted=db.query(DBMarketplaceDecision).filter_by(listing_id=row.id,action='submit').first()
  if submitted:
   listings.append({'id':row.id,'title':row.title,'course_id':row.course_id,'course_version':row.course_version,'snapshot_hash':row.snapshot_hash,'status':row.status,'owner_public_id':row.owner_public_id,'can_start':row.status in {'pending','approved','published'}})
 recipients=[{'public_id':row.public_id,'display_name':row.display_name,'role':row.role} for row in db.query(DBUser).filter(DBUser.role.in_(['student','teacher','admin'])).order_by(DBUser.display_name).all()]
 rows=db.query(DBCompetitionJourneyRun).filter_by(owner_public_id=actor.public_id,journey_type='marketplace').order_by(DBCompetitionJourneyRun.created_at.desc()).limit(20).all()
 return {'listings':listings,'recipients':recipients,'runs':[payload(db,actor,row) for row in rows],'truthfulness':{'completion_rule':'server_observed_evidence','visit_is_completion':False,'data_label':'冻结合成课程与演示账号','review_label':'管理员审核为比赛演示责任流程，不代表法律审查或第三方认证','transaction_label':'无支付交易；导入形成可追溯本地副本'}}

def integration_workspace(db,*,actor):
 if actor.role!='admin':fail('journey_forbidden','integration journey requires a system administrator',403)
 memberships=db.query(DBOrganizationMembership).filter_by(user_public_id=actor.public_id,role='admin',status='active').all();organizations=[]
 for member in memberships:
  org=db.get(DBOrganization,member.organization_id)
  if not org or org.status!='active':continue
  learner_members=db.query(DBOrganizationMembership).filter_by(organization_id=org.id,role='learner',status='active').all()
  users={row.public_id:row for row in db.query(DBUser).filter(DBUser.public_id.in_([x.user_public_id for x in learner_members] or ['-'])).all()}
  organizations.append({'id':org.id,'name':org.name,'learners':[{'public_id':x.user_public_id,'display_name':users[x.user_public_id].display_name} for x in learner_members if x.user_public_id in users]})
 rows=db.query(DBCompetitionJourneyRun).filter_by(owner_public_id=actor.public_id,journey_type='integration').order_by(DBCompetitionJourneyRun.created_at.desc()).limit(20).all()
 return {'organizations':organizations,'runs':[payload(db,actor,row) for row in rows],'truthfulness':{'completion_rule':'server_observed_evidence','visit_is_completion':False,'data_label':'本地模拟集成 · 冻结合成组织与身份数据','network_sent':False,'real_enterprise_connected':False,'certification_label':'不代表真实 OIDC/SAML、LMS/xAPI 互操作认证、企业容灾或第三方审计'}}
