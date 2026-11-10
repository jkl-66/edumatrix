"""Course stages keep entry diagnosis separate from whole-course mastery."""

from __future__ import annotations

from app.course_structure import prerequisite_ids


def course_diagnostic_scope(course, points, profile, *, question_count, stage_id=None):
    """Use course order and observed evidence, never occupation or self-rating."""
    by_id = {point.id: point for point in points}
    aliases = {value: point.id for point in points for value in (point.id, point.code)}
    manifest = course.manifest_data or {}
    order = {item.get('code'): index for index, item in enumerate(manifest.get('knowledge_points', []))}
    level_order = {'foundation': 0, 'basic': 0, 'core': 1, 'advanced': 2, 'stretch': 3}
    pending = sorted(points, key=lambda point: (
        order.get(point.code, len(order)), level_order.get(str(point.level).lower(), 1), point.title, point.id))
    ordered = []
    while pending:
        remaining = {point.id for point in pending}
        ready = next((point for point in pending if not any(
            aliases.get(str(before), str(before)) in remaining - {point.id}
            for before in prerequisite_ids(course, point))), pending[0])
        ordered.append(ready)
        pending.remove(ready)

    stages, assigned = [], set()
    for entry in manifest.get('diagnostic_stages', []):
        ids = [aliases[code] for code in entry.get('knowledge_point_codes', []) if code in aliases]
        if not ids:
            continue
        stages.append({'id': entry['id'], 'title': entry['title'], 'goal': entry.get('goal', ''),
                       'knowledgePointIds': list(dict.fromkeys(ids)),
                       'assessmentGuidance': entry.get('assessment_guidance', '')})
        assigned.update(ids)
    # Unconfigured courses and subsequently added topics remain accessible.
    remaining = [point.id for point in ordered if point.id not in assigned]
    # Stage identity must survive a learner changing the paper length. This is
    # pagination of the complete curriculum, not a cutoff of later topics.
    for offset in range(0, len(remaining), 15):
        ids = remaining[offset:offset + 15]
        stages.append({'id': f'course-stage-{offset // 15 + 1}',
                       'title': '课程学习起点' if not stages else f'后续学习 · {by_id[ids[0]].title}',
                       'goal': '确认先修理解、当前难点与独立完成能力。',
                       'knowledgePointIds': ids, 'assessmentGuidance': ''})
    if not stages:
        return {'selected': None, 'stages': [], 'courseKnowledgePoints': [], 'deferredKnowledgePoints': []}
    snapshot = profile.snapshot or {}
    same_course = (snapshot.get('course_id') or (snapshot.get('course_context') or {}).get('courseId')) == course.id
    mastery = (snapshot.get('mastery_by_knowledge_point') or {}) if same_course else {}

    def observed_mastered(key):
        item = mastery.get(key) or {}
        return (isinstance(item, dict) and isinstance(item.get('score'), (int, float))
                and item['score'] >= 0.7 and item.get('evidence_item_count', 0) >= 2)

    selected = next((stage for stage in stages if stage['id'] == stage_id), None) if stage_id else next(
        (stage for stage in stages if not all(observed_mastered(key) for key in stage['knowledgePointIds'])), stages[-1])
    if selected is None:
        # Imported lazily to avoid a dependency cycle with generation.
        from app.diagnostic_generation import DiagnosticGenerationError
        raise DiagnosticGenerationError('diagnostic_stage_unknown', '课程阶段已更新，请重新选择。', status_code=422)
    selected_ids = set(selected['knowledgePointIds'])
    inventory = [{'id': point.id, 'title': point.title, 'level': point.level} for point in ordered]
    return {'selected': selected, 'stages': stages, 'courseKnowledgePoints': inventory,
            'deferredKnowledgePoints': [point for point in inventory if point['id'] not in selected_ids]}
