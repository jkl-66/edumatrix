"""Read-only course capability inventory; does not generate or publish resources."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def audit(database, course_id):
    os.environ['EDUMATRIX_DB_PATH'] = str(database.resolve())
    from app.interactive_lab import _evaluate, experiment_execution_info, validate_parameters
    from app.resource_bundles import _interactive_template_for_knowledge_point, _legal_video_catalog
    from app.teaching_runtime import teaching_runtime_context
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    course = connection.execute('select * from courses where id=?', (course_id,)).fetchone()
    manifest = json.loads(course['manifest_data'])
    codes = {code for chapter in manifest['teaching_structure']['chapters']
             for code in chapter['knowledge_point_codes']}
    points = []
    for point in manifest['knowledge_points']:
        if point['code'] not in codes:
            continue
        sources = connection.execute('''select distinct s.id, s.quote, d.processing_status
            from knowledge_points k join chapter_knowledge_points ck on ck.knowledge_point_id=k.id
            join source_refs s on s.chapter_id=ck.chapter_id
            join source_documents d on d.id=s.source_document_id
            where k.code=? and d.course_id=?''', (point['code'], course_id)).fetchall()
        template = _interactive_template_for_knowledge_point(point['title'])
        result = {'code': point['code'], 'title': point['title'],
                  'source_count': len(sources), 'nonempty_source_count': sum(bool(s['quote'].strip()) for s in sources),
                  'source_ids': [s['id'] for s in sources], 'template_id': None, 'runs': []}
        if template:
            result.update(template_id=template.template_id, template_title=template.title)
            try:
                result['execution'] = experiment_execution_info(template.template_id)
            except Exception as exc:
                result['execution_error'] = f'{type(exc).__name__}: {exc}'
            defaults = {p.key: int(p.default) if p.kind == 'integer' else p.default for p in template.parameters}
            for p in template.parameters:
                for position, value in [('minimum', p.minimum), ('default', p.default), ('maximum', p.maximum)]:
                    params = {**defaults, p.key: int(value) if p.kind == 'integer' else value}
                    if template.template_id == 'rag-hybrid-tuning' and p.key in {'keyword_weight', 'vector_weight'}:
                        params['vector_weight' if p.key == 'keyword_weight' else 'keyword_weight'] = round(1 - value, 6)
                    metrics, feedback = _evaluate(template, validate_parameters(template, params))
                    result['runs'].append({'control': p.key, 'position': position,
                        'parameters': params, 'metrics': metrics, 'feedback': feedback,
                        'finite': all(math.isfinite(float(v)) for v in metrics.values())})
        points.append(result)
    connection.close()
    return {'at': datetime.now(timezone.utc).isoformat(), 'course_id': course_id,
        'version': course['version'], 'kind': '准备能力与真实模板计算核对；非模型资源生成、非正式指标',
        'types': ['handout', 'mind_map', 'quiz', 'code_sandbox', 'interactive_model', 'training_task', 'video', 'deck', 'feynman'],
        'points': points, 'runtime': teaching_runtime_context(),
        'registered_video_count': len(_legal_video_catalog()),
        'limitations': ['来源与模板存在不等于生成内容通过审核。', '视频主题相关性、外部播放与各画像教学效果仍需实际任务验收。'],
        'summary': {'points': len(points), 'with_sources': sum(p['nonempty_source_count'] > 0 for p in points),
            'with_template': sum(bool(p['template_id']) for p in points),
            'template_count': len({p['template_id'] for p in points}),
            'execution_contract_errors': sum('execution_error' in p for p in points),
            'control_runs': sum(len(p['runs']) for p in points)}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, default=ROOT / 'scratch/automatic-generation-r207/acceptance.sqlite3')
    parser.add_argument('--course', default='course-ai-deep-learning-agents-v1')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output exists; retain the previous evidence and choose a new name.')
    report = audit(args.database, args.course)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary']))
