from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any


class EvidenceModality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    GRAPH = "graph"
    CODE = "code"


class ProfileEvidenceSource(str, Enum):
    STUDENT_MESSAGE = "student_message"
    STUDENT_FEEDBACK = "student_feedback"
    PERFORMANCE_SIGNAL = "performance_signal"


class LearningStateCause(str, Enum):
    PREREQUISITE_GAP = "prerequisite_gap"
    MISCONCEPTION = "misconception"
    COGNITIVE_LOAD = "cognitive_load"
    STRATEGY_GAP = "strategy_gap"
    METACOGNITIVE_MISMATCH = "metacognitive_mismatch"
    AFFECTIVE_BARRIER = "affective_barrier"
    INTERACTION_MISMATCH = "interaction_mismatch"


class StrategyType(str, Enum):
    RETRIEVAL_PRACTICE = "retrieval_practice"
    SPACED_REVIEW = "spaced_review"
    WORKED_EXAMPLE = "worked_example"
    HINT_LADDER = "hint_ladder"
    MISCONCEPTION_CONTRAST = "misconception_contrast"
    METACOGNITIVE_CALIBRATION = "metacognitive_calibration"


CAUSE_LABELS: dict[str, str] = {
    LearningStateCause.PREREQUISITE_GAP.value: "前置知识缺口",
    LearningStateCause.MISCONCEPTION.value: "误概念/易混点",
    LearningStateCause.COGNITIVE_LOAD.value: "认知负荷过高",
    LearningStateCause.STRATEGY_GAP.value: "学习策略不足",
    LearningStateCause.METACOGNITIVE_MISMATCH.value: "自我判断失准",
    LearningStateCause.AFFECTIVE_BARRIER.value: "情绪与信心阻滞",
    LearningStateCause.INTERACTION_MISMATCH.value: "讲解方式适配需求",
}


DIMENSION_LABELS: dict[str, str] = {
    "knowledge_mastery": "知识基础",
    "misconception_profile": "易错点与误概念",
    "understanding_fluency_transfer": "理解-熟练-迁移",
    "cognitive_processing": "认知加工与负荷",
    "learning_strategy": "学习策略",
    "metacognition": "元认知与自我调节",
    "motivation_and_purpose": "动机目标与意义感",
    "affect_resilience": "情绪信心与韧性",
    "interaction_preference": "互动与表达偏好",
    "learning_context": "学习情境与公平支持",
}


CAUSE_INTERVENTIONS: dict[str, tuple[str, ...]] = {
    LearningStateCause.PREREQUISITE_GAP.value: (
        "先补前置概念，再进入目标知识点",
        "用 2-3 个微诊断题验证前置掌握",
    ),
    LearningStateCause.MISCONCEPTION.value: (
        "使用反例辨析和对照表拆开相似概念",
        "让学生先解释错误答案为什么看似合理",
    ),
    LearningStateCause.COGNITIVE_LOAD.value: (
        "把任务拆成不超过 3 步的小块",
        "用图示、条件清单和 worked example 降低负荷",
    ),
    LearningStateCause.STRATEGY_GAP.value: (
        "强制加入检索练习、错因复盘和间隔复习",
        "减少直接给答案，改用提示阶梯",
    ),
    LearningStateCause.METACOGNITIVE_MISMATCH.value: (
        "每题前记录自评置信度，题后校准",
        "用短测区分看懂、会做和能迁移",
    ),
    LearningStateCause.AFFECTIVE_BARRIER.value: (
        "降低第一题难度，先建立可见进步证据",
        "反馈聚焦下一步行动，不做人格评价",
    ),
    LearningStateCause.INTERACTION_MISMATCH.value: (
        "根据学生反馈切换讲解形式",
        "保留学生偏好的图、代码、例子或苏格拉底追问",
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class Evidence:
    id: str
    title: str
    content: str
    modality: EvidenceModality
    source: str
    tags: tuple[str, ...] = ()
    anchors: tuple[str, ...] = ()
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_score(self, score: float) -> "Evidence":
        return Evidence(
            id=self.id,
            title=self.title,
            content=self.content,
            modality=self.modality,
            source=self.source,
            tags=self.tags,
            anchors=self.anchors,
            score=score,
            metadata=self.metadata,
        )


@dataclass(frozen=True)
class GraphContext:
    target: str
    learning_path: tuple[str, ...]
    prerequisite_edges: tuple[tuple[str, str], ...]
    downstream_edges: tuple[tuple[str, str], ...]

    def to_prompt(self) -> str:
        path = " -> ".join(self.learning_path)
        prereq = "；".join(f"{a}->{b}" for a, b in self.prerequisite_edges) or "无"
        downstream = "；".join(f"{a}->{b}" for a, b in self.downstream_edges) or "无"
        return (
            f"GraphRAG目标知识点：{self.target}\n"
            f"完整学习路径：{path}\n"
            f"前置依赖边：{prereq}\n"
            f"后续应用边：{downstream}\n"
            "生成时必须覆盖关键前置概念、核心机制和常见误区。"
        )


@dataclass(frozen=True)
class RetrievalBundle:
    query: str
    target: str
    graph_context: GraphContext
    evidence: tuple[Evidence, ...]
    low_confidence: bool = False
    out_of_domain: bool = False

    def context_prompt(self) -> str:
        evidence_lines = []
        for item in self.evidence:
            evidence_lines.append(
                f"[{item.id}|{item.modality.value}|score={item.score:.2f}] "
                f"{item.title}: {item.content} 来源={item.source}"
            )
        return self.graph_context.to_prompt() + "\n" + "\n".join(evidence_lines)


@dataclass(frozen=True)
class DebateVerdict:
    evidence_id: str
    pro_score: float
    con_score: float
    judge_score: float
    keep: bool
    reason: str


@dataclass(frozen=True)
class ProfileEvidence:
    source: ProfileEvidenceSource
    text: str
    features: tuple[str, ...]
    weight: float
    confidence: float
    timestamp: str = field(default_factory=_utc_now)


@dataclass
class DimensionState:
    key: str
    label: str
    score: float
    confidence: float
    status: str
    evidence_count: int = 0
    evidence_fragments: list[str] = field(default_factory=list)
    recommended_interventions: list[str] = field(default_factory=list)
    last_updated: str = field(default_factory=_utc_now)


@dataclass
class CauseBreakdown:
    key: str
    label: str
    percentage: float
    confidence: float
    evidence_count: int
    evidence_fragments: list[str] = field(default_factory=list)
    recommended_interventions: list[str] = field(default_factory=list)


@dataclass
class KnowledgeTrace:
    concept: str
    mastery: float = 0.48
    attempts: int = 0
    correct_attempts: int = 0
    last_updated: str = field(default_factory=_utc_now)

    def update(self, *, correct: bool, hinted: bool = False) -> None:
        self.attempts += 1
        if correct:
            self.correct_attempts += 1
        learning_gain = 0.16 if correct else -0.10
        if hinted and correct:
            learning_gain *= 0.55
        if hinted and not correct:
            learning_gain *= 1.15
        self.mastery = round(_clamp(self.mastery + learning_gain), 2)
        self.last_updated = _utc_now()


@dataclass(frozen=True)
class StrategyAction:
    strategy: StrategyType
    title: str
    description: str
    trigger: str
    priority: int
    scheduled_after: str = "now"


@dataclass(frozen=True)
class LearningStrategyPlan:
    course: str
    target: str
    actions: tuple[StrategyAction, ...]
    rationale: str


@dataclass
class StudentProfile:
    student_id: str = "demo-student"
    target_course: str = "机器学习导论"
    knowledge_base: str = "初级"
    cognitive_style: str = "视觉+代码导向"
    weak_points: list[str] = field(default_factory=list)
    focus_level: float = 0.72
    major_preference: str = "人工智能实践"
    cognitive_load: float = 0.45
    history: list[str] = field(default_factory=list)
    major: str = ""
    learning_goals: list[str] = field(default_factory=list)
    interaction_preferences: list[str] = field(default_factory=list)
    profile_evidence: list[ProfileEvidence] = field(default_factory=list)
    dimension_states: dict[str, DimensionState] = field(default_factory=dict)
    learning_state_causes: dict[str, CauseBreakdown] = field(default_factory=dict)
    concept_mastery: dict[str, float] = field(default_factory=dict)
    misconception_patterns: dict[str, float] = field(default_factory=dict)
    knowledge_traces: dict[str, KnowledgeTrace] = field(default_factory=dict)
    favorites: list[dict] = field(default_factory=list)

    # === 替换 models.py 中的 add_favorite 方法 ===
    def add_favorite(self, target: str, resource_type: str, content: str, note: str = "", fav_id: str = "") -> None:
        import time
        # 如果前端传了 ID 就用前端的，否则后端生成
        fid = fav_id if fav_id else f"fav_{int(time.time())}_{len(self.favorites)}"
        self.favorites.append({
            "id": fid,
            "target": target,
            "resource_type": resource_type,
            "content_snippet": content[:120] + "...",
            "content": content,
            "note": note,
            "timestamp": time.time()
        })

    def remove_favorite(self, fav_id: str) -> None:
        """根据 ID 移除收藏项"""
        self.favorites = [f for f in self.favorites if f.get("id") != fav_id]

    def update_favorite_note(self, fav_id: str, note: str) -> None:
        """更新已有收藏的笔记"""
        for f in self.favorites:
            if f.get("id") == fav_id:
                f["note"] = note
                break

    def update_from_message(self, message: str) -> None:
        self.history.append(message)
        features = self._extract_features(message)
        if features:
            self.profile_evidence.append(
                ProfileEvidence(
                    source=ProfileEvidenceSource.STUDENT_MESSAGE,
                    text=message,
                    features=tuple(sorted(features)),
                    weight=min(1.0, 0.28 + 0.06 * len(features)),
                    confidence=0.62,
                )
            )
        self._update_context(message)
        self._update_legacy_fields(message)
        self._update_concepts(message, features)
        self._refresh_dynamic_profile()

    def update_from_feedback(
        self,
        *,
        feedback: str,
        accuracy: float | None = None,
        self_confidence: float | None = None,
        hint_count: int = 0,
    ) -> None:
        self.history.append(feedback)
        features = self._extract_features(feedback)
        if accuracy is not None:
            if accuracy < 0.55:
                features.add(LearningStateCause.PREREQUISITE_GAP.value)
            if hint_count >= 2:
                features.add(LearningStateCause.STRATEGY_GAP.value)
        if accuracy is not None and self_confidence is not None and abs(self_confidence - accuracy) >= 0.28:
            features.add(LearningStateCause.METACOGNITIVE_MISMATCH.value)
        self.profile_evidence.append(
            ProfileEvidence(
                source=ProfileEvidenceSource.STUDENT_FEEDBACK,
                text=feedback,
                features=tuple(sorted(features)),
                weight=0.76 if accuracy is not None else 0.58,
                confidence=0.82 if accuracy is not None else 0.68,
            )
        )
        if accuracy is not None:
            for point in self.weak_points:
                old = self.concept_mastery.get(point, 0.45)
                self.concept_mastery[point] = _clamp(old * 0.72 + accuracy * 0.28)
                trace = self.knowledge_traces.setdefault(point, KnowledgeTrace(concept=point, mastery=old))
                trace.update(correct=accuracy >= 0.68, hinted=hint_count > 0)
                self.concept_mastery[point] = trace.mastery
        self._update_context(feedback)
        self._update_legacy_fields(feedback)
        self._refresh_dynamic_profile()

    def apply_llm_features(self, payload: dict[str, Any], *, source_text: str) -> None:
        if not payload:
            return
        self.target_course = str(payload.get("course") or self.target_course or "机器学习导论")
        major = str(payload.get("major") or "").strip()
        if major:
            self.major = major
            self.major_preference = major
        for goal in payload.get("goals", []) or []:
            goal_text = str(goal).strip()
            if goal_text and goal_text not in self.learning_goals:
                self.learning_goals.append(goal_text)
                
        # 👇 强大的防御装甲：拦截大模型输出的坏数据
        raw_weak_points = payload.get("weak_points", [])
        if isinstance(raw_weak_points, str):
            raw_weak_points = [raw_weak_points]

        for point in raw_weak_points or []:
            point_text = str(point).strip()
            if point_text and point_text not in self.weak_points:
                self.weak_points.append(point_text)
            if point_text:
                self.concept_mastery.setdefault(point_text, 0.44)
                self.knowledge_traces.setdefault(point_text, KnowledgeTrace(concept=point_text, mastery=0.44))
                
        feature_values = {
            str(item).strip()
            for item in (payload.get("learning_state_causes", []) or [])
            if str(item).strip() in {cause.value for cause in LearningStateCause}
        }
        if feature_values:
            self.profile_evidence.append(
                ProfileEvidence(
                    source=ProfileEvidenceSource.PERFORMANCE_SIGNAL,
                    text=f"LLM画像抽取补充: {source_text[:96]}",
                    features=tuple(sorted(feature_values)),
                    weight=0.52,
                    confidence=0.70,
                )
            )
        for preference in payload.get("preferences", []) or []:
            preference_text = str(preference).strip()
            if preference_text and preference_text not in self.interaction_preferences:
                self.interaction_preferences.append(preference_text)
        
        # 👇 接收大模型的语义意图打分
        mastery_updates = payload.get("mastery_updates", {})
        if isinstance(mastery_updates, dict):
            for concept, delta_str in mastery_updates.items():
                concept_text = str(concept).strip()
                try:
                    delta = float(delta_str)
                    current = self.concept_mastery.get(concept_text, 0.48)
                    self.concept_mastery[concept_text] = _clamp(current + delta)
                    
                    self.knowledge_traces.setdefault(
                        concept_text,
                        KnowledgeTrace(concept=concept_text, mastery=self.concept_mastery[concept_text])
                    )
                except (ValueError, TypeError):
                    continue
                    
        self._refresh_dynamic_profile()

    def profile_prompt(self) -> str:
        dimensions = "；".join(
            f"{state.label}={state.status}(score={state.score:.2f}, confidence={state.confidence:.2f})"
            for state in self.dimension_states.values()
        )
        causes = "；".join(
            f"{cause.label}{cause.percentage:.1f}%"
            for cause in sorted(
                self.learning_state_causes.values(),
                key=lambda item: item.percentage,
                reverse=True,
            )
        )
        goals = "、".join(self.learning_goals) or "未显式说明"
        preferences = "、".join(self.interaction_preferences) or self.cognitive_style
        return (
            f"课程={self.target_course}；专业/方向={self.major or self.major_preference}；学习目标={goals}；"
            f"偏好支持={preferences}；薄弱点={','.join(self.weak_points) or '待诊断'}；"
            f"动态维度={dimensions or '待初始化'}；不会原因占比={causes or '待诊断'}"
        )

    def state_report(self) -> str:
        lines = ["学习状态画像:"]
        if self.major or self.learning_goals:
            lines.append(f"- 背景目标: {self.target_course}；{self.major or self.major_preference}；{', '.join(self.learning_goals) or '目标待细化'}")
        for state in self.dimension_states.values():
            fragments = " / ".join(state.evidence_fragments[:2]) or "暂无直接证据"
            lines.append(
                f"- {state.label}: {state.status} "
                f"(score={state.score:.2f}, confidence={state.confidence:.2f}, evidence={state.evidence_count})；证据={fragments}"
            )
        if self.learning_state_causes:
            lines.append("不会原因占比:")
            for cause in sorted(self.learning_state_causes.values(), key=lambda item: item.percentage, reverse=True):
                fragments = " / ".join(cause.evidence_fragments[:2]) or "暂无直接证据"
                lines.append(
                    f"- {cause.label}: {cause.percentage:.1f}% "
                    f"(confidence={cause.confidence:.2f}, evidence={cause.evidence_count})；证据={fragments}"
                )
        return "\n".join(lines)

    def _update_legacy_fields(self, message: str) -> None:
        if any(word in message for word in ("看不懂", "不会", "迷糊", "不理解")):
            self.cognitive_load = min(1.0, self.cognitive_load + 0.12)
            self.focus_level = max(0.15, self.focus_level - 0.08)
        if any(word in message for word in ("代码", "PyTorch", "python", "实操")):
            self.cognitive_style = "代码实操导向"
            if "代码实操" not in self.interaction_preferences:
                self.interaction_preferences.append("代码实操")
        if "图" in message or "演示" in message:
            self.cognitive_style = "视觉演示导向"
            if "图示演示" not in self.interaction_preferences:
                self.interaction_preferences.append("图示演示")
        for point in ("池化层", "卷积核", "反向传播", "链式法则", "梯度下降"):
            if point in message and point not in self.weak_points:
                self.weak_points.append(point)

    def _update_context(self, message: str) -> None:
        major_patterns = (
            (r"(计算机|软件工程|人工智能|数据科学|自动化|数学|物理|金融|医学|教育)[\u4e00-\u9fff]*(专业|方向)?", 0),
        )
        for pattern, group in major_patterns:
            match = re.search(pattern, message)
            if match:
                self.major = match.group(group)
                self.major_preference = self.major
                break
        goal_keywords = {
            "考试": "通过考试",
            "期末": "期末复习",
            "考研": "考研备考",
            "竞赛": "竞赛提升",
            "项目": "项目应用",
            "就业": "就业能力",
            "面试": "面试准备",
            "论文": "科研写作",
        }
        for keyword, goal in goal_keywords.items():
            if keyword in message and goal not in self.learning_goals:
                self.learning_goals.append(goal)
        preference_keywords = {
            "一步步": "分步引导",
            "例子": "具体例子",
            "对比": "对比辨析",
            "反例": "反例辨析",
            "别直接给答案": "提示阶梯",
            "提示": "提示阶梯",
            "视频": "视频脚本",
            "语音": "语音讲解",
        }
        for keyword, preference in preference_keywords.items():
            if keyword in message and preference not in self.interaction_preferences:
                self.interaction_preferences.append(preference)

    def _update_concepts(self, message: str, features: set[str]) -> None:
        # 为了演示倍速，这里的增减分被调高了
        known_points = ("池化层", "最大池化", "平均池化", "卷积核", "反向传播", "链式法则", "梯度下降", "特征图")
        known_points += (
            "机器学习", "监督学习", "数据预处理", "特征工程", "线性回归", "逻辑回归", 
            "决策树", "支持向量机", "朴素贝叶斯", "模型评估", "混淆矩阵", "过拟合", "正则化", "交叉验证"
        )
        for point in known_points:
            if point in message:
                if point not in self.weak_points and any(
                    cause in features
                    for cause in (
                        LearningStateCause.PREREQUISITE_GAP.value,
                        LearningStateCause.MISCONCEPTION.value,
                        LearningStateCause.COGNITIVE_LOAD.value,
                    )
                ):
                    self.weak_points.append(point)
                current = self.concept_mastery.get(point, 0.48)
                if any(word in message for word in ("懂了", "会了", "明白了", "解决了")):
                    self.concept_mastery[point] = _clamp(current + 0.35)
                elif any(word in message for word in ("不会", "看不懂", "不理解", "混", "错")):
                    self.concept_mastery[point] = _clamp(current - 0.25)
                else:
                    self.concept_mastery.setdefault(point, current)
                self.knowledge_traces.setdefault(point, KnowledgeTrace(concept=point, mastery=self.concept_mastery.get(point, current)))
        if LearningStateCause.MISCONCEPTION.value in features:
            pattern = self._detect_misconception_pattern(message)
            self.misconception_patterns[pattern] = _clamp(self.misconception_patterns.get(pattern, 0.0) + 0.22)

    def _extract_features(self, message: str) -> set[str]:
        feature_map: tuple[tuple[str, tuple[str, ...]], ...] = (
            (
                LearningStateCause.PREREQUISITE_GAP.value,
                ("基础", "前置", "定义", "概念", "公式看不懂", "从哪来", "为什么", "不知道", "原理不懂"),
            ),
            (
                LearningStateCause.MISCONCEPTION.value,
                ("总混", "混淆", "分不清", "老是错", "错题", "误区", "最大池化平均池化", "套公式"),
            ),
            (
                LearningStateCause.COGNITIVE_LOAD.value,
                ("题干长", "条件", "漏看", "多步骤", "跳步", "信息太多", "绕", "复杂", "迷糊"),
            ),
            (
                LearningStateCause.STRATEGY_GAP.value,
                ("看答案", "背", "不会复习", "忘了", "记不住", "刷题没用", "不知道怎么学", "只会看视频"),
            ),
            (
                LearningStateCause.METACOGNITIVE_MISMATCH.value,
                ("以为会", "一做就错", "不确定", "不知道哪里不会", "感觉懂", "自评", "没法判断"),
            ),
            (
                LearningStateCause.AFFECTIVE_BARRIER.value,
                ("焦虑", "害怕", "崩", "烦", "挫败", "没信心", "怕", "压力"),
            ),
            (
                LearningStateCause.INTERACTION_MISMATCH.value,
                ("讲太快", "太抽象", "听不进去", "换种讲法", "别直接给答案", "要例子", "要图", "要代码"),
            ),
        )
        features: set[str] = set()
        for feature, keywords in feature_map:
            if any(keyword in message for keyword in keywords):
                features.add(feature)
        if any(word in message for word in ("看不懂", "不会", "不理解")):
            features.add(LearningStateCause.PREREQUISITE_GAP.value)
        if "图" in message or "代码" in message or "一步步" in message:
            features.add(LearningStateCause.INTERACTION_MISMATCH.value)
        return features

    def _detect_misconception_pattern(self, message: str) -> str:
        if "最大池化" in message and "平均池化" in message:
            return "最大池化与平均池化混淆"
        if "卷积" in message and "池化" in message:
            return "卷积运算与池化操作混淆"
        if "公式" in message or "套" in message:
            return "公式套用误区"
        return "未分类误概念"

    def _refresh_dynamic_profile(self) -> None:
        cause_scores = {cause.value: 0.0 for cause in LearningStateCause}
        cause_evidence: dict[str, list[str]] = {cause.value: [] for cause in LearningStateCause}
        cause_confidence: dict[str, list[float]] = {cause.value: [] for cause in LearningStateCause}

        for index, evidence in enumerate(self.profile_evidence):
            recency = 1.0 + min(0.24, index * 0.015)
            for feature in evidence.features:
                if feature in cause_scores:
                    cause_scores[feature] += evidence.weight * evidence.confidence * recency
                    cause_confidence[feature].append(evidence.confidence)
                    if evidence.text not in cause_evidence[feature]:
                        cause_evidence[feature].append(evidence.text[:80])

        if self.cognitive_load > 0.62:
            cause_scores[LearningStateCause.COGNITIVE_LOAD.value] += (self.cognitive_load - 0.55) * 0.8
        if self.focus_level < 0.55:
            cause_scores[LearningStateCause.AFFECTIVE_BARRIER.value] += (0.60 - self.focus_level) * 0.45
        if self.interaction_preferences:
            cause_scores[LearningStateCause.INTERACTION_MISMATCH.value] += 0.12

        active_total = sum(score for score in cause_scores.values() if score > 0.0)
        self.learning_state_causes = {}
        if active_total > 0:
            for key, raw in cause_scores.items():
                if raw <= 0:
                    continue
                confidence_values = cause_confidence[key] or [0.55]
                self.learning_state_causes[key] = CauseBreakdown(
                    key=key,
                    label=CAUSE_LABELS[key],
                    percentage=round(raw / active_total * 100, 1),
                    confidence=round(min(0.95, sum(confidence_values) / len(confidence_values) + min(0.18, raw * 0.05)), 2),
                    evidence_count=len(cause_evidence[key]),
                    evidence_fragments=cause_evidence[key][:4],
                    recommended_interventions=list(CAUSE_INTERVENTIONS[key]),
                )

        avg_mastery = sum(self.concept_mastery.values()) / len(self.concept_mastery) if self.concept_mastery else 0.50
        misconception_strength = sum(self.misconception_patterns.values())
        strategy_gap = self.learning_state_causes.get(LearningStateCause.STRATEGY_GAP.value)
        metacognition_gap = self.learning_state_causes.get(LearningStateCause.METACOGNITIVE_MISMATCH.value)
        affect_gap = self.learning_state_causes.get(LearningStateCause.AFFECTIVE_BARRIER.value)

        dimension_inputs = {
            "knowledge_mastery": (
                avg_mastery,
                "前置概念需补强" if avg_mastery < 0.45 else "基础可支撑下一步学习",
                ["先补前置知识", "用微诊断验证掌握边界"],
            ),
            "misconception_profile": (
                _clamp(1.0 - misconception_strength),
                "存在高频易混点" if misconception_strength >= 0.22 else "未发现稳定误概念",
                ["加入反例辨析题", "对比相似概念的适用条件"],
            ),
            "understanding_fluency_transfer": (
                _clamp(avg_mastery - (misconception_strength * 0.18)),
                "迁移表现待验证" if avg_mastery < 0.62 or misconception_strength else "理解与迁移较稳定",
                ["worked example 后接变式题", "要求学生复述解题触发条件"],
            ),
            "cognitive_processing": (
                _clamp(1.0 - self.cognitive_load),
                "认知负荷偏高" if self.cognitive_load >= 0.62 else "负荷处于可教学区间",
                ["拆分步骤", "使用图示和条件清单"],
            ),
            "learning_strategy": (
                _clamp(1.0 - ((strategy_gap.percentage if strategy_gap else 0.0) / 100)),
                "学习策略需要显式训练" if strategy_gap else "暂未发现明显策略缺口",
                ["检索练习", "错因复盘", "间隔复习"],
            ),
            "metacognition": (
                _clamp(1.0 - ((metacognition_gap.percentage if metacognition_gap else 0.0) / 100)),
                "自我判断需要校准" if metacognition_gap else "自评校准待继续观察",
                ["题前自评", "题后校准", "区分看懂与会做"],
            ),
            "motivation_and_purpose": (
                0.72 if self.learning_goals else 0.54,
                "目标明确" if self.learning_goals else "目标意义仍需澄清",
                ["把知识连接到专业/考试/项目目标", "让学生选择学习路径"],
            ),
            "affect_resilience": (
                _clamp(self.focus_level - ((affect_gap.percentage if affect_gap else 0.0) / 180)),
                "信心或情绪有阻滞迹象" if affect_gap else "情绪风险暂未升高",
                ["小步成功体验", "反馈只指向任务和下一步"],
            ),
            "interaction_preference": (
                0.78 if self.interaction_preferences else 0.56,
                "已捕捉到有效互动偏好" if self.interaction_preferences else "互动偏好待确认",
                ["按偏好切换图示/代码/例子/追问", "让学生确认画像是否准确"],
            ),
            "learning_context": (
                0.72 if self.major or self.learning_goals else 0.48,
                "学习情境已部分明确" if self.major or self.learning_goals else "学习情境信息不足",
                ["追问可用时间、课程要求和评价方式", "按现实时间重排学习计划"],
            ),
        }
        self.dimension_states = {}
        evidence_count = len(self.profile_evidence)
        fragments = [item.text[:80] for item in self.profile_evidence[-3:]]
        for key, (score, status, interventions) in dimension_inputs.items():
            self.dimension_states[key] = DimensionState(
                key=key,
                label=DIMENSION_LABELS[key],
                score=round(score, 2),
                confidence=round(min(0.94, 0.48 + evidence_count * 0.07), 2),
                status=status,
                evidence_count=evidence_count,
                evidence_fragments=fragments,
                recommended_interventions=list(interventions),
                last_updated=_utc_now(),
            )


@dataclass(frozen=True)
class LearningSignal:
    accuracy: float
    dwell_seconds: int
    sandbox_error_rate: float

    @property
    def needs_replan(self) -> bool:
        return self.accuracy < 0.68 or self.sandbox_error_rate > 0.35


@dataclass(frozen=True)
class AgentOutput:
    agent: str
    resource_type: str
    content: str
    citations: tuple[str, ...]
    private_rationale: str = ""


@dataclass(frozen=True)
class AlignmentReport:
    passed: bool
    distance: float
    threshold: float
    conflicts: tuple | list = ()
    advice: str = ""


@dataclass(frozen=True)
class ResourcePackage:
    student_id: str
    target: str
    profile: StudentProfile
    retrieval: RetrievalBundle
    verdicts: tuple[DebateVerdict, ...]
    resources: tuple[AgentOutput, ...]
    alignment: AlignmentReport
    learning_signal: LearningSignal
    strategy_plan: LearningStrategyPlan | None = None