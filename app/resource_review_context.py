"""Current teaching requirements and exact learner-facing review inputs.

History stays in task events and artifact metadata. It is not a second set of
instructions for the next generation, review or assessment.
"""
from copy import deepcopy
import hashlib
import json


def requirements_snapshot(value):
    if value is None:
        return None
    if not isinstance(value, dict) or not str(value.get('learning_goal') or '').strip():
        raise ValueError('当前教学要求需要明确的学习目标。')
    shared = value.get('shared', [])
    by_resource = value.get('by_resource', {})
    if (not isinstance(shared, list) or any(not isinstance(item, str) for item in shared)
            or not isinstance(by_resource, dict)
            or any(not isinstance(items, list) or any(not isinstance(item, str) for item in items)
                   for items in by_resource.values())):
        raise ValueError('当前教学要求应按共同要求和资源要求整理。')
    result = {'learning_goal': value['learning_goal'].strip(),
              'shared': list(dict.fromkeys(item.strip() for item in shared if item.strip())),
              'by_resource': {kind: list(dict.fromkeys(item.strip() for item in items if item.strip()))
                              for kind, items in by_resource.items()}}
    if isinstance(value.get('source_request'), str) and value['source_request'].strip():
        result['source_request'] = value['source_request'].strip()
    return result


def requirements_for(manifest, kinds=None):
    current = manifest.get('active_requirements')
    if not current:
        return None
    return {**current, 'by_resource': {kind: items for kind, items in current.get('by_resource', {}).items()
                                     if kinds is None or kind in kinds}}


def teaching_context(context, requirements, *, review=False):
    context = deepcopy(context)
    if requirements:
        context['learning_goal'] = requirements['learning_goal']
        if isinstance(context.get('teaching_scope'), dict):
            context['teaching_scope']['goal'] = requirements['learning_goal']
        # Long-term goals and evidence are retained for planning. The reviewer
        # checks the current lesson, whose applicable constraints were resolved
        # in active_requirements; unrelated future units are not repeated.
        if review and isinstance(context.get('path_learning_context'), dict):
            context['path_learning_context'] = {
                key: value for key, value in context['path_learning_context'].items()
                if key not in {'path_goal', 'path_conditions'}
            }
    return context


def teaching_candidate(candidate):
    result = deepcopy(candidate)
    try:
        body = json.loads(result.get('content') or '')
    except (ValueError, TypeError):
        body = None
    if isinstance(body, dict) and ('semanticContext' in body or 'semantic_context' in body
                                  or (result.get('type') == 'quiz' and isinstance(body.get('adaptation'), dict))):
        # Provenance repeats the frozen old goal and profile, often at greater
        # length than the lesson. It is not rendered teaching content.
        body.pop('semanticContext', None)
        body.pop('semantic_context', None)
        if result.get('type') == 'quiz' and isinstance(body.get('adaptation'), dict):
            # These are frozen generation provenance, not the live quiz's
            # progress display. The review already receives current learning
            # evidence separately; later progress must not invalidate old items.
            # Keep the visible learning goal and the actual questions/hints.
            for key in ('profileSummary', 'masterySummary', 'recentLearningSummary'):
                body['adaptation'].pop(key, None)
        result['content'] = json.dumps(body, ensure_ascii=False)
    if 'dependency_bindings' in result:
        result['dependency_bindings'] = [binding for binding in result.get('dependency_bindings') or []
                                         if binding.get('purpose') != 'generation_reference']
    return result


def actual_review_dependencies(candidates, dependencies):
    """Only actual fixed learner links can bring an older version into review."""
    current = {item.get('version_id') for item in candidates}
    available = {item.get('version_id'): teaching_candidate(item) for item in dependencies
                 if item.get('version_id')}
    pending = [binding.get('version_id') for item in candidates
               for binding in item.get('dependency_bindings') or []
               if binding.get('purpose') != 'generation_reference']
    selected = {}
    while pending:
        version = pending.pop()
        if version in selected or version in current or version not in available:
            continue
        item = available[version]
        selected[version] = item
        pending.extend(binding.get('version_id') for binding in item.get('dependency_bindings') or [])
    return list(selected.values())


def local_dependencies(candidate, candidates, dependencies):
    available = {item.get('version_id'): item for item in [*dependencies, *candidates]
                 if item.get('version_id') != candidate.get('version_id')}
    needed = {binding.get('version_id') for binding in candidate.get('dependency_bindings') or []}
    # Local checks verify this resource's own complete lesson. Other resources
    # enter only through an actual navigation binding; the final connection
    # pass checks implicit quotations against all current programs and labs.
    pending = list(needed)
    while pending:
        for binding in available.get(pending.pop(), {}).get('dependency_bindings') or []:
            version = binding.get('version_id')
            if version and version not in needed:
                needed.add(version)
                pending.append(version)
    return [item for key, item in available.items() if key in needed]


def bind_finding_version(finding, candidates):
    """Fill an omitted version only when the resource type has one candidate."""
    finding = dict(finding)
    if not finding.get('version_id'):
        matching = [item for item in candidates if item.get('type') == finding.get('resourceType')]
        if len(matching) == 1 and matching[0].get('version_id'):
            finding['version_id'] = matching[0]['version_id']
    return finding


def review_findings(result, candidates):
    """Store actionable findings with stable version/location provenance."""
    findings = []
    for finding in result.get('findings') or []:
        if not isinstance(finding, dict):
            findings.append(finding)
            continue
        finding = bind_finding_version(finding, candidates)
        identity = {key: finding.get(key) for key in ('resourceType', 'version_id', 'location', 'issue')}
        if finding.get('evidence'):
            # Several quantities/rows can fail on the same slide. Their evidence
            # distinguishes the issues; one decision must never close them all.
            identity['evidence'] = finding['evidence']
        finding['issue_id'] = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
        if any(isinstance(old, dict) and old.get('issue_id') == finding['issue_id'] for old in findings):
            continue
        findings.append(finding)
    return {**result, 'findings': findings}


def unresolved_review_findings(history, candidates):
    """An interrupted adjudication cannot silently erase a finding on the same draft."""
    current = {(item.get('type'), item.get('version_id')) for item in candidates}
    pending = {}
    closed = set()
    for event_type, payload in history:
        review = payload.get('review', payload)
        reviewed = review.get('reviewed_versions') or []
        version_ids = set(payload.get('version_ids') or [item.get('version_id') for item in reviewed])
        # A null version belongs to the candidates reviewed by that event, not
        # whichever revision happens to be current when execution resumes.
        event_candidates = [item for item in candidates if item.get('version_id') in version_ids]
        for raw in review.get('findings') or []:
            if not isinstance(raw, dict):
                continue
            finding = bind_finding_version(raw, event_candidates)
            identity = finding.get('issue_id')
            if identity and identity not in closed and (finding.get('resourceType'), finding.get('version_id')) in current:
                pending[identity] = finding
        if event_type == 'resource_generation.review_adjudicated':
            for decision in review.get('adjudication') or []:
                if decision.get('verdict') in {'false_positive', 'optional'}:
                    identity = decision.get('issue_id')
                    closed.add(identity)
                    pending.pop(identity, None)
    return list(pending.values())


def merge_unresolved_review(review, pending):
    findings = {item['issue_id']: item for item in pending}
    findings.update({item['issue_id']: item for item in review.get('findings') or []})
    if not findings:
        return review
    return {**review, 'approved': False, 'findings': list(findings.values()),
            'rejectedTypes': list(dict.fromkeys(item['resourceType'] for item in findings.values()))}


def concise_review(result):
    return {**{key: result.get(key) for key in ('approved', 'summary', 'findings', 'rejectedTypes', 'reviewed_versions')},
            'conditionReview': [{key: value.get(key) for key in ('claimId', 'status')}
                                for value in result.get('conditionReview', [])]}
