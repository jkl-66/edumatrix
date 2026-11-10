"""Repair invalid verifier fields without rewriting already checked claims."""
from copy import deepcopy
import hashlib
import json
import re


def _same_text(left, right):
    return ' '.join(str(left or '').split()) == ' '.join(str(right or '').split())


def _targets(review, feedback):
    targets = []
    for finding in feedback:
        location = re.fullmatch(r'conditionReview\[(\d+)\]', str(finding.get('location') or ''))
        if location:
            target = ('conditionReview', int(location.group(1)))
            if target[1] >= len(review.get(target[0], [])):
                raise ValueError('核验条件位置没有对应记录。')
        else:
            matches = [index for index, claim in enumerate(review.get('claims', []))
                       if _same_text(claim.get('claim'), finding.get('claim'))]
            if len(matches) != 1:
                raise ValueError('核验问题无法唯一定位到原主张。')
            target = ('claims', matches[0])
        if target not in targets:
            targets.append(target)
    return targets


async def repair_review_fields(raw, *, parse, validate, latest_feedback, generate, history):
    """Keep the same claims and conditions; only fix the indicated evidence.

    A successful patch is checked by the original whole-review validator.
    Other pending rows cannot invalidate it or be silently removed. Repeated
    identical failures switch from local correction to evidence-first and
    independent calculation, then report the unchanged defect.
    """
    review = parse(raw)
    if isinstance(review.get('claims'), dict):
        review['claims'] = [review['claims']]
    if not isinstance(review.get('claims'), list):
        raise ValueError('缺少可逐条接续的核验主张。')
    pending_feedback = list(latest_feedback())
    signatures = {}
    strategy = 0
    while pending_feedback:
        targets = _targets(review, pending_feedback)
        if not targets:
            raise ValueError('没有可定位的核验问题。')
        collection, index = targets[0]
        original = deepcopy(review[collection][index])
        relevant = [finding for finding in pending_feedback
                    if (collection == 'claims' and _same_text(finding.get('claim'), original.get('claim')))
                    or (collection == 'conditionReview' and finding.get('location') == f'conditionReview[{index}]')]
        signature = hashlib.sha256(json.dumps([collection,index,original,relevant],
            ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        seen = signatures.get(signature, 0)
        signatures[signature] = seen + 1
        if seen >= 3:
            raise ValueError('逐条核验、原文重查和独立计算后，同一核验问题仍未改变。')
        strategy = min(seen, 2)
        trial_holder = {}

        def validate_patch(candidate):
            patch = parse(candidate)
            rows = patch.get(collection)
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                raise ValueError(f'只返回{collection}中的当前一项。')
            updated = rows[0]
            identity = 'claim' if collection == 'claims' else 'claimId'
            if not _same_text(updated.get(identity), original.get(identity)):
                raise ValueError('局部核验不能删除或改述原主张。')
            trial = deepcopy(review)
            trial[collection][index] = updated
            trial_holder['attempt'] = trial
            merged = json.dumps(trial, ensure_ascii=False)
            try:
                validate(merged)
            except ValueError:
                remaining = latest_feedback()
                trial_holder['failure_feedback'] = list(remaining)
                if not remaining or (collection,index) in _targets(trial, remaining):
                    raise
            trial_holder['review'] = trial

        request = {'collection':collection, 'item':original, 'feedback':relevant,
            'strategy':['local_correction','source_first','independent_calculation'][strategy]}
        try:
            candidate = await generate(request, validate_patch)
            if not trial_holder:
                validate_patch(candidate)
        except ValueError as exc:
            history.append({'localReviewTarget': {'collection':collection,'index':index},
                            'repairStrategy':request['strategy'], 'validationFeedback':str(exc)})
            # Retain the most recent validation details for this row, even if
            # the provider's wrapper rejected the response before returning it.
            if trial_holder.get('failure_feedback'):
                review = trial_holder['attempt']
                pending_feedback = trial_holder['failure_feedback']
            continue
        review = trial_holder['review']
        history.append({'localReviewTarget': {'collection':collection,'index':index},
                        'repairStrategy':request['strategy'], 'rawReview':json.dumps(review,ensure_ascii=False)})
        try:
            validate(json.dumps(review,ensure_ascii=False))
        except ValueError:
            pending_feedback = list(latest_feedback())
        else:
            return json.dumps(review,ensure_ascii=False)
    validate(json.dumps(review,ensure_ascii=False))
    return json.dumps(review,ensure_ascii=False)
