"""Freeze actual preceding lessons and learner work for a path resource request."""
from copy import deepcopy
import json
from types import SimpleNamespace

from app.database import (
    DBArtifact, DBArtifactVersion, DBAssessmentQuestionVersion, DBGenerationTask, DBLearningEvent,
    DBLearningPath, DBPathNode, DBPlanVersion, DBTaskEvent,
)


PATH_CONTINUITY_GUIDANCE = (
    "course.path_learning_context是本次请求冻结的前段学习资料与实际作答，不是教材来源。"
    "承接其中真实表格、数据、代码、符号和已提交结果；若改用新例，明确说明变化及原因。"
    "prior_steps中的安排和已准备资源不等于学过或掌握；只有learning_results记录实际动作，"
    "按其反馈与提示使用情况决定复习和撤去支架，不能把运行通过等同原理已掌握。"
    "各资源version_id固定，已学习旧版不能被新版默默替换。未提供的前段内容不能凭目标补造。"
    "承接程序时提供本节可独立运行的完整输入与代码；沙盒不保留上次内存、模型或文件。"
    "已有先修材料尚未学习时按预习安排，不声称已经完成；确需重新建立输入时给出明确准备步骤。"
    "审核同样核对这些跨段对应关系、实际反馈和当前目标；旧资源也可能有错，遇到矛盾应按课程来源纠正并解释，不能延续错误。"
)


def _resource_version_id(event):
    payload, context = event.payload or {}, event.context_ref or {}
    return (payload.get('resource_version_id') or payload.get('source_resource_version_id')
            or context.get('resource_version_id'))


def learned_resource_node(db, event):
    """Resolve an actual resource version to the task that requested it."""
    from app.resource_bundles import GENERATION_CAPABILITY

    version_id = _resource_version_id(event)
    version = db.get(DBArtifactVersion, version_id) if version_id else None
    artifact = db.get(DBArtifact, version.artifact_id) if version else None
    if (not artifact or artifact.id != event.object_id
            or artifact.owner_public_id != event.owner_public_id or artifact.course_id != event.course_id):
        return None
    origin = version.created_task_id or (version.metadata_json or {}).get('generation_job_id')
    task = db.get(DBGenerationTask, origin) if origin else None
    if (not task or task.owner_public_id != event.owner_public_id or task.course_id != event.course_id
            or task.capability != GENERATION_CAPABILITY):
        return None
    request = db.query(DBTaskEvent).filter_by(task_id=task.id, event_type='resource_generation.requested').order_by(
        DBTaskEvent.sequence).first()
    gate = (((request.payload or {}).get('manifest') or {}).get('exam_gate') or {}) if request else {}
    path = db.get(DBLearningPath, gate.get('path_id')) if gate.get('path_id') else None
    node = db.get(DBPathNode, gate.get('selected_task_id')) if gate.get('selected_task_id') else None
    if (not path or not node or node.learning_path_id != path.id
            or path.owner_public_id != event.owner_public_id or path.course_id != event.course_id
            or path.source_plan_version_id != gate.get('path_version_id')):
        return None
    return node


def quiz_resource_context(db, *, owner_public_id, course_id, question_version_id, resource_version_id):
    """Validate the exact page version supplied with a quiz answer."""
    version = db.get(DBArtifactVersion, resource_version_id)
    artifact = db.get(DBArtifact, version.artifact_id) if version else None
    if (not artifact or artifact.owner_public_id != owner_public_id or artifact.course_id != course_id):
        return None
    try:
        content = json.loads(version.content)
        questions = content.get('questions') or []
    except (ValueError, AttributeError, TypeError):
        return None
    if not any(isinstance(item, dict) and item.get('questionVersionId') == question_version_id for item in questions):
        return None
    question = db.get(DBAssessmentQuestionVersion, question_version_id)
    if not question:
        return None
    result = {'resourceId': artifact.id}
    if question.primary_knowledge_point_id:
        result['knowledgePointId'] = question.primary_knowledge_point_id
    node = learned_resource_node(db, SimpleNamespace(owner_public_id=owner_public_id, course_id=course_id,
        object_id=artifact.id, payload={'resource_version_id': version.id}, context_ref={}))
    if node:
        result.update(pathId=node.learning_path_id, taskId=node.id)
    return result


def completed_quiz_versions(db, events):
    """Resolve the quiz's existing required count from its immutable version."""
    from app.m5_resources import QuizResourceContent

    completed = set()
    for version_id in {_resource_version_id(event) for event in events}:
        version = db.get(DBArtifactVersion, version_id) if version_id else None
        if not version:
            continue
        try:
            content = QuizResourceContent.model_validate_json(version.content)
        except ValueError:
            continue
        required = {item.questionVersionId for item in content.questions if item.required}
        target = min(content.requiredQuestionCount, len(required))
        answered = {event.object_id for event in events if _resource_version_id(event) == version_id
                    and event.mastery_eligible and event.completion_effect == 'complete'
                    and (event.payload or {}).get('correct') is True}
        if target > 0 and len(required & answered) >= target:
            completed.add(version_id)
    return completed


def _learning_result(db, event):
    result = {
        'event_id': event.id, 'event_type': event.event_type,
        'occurred_at': event.occurred_at.isoformat() if event.occurred_at else None,
        'evidence_status': event.evidence_status, 'mastery_eligible': bool(event.mastery_eligible),
        'completion_effect': event.completion_effect,
        'resource_version_id': _resource_version_id(event),
        'payload': deepcopy(event.payload or {}),
    }
    if (event.payload or {}).get('run_id') and event.event_type in {'code_run', 'code_tests_passed'}:
        from app.code_sandbox import RUN_ARTIFACT_TYPE
        run = db.get(DBArtifact, event.payload['run_id'])
        version = db.get(DBArtifactVersion, run.current_version_id) if run else None
        if (run and version and run.owner_public_id == event.owner_public_id
                and run.course_id == event.course_id and run.artifact_type == RUN_ARTIFACT_TYPE
                and version.artifact_id == run.id):
            state = json.loads(version.content)
            if (state.get('sourceResourceId') == event.object_id
                    and state.get('sourceResourceVersionId') == result['resource_version_id']
                    and state.get('ownerPublicId') == event.owner_public_id):
                # Use submitted code and actual output, not the original starter.
                result['code_run'] = {key: state.get(key) for key in (
                    'code', 'files', 'standardInput', 'status', 'checks', 'passedCount', 'totalCount',
                )}
                result['code_run']['version_id'] = version.id
                for channel in ('stdout', 'stderr'):
                    complete = state.get(channel + 'Complete') or {}
                    result['code_run'][channel] = (complete.get('text', '') if complete.get('available')
                                                   else state.get(channel, ''))
                    result['code_run'][channel + '_capture'] = (complete.get('capture')
                        if complete.get('available') else state.get(channel + 'Capture'))
    return result


def preceding_learning_context(db, *, owner_public_id, course_id, path_id, task_id):
    """Resolve same-path prerequisites and earlier parts, without writing learning facts.

    Actual studied versions take precedence over later prepared versions. Compatible
    previous paths are followed only through the existing replan identity rules.
    """
    from app.learning_aggregation import _event_matches_node, _node_completion_supported, _node_predecessors
    from app.resource_bundles import GENERATION_CAPABILITY, _resource_review_content

    path = db.get(DBLearningPath, path_id)
    node = db.get(DBPathNode, task_id)
    if (not path or not node or path.owner_public_id != owner_public_id
            or path.course_id != course_id or node.learning_path_id != path.id):
        return None
    plan = db.get(DBPlanVersion, path.source_plan_version_id)
    planned = {item['node_key']: item for item in (plan.content or {}).get('nodes', [])} if plan else {}
    current = planned.get(node.node_key, {})
    ordered = db.query(DBPathNode).filter_by(learning_path_id=path.id).order_by(DBPathNode.sequence).all()
    goal = str(current.get('teaching_goal') or '')
    prerequisites = set(node.prerequisites or [])
    # A predecessor's final part may contain explanation while its first part
    # supplied the actual data/code. Keep those parts together when continuing.
    related_units = {planned.get(old.node_key, {}).get('teaching_unit_key') for old in ordered
                     if old.node_key in prerequisites or old.id in prerequisites}
    related_units.add(current.get('teaching_unit_key'))
    related_units.discard(None)
    related_units.discard('')
    related = [old for old in ordered if old.sequence < node.sequence and (
        old.node_key in prerequisites or old.id in prerequisites
        or planned.get(old.node_key, {}).get('teaching_unit_key') in related_units
        or (old.node_key and old.node_key in goal)
    )]
    result = {'path_id': path.id, 'path_version_id': path.source_plan_version_id,
              'task_id': node.id, 'path_goal': (plan.content or {}).get('goal', '') if plan else '',
              'path_conditions': deepcopy((plan.content or {}).get('assumptions') or []) if plan else [],
              'prior_steps': []}
    if not related:
        return result
    # A resource request already freezes path/version/task in its existing event.
    # Reuse that identity instead of inferring relationships from titles or topics.
    bindings = {}
    for old in related:
        for origin in (old, *_node_predecessors(db, old)):
            origin_path = db.get(DBLearningPath, origin.learning_path_id)
            bindings[(origin.learning_path_id, origin_path.source_plan_version_id, origin.id)] = old.id
    tasks = db.query(DBGenerationTask, DBTaskEvent).join(
        DBTaskEvent, DBTaskEvent.task_id == DBGenerationTask.id,
    ).filter(DBGenerationTask.owner_public_id == owner_public_id,
             DBGenerationTask.course_id == course_id, DBGenerationTask.capability == GENERATION_CAPABILITY,
             DBTaskEvent.event_type == 'resource_generation.requested').all()
    task_nodes = {}
    for task, event in tasks:
        gate = ((event.payload or {}).get('manifest') or {}).get('exam_gate') or {}
        bound = bindings.get((gate.get('path_id'), gate.get('path_version_id'), gate.get('selected_task_id')))
        if bound:
            task_nodes[task.id] = bound
    events = db.query(DBLearningEvent).filter_by(owner_public_id=owner_public_id, course_id=course_id).filter(
        DBLearningEvent.event_type.in_(['quiz_answered', 'code_run', 'code_tests_passed',
            'interactive_experiment_completed', 'interactive_model_observation_submitted',
            'feynman_submitted', 'formal_exam_submitted', 'review_completed', 'teacher_confirmed']),
    ).order_by(DBLearningEvent.occurred_at, DBLearningEvent.id).all()
    artifacts = db.query(DBArtifact).filter_by(owner_public_id=owner_public_id, course_id=course_id,
        status='published', archived_at=None).order_by(DBArtifact.updated_at.desc(), DBArtifact.id.desc()).all()
    resource_cache = {}

    def resource(version_id, old):
        if version_id in resource_cache:
            bound, item = resource_cache[version_id]
            return item if bound == old.id else None
        version = db.get(DBArtifactVersion, version_id) if version_id else None
        artifact = db.get(DBArtifact, version.artifact_id) if version else None
        if (not artifact or artifact.owner_public_id != owner_public_id or artifact.course_id != course_id
                or artifact.archived_at is not None or artifact.status in {'archived', 'withdrawn'}):
            resource_cache[version_id] = (None, None)
            return None
        metadata = version.metadata_json or {}
        origin = version.created_task_id or metadata.get('generation_job_id')
        bound = task_nodes.get(origin)
        if not bound:
            resource_cache[version_id] = (None, None)
            return None
        kind = metadata.get('resource_type') or artifact.artifact_type
        item = {'resource_id': artifact.id, 'version_id': version.id, 'type': kind,
                'title': artifact.title, 'content_hash': version.content_hash,
                'content_format': version.content_format,
                'content': _resource_review_content(db, version, kind),
                'source_ref_ids': list(metadata.get('source_ref_ids') or [])}
        resource_cache[version_id] = (bound, item)
        return item if bound == old.id else None

    for old in related:
        matched = [event for event in events if _event_matches_node(db, event, old)]
        resources, seen = [], set()
        for event in matched:
            item = resource(_resource_version_id(event), old)
            if item and item['version_id'] not in seen:
                resources.append({**item, 'use': 'learning_record'})
                seen.add(item['version_id'])
        studied_types = {item['type'] for item in resources}
        prepared_types = set()
        for artifact in artifacts:
            item = resource(artifact.current_version_id, old)
            if item and item['type'] not in studied_types | prepared_types:
                resources.append({**item, 'use': 'prepared_material'})
                prepared_types.add(item['type'])
        accepted = [event for event in matched if event.evidence_status == 'accepted' and event.mastery_eligible]
        result['prior_steps'].append({
            'task_id': old.id, 'node_key': old.node_key, 'title': old.title,
            'goal': planned.get(old.node_key, {}).get('teaching_goal', ''),
            'completion_supported': _node_completion_supported(db, old, accepted),
            'resources': resources, 'learning_results': [_learning_result(db, event) for event in matched],
        })
    return result
