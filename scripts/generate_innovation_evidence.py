"""Generate reproducible, non-fabricated innovation evidence.

The output separates structural code measurements from synthetic demo data. It
does not claim user-study accuracy, hallucination rate, or learning gains.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_swarm import EduMatrixSwarm
from drag_debate import DebateAugmentedRAG
from llm_client import AsyncDeterministicEducationLLM
from models import StudentProfile
from rag_engine import hybrid_rag


OUTPUT_DIR = ROOT / "outputs" / "innovation_evidence"


class OfflineRAG:
    """Adapter that prevents arXiv/video requests during evidence generation."""

    def retrieve(self, query, target=None, top_k=6, profile=None, doc_constraint=None):
        return hybrid_rag.retrieve(
            query,
            target=target,
            top_k=top_k,
            profile=profile,
            disable_external=True,
            doc_constraint=doc_constraint,
        )


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def profile_snapshot(profile: StudentProfile) -> dict[str, Any]:
    return {
        "student_id": profile.student_id,
        "major": profile.major,
        "target_course": profile.target_course,
        "learning_goals": profile.learning_goals,
        "interaction_preferences": profile.interaction_preferences,
        "cognitive_style": profile.cognitive_style,
        "weak_points": profile.weak_points,
        "learning_state_causes": jsonable(profile.learning_state_causes),
        "dimension_states": jsonable(profile.dimension_states),
        "cognitive_load": profile.cognitive_load,
    }


def package_snapshot(package) -> dict[str, Any]:
    debate = DebateAugmentedRAG().clean(package.retrieval)
    return {
        "student_id": package.student_id,
        "target": package.target,
        "resource_count": len(package.resources),
        "resource_types": [item.resource_type for item in package.resources],
        "resource_agents": [item.agent for item in package.resources],
        "citation_count": sum(len(item.citations) for item in package.resources),
        "resource_previews": [
            {
                "agent": item.agent,
                "resource_type": item.resource_type,
                "content_preview": item.content[:220],
                "citations": list(item.citations),
            }
            for item in package.resources
        ],
        "retrieval": {
            "evidence_count": len(package.retrieval.evidence),
            "evidence_ids": [item.id for item in package.retrieval.evidence],
            "evidence_sources": [item.source for item in package.retrieval.evidence],
            "graph_learning_path": list(package.retrieval.graph_context.learning_path),
            "graph_prerequisite_edges": [list(edge) for edge in package.retrieval.graph_context.prerequisite_edges],
            "graph_downstream_edges": [list(edge) for edge in package.retrieval.graph_context.downstream_edges],
            "low_confidence": package.retrieval.low_confidence,
            "out_of_domain": package.retrieval.out_of_domain,
        },
        "debate": {
            "verdict_count": len(debate.verdicts),
            "kept_count": len(debate.clean_evidence),
            "kept_evidence_ids": [item.id for item in debate.clean_evidence],
        },
        "alignment": jsonable(package.alignment),
        "learning_signal": jsonable(package.learning_signal),
        "strategy_plan": jsonable(package.strategy_plan),
        "profile_after": profile_snapshot(package.profile),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fixed_knowledge_set = [
        {
            "id": "fixed-ml-eval-001",
            "topic": "混淆矩阵与召回率",
            "statement": "Recall = TP / (TP + FN)，正类样本稀少时仅看 accuracy 可能掩盖漏检。",
            "data_label": "公开知识整理后的固定演示知识集",
        },
        {
            "id": "fixed-ml-pooling-001",
            "topic": "最大池化与平均池化",
            "statement": "最大池化在窗口内选择最大值，平均池化计算窗口均值；二者不是同一算子。",
            "data_label": "公开教材概念整理后的固定演示知识集",
        },
        {
            "id": "fixed-ml-regularization-001",
            "topic": "L1/L2 正则化",
            "statement": "L1 惩罚绝对值和，L2 惩罚平方和；正则项会改变优化目标与参数偏好。",
            "data_label": "公开教材概念整理后的固定演示知识集",
        },
    ]
    (OUTPUT_DIR / "fixed_knowledge_set.json").write_text(
        json.dumps(fixed_knowledge_set, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    profile_specs = [
        {
            "id": "synthetic_visual",
            "label": "视觉型计算机本科生",
            "major": "计算机科学与技术",
            "goals": ["期末复习冲刺"],
            "preferences": ["图示演示", "具体例子"],
            "style": "视觉演示导向",
        },
        {
            "id": "synthetic_engineering",
            "label": "项目型软件工程学生",
            "major": "软件工程",
            "goals": ["求职面试准备"],
            "preferences": ["代码实操", "分步引导"],
            "style": "代码实操导向",
        },
        {
            "id": "synthetic_research",
            "label": "跨专业研究型学习者",
            "major": "数学",
            "goals": ["科研学术深造"],
            "preferences": ["对比解析", "分步引导"],
            "style": "文本阅读导向",
        },
    ]
    profiles = {}
    for spec in profile_specs:
        profiles[spec["id"]] = StudentProfile(
            student_id=spec["id"],
            major=spec["major"],
            learning_goals=list(spec["goals"]),
            interaction_preferences=list(spec["preferences"]),
            cognitive_style=spec["style"],
        )
    (OUTPUT_DIR / "synthetic_profiles.json").write_text(
        json.dumps(
            [
                {**spec, "data_label": "合成演示数据，不代表真实用户调研"}
                for spec in profile_specs
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    swarm = EduMatrixSwarm(
        rag=OfflineRAG(),
        llm=AsyncDeterministicEducationLLM(),
        profile_store=profiles,
    )
    query = "一键生成资源包: 请解释最大池化和平均池化的区别，并给出图示、代码和练习。"
    profile_cases = []
    for spec in profile_specs:
        package = swarm.process(query, student_id=spec["id"])
        profile_cases.append({
            "profile": spec,
            "package": package_snapshot(package),
        })

    bundle = hybrid_rag.retrieve(
        "最大池化和平均池化的区别",
        target="池化层",
        disable_external=True,
    )
    rag_evidence = {
        "query": bundle.query,
        "target": bundle.target,
        "evidence_count": len(bundle.evidence),
        "evidence": [
            {
                "id": item.id,
                "title": item.title,
                "source": item.source,
                "modality": item.modality.value,
                "score": round(item.score, 4),
            }
            for item in bundle.evidence
        ],
        "data_label": "代码实测：本地固定/内置知识索引，外部检索已禁用",
    }

    multi_agent_types = sorted({item for case in profile_cases for item in case["package"]["resource_types"]})
    benchmark = {
        "data_label": "结构性代码实测 + 合成演示基线，不是用户效果实验",
        "protocol": {
            "profiles": len(profile_cases),
            "same_query": query,
            "llm": "AsyncDeterministicEducationLLM",
            "external_search": "disabled",
        },
        "single_agent_vs_multi_agent": {
            "single_agent_baseline": {
                "resource_count": 1,
                "resource_types": ["单段文本"],
                "required_resource_type_coverage": "0/5 (基线定义)",
            },
            "edumatrix_multi_agent": {
                "resource_count_per_case": [case["package"]["resource_count"] for case in profile_cases],
                "resource_types_observed": multi_agent_types,
                "required_resource_type_coverage": f"{len(multi_agent_types)}/5 (代码实测)",
            },
        },
        "without_profile_vs_with_profile": {
            "without_profile_baseline": {
                "profile_fields": 0,
                "adaptation_basis": [],
                "data_label": "基线定义，不宣称质量结果",
            },
            "with_profile": {
                "profile_fields_observed": [
                    "major", "learning_goals", "interaction_preferences", "cognitive_style", "learning_state_causes"
                ],
                "cases": [
                    {
                        "label": item["profile"]["label"],
                        "major_before": item["profile"]["major"],
                        "major_after": item["package"]["profile_after"]["major"],
                        "preferences_before": item["profile"]["preferences"],
                        "preferences_after": item["package"]["profile_after"]["interaction_preferences"],
                        "style_after": item["package"]["profile_after"]["cognitive_style"],
                        "target": item["package"]["target"],
                        "strategy_target": (item["package"]["strategy_plan"] or {}).get("target") if isinstance(item["package"]["strategy_plan"], dict) else None,
                    }
                    for item in profile_cases
                ],
            },
        },
        "without_rag_vs_with_rag": {
            "without_rag_baseline": {"citation_count": 0, "evidence_count": 0},
            "with_rag": rag_evidence,
        },
    }
    (OUTPUT_DIR / "innovation_benchmark.json").write_text(
        json.dumps(benchmark, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "profile_cases.json").write_text(
        json.dumps(profile_cases, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report = f"""# EduMatrix 创新对比与合成证据报告

> 生成方式：源码真实运行 + 固定本地知识索引 + 合成演示画像。
> 
> 本报告不声称真实用户实验、学习提升率、幻觉率或适配准确率已经达标。

## 1. 可复现实验配置

- 同一问题：`{query}`
- 画像数量：{len(profile_cases)} 组，全部为合成演示数据。
- LLM：`AsyncDeterministicEducationLLM`。
- 外部 arXiv/视频搜索：禁用，避免网络结果污染证据。
- 原始 JSON：`synthetic_profiles.json`、`fixed_knowledge_set.json`、`innovation_benchmark.json`、`profile_cases.json`。

## 2. 单 Agent 与多 Agent

单段文本基线只产生 1 个资源类型；EduMatrix 实际运行每组产生 `{profile_cases[0]['package']['resource_count']}` 个资源，观察到的资源类型为：

`{'、'.join(multi_agent_types)}`

这证明的是资源分工、并行工厂和输出结构存在，不等于已经证明教学效果优于单 Agent。

## 3. 无画像与有画像

无画像基线没有专业、目标、偏好和认知状态字段；三组合成画像实际进入 Swarm，并在输出中保留不同专业、目标、偏好、不会原因、资源类型和学习策略字段。具体输入/输出差异见 `innovation_benchmark.json` 与 `profile_cases.json`，答辩时应称为“合成画像流程对比”。

## 4. 无 RAG 与有 RAG

无 RAG 基线没有证据 ID 和来源；本次本地检索实际返回 `{rag_evidence['evidence_count']}` 条证据，详情见 `innovation_benchmark.json`。这证明证据链路可观察，不把证据数量直接解释为事实正确率。

## 5. 评委展示建议

1. 先展示同一问题下三组画像的输入差异。
2. 展示 Agent Timeline 和五类资源卡片，说明职责分工。
3. 展示 RAG 证据 ID、来源和对齐结果。
4. 明确标注所有画像和基线为合成/结构性演示数据。
5. 不宣称 `幻觉率 <5%`、`适配准确率 >=85%` 或真实学习提升，除非另有合规标注集和真实实验记录。
"""
    (OUTPUT_DIR / "innovation_evidence_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({
        "result": "passed",
        "profiles": len(profile_cases),
        "resources_per_profile": [case["package"]["resource_count"] for case in profile_cases],
        "rag_evidence": rag_evidence["evidence_count"],
        "output": str(OUTPUT_DIR.relative_to(ROOT)).replace("\\", "/"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
