import asyncio
from copy import deepcopy
import json

import pytest

from app.resource_review_adjudication import _validate_decisions, adjudicate_review
from app.resource_review_context import review_findings
from app.resource_review_context import unresolved_review_findings, merge_unresolved_review


def inputs():
    candidates = [{'type': 'code_sandbox', 'version_id': 'v-current',
                   'content': '验证误差为0.2，训练误差为0.1。'}]
    finding = {'resourceType': 'code_sandbox', 'version_id': None,
               'issue_id': 'old-issue', 'location': 'content', 'issue': '训练与验证不同'}
    decision = {'issue_id': 'old-issue', 'verdict': 'false_positive',
                'candidate_quote': candidates[0]['content'],
                'reason': '这两个指标评估不同数据，允许不同。', 'source_evidence': []}
    return candidates, finding, decision


def test_null_version_binds_only_unique_current_candidate_without_mutation():
    candidates, finding, decision = inputs()
    before = deepcopy(finding)
    review = {'approved': False, 'findings': [finding]}
    result = _validate_decisions([decision], findings=[finding], sources={},
                                 candidates=candidates, review=review)
    assert result['approved']
    assert result['adjudication'][0]['version_id'] == 'v-current'
    normalized = review_findings(review, candidates)
    assert normalized['findings'][0]['version_id'] == 'v-current'
    assert review_findings(normalized, candidates) == normalized
    assert finding == before


@pytest.mark.parametrize('explicit_version,second', [('v-stale', False), (None, True)])
def test_explicit_stale_or_ambiguous_version_cannot_close_a_finding(explicit_version, second):
    candidates, finding, decision = inputs()
    finding['version_id'] = explicit_version
    if second:
        candidates.append({**candidates[0], 'version_id': 'v-other'})
    normalized = review_findings({'findings': [finding]}, candidates)
    assert normalized['findings'][0]['version_id'] == explicit_version
    with pytest.raises(ValueError, match='old-issue'):
        _validate_decisions([decision], findings=[finding], sources={},
                            candidates=candidates, review={'approved': False})


def test_adjudicator_receives_bound_version_and_preserves_existing_issue_identity():
    candidates, finding, decision = inputs()
    requests = []

    class Judge:
        model = 'test'

        async def generate(self, system, prompt, **kwargs):
            request = json.loads(prompt)
            requests.append(request)
            assert request['findings'][0]['version_id'] == 'v-current'
            return json.dumps({'decisions': [decision]}, ensure_ascii=False)

    result = asyncio.run(adjudicate_review(Judge(), manifest={}, candidates=candidates,
                        review={'approved': False, 'findings': [finding]}))
    assert len(requests) == 1 and result['approved']
    assert result['adjudication'][0]['issue_id'] == 'old-issue'


def test_interrupted_verdict_survives_a_retry_that_misses_the_same_draft_issue():
    candidates, finding, decision = inputs()
    history = [('resource_generation.review_result', {'review': {'findings': [finding]},
                                                      'version_ids': ['v-current']})]
    pending = unresolved_review_findings(history, candidates)
    merged = merge_unresolved_review({'approved': True, 'findings': []}, pending)
    assert not merged['approved'] and merged['rejectedTypes'] == ['code_sandbox']
    assert merged['findings'][0]['issue_id'] == 'old-issue'
    history.append(('resource_generation.review_adjudicated', {'adjudication': [decision]}))
    assert unresolved_review_findings(history, candidates) == []
    # Replayed raw review history must not reopen the already excluded issue.
    history.append(history[0])
    assert unresolved_review_findings(history, candidates) == []


def test_previous_versions_do_not_accumulate_as_current_work():
    candidates, finding, _ = inputs()
    finding['version_id'] = 'old-version'
    assert unresolved_review_findings([('resource_generation.review_result', {'findings': [finding]})], candidates) == []


@pytest.mark.parametrize('event_versions', [['old-version'], []])
def test_null_historical_version_is_never_rebound_to_a_new_draft(event_versions):
    candidates, finding, _ = inputs()
    history = [('resource_generation.review_result', {
        'version_ids': event_versions, 'review': {'findings': [finding]}})]
    assert unresolved_review_findings(history, candidates) == []


def test_same_draft_null_version_uses_its_saved_review_snapshot():
    candidates, finding, _ = inputs()
    history = [('resource_generation.review_result', {
        'reviewed_versions': [{'type': 'code_sandbox', 'version_id': 'v-current'}],
        'findings': [finding]})]
    pending = unresolved_review_findings(history, candidates)
    assert pending[0]['version_id'] == 'v-current'
    assert pending[0]['issue_id'] == 'old-issue'


def test_bundle_adjudication_isolates_quote_target_and_reuses_successful_group():
    candidates = [{'type': kind, 'version_id': kind + '-v', 'content': text}
                  for kind, text in [('handout', '讲义里的原句。'), ('code_sandbox', '代码里的原句。')]]
    findings = [{'resourceType': item['type'], 'version_id': item['version_id'],
                 'issue_id': item['type'], 'issue': '核对本资源原句'} for item in candidates]
    cached, calls = {}, []
    fail_code = True

    class Judge:
        model = 'test'

        async def generate(self, system, prompt, **kwargs):
            request = json.loads(prompt)
            assert len(request['candidates']) == 1
            target = request['candidates'][0]
            calls.append(target['type'])
            other = request['dependencies'][0]
            quote = other['content'] if fail_code and target['type'] == 'code_sandbox' else target['content']
            return json.dumps({'decisions': [{'issue_id': target['type'], 'verdict': 'false_positive',
                'candidate_quote': quote, 'reason': '原句成立。', 'source_evidence': []}]}, ensure_ascii=False)

    def run():
        return asyncio.run(adjudicate_review(Judge(), manifest={}, candidates=candidates,
            review={'approved': False, 'findings': findings}, completed=cached,
            save=lambda key, value: cached.update({key: value})))

    with pytest.raises(ValueError, match='code_sandbox'):
        run()
    assert calls.count('handout') == 1 and calls.count('code_sandbox') == 2
    fail_code = False
    result = run()
    assert result['approved'] and len(result['adjudication']) == 2
    assert calls.count('handout') == 1 and calls.count('code_sandbox') == 3


def test_solver_adjudication_receives_the_installed_implementation():
    import inspect
    from sklearn.linear_model import LinearRegression
    from app.resource_review_adjudication import linear_regression_solver_evidence
    evidence = linear_regression_solver_evidence()
    assert evidence['source_excerpt'] in inspect.getsource(LinearRegression.fit)
    candidate = {'type':'code_sandbox','version_id':'solver-version',
                 'content':'LinearRegression的参数行为按当前版本核对。'}

    class Judge:
        model = 'test'

        async def generate(self, system, prompt, **kwargs):
            request = json.loads(prompt)
            assert request['installed_runtime_evidence'] == [evidence]
            return json.dumps({'decisions':[{'issue_id':'solver','verdict':'false_positive',
                'candidate_quote':candidate['content'],'reason':'这句话要求按当前版本核对，成立。'}]},ensure_ascii=False)

    result=asyncio.run(adjudicate_review(Judge(),manifest={},candidates=[candidate],
        review={'approved':False,'findings':[{'resourceType':'code_sandbox',
            'version_id':'solver-version','issue_id':'solver','issue':'参数作用不对'}]}))
    assert result['approved']
