"""Replay saved review failures and run two short, directly related live checks."""
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.resource_bundles import _real_model_backend
from app.resource_review_adjudication import adjudicate_review,linear_regression_solver_evidence
from app import numerical_verification as nv
from llm_client import parse_json_object

OUT=ROOT/'scratch/automatic-generation-r207/focused-defects-r208m/review-runtime-r208v'


def save(name,value):
    (OUT/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect((OUT.parents[1]/'acceptance.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        raw=json.loads(db.execute('select payload from task_events where task_id=? and sequence=440',
            ('task-7246f1d6f3004a9fa2fee21d8b696c08',)).fetchone()[0])['review']['raw']
        content=db.execute('select content from artifact_versions where id=?',
            ('av-bedd4d2a7b664bdf9f8c8d0845242e91',)).fetchone()[0]
    plan=nv._validate_plan(parse_json_object(raw),{'type':'handout','content':content})
    save('original-replay',{'passed':True,'plan':plan,'installed_solver':linear_regression_solver_evidence(),
        'scope':'原440抽取只修复唯一原句末尾问号/分号；文字、数值与精度未改。原442/450/459的库行为意见与实际源码相反。'})
    async def solver():
        if (OUT/'solver-result.json').exists():return
        evidence=linear_regression_solver_evidence()
        c={'type':'code_sandbox','version_id':'new-solver-current-v',
           'content':f"当前scikit-learn {evidence['version']}的LinearRegression对稠密输入且positive=False时，把tol作为lstsq的cond参数，因此会影响该求解的有效秩。"}
        review={'approved':False,'findings':[{'resourceType':'code_sandbox','version_id':c['version_id'],
            'issue_id':'dense-tol','issue':'tol在这个稠密路径中没有作用，以上说明错误。'}]}
        result=await adjudicate_review(_real_model_backend(),manifest={},candidates=[c],review=review,
            save=lambda key,value:save('solver-'+key.replace(':','-'),value))
        assert result['approved'] and result['adjudication'][0]['verdict']=='false_positive'
        save('solver-result',{'passed':True,'result':result,'evidence_kind':'合成短句，真实模型以当前安装源码裁决。'})
    async def punctuation():
        if (OUT/'punctuation-result.json').exists():return
        c={'type':'handout','content':'练习中10次试验有2次成功，相对频率=0.2；请说明分母。'}
        plan={'cases':[{'id':'frequency','inputs':{'total':10,'success':2},'method':'成功次数除以总次数。',
            'input_evidence':[{'path':'content','quote':'10次试验有2次成功'}],
            'targets':[{'id':'p','quantity':'相对频率','claims':[{'path':'content',
                'quote':'练习中10次试验有2次成功，相对频率=0.2？','values':['0.2']}]}]}],'not_computed':[]}
        backend=_real_model_backend()
        key='numerical-plan:'+nv._hash({'content':c['content'],'type':c['type'],
            'system':nv.EXTRACT_SYSTEM,'model':backend.model})
        cache={key+':failure':{'raw':json.dumps(plan,ensure_ascii=False),'error':'合成注入与原失败相同的句末标点错配'}}
        save('punctuation-input',{'candidate':c,'injected_extraction':plan})
        result=await nv.verify_numerical_content(backend,c,completed=cache,
            save=lambda key,value:save('punctuation-'+key.replace(':','-'),value))
        assert result['status']=='computed' and all(x['matches'] for x in result['comparisons'])
        save('punctuation-result',{'passed':True,'result':result,
            'evidence_kind':'合成抽取标点错误经公共恢复，真实模型编写程序并实际计算；不是重新真实抽取。'})
    started=time.monotonic()
    await asyncio.gather(solver(),punctuation())
    print('Original failures replayed; two short live checks passed in',round(time.monotonic()-started,2),'seconds.')


if __name__=='__main__':asyncio.run(main())
