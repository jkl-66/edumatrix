from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any


@dataclass(frozen=True)
class MetricEvent:
    name: str
    value: float
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceSpan:
    name: str
    duration_ms: float
    attributes: dict[str, Any] = field(default_factory=dict)


class TelemetrySink:
    """Small metrics/tracing sink used by local runs and tests.

    Production deployments can mirror the same calls to OpenTelemetry,
    Prometheus, or an internal metrics gateway without changing the RAG and
    Swarm code paths.
    """

    def __init__(self) -> None:
        self.metrics: list[MetricEvent] = []
        self.spans: list[TraceSpan] = []

    def record_metric(self, name: str, value: float, **tags: str) -> None:
        self.metrics.append(MetricEvent(name=name, value=value, tags=tags))

    def record_span(self, name: str, duration_ms: float, **attributes: Any) -> None:
        self.spans.append(TraceSpan(name=name, duration_ms=duration_ms, attributes=attributes))

    def snapshot(self) -> dict[str, Any]:
        return {
            "metrics": [asdict(item) for item in self.metrics[-100:]],
            "spans": [asdict(item) for item in self.spans[-100:]],
        }

    def clear(self) -> None:
        self.metrics.clear()
        self.spans.clear()

    # === P2-5 教育专用指标 ===
    def record_learning_event(self, student_id: str, event_type: str, concept: str, value: float) -> None:
        """记录学习事件（掌握度变化、误概念出现、挫败感波动等）。"""
        self.record_metric(
            f"learning.{event_type}",
            value,
            student_id=student_id,
            concept=concept,
        )

    def record_engagement(self, student_id: str, frustration: float, engagement: float) -> None:
        """记录学生参与度和情感状态。"""
        self.record_metric("engagement.frustration", frustration, student_id=student_id)
        self.record_metric("engagement.level", engagement, student_id=student_id)

    def get_education_summary(self) -> dict[str, Any]:
        """获取教育维度的指标汇总。"""
        edu_metrics = {}
        for m in self.metrics:
            if m.name.startswith("learning."):
                key = m.name
                edu_metrics.setdefault(key, []).append(m.value)
            if m.name.startswith("engagement."):
                key = m.name
                edu_metrics.setdefault(key, []).append(m.value)
        return {
            key: {
                "mean": round(sum(vals) / len(vals), 4) if vals else 0,
                "count": len(vals),
                "last": vals[-1] if vals else 0,
            }
            for key, vals in sorted(edu_metrics.items())
        }


class timed_span:
    def __init__(self, sink: TelemetrySink, name: str, **attributes: Any) -> None:
        self.sink = sink
        self.name = name
        self.attributes = attributes
        self.started = 0.0

    def __enter__(self) -> "timed_span":
        self.started = perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        duration_ms = (perf_counter() - self.started) * 1000
        status = "error" if exc_type else "ok"
        self.sink.record_span(self.name, duration_ms, status=status, **self.attributes)


TELEMETRY = TelemetrySink()
