"""Recompute derived teaching numbers, then compare their printed precision.

The extraction step sees the draft. The program author receives only the
original inputs, method and requested quantities, never the claimed answers.
Execution uses the learner's existing sandbox and writes no learning records.
"""
from __future__ import annotations

import asyncio
from copy import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
import re

from config import CONFIG
from llm_client import ModelOutputLimitError, parse_json_object


EXTRACT_SYSTEM = (
    '你整理教学材料中可以用程序复算的数值。只输出JSON：cases数组、not_computed数组。'
    'cases每项含id、inputs（原始数据对象）、method（完整算法、参数、单位及版本）、'
    'input_evidence数组（path与逐字quote）、targets数组。每个target含id、quantity（要计算的量及顺序）、'
    'claims数组，每个claim含path、quote（逐字原文）、values（按出现顺序列出的数值字符串，保留小数位、指数及精确分数）。'
    '原文写1/6时values也写1/6，不改成近似小数，不拆开分子分母；概率等精确分数同样按原条件复算。'
    'path从content开始，如content.slides[6].body；content为Markdown时直接用content。'
    '只选作者宣称由给定数据/方法得到的值，覆盖逐点预测、每项误差、汇总、概率等；汇总正确不能替代逐点值复算。'
    '题目待判断的说法、错误选项和解析正在否定的数值不是作者采纳的结论，除非解析明确认同，不列为待修作者答案。'
    '相同计算归为一case，相同量在多处出现可列多个claim。每个claim.values须与quantity一一对应；'
    '不要把行号、输入值混入输出。数值的百分号须在quantity明确单位。'
    '输入和method只能取原题、正文给定条件及来源；不得用待验结果反造输入、拟合残差或算法，'
    'method必须保留正文实际指定的库、类、版本和参数；正文为辨析而提到的另一算法、错误做法或不同实现不能混入实际计算方法。'
    '例如正文指定sklearn的LinearRegression并说明NumPy lstsq会得到不同结果时，只按指定的sklearn方法复算，不能把lstsq写成该方法。'
    '正文声称的求解器秩、系数和误差均是待验输出，放入targets，不作为method里的既定参数。'
    '计算目标必须保留具体对象与接口：原始特征矩阵、显式增加常数列的矩阵、拟合器内部处理后的矩阵是不同对象；'
    '不能因为fit_intercept=True就自行给特征加一列并把它的matrix_rank当作拟合器报告的有效秩。'
    '涉及数值秩时，在quantity写清矩阵构造、是否中心化、使用matrix_rank还是拟合器rank_及实际容差；'
    '原文指参考拟合器时按该拟合器公开属性计算。若原文对象有歧义，分别列出各对象的计算目标供审核辨析，'
    '在not_computed说明同一原句不能直接与某个任意选定对象比较，不凭代数等价关系替换数值计算对象。'
    '不得把作者宣称的结果放进inputs/method/quantity。没有原始数据的题给指标只作输入，不假造训练数据重算。'
    '明确区分“给定的练习预测”与“按某拟合方法计算的预测”；后者必须从原训练数据拟合再算，不能只复算MSE。'
    'not_computed逐项写path、quote、reason，说明题给数据、非数值结论或真正缺失的计算条件；无需计算可返回cases=[]。'
    '完整处理所有可计算例子，不因资料长截取前几项。不输出私有思维链。'
)

PROGRAM_SYSTEM = (
    '你根据原始数据和方法独立编写Python复算程序。没有作者声称的答案；不得猜测或构造目标结果。'
    '只输出JSON对象code，code为完整可执行Python；按给定算法/参数/数据实际计算每个target。'
    '可用math、json、statistics、numpy、sklearn；禁止网络、文件、系统访问。'
    '只有标准输入JSON，使用json.loads(input())读取cases，每项含id/inputs/method/targets。'
    '最后只打印一个JSON对象values，键为case_id:target_id，值是该量的数值数组，按quantity规定顺序；'
    '标量也用单元素数组。输出未舍入值，由系统按原文小数位比较，不能自行设置宽容差。'
    '使用实际算法而不是根据汇总误差反造逐点值；求解器参数、截断、截距与原始矩阵秩必须区分。'
    '明确指定某库的类/方法时直接使用该接口，不自行换成理论等价实现；数值秩亏、容差和版本可使等价公式产生不同数值。'
    '例如LinearRegression(fit_intercept=True)的稠密求解会中心化特征，并非显式添加常数列；'
    '其有效秩读拟合后model.rank_。原特征的np.linalg.matrix_rank、显式增广矩阵的默认秩和model.rank_应分别计算、分别标注，不能互相冒充。'
    '当前运行环境不允许getattr/setattr/hasattr、eval/exec和文件/系统访问；需要公开属性时直接访问，如model.rank_。'
    'numpy数值转成原生float/int，json.dumps(...,allow_nan=False)。不能计算时明确抛出带原因的ValueError。'
    'previous_failure若存在，只修正程序/接口问题，保留原数据和算法。'
)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def needs_computation(candidate):
    # Code execution already checks code resources. Static tables, equations and
    # reported calculations also need an actual computation, irrespective of UI.
    if candidate.get('type') in {'code_sandbox', 'video', 'mind_map'}:
        return False
    text = str(candidate.get('content') or '')
    return bool(re.search(r'\d', text) and re.search(
        r'\|[^\n]+\||[=＝≈]|MSE|均方|计算结果|预测值|预测表|概率|方差|标准差', text, re.I))


def _field(candidate, path):
    if not isinstance(path, str) or not re.fullmatch(r'content(?:\.[\w]+|\[\d+\])*', path):
        raise ValueError('数值核验的位置无效。')
    value = candidate['content']
    if path != 'content':
        value = json.loads(value)
        for key, index in re.findall(r'\.([\w]+)|\[(\d+)\]', path[7:]):
            value = value[key] if key else value[int(index)]
    return value if isinstance(value, str) else _json(value)


def _quote(candidate, item):
    quote = item.get('quote')
    field = _field(candidate, item.get('path'))
    if isinstance(quote, str) and quote.strip() and quote in field:
        return
    # A copied question may end with a question mark while the same source
    # sentence is followed by a semicolon in an enumerated task. Recover only
    # its unique exact text up to that sentence boundary; no numbers or wording
    # are normalized, and raw extraction remains in the saved call evidence.
    if isinstance(quote, str) and quote.endswith(('。', '？')):
        core = quote[:-1]
        if len(core) >= 8 and field.count(core) == 1:
            end = field.index(core) + len(core)
            if end == len(field) or field[end] in '。；！？\n':
                item['quote'] = core + (field[end] if end < len(field) and field[end] != '\n' else '')
                return
    raise ValueError(f"数值核验引句不在所指原文字段中：{item.get('path')}，引句={quote!r}。请逐字复制该字段原句。")


_FRACTION = r'[+−-]?[0-9]+\s*/\s*[+−-]?[0-9]+'
_DECIMAL = r'[+−-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:(?:[eE][+−-]?[0-9]+)|(?:\s*(?:×|\*|\\times)\s*10(?:\s*\^\s*\{?[+−-]?[0-9]+\}?|[⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)))?(?:…|\.\.\.)?'
_NUMBER = rf'(?:{_FRACTION}|{_DECIMAL})'


def _fraction_parts(value):
    if isinstance(value, str) and re.fullmatch(_FRACTION, value.strip()):
        numerator, denominator = (int(part.strip().replace('−', '-')) for part in value.split('/'))
        if denominator == 0:
            raise ValueError('待验分数的分母不能为零。')
        return numerator, denominator
    return None


def _same_printed_number(left, right):
    left_fraction, right_fraction = _fraction_parts(left), _fraction_parts(right)
    if left_fraction is not None or right_fraction is not None:
        # Retain the printed numerator and denominator, including unreduced
        # fractions, rather than matching a component or rounded decimal.
        return left_fraction == right_fraction
    a, b = _printed_number(left), _printed_number(right)
    return a == b and a.as_tuple().exponent == b.as_tuple().exponent


def _truncated(value):
    return value.strip().endswith(('…', '...'))


def _printed_number(value):
    """Read a printed number without losing its significant decimal places."""
    if not isinstance(value, str) or not re.fullmatch(_NUMBER, value.strip()):
        raise ValueError('待验数值必须保留原文显示精度，支持小数、科学计数法及精确分数。')
    fraction = _fraction_parts(value)
    if fraction is not None:
        return Decimal(fraction[0]) / Decimal(fraction[1])
    normalized = re.sub(r'(?:…|\.\.\.)$', '', value.strip()).replace('−', '-')
    normalized = re.sub(r'10([⁺⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)',
        lambda m: '10^' + m.group(1).translate(str.maketrans('⁺⁻⁰¹²³⁴⁵⁶⁷⁸⁹', '+-0123456789')), normalized)
    normalized = re.sub(r'\s*(?:×|\*|\\times)\s*10\s*\^\s*\{?([+-]?\d+)\}?', r'e\1', normalized)
    try:
        result = Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError('待验数值格式无效：' + value) from exc
    if not result.is_finite():
        raise ValueError('待验数值须为有限数字。')
    return result


def _validate_plan(plan, candidate):
    cases, skipped = plan.get('cases'), plan.get('not_computed')
    if not isinstance(cases, list) or not isinstance(skipped, list) or not (cases or skipped):
        raise ValueError('需要列出计算项或明确的无需计算依据。')
    ids = set()
    for case in cases:
        if (not case.get('id') or case['id'] in ids or not isinstance(case.get('inputs'), dict)
                or not case.get('method') or not case.get('input_evidence') or not case.get('targets')):
            raise ValueError('计算项缺原始输入、方法、依据或目标。')
        ids.add(case['id'])
        for evidence in case['input_evidence']:
            _quote(candidate, evidence)
        targets = set()
        for target in case['targets']:
            if not target.get('id') or target['id'] in targets or not target.get('quantity') or not target.get('claims'):
                raise ValueError('计算目标缺少唯一身份、计算含义或对应原句。')
            targets.add(target['id'])
            for claim in target['claims']:
                _quote(candidate, claim)
                if not isinstance(claim.get('values'), list) or not claim['values']:
                    raise ValueError('待验数值未提供。')
                offset = 0
                tokens = list(re.finditer(_NUMBER, claim['quote']))
                for value in claim['values']:
                    _printed_number(value)
                    # Chinese prose can touch a number. Match whole numeric
                    # tokens (including signs/exponents), not word boundaries.
                    found = next((token for token in tokens if token.start() >= offset
                        and _same_printed_number(token.group(), value)), None)
                    if found is not None and _truncated(found.group()) != _truncated(value):
                        raise ValueError('待验数值须保留原文省略号，不能将截断小数当四舍五入值。')
                    if found is None:
                        raise ValueError(f'待验数值{value}与原文顺序、数值或显示精度不符：{claim["quote"]}')
                    offset = found.end()
    for item in skipped:
        _quote(candidate, item)
        if not item.get('reason'):
            raise ValueError('未计算项目缺少依据。')
    return plan


def _solver_inputs(plan):
    return [{'id': c['id'], 'inputs': c['inputs'], 'method': c['method'],
             'targets': [{'id': t['id'], 'quantity': t['quantity']} for t in c['targets']]}
            for c in plan['cases']]


def _compare(plan, values):
    expected_keys = {c['id'] + ':' + t['id'] for c in plan['cases'] for t in c['targets']}
    if not isinstance(values, dict) or set(values) != expected_keys:
        raise ValueError('实跑输出没有完整对应全部计算目标。')
    results = []
    for case in plan['cases']:
        for target in case['targets']:
            actual = values[case['id'] + ':' + target['id']]
            if not isinstance(actual, list) or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                                   or not Decimal(str(v)).is_finite() for v in actual):
                raise ValueError('实际计算结果须为有限数值数组。')
            for claim in target['claims']:
                expected = claim['values']
                if len(expected) != len(actual):
                    raise ValueError('计算结果与待核对数值的维数不一致。')
                matches = []
                for printed, observed in zip(expected, actual):
                    fraction = _fraction_parts(printed)
                    if fraction is not None:
                        exact, measured = Fraction(*fraction), Fraction(Decimal(str(observed)))
                        # Exact fractions have no displayed decimal place to
                        # round to; allow only floating-point calculation noise.
                        tolerance = max(abs(exact), abs(measured)) * Fraction(1, 10**12)
                        matches.append(abs(exact - measured) <= tolerance)
                        continue
                    a, b = _printed_number(printed), Decimal(str(observed))
                    if _truncated(printed):
                        unit = Decimal(10) ** a.as_tuple().exponent
                        lower, upper = (a - unit, a) if a.is_signed() else (a, a + unit)
                        epsilon = abs(b) * Decimal('1e-14')
                        matches.append(lower - epsilon <= b <= upper + epsilon)
                        continue
                    decimal = '.' in printed or a.as_tuple().exponent != 0
                    tolerance = max(Decimal(10) ** a.as_tuple().exponent / 2,
                                    abs(b) * Decimal('1e-10')) if decimal else Decimal(0)
                    matches.append(abs(a - b) <= tolerance)
                results.append({**claim, 'case_id': case['id'], 'target_id': target['id'],
                                'quantity': target['quantity'], 'actual': actual, 'matches': all(matches)})
    return results


def _execution_values(execution, plan):
    full = execution.get('stdoutComplete') or {}
    if execution['status'] != 'success' or (not full.get('available') and (execution.get('stdoutCapture') or {}).get('truncated')):
        raise ValueError('计算程序未完成：' + str(execution.get('stderr') or execution['status']))
    output = json.loads(full['text'] if full.get('available') else execution.get('stdout', ''))
    # A valid target mapping does not become a failed computation merely because
    # the author omitted the redundant outer {values: ...} envelope.
    values = output.get('values', output) if isinstance(output, dict) else output
    _compare(plan, values)
    return values


async def verify_numerical_content(backend, candidate, *, completed=None, save=None, slots=None):
    if not needs_computation(candidate):
        return None
    from app.code_sandbox import CodeSandboxRunState, LocalPythonExecutor
    cache = completed if completed is not None else {}
    slots = slots if slots is not None else asyncio.Semaphore(2)
    worker = copy(backend)
    if hasattr(worker, 'reasoning_effort'):
        worker.reasoning_effort = 'high'
    if hasattr(worker, 'max_tokens'):
        worker.max_tokens = 32768
    identity = {'content': candidate['content'], 'type': candidate['type'], 'system': EXTRACT_SYSTEM,
                'model': getattr(worker, 'model', '')}
    key = 'numerical-plan:' + _hash(identity)

    def remember(name, value):
        cache[name] = value
        if save:
            save(name, value)

    async def generate(system, packet, role):
        from app.resource_generation_parts import generate_structured_parts
        encoded = _json(packet)
        overflow = 'numerical-overflow:' + _hash([system, packet, role])
        class BoundedBackend:
            model = getattr(worker, 'model', '')
            async def generate(self, system, user, *, role):
                async with slots:
                    return await worker.generate(system, user, role=role)
        bounded = BoundedBackend()
        if not cache.get(overflow):
            try:
                return await bounded.generate(system, encoded, role=role)
            except ModelOutputLimitError as exc:
                remember(overflow, {'error': str(exc)})
        result = await generate_structured_parts(bounded, resource_type=role, system=system,
            user=encoded, completed=cache, save=remember)
        return _json(result)

    plan = cache.get(key)
    if plan is None and (cache.get(key + ':failure') or {}).get('raw'):
        # A parser fix can accept a complete saved extraction. Revalidate every
        # source quote and value; never edit the candidate or its review state.
        try:
            plan = _validate_plan(parse_json_object(cache[key + ':failure']['raw']), candidate)
        except (ValueError, KeyError, TypeError, IndexError):
            pass
        else:
            remember(key, plan)
    if plan is None:
        raw = ''
        try:
            packet = {'candidate': {k: candidate.get(k) for k in ('type', 'content')},
                      'previous_failure': cache.get(key + ':failure')}
            raw = await generate(EXTRACT_SYSTEM, packet, 'numerical_extractor')
            plan = _validate_plan(parse_json_object(raw), candidate)
        except Exception as exc:
            failure = {'raw': raw, 'error': str(exc), 'error_type': type(exc).__name__}
            remember(key + ':failure:' + str(len(cache)), failure)
            remember(key + ':failure', failure)
            raise
        remember(key, plan)
    inputs = _solver_inputs(plan)
    if not inputs:
        return {'plan': plan, 'comparisons': [], 'status': 'not_applicable'}
    execution_key = 'numerical-execution:' + _hash({'inputs': inputs, 'system': PROGRAM_SYSTEM,
        'model': getattr(worker, 'model', ''), 'timeout': CONFIG.sandbox_timeout})
    evidence = cache.get(execution_key)
    failed = cache.get(execution_key + ':failure') or {}
    if evidence is None and (failed.get('execution') or {}).get('status') == 'success':
        try:
            values = _execution_values(failed['execution'], plan)
        except (ValueError, KeyError, TypeError):
            pass
        else:
            evidence = {'code': failed['code'], 'inputs': inputs, 'execution': failed['execution'], 'values': values}
            remember(execution_key, evidence)
    if evidence is None:
        raw, code, execution = '', '', None
        try:
            packet = {'cases': inputs,
                      'stdin_contract': '运行时标准输入直接是cases数组，不是本请求对象。使用 cases=json.loads(input()) 后直接遍历 cases；不要访问 data["cases"]。',
                      'previous_failure': cache.get(execution_key + ':failure')}
            raw = await generate(PROGRAM_SYSTEM, packet, 'numerical_programmer')
            code = str(parse_json_object(raw).get('code') or '')
            if not code.strip():
                raise ValueError('数值核验程序为空。')
            executor = LocalPythonExecutor()
            if not executor.enabled:
                raise ValueError('代码运行服务尚未启用。')
            state = CodeSandboxRunState(runAttemptId='numeric-' + _hash([inputs, code])[:24],
                ownerPublicId='generation-check', sourceResourceId='candidate', sourceResourceVersionId='candidate',
                entryFile='verify.py', runtimeBoundary='trusted_local', timeoutSeconds=max(1, int(CONFIG.sandbox_timeout)),
                code=code, codeSha256=hashlib.sha256(code.encode()).hexdigest(), standardInput=_json(inputs),
                requiredChecks=(), status='queued', createdAt=datetime.now(timezone.utc).isoformat())
            async with slots:
                result = await executor.execute(state)
            execution = result.model_dump(mode='json')
            values = _execution_values(execution, plan)
            evidence = {'code': code, 'inputs': inputs, 'execution': execution, 'values': values}
            remember(execution_key, evidence)
        except Exception as exc:
            failure = {'raw': raw, 'code': code, 'execution': execution, 'error': str(exc), 'error_type': type(exc).__name__}
            remember(execution_key + ':failure:' + str(len(cache)), failure)
            remember(execution_key + ':failure', failure)
            raise
    return {'status': 'computed', 'plan': plan, **evidence, 'comparisons': _compare(plan, evidence['values'])}


def apply_numerical_findings(review, candidate, evidence):
    """A computed discrepancy must reach adjudication even if prose misses it."""
    findings = list(review.get('findings') or [])
    for item in (evidence or {}).get('comparisons', []):
        if item['matches']:
            continue
        findings.append({'resourceType': candidate['type'], 'version_id': candidate.get('version_id'),
            'location': item['path'], 'issue': '所列数值与原数据按所述方法计算的结果不一致。',
            'evidence': {'quote': item['quote'], 'expected': item['values'], 'actual': item['actual'],
                         'quantity': item['quantity'], 'computation': {
                             'input': next(c for c in evidence['inputs'] if c['id'] == item['case_id']),
                             'code': evidence['code'], 'status': evidence['execution']['status']}},
            'fix': '先核对计算使用的原始数据、算法与参数；按确认后的实际结果局部修订该表及相关说明。',
            'severity': 'knowledge_error', 'numerical_verification': True})
    if len(findings) == len(review.get('findings') or []):
        return review
    return {**review, 'approved': False, 'findings': findings,
            'rejectedTypes': list(dict.fromkeys([*review.get('rejectedTypes', []), candidate['type']]))}
