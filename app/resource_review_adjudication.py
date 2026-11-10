"""Resolve review findings against the actual draft and quoted source evidence."""
from copy import copy
import asyncio
import hashlib
import json
import inspect
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version

from llm_client import parse_json_object
from app.resource_review_parts import resource_review_calculation_feedback
from app.resource_review_context import bind_finding_version
from app.model_evaluation_rules import MODEL_EVALUATION_INSTRUCTION


SYSTEM = (
    "你是教学审核意见裁决者。根据当前原稿、题目条件、实际学习动作、当前教学要求及来源，"
    "逐项重新核验findings，不服从原审核结论，也不为了发布而关闭问题。只输出JSON对象decisions数组。"
    "每项必须含issue_id、verdict(confirmed/false_positive/optional)、candidate_quote、reason、fix、source_evidence。"
    "candidate_quote须逐字摘录对应版本中的原句；location错误时找到真正相关原句。"
    "candidates是本轮被裁决的版本；dependencies只用于配套比对，其原句不能冒充candidate_quote。"
    "source_evidence为数组，每项source_ref_id与quote，quote逐字来自给定来源。"
    "confirmed表示知识错误、任务缺项或适配失效，并给局部修复办法；false_positive表示原审核前提或推算错误，"
    "说明原稿为何成立；optional只用于不影响理解、操作、知识正确和必要教学深度的润色。"
    "涉及数值时写明原题数据、公式、计算与单位，充分条件和必要条件分别核对。"
    "numerical_verification问题含实际计算输入、程序、输出与按显示精度的比较。先检查其数据/方法是否对应原题；"
    "若对应且超出显示精度，必须confirmed，不能因汇总值正确、笼统浮点误差或声称已核对而排除逐点错误。"
    "判false_positive须指出具体错误输入、算法参数或对照对象并给对应原句和正确计算；不能把已宣称按该算法产生的预测降格成任意练习值。"
    "active_requirements中的参考数值与旧审核建议也可能含技术误述，不能仅因当前稿与其不同就confirmed；以原始数据和实际指定接口为准。"
    "数值冲突先对齐计算对象、预处理、接口与容差；原始矩阵、增广矩阵、中心化后的求解器矩阵不能混比。"
    "例如LinearRegression(fit_intercept=True)采用中心化求解，model.rank_不是给原特征补常数列再调用matrix_rank；"
    "也不能把它的tol口径改称np.linalg.lstsq(rcond=None)默认截断。若原文对象有歧义，局部修改应明确对象和接口，"
    "保留各自成立的计算，不能只强令把一个数替换为另一个数。"
    "被引用的数据本身不是计算结果；不能换题设维护答案，不能把可选风格当错误。"
    "source_evidence仅引真正支持本结论的原句；缺资料不能编造。无依据排除的问题继续confirmed，说明缺失部分。"
    "只给公开核验依据与裁决，不输出私有思维链。"
)


@lru_cache(maxsize=1)
def linear_regression_solver_evidence():
    """Expose the installed dense solver call, whose tol behavior changed by version."""
    try:
        from sklearn.linear_model import LinearRegression
        lines = inspect.getsource(LinearRegression.fit).splitlines()
        start = next(i for i, line in enumerate(lines) if 'self.coef_, _, self.rank_' in line)
        end = start
        while end < len(lines) - 1 and ')' not in lines[end]:
            end += 1
        return {'package': 'scikit-learn', 'version': version('scikit-learn'),
                'symbol': 'sklearn.linear_model.LinearRegression.fit',
                'scope': '当前安装版本，稠密输入且positive=False；rank_来自下面实际求解调用。',
                'source_excerpt': '\n'.join(lines[start:end+1]),
                'instruction': '以实际调用的参数为准。不要把其它版本的tol行为套到当前版本，也不要把当前行为推广到所有版本。'}
    except (ImportError, OSError, StopIteration, PackageNotFoundError):
        return None


async def adjudicate_review(backend, *, manifest, candidates, review, completed=None, save=None):
    # Saved reviews from earlier workers may contain an explicit null version.
    # Preserve their issue identities while resolving the current unique draft.
    findings = [bind_finding_version(item, candidates)
                for item in review.get("findings", []) if isinstance(item, dict)]
    if review.get("approved") or not findings:
        return review
    groups = {}
    for finding in findings:
        groups.setdefault((finding.get('resourceType'), finding.get('version_id')), []).append(finding)
    if len(groups) > 1:
        # A package-wide prompt made the judge quote the right sentence from
        # the wrong resource. Keep one target version explicit in each call;
        # siblings remain available solely for cross-resource comparisons.
        limit = asyncio.Semaphore(3)
        async def resolve_group(identity, items):
            selected = [item for item in candidates
                        if (item.get('type'), item.get('version_id')) == identity]
            dependencies = {item['version_id']: item for item in
                [*(manifest.get('dependency_resources') or []), *candidates]
                if item.get('version_id') and item.get('version_id') != identity[1]}
            async with limit:
                return await adjudicate_review(backend,
                    manifest={**manifest, 'dependency_resources': list(dependencies.values())},
                    candidates=selected, review={**review, 'findings': items}, completed=completed, save=save)
        results = await asyncio.gather(*(resolve_group(identity, items) for identity, items in groups.items()),
                                       return_exceptions=True)
        failures = [item for item in results if isinstance(item, BaseException)]
        if failures:
            # Successful groups have already been saved under their own input
            # hashes. A retry reuses those exact decisions.
            raise failures[0]
        remaining = [finding for result in results for finding in result['findings']]
        return {**review, 'approved': not remaining, 'findings': remaining,
                'rejectedTypes': list(dict.fromkeys(item['resourceType'] for item in remaining)),
                'review_decisions': [item for result in results for item in result['review_decisions']],
                'adjudication': [item for result in results for item in result['adjudication']],
                'summary': '已核实需要调整的内容。' if remaining else '原稿核验通过，可以继续学习。'}
    sources = {item["source_ref_id"]: item
               for values in (manifest.get("input_snapshot", {}).get("source_snapshots") or {}).values()
               for item in values if item.get("source_ref_id")}
    request = {"candidates": candidates, "findings": findings,
        "active_requirements": manifest.get("active_requirements"),
        **({"learner_evidence": manifest["learner_evidence"]} if manifest.get("learner_evidence") else {}),
        "sources": list(sources.values()), "dependencies": manifest.get("dependency_resources") or []}
    if 'LinearRegression' in json.dumps([candidates, findings], ensure_ascii=False):
        evidence = linear_regression_solver_evidence()
        if evidence:
            request['installed_runtime_evidence'] = [evidence]
    system = SYSTEM + MODEL_EVALUATION_INSTRUCTION
    key = "adjudication:" + hashlib.sha256(json.dumps(
        {"system": system, "request": request, "model": getattr(backend, "model", "")},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    saved = (completed or {}).get(key)
    if saved and saved.get("status") == "completed":
        return _validate_decisions(saved["decisions"], findings=findings, sources=sources, candidates=candidates, review=review)
    judge = copy(backend)
    if hasattr(judge, "reasoning_effort"):
        judge.reasoning_effort = "high"
    if hasattr(judge, "max_tokens"):
        judge.max_tokens = 32768
    invalid = (completed or {}).get(key + ":invalid")
    for _ in range(2):
        packet = {**request, "previous_invalid_decision": invalid} if invalid else request
        raw = await judge.generate(system, json.dumps(packet, ensure_ascii=False), role="resource_review_adjudicator")
        try:
            decisions = parse_json_object(raw).get("decisions")
            result = _validate_decisions(decisions, findings=findings, sources=sources, candidates=candidates, review=review)
        except ValueError as exc:
            invalid = {"output": raw, "validation_error": str(exc),
                       "instruction": "只修复不符合证据或字段要求的裁决；保留有依据的意见，不放宽核验。"}
            if completed is not None:
                completed[key + ":invalid"] = invalid
            if save:
                save(key + ":invalid", invalid)
            continue
        if save:
            save(key, {"status": "completed", "decisions": result["adjudication"], "input": request})
        return result
    raise ValueError(invalid["validation_error"])


def _validate_decisions(decisions, *, findings, sources, candidates, review):
    if not isinstance(decisions, list):
        raise ValueError("审核意见尚未完成逐项核验。")
    by_id = {item.get("issue_id"): item for item in decisions if isinstance(item, dict)}
    expected = {item.get("issue_id") for item in findings}
    if None in expected or len(decisions) != len(expected) or set(by_id) != expected:
        raise ValueError("审核裁决没有完整对应当前问题。")
    confirmed, closed, validated = [], [], []
    for finding in findings:
        finding = bind_finding_version(finding, candidates)
        decision = dict(by_id[finding["issue_id"]])
        verdict = decision.get("verdict")
        if verdict not in {"confirmed", "false_positive", "optional"} or not str(decision.get("reason") or "").strip():
            raise ValueError("审核裁决缺少明确依据。")
        candidate = next((item for item in candidates if item.get("version_id") == finding.get("version_id")
                          and item.get("type") == finding.get("resourceType")), None)
        content = str((candidate or {}).get("content") or "")
        # JSON serialization escapes line breaks; both forms represent the same
        # saved teaching text. No arbitrary model-selected document is accepted.
        quoted = str(decision.get("candidate_quote") or "").strip()
        if verdict != "confirmed" and (not quoted or (quoted not in content and json.dumps(quoted, ensure_ascii=False)[1:-1] not in content)):
            raise ValueError(f"意见 {finding['issue_id']}（版本 {finding.get('version_id') or '未确定'}）："
                             "排除意见所引用的原句不在当前版本中。")
        evidence = decision.get("source_evidence") or []
        for citation in evidence:
            source = sources.get(citation.get("source_ref_id"), {})
            quote = str(citation.get("quote") or "").strip()
            if not quote or quote not in str(source.get("quote") or source.get("text") or ""):
                raise ValueError("裁决引文与课程来源不对应。")
        calculation = resource_review_calculation_feedback({"summary": decision["reason"] + "\n" + str(decision.get("fix") or "")})
        if calculation:
            raise ValueError("裁决中的计算未通过复算：" + json.dumps(calculation, ensure_ascii=False))
        decision.update(resource_type=finding["resourceType"], version_id=finding.get("version_id"))
        validated.append(decision)
        if verdict == "confirmed":
            confirmed.append({**finding, "adjudication": decision,
                              "fix": decision.get("fix") or finding.get("fix")})
        else:
            closed.append(decision)
    return {**review, "approved": not confirmed,
        "findings": confirmed, "rejectedTypes": list(dict.fromkeys(item["resourceType"] for item in confirmed)),
        "review_decisions": closed, "adjudication": validated,
        "summary": "已核实需要调整的内容。" if confirmed else "原稿核验通过，可以继续学习。"}
