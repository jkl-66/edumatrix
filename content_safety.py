from __future__ import annotations

import re
from typing import Any

SENSITIVE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(色情|赌博|毒品|枪支|暴力|血腥|自杀|自残|邪教|恐怖|分裂|反动|谣言|诈骗)", re.IGNORECASE),
    re.compile(r"(艳照|裸聊|一夜情|迷药|卖淫|嫖娼|招嫖|毒品交易|制毒|吸毒)", re.IGNORECASE),
    re.compile(r"(枪支买卖|军火|爆炸物|制枪|贩卖人口|器官买卖|洗钱|高利贷)", re.IGNORECASE),
    re.compile(r"(黑社会|暴力催收|人身攻击|辱骂|歧视|种族歧视|地域歧视)", re.IGNORECASE),
    re.compile(r"(baoliao|liuhecai|duchang|bo彩|地下钱庄|非法集资)", re.IGNORECASE),
)

HALLUCINATION_MARKERS: tuple[re.Pattern, ...] = (
    re.compile(r"(根据维基百科|据维基百科|Wikipedia says|According to Wikipedia)", re.IGNORECASE),
    re.compile(r"(据我所知这没有依据|我不确定|据不确定来源|可能不准确)", re.IGNORECASE),
    re.compile(r"(据某专家表示|据业内人士透露|据传言|据说|据称)", re.IGNORECASE),
    re.compile(r"(据202[0-9]年统计|根据最新研究|据权威数据)", re.IGNORECASE),
)

ACADEMIC_TERM_WHITELIST: tuple[str, ...] = (
    "反向传播", "链式法则", "梯度下降", "损失函数", "激活函数",
    "卷积", "池化", "全连接", "特征图", "正则化",
    "交叉验证", "混淆矩阵", "过拟合", "欠拟合", "逻辑回归",
    "线性回归", "决策树", "支持向量机", "朴素贝叶斯",
    "Transformer", "注意力机制", "LSTM", "RNN", "CNN",
    "Python", "PyTorch", "TensorFlow", "NumPy", "Pandas",
    "Matplotlib", "Scikit-learn", "Jupyter", "Docker",
    "概率", "统计", "线性代数", "微积分", "矩阵",
    "最大池化", "平均池化", "MaxPool2d", "AvgPool2d",
    "Sigmoid", "ReLU", "Tanh", "Softmax", "Dropout",
    "BatchNorm", "LayerNorm", "残差连接", "跳跃连接",
)

SUBJECT_WHITELIST: tuple[str, ...] = (
    "机器学习", "深度学习", "人工智能", "数据科学",
    "计算机视觉", "自然语言处理", "强化学习",
    "数据分析", "数据挖掘", "模式识别",
    "算法", "数据结构", "操作系统", "计算机网络",
    "数据库", "软件工程", "编译原理",
)


class ContentSafetyFilter:
    def __init__(self) -> None:
        self.violation_count = 0

    def check_safety(self, text: str) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        score = 1.0

        for pattern in SENSITIVE_PATTERNS:
            matches = pattern.findall(text)
            for match in matches:
                context = self._extract_context(text, text.index(match) if match in text else 0)
                issues.append({
                    "type": "sensitive_content",
                    "match": match,
                    "context": context,
                    "severity": "high",
                })
                score -= 0.25

        for pattern in HALLUCINATION_MARKERS:
            matches = pattern.findall(text)
            for match in matches:
                context = self._extract_context(text, text.index(match) if match in text else 0)
                issues.append({
                    "type": "hallucination_risk",
                    "match": match,
                    "context": context,
                    "severity": "medium",
                })
                score -= 0.15

        if "http" in text or "https" in text:
            urls = re.findall(r"https?://[^\s]+", text)
            for url in urls:
                if any(domain in url for domain in ("porn", "xxx", "gambling", "casino", "bet")):
                    issues.append({
                        "type": "unsafe_url",
                        "match": url[:60],
                        "context": url[:80],
                        "severity": "high",
                    })
                    score -= 0.3

        passed = score >= 0.6
        if not passed:
            self.violation_count += 1

        return {
            "passed": passed,
            "score": max(0.0, score),
            "issues": issues,
            "suggestion": "内容已通过安全审查" if passed else f"检测到 {len(issues)} 个安全问题，建议修正后重新生成",
        }

    def sanitize(self, text: str) -> str:
        result = text
        for pattern in SENSITIVE_PATTERNS:
            result = pattern.sub("***", result)
        return result

    def check_academic_validity(self, text: str, target_concept: str) -> dict[str, Any]:
        issues: list[str] = []
        term_count = sum(1 for term in ACADEMIC_TERM_WHITELIST if term in text)
        if term_count == 0 and not any(subj in text for subj in SUBJECT_WHITELIST):
            issues.append("未检测到专业术语，内容可能偏离学术范围")

        concept_variants = [
            target_concept,
            target_concept.lower(),
            target_concept.replace(" ", ""),
        ]
        concept_found = any(variant in text for variant in concept_variants)
        if not concept_found:
            for part in re.split(r"[与和、,，\s]+", target_concept):
                if len(part) > 1 and part in text:
                    concept_found = True
                    break

        return {
            "passed": len(issues) == 0,
            "term_count": term_count,
            "concept_covered": concept_found,
            "warnings": issues,
        }

    def _extract_context(self, text: str, position: int, window: int = 30) -> str:
        start = max(0, position - window)
        end = min(len(text), position + window)
        context = text[start:end]
        if start > 0:
            context = "..." + context
        if end < len(text):
            context = context + "..."
        return context


CONTENT_SAFETY = ContentSafetyFilter()
