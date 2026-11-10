"""Run self-contained teaching examples through the existing local executor.

Execution is evidence for the displayed output, not for the algorithm's fitness
for a learning task. No resource, grade, or learning event is written here.
"""
from __future__ import annotations

import ast
import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal

from app.code_sandbox import CodeSandboxRunState, LocalPythonExecutor

_FENCE = re.compile(r'^\s*```([^\n`]*)\n(.*?)^\s*```\s*$', re.M | re.S)
_NUMBER = re.compile(r'(?<![\w.])[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?![\w.])')


def compare_output(expected: str, actual: str) -> bool | None:
    """Compare like-for-like full output, respecting its printed precision.

Different labels, abbreviated output and random examples require semantic
review. They must not acquire a numeric mismatch from an unrelated number.
"""
    left, right = expected.split(), actual.split()
    if not left or '...' in expected or '…' in expected:
        return None
    expected, actual = ' '.join(left), ' '.join(right)
    if expected == actual:
        return True
    if _NUMBER.sub('#', expected) != _NUMBER.sub('#', actual):
        return None
    pairs = list(zip(_NUMBER.findall(expected), _NUMBER.findall(actual)))
    if not pairs:
        return None
    for printed, observed in pairs:
        a, b = Decimal(printed), Decimal(observed)
        # Integer counts/indices are exact; decimal displays allow rounding.
        rounding = (Decimal(10) ** a.as_tuple().exponent / 2
                    if '.' in printed or 'e' in printed.lower() else Decimal(0))
        tolerance = (max(rounding, max(abs(a), abs(b)) * Decimal('1e-10'))
                     if '.' in printed or 'e' in printed.lower() else Decimal(0))
        if abs(a - b) > tolerance:
            return False
    return True


def _pairs(draft: str):
    blocks = list(_FENCE.finditer(draft))
    for i, block in enumerate(blocks):
        if block[1].strip().lower() not in {'python', 'py', 'python3'}:
            continue
        if i + 1 >= len(blocks):
            continue
        output = blocks[i + 1]
        if output[1].strip().lower() not in {'', 'text', 'plaintext', 'output', 'stdout'}:
            continue
        caption = draft[block.end():output.start()]
        if not re.search(r'输出|运行结果|output|stdout', caption, re.I):
            continue
        code = block[2].strip()
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        # Explicit fragments and interactive tasks have no standalone result.
        if any(isinstance(n, ast.Constant) and n.value is Ellipsis for n in ast.walk(tree)):
            continue
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == 'input' for n in ast.walk(tree)):
            continue
        varying = bool(re.search(r'\brandom\b|\brandn?\b|\btime\b|\bdatetime\b|\bshuffle\b|\bsample\b', code))
        yield {'code': code, 'expected': output[2].strip(), 'quote': output[0],
               'line': draft[:block.start()].count('\n') + 1, 'varying': varying}


async def verify_teaching_code(draft: str, *, cache: dict, owner: str,
                               course_id: str | None, executor=None) -> list[dict]:
    executor = executor or LocalPythonExecutor()
    if not executor.enabled:
        return []
    records = []
    for pair in _pairs(draft):
        digest = hashlib.sha256(pair['code'].encode()).hexdigest()
        cached = digest in cache
        if not cached:
            state = CodeSandboxRunState(
                runAttemptId='teaching-check-' + digest, ownerPublicId=owner,
                sourceResourceId='chat-teaching', sourceResourceVersionId=digest,
                courseId=course_id, entryFile='example.py', runtimeBoundary='trusted_local',
                timeoutSeconds=20, code=pair['code'], codeSha256=digest,
                requiredChecks=(), status='queued', createdAt=datetime.now(timezone.utc).isoformat())
            result = await executor.execute(state)
            cache[digest] = result.model_dump(mode='json')
        result = cache[digest]
        full = result.get('stdoutComplete') or {}
        actual = full.get('text', result.get('stdout', ''))
        complete = full.get('available', not (result.get('stdoutCapture') or {}).get('truncated', False))
        comparison = (compare_output(pair['expected'], actual)
                      if result['status'] == 'success' and complete and not pair['varying'] else None)
        records.append({**pair, 'codeSha256': digest, 'status': result['status'],
                        'stdout': actual, 'stderr': result.get('stderr', ''),
                        'executionTimeMs': result['executionTimeMs'], 'complete': complete,
                        'matches': comparison, 'cached': cached})
    return records


def merge_execution_findings(parsed: dict, records: list[dict]) -> dict:
    """A measured mismatch reaches revision even if a reviewer overlooks it."""
    claims = list(parsed.get('claims') or [])
    for record in records:
        if record['matches'] is not False:
            continue
        existing = next((c for c in claims if ' '.join(str(c.get('claim') or '').split())
                         in {' '.join(record['quote'].split()), ' '.join(record['expected'].split())}), None)
        finding = {'claim_id': 'execution:' + record['codeSha256'][:24],
            'claim': record['quote'], 'basis': 'worked_example', 'support': 'unsupported',
            'needs_revision': True, 'quote': '', 'source_ref_ids': [],
            'location': f"第{record['line']}行代码的输出",
            'support_reason': '相同代码和输入的实跑结果与所列输出不一致。',
            'review': {'verifier': '已用当前Python运行环境执行正文中的完整代码。',
                       'revision': '保留正确代码，按实跑结果替换输出及相关说明：\n' + record['stdout']}}
        if existing is not None:
            existing.update(finding)
        else:
            claims.append(finding)
    parsed['claims'] = claims
    return parsed


def output_claim_executed(claim: str, records: list[dict]) -> bool:
    """Only the exact located output claim can reuse execution as its check."""
    def normalize(value):
        value = re.sub(r'^\s*```[^\n]*\n|\n\s*```\s*$', '', value)
        value = re.sub(r'^\s*(?:程序|代码|实际|预期|运行)?输出(?:块)?(?:为|是)?\s*[:：]?\s*', '', value)
        value = re.sub(r'\s+(?:与|和|以及)\s+|[；;]', ' ', value)
        return ' '.join(value.strip().rstrip('。').split())
    normalized = normalize(claim)
    return bool(normalized) and any(r['matches'] is not None and normalized == normalize(r['expected'])
                                    for r in records)
