"""Two synthetic learners, identical wrong choice, different observed reasons."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf-8')


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-pid', type=int, required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    import psutil
    import httpx
    os.environ.update({k:v for k,v in psutil.Process(args.runtime_pid).environ().items() if k.startswith('EDUMATRIX_')})
    assert Path(os.environ['EDUMATRIX_DB_PATH']).name == 'acceptance.sqlite3'
    from app.database import (SessionLocal, DBUser, DBCourseMembership, DBProfileSnapshot,
        DBAssessmentAttempt, DBMisconceptionReview, DBLearningEvent)
    from app.m5_assessment_core import create_question_version, QuestionVersionInput, record_attempt, AttemptInput
    from app.m1_repository import create_artifact_with_version
    from app.m5_resources import QuizResourceContent
    from app.profile_adaptation import with_current_learning_evidence, build_profile_adaptation
    from app.learning_inquiry import prepare_inquiry, answer_inquiry
    from llm_client import AsyncOpenAIChatLLM
    from config import CONFIG
    root = Path(args.output); root.mkdir(parents=True, exist_ok=True)
    course = 'course-ai-deep-learning-agents-v1'
    point = 'kp-e19ac82873cf72f6c7b27522'
    refs = ['ref-9e813bffe27b5705da77d217', 'ref-f93b7fce536564cda6ee3c99']
    fixture = root/'inputs.json'
    if fixture.exists():
        cases = json.loads(fixture.read_text(encoding='utf-8'))['cases']
    else:
        cases=[]
        for name, reply in [('train','我看训练MSE，A的0.06最低，所以在新数据上也最好。'),
                            ('direction','我看验证MSE，A的0.22最高，分数越高越好。')]:
            username = 'extension-inquiry-'+name+'-r193'
            response = httpx.post('http://127.0.0.1:8944/api/auth/register', json={
                'username':username,'password':'SyntheticLearning193!','display_name':'学习者甲' if name=='train' else '学习者乙'})
            assert response.status_code in (200,201,400,409)
            with SessionLocal() as db:
                actor = db.query(DBUser).filter_by(username=username).one()
                if not db.query(DBCourseMembership).filter_by(course_id=course,user_public_id=actor.public_id).first():
                    db.add(DBCourseMembership(course_id=course,user_public_id=actor.public_id,role='student',status='active'))
                baseline = {'course_id':course,'learning_goals':'根据独立验证数据选择模型',
                    'knowledge_base':'已经知道误差数值来自训练集或验证集，需要进一步理解如何选模型。'}
                db.add(DBProfileSnapshot(owner_public_id=actor.public_id,legacy_student_id=username,
                    profile_version='inquiry-synthetic-r193',snapshot=baseline,
                    content_hash=hashlib.sha256(json.dumps(baseline).encode()).hexdigest(),trace_id='inquiry-r193'))
                _, qv = create_question_version(db,owner_public_id=actor.public_id,course_id=course,
                    question_type='single_choice',origin='manual',version=QuestionVersionInput(
                        prompt='三个候选模型使用相同数据划分和MSE指标，测试集尚未使用。A的训练/验证MSE为0.06/0.22，B为0.10/0.16，C为0.14/0.19。为同分布的新数据选择模型，应选哪个？',
                        options=('模型A','模型B','模型C'),answer_key={'choice':'B'},scoring_rule={'type':'exact'},
                        explanation='B的验证MSE为0.16，是三者最低的。验证集用于比较候选模型在未参与拟合的数据上的表现。',
                        primary_knowledge_point_id=point,source_ref_ids=tuple(refs)))
                body=QuizResourceContent(title='选择模型：说说你的判断',summary='根据验证表现选择模型',
                    courseTitle='人工智能与深度学习',knowledgePoint={'id':point,'title':'训练误差与泛化误差'},
                    adaptation={'learningGoal':'根据验证表现选择模型','profileSummary':'合成学习者代表验证',
                                'masterySummary':'以实际作答为依据','recentLearningSummary':'完成模型选择练习'},
                    sourceRefIds=refs,questions=[{'questionVersionId':qv.id,'position':1}],requiredQuestionCount=1)
                resource, version = create_artifact_with_version(db,owner_public_id=actor.public_id,artifact_type='quiz',
                    title=body.title,content=body.model_dump_json(),content_format='json',course_id=course)
                attempt,_=record_attempt(db,owner_public_id=actor.public_id,attempt=AttemptInput(
                    question_version_id=qv.id,idempotency_key='inquiry-r193-'+name,answer={'choice':'A'}))
                cases.append({'name':name,'username':username,'owner':actor.public_id,'attempt_id':attempt.id,
                    'resource_id':resource.id,'question_version_id':qv.id,'response':reply,'baseline':baseline})
                db.commit()
        save(fixture,{'course_id':course,'point_id':point,'synthetic':True,'cases':cases,
            'criteria':['同错不同因','连续原句依据','定向反馈及新题','后续画像/教学读取','原分数不因追问改变','刷新恢复']})

    class TracedLLM(AsyncOpenAIChatLLM):
        async def generate(self, system, user, **kwargs):
            start=time.monotonic()
            record={'system':system,'input':json.loads(user),'role':kwargs.get('role'),
                    'model':self.model,'reasoning_effort':self.reasoning_effort,'max_tokens':self.max_tokens}
            path=root/'calls'/f'{time.time_ns()}-{kwargs.get("role")}.json'
            try:
                raw=await super().generate(system,user,**kwargs)
                record.update(status='completed',output=raw)
                return raw
            except Exception as exc:
                record.update(status='failed',error_type=type(exc).__name__)
                raise
            finally:
                record['seconds']=round(time.monotonic()-start,3); save(path,record)
    backend=TracedLLM(CONFIG.llm_endpoint,CONFIG.llm_api_key,model='deepseek-v4-flash',temperature=0,
        max_tokens=16384,timeout_seconds=CONFIG.llm_timeout,thinking_mode='enabled',reasoning_effort='medium')
    async def run(case):
        with SessionLocal() as db:
            actor=db.query(DBUser).filter_by(public_id=case['owner']).one(); db.expunge(actor)
        before_path=root/f'{case["name"]}-before.json'
        if not before_path.exists():
            with SessionLocal() as db:
                before=with_current_learning_evidence(db,case['baseline'],actor=actor,course_id=course,knowledge_point_id=point)
                save(before_path,before)
        start=time.monotonic()
        await prepare_inquiry(actor,case['attempt_id'],backend)
        result=await answer_inquiry(actor,case['attempt_id'],case['response'],backend)
        save(root/f'{case["name"]}-public.json',result)
        with SessionLocal() as db:
            stored=db.query(DBMisconceptionReview).filter_by(attempt_id=case['attempt_id']).one().evidence['inquiry']
            save(root/f'{case["name"]}-trace.json',stored)
            after=with_current_learning_evidence(db,case['baseline'],actor=actor,course_id=course,knowledge_point_id=point)
            save(root/f'{case["name"]}-after.json',after)
            adaptation=build_profile_adaptation(after,knowledge_point={'id':point,'title':'训练误差与泛化误差'})
            save(root/f'{case["name"]}-next-teaching-input.json',adaptation)
            assert case['response'] in json.dumps(stored,ensure_ascii=False)
            assert stored['interpretation']['learner_quote'] in json.dumps(after,ensure_ascii=False)
            assert stored['interpretation']['next_focus'] in json.dumps(adaptation,ensure_ascii=False)
            assert db.get(DBAssessmentAttempt,case['attempt_id']).score == 0
            event=db.get(DBLearningEvent,result['event_id'])
            assert not event.mastery_eligible
        print(case['name'],'completed',round(time.monotonic()-start,3),flush=True)
    async def all_cases():
        results=await asyncio.gather(*(run(case) for case in cases),return_exceptions=True)
        for result in results:
            if isinstance(result,Exception): raise result
    asyncio.run(all_cases())


if __name__=='__main__': main()
