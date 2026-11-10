"""Apply adjudicated local copy edits to the two isolated comparison messages."""
import argparse, hashlib, json, os, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--runtime-pid',type=int,required=True)
    parser.add_argument('--output',required=True); args=parser.parse_args()
    import psutil
    os.environ.update({k:v for k,v in psutil.Process(args.runtime_pid).environ().items() if k.startswith('EDUMATRIX_')})
    assert Path(os.environ['EDUMATRIX_DB_PATH']).name=='acceptance.sqlite3'
    from app.database import SessionLocal, DBChatMessage
    root=Path(args.output); record=root/'copy-adjudication-r194.json'
    if record.exists():
        with SessionLocal() as db:
            for row in json.loads(record.read_text(encoding='utf8')):
                message=db.get(DBChatMessage,row['message_id'])
                assert message.content==row['after']
                message.content_sha256=row['after_sha256']
            db.commit()
        print('Already applied; preserved original messages.'); return
    edits={
        'hybrid':[
            ('200 行、6:2:2 的比例都是本次教学设定，不是真实观测；实际数据换成你自己的，步骤不变。','以下使用练习数据，按6:2:2划分。'),
            ('比例是教学设定，关键在顺序：先划分，后拟合。','先划分，后拟合。'),
            ('检查时先固定标准差口径：','训练集中不变化的特征先删除，并同步删除验证和测试集的对应列。其余特征固定标准差口径：'),
            ('测试误差会偏乐观。','测试误差可能偏乐观，失去独立评价的条件。'),
            ('报出的数同样偏乐观。','报出的误差可能偏乐观。'),
            ('在固定训练集上训练误差应更低，最坏也只是相等。','在固定训练集、相同损失、包含低阶项且各模型都达到最优拟合时，高阶模型的训练误差不大于低阶模型。'),
        ],
        'hipporag2':[
            ('以下数值是我为了演示流程设定的教学示例，不是课程资料给出的数值，也不是本题的真实观测；真实重做时应替换为你在电子表格中算出的数。','下面使用两组独立练习数据，分别演示标准化和模型比较。'),
            ('这里的 \\(0.14\\) 只是教学演示值，不是课程资料或本题真实数据。',''),
            ('这是流程设定，不是唯一正确答案；关键是要包含低阶基线和你关心的九次模型，并且查看测试集后不再改候选列表。','包含低阶基线和你关心的九次模型，候选列表在查看测试结果前固定。'),
            ('注意：这里的验证MSE只用于选阶数和确定方案。如果你在步骤5采用做法A合并训练+验证重拟合，那么最终模型参数变了，原来的验证MSE不再对应这个重拟合模型，不能当作最终测试成绩；它只说明选型过程。最终成绩仍是步骤6的独立测试MSE。','原验证MSE保留为选模记录；最终重拟合后，用独立测试集评价。'),
            ('这样利用更多数据是允许的；但原来的验证MSE不再对应这个最终重拟合模型，不能把它当作最终测试成绩。',''),
            ('只计算并记录一次。不能看到测试MSE后再回去改阶数或改预处理；一旦这样改，这次测试结果就作废。','记录该固定方案的测试MSE。如果根据结果继续调整模型，应另留独立数据评价调整后的方案。'),
            ('如果合并了训练集和验证集重新拟合，原来的验证MSE不能当作最终测试成绩；最终测试成绩只能是步骤6的独立测试MSE。如果没有干净测试集，只能报告交叉验证或验证集误差，并注明“这不是独立测试成绩”。','没有独立测试集时，报告交叉验证或验证集误差，并写明实际评价方法。'),
            ('最终测试误差会偏乐观','最终测试误差可能偏乐观'),
        ]}
    reports=[]
    with SessionLocal() as db:
        for mode,pairs in edits.items():
            identity=json.loads((root/f'answer-{mode}.json').read_text(encoding='utf8'))
            message=db.get(DBChatMessage,identity['assistant_message_id'])
            assert message.status=='completed'
            before=message.content; after=before; applied=[]
            for old,new in pairs:
                assert old in after,(mode,old)
                applied.append({'before':old,'after':new,'occurrences':after.count(old)})
                after=after.replace(old,new)
            message.content=after
            message.content_sha256=hashlib.sha256(after.encode()).hexdigest()
            checkpoint=dict(message.stream_checkpoint or {})
            checkpoint['localFinalEdits']={'actor':'Codex','version':'r194',
                'evidence':str(record),'reason':'删除重复免责声明，补充分条件，保留实际模型原文与局部编辑区别。'}
            message.stream_checkpoint=checkpoint
            (root/f'answer-{mode}-final-r194.md').write_text(after,encoding='utf8')
            reports.append({'mode':mode,'message_id':message.id,'before':before,'after':after,'edits':applied,
                'before_sha256':hashlib.sha256(before.encode()).hexdigest(),'after_sha256':hashlib.sha256(after.encode()).hexdigest(),
                'original_model_files_unchanged':True,'model_calls':0,'review':'Codex full-text/source/numeric adjudication'})
        db.commit()
    record.write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    print([(r['mode'],len(r['edits'])) for r in reports])


if __name__=='__main__':main()
