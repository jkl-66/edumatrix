"""Locate quoted evidence inside this answer's frozen materials, without fuzzy matching."""
from __future__ import annotations

import ast
import json
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import operator
import re


def _prose_links(text: str):
    code = [match.span() for match in re.finditer(r'`+[^`]*`+', text)]
    for match in re.finditer(r'(?<!!)\[(?P<label>[^\[\]\n]+)\]\(https?://[^\s()]+\)', text):
        if not any(start < match.end() and end > match.start() for start, end in code):
            yield match


def _compact(text: str, *, math_markup: bool = False, markdown_links: bool = False) -> tuple[str, list[int]]:
    omitted = set()
    if markdown_links:
        # Compare the visible label of a complete prose link. A regenerated
        # destination is not a different quotation; the returned citation
        # still contains the exact original link and source offsets. Code
        # literals retain their URL, and labels/signs/numbers remain exact.
        for match in _prose_links(text):
            start, end = match.span('label')
            omitted.update(range(match.start(), start))
            omitted.update(range(end, match.end()))
    if math_markup:
        # Paired math delimiters affect rendering, not the quoted expression.
        # Keep commands, signs, powers and escaped currency characters intact.
        # Offsets still refer to the original source, including its markup.
        for pattern in (r'(?<!\\)\$\$(?P<body>[\s\S]+?)(?<!\\)\$\$',
                        r'(?<![\\$])\$(?!\$)(?P<body>[^\s$](?:[^$\n]*?[^\s$])?)(?<!\\)\$(?!\$)',
                        r'\\\((?P<body>[\s\S]+?)\\\)', r'\\\[(?P<body>[\s\S]+?)\\\]'):
            for match in re.finditer(pattern, text):
                if any(index in omitted for index in range(match.start(), match.end())):
                    continue
                start, end = match.span('body')
                omitted.update(range(match.start(), start))
                omitted.update(range(end, match.end()))
    positions = [index for index, char in enumerate(text) if not char.isspace() and index not in omitted]
    return ''.join(text[index] for index in positions), positions


def _quote_passages(material: dict):
    text = str(material.get('quote') or '')
    yield 'passage', text, None
    yield 'title', str(material.get('title') or ''), None
    if material.get('kind') != 'resource_version':
        return
    # Resource snapshots keep their complete structured JSON. A learner sees
    # decoded field text (not JSON escape sequences), including multiline code.
    # Match within a single actual field; never join separate passages or
    # interpret literal backslashes as escapes outside this JSON container.
    serialized = text.split('本次材料全文：\n', 1)[-1]
    try:
        body = json.loads(serialized)
    except (ValueError, TypeError):
        return

    def fields(value, path):
        if isinstance(value, str):
            yield 'passage', value, path
        elif isinstance(value, dict):
            for key, child in value.items():
                yield from fields(child, path + [key])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from fields(child, path + [index])

    yield from fields(body, [])


def verify_claim_quotes(candidate: dict, materials: list[dict]) -> dict:
    """Check quote provenance only; the verifier still judges semantic support.

    Whitespace, paired math delimiters and rendered prose-link differences are tolerated. Signs,
    negations, digits and formula expressions remain exact. Distinct passages are never
    concatenated into an apparently continuous quote.
    """
    raw = candidate.get('citations')
    if not isinstance(raw, list) or not raw:
        refs = candidate.get('source_ref_ids') or candidate.get('sourceRefIds') or []
        refs = [refs] if isinstance(refs, str) else refs
        raw = [{'source_ref_id': ref, 'quote': candidate.get('quote', '')} for ref in refs]
        # The legacy shape supplies one quote and several alternative sources.
        require_all = False
    else:
        require_all = True
    verified, failures = [], []
    for citation in raw:
        if not isinstance(citation, dict):
            failures.append('invalid_citation')
            continue
        reference = str(citation.get('source_ref_id') or citation.get('sourceRefId') or '').strip()
        quoted = str(citation.get('quote') or '').strip()
        needle, _ = _compact(quoted)
        if not needle:
            failures.append('missing_quote')
            continue
        found = None
        for index, material in enumerate(materials, 1):
            source_id = str(material.get('sourceRefId') or material.get('source_ref_id') or '')
            if not source_id or not material.get('available'):
                continue
            if reference != source_id and reference.strip('[]') != f'S{index}':
                continue
            for kind, text, field_path in _quote_passages(material):
                haystack, positions = _compact(text)
                offset = haystack.find(needle)
                matched_needle = needle
                match_kind = 'whitespace'
                if offset < 0:
                    haystack, positions = _compact(text, math_markup=True)
                    matched_needle, _ = _compact(quoted, math_markup=True)
                    offset = haystack.find(matched_needle) if matched_needle else -1
                    match_kind = 'math_delimiters'
                if offset < 0:
                    haystack, positions = _compact(text, math_markup=True, markdown_links=True)
                    matched_needle, _ = _compact(quoted, math_markup=True, markdown_links=True)
                    offset = haystack.find(matched_needle) if matched_needle else -1
                    match_kind = 'markdown_links'
                if offset < 0:
                    continue
                start, end = positions[offset], positions[offset + len(matched_needle) - 1] + 1
                if match_kind == 'markdown_links':
                    for link in _prose_links(text):
                        if start == link.start('label'):
                            start = link.start()
                        if end == link.end('label'):
                            end = link.end()
                found = {'sourceRefId': source_id, 'quote': text[start:end], 'quoteKind': kind,
                         'matchKind': match_kind,
                         'materialIndex': index,
                         'location': material.get('locationLabel') or material.get('location_label')
                                     or material.get('title') or '原文相关段落'}
                if field_path is not None:
                    found.update(fieldPath=field_path, matchKind='json_string_' + match_kind)
                base = material.get('charStart', material.get('char_start'))
                limit = material.get('charEnd', material.get('char_end'))
                # A pedagogical excerpt can combine separated spans. Only
                # contiguous, version-checked passages have arithmetic offsets.
                if kind == 'passage' and field_path is None and isinstance(base, int) and isinstance(limit, int) and limit - base == len(text):
                    found.update(charStart=base + start, charEnd=base + end)
                break
            if found:
                break
        if found:
            if found not in verified:
                verified.append(found)
        else:
            failures.append('quote_not_in_frozen_source')
    return {'verified': bool(verified) and (not failures or not require_all),
            'citations': verified, 'failures': failures}


_RESULT_NUMBER = r'[+\-−]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+\-]?\d+)?'
_RESULT_MARKER = (r'(?:(?:实际|运行|打印)?输出(?:结果)?|(?:打印|计算|变换|运行)?结果)'
                  r'(?:依次|分别)?(?:为|是|如下|[:：])|'
                  r'(?:依次|分别)(?:为|是|[:：])|'
                  r'(?:分别)?得(?:到)?[\u3400-\u9fff]{0,8}?(?=\s*[+\-−]?(?:\d|\.\d))')


def _given_metric_tables(draft: str) -> dict[str, set[tuple[Decimal, ...]]]:
    """Read complete metric columns explicitly supplied as example inputs.

    A computed/printed table is not input just because it belongs to an example.
    Preserve column identity and order; individual matching numbers are insufficient.
    """
    supplied = {}
    text = re.sub(r'```[\s\S]*?```', '', draft)
    metric = r'(?:训练|验证|测试)(?:集)?\s*(?:MSE|MAE|RMSE|损失|误差|准确率|精确率|召回率|分数)'
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip().startswith('|') or index + 1 >= len(lines):
            continue
        if not re.fullmatch(r'[\s|:\-]+', lines[index + 1]):
            continue
        intro = ' '.join(part for part in lines[max(0, index - 3):index] if part.strip())
        if (not re.search(r'假设|设定|给定|教学示例记录如下', intro)
                or re.search(r'计算(?:得到|结果)|算得|运行(?:结果|输出)|实际输出|程序输出', intro)):
            continue
        headers = [cell.strip().strip('*` ') for cell in line.strip().strip('|').split('|')]
        rows = []
        for row in lines[index + 2:]:
            if not row.strip().startswith('|'):
                break
            cells = [cell.strip().strip('*` ') for cell in row.strip().strip('|').split('|')]
            if len(cells) != len(headers):
                break
            rows.append(cells)
        for column, header in enumerate(headers):
            if (not re.fullmatch(metric, header, re.I) or len(rows) < 2
                    or not all(re.fullmatch(_RESULT_NUMBER, row[column]) for row in rows)):
                continue
            key = re.sub(r'\s+|集', '', header).casefold()
            supplied.setdefault(key, set()).add(tuple(Decimal(row[column].replace('−', '-')) for row in rows))
    return supplied


def _displayed_numeric_results(claim: str, *, question: str = '', draft: str = '') -> list[str]:
    """Locate displayed scalar/vector results, keeping input and metadata out.

    Shared by rounding and review completeness, so a paraphrased result does
    not gain different arithmetic rules. This is a bounded text extractor,
    not a general parser for equations, dimensions or arbitrary arrays.
    """
    expected = []
    text = re.sub(r'\\[\[\]() ]|[“”「」"`$]', '', claim)
    def affirmative(start):
        prefix = re.split(r'[，,；;。\n]', text[:start])[-1]
        return not re.search(r'不等于|并不表示|不代表|不是|并非|不能说|而非', prefix)
    vector = r'\[\s*(' + _RESULT_NUMBER + r'(?:\s*[,，、]\s*' + _RESULT_NUMBER + r')*)\s*\]'
    # A bare assignment may repeat a given vector without words like "input".
    # Compare the same variable and complete values with the actual question;
    # equal numbers under another name are not enough to exempt an output.
    question_text = re.sub(r'\\[\[\]() ]|[“”「」"`$]', '', question)
    metric_pattern = r'(?:训练|验证|测试)(?:集)?\s*(?:MSE|MAE|RMSE|损失|误差|准确率|精确率|召回率|分数)'
    series = _RESULT_NUMBER + r'(?:\s*[/、,，]\s*' + _RESULT_NUMBER + r')+'
    supplied_metrics = _given_metric_tables(draft)
    for supplied in re.finditer('(' + metric_pattern + r')\s*(?:依次|分别)?(?:为|是|[:：=])\s*(' + series + ')', question_text, re.I):
        key = re.sub(r'\s+|集', '', supplied[1]).casefold()
        supplied_metrics.setdefault(key, set()).add(tuple(Decimal(n.replace('−', '-'))
            for n in re.findall(_RESULT_NUMBER, supplied[2])))
    assignment_name = r'[A-Za-z_\u0370-\u03ff][A-Za-z_\u0370-\u03ff0-9]*'
    given_vectors = {(m.group(1), tuple(Decimal(n.replace('−', '-')) for n in re.findall(_RESULT_NUMBER, m.group(2))))
                     for m in re.finditer('(' + assignment_name + r')\s*=\s*' + vector, question_text)}
    for match in re.finditer(r'(?P<marker>' + _RESULT_MARKER + r'|得到|得|[:：=])\s*' + vector, text):
        label = re.split(r'[，,；;。\n]', text[:match.start()])[-1]
        if not affirmative(match.start()) or re.search(r'形状|维度|尺寸|版本|shape|version', label, re.I):
            continue
        context = label + match.group('marker')
        inputs = list(re.finditer(r'输入|原始|给定|已知|训练数据|样本数据|代入|(?:^|\s)(?:设|令|取)|\binput\b', context, re.I))
        outputs = list(re.finditer(r'输出|结果|得到|算得|更新后|变换后|得(?=\s*$)', context))
        if inputs and (not outputs or inputs[-1].start() > outputs[-1].start()):
            continue
        name = re.search('(' + assignment_name + r')\s*$', label)
        values = tuple(Decimal(n.replace('−', '-')) for n in re.findall(_RESULT_NUMBER, match.group(2)))
        if (match.group('marker') == '=' and name and not outputs
                and (name.group(1), values) in given_vectors):
            continue
        # "w=[...]时" states the condition of a calculation, not its output.
        # Explicit computed outputs remain checked even when reused below.
        if (match.group('marker') in {':', '：', '='}
                and re.match(r'\s*(?:时|的情况下)', text[match.end():])
                and not re.search(r'输出|结果|得到|算得|更新后|变换后', label)):
            continue
        expected.extend(re.findall(_RESULT_NUMBER, match.group(2)))
    for marker in re.finditer(_RESULT_MARKER, text):
        label = re.split(r'[，,；;。\n]', text[:marker.start()])[-1]
        sentence_label = re.split(r'[；;。\n]', text[:marker.start()])[-1]
        input_markers = list(re.finditer(r'给出|题给|给定|已知|已给|输入|练习条件', sentence_label))
        computed_markers = list(re.finditer(r'计算|算出|输出|结果|得到|更新后|变换后', sentence_label))
        metric = re.search('(' + metric_pattern + r')\s*$', label, re.I)
        if metric and not computed_markers:
            # Repeating the question's complete ordered metric series does
            # not require recalculating MSE from unavailable predictions.
            # A derived gap or explicitly computed output still needs work.
            named_value = r'(?:[A-Za-z]\s*[:：=]?\s*)?' + _RESULT_NUMBER
            repeated = re.match(r'\s*(' + named_value + r'(?:\s*[/、,，]\s*' + named_value + r')+)', text[marker.end():])
            if repeated:
                values = tuple(Decimal(n.replace('−', '-')) for n in re.findall(_RESULT_NUMBER, repeated[1]))
                key = re.sub(r'\s+|集', '', metric[1]).casefold()
                if values in supplied_metrics.get(key, set()):
                    continue
        supplied_enumeration = (input_markers
                                and (not computed_markers
                                     or input_markers[-1].start() > computed_markers[-1].start()))
        enum_input = (re.fullmatch(r'(?:依次|分别)(?:为|是|[:：])', marker.group())
                      and (supplied_enumeration or re.search(r'精确|严格|恰好|输入|原始|给定|训练数据|样本数据|形状|维度|尺寸|版本', label)))
        if (not affirmative(marker.start())
                or enum_input
                or re.search(r'精确|严格|恰好|输入|原始|给定|训练数据|样本数据|形状|维度|尺寸|版本', marker.group())):
            continue
        # A single output heading can introduce several numeric rows. Keep
        # reading those rows, but stop when prose, inputs or labels resume.
        # Unlabeled columns cannot safely be assumed to be iteration indices.
        numeric_row = _RESULT_NUMBER + r'(?:[ \t]+' + _RESULT_NUMBER + r')*'
        numeric_rows = re.match(
            r'\s*[:：]?\s*(' + numeric_row
            + r'(?:[ \t]*[；;\r\n]+[ \t]*' + numeric_row + r')+)'
            + r'[ \t]*(?=$|[。；;\r\n，,])', text[marker.end():])
        if numeric_rows:
            expected.extend(re.findall(_RESULT_NUMBER, numeric_rows.group(1)))
        output_text = re.split(r'[。；;\n]', text[marker.end():], maxsplit=1)[0]
        # A threshold after the result ("1.5, exceeds 1") is a condition,
        # not another computed output. Stop before its relational clause.
        clauses = re.split(r'[，,]', output_text)
        for index, clause in enumerate(clauses):
            if re.search(r'超过|大于|小于|不等于|等于|介于|至少|至多|不超过|不低于|范围|之间|给定|题给|已知|已给|输入', clause):
                output_text = ','.join(clauses[:index])
                break
        if not re.search(r'[()\[\]{}%％]', output_text):
            for part in re.split(r'[，,；;。\n]|和|及|与|或者|或|\bor\b', output_text):
                match = re.search(r'(?<![A-Za-z_\d.=+*/^−\-])(' + _RESULT_NUMBER
                                  + r'(?:\s*(?:、|\s)\s*' + _RESULT_NUMBER + r')*)\s*$', part)
                if match and not re.search(r'[=^*/]|第\s*$', part[:match.start()]):
                    expected.extend(re.findall(_RESULT_NUMBER, match.group(1)))
    return list(dict.fromkeys(expected))


def _table_result_literals(draft: str) -> set[str]:
    """Read displayed precision from numerical result columns in actual prose."""
    text = re.sub(r'```[\s\S]*?```', '', draft)
    result, columns = set(), []
    for line in text.splitlines():
        if not line.strip().startswith('|'):
            columns = []
            continue
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if not columns:
            columns = [i for i, cell in enumerate(cells)
                       if re.search(r'MSE|误差|残差|差的平方|平方差|均值|标准差|频率|输出|结果|\bloss\b|\bmean\b|\bstd\b', cell, re.I)
                       and not re.search(r'精确|严格|恰好|题给|给定|已知|输入', cell)]
            continue
        for index in columns:
            if index >= len(cells):
                continue
            # Numeric cells may contain a list of displayed squared residuals.
            cell = cells[index].replace('**', '').replace('−', '-')
            if re.fullmatch(r'[\d.eE+\-≈~\s,，、]+', cell):
                result.update(value for value in re.findall(_RESULT_NUMBER, cell)
                              if '.' in value or 'e' in value.lower())
    return result


def check_claim_calculations(candidate: dict, citations: list[dict], *, question: str = '', draft: str = '') -> list[dict]:
    """Check arithmetic separately from provenance and semantic entailment.

    A student's worked example need not contain the textbook's numbers. An
    evaluated expression verifies only that calculation, never its premises or
    whether the expression represents the problem correctly.
    """
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
    def numbers(text):
        return {Decimal(value) for value in re.findall(r'(?<![A-Za-z0-9_.])[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', text.replace('−', '-'))}
    cited = numbers('\n'.join(item['quote'] for item in citations))
    given = numbers(question)
    numeric_literal = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
    fraction_pattern = rf'({numeric_literal})\s*/\s*({numeric_literal})'
    approximate_literals = set()
    table_results = (_table_result_literals(draft)
                     if not re.search(r'精确|严格|恰好|(?<![A-Za-z_])\d\s*[^。；]*=\s*[-+]?\d', str(candidate.get('claim') or ''))
                     else set())
    listed_number = numeric_literal + r'(?![A-Za-z0-9_./])'
    # “approximately a, b, c” qualifies the whole numeric list, but stops
    # before another sentence/claim. Do not round every number in the answer.
    for match in re.finditer(
        r'(?:≈|≃|~|\\approx\s*|大?约(?:为|等于)?|近似(?:为|等于)?|approximately\s*|about\s*)\s*'
        + rf'({listed_number}(?:\s*(?:、|，|,|和|及|与|\band\b)\s*{listed_number})*)',
        str(candidate.get('claim') or '').replace('−', '-'), re.I,
    ):
        approximate_literals.update(re.findall(numeric_literal, match.group(1)))
    # Formatted program output may label every value, e.g. "输出约为：
    # degree=1 mse=0.039753; degree=3 mse=0.004253". The labels do not turn
    # explicitly approximate decimals into exact real-number assertions.
    # Stop at prose, so a later exact claim retains its own arithmetic rules.
    assignment = rf'[A-Za-z_][A-Za-z_0-9]*\s*=\s*({numeric_literal})(?![A-Za-z0-9_./])'
    for match in re.finditer(
        r'(?:输出|结果)\s*(?:约为|近似为)\s*[:：]?\s*'
        + rf'((?:{assignment}[\s,，;；]*)+)', str(candidate.get('claim') or ''),
    ):
        for value in re.findall(assignment, match.group(1)):
            if '.' in value or 'e' in value.lower():
                approximate_literals.add(value)
    output_places = set(re.findall(r'(?:保留|四舍五入到?)\s*(\d+)\s*位小数', question))
    claim_text = str(candidate.get('claim') or '')
    displayed_results = {Decimal(value.replace('−', '-')) for value in _displayed_numeric_results(claim_text, question=question, draft=draft)}
    # A displayed result is an exact string at the user's requested precision,
    # not an assertion that the underlying irrational value terminates there.
    # Use only an unambiguous output-format instruction, never arbitrary
    # tolerances or a model's invented precision for an unrelated claim.
    requested_output_places = (int(next(iter(output_places)))
        if len(output_places) == 1 and re.search(r'输出|打印|结果', question)
        and displayed_results
        and not re.search(r'精确(?:为|等于)|恰好等于|严格等于', claim_text) else None)

    def numeric_result(value):
        value = str(value).strip().replace('−', '-').replace('÷', '/')
        if len(value) > 500:
            raise ValueError('invalid_result')
        fraction = re.fullmatch(fraction_pattern, value)
        if fraction:
            numerator, denominator = map(Decimal, fraction.groups())
            if max(abs(numerator), abs(denominator)) > Decimal('1e30'):
                raise ValueError('invalid_result')
            return numerator / denominator
        return Decimal(value)

    # A fraction states one value, not its numerator and denominator as
    # separate results. Mask only its actual span, so "3/2 = 3" still states
    # an independent 3 and a wrong equality still reaches answer repair.
    # TeX permits either braced numeric arguments or single unbraced digits.
    # This deliberately does not interpret symbolic/nested TeX expressions.
    fraction_values = set()
    def replace_fraction(match):
        groups = match.groupdict()
        numerator = groups.get('numerator') or groups.get('numerator_digit')
        denominator = groups.get('denominator') or groups.get('denominator_digit')
        try:
            value = numeric_result(f'{numerator}/{denominator}')
            fraction_values.add(-value if groups.get('sign') == '-' else value)
        except (ArithmeticError, ValueError):
            pass
        return ' ' * len(match.group())
    numeric_text = claim_text.replace('−', '-')
    tex_fraction = (rf'(?P<sign>[+-]?)\\(?:dfrac|tfrac|frac)\s*'
                    rf'(?:\{{\s*(?P<numerator>{numeric_literal})\s*\}}|(?P<numerator_digit>\d))\s*'
                    rf'(?:\{{\s*(?P<denominator>{numeric_literal})\s*\}}|(?P<denominator_digit>\d))')
    numeric_text = re.sub(tex_fraction, replace_fraction, numeric_text)
    slash_fraction = (rf'(?<![A-Za-z0-9_./])(?P<numerator>{numeric_literal})\s*/\s*'
                      rf'(?P<denominator>{numeric_literal})(?![A-Za-z0-9_./])')
    numeric_text = re.sub(slash_fraction, replace_fraction, numeric_text)
    stated = numbers(numeric_text) | fraction_values
    results = []
    calculation_items = []
    for item in candidate.get('calculations', []) if isinstance(candidate.get('calculations'), list) else []:
        if not isinstance(item, dict):
            continue
        display = str(item.get('claimed_result') or '').strip().replace('−', '-')
        # A review may write a fraction and its rounded display in one field.
        # Check both, preserving the original claim's approximation rules;
        # a reviewer-added ≈ must not weaken an exact assertion in the answer.
        pair = re.fullmatch(rf'(?P<exact>{numeric_literal}(?:\s*/\s*{numeric_literal})?)?\s*'
                            rf'(?:≈|≃|~|约(?:为|等于)?)\s*(?P<rounded>{numeric_literal})', display)
        if pair:
            calculation_items.extend({**item, 'claimed_result': value, 'displayed_result': display}
                                     for value in (pair['exact'], pair['rounded']) if value)
        else:
            calculation_items.append(item)
    for item in calculation_items:
        expression = str(item.get('expression') or '')
        result = {'expression': expression, 'checked': False}
        if 'displayed_result' in item:
            result['displayedResult'] = item['displayed_result']
        try:
            # A symbolic identity needs the source/semantic review. It cannot be
            # accepted or rejected by a numeric calculator; calls/attributes
            # still remain invalid and are never executed.
            normalized = expression.replace('^', '**').replace('×', '*').replace('÷', '/').replace('−', '-')
            symbolic_trees = [ast.parse(value, mode='eval') for value in
                              (normalized, str(item.get('claimed_result', '')).replace('−', '-'))]
            symbolic_nodes = [node for tree in symbolic_trees for node in ast.walk(tree)]
            if (len(symbolic_nodes) <= 100 and any(isinstance(node, ast.Name) for node in symbolic_nodes)
                    and all(isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load,
                                              ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div,
                                              ast.Pow, ast.USub, ast.UAdd)) for node in symbolic_nodes)
                    and all(type(node.value) in {int, float} for node in symbolic_nodes if isinstance(node, ast.Constant))):
                result['reason'] = 'symbolic_requires_semantic_review'
                results.append(result)
                continue
            claimed = numeric_result(item.get('claimed_result'))
            if len(expression) > 500 or not claimed.is_finite():
                raise ValueError('invalid_result')
            # These are mathematical expressions, so ^ denotes exponentiation.
            # A few numeric functions are evaluated directly with Decimal;
            # Python calls, modules, attributes and generated code never run.
            tree = ast.parse(normalized, mode='eval')
            if len(list(ast.walk(tree))) > 100:
                raise ValueError('not_simple_arithmetic')
            operands = []
            def calculate(node):
                if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
                    number = Decimal(ast.get_source_segment(normalized, node))
                    if not number.is_finite() or abs(number) > Decimal('1e30'):
                        raise ValueError('invalid_operand')
                    operands.append(number)
                    return number
                if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
                    value = calculate(node.operand)
                    return -value if isinstance(node.op, ast.USub) else value
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
                    base, exponent = calculate(node.left), calculate(node.right)
                    if abs(exponent) > 10000:
                        raise ValueError('not_simple_power')
                    return base ** exponent
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
                    name = node.func.id
                    arities = {'ln': (1,), 'log': (1, 2), 'log10': (1,), 'log2': (1,), 'sqrt': (1,), 'exp': (1,), 'abs': (1,),
                               'min': range(1, 101), 'max': range(1, 101)}
                    if len(node.args) not in arities.get(name, ()):
                        raise ValueError('not_numeric_function')
                    values = [calculate(argument) for argument in node.args]
                    value = values[0]
                    if name in {'min', 'max'}:
                        return (min if name == 'min' else max)(values)
                    if name == 'abs':
                        return abs(value)
                    if name == 'sqrt':
                        return value.sqrt()
                    if name == 'exp':
                        if abs(value) > 100:
                            raise ValueError('exponential_outside_numeric_scope')
                        return value.exp()
                    if name == 'log10':
                        return value.log10()
                    if name == 'log2':
                        return value.ln() / Decimal(2).ln()
                    if name == 'log' and len(values) == 2:
                        return value.ln() / values[1].ln()
                    return value.ln()
                if isinstance(node, ast.BinOp) and type(node.op) in operations:
                    return operations[type(node.op)](calculate(node.left), calculate(node.right))
                raise ValueError('not_simple_arithmetic')
            actual = calculate(tree.body)
            if not actual.is_finite():
                raise ValueError('invalid_result')
            # Keep exact equalities strict; explicitly approximate values below
            # additionally use their own displayed precision.
            tolerance = max(Decimal('1e-9'), abs(actual) * Decimal('1e-6'))
            stated_result = str(item.get('claimed_result')).strip().replace('−', '-')
            approximate = stated_result in approximate_literals
            output_rounded = (requested_output_places is not None and re.fullmatch(numeric_literal, stated_result)
                and claimed.as_tuple().exponent == -requested_output_places and claimed in displayed_results)
            table_rounded = stated_result in table_results
            approximate = bool(approximate or output_rounded or table_rounded)
            if approximate:
                # A claim explicitly rounded to four decimals is allowed half
                # the last decimal place. Do not apply its precision to other
                # numbers in the sentence or silently weaken exact equalities.
                rounding_tolerance = Decimal('0.5').scaleb(claimed.as_tuple().exponent)
                tolerance = max(tolerance, rounding_tolerance)
            result.update(checked=True, calculated=str(actual), claimed=str(claimed),
                          agrees=abs(actual - claimed) <= tolerance,
                          resultMentioned=claimed in stated,
                          operandsCited=all(value in cited for value in operands),
                          operandsGiven=all(value in given for value in operands))
            # "The value is A, not B" denies B rather than asserting it.
            # Only handle an explicit local negation of this exact numeral;
            # broader negation and implications remain semantic review work.
            mentions = list(re.finditer(r'(?<![A-Za-z0-9_.])' + re.escape(stated_result)
                                       + r'(?![A-Za-z0-9_.])', str(candidate.get('claim') or '').replace('−', '-')))
            result['resultNegated'] = bool(mentions) and all(
                re.search(r'(?:不是|并非|不等于|而非)\s*$', str(candidate.get('claim') or '')[:match.start()])
                and not re.match(r'\s*(?:就是|便是|即是)', str(candidate.get('claim') or '')[match.end():])
                for match in mentions)
            result['claimConsistent'] = result['agrees'] != result['resultNegated']
            if approximate:
                result.update(approximate=True, tolerance=str(tolerance))
                if output_rounded:
                    result['roundingBasis'] = 'requested_output_precision'
                elif table_rounded:
                    result['roundingBasis'] = 'rendered_result_table'
        except (ValueError, SyntaxError, InvalidOperation, ArithmeticError, TypeError):
            result['reason'] = 'not_simple_arithmetic'
        results.append(result)
    return results


def check_review_calculations(candidate: dict, citations: list[dict], *, question: str = '') -> list[dict]:
    review = candidate.get('review') or {}
    text = ' '.join(str(value) for value in review.values()) if isinstance(review, dict) else str(review)
    checks = check_claim_calculations({'claim': text, 'calculations': candidate.get('revision_calculations')},
                                      citations, question=question)
    # Review prose is visible to learners too. Check its explicit numeric
    # equalities even when the model omits them from revision_calculations.
    # Leave symbolic steps, approximations and quoted/negated errors to the
    # semantic reviewer; never infer values for names such as J(2) or lambda.
    own_review = (str(review.get('verifier') or '') + '\n' + str(review.get('revision') or '')
                  if isinstance(review, dict) else text)
    own_review = re.sub(r'“[^”]*”|「[^」]*」|"[^"\n]*"|`[^`]*`', '', own_review)
    for clause in re.split(r'[，,；;。\n]', own_review):
        if re.search(r'错误|错式|不成立|不正确|不等|不能|并非|不是|原式|约|近似|舍入|取整|'
                     r'incorrect|wrong|not\b|approx|round', clause, re.I):
            continue
        for match in re.finditer(r"[A-Za-z_\u0370-\u03ff\u2070-\u209f\d.+−×÷·⋅⊙²³*/^(){}\\'′∇∂ \t=\-]+", clause):
            chain = match.group().strip()
            suffix = clause[match.end():]
            decimal_prefix = chain.endswith('...') or suffix.startswith('…')
            if chain.endswith('...'):
                chain = chain[:-3].rstrip()
            suffix = re.sub(r'^…+', '', suffix) if decimal_prefix else suffix
            if '=' not in chain or suffix.startswith(('%', '％')):
                continue
            parts = [part.strip() for part in chain.split('=')]
            for index, (left, right) in enumerate(zip(parts, parts[1:])):
                if not left or not right or not re.fullmatch(r'[\d.+−×÷*/^() \t\-]+', left + right):
                    continue
                # Evaluate each side separately using the same bounded numeric
                # calculator. This catches 0.5+0.5=1.5 in a longer equality.
                right_check = check_claim_calculations({'calculations': [
                    {'expression': right, 'claimed_result': '0'}]}, [], question=question)[0]
                if not right_check.get('checked'):
                    continue
                pair = check_claim_calculations({'claim': text, 'calculations': [
                    {'expression': left, 'claimed_result': right_check['calculated']}]}, citations,
                    question=question)[0]
                if pair.get('checked'):
                    pair.update(origin='review_text', equality=f'{left} = {right}', resultMentioned=True)
                    if (decimal_prefix and index == len(parts) - 2
                            and re.fullmatch(r'[+−-]?\d+\.\d+', right)):
                        # 1/3=0.333… states leading decimal digits, not the
                        # finite exact equality 1/3=0.333. Verify those digits;
                        # an incorrect prefix still reaches review repair.
                        prefix = Decimal(right.replace('−', '-'))
                        actual_prefix = Decimal(pair['calculated']).quantize(prefix, rounding=ROUND_DOWN)
                        pair.update(agrees=actual_prefix == prefix, claimConsistent=actual_prefix == prefix,
                                    representation='decimal_prefix', equality=f'{left} = {right}…')
                    if not any(item.get('expression') == pair['expression'] and item.get('claimed') == pair['claimed']
                               for item in checks):
                        checks.append(pair)
    return checks


def calculation_review_feedback(candidates: list[dict], materials: list[dict], *, question: str = '', draft: str | None = None) -> list[dict]:
    """Only request a second review for inconsistent or uncheckable corrections."""
    feedback = []
    for candidate in candidates:
        citations = verify_claim_quotes(candidate, materials)['citations']
        original = check_claim_calculations(candidate, citations, question=question, draft=draft or '')
        if draft is not None:
            # An incorrect value invented by the reviewer must repair the
            # review, not the teaching. Use the same numeric/TeX reader against
            # the actual candidate, not only the reviewer's paraphrased claim.
            draft_checks = check_claim_calculations({**candidate, 'claim': draft}, citations, question=question)
            unstated_errors = [check for check, actual in zip(original, draft_checks)
                               if check.get('checked') and check.get('resultMentioned')
                               and not check.get('claimConsistent') and not actual.get('resultMentioned')]
            if unstated_errors:
                feedback.append({'claim': candidate.get('claim'),
                    'unstatedErroneousResults': [check['claimed'] for check in unstated_errors],
                    'instruction': '审核声称正文包含这些错误数值，但当前正文没有写出。请按实际正文重新抽取主张；'
                    '不能把你为独立练习推算的答案或旧稿数值当成作者已给出的结果。'
                    '核算练习时把你的结果放在revision_calculations，并核对题目是否可解，不要求提前给学生答案。'})
        corrections = check_review_calculations(candidate, citations, question=question)
        missing_outputs = _unchecked_claimed_numeric_outputs(candidate, original, question=question, draft=draft or '')
        if missing_outputs:
            literal_checks = [check for check in original if check.get('checked')
                              and re.fullmatch(_RESULT_NUMBER, str(check.get('expression') or '').strip())
                              and Decimal(check['claimed']) in {
                                  Decimal(value.replace('−', '-')) for value in missing_outputs}]
            feedback.append({'claim': candidate.get('claim'), 'missingOutputCalculations': missing_outputs,
                             'literalResultsNotCalculations': [
                                 {'expression': check['expression'], 'claimed_result': check['claimed']}
                                 for check in literal_checks],
                             'instruction': '这条审核确认了数值输出，但下列原输出值还没有可执行的数值算式。'
                             '这表示核对依据未补齐，不表示原答案算错。请在这条主张的calculations中补齐对应算式，'
                             '从原题输入或明确推导的中间量计算，claimed_result保留原输出及显示精度；'
                             'literalResultsNotCalculations列出了仅复写结果的无效项，带正负号的常数仍只是结果，'
                             '不能原样再提交，也不能靠加括号或加零伪装验算。向量或矩阵的数值结果须逐分量展开实际运算，'
                             '把所用输入和中间量代入算式，保留取负、乘除及其先后顺序。'
                             '不要把另一条主张的计算当作本条已有验算。若不是算术结果，说明其实际依据，'
                             '不声称程序已执行或数值已经验算；不要为补审核记录改动正确答案。'})
        problems = [item for item in corrections
                    if item.get('reason') != 'symbolic_requires_semantic_review'
                    and (not item.get('checked') or not item['agrees'])]
        review = candidate.get('review') or {}
        if (candidate.get('support') in {'supported', 'partially_supported'}
                and candidate.get('needs_revision') is not True
                and (not isinstance(review, dict) or not review.get('revision'))):
            # A reviewer parroting the answer's wrong equality is not a new
            # correction. The known discrepancy already makes the answer
            # contradicted in _normalize_claims and must reach answer repair.
            problems = [item for item in problems if not review_repeats_answer_error(item, original)]
        # A wrong number actually stated in the answer is a content finding,
        # not a malformed review. _normalize_claims marks that claim contradicted
        # and passes the verified discrepancy to the existing answer revision.
        # Retry the reviewer only when its calculation targets an unstated value;
        # otherwise a reviewer insisting "supported" can block the very repair
        # that the independent calculator has already made possible.
        problems += [item for item in original if item.get('checked') and not item['agrees']
                     and not item['resultMentioned']]
        if problems:
            unquoted_results = [item for item in original if item.get('checked') and not item.get('resultMentioned')]
            feedback.append({'claim': candidate.get('claim'), 'calculationChecks': problems,
                             'instruction': '重新核对原结论和纠正意见。验算只证明算式结果，不证明前提、公式或来源支持；不要把纠正值冒充原结论声称值。'
                             + (' 这些结果没有在这条claim原句中出现：'
                                + '、'.join(str(item.get('claimed')) for item in unquoted_results)
                                + '。若是评注中的例子或纠正数值，将算式移到revision_calculations，并在review说明是否为近似值；'
                                  '不要把别条主张的数值放在这里，也不要把近似值伪称精确等式。'
                                if unquoted_results else '')})
    return feedback


def quotation_review_feedback(candidates: list[dict], materials: list[dict]) -> list[dict]:
    """Repair an incomplete reviewer citation before changing valid teaching.

    No quotation is inferred or silently removed here. The same bounded review
    retry must supply actual evidence or explicitly distinguish a derivation
    from source support. Unresolved evidence remains a failed review.
    """
    feedback = []
    for candidate in candidates:
        if candidate.get('support') not in {'supported', 'partially_supported'} or candidate.get('needs_revision') is not False:
            continue
        if not (candidate.get('source_ref_ids') or candidate.get('sourceRefIds')
                or candidate.get('quote') or candidate.get('citations')):
            continue
        quotation = verify_claim_quotes(candidate, materials)
        if not quotation['verified']:
            feedback.append({'claim': candidate.get('claim'), 'citationFailures': quotation['failures'],
                'instruction': '这条审核声称有来源支持，但所列引文不完整或没有匹配本次原文。'
                '请重新检查审核依据：有直接支持时从所给来源复制连续原句，保留原句中的英文术语、括号、强调标记和链接；'
                '不要把概括、翻译或删去句中词语后的文字放进quote。解释支持关系写在support_reason。只有公式依据时说明部分支持，'
                '题设数值的推导另用calculations核对；确实没有直接出处但推导正确时明确标为无直接来源支持，'
                '不挂无关引用。不要为补审核字段改写正确答案，也不能通过删除引用掩盖原答案虚构来源或内容错误；'
                '原答案确实有错时仍须指出原句和修订原因。'})
    return feedback


def review_repeats_answer_error(check: dict, originals: list[dict]) -> bool:
    """An explicit review equality repeats an independently found answer error."""
    if check.get('origin') != 'review_text' or not check.get('checked') or check.get('agrees'):
        return False
    return any(item.get('checked') and item.get('resultMentioned') and not item.get('resultNegated')
               and not item.get('agrees') and Decimal(item['claimed']) == Decimal(check['claimed'])
               and Decimal(item['calculated']) == Decimal(check['calculated']) for item in originals)


def _unchecked_claimed_numeric_outputs(candidate: dict, checks: list[dict], *, question: str = '', draft: str = '') -> list[str]:
    """Require arithmetic behind approval of explicit numeric output.

    This is deliberately about concrete printed values, not every numeral in
    prose. Shape labels, versions, symbolic formulae and quoted source facts
    do not become calculation requirements. It does not prove that the model
    extracted every result, chose the right formula or executed the program.
    """
    if not str(candidate.get('basis') or '').startswith('worked_example'):
        return []
    # Support describes textbook provenance, not arithmetic. A correct
    # worked example can lack a matching textbook number and still require
    # calculations. In particular "材料未给出" must not waive this check.
    if (candidate.get('support') == 'contradicted' or candidate.get('needs_revision') is True
            or (candidate.get('support') == 'unsupported' and candidate.get('needs_revision') is not False)):
        return []
    expected = _displayed_numeric_results(str(candidate.get('claim') or ''), question=question, draft=draft)
    covered = set()
    for check in checks:
        if not check.get('checked') or not check.get('resultMentioned'):
            continue
        # Returning the displayed literal itself does not independently check
        # it. More substantive formula/operand fidelity remains semantic work.
        if re.fullmatch(_RESULT_NUMBER, str(check.get('expression') or '').strip()):
            continue
        covered.add(Decimal(check['claimed']))
    return [value for value in expected if Decimal(value.replace('−', '-')) not in covered]
