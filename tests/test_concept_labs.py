import math
import json
import pytest
from app.concept_labs import BY_ID, TOPIC_LABS, evaluate
from app.interactive_lab import get_template, validate_parameters, _computed_series
from app.resource_bundles import _interactive_template_for_knowledge_point, _interactive_template_directory


@pytest.mark.parametrize("template_id", list(BY_ID))
def test_all_concept_controls_execute_across_their_declared_range(template_id):
    template = get_template(template_id)
    parameter = template.parameters[0]
    for value in (parameter.minimum, parameter.default, parameter.maximum):
        if parameter.kind == "integer":
            value = int(value)
        params = validate_parameters(template, {"value": value})
        metrics, feedback = evaluate(template_id, params)
        assert set(metrics) == {metric.key for metric in template.metrics}
        assert all(math.isfinite(x) for x in metrics.values())
        assert feedback
        assert all(series.points for series in _computed_series(template, params))


def test_known_numerical_results_and_boundary_cases():
    def run(key, value):
        return evaluate("concept-" + key, {"value": value})[0]
    assert run("derivative", 1)["m1"] == pytest.approx(8)
    assert run("derivative", 1)["m2"] == pytest.approx(8, abs=1e-6)
    assert run("conditional", 20) == {"m0": .5, "m1": .5, "m2": 0}
    assert run("variance", 5) == {"m0": 3, "m1": 2, "m2": 2.5}
    assert run("cross-entropy", 0)["m1"] == pytest.approx(math.log(2))
    assert run("linear-model", 1)["m2"] == 0
    assert run("distributed-gradient", 2) == {"m0": 5.5, "m1": 4, "m2": .45}
    assert run("serialization", -2)["m2"] == 0
    assert run("boxes", 0)["m2"] == 1
    assert run("boxes", 2)["m2"] == 0
    assert run("autoencoder", 3)["m0"] == pytest.approx(0, abs=1e-10)
    assert run("beam-search", 1)["m0"] == pytest.approx(.3)
    assert run("beam-search", 2)["m0"] == pytest.approx(.36)
    assert run("tool-recovery", 3) == {"m0": 4, "m1": 10, "m2": 1}
    assert run("graph-message", 12)["m0"] < run("graph-message", 1)["m0"]
    assert run("preprocessing", 0)["m0"] == run("preprocessing", 10)["m0"]


def test_concepts_map_to_their_own_executable_operation():
    for title, template_id in TOPIC_LABS.items():
        assert _interactive_template_for_knowledge_point(title).template_id == template_id


@pytest.mark.parametrize('template_id', list(BY_ID))
def test_generation_can_read_the_actual_experiment_contract(template_id):
    contract = _interactive_template_directory(get_template(template_id))
    assert contract['executionMode'] == 'synthetic_data_computation'
    assert contract['capabilities'] == BY_ID[template_id][5]
    assert contract['parameters'] and contract['metrics']


def test_concept_values_follow_the_declared_operations():
    def run(key, value):
        metrics, feedback = evaluate('concept-' + key, {'value': value})
        return metrics, json.loads(feedback[0])
    assert run('tensor-shape', 4)[0] == {'m0': 3, 'm1': 24, 'm2': 24}
    assert run('dot-product', -1)[0] == {'m0': -2, 'm1': 1.5, 'm2': -.5}
    assert run('matrix-vector', 2)[0] == {'m0': 4, 'm1': -1, 'm2': 5}
    assert run('imputation', 2)[1]['填补后验证'] == [2,100]
    probs, detail = run('softmax', 0)
    assert sum(probs.values()) == pytest.approx(1)
    assert probs['m0'] == probs['m1'] and probs['m2'] < probs['m1']
    assert run('linear-training', 20)[0]['m2'] < run('linear-training', 1)[0]['m2']
    for key in ['mlp', 'recurrent']:
        for value in [-1.5,0,1.5]:
            metrics, detail = run(key, value)
            assert metrics['m2'] == pytest.approx(detail['中心差分梯度'], abs=1e-8)
    assert run('quadratic-descent', .5)[0] == {'m0': 3, 'm1': 0, 'm2': 0}
    assert run('quadratic-descent', 1.25)[0]['m1'] > 9
    _, adam = run('adam', .1)
    first = adam['更新'][0]
    assert first['校正一阶矩'] == pytest.approx(1)
    assert first['校正二阶矩'] == pytest.approx(1)
    assert first['Adam权重'] == pytest.approx(1.9)
    schedule, _ = run('lr-schedule', 1)
    assert schedule['m1'] == schedule['m2']
    _, attention = run('attention', 1)
    assert sum(attention['权重']) == pytest.approx(1)
    assert attention['权重'][0] == attention['权重'][1]
    low, _ = run('causal-attention', -2)
    high, _ = run('causal-attention', 4)
    assert low['m0'] == high['m0'] and low['m2'] == high['m2'] == 0
    assert low['m1'] != high['m1']
    assert run('text-classification', 20)[0]['m2'] < math.log(2)
    perplexity, _ = run('perplexity', 1)
    assert perplexity['m2'] == pytest.approx(math.exp(perplexity['m1']))
    assert run('tiny-language-training', 30)[0]['m0'] < run('tiny-language-training', 0)[0]['m0']
    assert run('low-rank', 3)[0] == {'m0': 21, 'm1': 12, 'm2': 0}
    assert run('dpo', 0)[0]['m0'] == pytest.approx(math.log(2))
    assert run('dpo', 0)[0]['m1'] == pytest.approx(-.1)
    assert run('retrieval-ranking', 1)[0]['m0'] == 0
    assert run('retrieval-ranking', 4)[0]['m0'] == 1
    assert run('evidence-ablation', 0)[0] == {'m0': 0, 'm1': 3, 'm2': 0}
    assert run('agent-state', 3)[0] == {'m0': 4, 'm1': 10, 'm2': 1}
    assert run('code-cycle', 0)[0] == {'m0': 3, 'm1': 3, 'm2': 0}
    assert run('code-cycle', 2)[0] == {'m0': 0, 'm1': 3, 'm2': 1}


def test_overfitting_is_not_algorithm_complexity():
    assert _interactive_template_for_knowledge_point('欠拟合、过拟合与模型复杂度').template_id == 'model-complexity-generalization'
    assert _interactive_template_for_knowledge_point('时间与空间复杂度').template_id == 'algorithm-complexity'
