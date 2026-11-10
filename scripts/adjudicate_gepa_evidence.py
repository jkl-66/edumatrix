"""Codex's explicit numeric/source adjudication, separate from GEPA model scores."""
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path
import numpy as np

root=Path('scratch/defense-reference-20261030/b7-evaluation/same-ai-five391/extensions/gepa/run-r194')
def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
rows={p.stem:json.loads(p.read_text(encoding='utf8')) for p in (root/'evaluations').glob('*.json')}
comparisons={'03a9bca2a582':['3.6','2.8','4.1'],'36e92377af54':['6.1','3.4'],
    '52d9a22556dd':['4.8','4.2','5.1','3.9'],'634b2efb03b2':['2.8','3.6'],
    '69381ed21494':['.42','.31','.35'],'7995d4b92f88':['.22','.14','.18'],
    '888587f682b7':['.18','.30'],'8e290eb7ca4f':['2.0','2.4','1.6','2.2'],
    'b868e62551d3':['.28','.12','.20']}
checks=[]
for prefix,values in comparisons.items():
    key=next(k for k in rows if k.startswith(prefix)); row=rows[key]
    expected=chr(65+min(range(len(values)),key=lambda i:D(values[i])))
    assert row['output']['next_task']['answer']==expected
    checks.append({'evaluation':key,'values':values,'operation':'Decimal argmin','answer':expected,'passed':True})
for expression,value,expected in [('2000*0.7',D(2000)*D('.7'),'1400'),
    ('0.31-0.02',D('.31')-D('.02'),'.29'),('0.17-0.11',D('.17')-D('.11'),'.06'),
    ('5*3',D(5)*D(3),'15'),('480+160+160',D(480)+D(160)+D(160),'800'),
    ('350+75+75',D(350)+D(75)+D(75),'500')]:
    assert value==D(expected); checks.append({'expression':expression,'calculated':str(value),'passed':True})

# An affine change of a nonconstant predictor with a free OLS intercept does
# not change the fitted prediction. Leakage need not lower every sample error.
train_x=np.array([0.,1.]); y=np.array([0.,2.]); valid_x=np.array([2.]); predictions=[]
for values in (train_x,np.concatenate([train_x,valid_x])):
    mu,sd=values.mean(),values.std()
    design=np.column_stack([np.ones(2),(train_x-mu)/sd])
    coef=np.linalg.lstsq(design,y,rcond=None)[0]
    predictions.append(float(np.column_stack([np.ones(1),(valid_x-mu)/sd]).dot(coef)[0]))
assert np.allclose(predictions,[4.,4.],atol=1e-12)
checks.append({'counterexample':'OLS with intercept; fit scaling on train or all points',
    'train_x':train_x.tolist(),'train_y':y.tolist(),'valid_x':valid_x.tolist(),'valid_y':[4.],
    'predictions':predictions,'mse':[float((v-4)**2) for v in predictions],
    'conclusion':'The evaluation boundary is violated, but optimistic movement is not guaranteed for every run.'})

final_path=root/'conditions-r195/heldout-fold.json'
raw_path=root/'conditions-r195/heldout-fold-raw.json'
data=json.loads(final_path.read_text(encoding='utf8'))
if not raw_path.exists():
    save(raw_path,data)
    old='验证分数会偏乐观'
    assert old in data['output']['feedback']
    data['output']['feedback']=data['output']['feedback'].replace(old,'验证评价失去独立性，分数可能偏乐观')
    data['local_adjudication']={'actor':'Codex','reason':'Scope of leakage bias; supported by OLS counterexample',
                               'model_original':raw_path.name,'model_reruns':0}
    save(final_path,data)

result=json.loads((root/'gepa-result.json').read_text(encoding='utf8'))
calls=[json.loads(p.read_text(encoding='utf8')) for p in (root/'calls').glob('*.json')]
reflections=[json.loads(p.read_text(encoding='utf8')) for p in (root/'reflections').glob('*.json')]
condition_calls=[json.loads(p.read_text(encoding='utf8')) for p in (root/'conditions-r195').glob('call-*.json')]
report={'status':'mechanism_verified','official_gepa_version':'0.1.4','proposals':len(reflections),
    'accepted_candidate_entries':len(result['candidates']),'distinct_strategies_including_baseline':len({c['instruction'] for c in result['candidates']}),
    'unique_evaluations':len(rows),'actual_generation_and_grading_calls':len(calls),
    'reflection_calls':len(reflections),'shared_rule_followup_calls':len(condition_calls),
    'model_call_seconds_sum':round(sum(c['seconds'] for c in calls+reflections+condition_calls),3),
    'output_exhausted':sum(c.get('error_type')=='ModelOutputLimitError' for c in calls+condition_calls),
    'raw_model_validation_scores':result['val_aggregate_scores'],'chosen_policy':'baseline retained',
    'measured_gain':None,'selection_adjudication':'Raw scores tied. No reliable superiority over the shorter baseline; candidates also added competing Markdown/length instructions. Retain baseline and apply shared factual conditions.',
    'model_evaluator_missed':[{'case':'val-training','issue':'Gap treated too strongly as proof of overfitting','resolution':'Shared conditions and targeted new live feedback'},
        {'case':'heldout-fold','issue':'Leakage said to guarantee optimistic validation score','resolution':'Shared conditions; one live follow-up still repeated it, then Codex corrected the saved sentence with numerical counterexample'}],
    'numeric_checks':checks,'raw_uncomputed_calculation_entries':sum(not c.get('checked') for r in rows.values() for c in r['calculation_checks']),
    'original_module_applied':True,'original_module_application':'applied-original-module.json',
    'formal_60_unchanged':True,'limitations':['Small synthetic cases and model rubric are not learner effectiveness or external independent evaluation.',
        'Shared factual instructions do not guarantee the model follows them; the remaining observed sentence was locally adjudicated without restarting the optimization.',
        'Model calculation strings included prose; only explicit Decimal/NumPy checks above are claimed as numerical verification.']}
save(root/'acceptance.json',report)
print(json.dumps({k:report[k] for k in ['proposals','distinct_strategies_including_baseline','unique_evaluations',
    'actual_generation_and_grading_calls','reflection_calls','shared_rule_followup_calls','output_exhausted']},ensure_ascii=False))
