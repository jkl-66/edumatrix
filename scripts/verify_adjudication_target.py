"""Reproduce a saved wrong-resource quote; verify isolated real adjudication."""
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.resource_review_adjudication import adjudicate_review, _validate_decisions
from app.resource_bundles import _real_model_backend
from llm_client import parse_json_object

OUT = ROOT/'scratch/automatic-generation-r207/focused-defects-r208m/adjudication-target-r208u'


def save(name, value):
    (OUT/f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect((OUT.parents[1]/'acceptance.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        task = 'task-7246f1d6f3004a9fa2fee21d8b696c08'
        review = json.loads(db.execute('select payload from task_events where task_id=? and sequence=393', (task,)).fetchone()[0])['review']
        failed = json.loads(db.execute('select payload from task_events where task_id=? and sequence=394', (task,)).fetchone()[0])['review']
        finding = next(f for f in review['findings'] if f['issue_id']=='cea098063717d737fc2d')
        decision = next(d for d in parse_json_object(failed['output'])['decisions'] if d['issue_id']==finding['issue_id'])
        content = db.execute('select content from artifact_versions where id=?',(finding['version_id'],)).fetchone()[0]
    try:
        _validate_decisions([decision], findings=[finding], sources={},
            candidates=[{'type':finding['resourceType'],'version_id':finding['version_id'],'content':content}], review=review)
        raise AssertionError('Wrong-version quote was accepted')
    except ValueError as error:
        save('original-failure-replay', {'passed': True, 'error': str(error), 'finding':finding, 'decision':decision})
    if (OUT/'new-result.json').exists():
        print('Reused successful target-isolation evidence.'); return
    candidates = [
        {'type':'handout','version_id':'new-handout-target-u',
         'content':'训练集拟合模型参数，验证集比较候选，测试集用于方案固定后的最终评估。'},
        {'type':'code_sandbox','version_id':'new-code-target-u',
         'content':'在测试集上尝试十种正则强度，选测试误差最低的一种，然后把该测试误差报告为最终独立评估。'}]
    findings = [{'resourceType':c['type'],'version_id':c['version_id'],'issue_id':c['type'],
                 'issue':'本资源是否用测试集选超参数？','location':'content'} for c in candidates]
    request={'candidates':candidates,'review':{'approved':False,'findings':findings}}
    save('new-input', request)
    began=time.monotonic()
    try:
        result=await adjudicate_review(_real_model_backend(),manifest={},**request,
            save=lambda key,value:save('call-'+key.replace(':','-'),value))
        verdicts={d['issue_id']:d['verdict'] for d in result['adjudication']}
        assert verdicts=={'handout':'false_positive','code_sandbox':'confirmed'},verdicts
        save('new-result', {'passed':True,'seconds':round(time.monotonic()-began,2),'result':result,
            'evidence_kind':'合成短输入、真实模型按版本裁决；未发布教学内容。'})
        print('Saved failure rejected; isolated true and false findings correctly adjudicated.')
    except Exception as exc:
        save('failure-'+str(int(time.time())),{'error':str(exc)});raise


if __name__=='__main__': asyncio.run(main())
