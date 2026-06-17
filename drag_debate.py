from __future__ import annotations

from dataclasses import dataclass

from config import CONFIG
from models import DebateVerdict, Evidence, RetrievalBundle


@dataclass(frozen=True)
class DebateResult:
    clean_evidence: tuple[Evidence, ...]
    verdicts: tuple[DebateVerdict, ...]
    low_confidence: bool = False


class DebateAugmentedRAG:
    """DRAG-style multi-agent evidence cleaning.

    The implementation uses three deterministic roles so the quality gate is
    repeatable: Prover estimates answerability, Challenger estimates noise or
    contradiction risk, and Judge applies the final threshold.
    """

    def __init__(self, min_score: float = CONFIG.debate_min_score) -> None:
        self.min_score = min_score

    def clean(self, bundle: RetrievalBundle) -> DebateResult:
        verdicts: list[DebateVerdict] = []
        clean: list[Evidence] = []
        kept_anchors: set[str] = set()
        for item in bundle.evidence:
            pro_score = self._prover(bundle.query, bundle.target, item)
            con_score = self._challenger(bundle.query, bundle.target, item, kept_anchors)
            judge_score = max(0.0, min(1.0, pro_score - con_score * 0.55 + item.score * 0.35))
            keep = judge_score >= self.min_score
            reason = self._reason(item, pro_score, con_score, judge_score, keep)
            verdict = DebateVerdict(
                evidence_id=item.id,
                pro_score=pro_score,
                con_score=con_score,
                judge_score=judge_score,
                keep=keep,
                reason=reason,
            )
            verdicts.append(verdict)
            if keep:
                clean.append(item.with_score(judge_score))
                kept_anchors.update(item.anchors)
        if not clean and bundle.evidence:
            best = max(bundle.evidence, key=lambda evidence: evidence.score)
            clean.append(best.with_score(max(best.score, self.min_score)))
            verdicts.append(
                DebateVerdict(
                    evidence_id=best.id,
                    pro_score=best.score,
                    con_score=0.0,
                    judge_score=max(best.score, self.min_score),
                    keep=True,
                    reason="兜底保留最高分证据，避免生成器空上下文回答。",
                )
            )
        
        # Determine low_confidence status
        is_low = bundle.low_confidence
        if not clean:
            is_low = True
        else:
            max_clean_score = max(item.score for item in clean)
            if max_clean_score < 0.20:
                is_low = True

        return DebateResult(clean_evidence=tuple(clean), verdicts=tuple(verdicts), low_confidence=is_low)

    def _prover(self, query: str, target: str, item: Evidence) -> float:
        text = " ".join((item.title, item.content, " ".join(item.tags), " ".join(item.anchors)))
        score = item.score

        # === 新增：学术特权提分 ===
        if item.metadata.get("is_academic") or item.source == "arXiv.org":
            score += 0.25 # 给学术源直接加 0.25 的信用基础分，避免被当作噪声误杀
        # === 新增结束 ===

        if target in text:
            score += 0.28
        if any(anchor in query or anchor.lower() in query.lower() for anchor in item.anchors):
            score += 0.18
        if any(tag in query for tag in item.tags):
            score += 0.12
        if item.modality.value == "image" and any(word in query for word in ("图", "演示", "看不懂", "矩阵")):
            score += 0.1
        return min(1.0, score)

    def _challenger(self, query: str, target: str, item: Evidence, kept_anchors: set[str]) -> float:
        text = " ".join((item.title, item.content, " ".join(item.tags), " ".join(item.anchors)))
        risk = 0.0
        if target not in text and item.score < 0.18:
            risk += 0.38
        asks_max = "最大池化" in query or "Max" in query or "max" in query
        asks_avg = "平均池化" in query or "Average" in query or "Avg" in query
        doc_avg = "平均池化" in text or "AvgPool2d" in text
        doc_max = "最大池化" in text or "MaxPool2d" in text or "Max Pooling" in text
        if asks_max and doc_avg and not doc_max:
            risk += 0.82
        if asks_avg and doc_max and not doc_avg:
            risk += 0.82
        if kept_anchors and {"AvgPool2d", "MaxPool2d"} <= (kept_anchors | set(item.anchors)):
            if asks_max or asks_avg:
                risk += 0.16
        if "反向传播" in text and "池化" in query:
            risk += 0.22
        return min(1.0, risk)

    def _reason(self, item: Evidence, pro: float, con: float, judge: float, keep: bool) -> str:
        action = "保留" if keep else "剔除"
        
        # 优化学术记录日志展示
        if keep and (item.metadata.get("is_academic") or item.source == "arXiv.org"):
            action = "🔬 权威保留"
            
        return (
            f"{action} {item.title}：正方相关性 {pro:.2f}，反方噪声/矛盾风险 {con:.2f}，"
            f"法官分 {judge:.2f}。"
        )