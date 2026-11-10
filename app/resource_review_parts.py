"""Bound the work of an exhausted reviewer without truncating its evidence."""
from __future__ import annotations

import json
import re
from typing import Any

from app.claim_evidence import check_review_calculations


CONDITION_EQUIVALENCE_GUIDANCE = (
    "先独立确认学生要求学习或实现的目标量、定义和操作，再核草稿是否完成同一任务。"
    "代码与其输出彼此一致仍可能算错对象；把实现逐项对应定义中的运算、权重、分母及更新顺序，"
    "不能把草稿自行选择的公式冒充题设，或以worked_example为由放过偏离目标的计算。"
    "题设与教材对同一个字母采用不同含义时，先按含义换名并保持题设数值对应；"
    "不能仅因字母相同，就把题设给定的数值转赋给教材中含义不同的参数、再列另一套答案。"
    "判断条件对错前，先在相同定义域和量词下检查移项、代入、恒等变换是否等价；"
    "不能仅因更偏好另一种写法就要求修订正确条件。约分或除法须保留零点和定义域限制，"
    "核对退化、化简、约去或缩放不变的说法时，检查其实际适用范围，尤其是零分母；"
    "不能只在审核说明里默默补上正文缺失的必要前提，然后把原来的普遍结论判为正确。"
    "先读取原题和正文已有范围：已明确的正值/非零前提可沿用，不要求每句重复；"
    "显式工程约定与原式的计算结果分开，合法的约定不能因原式在该处未定义而被误拒。"
    "比较均值、比例或总量时固定同一对象集合，不得把全体样本换成正权重子集、"
    "把全部类别换成某类等方式证明原结论。区分给定数据上的数值相等与对任意输入恒等；"
    "numeric_comparison条目须把原句的大于/小于/增加/减少对应到实际比较量；"
    "区分带符号数值、绝对值与负梯度方向，不能在判断时偷偷将作者写的数值比较改成绝对值比较。"
    "‘绝对值更大’等已明确说明的量按原说明核算；引用后明确否定的错误比较不是作者采纳的结论。"
    "个别输入下可能偶然相等，不能据此推出权重或参数的必要条件。"
    "补缺失前提时保留原句的充分关系，不擅自升级为充要条件；"
    "学生问“何时”也不意味着必须把一个正确的充分条件判错并新增无关分类。"
    "单点数值相等不能证明恒等。收敛、发散和稳定性要区分给定初值与所有初值，"
    "检查固定点、零误差和退化参数等例外；一般不稳定不等于每个初值都发散。"
    "非负与单调不减是不同性质；讨论累计、平滑或衰减时，比较相邻状态及更新增量，不能只看新加入项的符号。"
    "讲到乘性更新的收缩或放大时，区分因子符号与绝对值，并区分单独的正则项和还含其他梯度项的完整更新；"
    "正系数不自动意味着范数缩小，单独衰减也不保证整步参数范数下降。"
    "一般性的抑制大参数、改善泛化等作用说明不是逐步必然下降的断言，不能据此要求删除合理概括。"
    "区分必须修正的教学错误与可选的措辞润色。原句已经成立、只是你更喜欢另一种表达时，"
    "将条件判断标valid、needs_revision设false；不能一边承认原句成立、一边因可能的另一种读法要求整稿返工。"
    "例如‘判断是否一定下降，需要同时考虑步长和梯度’是在说明需要检查的因素，"
    "不是断言这些因素满足某个充分条件就必然下降。实际歧义会改变答案、概念或操作时仍应指出并修正。"
    "‘只增不减/不会减小’允许相邻值相等；不变不是其反例。判断变化时始终比较同一个量的前后值，"
    "不能将相对于上一状态的变化偷换为相对于衰减后状态的变化；原文已有序列时先检查各对相邻值。"
    "program_output条目是实际展示的输出块，须逐个对应代码、输入和显示精度；"
    "后文补上正确数字不代表前面的错误输出已被替换。"
    "numerical_basis条目来自数值核验未计算的范围，computation_note是未计算原因，不是正确性结论。"
    "若未计算原因指出对象或接口有歧义，逐项解析正文实际指向的对象、预处理、接口和容差，"
    "不能只以‘按参考实现’或‘请求给过这个数’判valid；必须解释原句如何排除该歧义。"
    "尤其LinearRegression(fit_intercept=True)对稠密特征中心化，model.rank_属于该内部求解；"
    "显式加常数列的增广矩阵、原始特征矩阵和中心化矩阵各有自己的秩。"
    "拟合器tol也不能称作np.linalg.lstsq(rcond=None)的默认截断。正文混写这些对象或接口就是知识错误，"
    "即使其中一个数与参考实现输出相同也不能通过；局部修法应明确对象与接口，不强换一个数。"
    "逐项判断它是合法给定条件、非数值说明，还是作者输出的对象/算法/必要条件不清。"
    "前两类按原上下文判valid；后一类核清实际接口、矩阵、参数与依据，给可执行的局部修正。"
    "不能把未计算当作通过，也不因题给数据无需重算而拒绝正确材料。"
    "将疑点落实为原句实际遗漏的条件或可核对反例，不因使用符号表达就自动接受或拒绝。"
    "task_conditions条目是题目或表格声明条件未给出的地方：先以学习者当前可见的题设完成所要求的判断，"
    "逐项指出依据。未列出预处理范围不能自动补成只在训练行拟合；未列出的数据不能推定存在。"
    "若题目就是要求辨认信息不足，且核对答案也保留该结论，则成立；若要求唯一选择却缺少必要条件，"
    "补齐具体题设后再核对，不能默默补前提或把题目改成无需完成原任务。"
    "模型公平比较须使用相同验证样本与评价口径，各自的数据相关预处理只在训练部分拟合；"
    "不同模型可以使用不同的合法预处理流程，不能把‘所有候选必须采用同一预处理方法’当成公平比较的必要条件。"
    "信息泄漏使评价依据失去隔离，但不保证某个数据集上的误差一定降低；如无正则含截距线性回归可能对可逆仿射标准化保持预测不变。"
    "未给具体算法与重算依据时，把全量标准化写成必然降低MSE或重做后分数必降是知识结论过强，须按风险和所给条件纠正。"
    "实际修改建议须保留用户给定的题设和本次必须完成的学习目标；"
    "不得以删除仍需完成的计算、改变已给定的数据或分布来让错误结论成立。"
    "反例或假设性讨论须与原题的修复方案区分；若题设自身矛盾，明确指出冲突，不偷偷换题。"
    "来源也可能有笔误：逐字引文证明出处，不自动证明专业结论正确。"
    "source_scope条目是草稿对当前材料范围的判断；逐一检查本次实际可见材料，"
    "不能照搬旧稿关于‘材料未展示公式’的说明，也不能从当前摘录缺失推断整门课程没有。"
    "材料确实未提供时保留准确的范围说明；若已经给出，引用实际原句并纠正缺失说法。"
    "同一资料的定义或递推式与后文结论冲突时，按原定义独立推导或构造反例，区分原文表述与勘误。"
    "资料没有明确给出第二种定义时，不能虚构‘另一种口径’来维护算错的原句；"
    "也不能仅因正确勘误与原文不同就要求改回错误说法。"
    "修订只补必要的条件和解释，避免添加题设范围之外的新断言；确需讨论边界时，须分别代入边界值、零项和初值检查。"
)


def conditional_teaching_claims(candidates: list[dict[str, Any]], scope: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Locate conditional prose for the existing reviewer; never judge by keyword.

    Full candidate content remains in the request so negation, worked examples,
    and sufficient conditions can be checked in their actual context.
    """
    claims = []
    terms = re.compile(r'必要|充分|充要|只有|只要|才能|才会|才可|必然|一定|始终|总是|单调|收缩|缩小|只增不减|只减不增|非递增|非递减|(?:不会|不能|不再|只能|只会)(?:减小|减少|下降|降低|增大|增加|上升|提高)|不可省略|不能省(?:略)?|不可缺少|缺一不可|必须满足|必须保持|(?:所需|需要的)(?:条件|假设)|前提条件|等价|恒等|收敛|发散|need(?:s)? to|necessary|sufficient|always|equivalent|converg|diverg|monotoni|non.?increas|non.?decreas|(?:never|cannot|can.?t|won.?t|will not)\s+(?:increase|decrease|grow|shrink)', re.I)
    excluded = {'code', 'starterCode', 'options', 'sourceRefIds', 'sourceRefs', 'semanticContext',
                'profileAdaptation', 'schemaVersion', 'id', 'language', 'source_ref_ids',
                'nodeId', 'parentNodeId', 'rootNodeId'}
    for index, candidate in enumerate(candidates):
        if scope and scope.get('stage') == 'section' and scope.get('candidate_index') != index:
            continue
        raw = candidate.get('content') or ''
        try:
            body = json.loads(raw)
        except (TypeError, ValueError):
            body = raw

        def visit(value, path):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key not in excluded:
                        visit(child, f'{path}.{key}')
            elif isinstance(value, list):
                for position, child in enumerate(value):
                    visit(child, f'{path}[{position}]')
            elif isinstance(value, str):
                if scope and scope.get('stage') == 'section' and not any(
                    path == prefix or path.startswith(prefix + '.') or path.startswith(prefix + '[')
                    for prefix in scope.get('paths', [])
                ):
                    return
                # Declared output blocks are part of the teaching content.
                # Include every one so a later correction cannot hide an old
                # wrong block that still looks like the program's actual output.
                for output_index, match in enumerate(re.finditer(
                        r'```(?:text|plaintext|output|stdout)\s*\n(.*?)```', value, re.S | re.I)):
                    preceding = value[:match.start()].rsplit('```', 1)[-1][-200:]
                    if re.search(r'输出|运行结果|output|stdout', preceding, re.I):
                        claims.append({'id': f"{candidate.get('version_id') or index}:{path}:output:{output_index}",
                                       'resourceType': candidate['type'], 'path': path,
                                       'kind': 'program_output', 'quote': match.group(0)})
                prose = re.sub(r'```[^\n]*\n.*?```', '', value, flags=re.S)
                for position, line in enumerate(re.split(r'(?<=[。！？])|\n', prose)):
                    quote = line.strip()
                    reductions = r'退化为|化简为|化为|约去|保持不变|的条件是|(?:缩放|放大|缩小)不影响|reduces? to|invariant'
                    source_scope = re.search(
                        r'(?:材料|资料|摘录|原文|教材|课文)[^。！？\n]{0,40}?'
                        r'(?:没有|并未|未|不曾)\s*(?:完整)?\s*(?:给出|展示|提供|包含|写出|提及|说明|覆盖|证明)', quote)
                    numeric_comparison = len(re.findall(r'[−+-]?\d+(?:\.\d+)?', quote)) >= 2 and re.search(
                        r'大于|小于|多了|少了|增加|减少|增大|减小|上升|下降|greater than|less than|increas|decreas', quote, re.I)
                    task_conditions = re.search(r'(?:未|没有|没)(?:列出|说明|给出|提供|注明|明确)[^。！？\n]{0,20}(?:条件|范围|数据|参数|说明)|条件不详|按常规处理', quote)
                    # A prompt asking the learner to refute a proposition does
                    # not assert that proposition. The ordinary task review
                    # still checks the question and its answer.
                    if quote.rstrip().endswith(('?', '？')):
                        continue
                    if terms.search(quote) or re.search(reductions, quote, re.I) or source_scope or numeric_comparison or task_conditions:
                        located = {'id': f"{candidate.get('version_id') or index}:{path}:{position}", 'resourceType': candidate['type'],
                                   'path': path, 'quote': quote}
                        if task_conditions:
                            located['kind'] = 'task_conditions'
                        elif source_scope:
                            located['kind'] = 'source_scope'
                        elif numeric_comparison:
                            located['kind'] = 'numeric_comparison'
                        claims.append(located)

        visit(body, 'content')
        # A numeric extractor can correctly decline an ambiguous computation.
        # That ambiguity still needs a recorded teaching verdict; otherwise a
        # successful computation of the other values hides the unresolved claim.
        numerical = (candidate.get('runtime_verification') or {}).get('numerical') or {}
        for position, item in enumerate((numerical.get('plan') or {}).get('not_computed', [])):
            path, quote = item['path'], item['quote']
            if scope and scope.get('stage') == 'section' and not any(
                path == prefix or path.startswith(prefix + '.') or path.startswith(prefix + '[')
                for prefix in scope.get('paths', [])
            ):
                continue
            existing = next((claim for claim in claims
                if claim['resourceType'] == candidate['type'] and claim['path'] == path
                and claim['quote'] == quote), None)
            if existing is not None:
                existing['computation_note'] = item['reason']
                continue
            claims.append({'id': f"{candidate.get('version_id') or index}:{path}:uncomputed:{position}",
                'resourceType': candidate['type'], 'path': path, 'quote': quote,
                'kind': 'numerical_basis', 'computation_note': item['reason']})
    return claims


def validate_condition_review(result: dict[str, Any], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every selected sentence needs one verdict, including on resumed reviews."""
    checks = result.get('conditionReview', [])
    expected = {claim['id'] for claim in claims}
    if (not isinstance(checks, list)
            or any(not isinstance(check, dict) or not isinstance(check.get('claimId'), str) for check in checks)
            or len(checks) != len(expected)
            or {check['claimId'] for check in checks} != expected):
        raise ValueError('部分条件尚未对应到本次讲解，请重新核对。')
    return checks


def _same_located_repair(item: dict[str, Any], claim: dict[str, Any], fix: str) -> bool:
    """Match a prose finding to its condition check without merging other questions."""
    location = str(item.get('location') or '')
    path = str(claim.get('path') or '')
    # Reviewers often append a human-readable section label to the exact path.
    located_path = re.match(r'content(?:\.[A-Za-z_][A-Za-z_0-9]*|\[\d+\])+', location)
    same_location = bool(path and (location == path or (located_path and located_path[0] == path)))
    question_path = re.search(r'content\.(?:question_details|questions)\[(\d+)\]', path)
    question_label = re.search(r'第\s*(\d+)\s*题', location)
    if question_path and question_label:
        same_location = int(question_path[1]) + 1 == int(question_label[1])
    if not same_location:
        return False
    normalize = lambda value: re.sub(r'[\s，。；：、,.!?！？;:“”"`]', '', value)
    # A shortened quotation can identify the same sentence without identical
    # repair wording. Require ordered literal fragments, not semantic similarity.
    quote = normalize(str(claim.get('quote') or ''))
    for excerpt in re.findall(r'“([^”]+)”|"([^"]+)"', str(item.get('issue') or '') + str(item.get('evidence') or '')):
        fragments = [normalize(value) for value in re.split(r'…+|\.{3,}', next(value for value in excerpt if value))]
        fragments = [value for value in fragments if value]
        if sum(map(len, fragments)) < 12:
            continue
        position = 0
        for fragment in fragments:
            found = quote.find(fragment, position)
            if found < 0:
                break
            position = found + len(fragment)
        else:
            return True
    prior_fix, current_fix = normalize(str(item.get('fix') or '')), normalize(fix)
    if min(len(prior_fix), len(current_fix)) >= 12 and (prior_fix in current_fix or current_fix in prior_fix):
        return True
    # A quoted replacement is more specific than generic "check the formula"
    # advice. Retain both condition records even when they have one repair.
    replacements = [normalize(value) for value in re.findall(r'“([^”]+)”', fix)]
    return any(len(value) >= 8 and value in prior_fix for value in replacements)


def _condition_repair_finding(result, claim):
    """An identified missing premise is actionable without inventing a verdict."""
    quote = re.sub(r'\s+', '', claim['quote'])
    for finding in result.get('findings', []):
        if (not isinstance(finding, dict) or finding.get('resourceType') != claim['resourceType']
                or not str(finding.get('issue') or '').strip() or not str(finding.get('fix') or '').strip()):
            continue
        evidence = str(finding.get('evidence') or '')
        if quote and quote in re.sub(r'\s+', '', evidence):
            return finding
        # A review can quote the missing-condition cell rather than repeat the
        # entire Markdown table row. Require both the field and a verbatim,
        # informative fragment so unrelated findings do not suppress uncertainty.
        if claim.get('path') and claim['path'] in str(finding.get('location') or ''):
            fragments = re.findall(r'“([^”]+)”|"([^"\n]+)"|「([^」]+)」', evidence)
            if any(len(fragment) >= 8 and fragment in quote
                   for group in fragments for part in group
                   if (fragment := re.sub(r'\s+', '', part))):
                return finding
    return None


def apply_condition_review(result: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any]:
    """A detailed adverse judgement cannot coexist with an approved summary."""
    by_id = {claim['id']: claim for claim in claims}
    for check in validate_condition_review(result, claims):
        claim = by_id.get(check.get('claimId'))
        if claim is None or check.get('status') not in {'valid', 'overstated', 'incorrect', 'uncertain'}:
            raise ValueError('条件核对没有对应到本次讲解。')
        if check['status'] == 'uncertain':
            finding = _condition_repair_finding(result, claim)
            if finding is None:
                raise ValueError('部分结论的适用条件尚未确认，可以重新核对；原稿已保留。')
            # Keep the uncertainty and send the concrete missing-condition
            # finding through normal evidence adjudication before any repair.
            related = finding.setdefault('conditionClaimIds', [])
            if claim['id'] not in related:
                related.append(claim['id'])
            result['approved'] = False
            rejected = result.setdefault('rejectedTypes', [])
            if claim['resourceType'] not in rejected:
                rejected.append(claim['resourceType'])
            continue
        if check['status'] not in {'overstated', 'incorrect'}:
            continue
        reason, fix = str(check.get('reason') or '').strip(), str(check.get('fix') or '').strip()
        if not reason or not fix:
            raise ValueError('条件核对尚未说明具体问题和修正办法。')
        finding = {'resourceType': claim['resourceType'], 'location': claim['path'],
                   'issue': f"{claim['quote']}：{reason}", 'fix': fix}
        findings = result.setdefault('findings', [])
        quote = re.sub(r'\s+', '', claim['quote'])
        # A condition verdict and a finding often quote the exact same defect.
        # Keep one actionable issue while retaining every condition verdict.
        represented = next((item for item in findings if isinstance(item, dict)
            and item.get('resourceType') == claim['resourceType']
            and ((quote and quote in re.sub(r'\s+', '', str(item.get('issue') or '') + str(item.get('evidence') or '')))
                 or _same_located_repair(item, claim, fix))), None)
        if represented is not None:
            related = represented.setdefault('conditionClaimIds', [])
            if claim['id'] not in related:
                related.append(claim['id'])
        if finding not in findings and represented is None:
            findings.append(finding)
        rejected = result.setdefault('rejectedTypes', [])
        if claim['resourceType'] not in rejected:
            rejected.append(claim['resourceType'])
        result['approved'] = False
        result['summary'] = '部分结论的适用条件还需调整，具体位置与修改建议已列出。'
    return result


def resource_review_condition_feedback(result: dict[str, Any], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Unresolved checks need clarification, not an invented error or approval."""
    by_id = {claim['id']: claim for claim in claims}
    return [{'claimId': check['claimId'], 'quote': by_id[check['claimId']]['quote'],
             'reason': str(check.get('reason') or ''),
             'instruction': '结合原稿上下文、所选材料及必要推导，核实这条结论。正确则保留valid；确有错误才给出反例和修订办法；仍缺依据则保留uncertain并说明缺少什么。'}
            for check in validate_condition_review(result, claims) if check.get('status') == 'uncertain'
            and _condition_repair_finding(result, by_id[check['claimId']]) is None]


def resource_review_calculation_feedback(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Check the reviewer's explicit arithmetic, not arbitrary learner code.

    Reuse the question-answer checker: quoted/negated errors, rounding and
    symbolic derivations remain semantic judgements. A correct arithmetic
    result alone does not establish the formula's relevance or assumptions.
    """
    sections = [('summary', {'verifier': result.get('summary') or ''})]
    for field, keys in [('findings', ('issue', 'fix')), ('conditionReview', ('reason', 'fix')),
                        ('teachingReview', ('evidence',))]:
        for index, item in enumerate(result.get(field) or []):
            if isinstance(item, dict):
                sections.append((f'{field}[{index}]', {'verifier': '\n'.join(str(item.get(k) or '') for k in keys)}))
    feedback = []
    for location, review in sections:
        checks = check_review_calculations({'review': review}, [])
        errors = [item for item in checks if item.get('checked') and not item.get('agrees')]
        if errors:
            feedback.append({'location': location, 'calculationChecks': errors,
                'instruction': '这处审核意见的算术结果不一致。请核对原稿与修改建议，保留正确内容；算式结果不代替公式、条件和来源判断。'})
    return feedback


def document_review_scopes(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each stored section is checked once; full candidates remain available.

    This splits review effort, not the provider's input context. An indivisible
    large section or an input beyond the provider limit still reports failure.
    """
    scopes: list[dict[str, Any]] = []
    for candidate_index, candidate in enumerate(candidates):
        try:
            content = json.loads(candidate.get("content") or "")
        except (ValueError, TypeError):
            content = None
        if candidate.get("type") not in {
            "handout", "deck", "code_sandbox", "interactive_model", "training_task",
        } or not isinstance(content, dict):
            scopes.append({"candidate_index": candidate_index, "paths": ["content"]})
            continue
        groups: list[list[str]] = []
        paths: list[str] = []
        supporting_paths: list[str] = []
        size = 0
        for key, value in content.items():
            if key == 'semanticContext':
                # This is the frozen generation provenance, not a lesson section.
                # It remains in the complete candidate sent with every request;
                # the shared course/profile/source contract is checked globally.
                # Do not schedule an extra local teaching review for its copy.
                continue
            if key in {'schemaVersion', 'title', 'outline', 'profileAdaptation', 'estimatedMinutes'} or value in ([], {}):
                # These fields organize the same lesson. Keep them in scope,
                # together with actual teaching, rather than asking a model to
                # re-review a long document just for twelve outline entries.
                supporting_paths.append(f"content.{key}")
                continue
            # Keep a complete code block/question/section together. Empty lists
            # and learner-visible adaptation remain part of the review.
            rows = list(enumerate(value)) if isinstance(value, list) and value else [(None, value)]
            for index, row in rows:
                length = len(json.dumps(row, ensure_ascii=False))
                if paths and size + length > 6000:
                    groups.append(paths)
                    paths, size = [], 0
                paths.append(f"content.{key}" + (f"[{index}]" if index is not None else ""))
                size += length
        if paths:
            groups.append(paths)
        if supporting_paths:
            if groups:
                groups[0] = supporting_paths + groups[0]
            else:
                groups.append(supporting_paths)
        scopes.extend({"candidate_index": candidate_index, "paths": group} for group in groups)
    return scopes if len(scopes) > 1 else []


def split_review_scope(candidates: list[dict[str, Any]], scope: dict[str, Any]) -> list[dict[str, Any]]:
    """Split exhausted review work at field boundaries, keeping full input.

    This never slices a prose/code string or drops the tail of a document.
    A single indivisible value still reports the provider limit.
    """
    if scope.get('stage') == 'consistency':
        checks = scope.get('checks') or [
            '目标覆盖、教学顺序、提示和独立任务是否衔接',
            '实际绑定版本、代码输出、实验数据、符号与引用是否对应',
            '题目、答案、解析、评分和完成条件是否一致',
            '先修、工具、时间负担与当前生效的学习要求是否匹配',
        ]
        if len(checks) < 2:
            return []
        middle = len(checks) // 2
        return [{**scope, 'checks': part} for part in (checks[:middle], checks[middle:])]
    if scope.get('stage') != 'section':
        return []
    paths = list(scope.get('paths') or [])
    if not paths:
        return []
    if len(paths) == 1:
        path = paths[0]
        try:
            value = json.loads(candidates[scope.get('candidate_index', 0)]['content'])
            for key, index in re.findall(r'\.([^\.\[\]]+)|\[(\d+)\]', path[len('content'):]):
                value = value[key] if key else value[int(index)]
            if isinstance(value, dict):
                paths = [path + '.' + key for key in value if key != 'semanticContext']
            elif isinstance(value, list):
                paths = [f'{path}[{index}]' for index in range(len(value))]
            else:
                return []
        except (ValueError, TypeError, KeyError, IndexError):
            return []
        # Descend through a single wrapper rather than retrying unchanged work.
        if len(paths) == 1 and paths[0] != path:
            return split_review_scope(candidates, {**scope, 'paths': paths})
    if len(paths) < 2:
        return []
    middle = len(paths) // 2
    return [{**scope, 'paths': part} for part in (paths[:middle], paths[middle:])]


def combine_document_reviews(results: list[dict[str, Any]]) -> dict[str, Any]:
    rejected = list(dict.fromkeys(kind for result in results for kind in result.get("rejectedTypes") or []))
    approved = all(result.get("approved") is True for result in results) and not rejected
    findings, teaching, conditions = [], [], {}
    severity = {'valid': 0, 'uncertain': 1, 'overstated': 2, 'incorrect': 3}
    for result in results:
        for field, target in [("findings", findings), ("teachingReview", teaching)]:
            for item in result.get(field) or []:
                if item not in target:
                    target.append(item)
        for item in result.get('conditionReview') or []:
            previous = conditions.get(item['claimId'])
            # A section and the final consistency check can cover the same
            # sentence. Keep one summary verdict; all detail stays below.
            if previous is None or severity[item['status']] > severity[previous['status']]:
                conditions[item['claimId']] = item
    return {"approved": approved, "rejectedTypes": rejected, "findings": findings,
            "teachingReview": teaching,
            "conditionReview": list(conditions.values()),
            "summary": "各段内容及前后关系已核对。" if approved else "；".join(
                str(result.get("summary") or "部分内容仍需调整。") for result in results if not result.get("approved")),
            "sectionReviews": results}
