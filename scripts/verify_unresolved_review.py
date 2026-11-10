"""Replay omitted live findings; exercise interrupted adjudication on a short new task."""
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.database import SessionLocal, DBGenerationTask, DBTaskEvent, DBArtifactVersion, DBArtifact
from app.resource_bundles import _real_model_backend
from app.resource_review_context import unresolved_review_findings, merge_unresolved_review
from app.resource_review_adjudication import adjudicate_review

OUT = ROOT/'scratch/automatic-generation-r207/focused-defects-r208m/unresolved-review-r208s'


def save(name, value):
    (OUT/f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2),encoding='utf8')


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        assert Path(db.bind.url.database).resolve() == OUT.parents[1]/'acceptance.sqlite3'
        rows = db.query(DBTaskEvent).filter(DBTaskEvent.task_id=='task-7246f1d6f3004a9fa2fee21d8b696c08',
            DBTaskEvent.sequence<=324, DBTaskEvent.event_type.in_([
                'resource_generation.review_result','resource_generation.review_adjudicated'])).order_by(DBTaskEvent.sequence).all()
        original = next(row for row in rows if row.sequence==251)
        latest = next(row for row in rows if row.sequence==324)
        candidates=[]
        for vid in latest.payload['version_ids']:
            v=db.get(DBArtifactVersion, vid);a=db.get(DBArtifact,v.artifact_id)
            candidates.append({'version_id':vid,'type':a.artifact_type,'content':v.content})
        history=[(row.event_type,row.payload) for row in rows]
    pending = unresolved_review_findings(history,candidates)
    handout = next(f for f in pending if f['issue_id']=='9b79481fdd210b982d81')
    lab = next(f for f in pending if f['issue_id']=='61dc82e420da31599024')
    assert not any(f['issue_id']==handout['issue_id'] for f in latest.payload['review']['findings'])
    save('original-replay',{'passed':True,'previous_sequence':251,'later_sequence':324,
        'omitted_unresolved':[handout,lab], 'restored_issue_ids':[f['issue_id'] for f in pending],
        'scope':'同版本未裁决问题被漏掉的真实反例；恢复到裁决输入，不人工改教学内容。'})
    candidates=[{'type':'handout','version_id':'new-linear-r208s',
        'content':'候选为线性函数，在x=0和1的预测分别是0和1；同一模型的训练数据x=[0,1]、y=[0,0]，训练MSE为0。'},
        {'type':'interactive_model','version_id':'new-lab-r208s',
         'content':'本任务要求分别比较样本量和正则强度的影响。完成条件：只需选样本量或正则强度中的一个做对照。'}]
    findings=[{'issue_id':'new-linear','resourceType':'handout','version_id':'new-linear-r208s',
               'issue':'同一线性模型的训练MSE与已知预测矛盾。','location':'content'},
              {'issue_id':'new-lab','resourceType':'interactive_model','version_id':'new-lab-r208s',
               'issue':'完成条件漏掉必须完成的另一组对照。','location':'content'}]
    # A fresh retry misses the issue. The real adjudicator must still receive
    # it through the common resume function, exactly as for the saved failure.
    history=[('resource_generation.review_result',{'findings':findings})]
    review=merge_unresolved_review({'approved':True,'findings':[]},unresolved_review_findings(history,candidates))
    manifest={'active_requirements':{'learning_goal':'按同一模型核对MSE，并分别完成两个因素的对照。'}}
    save('new-input',{'review':review,'candidates':candidates,'manifest':manifest})
    if (OUT/'new-result.json').exists():
        print('Reused successful short task.');return
    start=time.monotonic()
    try:
        result=await adjudicate_review(_real_model_backend(),manifest=manifest,candidates=candidates,review=review,
            save=lambda key,value:save('call-'+key.replace(':','-'),value))
        assert not result['approved'] and len(result['findings'])==2
        assert all(d['verdict']=='confirmed' for d in result['adjudication'])
        save('new-result',{'passed':True,'seconds':round(time.monotonic()-start,2),'result':result,
            'evidence_type':'合成短输入和真实模型裁决；原任务知识错误仍待实际修订。'})
        print('Original omission replay and short live resume task passed.')
    except Exception as exc:
        save('failure-'+str(int(time.time())),{'error':str(exc),'seconds':round(time.monotonic()-start,2)})
        raise


if __name__=='__main__':asyncio.run(main())
