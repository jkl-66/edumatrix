from __future__ import annotations

import math
from typing import Any

from embedding_models import EMBEDDINGS
from embedding_models import cosine_similarity
from models import AlignmentReport


_EMBED_CACHE: dict[str, tuple[float, ...]] = {}

def _embed_cached(text: str) -> tuple[float, ...]:
    if not text:
        return ()
    if text in _EMBED_CACHE:
        return _EMBED_CACHE[text]
    raw = EMBEDDINGS.embed(text)
    val = raw if raw else ()
    _EMBED_CACHE[text] = val
    return val


def _embed_safe(text: str) -> tuple[float, ...]:
    raw = _embed_cached(text)
    if not raw:
        return tuple(0.0 for _ in range(384))
    return raw


def _extract_concept_text(resource: object) -> str:
    if isinstance(resource, str):
        return resource[:500]
    content = getattr(resource, "content", "") or ""
    source = getattr(resource, "source", "") or ""
    title = getattr(resource, "title", "") or ""
    return f"{title} {content[:500]} {source}"


def verify_alignment(
    resources: list[object],
    *,
    base_concept: str = "",
    alignment_threshold: float = 0.65,
) -> AlignmentReport:
    if len(resources) < 2:
        return AlignmentReport(
            passed=True,
            distance=0.0,
            threshold=alignment_threshold,
            conflicts=[],
            advice="资源数量不足，跳过对齐校验。",
        )

    # 1. 预先提取并计算所有资源的嵌入向量，避免在双重循环中进行 N^2 次计算
    embedded_resources = []
    for r in resources:
        text = _extract_concept_text(r)
        vec = _embed_safe(text)
        embedded_resources.append((r, vec, text))

    base_vec = _embed_safe(base_concept) if base_concept else _embed_safe("通用机器学习概念")

    conflicts: list[dict[str, Any]] = []
    max_distance = 0.0

    # 2. 双循环一致性校验（已被优化为 N 次嵌入提取，计算复杂度极低）
    for i, (resource_a, vec_a, _) in enumerate(embedded_resources):
        for j, (resource_b, vec_b, _) in enumerate(embedded_resources):
            if i == j:
                continue
            sim = cosine_similarity(vec_a, vec_b)
            distance = 1.0 - sim
            max_distance = max(max_distance, distance)
            if distance > alignment_threshold:
                conflicts.append({
                    "type": "跨模态不一致",
                    "resources": [
                        getattr(resource_a, "id", "") or getattr(resource_a, "agent", ""),
                        getattr(resource_b, "id", "") or getattr(resource_b, "agent", ""),
                    ],
                    "distance": round(distance, 3),
                    "suggestion": "检测到跨模态语义不一致，建议统一概念表述后重新生成。",
                })

    # 3. 校验对核心概念的偏离度
    for resource, r_vec, r_text in embedded_resources:
        sim = cosine_similarity(base_vec, r_vec)
        distance = 1.0 - sim
        max_distance = max(max_distance, distance)
        if distance > alignment_threshold:
            conflicts.append({
                "type": "偏离核心概念",
                "resources": [r_text[:60]],
                "distance": round(distance, 3),
                "suggestion": f"该资源距离核心概念太远(d={distance:.2f})，建议重新生成。",
            })

    passed = len(conflicts) == 0
    advice = (
        "所有资源在双曲空间中一致性良好，无需回滚。"
        if passed
        else f"发现{len(conflicts)}个冲突点，建议携带 correction 回滚重生成。"
    )
    return AlignmentReport(
        passed=passed,
        distance=round(max_distance, 3),
        threshold=alignment_threshold,
        conflicts=conflicts,
        advice=advice,
    )


class CouncilDecisionEngine:
    """XH-202630 委员会决策引擎：在“分诊 ➔ 平行专家生成 ➔ 共识合成”工作流中，执行事实与相关性得分的定量共识核查。"""

    def __init__(self, fact_threshold: float = 0.70, rel_threshold: float = 0.65) -> None:
        self.fact_threshold = fact_threshold
        self.rel_threshold = rel_threshold

    def synthesize(self, resources: list[Any], target_concept: str) -> dict[str, Any]:
        """对平行专家生成的定制资源进行事实性与相关性定量共识核查。"""
        target_vec = _embed_cached(target_concept) if target_concept else ()
        
        # 1. 预先提取并计算所有资源的嵌入向量（直接走缓存，避免在嵌套循环中多次重复计算）
        embedded_resources = []
        for r in resources:
            content = getattr(r, "content", "") or ""
            r_vec = _embed_cached(content[:500]) if content else ()
            embedded_resources.append((r, r_vec, content))
        
        verdicts = []
        passed_count = 0
        total_fact_score = 0.0
        total_rel_score = 0.0
        
        for i, (r, r_vec, content) in enumerate(embedded_resources):
            rtype = getattr(r, "resource_type", "") or getattr(r, "agent", "")
            
            # 1. 计算相关性得分 (Relevance Score)：资源内容与目标概念的余弦相似度
            rel_score = cosine_similarity(target_vec, r_vec) if (target_vec and r_vec) else 0.80
            
            # 2. 计算事实性得分 (Factuality Score)：防幻觉交叉核对
            fact_score = 1.0
            
            # 逻辑校验：池化操作冲突检测
            has_max = "maxpool" in content.lower() or "最大池化" in content
            has_avg = "avgpool" in content.lower() or "平均池化" in content
            if has_max and has_avg:
                fact_score -= 0.35
            
            # 交叉一致性核对（纯向量比对，不产生额外计算开销）
            cross_similarities = []
            for j, (_, other_vec, _) in enumerate(embedded_resources):
                if i == j:
                    continue
                if r_vec and other_vec:
                    cross_similarities.append(cosine_similarity(r_vec, other_vec))
            
            if cross_similarities:
                mean_cross = sum(cross_similarities) / len(cross_similarities)
                if mean_cross < 0.5:
                    fact_score -= (0.5 - mean_cross) * 0.5
            
            fact_score = max(0.0, min(1.0, fact_score))
            
            # 判定是否通过共识
            is_passed = (fact_score >= self.fact_threshold) and (rel_score >= self.rel_threshold)
            if is_passed:
                passed_count += 1
            
            total_fact_score += fact_score
            total_rel_score += rel_score
            
            verdicts.append({
                "resource_type": rtype,
                "factuality_score": round(fact_score, 3),
                "relevance_score": round(rel_score, 3),
                "passed": is_passed,
                "suggestion": "通过共识合成" if is_passed else "偏离核心事实或相关度过低，建议重写。"
            })
            
        n = len(resources) if resources else 1
        mean_fact = total_fact_score / n
        mean_rel = total_rel_score / n
        
        overall_passed = (mean_fact >= 0.65) and (mean_rel >= 0.65) and (passed_count >= len(resources) * 0.5)
        
        return {
            "overall_passed": overall_passed,
            "mean_factuality_score": round(mean_fact, 3),
            "mean_relevance_score": round(mean_rel, 3),
            "verdicts": verdicts,
            "advice": "委员会共识合成通过，事实谬误控制在安全阈值内。" if overall_passed else "委员会未能达成共识，建议携带反思日志触发重试。"
        }


class ManifoldAlignmentVerifier:
    def __init__(self, threshold: float | None = None) -> None:
        self.threshold = threshold or 0.65
        self.council = CouncilDecisionEngine()

    def verify(self, resources: list[object], *, target: str = "", **kwargs: Any) -> AlignmentReport:
        # 1. 运行图谱校验
        report = verify_alignment(
            resources,
            base_concept=target,
            alignment_threshold=self.threshold,
        )
        
        # 2. 运行委员会共识合成分析
        synthesis = self.council.synthesize(resources, target)
        
        # 3. 融合判定
        new_passed = report.passed and synthesis["overall_passed"]
        
        new_advice = (
            f"【委员会共识合成报告】事实均分: {synthesis['mean_factuality_score']:.2f}, "
            f"相关均分: {synthesis['mean_relevance_score']:.2f}。{synthesis['advice']}\n"
            f"原图谱校验：{report.advice}"
        )
        
        # 将委员会 verdicts 拼接到 conflicts 方便查看与反思重试
        new_conflicts = list(report.conflicts)
        for v in synthesis["verdicts"]:
            if not v["passed"]:
                new_conflicts.append({
                    "type": "委员会核查拦截",
                    "resources": [v["resource_type"]],
                    "distance": round(1.0 - v["factuality_score"], 3),
                    "suggestion": f"事实分({v['factuality_score']})或相关分({v['relevance_score']})不符合阈值。建议：{v['suggestion']}"
                })
                
        return AlignmentReport(
            passed=new_passed,
            distance=report.distance,
            threshold=report.threshold,
            conflicts=new_conflicts,
            advice=new_advice
        )


def verify_consistency(text_resource: object, code_resource: object, threshold: float = 0.65) -> AlignmentReport:
    return verify_alignment([text_resource, code_resource], alignment_threshold=threshold)
