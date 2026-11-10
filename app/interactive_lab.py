"""Reusable, deterministic interactive experiment templates and instances."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.database import DBArtifact, DBArtifactVersion, DBLearningEvent, DBMediaContextResource
from app.learning_aggregation import (
    aggregate_learning_event,
    get_learning_aggregation,
    learning_feedback_payload,
)
from app.m1_repository import add_artifact_version
from app.m2_contracts import StrictModel
from app.m5_resources import canonical_resource_type, parse_interactive_model_content, resource_generation_blocker


LAB_INSTANCE_TYPE = "interactive_lab_instance"
LAB_EVENT_TYPE = "interactive_model_observation_submitted"
LAB_SCHEMA_VERSION = "next.interactive-lab.v1"


class InteractiveLabError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise InteractiveLabError(code, message)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _aggregate_feedback(db: Any, event: DBLearningEvent) -> dict[str, Any]:
    try:
        consumption = aggregate_learning_event(db, event=event)
    except Exception:
        consumption = get_learning_aggregation(db, event_id=event.id)
    return learning_feedback_payload(event, consumption)


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{hashlib.sha256(chr(31).join(parts).encode()).hexdigest()[:32]}"


class LabParameter(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    label: str
    kind: Literal["float", "integer"]
    minimum: float
    maximum: float
    step: float
    default: float
    unit: str = ""
    description: str


class LabMetric(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    label: str
    unit: str = ""
    higher_is_better: bool | None
    acceptance_threshold: float | None


class LabTemplate(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["next.interactive-template.v1"] = "next.interactive-template.v1"
    template_id: str
    template_version: str
    title: str
    summary: str
    skill_target: str
    applicability: str
    sweep_parameter_key: str
    runtime_mode: Literal["safe_deterministic_simulation"] = "safe_deterministic_simulation"
    security_level: Literal["no_external_code_or_network"] = "no_external_code_or_network"
    parameters: tuple[LabParameter, ...]
    metrics: tuple[LabMetric, ...]
    public_scenarios: tuple[str, ...]
    checker_version: str
    checker_contract_sha256: str
    hidden_expected_values_exposed: Literal[False] = False
    static_fallback: str
    template_sha256: str = ""


class HiddenLabResult(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    passed_count: int = Field(ge=0)
    total_count: int = Field(ge=1)
    failure_categories: tuple[str, ...]
    checker_version: str
    hidden_expected_values_exposed: Literal[False] = False


class LabSeriesPoint(StrictModel):
    x: float
    y: float


class LabComputedSeries(StrictModel):
    key: str
    label: str
    unit: str = ""
    points: tuple[LabSeriesPoint, ...]


class LabState(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["next.interactive-instance.v1"] = "next.interactive-instance.v1"
    instance_id: str
    owner_public_id: str
    template_id: str
    template_version: str
    template_sha256: str
    title: str
    linked_media_resource_id: str | None = None
    source_resource_id: str | None = None
    source_resource_version_id: str | None = None
    course_id: str | None = None
    knowledge_point_id: str | None = None
    profile_snapshot_id: str | None = None
    source_ref_ids: tuple[str, ...] = ()
    observation_prompt: str | None = None
    observation_minimum_characters: int = Field(default=1, ge=1, le=2_000)
    completion_rule: str | None = None
    status: Literal["configured", "evaluated", "passed", "needs_retry"] = "configured"
    attempt: int = Field(default=1, ge=1)
    parameters: dict[str, float | int]
    metrics: dict[str, float | int] | None = None
    computed_series: tuple[LabComputedSeries, ...] = ()
    feedback: tuple[str, ...] = ()
    hidden_acceptance: HiddenLabResult | None = None
    submitted_observation: str | None = None
    hint_count: int = Field(default=0, ge=0)
    action_count: int = Field(default=0, ge=0)
    last_action: str = "created"


def _template(spec: dict[str, Any]) -> LabTemplate:
    checker_contract = {
        "checker_version": spec["checker_version"],
        "categories": spec.pop("hidden_categories"),
        "expected_values_exposed": False,
    }
    spec["checker_contract_sha256"] = _digest(checker_contract)
    provisional = LabTemplate(**spec)
    content = provisional.model_dump(mode="json", exclude={"template_sha256"})
    return provisional.model_copy(update={"template_sha256": _digest(content)})


def _coverage_template(
    *,
    template_id: str,
    title: str,
    summary: str,
    skill_target: str,
    applicability: str,
    parameter_labels: tuple[str, str, str, str],
    metric_definitions: tuple[tuple[str, str, bool, float], ...],
    scenarios: tuple[str, ...],
) -> LabTemplate:
    """Build a safe, deterministic family template for course-wide coverage.

    The family templates share a small numeric contract so the registry can
    cover algorithm and agent concepts without allowing arbitrary model code.
    Their titles, applicability and metric labels remain domain-specific in the
    learner-facing workspace.
    """
    return _template({
        "template_id": template_id,
        "template_version": "1.0.0",
        "title": title,
        "summary": summary,
        "skill_target": skill_target,
        "applicability": applicability,
        "sweep_parameter_key": "scenario_scale",
        "parameters": (
            LabParameter(key="scenario_scale", label=parameter_labels[0], kind="integer", minimum=1, maximum=5, step=1, default=3, description="控制实验案例的复杂程度。"),
            LabParameter(key="input_size", label=parameter_labels[1], kind="integer", minimum=1, maximum=5, step=1, default=3, description="控制本轮冻结输入规模或结构规模。"),
            LabParameter(key="guidance_level", label=parameter_labels[2], kind="float", minimum=0.2, maximum=1, step=0.1, default=0.6, description="控制实验中可见提示和分步支架的强度。"),
            LabParameter(key="evidence_threshold", label=parameter_labels[3], kind="float", minimum=0.4, maximum=0.9, step=0.05, default=0.65, description="控制结论被视为有证据的最低阈值。"),
        ),
        "metrics": tuple(
            LabMetric(key=key, label=label, higher_is_better=higher, acceptance_threshold=threshold)
            for key, label, higher, threshold in metric_definitions
        ),
        "public_scenarios": scenarios,
        "checker_version": f"lab.{template_id}.hidden.v1",
        "hidden_categories": tuple(key for key, _, _, _ in metric_definitions),
        "static_fallback": "展示冻结案例和参数说明；静态模式不产生隐藏验收证据。",
    })


_TEMPLATES = {
    "sample-frequency-estimation": _template({
        "template_id": "sample-frequency-estimation", "template_version": "1.0.1",
        "title": "样本频率与总体比例",
        "summary": "重复抽取同一总体的样本，比较单次频率和多次抽样的波动。",
        "skill_target": "用样本频率估计总体比例，解释样本量、抽样波动与下一次事件的不确定性。",
        "applicability": "频率与概率估计、互补事件、独立同分布抽样和样本量；总体比例在教学模型中已知。",
        "sweep_parameter_key": "sample_size",
        "parameters": (
            LabParameter(key="event_probability", label="设定的总体比例", kind="float", minimum=0, maximum=1, step=.01, default=.11,
                description="教学总体中事件发生的概率p；每次试验独立且保持同一概率。真实业务中的总体比例需要估计。"),
            LabParameter(key="sample_size", label="每组样本量", kind="integer", minimum=20, maximum=2000, step=20, default=100, unit="次",
                description="每组独立试验的次数n；每次运行计算200组，每组按二项分布抽取事件计数。"),
            LabParameter(key="sample_seed", label="抽样批次", kind="integer", minimum=1, maximum=20, step=1, default=7,
                description="更换随机种子查看另一批样本；相同参数可复现。改变样本量会重新抽样，不是在同一组末尾追加记录。"),
        ),
        "metrics": (
            LabMetric(key="event_count", label="第一组事件次数", unit="次", higher_is_better=None, acceptance_threshold=None),
            LabMetric(key="sample_frequency", label="第一组频率", unit="%", higher_is_better=None, acceptance_threshold=None),
            LabMetric(key="complement_frequency", label="第一组互补频率", unit="%", higher_is_better=None, acceptance_threshold=None),
            LabMetric(key="mean_frequency", label="200组平均频率", unit="%", higher_is_better=None, acceptance_threshold=None),
            LabMetric(key="frequency_sd", label="200组频率标准差", unit="百分点", higher_is_better=None, acceptance_threshold=None),
            LabMetric(key="theoretical_se", label="理论频率标准差", unit="百分点", higher_is_better=None, acceptance_threshold=None),
        ),
        "public_scenarios": ("同一比例不同批次", "小样本与大样本的波动", "事件与互补事件"),
        "checker_version": "lab.sample-frequency-estimation.v1",
        "hidden_categories": ("sample_consistency",),
        "static_fallback": "先计算两组事件次数除以各自总次数，写出对应的互补频率，再比较样本量。",
    }),
    "prediction-score-to-class": _template({
        "template_id": "prediction-score-to-class", "template_version": "1.0.1",
        "title": "从给定分数到分类结果",
        "summary": "改变一个阈值，逐行核对六个教学样本的类别；分清给定分数、预测类别与真实标签。",
        "skill_target": "按明确阈值判断类别，说明预测不读取真实标签，而核对预测是否正确需要真实标签。",
        "applicability": "监督学习的输入与标签、分类任务、模型分数到类别的决策；不讲模型复杂度或训练调参。",
        "sweep_parameter_key": "decision_threshold",
        "parameters": (
            LabParameter(key="decision_threshold", label="判为类别1的阈值", kind="float",
                minimum=0, maximum=1, step=0.05, default=0.5,
                description="给定分数大于或等于阈值判为1，否则判为0；不改变原分数，不重新训练。"),
        ),
        "metrics": (
            LabMetric(key="predicted_positive", label="预测为1的样本", unit="个", higher_is_better=None, acceptance_threshold=None),
            LabMetric(key="predicted_negative", label="预测为0的样本", unit="个", higher_is_better=None, acceptance_threshold=None),
            LabMetric(key="matched_labels", label="与真实标签一致", unit="个", higher_is_better=True, acceptance_threshold=5),
        ),
        "public_scenarios": ("等于阈值的样本", "阈值提高后哪些类别变化", "判类后再核对真实标签"),
        "checker_version": "lab.prediction-score-to-class.v2",
        "hidden_categories": ("matched_labels",),
        "static_fallback": "六个给定分数依次为0.20、0.40、0.50、0.60、0.80、0.90，真实标签依次为0、0、1、0、1、1。先遮住标签按阈值判类，再核对。",
    }),
    "inventory-demand-boundary": _template({
        "template_id": "inventory-demand-boundary", "template_version": "1.0.0",
        "title": "需求波动与交货期库存实验",
        "summary": "用十天教学需求比较交货期内的供货与缺货，分别观察缺货延期和销售丢失。",
        "skill_target": "理解平均需求不能保证不缺货，区分现货满足、延期交货与销售丢失。",
        "applicability": "单店单品的随机需求、固定提前期、库存模型假设、缺货延期与销售丢失；不计算最优订货策略。",
        "sweep_parameter_key": "initial_stock",
        "parameters": (
            LabParameter(key="initial_stock", label="现有库存", kind="integer", minimum=0, maximum=60, step=1, default=12, unit="件", description="每个交货期案例起点的现货；本轮结束前没有新货到达，也没有期初积欠。"),
            LabParameter(key="lead_days", label="固定交货期", kind="integer", minimum=1, maximum=5, step=1, default=2, unit="天", description="每个案例均采用同一交货期；调整后比较另一组固定交货期，不模拟随机交货期。"),
            LabParameter(key="demand_variation", label="需求波动倍数", kind="float", minimum=0, maximum=2, step=0.25, default=1, description="教学需求为5.5+倍数×(原需求−5.5)。倍数0表示每日5.5件，倍数1保留原波动；小数表示连续需求近似。"),
            LabParameter(key="backorder", label="缺货处理（0丢失 / 1延期）", kind="integer", minimum=0, maximum=1, step=1, default=0, description="0：未满足需求成为丢失销售；1：全部保留为等待下一次交货的积欠。本实验不模拟下一次到货后的清偿。"),
        ),
        "metrics": (
            LabMetric(key="immediate_fill_rate", label="现货满足比例", unit="%", higher_is_better=True, acceptance_threshold=95),
            LabMetric(key="average_unmet", label="每个交货期平均未满足需求", unit="件", higher_is_better=False, acceptance_threshold=.5),
            LabMetric(key="average_backlog", label="交货前平均积欠", unit="件", higher_is_better=False, acceptance_threshold=.5),
            LabMetric(key="average_lost", label="平均丢失销售", unit="件", higher_is_better=False, acceptance_threshold=.5),
        ),
        "public_scenarios": ("每日相同需求", "平均值相同但需求波动", "较长的固定交货期", "缺货延期与销售丢失"),
        "checker_version": "lab.inventory-demand-boundary.v1",
        "hidden_categories": ("immediate_fill_rate", "average_unmet", "average_backlog", "average_lost"),
        "static_fallback": "教学需求为4、6、5、7、5、6、4、8、5、5；可先在纸上比较相邻两天需求与12件现货。",
    }),
    "parallel-training-throughput": _template({
        "template_id": "parallel-training-throughput", "template_version": "1.0.0",
        "title": "并行计算与通信重叠实验",
        "summary": "按串行比例、设备数和通信耗时计算一步训练用时，比较并行加速与通信重叠的收益。",
        "skill_target": "解释并行加速为什么受串行部分和通信约束，区分理想上限与实际测量。",
        "applicability": "计算性能、异步计算、并行训练、Amdahl定律、通信与计算重叠。",
        "sweep_parameter_key": "devices",
        "parameters": (
            LabParameter(key="devices", label="计算设备数", kind="integer", minimum=1, maximum=16, step=1, default=4, unit="个", description="固定总工作量，增加参与并行计算的设备。"),
            LabParameter(key="parallel_fraction", label="可并行比例", kind="float", minimum=0, maximum=1, step=0.05, default=0.9, description="单设备计算时间中可以均分到多设备的比例，其余部分仍需串行执行。"),
            LabParameter(key="communication_seconds", label="每增加一台的通信耗时", kind="float", minimum=0, maximum=20, step=0.5, default=2, unit="秒", description="教学模型假设总通信耗时随额外设备数线性增加，不代表某种真实集群拓扑。"),
            LabParameter(key="overlap_fraction", label="通信重叠比例", kind="float", minimum=0, maximum=1, step=0.05, default=0.5, description="被计算掩盖的通信比例；设为1代表理想的完全重叠。"),
            LabParameter(key="serial_seconds", label="单设备计算耗时", kind="integer", minimum=20, maximum=200, step=10, default=100, unit="秒", description="相同工作量在单设备上完成计算的用时，不含跨设备通信。"),
        ),
        "metrics": (
            LabMetric(key="step_seconds", label="一步训练耗时", unit="秒", higher_is_better=False, acceptance_threshold=40),
            LabMetric(key="speedup", label="加速比", unit="倍", higher_is_better=True, acceptance_threshold=2),
            LabMetric(key="parallel_efficiency", label="并行效率", higher_is_better=True, acceptance_threshold=0.65),
        ),
        "public_scenarios": ("单设备基线", "串行瓶颈", "无通信理想上限", "通信开销", "通信与计算重叠"),
        "checker_version": "lab.parallel-training.hidden.v1", "hidden_categories": ("step_seconds", "speedup", "parallel_efficiency"),
        "static_fallback": "可阅读Amdahl定律与通信说明；运行后查看本组参数的计算结果。",
    }),
    "exploratory-data-distribution": _template({
        "template_id": "exploratory-data-distribution", "template_version": "1.0.0",
        "title": "异常值与缺失数据观察实验",
        "summary": "用30到70的41个合成观测值，比较高值异常和低值缺失怎样改变均值、中位数与数据完整性。",
        "skill_target": "能够用实际统计量区分异常值影响和非随机缺失偏差，不把缺失或极端值一律删除。",
        "applicability": "探索性数据分析、描述统计、均值、中位数、异常值与缺失模式。",
        "sweep_parameter_key": "outlier_count",
        "parameters": (
            LabParameter(key="outlier_count", label="高值异常数量", kind="integer", minimum=0, maximum=8, step=1, default=2, unit="个", description="把原数据末尾的若干高值替换为指定异常值。"),
            LabParameter(key="outlier_value", label="异常值大小", kind="integer", minimum=70, maximum=200, step=10, default=100, description="仅影响被替换的高值，其他观测值保持不变。"),
            LabParameter(key="missing_count", label="低值缺失数量", kind="integer", minimum=0, maximum=8, step=1, default=2, unit="个", description="从原数据最低值开始移除若干观测，模拟非随机缺失，不用零代替缺失值。"),
        ),
        "metrics": (
            LabMetric(key="mean_shift", label="均值偏移幅度", higher_is_better=False, acceptance_threshold=5),
            LabMetric(key="median_shift", label="中位数偏移幅度", higher_is_better=False, acceptance_threshold=5),
            LabMetric(key="available_fraction", label="保留观测比例", higher_is_better=True, acceptance_threshold=0.8),
        ),
        "public_scenarios": ("完整数据基线", "高值异常", "低值缺失", "均值与中位数对照"),
        "checker_version": "lab.eda.hidden.v1", "hidden_categories": ("mean_shift", "median_shift", "available_fraction"),
        "static_fallback": "可阅读统计方法；只有实际运行才能形成观察结果。",
    }),
    "sklearn-fit-predict": _template({
        "template_id": "sklearn-fit-predict", "template_version": "1.0.0",
        "title": "训练与预测接口实验",
        "summary": "在固定的300条双月形合成数据上实际调用scikit-learn训练决策树，再预测一个新样本；只用验证集比较参数。",
        "skill_target": "区分训练时的fit、预测时的predict和验证评分，理解训练量、树深度与新样本预测的关系。",
        "applicability": "scikit-learn、sklearn、训练与推理接口、fit与predict。",
        "sweep_parameter_key": "max_depth",
        "parameters": (
            LabParameter(key="max_depth", label="树的最大深度", kind="integer", minimum=1, maximum=10, step=1, default=3, description="每轮用相同数据重新训练，观察容量变化，不用验证集拟合。"),
            LabParameter(key="training_samples", label="训练样本数量", kind="integer", minimum=40, maximum=240, step=40, default=160, unit="条", description="从固定240条训练池依次取样，另外60条验证数据始终不参与训练。"),
            LabParameter(key="prediction_x", label="新样本第一维", kind="float", minimum=-2, maximum=3, step=0.25, default=1.5, description="新样本第二维固定为0.25；此参数只影响预测，不改变训练或验证得分。"),
        ),
        "metrics": (
            LabMetric(key="training_score", label="训练准确率", higher_is_better=True, acceptance_threshold=0.75),
            LabMetric(key="validation_score", label="验证准确率", higher_is_better=True, acceptance_threshold=0.75),
            LabMetric(key="generalization_gap", label="训练与验证差距", higher_is_better=False, acceptance_threshold=0.2),
        ),
        "public_scenarios": ("训练后预测", "不同训练量", "浅树与深树", "改变新样本不重新选参"),
        "checker_version": "lab.sklearn.hidden.v1", "hidden_categories": ("training_score", "validation_score", "generalization_gap"),
        "static_fallback": "可阅读训练和预测方法；未运行时不产生模型分数。",
    }),
    "rag-hybrid-tuning": _template({
        "template_id": "rag-hybrid-tuning",
        "template_version": "1.0.0",
        "title": "混合检索调优实验",
        "summary": "调节关键词与向量检索权重，在质量、延迟和隔离约束之间取得平衡。",
        "skill_target": "能够调节混合检索参数并保持 owner 与版本隔离。",
        "applicability": "检索、RAG、向量检索、关键词检索、重排、召回率与检索延迟。",
        "sweep_parameter_key": "top_k",
        "parameters": (
            LabParameter(key="keyword_weight", label="关键词权重", kind="float", minimum=0, maximum=1, step=0.05, default=0.5, description="控制精确术语匹配在混合检索中的占比。"),
            LabParameter(key="vector_weight", label="向量权重", kind="float", minimum=0, maximum=1, step=0.05, default=0.5, description="控制语义相似度在混合检索中的占比。"),
            LabParameter(key="top_k", label="召回数量", kind="integer", minimum=1, maximum=10, step=1, default=3, unit="条", description="决定进入重排阶段的候选来源数量。"),
            LabParameter(key="rerank_threshold", label="重排阈值", kind="float", minimum=0, maximum=1, step=0.05, default=0.5, description="控制候选来源进入最终上下文所需的最低重排得分。"),
        ),
        "metrics": (
            LabMetric(key="recall_at_k", label="召回率", higher_is_better=True, acceptance_threshold=0.72),
            LabMetric(key="ranking_score", label="排序质量", higher_is_better=True, acceptance_threshold=0.71),
            LabMetric(key="average_latency_ms", label="平均延迟", unit="ms", higher_is_better=False, acceptance_threshold=170),
        ),
        "public_scenarios": ("精确术语", "语义改写", "课程范围", "版本范围", "用户隔离"),
        "checker_version": "lab.rag.hidden.v1",
        "hidden_categories": ("retrieval_quality", "ranking_quality", "isolation", "version_scope"),
        "static_fallback": "展示参数说明和公开场景；静态模式不产生隐藏验收证据。",
    }),
    "classifier-threshold-calibration": _template({
        "template_id": "classifier-threshold-calibration",
        "template_version": "1.0.0",
        "title": "分类阈值校准实验",
        "summary": "调节决策阈值与拒判区间，观察准确性、误报率、覆盖率和校准误差。",
        "skill_target": "能够解释分类阈值、拒判策略与可靠性指标之间的权衡。",
        "applicability": "分类、逻辑回归、线性分类、混淆矩阵、精确率、召回率、阈值、校准与误报。",
        "sweep_parameter_key": "decision_threshold",
        "parameters": (
            LabParameter(key="decision_threshold", label="决策阈值", kind="float", minimum=0.2, maximum=0.8, step=0.05, default=0.5, description="控制样本被判为正类所需的最低置信度。"),
            LabParameter(key="abstain_margin", label="拒判区间", kind="float", minimum=0, maximum=0.25, step=0.025, default=0.05, description="在决策边界附近保留不自动判断的区间。"),
            LabParameter(key="calibration_bins", label="校准分桶", kind="integer", minimum=4, maximum=20, step=1, default=10, unit="组", description="用于比较预测置信度与真实频率的分桶数量。"),
        ),
        "metrics": (
            LabMetric(key="balanced_accuracy", label="平衡准确率", higher_is_better=True, acceptance_threshold=0.84),
            LabMetric(key="false_positive_rate", label="误报率", higher_is_better=False, acceptance_threshold=0.13),
            LabMetric(key="coverage", label="覆盖率", higher_is_better=True, acceptance_threshold=0.82),
            LabMetric(key="calibration_error", label="校准误差", higher_is_better=False, acceptance_threshold=0.075),
        ),
        "public_scenarios": ("类别均衡", "类别偏斜", "边界样本", "低置信拒判", "概率校准"),
        "checker_version": "lab.classifier.hidden.v1",
        "hidden_categories": ("balanced_quality", "false_positives", "coverage", "calibration"),
        "static_fallback": "展示冻结样本分布和参数说明；静态模式不产生隐藏验收证据。",
    }),
    "data-processing-sensitivity": _template({
        "template_id": "data-processing-sensitivity",
        "template_version": "1.0.0",
        "title": "数据处理性能与质量实验",
        "summary": "调节数据规模、特征数、向量化比例和缺失率，观察吞吐、耗时、内存与可用数据比例。",
        "skill_target": "能够解释数据规模、向量化处理和数据质量之间的工程权衡。",
        "applicability": "Python 数据处理、NumPy、Pandas、向量化、探索性分析、数据清洗与特征准备。",
        "sweep_parameter_key": "vectorization_ratio",
        "parameters": (
            LabParameter(key="row_count", label="数据行数", kind="integer", minimum=1000, maximum=10000, step=1000, default=5000, unit="行", description="控制本轮处理的数据记录规模。"),
            LabParameter(key="feature_count", label="特征数量", kind="integer", minimum=2, maximum=20, step=1, default=8, unit="列", description="控制每条记录参与计算的特征维度。"),
            LabParameter(key="vectorization_ratio", label="向量化比例", kind="float", minimum=0, maximum=1, step=0.1, default=0.7, description="表示使用数组批量运算替代逐行循环的比例。"),
            LabParameter(key="missing_rate", label="缺失比例", kind="float", minimum=0, maximum=0.5, step=0.05, default=0.1, description="表示冻结样本中需要清洗或填补的数据比例。"),
        ),
        "metrics": (
            LabMetric(key="processing_time_ms", label="处理耗时", unit="ms", higher_is_better=False, acceptance_threshold=100),
            LabMetric(key="memory_mb", label="估算内存", unit="MB", higher_is_better=False, acceptance_threshold=2),
            LabMetric(key="usable_data_ratio", label="可用数据比例", higher_is_better=True, acceptance_threshold=0.8),
            LabMetric(key="throughput_rows_s", label="处理吞吐", unit="行/秒", higher_is_better=True, acceptance_threshold=3500),
        ),
        "public_scenarios": ("逐行循环", "部分向量化", "完全向量化", "高缺失率", "宽表数据"),
        "checker_version": "lab.data-processing.hidden.v1",
        "hidden_categories": ("processing_time_ms", "memory_mb", "usable_data_ratio", "throughput_rows_s"),
        "static_fallback": "展示冻结数据规模和处理参数；静态模式不产生实验结果或学习证据。",
    }),
    "model-complexity-generalization": _template({
        "template_id": "model-complexity-generalization",
        "template_version": "1.0.0",
        "title": "模型复杂度与泛化实验",
        "summary": "调节模型复杂度、训练样本量和正则强度，观察训练表现、验证表现、泛化差距与推理成本。",
        "skill_target": "能够识别欠拟合、合适容量和过拟合，并说明样本与正则化的作用。",
        "applicability": "监督学习、决策树、集成学习、过拟合、欠拟合、正则化、模型容量与泛化。",
        "sweep_parameter_key": "model_complexity",
        "parameters": (
            LabParameter(key="model_complexity", label="模型复杂度", kind="integer", minimum=1, maximum=10, step=1, default=5, unit="级", description="表示模型能够表达的规则复杂程度。"),
            LabParameter(key="training_samples", label="训练样本量", kind="integer", minimum=100, maximum=1000, step=100, default=500, unit="条", description="设置教学模拟中的样本规模；本页不加载数据进行真实训练。"),
            LabParameter(key="regularization", label="正则强度", kind="float", minimum=0, maximum=1, step=0.05, default=0.2, description="控制对过度复杂模型的惩罚强度。"),
        ),
        "metrics": (
            LabMetric(key="training_score", label="训练得分", higher_is_better=True, acceptance_threshold=0.76),
            LabMetric(key="validation_score", label="验证得分", higher_is_better=True, acceptance_threshold=0.75),
            LabMetric(key="generalization_gap", label="泛化差距", higher_is_better=False, acceptance_threshold=0.12),
            LabMetric(key="inference_cost", label="推理成本", unit="相对值", higher_is_better=False, acceptance_threshold=45),
        ),
        "public_scenarios": ("低容量欠拟合", "合适容量", "高容量过拟合", "增加样本", "增强正则"),
        "checker_version": "lab.generalization.hidden.v1",
        "hidden_categories": ("training_score", "validation_score", "generalization_gap", "inference_cost"),
        "static_fallback": "展示训练/验证关系说明；静态模式不产生拟合曲线或学习证据。",
    }),
    "clustering-configuration": _template({
        "template_id": "clustering-configuration",
        "template_version": "1.0.0",
        "title": "聚类配置与稳定性实验",
        "summary": "调节聚类数、特征尺度、噪声和初始化次数，观察轮廓系数、稳定性、覆盖率与计算成本。",
        "skill_target": "能够解释聚类数、特征缩放、噪声与初始化对无监督聚类结果的影响。",
        "applicability": "无监督学习、K-Means、聚类数、特征缩放、聚类稳定性与轮廓系数。",
        "sweep_parameter_key": "cluster_count",
        "parameters": (
            LabParameter(key="cluster_count", label="聚类数量", kind="integer", minimum=2, maximum=10, step=1, default=4, unit="类", description="控制算法尝试划分的簇数量。"),
            LabParameter(key="feature_scale", label="特征尺度", kind="float", minimum=0.5, maximum=2, step=0.1, default=1, description="表示特征经过缩放后的相对量级。"),
            LabParameter(key="noise_level", label="噪声水平", kind="float", minimum=0, maximum=0.5, step=0.05, default=0.1, description="表示冻结样本中偏离主要簇结构的数据比例。"),
            LabParameter(key="initialization_runs", label="初始化次数", kind="integer", minimum=1, maximum=20, step=1, default=10, unit="次", description="控制不同初始中心的重复尝试次数。"),
        ),
        "metrics": (
            LabMetric(key="silhouette_score", label="轮廓系数", higher_is_better=True, acceptance_threshold=0.65),
            LabMetric(key="cluster_stability", label="聚类稳定性", higher_is_better=True, acceptance_threshold=0.7),
            LabMetric(key="assignment_coverage", label="分配覆盖率", higher_is_better=True, acceptance_threshold=0.8),
            LabMetric(key="compute_cost", label="计算成本", unit="相对值", higher_is_better=False, acceptance_threshold=120),
        ),
        "public_scenarios": ("聚类数过少", "聚类数合适", "聚类数过多", "未缩放特征", "噪声样本"),
        "checker_version": "lab.clustering.hidden.v1",
        "hidden_categories": ("silhouette_score", "cluster_stability", "assignment_coverage", "compute_cost"),
        "static_fallback": "展示聚类配置和样本摘要；静态模式不生成簇分配或学习证据。",
    }),
    "dimensionality-reduction": _template({
        "template_id": "dimensionality-reduction",
        "template_version": "1.0.0",
        "title": "降维信息保留实验",
        "summary": "调节保留维数、主方向强度、噪声和样本量，观察解释方差、重构质量、压缩率与计算成本。",
        "skill_target": "能够解释降维维数与信息保留、压缩效率及噪声之间的权衡。",
        "applicability": "主成分分析、PCA、降维、解释方差、重构误差、特征压缩与可视化。",
        "sweep_parameter_key": "component_count",
        "parameters": (
            LabParameter(key="component_count", label="保留维数", kind="integer", minimum=1, maximum=10, step=1, default=3, unit="维", description="控制降维后保留的主成分数量。"),
            LabParameter(key="signal_strength", label="主方向强度", kind="float", minimum=0.5, maximum=1, step=0.05, default=0.8, description="表示数据方差集中在主要方向上的程度。"),
            LabParameter(key="noise_level", label="噪声水平", kind="float", minimum=0, maximum=0.5, step=0.05, default=0.1, description="表示不沿主要方向分布的随机变化比例。"),
            LabParameter(key="sample_size", label="样本数量", kind="integer", minimum=100, maximum=1000, step=100, default=500, unit="条", description="控制用于估计主方向的冻结样本规模。"),
        ),
        "metrics": (
            LabMetric(key="explained_variance", label="解释方差", higher_is_better=True, acceptance_threshold=0.7),
            LabMetric(key="reconstruction_quality", label="重构质量", higher_is_better=True, acceptance_threshold=0.65),
            LabMetric(key="compression_ratio", label="压缩比例", higher_is_better=True, acceptance_threshold=0.5),
            LabMetric(key="compute_cost", label="计算成本", unit="相对值", higher_is_better=False, acceptance_threshold=45),
        ),
        "public_scenarios": ("保留维数过少", "信息与压缩平衡", "高噪声", "小样本估计", "增加主成分"),
        "checker_version": "lab.dimensionality.hidden.v1",
        "hidden_categories": ("explained_variance", "reconstruction_quality", "compression_ratio", "compute_cost"),
        "static_fallback": "展示方差与维数说明；静态模式不生成主成分结果或学习证据。",
    }),
    "linear-algebra-probability": _template({
        "template_id": "linear-algebra-probability",
        "template_version": "1.0.0",
        "title": "向量、矩阵与概率计算实验",
        "summary": "调节向量尺度、矩阵维度、温度和稀疏度，观察点积、矩阵迹、概率熵与归一化误差。",
        "skill_target": "能够把向量运算、矩阵结构和概率归一化连接到可验证的数值结果。",
        "applicability": "向量、矩阵、线性代数、概率基础、点积、矩阵迹、softmax 与概率归一化。",
        "sweep_parameter_key": "vector_scale",
        "parameters": (
            LabParameter(key="vector_scale", label="向量尺度", kind="float", minimum=0.5, maximum=2, step=0.1, default=1, description="控制输入向量各分量的共同缩放倍数。"),
            LabParameter(key="matrix_dimension", label="矩阵维度", kind="integer", minimum=2, maximum=6, step=1, default=3, unit="维", description="控制方阵的行列维度，用于观察矩阵迹和计算规模。"),
            LabParameter(key="temperature", label="概率温度", kind="float", minimum=0.5, maximum=2, step=0.1, default=1, description="控制 softmax 分布的平滑程度，温度越高分布越均匀。"),
            LabParameter(key="sparsity", label="稀疏比例", kind="float", minimum=0, maximum=0.6, step=0.1, default=0.2, description="表示输入向量中被置零的分量比例。"),
        ),
        "metrics": (
            LabMetric(key="dot_product", label="向量点积", higher_is_better=True, acceptance_threshold=2.0),
            LabMetric(key="matrix_trace", label="矩阵迹", higher_is_better=True, acceptance_threshold=2.0),
            LabMetric(key="probability_entropy", label="概率熵", higher_is_better=True, acceptance_threshold=0.45),
            LabMetric(key="normalization_error", label="归一化误差", higher_is_better=False, acceptance_threshold=0.02),
        ),
        "public_scenarios": ("低温尖锐分布", "高温平滑分布", "稀疏向量", "小矩阵", "增大矩阵维度"),
        "checker_version": "lab.linear-algebra-probability.hidden.v1",
        "hidden_categories": ("dot_product", "matrix_trace", "probability_entropy", "normalization_error"),
        "static_fallback": "展示向量、矩阵和概率参数说明；静态模式不生成数值结果或学习证据。",
    }),
    "optimization-dynamics": _template({
        "template_id": "optimization-dynamics",
        "template_version": "1.0.0",
        "title": "优化与训练动态实验",
        "summary": "调节学习率、批量大小、训练轮次和正则强度，观察损失、收敛、稳定性与训练成本。",
        "skill_target": "能够判断学习率、批量大小和训练轮次对收敛速度与稳定性的影响。",
        "applicability": "梯度下降、反向传播、学习率、批量训练、训练轮次、损失函数与神经网络优化。",
        "sweep_parameter_key": "learning_rate",
        "parameters": (
            LabParameter(key="learning_rate", label="学习率", kind="float", minimum=0.01, maximum=0.5, step=0.01, default=0.1, description="控制每次梯度更新的步幅。"),
            LabParameter(key="batch_size", label="批量大小", kind="integer", minimum=8, maximum=128, step=8, default=32, unit="条", description="控制每次参数更新使用的样本数量。"),
            LabParameter(key="epochs", label="训练轮次", kind="integer", minimum=5, maximum=100, step=5, default=30, unit="轮", description="控制完整遍历训练数据的次数。"),
            LabParameter(key="regularization", label="正则强度", kind="float", minimum=0, maximum=1, step=0.05, default=0.1, description="控制对过大参数的惩罚强度。"),
        ),
        "metrics": (
            LabMetric(key="final_loss", label="最终损失", higher_is_better=False, acceptance_threshold=0.5),
            LabMetric(key="convergence_score", label="收敛程度", higher_is_better=True, acceptance_threshold=0.7),
            LabMetric(key="stability_score", label="训练稳定性", higher_is_better=True, acceptance_threshold=0.7),
            LabMetric(key="training_cost", label="训练成本", unit="相对值", higher_is_better=False, acceptance_threshold=650),
        ),
        "public_scenarios": ("学习率过低", "稳定收敛", "学习率过高", "小批量波动", "增加训练轮次"),
        "checker_version": "lab.optimization.hidden.v1",
        "hidden_categories": ("final_loss", "convergence_score", "stability_score", "training_cost"),
        "static_fallback": "展示优化参数和训练阶段；静态模式不生成损失曲线或学习证据。",
    }),
}


# Course-wide coverage families.  They expose the same bounded numeric
# controls, while their titles, metrics and scenarios remain specific to the
# concept being practised.  Runtime evaluation below keeps the simulation
# deterministic and never executes learner-supplied code.
_TEMPLATES.update({
    spec["template_id"]: _coverage_template(
        template_id=spec["template_id"],
        title=spec["title"],
        summary=spec["summary"],
        skill_target=spec["skill_target"],
        applicability=spec["applicability"],
        parameter_labels=spec["parameter_labels"],
        metric_definitions=spec["metric_definitions"],
        scenarios=spec["scenarios"],
    )
    for spec in (
        {
            "template_id": "algorithmic-problem-framing",
            "title": "算法问题建模实验",
            "summary": "把业务目标拆成输入、约束、输出和验收条件，比较建模完整度与可验证性。",
            "skill_target": "能够把自然语言需求转成可执行的算法问题。",
            "applicability": "人工智能概览、算法问题建模、需求拆解、输入输出与约束。",
            "parameter_labels": ("案例复杂度", "需求规模", "提示支架", "验收阈值"),
            "metric_definitions": (("problem_clarity", "问题定义清晰度", True, 0.72), ("constraint_coverage", "约束覆盖率", True, 0.68), ("testability", "可测试性", True, 0.7), ("ambiguity", "歧义风险", False, 0.28)),
            "scenarios": ("分类任务", "预测任务", "检索任务", "资源调度", "验收用例"),
        },
        {
            "template_id": "algorithm-complexity",
            "title": "时间与空间复杂度实验",
            "summary": "改变输入规模，比较常见算法的增长曲线、内存占用和可扩展边界。",
            "skill_target": "能够从操作次数和辅助空间判断算法复杂度。",
            "applicability": "时间复杂度、空间复杂度、渐进分析、输入规模。",
            "parameter_labels": ("规模档位", "输入规模", "提示支架", "验收阈值"),
            "metric_definitions": (("growth_prediction", "增长趋势判断", True, 0.72), ("space_accounting", "空间核算准确度", True, 0.68), ("scalability", "可扩展性", True, 0.65), ("operation_cost", "操作成本", False, 3.0)),
            "scenarios": ("常数", "对数", "线性", "平方", "指数增长"),
        },
        {
            "template_id": "data-structure-operations",
            "title": "数据结构操作与代价实验",
            "summary": "选择不同结构规模，观察插入、删除、查询的正确性、稳定性与操作代价。",
            "skill_target": "能够根据操作目标选择合适的数据结构。",
            "applicability": "数组、字符串、链表、栈、队列、哈希表、Trie、LRU。",
            "parameter_labels": ("操作场景", "结构规模", "提示支架", "验收阈值"),
            "metric_definitions": (("operation_correctness", "操作正确率", True, 0.75), ("invariant_coverage", "结构不变量覆盖", True, 0.7), ("update_stability", "更新稳定性", True, 0.68), ("operation_cost", "操作代价", False, 3.0)),
            "scenarios": ("随机访问", "顺序插入", "先进先出", "键值查找", "淘汰策略"),
        },
        {
            "template_id": "tree-traversal",
            "title": "树结构遍历与平衡实验",
            "summary": "调整树的规模与形态，逐步观察遍历顺序、搜索命中和高度变化。",
            "skill_target": "能够维护树的结构不变量并选择遍历方式。",
            "applicability": "二叉树、二叉搜索树、平衡树、遍历、前驱后继。",
            "parameter_labels": ("树形态", "节点规模", "提示支架", "验收阈值"),
            "metric_definitions": (("traversal_correctness", "遍历正确率", True, 0.75), ("ordering_invariant", "有序性不变量", True, 0.72), ("search_efficiency", "搜索效率", True, 0.68), ("height_cost", "树高代价", False, 3.0)),
            "scenarios": ("完全二叉树", "退化链", "搜索树", "平衡旋转", "层序遍历"),
        },
        {
            "template_id": "heap-priority-queue",
            "title": "堆与优先队列实验",
            "summary": "改变队列规模和优先级分布，观察堆序不变量、Top-K 结果与调整成本。",
            "skill_target": "能够解释堆序、上浮下沉和优先队列的复杂度。",
            "applicability": "堆、优先队列、Top-K、任务调度。",
            "parameter_labels": ("优先级分布", "任务规模", "提示支架", "验收阈值"),
            "metric_definitions": (("heap_invariant", "堆序不变量", True, 0.76), ("topk_precision", "Top-K 准确度", True, 0.75), ("schedule_fairness", "调度公平性", True, 0.66), ("adjustment_cost", "调整成本", False, 3.0)),
            "scenarios": ("最大堆", "最小堆", "Top-K", "动态插入", "任务调度"),
        },
        {
            "template_id": "graph-traversal",
            "title": "图表示、遍历与路径实验",
            "summary": "调整图规模和连接密度，观察 BFS/DFS 访问顺序、连通性和路径代价。",
            "skill_target": "能够从图表示选择遍历算法并解释访问结果。",
            "applicability": "图表示、BFS、DFS、拓扑排序、最短路、连通性、图神经网络消息传递。",
            "parameter_labels": ("连接密度", "节点规模", "提示支架", "验收阈值"),
            "metric_definitions": (("visit_coverage", "节点访问覆盖", True, 0.75), ("path_correctness", "路径正确率", True, 0.72), ("connectivity_confidence", "连通性判断", True, 0.7), ("edge_scan_cost", "边扫描成本", False, 3.0)),
            "scenarios": ("邻接表", "邻接矩阵", "BFS", "DFS", "拓扑与最短路"),
        },
        {
            "template_id": "sorting-strategy",
            "title": "排序策略与稳定性实验",
            "summary": "改变数据规模和重复值比例，比较排序正确性、稳定性与比较次数。",
            "skill_target": "能够根据数据特征选择排序算法并解释复杂度。",
            "applicability": "比较排序、归并排序、快速排序、堆排序、线性排序与稳定性。",
            "parameter_labels": ("数据分布", "元素规模", "提示支架", "验收阈值"),
            "metric_definitions": (("sorted_correctness", "有序正确率", True, 0.8), ("stability_score", "稳定性", True, 0.7), ("adaptive_fit", "分布适配度", True, 0.68), ("comparison_cost", "比较成本", False, 3.0)),
            "scenarios": ("近乎有序", "随机数据", "大量重复", "稳定排序", "线性排序"),
        },
        {
            "template_id": "search-boundary",
            "title": "查找边界与指针收缩实验",
            "summary": "逐步调整目标和区间，观察二分边界、双指针移动与终止条件。",
            "skill_target": "能够维护循环不变量并正确处理查找边界。",
            "applicability": "二分查找、边界处理、哈希查找、双指针。",
            "parameter_labels": ("目标难度", "序列规模", "提示支架", "验收阈值"),
            "metric_definitions": (("boundary_correctness", "边界正确率", True, 0.8), ("invariant_coverage", "循环不变量覆盖", True, 0.76), ("termination_safety", "终止安全性", True, 0.76), ("probe_cost", "探测次数", False, 3.0)),
            "scenarios": ("命中元素", "左边界", "右边界", "未命中", "双指针窗口"),
        },
        {
            "template_id": "recursion-backtracking",
            "title": "递归、分治与回溯实验",
            "summary": "调整搜索深度和剪枝强度，观察递归树规模、解空间覆盖与回溯成本。",
            "skill_target": "能够写出递归状态、终止条件并判断剪枝收益。",
            "applicability": "递归、分治、回溯、剪枝、搜索空间。",
            "parameter_labels": ("搜索深度", "问题规模", "提示支架", "验收阈值"),
            "metric_definitions": (("solution_correctness", "解正确率", True, 0.76), ("state_coverage", "状态覆盖", True, 0.7), ("pruning_gain", "剪枝收益", True, 0.65), ("branch_cost", "分支成本", False, 3.0)),
            "scenarios": ("递归基", "分治拆分", "排列组合", "约束剪枝", "搜索树"),
        },
        {
            "template_id": "algorithmic-strategy",
            "title": "贪心策略与可行性实验",
            "summary": "改变局部选择与约束规模，比较贪心解的可行性、质量和反例风险。",
            "skill_target": "能够识别贪心选择性质并用反例检验策略。",
            "applicability": "贪心策略、局部最优、可行性、反例与近似。",
            "parameter_labels": ("选择偏好", "约束规模", "提示支架", "验收阈值"),
            "metric_definitions": (("feasibility", "可行性", True, 0.78), ("solution_quality", "解质量", True, 0.7), ("counterexample_resistance", "反例抵抗力", True, 0.65), ("decision_cost", "决策成本", False, 3.0)),
            "scenarios": ("区间选择", "背包近似", "任务安排", "最小生成树", "反例检验"),
        },
        {
            "template_id": "dynamic-programming",
            "title": "动态规划状态转移实验",
            "summary": "调节状态规模和转移密度，观察子问题复用、边界条件与最优值收敛。",
            "skill_target": "能够定义状态、转移方程和边界条件。",
            "applicability": "动态规划、背包、区间 DP、路径 DP、状态压缩。",
            "parameter_labels": ("转移密度", "状态规模", "提示支架", "验收阈值"),
            "metric_definitions": (("transition_correctness", "转移正确率", True, 0.78), ("subproblem_reuse", "子问题复用", True, 0.72), ("boundary_safety", "边界安全性", True, 0.76), ("state_cost", "状态成本", False, 3.0)),
            "scenarios": ("线性 DP", "背包", "区间 DP", "树形 DP", "路径规划"),
        },
        {
            "template_id": "neural-architecture",
            "title": "神经网络结构与表征实验",
            "summary": "改变网络深度、宽度和样本规模，观察表征能力、泛化和推理成本。",
            "skill_target": "能够把网络结构变化联系到表征能力与泛化表现。",
            "applicability": "多层感知机、卷积网络、循环网络、视觉表征、预训练模型。",
            "parameter_labels": ("结构深度", "样本规模", "提示支架", "验收阈值"),
            "metric_definitions": (("representation_quality", "表征质量", True, 0.72), ("generalization", "泛化表现", True, 0.7), ("task_coverage", "任务覆盖", True, 0.72), ("inference_cost", "推理成本", False, 3.0)),
            "scenarios": ("全连接", "卷积特征", "序列记忆", "视觉分类", "预训练迁移"),
        },
        {
            "template_id": "attention-mechanics",
            "title": "注意力与 Transformer 机制实验",
            "summary": "改变序列长度、头数和温度，观察 Q/K/V 对齐、注意力分布与计算代价。",
            "skill_target": "能够解释缩放点积、多头注意力和位置编码的作用。",
            "applicability": "注意力机制、QKV、自注意力、多头、Transformer、位置编码。",
            "parameter_labels": ("注意力温度", "序列规模", "提示支架", "验收阈值"),
            "metric_definitions": (("alignment_quality", "QKV 对齐质量", True, 0.74), ("attention_focus", "注意力聚焦度", True, 0.68), ("position_coverage", "位置信息覆盖", True, 0.7), ("attention_cost", "注意力成本", False, 3.0)),
            "scenarios": ("缩放点积", "多头分工", "位置编码", "因果掩码", "长序列"),
        },
        {
            "template_id": "language-generation",
            "title": "语言模型生成与对齐实验",
            "summary": "改变生成温度、上下文长度和约束强度，观察可控性、覆盖度与事实风险。",
            "skill_target": "能够理解自回归生成、采样参数和指令对齐的权衡。",
            "applicability": "自然语言处理、预训练、大语言模型、生成、指令微调与偏好对齐。",
            "parameter_labels": ("生成温度", "上下文规模", "提示支架", "验收阈值"),
            "metric_definitions": (("instruction_following", "指令遵循", True, 0.72), ("content_coverage", "内容覆盖", True, 0.7), ("coherence", "连贯性", True, 0.72), ("hallucination_risk", "幻觉风险", False, 3.0)),
            "scenarios": ("分类生成", "摘要生成", "中文问答", "指令遵循", "偏好约束"),
        },
        {
            "template_id": "agent-workflow",
            "title": "RAG、工具调用与 Agent 工作流实验",
            "summary": "调整检索范围、工具步骤和停止条件，观察证据覆盖、任务完成和失败恢复。",
            "skill_target": "能够设计带证据、工具和停止条件的智能体工作流。",
            "applicability": "RAG、工具调用、ReAct、Agent、Coding Agent、MCP、个性化学习智能体。",
            "parameter_labels": ("工作流复杂度", "步骤规模", "提示支架", "验收阈值"),
            "metric_definitions": (("evidence_coverage", "证据覆盖", True, 0.74), ("task_completion", "任务完成度", True, 0.72), ("recovery_quality", "失败恢复质量", True, 0.68), ("tool_cost", "工具调用成本", False, 3.0)),
            "scenarios": ("证据检索", "工具调用", "多步推理", "代码测试", "失败恢复"),
        },
    )
})


from app.concept_labs import BY_ID as CONCEPT_LABS, template_specs as concept_template_specs

_TEMPLATES.update({spec["template_id"]: _template(spec) for spec in concept_template_specs()})


def list_templates() -> tuple[LabTemplate, ...]:
    return tuple(_TEMPLATES[key] for key in sorted(_TEMPLATES))


def get_template(template_id: str) -> LabTemplate:
    template = _TEMPLATES.get(template_id)
    if template is None:
        _fail("lab_template_unknown", "当前知识点没有匹配到可用的交互实验模板。")
    return template


def validate_parameters(template: LabTemplate, values: dict[str, Any]) -> dict[str, float | int]:
    definitions = {item.key: item for item in template.parameters}
    if set(values) != set(definitions):
        _fail("lab_parameters_invalid", "参数集合与所选实验模板不一致。")
    result: dict[str, float | int] = {}
    for key, definition in definitions.items():
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail("lab_parameter_type_invalid", f"参数“{definition.label}”必须是数值。")
        if definition.kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            _fail("lab_parameter_type_invalid", f"参数“{definition.label}”必须是整数。")
        numeric = float(value)
        if numeric < definition.minimum or numeric > definition.maximum:
            _fail("lab_parameter_out_of_bounds", f"参数“{definition.label}”超出允许范围。")
        steps = (numeric - definition.minimum) / definition.step
        if abs(steps - round(steps)) > 1e-7:
            _fail("lab_parameter_step_invalid", f"参数“{definition.label}”不符合步长要求。")
        result[key] = int(value) if definition.kind == "integer" else round(numeric, 6)
    if template.template_id == "rag-hybrid-tuning":
        if abs(float(result["keyword_weight"]) + float(result["vector_weight"]) - 1.0) > 1e-7:
            _fail("lab_parameter_relation_invalid", "关键词权重与向量权重之和必须等于 1。")
    return result


def validate_resource_template_content(content: Any) -> LabTemplate:
    """Validate a released resource against the same template used at runtime."""
    template = get_template(str(content.templateId))
    declared = {item.key: item for item in content.parameters}
    expected = {item.key: item for item in template.parameters}
    if set(declared) != set(expected):
        _fail("interactive_model_template_mismatch", "这份资源的参数与所选实验模板不一致，请重新生成可交互模型。")
    for key, definition in expected.items():
        item = declared[key]
        if (
            not item.label.strip()
            or item.kind != definition.kind
            or item.unit != definition.unit
            or float(item.minimum) != float(definition.minimum)
            or float(item.maximum) != float(definition.maximum)
            or float(item.step) != float(definition.step)
            or float(item.default) != float(definition.default)
        ):
            _fail("interactive_model_template_mismatch", "这份资源的参数范围与所选实验模板不一致，请重新生成可交互模型。")
    declared_series = {item.key: item for item in content.chart.series}
    expected_series = {item.key: item for item in template.metrics}
    if set(declared_series) != set(expected_series):
        _fail("interactive_model_template_mismatch", "这份资源的结果指标与所选实验模板不一致，请重新生成可交互模型。")
    for key, definition in expected_series.items():
        item = declared_series[key]
        if not item.label.strip() or item.unit != definition.unit or item.higherIsBetter != definition.higher_is_better:
            _fail("interactive_model_template_mismatch", "这份资源的结果指标定义与所选实验模板不一致，请重新生成可交互模型。")
    return template


def experiment_execution_info(template_id: str) -> dict[str, str]:
    """Describe the actual evaluator, independently of generated resource prose."""
    if template_id in CONCEPT_LABS:
        from app.concept_labs import execution_info
        return execution_info(template_id)
    if template_id == "sample-frequency-estimation":
        return {
            "mode": "synthetic_data_statistics", "label": "合成样本统计",
            "description": "在设定比例的教学总体中，实际抽取200组二项计数并统计频率。",
            "capabilities": "固定随机种子sample_seed，使用numpy.default_rng.binomial(n=sample_size,p=event_probability,size=200)。第一组展示事件计数、计数/n的频率和1−频率；另计算200组频率均值、样本标准差(ddof=1)，以及理论标准差sqrt(p*(1-p)/n)。比例与均值用百分数，标准差用百分点。反馈提供前10组事件计数及各组频率。曲线在相同p和种子下重抽不同n，比较分布波动；不是对同一组追加数据。总体p在此模拟已知；它不自动等于真实业务比例，单次频率不保证下一次结果。大样本降低同分布独立抽样下的理论波动，但某一次频率不必随n单调靠近p。",
        }
    if template_id == "prediction-score-to-class":
        return {
            "mode": "synthetic_data_statistics", "label": "教学样本逐行计算",
            "description": "实际对六个给定教学分数逐行应用阈值，不训练模型，也不把分数自动解释为概率。",
            "capabilities": "S1到S6的给定分数为[0.20,0.40,0.50,0.60,0.80,0.90]，真实标签为[0,0,1,0,1,1]。分数>=decision_threshold判为1，否则为0；反馈逐行给出分数、预测类别和真实标签。统计预测为1、预测为0以及与标签一致的个数，曲线扫描同一组分数的阈值。预测类别只使用给定分数与阈值；核对是否正确才读取标签。本页没有输入特征或训练步骤，不能声称已学习特征到标签的映射。分数落在[0,1]不证明它是概率；六行一致数不证明真实泛化能力，也不表示预测1越多或越少越好。",
        }
    if template_id == "inventory-demand-boundary":
        return {
            "mode": "synthetic_data_statistics", "label": "库存教学案例计算",
            "description": "实际计算十天合成需求的十个循环交货期案例；不是店铺真实销量、未来概率预测或最优订货方案。",
            "capabilities": "原需求[4,6,5,7,5,6,4,8,5,5]，均值5.5；每天变为5.5+demand_variation*(原值-5.5)。从每一天起循环取lead_days天求和，共十个等权案例，每例均从initial_stock开始，期内无补货、无期初积欠、仅单店单品。未满足量=max(交货期需求-现货,0)；现货满足比例=100*各例min(现货,需求)总和/各例需求总和；其余为十例均值。backorder=0将未满足量计为丢失销售，=1计为到货前积欠，模式不改变本期现货满足率。曲线仅扫描现有库存。不能从这些教学案例推出真实缺货概率、EOQ、再订货点、随机提前期或商品相关性。",
        }
    if template_id == "parallel-training-throughput":
        return {
            "mode": "teaching_simulation", "label": "并行耗时计算",
            "description": "按Amdahl定律与线性通信模型计算固定工作量的用时，不启动多卡训练，也不代表真实硬件测速。",
            "capabilities": "T=T1*((1-p)+p/n)+c*(n-1)*(1-o)；加速比=T1/T，并行效率=加速比/n。T1为单设备计算秒数，p为可并行比例，n为设备数，c为每增加一台的通信秒数，o为通信重叠比例。曲线只扫描设备数；不模拟梯度陈旧、收敛精度或真实通信拓扑。",
        }
    if template_id == "sklearn-fit-predict":
        return {
            "mode": "synthetic_data_training", "label": "合成数据训练",
            "description": "本页实际训练固定的双月形合成数据：300条中240条作为训练池，60条只作验证；不会加载教材数据，结果不能视为真实业务效果。",
            "capabilities": "实际使用make_moons(300,noise=0.25,random_state=42)，train_test_split(test_size=60,stratify=y,random_state=42)，DecisionTreeClassifier(max_depth,random_state=42)。训练取训练池前training_samples条；新样本为(prediction_x,0.25)，反馈展示predict类别与概率。曲线扫描树深度，评分只有训练准确率、验证准确率及二者差距绝对值。不提供测试分数、路径或不纯度操作。",
        }
    if template_id == "exploratory-data-distribution":
        return {
            "mode": "synthetic_data_statistics", "label": "合成数据统计",
            "description": "本页实际计算30到70共41个合成观测值：替换末尾高值并移除开头低值，比较统计量；不会加载教材数据。",
            "capabilities": "高值异常数量指定替换原数据末尾多少个值，替换值由异常值大小决定；低值缺失数量指定移除开头多少个值。实际计算均值、中位数相对50的偏移绝对值及保留比例，反馈展示均值与中位数；曲线扫描异常数量。不能声称执行自动清洗、插补或任意文件分析。",
        }
    return {
        "mode": "teaching_simulation", "label": "教学模拟",
        "description": "本页根据参数计算教学模拟趋势，不会加载这份数据进行真实训练；实际训练请使用关联代码练习。",
        "capabilities": "只计算此模板声明的参数和模拟指标；不执行代码沙盒的训练、数据划分、决策路径或不纯度计算。",
    }


@lru_cache(maxsize=128)
def _sklearn_training_run(depth: int, count: int):
    from sklearn.datasets import make_moons
    from sklearn.model_selection import train_test_split
    from sklearn.tree import DecisionTreeClassifier

    x, y = make_moons(n_samples=300, noise=0.25, random_state=42)
    train_x, valid_x, train_y, valid_y = train_test_split(x, y, test_size=60, stratify=y, random_state=42)
    model = DecisionTreeClassifier(max_depth=depth, random_state=42)
    model.fit(train_x[:count], train_y[:count])
    return model, model.score(train_x[:count], train_y[:count]), model.score(valid_x, valid_y)


def _evaluate(template: LabTemplate, p: dict[str, float | int]) -> tuple[dict[str, float | int], tuple[str, ...]]:
    if template.template_id in CONCEPT_LABS:
        from app.concept_labs import evaluate
        return evaluate(template.template_id, p)
    if template.template_id == "sample-frequency-estimation":
        import math
        import numpy as np
        probability, count, seed = float(p["event_probability"]), int(p["sample_size"]), int(p["sample_seed"])
        counts = np.random.default_rng(seed).binomial(count, probability, size=200)
        frequencies = counts / count
        return {
            "event_count": int(counts[0]),
            "sample_frequency": round(float(frequencies[0]) * 100, 6),
            "complement_frequency": round((1 - float(frequencies[0])) * 100, 6),
            "mean_frequency": round(float(frequencies.mean()) * 100, 6),
            "frequency_sd": round(float(frequencies.std(ddof=1)) * 100, 6),
            "theoretical_se": round(math.sqrt(probability * (1 - probability) / count) * 100, 6),
        }, (
            f"总体比例设为{probability:.0%}；每组{count}次独立试验，共200组。",
            *tuple(f"第{i+1}组：事件{value}/{count}次，频率{value/count:.2%}。" for i,value in enumerate(counts[:10])),
            "比较200组频率的分散程度与理论标准差，解释样本量对波动的影响。",
            (f"总体比例设为{probability:.0%}，每次事件{'都不发生' if probability == 0 else '都发生'}；各组频率相同，标准差恒为0。"
             if probability in (0, 1) else
             "第一组频率是这组样本的结果；下一次事件仍按设定的总体概率发生。"),
        )
    if template.template_id == "prediction-score-to-class":
        scores, labels = (.2, .4, .5, .6, .8, .9), (0, 0, 1, 0, 1, 1)
        threshold = float(p["decision_threshold"])
        predicted = [int(score >= threshold) for score in scores]
        return {
            "predicted_positive": sum(predicted), "predicted_negative": len(scores) - sum(predicted),
            "matched_labels": sum(prediction == label for prediction, label in zip(predicted, labels)),
        }, (
            f"本次规则：分数≥{threshold:g}判为1，否则为0。",
            *tuple(f"S{i}：给定分数{score:.2f} → 预测类别{prediction}；真实标签{label}。"
                   for i, (score, prediction, label) in enumerate(zip(scores, predicted, labels), 1)),
            "先遮住真实标签也能按分数判类；核对预测是否正确才需要标签。改变阈值不会改变给定分数。",
            "这六行只用于练习判断，不能证明模型在新数据上可靠；分数在0到1之间也不自动成为概率。",
        )
    if template.template_id == "inventory-demand-boundary":
        original = (4, 6, 5, 7, 5, 6, 4, 8, 5, 5)
        demand = [5.5 + float(p["demand_variation"]) * (value - 5.5) for value in original]
        lead = int(p["lead_days"])
        totals = [sum(demand[(start + day) % len(demand)] for day in range(lead))
                  for start in range(len(demand))]
        stock = int(p["initial_stock"])
        unmet = [max(total - stock, 0) for total in totals]
        average_unmet = sum(unmet) / len(unmet)
        backorder = bool(p["backorder"])
        metrics = {
            "immediate_fill_rate": round(100 * sum(min(stock, total) for total in totals) / sum(totals), 4),
            "average_unmet": round(average_unmet, 4),
            "average_backlog": round(average_unmet if backorder else 0, 4),
            "average_lost": round(0 if backorder else average_unmet, 4),
        }
        feedback = (
            f"十个教学案例的交货期需求为：{'、'.join(f'{value:g}' for value in totals)}件；每例从{stock}件现货开始。",
            "延期模式把未满足需求保留到下一次交货；丢失模式不保留。切换模式本身不会增加本期现货或改善现货满足比例。",
            "只改变一个条件比较结果；这里是单店单品的教学案例，不是店铺未来需求概率或最优库存。",
        )
    elif template.template_id == "parallel-training-throughput":
        devices = int(p["devices"])
        baseline = float(p["serial_seconds"])
        parallel = float(p["parallel_fraction"])
        communication = float(p["communication_seconds"]) * (devices - 1) * (1 - float(p["overlap_fraction"]))
        elapsed = baseline * (1 - parallel + parallel / devices) + communication
        speedup = baseline / elapsed
        metrics = {"step_seconds": round(elapsed, 4), "speedup": round(speedup, 4),
                   "parallel_efficiency": round(speedup / devices, 4)}
        feedback = (
            f"计算部分用时{elapsed - communication:.2f}秒，未被掩盖的通信耗时{communication:.2f}秒。",
            "保持工作量不变，比较增加设备和提高通信重叠比例；串行部分不能随设备数增加而缩短。",
        )
    elif template.template_id == "exploratory-data-distribution":
        from statistics import mean, median

        values = list(range(30, 71))
        outliers, missing = int(p["outlier_count"]), int(p["missing_count"])
        if outliers:
            values[-outliers:] = [int(p["outlier_value"])] * outliers
        observed = values[missing:]
        average, middle = mean(observed), median(observed)
        metrics = {
            "mean_shift": round(abs(average - 50), 4),
            "median_shift": round(abs(middle - 50), 4),
            "available_fraction": round(len(observed) / 41, 4),
        }
        feedback = (
            f"完整合成数据均值和中位数均为50；本轮保留{len(observed)}个观测，均值{average:.4f}，中位数{middle:g}。",
            "高值异常通常更明显地拉动均值；仅缺失低值也会使中心位置上移，不能假定缺失完全随机。",
            "偏移以这份已知完整数据为基准，不代表实际数据的中心越低越好；先解释异常原因，再决定处理方式。",
        )
    elif template.template_id == "sklearn-fit-predict":
        count = int(p["training_samples"])
        model, training, validation = _sklearn_training_run(int(p["max_depth"]), count)
        sample = [[float(p["prediction_x"]), 0.25]]
        predicted = int(model.predict(sample)[0])
        probabilities = model.predict_proba(sample)[0]
        probability = float(probabilities[list(model.classes_).index(predicted)])
        metrics = {
            "training_score": round(float(training), 4), "validation_score": round(float(validation), 4),
            "generalization_gap": round(abs(float(training - validation)), 4),
        }
        feedback = (
            f"已实际用{count}条合成训练样本调用fit；另60条固定验证样本只用于score，没有参与拟合。",
            f"predict对新样本({sample[0][0]:g}, 0.25)给出类别{predicted}；该类预测概率为{probability:.1%}，不等于预测一定正确。",
            "改变新样本第一维只影响预测结果；比较树深度使用验证分数，本实验没有提供可反复用于调参的最终测试分数。",
            "这是固定合成数据的教学实验，分数不代表真实课程数据或生产模型效果。",
        )
    elif template.template_id == "rag-hybrid-tuning":
        recall = 0.56 + min(int(p["top_k"]), 6) * 0.04 - abs(float(p["keyword_weight"]) - 0.4) * 0.2
        ranking = 0.62 + float(p["rerank_threshold"]) * 0.2 - abs(float(p["vector_weight"]) - 0.6) * 0.3
        metrics = {
            "recall_at_k": round(max(0, min(1, recall)), 4),
            "ranking_score": round(max(0, min(1, ranking)), 4),
            "average_latency_ms": 70 + int(p["top_k"]) * 12 + int(float(p["rerank_threshold"]) * 40),
        }
        feedback = (
            "增加 top_k 通常提高召回，但会增加延迟。",
            "关键词和向量权重必须保持总和为 1，隔离过滤不可关闭。",
        )
    elif template.template_id == "classifier-threshold-calibration":
        threshold = float(p["decision_threshold"])
        margin = float(p["abstain_margin"])
        bins = int(p["calibration_bins"])
        metrics = {
            "balanced_accuracy": round(max(0, 0.88 - abs(threshold - 0.55) * 0.5 - margin * 0.12), 4),
            "false_positive_rate": round(max(0, 0.16 - (threshold - 0.4) * 0.22), 4),
            "coverage": round(max(0, 1 - margin * 1.35), 4),
            "calibration_error": round(max(0.01, 0.11 - min(bins, 14) * 0.004 + abs(threshold - 0.55) * 0.14), 4),
        }
        feedback = (
            "提高阈值可降低误报，但可能牺牲召回。",
            "扩大拒判区间会降低覆盖率，应与人工复核能力共同评估。",
        )
    elif template.template_id == "data-processing-sensitivity":
        rows = int(p["row_count"])
        features = int(p["feature_count"])
        vectorized = float(p["vectorization_ratio"])
        missing = float(p["missing_rate"])
        throughput = max(500, 1200 + vectorized * 6500 - features * 55 - missing * 900)
        metrics = {
            "processing_time_ms": round(rows / throughput * 80, 3),
            "memory_mb": round(rows * features * 8 / 1_000_000 * (1.25 - vectorized * 0.2), 3),
            "usable_data_ratio": round(max(0, 1 - missing), 4),
            "throughput_rows_s": round(throughput, 1),
        }
        feedback = (
            "提高向量化比例通常会降低处理耗时并提高吞吐。",
            "缺失比例会直接减少可用数据，仍需结合清洗策略判断。",
        )
    elif template.template_id == "model-complexity-generalization":
        complexity = int(p["model_complexity"])
        samples = int(p["training_samples"])
        regularization = float(p["regularization"])
        ideal = min(8.0, 2.5 + samples / 220 + regularization * 1.5)
        training = min(0.99, 0.62 + complexity * 0.045 - regularization * 0.08)
        validation = max(0.3, min(0.95, 0.86 - abs(complexity - ideal) * 0.045 - max(0, complexity - ideal) * 0.018 + samples / 10000))
        metrics = {
            "training_score": round(training, 4),
            "validation_score": round(validation, 4),
            "generalization_gap": round(max(0, training - validation), 4),
            "inference_cost": round(8 + complexity ** 1.7, 2),
        }
        feedback = (
            "复杂度过低可能欠拟合，过高则会拉大训练与验证差距。",
            "增加样本或适当正则化可以缓解高容量模型的过拟合。",
        )
    elif template.template_id == "clustering-configuration":
        clusters = int(p["cluster_count"])
        scale = float(p["feature_scale"])
        noise = float(p["noise_level"])
        runs = int(p["initialization_runs"])
        metrics = {
            "silhouette_score": round(max(0, min(1, 0.84 - abs(clusters - 4) * 0.085 - noise * 0.38 - abs(scale - 1) * 0.08)), 4),
            "cluster_stability": round(max(0, min(1, 0.58 + min(runs, 12) * 0.025 - noise * 0.25 - abs(scale - 1) * 0.06)), 4),
            "assignment_coverage": round(max(0, min(1, 0.98 - noise * 0.32 - abs(clusters - 4) * 0.018)), 4),
            "compute_cost": round(clusters * runs * (1 + abs(scale - 1) * 0.2), 2),
        }
        feedback = (
            "聚类数偏离冻结样本的主要结构时，轮廓系数通常下降。",
            "增加初始化次数可提高稳定性，但会增加计算成本。",
        )
    elif template.template_id == "dimensionality-reduction":
        components = int(p["component_count"])
        signal = float(p["signal_strength"])
        noise = float(p["noise_level"])
        samples = int(p["sample_size"])
        explained = min(0.99, (1 - 0.72 ** components) * signal + components * 0.018 - noise * 0.08)
        metrics = {
            "explained_variance": round(max(0, explained), 4),
            "reconstruction_quality": round(max(0, min(1, explained - noise * 0.12 + samples / 12000)), 4),
            "compression_ratio": round(max(0, min(0.95, 1 - components / 12)), 4),
            "compute_cost": round(components * samples / 100, 2),
        }
        feedback = (
            "保留更多主成分会提高信息保留，但压缩比例随之下降。",
            "噪声和小样本会降低主方向估计及重构质量。",
        )
    elif template.template_id == "linear-algebra-probability":
        scale = float(p["vector_scale"])
        dimension = int(p["matrix_dimension"])
        temperature = float(p["temperature"])
        sparsity = float(p["sparsity"])
        dot_product = scale * (1 - sparsity) * 3.5
        matrix_trace = dimension * (1.15 - sparsity * 0.25)
        probability_entropy = min(1, 0.42 + 0.26 * temperature - sparsity * 0.18)
        metrics = {
            "dot_product": round(dot_product, 4),
            "matrix_trace": round(matrix_trace, 4),
            "probability_entropy": round(probability_entropy, 4),
            "normalization_error": 0.0,
        }
        feedback = (
            "向量尺度和稀疏比例会改变点积大小；先确认维度一致，再解释数值变化。",
            "提高概率温度会让分布更平滑，但归一化误差仍应保持接近 0。",
        )
    elif template.template_id == "optimization-dynamics":
        learning_rate = float(p["learning_rate"])
        batch_size = int(p["batch_size"])
        epochs = int(p["epochs"])
        regularization = float(p["regularization"])
        stability = max(0, min(1, 0.96 - abs(learning_rate - 0.12) * 1.45 - max(0, 24 - batch_size) / 80))
        convergence = max(0, min(1, 0.48 + min(epochs, 65) * 0.0065 - abs(learning_rate - 0.12) * 0.85 - abs(regularization - 0.15) * 0.08))
        metrics = {
            "final_loss": round(max(0.05, 1.02 - convergence * 0.78 + regularization * 0.08), 4),
            "convergence_score": round(convergence, 4),
            "stability_score": round(stability, 4),
            "training_cost": round(epochs * (128 / batch_size) * 4, 2),
        }
        feedback = (
            "学习率过低会收敛缓慢，过高则会破坏训练稳定性。",
            "增加轮次可能改善收敛，但训练成本也会同步上升。",
        )
    elif template.template_id in {
        "algorithmic-problem-framing", "algorithm-complexity", "data-structure-operations",
        "tree-traversal", "heap-priority-queue", "graph-traversal", "sorting-strategy",
        "search-boundary", "recursion-backtracking", "algorithmic-strategy", "dynamic-programming",
        "neural-architecture", "attention-mechanics", "language-generation", "agent-workflow",
    }:
        # These families intentionally share a bounded simulation contract, but
        # derive every metric from the selected scenario and input scale.  The
        # metric definitions still carry the domain-specific labels and hidden
        # acceptance thresholds exposed by the template.
        scale = int(p["scenario_scale"])
        size = int(p["input_size"])
        guidance = float(p["guidance_level"])
        threshold = float(p["evidence_threshold"])
        difficulty = abs(scale - 3) * 0.025 + abs(size - 3) * 0.018
        metrics = {}
        for index, definition in enumerate(template.metrics):
            if definition.higher_is_better:
                value = float(definition.acceptance_threshold) + 0.12 - difficulty + guidance * 0.03 - index * 0.012
                # Keep score-like values in a readable range while preserving
                # larger scales for cost/operation metrics.
                if definition.acceptance_threshold <= 1:
                    value = min(0.98, max(0.05, value))
            else:
                if float(definition.acceptance_threshold) <= 1:
                    value = float(definition.acceptance_threshold) * 0.35 + scale * 0.03 + size * 0.02 - guidance * 0.01 + index * 0.005
                else:
                    value = float(definition.acceptance_threshold) * 0.35 + scale * 0.32 + size * 0.16 - guidance * 0.08 + index * 0.05
                value = max(0.05, value + threshold * 0.02)
            metrics[definition.key] = round(value, 4)
        feedback = (
            "提高案例或输入规模会增加状态、样本或工具步骤，结果指标会随之变化。",
            "先观察理论不变量，再用第二组参数比较效率、正确性和可迁移性。",
        )
    else:
        _fail("lab_template_evaluator_missing", "当前实验模板暂时没有可用的运行计算规则。")
    return metrics, feedback


def _computed_series(template: LabTemplate, p: dict[str, float | int]) -> tuple[LabComputedSeries, ...]:
    sweep = next(item for item in template.parameters if item.key == template.sweep_parameter_key)
    step_count = int(round((sweep.maximum - sweep.minimum) / sweep.step))
    sample_indexes = sorted({round(index * step_count / min(6, step_count)) for index in range(min(6, step_count) + 1)})
    rows = []
    for index in sample_indexes:
        numeric = sweep.minimum + index * sweep.step
        value: float | int = int(round(numeric)) if sweep.kind == "integer" else round(numeric, 6)
        metrics, _ = _evaluate(template, {**p, sweep.key: value})
        rows.append((value, metrics))
    return tuple(
        LabComputedSeries(
            key=definition.key,
            label=definition.label,
            unit=definition.unit,
            points=tuple(LabSeriesPoint(x=float(x), y=float(metrics[definition.key])) for x, metrics in rows),
        )
        for definition in template.metrics
    )


def _hidden(template: LabTemplate, state: LabState) -> HiddenLabResult:
    m, p = state.metrics or {}, state.parameters
    if template.template_id in CONCEPT_LABS:
        import math
        checks = {"finite_computation": bool(m) and all(math.isfinite(float(value)) for value in m.values())}
    elif template.template_id == "sample-frequency-estimation":
        checks = {"sample_consistency": (
            0 <= m["event_count"] <= p["sample_size"]
            and abs(m["sample_frequency"] - 100 * m["event_count"] / p["sample_size"]) < 1e-5
            and abs(m["sample_frequency"] + m["complement_frequency"] - 100) < 1e-5
            and m["frequency_sd"] >= 0 and m["theoretical_se"] >= 0
        )}
    elif template.template_id == "rag-hybrid-tuning":
        checks = {
            "retrieval_quality": float(m["recall_at_k"]) >= 0.72 and 4 <= int(p["top_k"]) <= 6,
            "ranking_quality": float(m["ranking_score"]) >= 0.71,
            "isolation": True,
            "version_scope": state.template_sha256 == template.template_sha256,
        }
    elif template.template_id == "classifier-threshold-calibration":
        checks = {
            "balanced_quality": float(m["balanced_accuracy"]) >= 0.84,
            "false_positives": float(m["false_positive_rate"]) <= 0.13,
            "coverage": float(m["coverage"]) >= 0.82,
            "calibration": float(m["calibration_error"]) <= 0.075,
        }
    else:
        checks = {
            definition.key: (
                float(m[definition.key]) >= definition.acceptance_threshold
                if definition.higher_is_better
                else float(m[definition.key]) <= definition.acceptance_threshold
            )
            for definition in template.metrics
            if definition.higher_is_better is not None and definition.acceptance_threshold is not None
        }
    failures = tuple(key for key, passed in checks.items() if not passed)
    return HiddenLabResult(
        passed=not failures, passed_count=sum(checks.values()), total_count=len(checks),
        failure_categories=failures, checker_version=template.checker_version,
    )


def _resource_contract(
    db: Any, source_resource_id: str, owner: str,
) -> tuple[DBArtifact, DBArtifactVersion, Any]:
    artifact = db.get(DBArtifact, source_resource_id)
    if artifact is None:
        _fail("lab_source_resource_unknown", "interactive model resource does not exist")
    if artifact.owner_public_id != owner:
        _fail("lab_source_resource_forbidden", "interactive model resource belongs to another owner")
    if reason := resource_generation_blocker(db, artifact):
        _fail("resource_generation_incomplete", reason)
    version = db.get(DBArtifactVersion, artifact.current_version_id)
    metadata = dict(version.metadata_json or {}) if version else {}
    if version is None or canonical_resource_type(artifact.artifact_type, metadata) != "interactive_model":
        _fail("lab_source_resource_type_invalid", "source resource is not an interactive model")
    if version.content_format != "json":
        _fail("lab_source_resource_legacy", "legacy interactive model resources cannot run experiments")
    try:
        content = parse_interactive_model_content(version.content)
    except ValueError as exc:
        _fail("lab_source_resource_invalid", str(exc))
    validate_resource_template_content(content)
    return artifact, version, content


def _owned_instance(db: Any, instance_id: str, owner: str) -> tuple[DBArtifact, DBArtifactVersion, LabState]:
    artifact = db.get(DBArtifact, instance_id)
    if artifact is None or artifact.artifact_type != LAB_INSTANCE_TYPE:
        _fail("lab_instance_unknown", "interactive lab instance does not exist")
    if artifact.owner_public_id != owner:
        _fail("lab_instance_forbidden", "interactive lab instance belongs to another owner")
    version = db.get(DBArtifactVersion, artifact.current_version_id)
    return artifact, version, LabState.model_validate_json(version.content)


def create_instance(
    db: Any,
    *,
    owner: str,
    template_id: str | None,
    title: str | None,
    parameters: dict[str, Any] | None,
    linked_media_resource_id: str | None,
    source_resource_id: str | None,
    idempotency_key: str,
) -> tuple[LabState, DBArtifactVersion, bool]:
    source_artifact = source_version = source_content = None
    if source_resource_id:
        source_artifact, source_version, source_content = _resource_contract(db, source_resource_id, owner)
        if template_id and template_id != source_content.templateId:
            _fail("lab_source_resource_template_conflict", "requested template differs from the resource template")
        template_id = source_content.templateId
        title = title or source_content.title
        defaults = {
            item.key: int(item.default) if item.kind == "integer" else item.default
            for item in source_content.parameters
        }
        parameters = parameters or defaults
    if not template_id or not title or parameters is None:
        _fail("lab_instance_input_required", "template, title and parameters are required")
    template = get_template(template_id)
    validated = validate_parameters(template, parameters)
    if linked_media_resource_id:
        media = db.get(DBMediaContextResource, linked_media_resource_id)
        if media is None:
            _fail("lab_media_unknown", "linked media resource does not exist")
        if media.owner_public_id != owner:
            _fail("lab_media_forbidden", "linked media resource belongs to another owner")
    instance_id = _stable_id("lab", owner, idempotency_key)
    existing = db.get(DBArtifact, instance_id)
    request_hash = _digest({
        "template_id": template_id,
        "title": title,
        "parameters": validated,
        "media": linked_media_resource_id,
        "source_resource_id": source_resource_id,
        "source_resource_version_id": source_version.id if source_version else None,
    })
    if existing:
        creation_version = db.query(DBArtifactVersion).filter_by(artifact_id=existing.id, version_number=1).one()
        if (creation_version.metadata_json or {}).get("create_request_sha256") != request_hash:
            _fail("lab_idempotency_conflict", "idempotency key is bound to another lab instance")
        version = db.get(DBArtifactVersion, existing.current_version_id)
        return LabState.model_validate_json(version.content), version, False
    artifact = DBArtifact(id=instance_id, owner_public_id=owner, artifact_type=LAB_INSTANCE_TYPE, title=title)
    db.add(artifact)
    db.flush()
    source_refs = tuple(source_content.sourceRefIds) if source_content else ()
    state = LabState(
        instance_id=instance_id,
        owner_public_id=owner,
        template_id=template_id,
        template_version=template.template_version,
        template_sha256=template.template_sha256,
        title=title,
        linked_media_resource_id=linked_media_resource_id,
        source_resource_id=source_resource_id,
        source_resource_version_id=source_version.id if source_version else None,
        course_id=source_artifact.course_id if source_artifact else None,
        knowledge_point_id=(source_version.metadata_json or {}).get("knowledge_point_id") if source_version else None,
        profile_snapshot_id=(source_version.metadata_json or {}).get("profile_snapshot_id") if source_version else None,
        source_ref_ids=source_refs,
        observation_prompt=source_content.observationPrompt.prompt if source_content else None,
        observation_minimum_characters=(source_content.observationPrompt.minimumCharacters if source_content else 1),
        completion_rule=source_content.completionRule if source_content else None,
        parameters=validated,
    )
    version = add_artifact_version(db, artifact=artifact, content=_canonical(state.model_dump(mode="json")),
                                   created_by_public_id=owner, content_format="json",
                                   metadata={"template_id": template_id, "template_sha256": template.template_sha256,
                                             "create_request_sha256": request_hash,
                                             "source_resource_id": source_resource_id,
                                             "source_resource_version_id": source_version.id if source_version else None})
    return state, version, True


def list_instances(db: Any, owner: str) -> list[dict[str, Any]]:
    artifacts = db.query(DBArtifact).filter_by(owner_public_id=owner, artifact_type=LAB_INSTANCE_TYPE).order_by(DBArtifact.created_at.desc()).all()
    return [instance_payload(*_owned_instance(db, item.id, owner)) for item in artifacts]


def instance_payload(artifact: DBArtifact, version: DBArtifactVersion, state: LabState) -> dict[str, Any]:
    payload = state.model_dump(mode="json")
    payload.update(version_id=version.id, version_number=version.version_number, content_sha256=version.content_hash,
                   template=get_template(state.template_id).model_dump(mode="json"))
    return payload


def get_instance(db: Any, instance_id: str, owner: str) -> dict[str, Any]:
    return instance_payload(*_owned_instance(db, instance_id, owner))


def apply_action(
    db: Any,
    *,
    instance_id: str,
    owner: str,
    action: str,
    parameters: dict[str, Any] | None,
    observation: str | None,
    expected_version: int,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    artifact, version, state = _owned_instance(db, instance_id, owner)
    event_id = _stable_id("le-lab", instance_id, idempotency_key)
    request_hash = _digest({
        "action": action,
        "parameters": parameters,
        "observation": observation,
        "expected_version": expected_version,
    })
    existing_event = db.get(DBLearningEvent, event_id)
    if existing_event:
        if (existing_event.payload or {}).get("request_sha256") != request_hash:
            _fail("lab_idempotency_conflict", "idempotency key is bound to another action")
        result_version = db.get(DBArtifactVersion, existing_event.payload["result_version_id"])
        result = instance_payload(artifact, result_version, LabState.model_validate_json(result_version.content))
        result["learning_evidence"] = {"created": False, "event_id": existing_event.id}
        result["learning_feedback"] = _aggregate_feedback(db, existing_event)
        return result, False
    action_versions = db.query(DBArtifactVersion).filter_by(artifact_id=artifact.id).order_by(
        DBArtifactVersion.version_number.desc()
    ).all()
    for action_version in action_versions:
        metadata = dict(action_version.metadata_json or {})
        if metadata.get("action_idempotency_key") != idempotency_key:
            continue
        if metadata.get("action_request_sha256") != request_hash:
            _fail("lab_idempotency_conflict", "idempotency key is bound to another action")
        result = instance_payload(artifact, action_version, LabState.model_validate_json(action_version.content))
        result["learning_evidence"] = {"created": False, "event_id": None}
        return result, False
    if state.source_resource_id:
        source = db.get(DBArtifact, state.source_resource_id)
        if source and (reason := resource_generation_blocker(db, source, state.source_resource_version_id)):
            _fail("resource_generation_incomplete", reason)
    if version.version_number != expected_version:
        _fail("lab_version_conflict", "interactive lab instance has changed")
    template = get_template(state.template_id)
    data = state.model_dump(mode="json")
    if action == "configure":
        if state.status not in {"configured", "evaluated", "needs_retry"} or parameters is None:
            _fail("lab_transition_invalid", "configure requires editable state and parameters")
        data.update(parameters=validate_parameters(template, parameters), status="configured", metrics=None,
                    computed_series=(), feedback=(), hidden_acceptance=None, submitted_observation=None)
    elif action == "run":
        if state.status != "configured":
            _fail("lab_transition_invalid", "run requires configured state")
        metrics, feedback = _evaluate(template, state.parameters)
        data.update(status="evaluated", metrics=metrics, computed_series=_computed_series(template, state.parameters),
                    feedback=feedback, hidden_acceptance=None, submitted_observation=None)
    elif action == "submit":
        if state.status != "evaluated":
            _fail("lab_transition_invalid", "submit requires evaluated state")
        if state.source_resource_id:
            clean_observation = str(observation or "").strip()
            if len(" ".join(clean_observation.split())) < state.observation_minimum_characters:
                _fail(
                    "lab_observation_required",
                    f"observation must contain at least {state.observation_minimum_characters} characters",
                )
            data.update(status="passed", hidden_acceptance=None, submitted_observation=clean_observation)
        else:
            result = _hidden(template, state)
            data.update(status="passed" if result.passed else "needs_retry",
                        hidden_acceptance=result.model_dump(mode="json"))
    elif action == "request_hint":
        if state.status not in {"evaluated", "needs_retry"}:
            _fail("lab_transition_invalid", "hint requires an observable result")
        data["hint_count"] = state.hint_count + 1
        if template.template_id == "sklearn-fit-predict":
            hint = "先固定训练样本量，对比浅树和较深的树；记录训练与验证准确率。再固定这两个设置，只改变新样本，检查预测是否变化、验证分数是否保持不变。"
        elif template.template_id == "exploratory-data-distribution":
            hint = "先把异常和缺失数量都设为0，核对均值与中位数均为50；只加入一个高值异常，比较哪个统计量变化更大，再单独试低值缺失。"
        else:
            sweep = next(item for item in template.parameters if item.key == template.sweep_parameter_key)
            hint = f"先保持其他参数不变，只调整“{sweep.label}”；对比两次“{template.metrics[0].label}”的结果，结合实验条件解释变化，不能只记录哪个数更大。"
        if hint not in state.feedback:
            data["feedback"] = tuple(state.feedback) + (hint,)
    elif action == "reset":
        defaults = {item.key: int(item.default) if item.kind == "integer" else item.default for item in template.parameters}
        data.update(status="configured", attempt=state.attempt + 1, parameters=defaults, metrics=None,
                    computed_series=(), feedback=(), hidden_acceptance=None, submitted_observation=None, hint_count=0)
    else:
        _fail("lab_action_unknown", "interactive lab action is not supported")
    data.update(action_count=state.action_count + 1, last_action=action)
    next_state = LabState.model_validate(data)
    next_version = add_artifact_version(db, artifact=artifact, content=_canonical(next_state.model_dump(mode="json")),
                                        created_by_public_id=owner, content_format="json",
                                        metadata={"template_id": template.template_id, "template_sha256": template.template_sha256,
                                                  "action": action, "status": next_state.status,
                                                  "action_idempotency_key": idempotency_key,
                                                  "action_request_sha256": request_hash,
                                                  "source_resource_id": next_state.source_resource_id,
                                                  "source_resource_version_id": next_state.source_resource_version_id})
    evidence = {"created": False, "event_id": None}
    if action == "submit" and next_state.source_resource_id:
        # Parameter runs and ungraded prose prove participation, not correctness.
        strength = 0.0
        event = DBLearningEvent(
            id=event_id,
            owner_public_id=owner,
            course_id=next_state.course_id,
            event_type=LAB_EVENT_TYPE,
            schema_version="1.0",
            idempotency_key=idempotency_key,
            source="interactive_model",
            trace_id=_stable_id("trace-lab", instance_id),
            object_type="interactive_model",
            object_id=next_state.source_resource_id,
            action="submit_observation",
            context_ref={
                "resource_id": next_state.source_resource_id,
                "resource_version_id": next_state.source_resource_version_id,
                "instance_id": instance_id,
                "knowledge_point_id": next_state.knowledge_point_id,
                "profile_snapshot_id": next_state.profile_snapshot_id,
                "source_ref_ids": list(next_state.source_ref_ids),
            },
            evidence_strength=strength,
            evidence_status="none",
            evidence_reason="实验观察已保存；理解程度由后续作答或复述评价确认",
            mastery_eligible=False,
            completion_effect="progress",
            payload_version="f6.interactive-model-observation.v1",
            payload={
                "request_sha256": request_hash,
                "evidence_kind": "guided_practice",
                "result_version_id": next_version.id,
                "template_id": template.template_id,
                "parameters": next_state.parameters,
                "metrics": next_state.metrics,
                "observation_prompt": next_state.observation_prompt,
                "observation": next_state.submitted_observation,
                "hint_count": next_state.hint_count,
            },
        )
        db.add(event)
        evidence = {"created": True, "event_id": event.id}
    db.flush()
    result = instance_payload(artifact, next_version, next_state)
    result["learning_evidence"] = evidence
    if evidence["event_id"]:
        event = db.get(DBLearningEvent, evidence["event_id"])
        result["learning_feedback"] = _aggregate_feedback(db, event)
    return result, True
