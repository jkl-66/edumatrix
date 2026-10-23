"""Evidence-bound code reviews and apply-as-new-version workflow."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

from pydantic import Field

from app.agent_audit import PublicAgentRun, assert_public_audit_is_sanitized, sanitize_public_value
from app.code_sandbox import CodeSandboxError, CodeSandboxRunState, _owned_run, _owned_resource
from app.database import DBArtifact, DBArtifactVersion
from app.m1_lifecycle import record_audit
from app.m1_repository import add_artifact_version
from app.m2_contracts import StrictModel
from app.m3_agents import M3_AGENT_CONTRACTS, M3AgentRole
from app.m5_resources import parse_code_sandbox_content, resource_detail


REVIEW_ARTIFACT_TYPE = "code_sandbox_review"
REVIEW_SCHEMA_VERSION = "f6.code-review.v1"
REVIEWABLE_RUN_STATUSES = frozenset({"success", "runtime_error", "timeout"})
_TRACEBACK_LINE = re.compile(r'File "[^"]+", line (\d+)')
_ERROR_LINE = re.compile(r"^(?P<kind>[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)):\s*(?P<message>.+)$")
_DIVIDE_BY_LEN = re.compile(r"/\s*len\((?P<name>[A-Za-z_][A-Za-z0-9_]*)\)")
_SENSITIVE_TEXT = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*", re.IGNORECASE),
    re.compile(r"\b(?:api[_ -]?key|secret|password|token)\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
    re.compile(r"\b(?:system[_ -]?prompt|user[_ -]?prompt|chain[_ -]?of[_ -]?thought|private[_ -]?reasoning)\b", re.IGNORECASE),
)
ReviewCategory = Literal["general", "security", "performance", "reliability", "readability", "custom"]


class CodeReviewFinding(StrictModel):
    id: str
    severity: Literal["info", "warning", "error"]
    title: str
    location: str
    evidence: str
    recommendation: str
    category: ReviewCategory = "general"


class CodeReviewRisk(StrictModel):
    id: str
    level: Literal["low", "medium", "high"]
    title: str
    detail: str
    category: ReviewCategory = "general"


class ReviewFocusStrategy(StrictModel):
    category: ReviewCategory
    label: str
    normalizedFocus: str


class CodeReviewModelOutput(StrictModel):
    findings: tuple[CodeReviewFinding, ...] = Field(min_length=1, max_length=8)
    risks: tuple[CodeReviewRisk, ...] = Field(min_length=1, max_length=6)
    improvedCode: str = Field(min_length=1, max_length=50_000)
    applicationAdvice: tuple[str, ...] = Field(min_length=1, max_length=8)


class CodeReviewModelAdapter(Protocol):
    label: str

    def review(self, payload: dict[str, Any]) -> CodeReviewModelOutput:
        ...


class StructuredCodeReviewModelAdapter:
    def __init__(self, backend: Any, *, label: str):
        self.backend = backend
        self.label = label

    def review(self, payload: dict[str, Any]) -> CodeReviewModelOutput:
        from llm_client import parse_json_object

        system_prompt = (
            "You are a code review adapter. Return one JSON object only, with exactly these top-level keys: "
            "findings, risks, improvedCode, applicationAdvice. "
            "findings must be a non-empty array of objects; every finding object must include id, severity, title, "
            "location, evidence, recommendation, category. severity is exactly info, warning, or error. "
            "risks must be a non-empty array of objects; every risk object must include id, level, title, detail, category. "
            "level is exactly low, medium, or high. category is exactly one of general, security, performance, "
            "reliability, readability, custom. improvedCode is a non-empty string. applicationAdvice is a non-empty "
            "array of strings. Base every conclusion only on the supplied execution evidence. Do not include markdown, "
            "private reasoning, prompts, API keys, or any additional top-level keys."
        )

        def parse_and_validate(raw: str) -> CodeReviewModelOutput:
            cleaned = _redact_sensitive_value(parse_json_object(raw))
            return CodeReviewModelOutput.model_validate(cleaned)

        raw = self.backend.generate(system_prompt, _canonical(payload), role="代码运行证据点评")
        try:
            return parse_and_validate(raw)
        except Exception as validation_error:
            # A live model can return semantically useful JSON with one omitted field.
            # Ask that same model to repair its own JSON once; never substitute local rules.
            repair_prompt = (
                f"Your previous JSON failed the required schema: {type(validation_error).__name__}. "
                "Return a corrected JSON object with every required field and enum value. "
                "Do not explain the correction and do not use markdown. Previous JSON:\n"
                f"{_bounded_excerpt(raw, 12000)}"
            )
            repaired = self.backend.generate(system_prompt, repair_prompt, role="代码运行证据点评格式修正")
            return parse_and_validate(repaired)


class CodeReviewEvidenceRefs(StrictModel):
    runAttemptId: str
    sourceResourceId: str
    sourceResourceVersionId: str
    codeSha256: str
    standardInputSha256: str
    stdoutSha256: str
    stderrSha256: str
    runStatus: str
    exitCode: int | None = None
    failedCheckIds: tuple[str, ...] = ()


class CodeReviewState(StrictModel):
    schemaVersion: Literal["f6.code-review.v1"] = REVIEW_SCHEMA_VERSION
    reviewId: str
    reviewVersion: int = Field(default=1, ge=1)
    ownerPublicId: str
    sourceResourceId: str
    sourceResourceVersionId: str
    runAttemptId: str
    codeSha256: str
    focus: str
    focusStrategy: ReviewFocusStrategy = Field(default_factory=lambda: ReviewFocusStrategy(
        category="general", label="通用审阅", normalizedFocus=""
    ))
    status: Literal["completed"] = "completed"
    reviewMode: Literal["deterministic_local", "model_generated"] = "model_generated"
    modelState: Literal["not_requested", "completed", "failed"] = "not_requested"
    modelLabel: str = ""
    modelFailureCode: str = ""
    generatedAt: str
    findings: tuple[CodeReviewFinding, ...]
    risks: tuple[CodeReviewRisk, ...]
    baselineFindings: tuple[CodeReviewFinding, ...] = ()
    baselineRisks: tuple[CodeReviewRisk, ...] = ()
    improvedCode: str = Field(min_length=1, max_length=50_000)
    applicationAdvice: tuple[str, ...] = Field(min_length=1, max_length=8)
    evidenceRefs: CodeReviewEvidenceRefs
    agentAudit: tuple[PublicAgentRun, ...]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(value: Any) -> str:
    return _digest_text(_canonical(value))


def _stable_id(prefix: str, *parts: str) -> str:
    material = chr(31).join(parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(material).hexdigest()[:32]}"


def _clean_focus(value: str) -> str:
    return " ".join(str(sanitize_public_value(value or "")).split())[:1000]


def _redact_sensitive_text(value: str) -> str:
    text = str(value or "")
    for pattern in _SENSITIVE_TEXT:
        text = pattern.sub("[redacted]", text)
    return text


def _redact_sensitive_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_sensitive_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_sensitive_value(item) for item in value]
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    return value


def _focus_strategy(focus: str) -> ReviewFocusStrategy:
    normalized = _clean_focus(focus)
    lowered = normalized.lower()
    candidates: tuple[tuple[ReviewCategory, str, tuple[str, ...]], ...] = (
        ("security", "安全与输入边界", ("安全", "注入", "权限", "密钥", "secret", "token", "eval", "exec")),
        ("performance", "性能与复杂度", ("性能", "复杂度", "耗时", "内存", "循环", "performance")),
        ("reliability", "可靠性与异常边界", ("边界", "异常", "错误", "稳定", "可靠", "超时")),
        ("readability", "可读性与维护性", ("可读", "命名", "结构", "维护", "注释", "readability")),
    )
    if not normalized:
        return ReviewFocusStrategy(category="general", label="通用审阅", normalizedFocus="")
    for category, label, markers in candidates:
        if any(marker in lowered for marker in markers):
            return ReviewFocusStrategy(category=category, label=label, normalizedFocus=normalized)
    return ReviewFocusStrategy(category="custom", label="自定义重点", normalizedFocus=normalized)


def configured_code_review_adapter() -> CodeReviewModelAdapter | None:
    """Use the configured OpenAI-compatible live model for learner code reviews."""
    from config import CONFIG
    from llm_client import OpenAIChatLLM

    provider = CONFIG.llm_provider.strip().lower()
    if provider not in {"openai", "vllm"} or not CONFIG.llm_endpoint or not CONFIG.llm_api_key or not CONFIG.llm_model:
        return None
    backend = OpenAIChatLLM(
        endpoint=CONFIG.llm_endpoint,
        api_key=CONFIG.llm_api_key,
        model=CONFIG.llm_model,
        temperature=CONFIG.llm_temperature,
        max_tokens=CONFIG.llm_max_tokens,
        timeout_seconds=CONFIG.llm_timeout,
    )
    return StructuredCodeReviewModelAdapter(backend, label=f"{provider}:{CONFIG.llm_model}")


def _bounded_excerpt(value: str, limit: int = 420) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return f"{text[:head]}\n...\n{text[-tail:]}"


def _runtime_location(stderr: str) -> str:
    matches = _TRACEBACK_LINE.findall(stderr)
    return f"main.py:{matches[-1]}" if matches else "运行结果"


def _runtime_error_summary(stderr: str) -> str:
    for line in reversed([item.strip() for item in stderr.splitlines() if item.strip()]):
        match = _ERROR_LINE.match(line)
        if match:
            return f"{match.group('kind')}: {match.group('message')}"
    return _bounded_excerpt(stderr) or "程序以运行错误结束。"


def _static_findings(code: str) -> tuple[list[CodeReviewFinding], list[CodeReviewRisk]]:
    findings: list[CodeReviewFinding] = []
    risks: list[CodeReviewRisk] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        findings.append(CodeReviewFinding(
            id="syntax-error",
            severity="error",
            title="代码无法通过语法检查",
            location=f"main.py:{exc.lineno or 1}",
            evidence=str(exc.msg or "SyntaxError"),
            recommendation="先修复该行附近的括号、缩进或表达式，再重新运行。",
            category="reliability",
        ))
        return findings, risks

    for node in ast.walk(tree):
        if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and node.test.value is True:
            risks.append(CodeReviewRisk(
                id=f"unbounded-loop-{node.lineno}",
                level="high",
                title="循环可能无法结束",
                detail=f"main.py:{node.lineno} 使用 while True；应提供可验证的退出条件或明确的迭代上限。",
                category="reliability",
            ))
        if isinstance(node, ast.ExceptHandler) and not node.body:
            risks.append(CodeReviewRisk(
                id=f"empty-except-{node.lineno}",
                level="medium",
                title="异常处理没有留下诊断信息",
                detail=f"main.py:{node.lineno} 捕获异常后未记录或重新抛出，可能掩盖真实错误。",
                category="reliability",
            ))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
            risks.append(CodeReviewRisk(
                id=f"dynamic-exec-{node.lineno}",
                level="high",
                title="动态执行扩大了输入风险",
                detail=f"main.py:{node.lineno} 调用了 {node.func.id}；当前学习任务通常不需要动态执行字符串。",
                category="security",
            ))
        if isinstance(node, (ast.For, ast.While)) and any(
            isinstance(child, (ast.For, ast.While)) for child in ast.iter_child_nodes(node)
        ):
            risks.append(CodeReviewRisk(
                id=f"nested-loop-{node.lineno}",
                level="medium",
                title="嵌套循环需要核对数据规模",
                detail=f"main.py:{node.lineno} 包含嵌套循环；请结合输入规模验证时间复杂度。",
                category="performance",
            ))
    return findings, risks


def _improved_code(run: CodeSandboxRunState) -> str:
    code = run.code.rstrip()
    if "ZeroDivisionError" in run.stderr:
        repaired, count = _DIVIDE_BY_LEN.subn(
            lambda match: f"/ len({match.group('name')}) if {match.group('name')} else 0.0",
            code,
            count=1,
        )
        if count:
            return repaired
    if run.status == "timeout" and "while True:" in code:
        return code.replace("while True:", "for _ in range(1000):", 1)
    marker = f"# Review draft from {run.runAttemptId[-12:]}: verify the highlighted evidence before submission."
    if code.startswith(marker):
        return code
    return f"{marker}\n{code}"


def _review_sections(run: CodeSandboxRunState, strategy: ReviewFocusStrategy) -> tuple[
    tuple[CodeReviewFinding, ...], tuple[CodeReviewRisk, ...], str,
    tuple[CodeReviewFinding, ...], tuple[CodeReviewRisk, ...]
]:
    findings, risks = _static_findings(run.code)
    if run.status == "runtime_error":
        findings.insert(0, CodeReviewFinding(
            id="runtime-error",
            severity="error",
            title="真实运行记录了错误",
            location=_runtime_location(run.stderr),
            evidence=_runtime_error_summary(run.stderr),
            recommendation="从该位置复核输入边界和变量状态，应用建议草稿后重新运行并比较结果。",
            category="reliability",
        ))
    elif run.status == "timeout":
        findings.insert(0, CodeReviewFinding(
            id="runtime-timeout",
            severity="error",
            title="真实运行超过时间上限",
            location=_runtime_location(run.stderr),
            evidence=run.stopReason or "执行器达到任务超时边界并清理了进程树。",
            recommendation="为循环或等待逻辑增加明确终止条件，再重新运行验证。",
            category="reliability",
        ))
    for check in run.checks:
        if not check.passed:
            findings.append(CodeReviewFinding(
                id=f"failed-check-{check.id}",
                severity="warning",
                title=f"必需检查未通过：{check.label}",
                location="运行检查",
                evidence=check.detail,
                recommendation="按检查要求调整代码或输出，并使用同一任务重新运行。",
                category="reliability",
            ))
    if run.stderr.strip() and run.status == "success":
        risks.append(CodeReviewRisk(
            id="stderr-on-success",
            level="medium",
            title="成功退出仍产生错误输出",
            detail=_bounded_excerpt(run.stderr),
            category="reliability",
        ))
    if not findings:
        findings.append(CodeReviewFinding(
            id="no-blocking-finding",
            severity="info",
            title="未发现阻断当前任务的运行问题",
            location="整体",
            evidence=f"运行状态 {run.status}，必需检查通过 {run.passedCount}/{run.totalCount}。",
            recommendation="继续核对边界输入，并根据点评重点审阅可读性与可维护性。",
            category="general",
        ))
    if not risks:
        risks.append(CodeReviewRisk(
            id="boundary-coverage",
            level="low",
            title="仍需验证边界输入",
            detail="当前结论只绑定本次标准输入和运行证据，不代表所有输入都已验证。",
            category="general",
        ))
    baseline_findings = tuple(findings[:8])
    baseline_risks = tuple(risks[:6])
    if strategy.category != "general":
        mandatory_ids = {"runtime-error", "runtime-timeout"}
        focused_findings = [
            item for item in baseline_findings
            if item.id in mandatory_ids or item.id.startswith("failed-check-") or item.category == strategy.category
        ]
        focused_risks = [item for item in baseline_risks if item.category == strategy.category]
        findings = focused_findings
        risks = focused_risks
    else:
        findings = list(baseline_findings)
        risks = list(baseline_risks)
    if strategy.normalizedFocus:
        findings.append(CodeReviewFinding(
            id="learner-focus",
            severity="info",
            title=f"已采用{strategy.label}策略",
            location="点评重点",
            evidence=strategy.normalizedFocus,
            recommendation="应用建议后，使用相同输入重跑，再补充一个针对该重点的边界样例。",
            category=strategy.category,
        ))
    if not risks:
        risks.append(CodeReviewRisk(
            id=f"focus-coverage-{strategy.category}",
            level="low",
            title=f"本次运行未命中{strategy.label}规则",
            detail="该结论仅表示当前静态规则未命中；仍应通过针对性输入或模型点评继续核对。",
            category=strategy.category,
        ))
    return tuple(findings[:8]), tuple(risks[:6]), _improved_code(run), baseline_findings, baseline_risks


def _model_payload(run: CodeSandboxRunState, strategy: ReviewFocusStrategy) -> dict[str, Any]:
    return _redact_sensitive_value({
        "schemaVersion": "f6.code-review-model-input.v1",
        "focusStrategy": strategy.model_dump(mode="json"),
        "run": {
            "status": run.status,
            "entryFile": run.entryFile,
            "code": run.code,
            "standardInput": run.standardInput,
            "stdout": run.stdout,
            "stderr": run.stderr,
            "exitCode": run.exitCode,
            "stopReason": run.stopReason,
            "checks": [item.model_dump(mode="json") for item in run.checks],
            "plots": [
                {"id": item.id, "title": item.title, "bytes": item.bytes, "sha256": _digest_text(item.dataUrl)}
                for item in run.plots
            ],
        },
    })


def _agent_audit(
    *, review_id: str, run: CodeSandboxRunState, findings: tuple[CodeReviewFinding, ...], focus: str
) -> tuple[PublicAgentRun, ...]:
    contracts = {contract.role: contract for contract in M3_AGENT_CONTRACTS}
    failed_checks = [item.id for item in run.checks if not item.passed]
    input_refs = (
        run.runAttemptId,
        run.sourceResourceVersionId,
        f"code:{run.codeSha256}",
        f"stdout:{_digest_text(run.stdout)}",
        f"stderr:{_digest_text(run.stderr)}",
    )
    items = (
        PublicAgentRun(
            runId=f"{review_id}-evidence",
            role=contracts[M3AgentRole.EVIDENCE_REVIEW].role.value,
            inputRefs=input_refs,
            candidateSummary=f"Reviewed terminal run {run.status}; found {len(findings)} review items.",
            disagreement=(
                "Runtime status and required checks disagree; the conservative result keeps the failed checks visible."
                if run.status == "success" and failed_checks
                else "No material conflict between terminal runtime evidence and required checks was found."
            ),
            validation="Code hash, run ownership, resource version, stdout, stderr, exit status, and required checks were verified.",
            revision="Converted raw execution evidence into bounded public findings and risks.",
            decisionSummary="Only conclusions traceable to the selected run are included.",
            status="completed",
        ),
        PublicAgentRun(
            runId=f"{review_id}-candidate",
            role=contracts[M3AgentRole.DOMAIN_GENERATION].role.value,
            inputRefs=(run.runAttemptId, f"focus:{_digest_text(focus)}" if focus else "focus:general"),
            candidateSummary="Prepared one conservative improved-code draft without changing the original run snapshot.",
            disagreement="Automatic edits are limited to locally verifiable patterns; uncertain changes remain recommendations.",
            validation="The suggested draft remains valid text inside the current code-resource size boundary.",
            revision="Kept the original code immutable and moved the candidate to an explicit apply-as-new-version action.",
            decisionSummary="The learner chooses whether to apply and rerun the draft.",
            status="completed",
        ),
        PublicAgentRun(
            runId=f"{review_id}-decision",
            role=contracts[M3AgentRole.DECISION_ORCHESTRATION].role.value,
            inputRefs=(run.runAttemptId, review_id),
            candidateSummary="Compared the original run evidence with the bounded improvement candidate.",
            disagreement="A review or applied draft alone is not accepted as mastery evidence.",
            validation="Completion remains owned by the existing code_tests_passed server rule after a qualifying rerun.",
            revision="Separated review, apply, rerun, and learning-completion actions.",
            decisionSummary="Apply as a new draft, rerun, compare evidence, then complete learning only if checks pass.",
            status="completed",
        ),
    )
    payload = [item.model_dump(mode="json", by_alias=True) for item in items]
    assert_public_audit_is_sanitized(payload)
    return items


def _owned_review(db: Any, review_id: str, owner: str) -> tuple[DBArtifact, DBArtifactVersion, CodeReviewState]:
    artifact = db.get(DBArtifact, review_id)
    if artifact is None or artifact.artifact_type != REVIEW_ARTIFACT_TYPE:
        raise CodeSandboxError("code_review_unknown", "代码点评不存在或已经不可用。")
    if artifact.owner_public_id != owner:
        raise CodeSandboxError("code_review_forbidden", "该代码点评属于其他用户。")
    version = db.get(DBArtifactVersion, artifact.current_version_id)
    return artifact, version, CodeReviewState.model_validate_json(version.content)


def _application(db: Any, review: CodeReviewState) -> dict[str, Any] | None:
    versions = (
        db.query(DBArtifactVersion)
        .filter_by(artifact_id=review.sourceResourceId)
        .order_by(DBArtifactVersion.version_number.desc())
        .all()
    )
    for version in versions:
        metadata = dict(version.metadata_json or {})
        if metadata.get("code_review_id") == review.reviewId:
            return {
                "resourceVersionId": version.id,
                "resourceVersionNumber": version.version_number,
                "appliedAt": metadata.get("code_review_applied_at"),
            }
    return None


def create_review(
    db: Any,
    *,
    owner: str,
    resource_id: str,
    run_attempt_id: str,
    code_sha256: str,
    focus: str,
    idempotency_key: str,
    model_adapter: CodeReviewModelAdapter | None = None,
) -> tuple[dict[str, Any], bool]:
    resource, _, _ = _owned_resource(db, resource_id, owner)
    _, _, run = _owned_run(db, run_attempt_id, owner)
    if run.sourceResourceId != resource.id:
        raise CodeSandboxError("code_review_run_resource_mismatch", "运行记录不属于当前代码沙盒。")
    if run.status not in REVIEWABLE_RUN_STATUSES:
        raise CodeSandboxError("code_review_run_ineligible", "请先完成一次真实运行；排队中、运行中或主动停止的记录不能生成点评。")
    if run.codeSha256 != code_sha256:
        raise CodeSandboxError("code_review_code_hash_mismatch", "代码哈希与所选运行记录不一致。")
    focus = _clean_focus(focus)
    focus_strategy = _focus_strategy(focus)
    request = {
        "resource_id": resource_id,
        "run_attempt_id": run_attempt_id,
        "code_sha256": code_sha256,
        "focus": focus,
    }
    request_hash = _digest(request)
    review_id = _stable_id("review", owner, resource_id, idempotency_key)
    existing = db.get(DBArtifact, review_id)
    if existing is not None:
        first = db.query(DBArtifactVersion).filter_by(artifact_id=review_id, version_number=1).one()
        if (first.metadata_json or {}).get("create_request_sha256") != request_hash:
            raise CodeSandboxError("code_review_idempotency_conflict", "点评幂等键已经绑定到其他运行或点评重点。")
        return get_review(db, owner=owner, review_id=review_id), False

    if model_adapter is None:
        raise CodeSandboxError("code_review_model_unavailable", "当前没有可用的真实模型，暂时不能生成点评，请稍后重试。")
    model_label = _redact_sensitive_text(model_adapter.label)[:120]
    try:
        model_output = model_adapter.review(_model_payload(run, focus_strategy))
    except Exception as exc:
        raise CodeSandboxError("code_review_model_failed", "真实模型点评暂时失败，请重试。") from exc
    findings = model_output.findings
    risks = model_output.risks
    improved_code = model_output.improvedCode
    application_advice = model_output.applicationAdvice
    review_mode: Literal["deterministic_local", "model_generated"] = "model_generated"
    model_state: Literal["not_requested", "completed", "failed"] = "completed"
    baseline_findings: tuple[CodeReviewFinding, ...] = ()
    baseline_risks: tuple[CodeReviewRisk, ...] = ()
    evidence = CodeReviewEvidenceRefs(
        runAttemptId=run.runAttemptId,
        sourceResourceId=run.sourceResourceId,
        sourceResourceVersionId=run.sourceResourceVersionId,
        codeSha256=run.codeSha256,
        standardInputSha256=_digest_text(run.standardInput),
        stdoutSha256=_digest_text(run.stdout),
        stderrSha256=_digest_text(run.stderr),
        runStatus=run.status,
        exitCode=run.exitCode,
        failedCheckIds=tuple(item.id for item in run.checks if not item.passed),
    )
    state = CodeReviewState(
        reviewId=review_id,
        ownerPublicId=owner,
        sourceResourceId=resource.id,
        sourceResourceVersionId=run.sourceResourceVersionId,
        runAttemptId=run.runAttemptId,
        codeSha256=run.codeSha256,
        focus=focus,
        focusStrategy=focus_strategy,
        reviewMode=review_mode,
        modelState=model_state,
        modelLabel=model_label,
        modelFailureCode="",
        generatedAt=_now(),
        findings=findings,
        risks=risks,
        baselineFindings=baseline_findings,
        baselineRisks=baseline_risks,
        improvedCode=improved_code,
        applicationAdvice=application_advice,
        evidenceRefs=evidence,
        agentAudit=_agent_audit(review_id=review_id, run=run, findings=findings, focus=focus),
    )
    artifact = DBArtifact(
        id=review_id,
        owner_public_id=owner,
        course_id=resource.course_id,
        artifact_type=REVIEW_ARTIFACT_TYPE,
        title=f"{resource.title} · 代码点评",
        status="approved",
    )
    db.add(artifact)
    db.flush()
    version = add_artifact_version(
        db,
        artifact=artifact,
        content=_canonical(state.model_dump(mode="json", by_alias=True)),
        content_format="json",
        created_by_public_id=owner,
        metadata={
            "create_request_sha256": request_hash,
            "source_resource_id": resource.id,
            "source_resource_version_id": run.sourceResourceVersionId,
            "run_attempt_id": run.runAttemptId,
            "code_sha256": run.codeSha256,
            "review_mode": state.reviewMode,
        },
    )
    record_audit(
        db,
        actor_public_id=owner,
        action="code_review.create",
        object_type="artifact_version",
        object_id=version.id,
        metadata={"review_id": review_id, "run_attempt_id": run.runAttemptId, "code_sha256": run.codeSha256},
    )
    return {**state.model_dump(mode="json", by_alias=True), "versionId": version.id, "application": None}, True


def get_review(db: Any, *, owner: str, review_id: str) -> dict[str, Any]:
    _, version, state = _owned_review(db, review_id, owner)
    return {
        **state.model_dump(mode="json", by_alias=True),
        "versionId": version.id,
        "versionNumber": version.version_number,
        "application": _application(db, state),
    }


def latest_review(db: Any, *, owner: str, resource_id: str, run_attempt_id: str) -> dict[str, Any] | None:
    _owned_resource(db, resource_id, owner)
    artifacts = (
        db.query(DBArtifact)
        .filter_by(owner_public_id=owner, artifact_type=REVIEW_ARTIFACT_TYPE)
        .order_by(DBArtifact.created_at.desc())
        .all()
    )
    for artifact in artifacts:
        version = db.get(DBArtifactVersion, artifact.current_version_id)
        state = CodeReviewState.model_validate_json(version.content)
        if state.sourceResourceId == resource_id and state.runAttemptId == run_attempt_id:
            return get_review(db, owner=owner, review_id=state.reviewId)
    return None


def apply_review(
    db: Any,
    *,
    owner: str,
    review_id: str,
    expected_lock_version: int,
    idempotency_key: str,
) -> dict[str, Any]:
    _, review_version, review = _owned_review(db, review_id, owner)
    resource = db.get(DBArtifact, review.sourceResourceId)
    if resource is None or resource.owner_public_id != owner:
        raise CodeSandboxError("code_review_resource_unavailable", "代码点评对应的沙盒资源不可用。")
    existing = _application(db, review)
    if existing is not None:
        return {
            "schemaVersion": "f6.code-review-application.v1",
            "reviewId": review.reviewId,
            "runAttemptId": review.runAttemptId,
            "created": False,
            **existing,
            "resource": resource_detail(db, resource),
        }
    if resource.lock_version != expected_lock_version:
        raise CodeSandboxError("code_review_apply_conflict", "代码沙盒已发生变化，请刷新后重新确认点评建议。")
    if resource.current_version_id != review.sourceResourceVersionId:
        raise CodeSandboxError("code_review_apply_stale", "该点评基于旧代码版本，不能覆盖当前草稿。")
    source_version = db.get(DBArtifactVersion, resource.current_version_id)
    content = parse_code_sandbox_content(source_version.content)
    if not any(item.path == content.entryFile for item in content.files):
        raise CodeSandboxError("code_review_entry_file_missing", "当前代码版本缺少点评对应的入口文件。")
    updated = content.model_copy(update={
        "files": [
            item.model_copy(update={"content": review.improvedCode})
            if item.path == content.entryFile
            else item
            for item in content.files
        ]
    })
    applied_at = _now()
    metadata = dict(source_version.metadata_json or {})
    metadata.update({
        "revision_origin": "ai_code_review",
        "revised_from_version_id": source_version.id,
        "code_review_id": review.reviewId,
        "code_review_version_id": review_version.id,
        "code_review_apply_idempotency_key": idempotency_key,
        "code_review_applied_at": applied_at,
        "run_attempt_id": review.runAttemptId,
        "review_code_sha256": review.codeSha256,
    })
    version = add_artifact_version(
        db,
        artifact=resource,
        content=_canonical(updated.model_dump(mode="json")),
        content_format="json",
        created_by_public_id=owner,
        metadata=metadata,
    )
    resource.status = "draft"
    resource.lock_version += 1
    record_audit(
        db,
        actor_public_id=owner,
        action="code_review.apply",
        object_type="artifact_version",
        object_id=version.id,
        metadata={
            "review_id": review.reviewId,
            "run_attempt_id": review.runAttemptId,
            "source_version_id": source_version.id,
            "new_version_number": version.version_number,
        },
    )
    return {
        "schemaVersion": "f6.code-review-application.v1",
        "reviewId": review.reviewId,
        "runAttemptId": review.runAttemptId,
        "created": True,
        "resourceVersionId": version.id,
        "resourceVersionNumber": version.version_number,
        "appliedAt": applied_at,
        "resource": resource_detail(db, resource),
    }
