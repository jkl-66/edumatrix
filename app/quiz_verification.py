"""CoVe for existing quizzes: solve without answer keys, then adjudicate.

Question-derived verification plans replace a second planner model. Independent
solvers see only each public question and canonical source passages; the existing
resource reviewer sees both answers afterward and owns the final verdict.
"""
from __future__ import annotations

import asyncio
from copy import copy
import hashlib
import json
from time import perf_counter

from app.claim_evidence import check_claim_calculations, verify_claim_quotes
from app.learner_output import LEARNER_FEEDBACK_INSTRUCTION
from llm_client import parse_json_object


SOLVER_SYSTEM = (
    LEARNER_FEEDBACK_INSTRUCTION
    + '你独立解答一道测验，只接收题目、选项与必要资料，没有出题者答案。'
    '先按题设独立求解，再回答；只输出JSON：answer（单选填选项ID，多选填ID数组，判断填布尔值，填空填答案数组，简答填完整参考答案）、justification（简短可核查依据）、'
    'calculations（expression与claimed_result）、citations（source_ref_id与逐字quote）、assumptions。'
    '计算用代入数值的四则、幂、sqrt/ln/log/exp/abs/min/max；不填符号式或复写常数。'
    '只列解题需要的计算与原文依据，不输出私有推理。若题干不完备或答案不唯一，在answer填uncertain并说明。'
    '题设给定的比较指标是输入，不要求凭空重算；选择最小/最大项时核对指标及对应行。'
)


def public_question(question):
    options = question.get('options') or []
    return {'prompt': str(question.get('prompt') or ''),
            'type': question.get('question_type') or question.get('type') or 'single_choice',
            'options': [{'id': str(option.get('id') or option.get('key') or chr(65 + index)),
                         'text': str(option.get('text') or option.get('label') or option.get('content') or '')}
                        if isinstance(option, dict) else {'id': chr(65 + index), 'text': str(option)}
                        for index, option in enumerate(options)]}


def source_materials(sources):
    materials = []
    for source in sources:
        for passage in source.get('passages') or [source]:
            quote = str(passage.get('quote') or passage.get('text') or passage.get('content') or '')
            if quote:
                materials.append({'source_ref_id': source['source_ref_id'], 'available': True,
                    'title': str(source.get('title') or ''), 'quote': quote,
                    'char_start': passage.get('char_start'), 'char_end': passage.get('char_end')})
    return materials


def _answer(question):
    value = question.get('answer_key', question.get('answer'))
    if isinstance(value, dict):
        value = next((value[key] for key in ('choice', 'choices', 'value', 'blanks', 'reference_answer',
                     'correct_option', 'correct_options', 'answer') if key in value), None)
    return value


def _normalized_answer(answer, kind):
    if isinstance(answer, str) and answer.strip().lower() == 'uncertain':
        return 'uncertain'
    if kind == 'multiple_choice':
        return sorted(str(item).strip().upper() for item in (answer if isinstance(answer, list) else str(answer).replace(',', ' ').split()))
    if kind == 'true_false':
        if isinstance(answer, bool):
            return answer
        value = str(answer).strip().lower()
        return True if value in {'true', '正确', '对'} else False if value in {'false', '错误', '错'} else answer
    return answer


async def independently_solve_quizzes(backend, candidates, sources, *, completed=None, save=None, slots=None):
    cache = completed if completed is not None else {}
    slots = slots if slots is not None else asyncio.Semaphore(2)
    materials = source_materials(sources)
    solver = copy(backend)
    if hasattr(solver, 'reasoning_effort'):
        solver.reasoning_effort = 'medium'
    if hasattr(solver, 'thinking_mode'):
        solver.thinking_mode = 'enabled'
    if hasattr(solver, 'max_tokens'):
        solver.max_tokens = 16384

    def remember(key, value):
        cache[key] = value
        if save:
            save(key, value)

    async def solve(candidate, question, position):
        public = public_question(question)
        if not public['prompt']:
            raise ValueError('独立核验题目缺少题干。')
        request = {'question': public, 'sources': materials,
                   'verification_plan': ['按题设独立求解并核对选项', '核算数值和条件', '引用实际支持的原文']}
        identity = {'request': request, 'system': SOLVER_SYSTEM, 'model': getattr(solver, 'model', ''),
                    'reasoning_effort': 'medium', 'max_tokens': 16384}
        key = 'cove:' + hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        saved = cache.get(key)
        if not isinstance(saved, dict) or saved.get('status') != 'completed':
            started = perf_counter()
            raw = ''
            try:
                async with slots:
                    raw = await solver.generate(SOLVER_SYSTEM, json.dumps(request, ensure_ascii=False), role='quiz_independent_solver')
                solution = parse_json_object(raw)
                if 'answer' not in solution or not str(solution.get('justification') or '').strip():
                    raise ValueError('独立解答缺少答案或依据。')
                option_ids = [item['id'] for item in public['options']]
                answer = _normalized_answer(solution['answer'], public['type'])
                if public['type'] == 'multiple_choice' and answer != 'uncertain':
                    if not isinstance(answer, list) or not answer or any(item not in option_ids for item in answer):
                        raise ValueError('独立解答的选项不在题目中。')
                elif option_ids and public['type'] == 'single_choice' and answer not in [*option_ids, 'uncertain']:
                    raise ValueError('独立解答的选项不在题目中。')
                supplied_calculations = solution.get('calculations') or []
                if isinstance(supplied_calculations, dict):
                    supplied_calculations = [supplied_calculations]
                calculations = check_claim_calculations({'claim': solution['justification'],
                    'calculations': supplied_calculations}, [], question=public['prompt'])
                citations = verify_claim_quotes({'citations': solution.get('citations') or []}, materials)
                saved = {'status': 'completed', 'request': request, 'solution': solution,
                         'calculation_checks': calculations, 'quote_checks': citations,
                         'execution': {'seconds': round(perf_counter() - started, 3), 'max_tokens': 16384,
                                       'reasoning_effort': 'medium', 'model': getattr(solver, 'model', '')}}
                remember(key, saved)
            except Exception as exc:
                remember(key + ':failure:' + str(len(cache)), {'status': 'failed', 'request': request,
                    'raw': raw, 'error_type': type(exc).__name__, 'seconds': round(perf_counter() - started, 3)})
                raise
        # Join private keys only after the independent response is stored.
        original = _answer(question)
        return {'verification_id': f"{candidate.get('version_id') or candidate['type']}:{position}",
                'resource_type': candidate['type'], 'version_id': candidate.get('version_id'),
                'question_position': position, 'question_version_id': question.get('questionVersionId'),
                'cache_key': key, 'original_answer': original,
                'independent_answer': saved['solution']['answer'],
                'answers_match': _normalized_answer(original, public['type']) == _normalized_answer(saved['solution']['answer'], public['type']),
                'comparison_requires_judgment': public['type'] in {'short_answer', 'fill_blank'},
                'solution': saved['solution'], 'calculation_checks': saved['calculation_checks'],
                'quote_checks': saved['quote_checks']}

    pending = []
    for candidate in candidates:
        if candidate.get('type') != 'quiz':
            continue
        body = json.loads(candidate['content'])
        for position, question in enumerate(body.get('question_details') or body.get('quizQuestions') or [], 1):
            pending.append(solve(candidate, question, position))
    results = await asyncio.gather(*pending, return_exceptions=True)
    failure = next((result for result in results if isinstance(result, Exception)), None)
    if failure:
        raise failure
    return results


def apply_verification_decisions(result, verifications):
    """Ensure each disagreement is adjudicated, never majority-voted away."""
    decisions = result.get('verificationDecisions') or []
    indexed = {item.get('verification_id'): item for item in decisions if isinstance(item, dict)}
    if len(indexed) != len(decisions) or set(indexed) != {item['verification_id'] for item in verifications}:
        raise ValueError('独立核验尚有题目没有裁决。')
    for item in verifications:
        decision = indexed[item['verification_id']]
        verdict = decision.get('verdict')
        if verdict not in {'agree', 'revise_candidate', 'solver_error', 'unresolved'} or not decision.get('evidence'):
            raise ValueError('独立核验裁决缺少明确结论与依据。')
        if verdict == 'agree' and not item['answers_match'] and not item.get('comparison_requires_judgment'):
            raise ValueError('不同答案须说明修改原稿或独立解答出错的依据。')
        if verdict in {'revise_candidate', 'unresolved'}:
            result['approved'] = False
            result['rejectedTypes'] = list(dict.fromkeys([*result.get('rejectedTypes', []), item['resource_type']]))
            matching = next((finding for finding in result.get('findings', [])
                if finding.get('resourceType') == item['resource_type']
                and finding.get('location') == f"第{item['question_position']}题"
                and finding.get('severity') == 'knowledge_error'), None)
            if matching is not None:
                matching['verification_id'] = item['verification_id']
                matching['verification_decision'] = decision
                continue
            result.setdefault('findings', []).append({'resourceType': item['resource_type'],
                'location': f"第{item['question_position']}题", 'issue': decision.get('issue') or '答案核验存在差异',
                'evidence': decision['evidence'], 'fix': decision.get('fix') or '按裁决依据修订本题答案及解析。',
                'severity': 'knowledge_error', 'verification_id': item['verification_id']})
    return {**result, 'independent_verification': verifications}
