from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "outputs" / "竞品深度分析"
OUTPUT_DIR = ROOT / "outputs" / "M0_阶段0基线与架构契约" / "datasets"

SOURCES = (
    ("智教星", SOURCE_DIR / "01_智教星视频深度分析与EduMatrix对照.md", r"ZJ-\d{3}"),
    ("学枢", SOURCE_DIR / "02_学枢视频深度分析与EduMatrix对照.md", r"XS-\d{3}"),
    ("LearnForge", SOURCE_DIR / "03_LearnForge_PPT深度分析与EduMatrix对照.md", r"LF-F\d{3}"),
)

CAPABILITIES = {
    "CAP-01": "身份、组织与权限",
    "CAP-02": "课程与领域包治理",
    "CAP-03": "来源与许可证治理",
    "CAP-04": "多格式解析与摄入",
    "CAP-05": "检索、引用与知识图谱",
    "CAP-06": "画像与认知诊断",
    "CAP-07": "目标、计划与学习路径",
    "CAP-08": "Agent 编排与任务恢复",
    "CAP-09": "个性化资源生成",
    "CAP-10": "质量门禁与审核发布",
    "CAP-11": "测验、作答与错题诊疗",
    "CAP-12": "实操与交互技能工件",
    "CAP-13": "学习事件、掌握度与反馈",
    "CAP-14": "记忆与上下文治理",
    "CAP-15": "学情分析与报告",
    "CAP-16": "教师工作台与课程运营",
    "CAP-17": "企业岗位标准与培训",
    "CAP-18": "评测、声明与证据工程",
    "CAP-19": "安全、隐私与合规",
    "CAP-20": "可观测性、性能与交付",
}

# Ordered by responsibility specificity. The first highest-scoring capability
# is the unique primary owner; ties follow this order and are flagged.
RULES = (
    ("CAP-19", ("安全", "隐私", "合规", "脱敏", "审计", "越权", "隔离", "删除", "加密", "敏感", "权限拒绝")),
    ("CAP-01", ("登录", "注册", "账号", "角色", "权限", "身份", "组织", "成员", "租户", "SSO", "单点登录")),
    ("CAP-10", ("审核", "审查", "质量门禁", "抽查", "发布", "撤回", "返工", "版本", "校验", "检查器", "审批")),
    ("CAP-18", ("评测", "测试", "基准", "指标", "证据", "追踪矩阵", "声明", "覆盖率", "幻觉率", "准确率", "验收")),
    ("CAP-17", ("企业", "岗位", "培训", "转岗", "胜任", "认证", "证书", "免修", "能力标准", "HR", "LMS")),
    ("CAP-11", ("错题", "习题", "题目", "题库", "测验", "考试", "作答", "评分", "判分", "复习", "闪卡", "练习")),
    ("CAP-12", ("代码", "沙箱", "编程", "实验", "仿真", "交互式", "可执行", "运行代码", "技能工件")),
    ("CAP-06", ("画像", "诊断", "认知", "学习者", "先验", "能力评估", "不会原因", "学习风格")),
    ("CAP-07", ("学习路径", "路径", "计划", "日程", "目标", "进度", "导航", "里程碑", "重规划", "时间表")),
    ("CAP-14", ("记忆", "上下文", "对话历史", "历史会话", "长期记忆", "短期记忆")),
    ("CAP-13", ("学习事件", "事件", "反馈", "掌握", "行为", "打卡", "状态更新", "回流", "遗忘")),
    ("CAP-08", ("Agent", "智能体", "任务队列", "后台任务", "异步", "编排", "调度", "重试", "断点", "恢复", "工作流", "流水线")),
    ("CAP-05", ("知识库", "检索", "搜索", "RAG", "引用", "知识图谱", "图谱", "向量", "证据溯源", "书签")),
    ("CAP-04", ("上传", "导入", "解析", "PDF", "PPT", "PPTX", "DOCX", "OCR", "文件", "文档阅读", "视频转写", "截图提问")),
    ("CAP-03", ("许可证", "许可", "版权", "来源", "署名", "出处", "素材清单", "白名单")),
    ("CAP-15", ("报告", "学情", "分析", "仪表盘", "看板", "可视化", "统计", "雷达", "趋势", "导出报告")),
    ("CAP-16", ("教师", "班级", "课堂", "教研", "教学运营", "课程运营", "备课", "教案", "学生管理")),
    ("CAP-09", ("生成", "讲义", "课件", "导图", "视频", "动画", "资源", "内容生产", "海报", "摘要", "解释")),
    ("CAP-02", ("课程", "教材", "章节", "知识点", "领域", "模板", "学习空间", "工作台", "课程包", "目录")),
    ("CAP-20", ("日志", "监控", "性能", "部署", "缓存", "成本", "Token", "限流", "熔断", "离线", "高可用", "并发", "环境", "一键启动", "E2E")),
)

# Terms observed during the M0 row-by-row review that are not covered by the
# first-pass vocabulary above. Keep these separate so the original taxonomy
# remains readable and future reviews can see why a rule was added.
RULE_AUGMENTS = {
    "CAP-02": (
        "研究课题", "科目", "词库", "资料分类", "课程包", "学习画布",
    ),
    "CAP-04": (
        "链接读取", "网页", "抓取", "图片输入", "拍题", "资料划选", "原文抽取",
        "成绩单抽取", "课表抽取", "大纲抽取",
    ),
    "CAP-05": (
        "相关性门控", "相关结果", "多类型关系", "实体关系", "问选中", "选中原文",
        "来源绑定", "source_refs",
    ),
    "CAP-06": (
        "偏好", "教学风格", "讲解深度", "默认难度", "薄弱点", "知识状态",
        "AI 判断", "能力画像",
    ),
    "CAP-07": (
        "学习规划", "学习安排", "智能推荐", "推荐内容", "下一步建议", "学习提醒",
        "学习时长", "预计时长", "任务完成状态", "待办", "路线", "暂停科目",
    ),
    "CAP-08": (
        "复杂任务", "放弃任务", "取消任务", "意图识别", "操作序列", "窗口控制",
        "自然语言控制", "混合请求", "能力契约", "执行管线", "快答逃生舱",
        "学习伙伴", "AI 助教", "AI 教练",
    ),
    "CAP-09": (
        "知识讲解", "讲解模式", "数字人", "TTS", "播报", "教学图解", "信息图",
        "产物", "学习资料", "精选内容",
    ),
    "CAP-10": (
        "两段式物化", "先草稿", "空壳检查", "假按钮", "占位符", "能力锁定",
        "质量检查", "相关性检查",
    ),
    "CAP-11": (
        "自动判定", "答案是否正确", "解题思路", "计算失误", "错误类型", "难度分布",
        "答案保留", "读题阶段", "编码阶段", "复盘阶段",
    ),
    "CAP-12": (
        "互动形式", "可交互模型", "实时读数", "变量状态", "算法过程", "算法状态",
        "调用/对象关系", "播放控制", "算法推演", "在线编辑器", "运行阶段",
        "运行输出", "语言选择",
    ),
    "CAP-14": (
        "学习笔记", "笔记标题", "笔记正文", "自动带入原文", "所选段落", "答案保留",
    ),
    "CAP-15": (
        "流失风险", "风险预警", "Word 导出", "Markdown 导出", "日期范围筛选",
        "错误类型筛选", "下一步建议",
    ),
    "CAP-16": (
        "讨论比例", "教学互动", "研究课题入口",
    ),
    "CAP-18": (
        "单元测试", "集成测试", "端到端", "E2E", "契约测试", "空壳检查",
    ),
    "CAP-19": (
        "对象级访问控制", "访问控制", "本地保留", "数据保留",
    ),
    "CAP-20": (
        "调用次数", "调用量", "模型服务", "API 地址", "服务 URL", "超时配置",
        "请求超时", "模型档位", "服务状态", "统一模型网关", "模型网关", "多厂商",
        "兼容端点", "OpenAI 兼容", "流式", "备用模型", "稳妥降级", "多模型场景矩阵",
    ),
}

NOT_ADOPT = (
    "Electron", "加密货币", "NFT", "排行榜", "积分", "徽章", "游戏化", "社交",
)
DEFER = (
    "SSO", "单点登录", "多租户", "HR", "LMS", "企业微信", "钉钉", "移动端", "桌面端",
    "社区", "学习市场", "市场搜索", "发布到市场", "证书", "数字人", "语音输入", "TTS",
)
ADJUST = ("Agent", "智能体", "成功率", "排行榜", "积分", "徽章", "游戏化", "Token", "无限", "自动发布", "长期记忆")

# Explicit outcomes from the M0 semantic review. These rows legitimately hit
# multiple domains or use product-specific wording that a generic keyword rule
# cannot resolve reliably. Keeping the decisions by source ID makes the review
# reproducible and prevents later vocabulary changes from silently moving them.
CURATED_PRIMARY = {
    "ZJ-005": "CAP-02", "ZJ-026": "CAP-15", "ZJ-048": "CAP-09",
    "ZJ-056": "CAP-09", "ZJ-058": "CAP-10", "ZJ-062": "CAP-02",
    "ZJ-065": "CAP-08", "ZJ-076": "CAP-10", "ZJ-077": "CAP-04",
    "ZJ-083": "CAP-16", "ZJ-086": "CAP-15", "ZJ-089": "CAP-02",
    "ZJ-093": "CAP-07", "ZJ-106": "CAP-13", "ZJ-109": "CAP-11",
    "ZJ-115": "CAP-06", "ZJ-125": "CAP-15",
    "XS-004": "CAP-06", "XS-015": "CAP-08", "XS-024": "CAP-13",
    "XS-029": "CAP-11", "XS-035": "CAP-13", "XS-040": "CAP-07",
    "XS-042": "CAP-07", "XS-058": "CAP-04", "XS-064": "CAP-06",
    "XS-084": "CAP-07", "XS-086": "CAP-07", "XS-089": "CAP-07",
    "XS-094": "CAP-09", "XS-099": "CAP-12", "XS-105": "CAP-11",
    "XS-110": "CAP-04", "XS-111": "CAP-11", "XS-121": "CAP-09",
    "XS-123": "CAP-11", "XS-138": "CAP-13", "XS-154": "CAP-09",
    "XS-160": "CAP-09", "XS-161": "CAP-10", "XS-164": "CAP-09",
    "LF-F002": "CAP-12", "LF-F008": "CAP-08", "LF-F045": "CAP-05",
    "LF-F056": "CAP-15", "LF-F058": "CAP-15", "LF-F060": "CAP-13",
    "LF-F065": "CAP-09", "LF-F070": "CAP-08", "LF-F073": "CAP-08",
    "LF-F076": "CAP-08", "LF-F086": "CAP-10", "LF-F093": "CAP-04",
    "LF-F097": "CAP-04", "LF-F103": "CAP-20", "LF-F107": "CAP-18",
    "LF-F108": "CAP-18",
}

CURATED_DISPOSITION = {
    "XS-154": "defer", "XS-159": "defer", "XS-161": "defer",
    "XS-164": "defer", "XS-169": "defer",
}


def parse_rows() -> list[dict]:
    rows: list[dict] = []
    for product, path, id_pattern in SOURCES:
        matcher = re.compile(rf"^\|\s*({id_pattern})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|")
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = matcher.match(line)
            if not match:
                continue
            rows.append(
                {
                    "source_id": match.group(1),
                    "product": product,
                    "title": match.group(2).strip(),
                    "description": match.group(3).strip(),
                    "source_file": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "source_line": line_no,
                }
            )
    return rows


def classify(row: dict) -> dict:
    text = f"{row['title']} {row['description']}"
    scored: list[tuple[int, int, str, list[str]]] = []
    for priority, (capability, keywords) in enumerate(RULES):
        keywords = keywords + RULE_AUGMENTS.get(capability, ())
        hits = [keyword for keyword in keywords if keyword.lower() in text.lower()]
        if hits:
            title_hits = sum(keyword.lower() in row["title"].lower() for keyword in hits)
            score = len(hits) * 2 + title_hits * 3
            scored.append((score, -priority, capability, hits))
    scored.sort(reverse=True)

    if scored:
        score, _, primary, hits = scored[0]
        tied = len(scored) > 1 and scored[1][0] == score
        confidence = "high" if score >= 5 and not tied else "medium"
        secondary = [item[2] for item in scored[1:4]]
    else:
        primary, hits, secondary, confidence, tied = "CAP-02", [], [], "low", False

    curated_primary = CURATED_PRIMARY.get(row["source_id"])
    if curated_primary:
        primary = curated_primary
        secondary = [item[2] for item in scored if item[2] != primary][:3]
        confidence = "high"
        tied = False

    if any(keyword.lower() in text.lower() for keyword in NOT_ADOPT):
        disposition = "not_adopt"
        rationale = "与当前交付环境或产品边界冲突"
    elif any(keyword.lower() in text.lower() for keyword in DEFER):
        disposition = "defer"
        rationale = "产品化有价值，但不阻塞比赛黄金旅程"
    elif any(keyword.lower() in text.lower() for keyword in ADJUST):
        disposition = "adjust"
        rationale = "保留价值但按统一对象、责任和证据契约重构"
    else:
        disposition = "adopt"
        rationale = "直接增强比赛闭环、可信度或后续通用底座"

    if row["source_id"] in CURATED_DISPOSITION:
        disposition = CURATED_DISPOSITION[row["source_id"]]
        rationale = "竞品生态能力有产品化价值，但不阻塞比赛黄金旅程"

    return {
        **row,
        "primary_capability": primary,
        "primary_capability_name": CAPABILITIES[primary],
        "secondary_candidates": secondary,
        "disposition": disposition,
        "rationale": rationale,
        "matched_keywords": hits,
        "match_score": score if scored else 0,
        "score_tied": tied,
        "confidence": confidence,
        "needs_human_review": confidence == "low" or tied,
        "review_reason": "no_rule_match" if confidence == "low" else ("top_score_tie" if tied else None),
        "review_method": "curated_m0_semantic_review" if curated_primary else "rule_v0.2",
    }


def write_outputs(rows: list[dict]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = OUTPUT_DIR / "competitor_capability_matrix.jsonl"
    jsonl_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    by_product = Counter(row["product"] for row in rows)
    by_capability = Counter(row["primary_capability"] for row in rows)
    by_disposition = Counter(row["disposition"] for row in rows)
    review_rows = [row for row in rows if row["needs_human_review"]]
    summary = {
        "schema_version": "competitor-matrix-m0-0.2",
        "total": len(rows),
        "unique_source_ids": len({row["source_id"] for row in rows}),
        "by_product": dict(sorted(by_product.items())),
        "by_capability": {
            cap: {"name": CAPABILITIES[cap], "count": by_capability.get(cap, 0)}
            for cap in CAPABILITIES
        },
        "by_disposition": {
            value: by_disposition.get(value, 0)
            for value in ("adopt", "adjust", "defer", "not_adopt")
        },
        "needs_human_review": len(review_rows),
        "review_policy": "Only rows with no rule match or a true top-score tie require manual review.",
        "review_source_ids": [row["source_id"] for row in review_rows],
        "invariants": {
            "expected_total": 412,
            "all_have_one_primary_capability": all(row["primary_capability"] in CAPABILITIES for row in rows),
            "all_have_disposition": all(row["disposition"] in {"adopt", "adjust", "defer", "not_adopt"} for row in rows),
        },
    }
    (OUTPUT_DIR / "competitor_capability_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    matrix_lines = [
        "# 竞品 412 条能力逐项归属与复核",
        "",
        "版本：`competitor-matrix-m0-0.2`  ",
        "口径：每个来源条目保留唯一 `primary_capability` 和唯一处置结论；规则无法稳定判断或真实同分的条目由 M0 语义复核表显式覆盖。",
        "",
        f"总数：{len(rows)}；唯一来源 ID：{len({row['source_id'] for row in rows})}；待人工复核：{len(review_rows)}。",
        "",
        "| ID | 产品 | 标题 | 唯一主能力域 | 处置 | 置信度/方法 | 来源 |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        matrix_lines.append(
            f"| {row['source_id']} | {row['product']} | {row['title']} | "
            f"{row['primary_capability']} {row['primary_capability_name']} | "
            f"{row['disposition']} | {row['confidence']} / {row['review_method']} | "
            f"`{row['source_file']}:{row['source_line']}` |"
        )
    matrix_lines.extend([
        "",
        "## 未决复核",
        "",
        "无。后续若竞品源文档改版，必须重新运行脚本并复核新增或变更 ID。" if not review_rows else
        "以下 ID 尚需团队复核：" + "、".join(row["source_id"] for row in review_rows),
    ])
    (OUTPUT_DIR.parent / "18_竞品412条能力逐项归属与复核.md").write_text(
        "\n".join(matrix_lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    parsed = parse_rows()
    if len(parsed) != 412:
        raise SystemExit(f"Expected 412 source rows, found {len(parsed)}")
    if len({row['source_id'] for row in parsed}) != 412:
        raise SystemExit("Competitor source IDs are not unique")
    classified = [classify(row) for row in parsed]
    write_outputs(classified)
    print(json.dumps({
        "rows": len(classified),
        "review": sum(row["needs_human_review"] for row in classified),
        "capabilities": len({row["primary_capability"] for row in classified}),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
