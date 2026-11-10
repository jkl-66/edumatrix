"""Official GEPA optimizes the real inquiry feedback module on separate cases."""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding='utf8')


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf8')


RUBRIC = {
    'correctness':'0=知识/数字/答案错误；1=结论正确但必要条件或推理缺一环；2=概念、条件、数字与新题答案均正确。',
    'targeting':'0=误解原因错误；1=提到实际原因但泛泛重教或重复已会部分；2=明确改变回答中有依据的那一步，并保留已会部分。',
    'next_action':'0=无可独立完成的新题；1=完整但题干泄露答案或不足以检查该误解；2=完整新数据/新情境，唯一正确选项，独立检查该误解。',
    'clarity':'0=不自然/内部策略/大量防御说明；1=可读但重复或无用解释明显；2=自然简洁且必要知识完整。',
}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--runtime-pid',type=int,required=True)
    parser.add_argument('--output',required=True); args=parser.parse_args()
    import psutil
    os.environ.update({k:v for k,v in psutil.Process(args.runtime_pid).environ().items() if k.startswith('EDUMATRIX_')})
    assert Path(os.environ['EDUMATRIX_DB_PATH']).name=='acceptance.sqlite3'
    import gepa
    from gepa.core.adapter import GEPAAdapter, EvaluationBatch
    from app.learning_feedback import generate_targeted_feedback, BASE_STRATEGY, POLICY_PATH, MODEL_EVALUATION_RULES
    from app.claim_evidence import check_claim_calculations
    from config import CONFIG
    from llm_client import AsyncOpenAIChatLLM, OpenAIChatLLM, parse_json_object
    root=Path(args.output); root.mkdir(parents=True,exist_ok=True)
    if (root/'acceptance.json').exists():
        print('Reuse completed GEPA evidence:', root/'acceptance.json', flush=True)
        return
    fixture=root/'frozen-cases.json'
    if not fixture.exists():
        inquiry=root.parent.parent/'inquiry'/'run-r193'
        trace=json.loads((inquiry/'train-trace.json').read_text(encoding='utf8'))
        sources=trace['context']['sources']
        def case(id,split,question,response,finding,focus):
            return {'id':id,'split':split,'context':{'question':{'prompt':question},'learner_answer':{'choice':'A'},
                'inquiry':'你用了什么数据、怎样比较或处理？','learner_response':response,
                'learning_evidence':{'learner_quote':response,'finding':finding,'next_focus':focus},'sources':sources}}
        cases=[
            case('dev-training','dev','X训练MSE .04验证.24；Y训练.10验证.16。选择新数据上预期更好的模型。',
                 'X训练误差最低，所以新样本也最好。','把训练拟合当泛化','用验证MSE选模型；保留误差越小越好'),
            case('dev-mse','dev','X验证MSE .25，Y为.15，同一划分。选模型。','我看验证集，.25得分最高。',
                 '把MSE当越高越好','解释平方误差及越小越好；保留验证集选择'),
            case('dev-test','dev','测试误差被反复用来选择五个超参数，能作为最终独立测试吗？','没用测试集拟合权重，所以还独立。',
                 '认为只有梯度拟合才会用到测试信息','区分参数拟合与超参数选择；新独立测试集'),
            case('dev-scaler','dev','全数据标准化后随机划分训练/验证/测试。流程合适吗？','没读标签，先算全体均值不算泄漏。',
                 '认为无标签预处理不会泄漏','先划分，仅训练部分拟合均值/标准差，验证/测试复用'),
            case('val-training','validation','甲训练MSE .02验证.31；乙训练.11验证.17。为同分布新数据选择。',
                 '甲在训练集上的拟合更精确，我选甲。','把已见数据拟合当未见数据表现','验证误差比较；保持会读训练误差'),
            case('val-mae','validation','甲验证MAE 4，乙为2，同一划分，选模型。','甲的4大于2，我把它当准确率选高的。',
                 '误差指标与准确率方向混淆','MAE绝对误差越小越好；保留用验证集'),
            case('heldout-direction','heldout','甲验证MSE .36，乙为.25，同一划分。选模型。','我已经看验证集了，.36越大越准确。',
                 '把平方误差当准确程度','平方偏差的平均越小越好，保持用验证集'),
            case('heldout-fold','heldout','5折验证前先在全训练数据拟合标准化。合适吗？','这些都不是最终测试数据，折内验证可以提前参与。',
                 '忽略每折验证样本参与预处理','每折仅训练折拟合变换，验证折仅应用；最后按固定方案重拟合'),
        ]
        save(fixture,{'seed':42,'base_strategy':BASE_STRATEGY,'rubric':RUBRIC,'cases':cases,
            'separation':'New synthetic mechanism-development cases; formal 60 and old 54+9 are neither training nor validation.'})
    frozen=json.loads(fixture.read_text(encoding='utf8')); cases=frozen['cases']
    save(root/'runtime.json',{'gepa_version':importlib.metadata.version('gepa'),
        'official_package':'https://github.com/gepa-ai/gepa','model':'deepseek-v4-flash',
        'reasoning_effort':'medium','max_tokens':16384,'concurrency':2,'rubric':RUBRIC})

    class TracedLLM(AsyncOpenAIChatLLM):
        async def generate(self,system,user,**kwargs):
            start=time.monotonic(); path=root/'calls'/f'{time.time_ns()}-{kwargs.get("role")}.json'
            record={'system':system,'input':json.loads(user),'role':kwargs.get('role')}
            try:
                raw=await super().generate(system,user,**kwargs); record.update(status='completed',output=raw); return raw
            except Exception as exc:
                record.update(status='failed',error_type=type(exc).__name__); raise
            finally:
                record['seconds']=round(time.monotonic()-start,3); save(path,record)
    backend=TracedLLM(CONFIG.llm_endpoint,CONFIG.llm_api_key,model='deepseek-v4-flash',temperature=0,
        max_tokens=16384,timeout_seconds=CONFIG.llm_timeout,thinking_mode='enabled',reasoning_effort='medium')
    sync_backend=OpenAIChatLLM(CONFIG.llm_endpoint,CONFIG.llm_api_key,model='deepseek-v4-flash',temperature=0,
        max_tokens=16384,timeout_seconds=CONFIG.llm_timeout,thinking_mode='enabled',reasoning_effort='medium')
    reflection_count=0
    def reflect(messages):
        nonlocal reflection_count
        reflection_count+=1
        if isinstance(messages,str): messages=[{'role':'user','content':messages}]
        start=time.monotonic(); raw,usage=sync_backend.infer_messages(messages)
        save(root/'reflections'/f'{reflection_count}.json',{'messages':messages,'output':raw,'usage':usage,
            'seconds':round(time.monotonic()-start,3)})
        return raw

    async def evaluate_one(case,candidate):
        key=hashlib.sha256(json.dumps({'case':case,'candidate':candidate,'rubric':RUBRIC,
            'shared_rules':MODEL_EVALUATION_RULES},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        cache=root/'evaluations'/f'{key}.json'
        if cache.exists(): return json.loads(cache.read_text(encoding='utf8'))
        output_path=root/'outputs'/f'{key}.json'
        if output_path.exists(): output=json.loads(output_path.read_text(encoding='utf8'))
        else:
            output=await generate_targeted_feedback(backend,case['context'],strategy=candidate['instruction'])
            save(output_path,output)
        request={'context':case['context'],'output':output,'rubric':RUBRIC}
        raw=await backend.generate('你是教学输出评价者。按给定四项标准逐项评分，每项0/1/2并给具体位置与依据。'
            '只评输出，不把个人措辞偏好当缺陷。重点核对实际回答支持的错因、新题条件、答案、计算。'
            '只返回JSON：scores（四项分数）、evidence（四项依据）、calculations（实际结果算式的expression/claimed_result数组；给定数值无需重算）。'
            + MODEL_EVALUATION_RULES,
            json.dumps(request,ensure_ascii=False),role='gepa_feedback_evaluator')
        assessment=parse_json_object(raw)
        scores=assessment['scores']; assert set(scores)==set(RUBRIC)
        assert all(type(value) in (int,float) and value in (0,1,2) for value in scores.values())
        supplied=assessment.get('calculations') or []
        checks=check_claim_calculations({'claim':json.dumps(output,ensure_ascii=False),'calculations':supplied},[],
            question=json.dumps(case['context'],ensure_ascii=False),draft=json.dumps(output,ensure_ascii=False))
        if any(row.get('checked') and not row.get('agrees') for row in checks): scores['correctness']=0
        result={'case_id':case['id'],'split':case['split'],'candidate':candidate,'output':output,
            'assessment':assessment,'calculation_checks':checks,'score':sum(scores.values())/8,
            'input':case['context'],'evaluator_kind':'model rubric; later Codex adjudication'}
        save(cache,result); print('evaluate',case['id'],result['score'],flush=True); return result

    class Adapter(GEPAAdapter):
        def evaluate(self,batch,candidate,capture_traces=False):
            async def run():
                semaphore=asyncio.Semaphore(2)
                async def one(case):
                    async with semaphore: return await evaluate_one(case,candidate)
                values=await asyncio.gather(*(one(case) for case in batch),return_exceptions=True)
                for value in values:
                    if isinstance(value,Exception): raise value
                return values
            values=asyncio.run(run())
            return EvaluationBatch(outputs=[v['output'] for v in values],scores=[v['score'] for v in values],
                trajectories=values if capture_traces else None,
                objective_scores=[v['assessment']['scores'] for v in values])
        def make_reflective_dataset(self,candidate,eval_batch,components_to_update):
            data={'instruction':[{'Inputs':trace['input'],'Generated Outputs':trace['output'],
                'Feedback':{'rubric':RUBRIC,'scores':trace['assessment']['scores'],
                            'evidence':trace['assessment']['evidence'],'calculation_checks':trace['calculation_checks']}}
                for trace in eval_batch.trajectories]}
            save(root/'reflective-datasets'/f'{time.time_ns()}.json',data); return data
    adapter=Adapter()
    result_path=root/'gepa-result.json'
    if result_path.exists():
        from gepa.core.result import GEPAResult
        result=GEPAResult.from_dict(json.loads(result_path.read_text(encoding='utf8')))
    else:
        result=gepa.optimize(seed_candidate={'instruction':frozen['base_strategy']},
            trainset=[c for c in cases if c['split']=='dev'],valset=[c for c in cases if c['split']=='validation'],
            adapter=adapter,reflection_lm=reflect,reflection_minibatch_size=2,skip_perfect_score=False,
            max_metric_calls=40,stop_callbacks=lambda state: reflection_count>=3,seed=42,
            acceptance_criterion='improvement_or_equal',cache_evaluation=True,run_dir=str(root/'official-run'))
        save(result_path,result.to_dict())
    chosen=result.best_candidate
    heldout=[c for c in cases if c['split']=='heldout']
    baseline_eval=adapter.evaluate(heldout,{'instruction':frozen['base_strategy']},True)
    chosen_eval=adapter.evaluate(heldout,chosen,True)
    report={'gepa_best_index':result.best_idx,'selected_instruction':chosen['instruction'],
        'validation_scores':result.val_aggregate_scores,'parents':result.parents,
        'baseline_heldout':baseline_eval.scores,'selected_heldout':chosen_eval.scores,
        'selection_rule':'Highest validation mean; ties keep earlier candidate. Held-out cases report only, not used for selection.',
        'baseline_retained':chosen['instruction']==frozen['base_strategy'],
        'formal_evaluation_unchanged':True,'mechanism':'official GEPA reflection, minibatch evaluation, acceptance and Pareto candidate selection'}
    save(root/'selection.json',report)
    # Apply the actual chosen policy to the original shared module. A live call
    # without a strategy override verifies the normal policy-loading path.
    save(POLICY_PATH,{'instruction':chosen['instruction'],'version':'gepa-r194',
        'evidence':str(root/'selection.json'),'selected_by':'official GEPA validation'})
    applied_path=root/'applied-original-module.json'
    if not applied_path.exists():
        applied=asyncio.run(generate_targeted_feedback(backend,heldout[0]['context']))
        save(applied_path,{'context':heldout[0]['context'],'output':applied,'policy_version':'gepa-r194',
                           'explicit_strategy_override':False})
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__': main()
