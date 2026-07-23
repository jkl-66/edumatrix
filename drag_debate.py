from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from config import CONFIG
from models import DebateVerdict, Evidence, RetrievalBundle


@dataclass(frozen=True)
class DebateResult:
    clean_evidence: tuple[Evidence, ...]
    verdicts: tuple[DebateVerdict, ...]
    trajectory: tuple[dict[str, Any], ...] = ()  # 任务 9.1: 辩论完整轨迹
    knowledge_gap: bool = False                   # 任务 9.1: 知识库覆盖不足标记
    mean_judge_score: float = 0.0                # 任务 9.1: 平均法官分


# 任务 9.1: 证据最低质量阈值（低于此值直接拦截）
EVIDENCE_MIN_THRESHOLD = 0.20


class DebateAugmentedRAG:
    """DRAG-style multi-agent evidence cleaning.

    P1-2 升级：当 LLM 可用时，使用真正的 LLM 驱动的 Prover-Challenger-Judge
    三轮对话进行证据辩论清洗。LLM 不可用时回退到确定性评分函数。
    """

    def __init__(self, min_score: float = CONFIG.debate_min_score, llm: Any | None = None) -> None:
        self.min_score = min_score
        self.llm = llm

    def clean(self, bundle: RetrievalBundle) -> DebateResult:
        # 当 LLM 可用且证据数量适中时，使用 LLM 辩论
        import inspect
        if (
            self.llm is not None
            and not inspect.iscoroutinefunction(getattr(self.llm, "generate", None))
            and 1 < len(bundle.evidence) <= 12
        ):
            return self._llm_debate_clean(bundle)
        # 否则使用确定性评分函数
        return self._deterministic_clean(bundle)

    async def aclean(self, bundle: RetrievalBundle) -> DebateResult:
        """Async entry point; never blocks an active event loop."""
        import asyncio
        import inspect

        if self.llm is not None and 1 < len(bundle.evidence) <= 12:
            if inspect.iscoroutinefunction(getattr(self.llm, "generate", None)):
                return await self._llm_debate_clean_async(bundle)
            return await asyncio.to_thread(self._llm_debate_clean, bundle)
        return self._deterministic_clean(bundle)

    # ================================================================
    # LLM 驱动的辩论清洗（P1-2 核心新增）
    # ================================================================

    def _llm_debate_clean(self, bundle: RetrievalBundle) -> DebateResult:
        return self._build_llm_debate_result(bundle, self._collective_batch_judge(bundle))

    async def _llm_debate_clean_async(self, bundle: RetrievalBundle) -> DebateResult:
        return self._build_llm_debate_result(
            bundle, await self._collective_batch_judge_async(bundle)
        )

    def _build_llm_debate_result(
        self, bundle: RetrievalBundle, collective_verdict: list[dict[str, Any]]
    ) -> DebateResult:
        """Build the verdict from a synchronous or asynchronous LLM result."""
        verdicts: list[DebateVerdict] = []
        clean: list[Evidence] = []
        kept_anchors: set[str] = set()

        # 对整个证据集进行一次 LLM 集体评估
        collective_verdict = self._collective_batch_judge(bundle)

        # 使用集体评估结果初始化每个证据的判决
        batch_judgments: dict[str, dict[str, Any]] = {}
        for j in collective_verdict:
            batch_judgments[j["evidence_id"]] = j

        for item in bundle.evidence:
            # 从集体判决中获取，或回退到确定性评分
            if item.id in batch_judgments:
                bj = batch_judgments[item.id]
                pro_score = float(bj.get("pro_score", 0.0))
                con_score = float(bj.get("con_score", 0.0))
                judge_score = float(bj.get("judge_score", 0.0))
                reason = str(bj.get("reason", ""))
            else:
                # 回退到确定性评分
                pro_score = self._prover(bundle.query, bundle.target, item)
                con_score = self._challenger(bundle.query, bundle.target, item, kept_anchors)
                judge_score = max(0.0, min(1.0, pro_score - con_score * 0.55 + item.score * 0.35))
                reason = "LLM 未评估此证据，使用确定性评分"

            # 任务 9.1: 低分证据直接拦截（知识库覆盖不足检测）
            if item.score < EVIDENCE_MIN_THRESHOLD and judge_score < 0.30:
                keep = False
                reason = f"【知识库覆盖不足】证据分 {item.score:.2f} 低于阈值 {EVIDENCE_MIN_THRESHOLD}，已拦截"
            else:
                keep = judge_score >= self.min_score

            verdict = DebateVerdict(
                evidence_id=item.id,
                pro_score=round(pro_score, 4),
                con_score=round(con_score, 4),
                judge_score=round(judge_score, 4),
                keep=keep,
                reason=reason,
            )
            verdicts.append(verdict)
            if keep:
                clean.append(item.with_score(judge_score))
                kept_anchors.update(item.anchors)

        # 兜底：所有证据都被剔除时保留最高分
        if not clean and bundle.evidence:
            best = max(bundle.evidence, key=lambda e: e.score)
            clean.append(best.with_score(max(best.score, self.min_score)))
            verdicts.append(
                DebateVerdict(
                    evidence_id=best.id,
                    pro_score=best.score,
                    con_score=0.0,
                    judge_score=max(best.score, self.min_score),
                    keep=True,
                    reason="LLM 辩论兜底：保留最高分证据避免空上下文",
                )
            )

        # 任务 9.1: 构建辩论轨迹
        trajectory = [
            {
                "evidence_id": v.evidence_id,
                "pro_score": v.pro_score,
                "con_score": v.con_score,
                "judge_score": v.judge_score,
                "keep": v.keep,
                "reason": v.reason,
                "method": "llm_debate",
            }
            for v in verdicts
        ]
        all_scores = [v.judge_score for v in verdicts]
        mean_judge = sum(all_scores) / max(len(all_scores), 1)
        knowledge_gap = any(v.judge_score < 0.30 and not v.keep for v in verdicts)

        return DebateResult(
            clean_evidence=tuple(clean),
            verdicts=tuple(verdicts),
            trajectory=tuple(trajectory),
            knowledge_gap=knowledge_gap,
            mean_judge_score=round(mean_judge, 4),
        )

    def _collective_batch_judge(self, bundle: RetrievalBundle) -> list[dict[str, Any]]:
        """对整个证据集进行 LLM 批量评估，模拟 Prover-Challenger-Judge 三层对话。"""
        # 构建证据摘要
        evidence_lines = []
        for i, item in enumerate(bundle.evidence):
            evidence_lines.append(
                f"[{i}] ID={item.id} | 标题={item.title} | "
                f"来源={item.source} | 类型={item.modality.value} | "
                f"标签={','.join(item.tags)} | 锚点={','.join(item.anchors)}"
            )

        system_prompt = (
            "你是 EduMatrix 的证据辩论裁判委员会主席。你的任务是对检索到的教学证据进行三轮思维评估。\n\n"
            "三轮评估规则：\n"
            "1. 正方(Prover)评估：该证据与查询的相关性、权威性和教学价值（0~1）\n"
            "2. 反方(Challenger)评估：该证据是否存在概念矛盾、过时信息、噪声风险（0~1）\n"
            "3. 法官(Judge)综合裁决：综合正反方意见给出最终保留分（0~1），低于0.5分建议剔除\n\n"
            "打分准则：\n"
            "- 学术源（arXiv等）自动获得 pro_score +0.25 信用分\n"
            "- 概念矛盾（如查询最大池化但证据讲平均池化）con_score 应极高（>0.7）\n"
            "- 图像证据与数学概念查询匹配时 pro_score 应 +0.1\n"
            "- 多模态一致性：如果多个证据间存在相互矛盾的概念，con_score 应升高\n\n"
            "请以纯 JSON 数组格式返回，不要包含其他文字：\n"
            '[{"evidence_id": "...", "pro_score": 0.0, "con_score": 0.0, '
            '"judge_score": 0.0, "reason": "..."}]'
        )

        user_prompt = (
            f"查询：{bundle.query}\n"
            f"目标知识点：{bundle.target}\n"
            f"完整学习路径：{' -> '.join(bundle.graph_context.learning_path)}\n\n"
            f"待评估证据列表（共{len(bundle.evidence)}条）：\n"
            + "\n".join(evidence_lines)
        )

        try:
            import inspect
            # Sync callers deliberately use deterministic scoring for async LLMs.
            if hasattr(self.llm, 'generate'):
                if inspect.iscoroutinefunction(self.llm.generate):
                    return []
                raw = self.llm.generate(system_prompt, user_prompt, role="证据辩论裁判")
            else:
                raw = self.llm.chat(system_prompt, user_prompt)

            # 解析 JSON
            json_match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if not json_match:
                return []
            parsed = json.loads(json_match.group())
            if not isinstance(parsed, list):
                return []
            return parsed
        except Exception as exc:
            print(f"  [DragDebate] LLM 辩论失败，回退确定性评分: {exc}")
            return []

    async def _collective_batch_judge_async(self, bundle: RetrievalBundle) -> list[dict[str, Any]]:
        """Run the collective judge without nesting an event loop."""
        evidence_lines = [
            f"[{i}] ID={item.id} | 标题={item.title} | 来源={item.source} | "
            f"类型={item.modality.value} | 标签={','.join(item.tags)} | 锚点={','.join(item.anchors)}"
            for i, item in enumerate(bundle.evidence)
        ]
        system_prompt = (
            "你是 EduMatrix 的证据辩论裁判委员会主席。请按正方、反方、法官三轮评估教学证据。\n"
            "正方评估相关性、权威性和教学价值；反方评估矛盾、过时信息和噪声；法官给出 0~1 的最终分。\n"
            "仅返回 JSON 数组：[{'evidence_id':'...','pro_score':0.0,'con_score':0.0,"
            "'judge_score':0.0,'reason':'...'}]，不要输出其他文字。"
        )
        user_prompt = (
            f"查询：{bundle.query}\n目标知识点：{bundle.target}\n"
            f"完整学习路径：{' -> '.join(bundle.graph_context.learning_path)}\n\n"
            f"待评估证据列表（共{len(bundle.evidence)}条）：\n" + "\n".join(evidence_lines)
        )
        try:
            raw = await self.llm.generate(system_prompt, user_prompt, role="证据辩论裁判")
            json_match = re.search(r"\[.*?\]", raw, re.DOTALL)
            if not json_match:
                return []
            parsed = json.loads(json_match.group())
            return parsed if isinstance(parsed, list) else []
        except Exception as exc:
            print(f"  [DragDebate] 异步 LLM 辩论失败，回退确定性评分: {exc}")
            return []

    # ================================================================
    # 原始确定性评分函数（LLM 不可用时的回退路径）
    # ================================================================

    def _deterministic_clean(self, bundle: RetrievalBundle) -> DebateResult:
        """原始确定性评分函数路径。"""
        verdicts: list[DebateVerdict] = []
        clean: list[Evidence] = []
        kept_anchors: set[str] = set()
        # 任务 9.1: 低分证据直接拦截（知识库覆盖不足检测）
        for item in bundle.evidence:
            if item.score < EVIDENCE_MIN_THRESHOLD and item.score < self.min_score * 0.6:
                # 将拦截记录注入兜底逻辑
                pass

        for item in bundle.evidence:
            pro_score = self._prover(bundle.query, bundle.target, item)
            con_score = self._challenger(bundle.query, bundle.target, item, kept_anchors)
            judge_score = max(0.0, min(1.0, pro_score - con_score * 0.55 + item.score * 0.35))

            # 任务 9.1: 低分证据直接拦截
            if item.score < EVIDENCE_MIN_THRESHOLD and judge_score < 0.30:
                keep = False
                reason = f"【知识库覆盖不足】证据分 {item.score:.2f} 低于阈值 {EVIDENCE_MIN_THRESHOLD}，已拦截"
            else:
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

        # 兜底
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

        # 任务 9.1: 构建辩论轨迹
        trajectory = [
            {
                "evidence_id": v.evidence_id,
                "pro_score": v.pro_score,
                "con_score": v.con_score,
                "judge_score": v.judge_score,
                "keep": v.keep,
                "reason": v.reason,
                "method": "deterministic",
            }
            for v in verdicts
        ]
        all_scores = [v.judge_score for v in verdicts]
        mean_judge = sum(all_scores) / max(len(all_scores), 1)
        knowledge_gap = any(v.judge_score < 0.30 and not v.keep for v in verdicts)

        return DebateResult(
            clean_evidence=tuple(clean),
            verdicts=tuple(verdicts),
            trajectory=tuple(trajectory),
            knowledge_gap=knowledge_gap,
            mean_judge_score=round(mean_judge, 4),
        )

    def _prover(self, query: str, target: str, item: Evidence) -> float:
        text = " ".join((item.title, item.content, " ".join(item.tags), " ".join(item.anchors)))
        score = item.score

        if item.metadata.get("is_academic") or item.source == "arXiv.org":
            score += 0.25

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
        if keep and (item.metadata.get("is_academic") or item.source == "arXiv.org"):
            action = "学术保留"
        return (
            f"{action} {item.title}：正方相关性 {pro:.2f}，反方噪声/矛盾风险 {con:.2f}，"
            f"法官分 {judge:.2f}。"
        )
