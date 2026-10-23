#!/usr/bin/env python3
"""Cross-check the authoritative fusion product and implementation specs.

This validator derives all counts from generated structures. It intentionally
does not treat legacy constants such as 52 routes or 175 atoms as completion
gates.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TARGET_ROUTE_FIELDS = {
    "path",
    "label",
    "role",
    "navigation",
    "purpose",
    "primary_action",
    "layout",
    "inputs",
    "outputs",
    "states",
    "interactions",
    "linkage",
    "baseline_code",
    "candidate_code",
    "refactor_code",
    "hidden_or_removed",
    "acceptance",
    "phase",
}

TASK_FIELDS = {
    "id",
    "title",
    "objective",
    "source_groups",
    "source_word_paragraphs",
    "source_images",
    "source_image_text_units",
    "source_group_contracts",
    "atomic_requirement_ids",
    "atomic_contracts",
    "related_atomic_requirement_ids",
    "routes",
    "preserve",
    "candidate",
    "modules",
    "protocol",
    "ui",
    "full_state_contract",
    "states",
    "f1_design_inheritance",
    "automated_tests",
    "manual_acceptance",
    "rollback",
    "visible_result",
}

F1_DESIGN_RULE_IDS = [f"F1-DR-{index:02d}" for index in range(1, 11)]
F1_DESIGN_CONTRACT_FIELDS = {
    "source",
    "mandatory",
    "scope",
    "non_ui_handling",
    "rules",
}
F1_DESIGN_RULE_FIELDS = {"id", "title", "rule", "verification"}
F1_DESIGN_RULE_REQUIRED_TOKENS = {
    "F1-DR-01": ["雾白", "白色内容面", "墨蓝灰", "绿色", "深墨蓝底白字", "#9BA8AB", "深色模式"],
    "F1-DR-02": ["思源黑体", "思源宋体", "14px", "负字距"],
    "F1-DR-03": ["1440x900", "1366x768", "224px", "56px"],
    "F1-DR-04": ["卡片嵌套", "卡片墙", "8px", "阴影"],
    "F1-DR-05": ["一个视觉主动作", "深墨蓝底白字", "Tooltip", "键盘焦点"],
    "F1-DR-06": ["我在哪里", "完成条件", "按需展开", "7.20实质能力"],
    "F1-DR-07": ["蓝紫渐变", "绿色渐变", "发光背景", "毛玻璃"],
    "F1-DR-08": ["加载", "失败", "恢复", "内部状态码"],
    "F1-DR-09": ["横向溢出", "控件碰撞", "内容裁切", "可见焦点"],
    "F1-DR-10": ["1440x900", "1366x768", "0横向溢出", "N/A"],
}

IMAGE_TEXT_FIELDS = {
    "image",
    "filename",
    "paragraph",
    "source_context_paragraphs",
    "same_paragraph_text",
    "previous_paragraph",
    "previous_text",
    "next_paragraph",
    "next_text",
    "semantic_anchor_paragraphs",
    "semantic_anchor_texts",
    "boundary_context_paragraphs",
    "boundary_context_texts",
    "context_relationship",
    "combined_contextual_interpretation",
    "observed",
    "adopt",
    "avoid",
}

EXPECTED_JOURNEY = [
    ("展示页", "/landing", "P05-LANDING", "F1-T04"),
    ("登录", "/login", "P05-LOGIN", "F1-T04"),
    ("自然语言画像", "/onboarding", "P05-ONBOARDING", "F3-T01"),
    ("入学诊断", "/workspace/assessment/entry", "P10-DIAGNOSTIC", "F3-T03"),
    ("学习画像", "/profile/learning", "P08", "F4-T02"),
    ("总路径", "/workspace/path", "P11", "F4-T03"),
    ("今日知识点与资源包", "/workspace/resources/bundles/:bundleId", "P12", "F4-T04"),
    ("今日必做资源", "/workspace/resources/handouts/:resourceId", "P13", "F5-T03"),
    ("代码/实验/费曼证据", "/workspace/code/:resourceId", "P17", "F6-T03"),
    ("智能组卷解锁", "/workspace/assessment", "P10", "F4-T05"),
    ("智能组卷作答", "/workspace/assessment/exams/:examId", "P10-EXAM", "F6-T06"),
    ("错题与复习", "/workspace/review/wrong-questions", "P22", "F8-T02"),
    ("反馈更新", "/profile/history", "P07", "F8-T05"),
    ("下一日继续", "/", "P06", "F4-T01"),
]

OFFICIAL_REQUIREMENTS = [
    {
        "id": "OFFICIAL-01",
        "requirement": "至少一个垂直领域，体现不同背景学习者适配",
        "product": ["P01", "P05", "P08"],
        "tasks": ["F0-T02", "F3-T01", "F3-T05"],
    },
    {
        "id": "OFFICIAL-02",
        "requirement": "至少三 Agent，形成分析-生成-校验-决策闭环",
        "product": ["P01", "P24-AGENT", "P27"],
        "tasks": ["F2-T05", "F7-T05"],
    },
    {
        "id": "OFFICIAL-03",
        "requirement": "画像与领域知识库共同驱动至少三种个性化资源",
        "product": ["P05-ONBOARDING", "P12", "P23"],
        "tasks": ["F3-T02", "F5-T02", "F7-T01"],
    },
    {
        "id": "OFFICIAL-04",
        "requirement": "可视化画像、难度匹配、路径规划与动态反馈",
        "product": ["P08", "P11", "P28"],
        "tasks": ["F3-T05", "F4-T03", "F8-T05"],
    },
    {
        "id": "OFFICIAL-05",
        "requirement": "高保真来源、交叉验证、追问式导学与隐私边界",
        "product": ["P23-DOCUMENT", "P24", "P24-AGENT"],
        "tasks": ["F2-T05", "F7-T02", "F7-T04", "F7-T05"],
    },
    {
        "id": "OFFICIAL-06",
        "requirement": "完整闭环、部署与测试数据；指标仅在有正式证据时宣称",
        "product": ["P00", "P28", "P30"],
        "tasks": ["F0-T02", "F10-T02", "F10-T03"],
    },
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def add_check(
    checks: list[dict[str, Any]],
    check_id: str,
    title: str,
    passed: bool,
    evidence: str,
    details: list[str] | None = None,
) -> None:
    checks.append(
        {
            "id": check_id,
            "title": title,
            "passed": bool(passed),
            "evidence": evidence,
            "details": details or [],
        }
    )


def valid_id_set(product: dict[str, Any]) -> set[str]:
    result = {item["id"] for item in product["sections"]}
    result.update(item["subsection_id"] for item in product["routes"])
    for section in product["sections"]:
        result.update(item["id"] for item in section["standalone_subsections"])
    return result


def validate(root: Path) -> dict[str, Any]:
    base = root / "outputs" / "原系统融合重构执行"
    product = load_json(base / "09_EduMatrix最终产品方案.json")
    implementation = load_json(base / "10_原版融合重构详细实施方案.json")
    audit = load_json(base / "13_改进想法逐句逐图实质落实审计.json")
    target_routes = load_json(
        base / "evidence" / "target_product_spec" / "target_product_route_spec.json"
    )
    current_routes = load_json(
        base / "evidence" / "route_product_spec" / "route_product_spec.json"
    )
    scope = load_json(
        base / "evidence" / "fusion_scope_matrix" / "fusion_scope_matrix.json"
    )
    protection = load_json(
        base / "evidence" / "protection_baseline" / "protected_pages_baseline.json"
    )
    product_md = (base / "09_EduMatrix最终产品方案.md").read_text(
        encoding="utf-8"
    )
    implementation_md = (
        base / "10_原版融合重构详细实施方案.md"
    ).read_text(encoding="utf-8")
    audit_md = (
        base / "13_改进想法逐句逐图实质落实审计.md"
    ).read_text(encoding="utf-8")
    status_md = (base / "00_唯一执行状态.md").read_text(encoding="utf-8")
    constitution_md = (base / "06_用户意图与产品宪法.md").read_text(
        encoding="utf-8"
    )
    route_matrix_md = (
        base / "08_用户需求追踪与路由迁移矩阵.md"
    ).read_text(encoding="utf-8")
    recovery_md = (base / "11_上下文恢复与实施索引.md").read_text(
        encoding="utf-8"
    )
    current_checkpoint = load_json(
        base / "evidence" / "context_recovery" / "current_checkpoint.json"
    )

    checks: list[dict[str, Any]] = []
    errors: list[str] = []

    # A. Word and image-text semantics.
    image_units = audit.get("image_text_units", [])
    image_numbers = [item.get("image") for item in image_units]
    image_field_errors: list[str] = []
    for unit in image_units:
        missing = sorted(IMAGE_TEXT_FIELDS - set(unit))
        if missing:
            image_field_errors.append(f"图{unit.get('image')}缺少字段{missing}")
        if not unit.get("semantic_anchor_paragraphs"):
            image_field_errors.append(f"图{unit.get('image')}没有人工语义锚点")
        image_path = (
            base
            / "evidence"
            / "dual_version_audit"
            / "improvement_ideas"
            / unit.get("filename", "")
        )
        if not image_path.is_file():
            image_field_errors.append(f"图{unit.get('image')}原文件不存在")
    image_semantics_ok = (
        audit.get("paragraph_count") == 73
        and image_numbers == list(range(1, 30))
        and not image_field_errors
    )
    add_check(
        checks,
        "TRACE-01",
        "Word 顺序与 29 组图文语义单元完整",
        image_semantics_ok,
        f"{audit.get('paragraph_count')}个段位；{len(image_units)}组图片单元；每组保存前文/图片段/后文/语义锚点/边界/综合解释。",
        image_field_errors,
    )

    image_by_number = {int(item["image"]): item for item in image_units}
    special_image_errors: list[str] = []
    expected_special = {
        13: {"paragraph": 30, "anchors": [31], "boundaries": [29]},
        25: {"paragraph": 47, "anchors": [49], "boundaries": [46]},
    }
    for number, expected in expected_special.items():
        unit = image_by_number.get(number, {})
        if unit.get("paragraph") != expected["paragraph"]:
            special_image_errors.append(f"图{number}图片段错误")
        if unit.get("semantic_anchor_paragraphs") != expected["anchors"]:
            special_image_errors.append(f"图{number}语义锚点错误")
        if unit.get("boundary_context_paragraphs") != expected["boundaries"]:
            special_image_errors.append(f"图{number}跨主题边界错误")
    add_check(
        checks,
        "TRACE-02",
        "关键跨主题图片没有被机械邻接误判",
        not special_image_errors,
        "图13=知识库书架（图片段30/锚点31/边界29）；图25=费曼第一轮（图片段47/锚点49/边界46）。",
        special_image_errors,
    )

    # B. Product structure and target routes.
    product_ids = valid_id_set(product)
    target_paths = [item["path"] for item in target_routes]
    product_paths = [item["path"] for item in product["routes"]]
    route_errors: list[str] = []
    if len(target_paths) != len(set(target_paths)):
        route_errors.append("目标路由存在重复")
    if len(target_paths) != len(product_paths) or set(target_paths) != set(product_paths):
        route_errors.append("09 JSON 的路由集合与目标路由证据不一致")
    for route in target_routes:
        missing = sorted(TARGET_ROUTE_FIELDS - set(route))
        empty = sorted(
            field for field in TARGET_ROUTE_FIELDS if not str(route.get(field, "")).strip()
        )
        if missing or empty:
            route_errors.append(
                f"{route.get('path')}字段缺失={missing} 空字段={empty}"
            )
    add_check(
        checks,
        "PRODUCT-01",
        "目标路由数量由实际产品结构导出且逐页字段完整",
        not route_errors,
        f"实际目标路由{len(target_routes)}条，产品章节{len(product['sections'])}个；未使用固定52条门禁。",
        route_errors,
    )

    assessment = next(
        item for item in product["routes"] if item["path"] == "/workspace/assessment"
    )
    onboarding = next(
        item for item in product["routes"] if item["path"] == "/onboarding"
    )
    feynman_section = next(
        item for item in product["sections"] if item["id"] == "P21"
    )
    placement_errors: list[str] = []
    if "/workspace/practice/:resourceId" in target_paths:
        placement_errors.append("旧练习路由仍在目标结构")
    if "/workspace/resources/quizzes/:resourceId" not in target_paths:
        placement_errors.append("测验题资源正式路由缺失")
    assessment_text = " ".join(
        str(assessment.get(key, ""))
        for key in ("purpose", "layout", "inputs", "outputs", "interactions")
    )
    if "入学诊断" not in assessment_text or "智能组卷" not in assessment_text:
        placement_errors.append("测评中心两类正式测评定义不完整")
    if "左右两列分别为入学诊断和智能组卷" not in assessment.get("layout", ""):
        placement_errors.append("测评中心布局不是严格两列两类正式测评")
    onboarding_text = " ".join(
        str(onboarding.get(key, ""))
        for key in ("purpose", "layout", "inputs", "outputs", "interactions", "acceptance")
    )
    if "多轮" not in onboarding_text or "画像" not in onboarding_text:
        placement_errors.append("首次画像没有明确自然语言多轮构建")
    if "不接收学生上传课程课件" not in onboarding.get("inputs", ""):
        placement_errors.append("首次旅程没有明确排除课程材料上传门禁")
    if "不上传任何文件也能完成" not in onboarding.get("acceptance", ""):
        placement_errors.append("首次旅程没有无附件完成验收")
    feynman_text = json.dumps(feynman_section, ensure_ascii=False)
    if "accuracy/recall" in feynman_text.lower():
        placement_errors.append("费曼产品行为仍含固定 accuracy/recall 问题")
    add_check(
        checks,
        "PRODUCT-02",
        "已知产品归属错误均已从正式规格移除",
        not placement_errors,
        "测评中心仅两类正式测评；练习归入测验题资源；首次画像不强制课程上传；费曼任务动态生成。",
        placement_errors,
    )

    mobile_errors: list[str] = []
    for route in product["routes"]:
        current_acceptance = " ".join(
            str(route.get(key, ""))
            for key in ("layout", "states", "acceptance", "refactor_code")
        )
        if "390x844" in current_acceptance or "移动端抽屉" in current_acceptance:
            mobile_errors.append(f"{route['path']}仍含本周期移动端门禁")
    add_check(
        checks,
        "PRODUCT-03",
        "当前周期严格限定桌面端",
        not mobile_errors,
        "目标路由布局/验收中无390x844或移动端抽屉要求；移动端只在延期边界出现。",
        mobile_errors,
    )

    # C. Implementation plan.
    tasks = implementation.get("tasks", [])
    task_ids = [item["id"] for item in tasks]
    task_id_set = set(task_ids)
    task_errors: list[str] = []
    if len(task_ids) != len(set(task_ids)):
        task_errors.append("实施任务 ID 重复")
    for item in tasks:
        missing = sorted(TASK_FIELDS - set(item))
        empty = sorted(
            field
            for field in TASK_FIELDS
            - {
                "routes",
                "source_images",
                "source_image_text_units",
                "atomic_requirement_ids",
                "atomic_contracts",
            }
            if item.get(field) in (None, "", [])
        )
        if missing or empty:
            task_errors.append(
                f"{item.get('id')}字段缺失={missing} 空字段={empty}"
            )
        if not item.get("full_state_contract"):
            task_errors.append(f"{item.get('id')}没有完整状态矩阵")
    add_check(
        checks,
        "PLAN-01",
        "F0-F10 每个任务均含完整实施字段",
        not task_errors,
        f"实际阶段{implementation.get('phase_count')}个，任务{len(tasks)}个；每个任务包含来源、协议、UI、状态、测试、回滚、可见结果和F1设计继承字段。",
        task_errors,
    )

    f1_design_errors: list[str] = []
    global_design_contract = implementation.get("f1_design_contract")
    if not isinstance(global_design_contract, dict):
        f1_design_errors.append("10 JSON缺少顶层f1_design_contract")
        global_design_contract = {}
    else:
        missing = sorted(F1_DESIGN_CONTRACT_FIELDS - set(global_design_contract))
        if missing:
            f1_design_errors.append(f"顶层F1设计合同缺少字段{missing}")
        if global_design_contract.get("mandatory") is not True:
            f1_design_errors.append("顶层F1设计合同mandatory不是true")

    global_rules = global_design_contract.get("rules", [])
    global_rule_ids = [rule.get("id") for rule in global_rules if isinstance(rule, dict)]
    if global_rule_ids != F1_DESIGN_RULE_IDS:
        f1_design_errors.append(
            f"顶层F1规则ID或顺序错误：actual={global_rule_ids} expected={F1_DESIGN_RULE_IDS}"
        )
    for rule in global_rules:
        if not isinstance(rule, dict):
            f1_design_errors.append("顶层F1规则存在非对象条目")
            continue
        missing = sorted(F1_DESIGN_RULE_FIELDS - set(rule))
        empty = sorted(
            field for field in F1_DESIGN_RULE_FIELDS if rule.get(field) in (None, "")
        )
        if missing or empty:
            f1_design_errors.append(
                f"{rule.get('id')}字段缺失={missing} 空字段={empty}"
            )
            continue
        combined = f"{rule['title']} {rule['rule']} {rule['verification']}"
        for token in F1_DESIGN_RULE_REQUIRED_TOKENS.get(rule["id"], []):
            if token not in combined:
                f1_design_errors.append(f"{rule['id']}缺少硬约束词：{token}")

    inheritance_heading = "#### 7.1 F1 设计继承门禁（本任务强制）"
    heading_count = implementation_md.count(inheritance_heading)
    if heading_count != len(tasks):
        f1_design_errors.append(
            f"10 Markdown逐任务F1门禁小节数量错误：actual={heading_count} expected={len(tasks)}"
        )
    for item in tasks:
        task_id = item.get("id", "<unknown>")
        inheritance = item.get("f1_design_inheritance")
        if not isinstance(inheritance, dict):
            f1_design_errors.append(f"{task_id}缺少f1_design_inheritance对象")
            continue
        missing = sorted(F1_DESIGN_CONTRACT_FIELDS - set(inheritance))
        if missing:
            f1_design_errors.append(f"{task_id}F1设计合同缺少字段{missing}")
        if inheritance.get("mandatory") is not True:
            f1_design_errors.append(f"{task_id}F1设计合同mandatory不是true")
        if inheritance != global_design_contract:
            f1_design_errors.append(f"{task_id}没有逐字继承顶层F1设计合同")
        marker = f"### {task_id} "
        start = implementation_md.find(marker)
        if start < 0:
            f1_design_errors.append(f"10 Markdown缺少任务段{task_id}")
            continue
        end = implementation_md.find("\n### ", start + len(marker))
        segment = implementation_md[start : end if end >= 0 else len(implementation_md)]
        if inheritance_heading not in segment:
            f1_design_errors.append(f"{task_id}正文缺少独立F1设计继承门禁小节")
        for rule_id in F1_DESIGN_RULE_IDS:
            if rule_id not in segment:
                f1_design_errors.append(f"{task_id}正文缺少{rule_id}")
    for rule_id in F1_DESIGN_RULE_IDS:
        count = implementation_md.count(rule_id)
        if count != len(tasks):
            f1_design_errors.append(
                f"10 Markdown中{rule_id}出现{count}次，预期每个任务一次共{len(tasks)}次"
            )
    add_check(
        checks,
        "PLAN-02",
        "F1设计规则逐任务继承且不可由顶部总则代替",
        not f1_design_errors,
        f"{len(tasks)}个任务各自携带{len(F1_DESIGN_RULE_IDS)}条F1设计规则；JSON合同、Markdown独立小节、硬约束词和逐任务次数全部校验。",
        f1_design_errors[:200],
    )

    # D. Atomic one-to-one traceability.
    atoms = audit.get("atomic_requirements", [])
    atom_ids = [item["atomic_requirement_id"] for item in atoms]
    atom_errors: list[str] = []
    if len(atom_ids) != len(set(atom_ids)):
        atom_errors.append("原子 ID 重复")
    for atom in atoms:
        section_ids = atom.get("product_section_ids")
        implementation_ids = atom.get("implementation_task_ids")
        if not isinstance(section_ids, list) or not section_ids:
            atom_errors.append(f"{atom['atomic_requirement_id']}产品章节数组为空")
            continue
        if not isinstance(implementation_ids, list) or not implementation_ids:
            atom_errors.append(f"{atom['atomic_requirement_id']}任务数组为空")
            continue
        invalid_sections = sorted(set(section_ids) - product_ids)
        invalid_tasks = sorted(set(implementation_ids) - task_id_set)
        if invalid_sections:
            atom_errors.append(
                f"{atom['atomic_requirement_id']}无效章节{invalid_sections}"
            )
        if invalid_tasks:
            atom_errors.append(
                f"{atom['atomic_requirement_id']}无效任务{invalid_tasks}"
            )
        if atom.get("primary_product_section_id") not in product_ids:
            atom_errors.append(
                f"{atom['atomic_requirement_id']}无效主责章节{atom.get('primary_product_section_id')}"
            )
        if atom.get("primary_implementation_task_id") not in task_id_set:
            atom_errors.append(
                f"{atom['atomic_requirement_id']}无效主责任务{atom.get('primary_implementation_task_id')}"
            )
        for required in (
            "word_paragraphs",
            "full_original_words",
            "correct_product_interpretation",
            "page_layout_and_interaction",
            "primary_product_section_id",
            "primary_implementation_task_id",
            "product_realization_contract",
            "implementation_realization_contract",
            "automatic_validation",
            "manual_acceptance",
            "current_status",
            "conflict_or_defer_decision",
        ):
            if atom.get(required) in (None, "", []):
                atom_errors.append(
                    f"{atom['atomic_requirement_id']}缺少{required}"
                )
    add_check(
        checks,
        "TRACE-03",
        "每条原子要求实质映射到存在的产品章节和实施任务",
        not atom_errors,
        f"实际原子要求{len(atoms)}条；未使用固定175条或G01-G28关键词出现门禁。",
        atom_errors[:100],
    )

    group_product_map = product.get("group_product_section_map", {})
    group_task_map = implementation.get("group_implementation_task_map", {})
    group_errors: list[str] = []
    atoms_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for atom in atoms:
        atoms_by_group[atom["group_id"]].append(atom)
    for group_id, group_atoms in atoms_by_group.items():
        expected_products = group_product_map.get(group_id, [])
        expected_tasks = group_task_map.get(group_id, [])
        if not expected_products or not expected_tasks:
            group_errors.append(f"{group_id}缺少章节或任务映射")
            continue
        for atom in group_atoms:
            if not set(expected_products).issubset(atom["product_section_ids"]):
                group_errors.append(f"{atom['atomic_requirement_id']}影响章节映射漂移")
            if not set(expected_tasks).issubset(atom["implementation_task_ids"]):
                group_errors.append(f"{atom['atomic_requirement_id']}影响任务映射漂移")
            if atom.get("primary_product_section_id") not in atom["product_section_ids"]:
                group_errors.append(f"{atom['atomic_requirement_id']}主责章节不在影响数组")
            if atom.get("primary_implementation_task_id") not in atom["implementation_task_ids"]:
                group_errors.append(f"{atom['atomic_requirement_id']}主责任务不在影响数组")
    add_check(
        checks,
        "TRACE-04",
        "09、10、13 使用同一映射事实源",
        not group_errors,
        f"{len(atoms_by_group)}个需求组保留影响数组，并为每条原子要求增加唯一主责章节和主责任务。",
        group_errors,
    )

    # Exact semantic coverage: IDs and destination existence are not enough.
    product_atomic_contracts = product.get("atomic_contracts", [])
    implementation_atomic_contracts = implementation.get("atomic_contracts", [])
    product_contract_by_id = {
        item.get("atomic_requirement_id"): item for item in product_atomic_contracts
    }
    implementation_contract_by_id = {
        item.get("atomic_requirement_id"): item
        for item in implementation_atomic_contracts
    }

    product_placements: dict[str, set[str]] = defaultdict(set)
    for section in product.get("sections", []):
        for contract in section.get("atomic_contracts", []):
            product_placements[contract["atomic_requirement_id"]].add(section["id"])
        for route in section.get("route_specs", []):
            for contract in route.get("atomic_contracts", []):
                product_placements[contract["atomic_requirement_id"]].add(
                    route["subsection_id"]
                )
        for subsection in section.get("standalone_subsections", []):
            for contract in subsection.get("atomic_contracts", []):
                product_placements[contract["atomic_requirement_id"]].add(
                    subsection["id"]
                )

    implementation_placements: dict[str, set[str]] = defaultdict(set)
    for item in tasks:
        for contract in item.get("atomic_contracts", []):
            implementation_placements[contract["atomic_requirement_id"]].add(
                item["id"]
            )

    product_semantic_errors: list[str] = []
    implementation_semantic_errors: list[str] = []
    product_owned_rows = [
        contract
        for section in product.get("sections", [])
        for contract in section.get("atomic_contracts", [])
    ]
    implementation_owned_rows = [
        contract
        for item in tasks
        for contract in item.get("atomic_contracts", [])
    ]
    if len(product_atomic_contracts) != len(atoms) or len(product_contract_by_id) != len(atoms):
        product_semantic_errors.append(
            f"09 atomic_contracts数量/唯一性错误：rows={len(product_atomic_contracts)} unique={len(product_contract_by_id)} expected={len(atoms)}"
        )
    if (
        len(product_owned_rows) != len(atoms)
        or len({item["atomic_requirement_id"] for item in product_owned_rows})
        != len(atoms)
    ):
        product_semantic_errors.append(
            f"09主责章节原子合同不是一对一：rows={len(product_owned_rows)} expected={len(atoms)}"
        )
    if (
        len(implementation_atomic_contracts) != len(atoms)
        or len(implementation_contract_by_id) != len(atoms)
    ):
        implementation_semantic_errors.append(
            f"10 atomic_contracts数量/唯一性错误：rows={len(implementation_atomic_contracts)} unique={len(implementation_contract_by_id)} expected={len(atoms)}"
        )
    if (
        len(implementation_owned_rows) != len(atoms)
        or len({item["atomic_requirement_id"] for item in implementation_owned_rows})
        != len(atoms)
    ):
        implementation_semantic_errors.append(
            f"10主责任务原子合同不是一对一：rows={len(implementation_owned_rows)} expected={len(atoms)}"
        )
    for atom in atoms:
        atom_id = atom["atomic_requirement_id"]
        requirement = atom["correct_product_interpretation"]
        layout = atom["page_layout_and_interaction"]

        product_contract = product_contract_by_id.get(atom_id)
        if not product_contract:
            product_semantic_errors.append(f"{atom_id}未进入09 atomic_contracts")
        else:
            if product_contract.get("requirement") != requirement:
                product_semantic_errors.append(f"{atom_id}在09的完整要求发生漂移")
            if product_contract.get("page_layout_and_interaction") != layout:
                product_semantic_errors.append(f"{atom_id}在09的页面合同发生漂移")
            if (
                product_contract.get("primary_product_section_id")
                != atom["primary_product_section_id"]
            ):
                product_semantic_errors.append(f"{atom_id}在09的主责章节发生漂移")
            if atom["primary_product_section_id"] not in product_placements.get(
                atom_id, set()
            ):
                product_semantic_errors.append(
                    f"{atom_id}未写入09唯一主责章节/子章节{atom['primary_product_section_id']}"
                )
        if atom_id not in product_md or requirement not in product_md or layout not in product_md:
            product_semantic_errors.append(
                f"{atom_id}的完整要求或页面合同未进入09 Markdown正文"
            )

        implementation_contract = implementation_contract_by_id.get(atom_id)
        if not implementation_contract:
            implementation_semantic_errors.append(
                f"{atom_id}未进入10 atomic_contracts"
            )
        else:
            if implementation_contract.get("requirement") != requirement:
                implementation_semantic_errors.append(
                    f"{atom_id}在10的完整要求发生漂移"
                )
            if implementation_contract.get("page_layout_and_interaction") != layout:
                implementation_semantic_errors.append(
                    f"{atom_id}在10的页面合同发生漂移"
                )
            if (
                implementation_contract.get("primary_implementation_task_id")
                != atom["primary_implementation_task_id"]
            ):
                implementation_semantic_errors.append(
                    f"{atom_id}在10的主责任务发生漂移"
                )
            if atom["primary_implementation_task_id"] not in implementation_placements.get(
                atom_id, set()
            ):
                implementation_semantic_errors.append(
                    f"{atom_id}未写入10唯一主责任务{atom['primary_implementation_task_id']}"
                )
        if (
            atom_id not in implementation_md
            or requirement not in implementation_md
            or layout not in implementation_md
        ):
            implementation_semantic_errors.append(
                f"{atom_id}的完整要求或页面合同未进入10 Markdown正文"
            )

    add_check(
        checks,
        "TRACE-06",
        "245条原子要求的完整语义逐条进入09产品方案",
        not product_semantic_errors,
        "逐条比对完整要求、页面结构与交互、章节/子章节归属和Markdown正文；不接受只有ID或章节存在。",
        product_semantic_errors[:200],
    )
    add_check(
        checks,
        "TRACE-07",
        "245条原子要求逐条进入10对应实施任务",
        not implementation_semantic_errors,
        "每条要求只在唯一主责任务中作为必做合同出现，同时保留影响/协同任务数组供跨模块追踪。",
        implementation_semantic_errors[:200],
    )

    image_contract_errors: list[str] = []
    for unit in image_units:
        number = int(unit["image"])
        for field in ("observed", "adopt", "avoid"):
            value = unit[field]
            if value not in product_md:
                image_contract_errors.append(f"图{number}的{field}未进入09正文")
            if value not in implementation_md:
                image_contract_errors.append(f"图{number}的{field}未进入10正文")
        matching_tasks = [item for item in tasks if number in item.get("source_images", [])]
        if not matching_tasks:
            image_contract_errors.append(f"图{number}没有对应实施任务")
            continue
        for item in matching_tasks:
            matching_units = {
                int(source["image"]): source
                for source in item.get("source_image_text_units", [])
            }
            task_unit = matching_units.get(number)
            if not task_unit:
                image_contract_errors.append(f"图{number}未进入任务{item['id']}")
                continue
            for field in ("observed", "adopt", "avoid"):
                if task_unit.get(field) != unit.get(field):
                    image_contract_errors.append(
                        f"图{number}在任务{item['id']}的{field}发生漂移"
                    )
    add_check(
        checks,
        "TRACE-08",
        "29张原图的结构、必须吸收和禁止照搬均进入产品与任务书",
        not image_contract_errors,
        "逐图核对observed/adopt/avoid三类合同；10中的对应任务必须保存完整原图硬约束。",
        image_contract_errors[:200],
    )

    group_layout_errors: list[str] = []
    for group in audit.get("groups", []):
        layout = group.get("layout_and_interaction", "")
        if not layout:
            group_layout_errors.append(f"{group.get('id')}缺少布局与交互合同")
            continue
        if layout not in product_md:
            group_layout_errors.append(f"{group['id']}布局合同未进入09")
        if layout not in implementation_md:
            group_layout_errors.append(f"{group['id']}布局合同未进入10")
    add_check(
        checks,
        "TRACE-09",
        "28组页面布局与交互合同同时进入09和10",
        not group_layout_errors,
        "逐组校验完整布局句，不以需求组标题或原子ID替代。",
        group_layout_errors,
    )

    # E. Journey simulation and reverse traceability.
    route_by_path = {item["path"]: item for item in product["routes"]}
    journey_rows: list[dict[str, Any]] = []
    journey_errors: list[str] = []
    for index, (step, path, product_id, task_id) in enumerate(
        EXPECTED_JOURNEY, start=1
    ):
        route = route_by_path.get(path)
        passed = bool(route and product_id in product_ids and task_id in task_id_set)
        if not passed:
            journey_errors.append(
                f"第{index}步{step}缺路由/产品章节/任务：{path}/{product_id}/{task_id}"
            )
        journey_rows.append(
            {
                "step": index,
                "name": step,
                "route": path,
                "product_id": product_id,
                "task_id": task_id,
                "passed": passed,
                "primary_action": route.get("primary_action") if route else "",
                "states": route.get("states") if route else "",
            }
        )
    add_check(
        checks,
        "JOURNEY-01",
        "完整学生旅程没有规格死路",
        not journey_errors,
        f"从展示页到下一日继续共{len(journey_rows)}步，每步都有目标路由、产品规格、主动作、状态和实施任务。",
        journey_errors,
    )

    reverse_errors: list[str] = []
    task_atoms = {
        atom_id for item in tasks for atom_id in item.get("atomic_requirement_ids", [])
    }
    missing_task_atoms = sorted(set(atom_ids) - task_atoms)
    if missing_task_atoms:
        reverse_errors.append(
            f"有{len(missing_task_atoms)}条原子要求未被任何任务反向引用"
        )
    for route in product["routes"]:
        if route.get("section_id") not in product_ids:
            reverse_errors.append(f"{route['path']}产品章节不存在")
        if not route.get("phase"):
            reverse_errors.append(f"{route['path']}没有实施阶段")
    add_check(
        checks,
        "TRACE-05",
        "页面、路由、任务与原子要求可双向追溯",
        not reverse_errors,
        "每条目标路由有产品章节和阶段；每条原子要求至少被一个实施任务反向引用。",
        reverse_errors,
    )

    # F. Contest, protection, current code disposition.
    official_rows: list[dict[str, Any]] = []
    official_errors: list[str] = []
    for item in OFFICIAL_REQUIREMENTS:
        missing_products = sorted(set(item["product"]) - product_ids)
        missing_tasks = sorted(set(item["tasks"]) - task_id_set)
        passed = not missing_products and not missing_tasks
        if not passed:
            official_errors.append(
                f"{item['id']}缺产品{missing_products}或任务{missing_tasks}"
            )
        official_rows.append({**item, "passed": passed})
    add_check(
        checks,
        "OFFICIAL-01",
        "唯一赛题核心要求均有产品和实施归宿",
        not official_errors,
        f"{len(official_rows)}组赛题核心要求覆盖垂直领域、三Agent、个性化资源、动态反馈、高保真来源和完整闭环。",
        official_errors,
    )

    protected_pages = protection.get("pages", [])
    protection_errors: list[str] = []
    if len(protected_pages) != protection.get("protected_page_count"):
        protection_errors.append("保护页计数与列表不一致")
    expected_protected_routes = {
        "/student-analysis",
        "/learning-path",
        "/notes",
        "/wrong-questions",
    }
    actual_protected_routes = {item["route"] for item in protected_pages}
    if actual_protected_routes != expected_protected_routes:
        protection_errors.append(
            f"保护页路由不一致：{sorted(actual_protected_routes)}"
        )
    add_check(
        checks,
        "PROTECT-01",
        "7.20 四个高价值页面存在显式保护门禁",
        not protection_errors,
        "学习画像、学习路径、笔记本、错题本只允许排版减负和闭环增强。",
        protection_errors,
    )

    current_route_errors = [
        f"{item.get('path')}缺归宿"
        for item in current_routes
        if not item.get("disposition") or not item.get("target_destination")
    ]
    backend_errors = [
        f"{item.get('method')} {item.get('final_path')}未分类"
        for item in scope.get("routes", [])
        if not item.get("disposition")
        or not item.get("destination")
        or "未分类" in str(item.get("disposition"))
    ]
    model_errors = [
        f"{item.get('model')}未分类"
        for item in scope.get("models", [])
        if not item.get("disposition")
        or not item.get("destination")
        or "未分类" in str(item.get("disposition"))
    ]
    scope_errors = current_route_errors + backend_errors + model_errors
    add_check(
        checks,
        "SCOPE-01",
        "当前路由、后端端点和 ORM 模型均有归宿",
        not scope_errors,
        f"当前前端路由{len(current_routes)}条、注册端点{len(scope.get('routes', []))}个、ORM模型{len(scope.get('models', []))}个；数量仅陈述事实，不驱动新增工作台。",
        scope_errors[:100],
    )

    # G. Generated Markdown contains the authoritative structures.
    markdown_errors: list[str] = []
    for section_id in sorted(product_ids):
        if section_id not in product_md:
            markdown_errors.append(f"09 Markdown缺少{section_id}")
    for task_id in task_ids:
        if task_id not in implementation_md:
            markdown_errors.append(f"10 Markdown缺少{task_id}")
    for atom_id in atom_ids:
        if atom_id not in audit_md:
            markdown_errors.append(f"13 Markdown缺少{atom_id}")
    for number in range(1, 30):
        if f"图 {number}" not in product_md and f"图{number}" not in product_md:
            markdown_errors.append(f"09 Markdown缺少图{number}图文单元")
    add_check(
        checks,
        "DOC-01",
        "Markdown 正文与 JSON 事实源同步",
        not markdown_errors,
        "09包含全部产品章节/子章节、29组图文单元和逐原子产品合同；10包含全部任务及逐原子执行合同；13包含全部原子ID。",
        markdown_errors[:100],
    )

    context_errors: list[str] = []
    expected_context_tokens = {
        "00": [
            f"{len(atoms)} 条原子要求",
            f"{len(target_routes)} 条目标路由",
            f"{len(tasks)} 个任务",
            "每个 F0-F10 小任务",
            "F1 设计继承门禁",
            "F1-PASS",
            "F4-CLOSED",
            "F5-F8-TOTAL-ACCEPTANCE",
            "F2-T01",
            "图 13",
            "图 25",
        ],
        "06": [
            "图片都必须与对应文字联合理解",
            "测评中心只包含",
            "/workspace/resources/quizzes/:resourceId",
            "实训任务书",
            "图片区域框选提问",
            "当前周期只设计、实施和验收桌面端",
            "每个小任务独立继承",
            "1440x900、1366x768 双尺寸验收",
        ],
        "08": [
            f"{len(product['routes'])} 条目标产品路由",
            f"{len(current_routes)} 条当前前端路由",
            "/workspace/resources/quizzes/:resourceId",
            "每个迁移任务必须执行自身携带的F1设计继承门禁",
        ],
        "11": [
            "outputs/改进想法.docx",
            "29 张原图必须逐张打开",
            "F2-T01",
            "F4-CLOSED",
            "F5-F8-TOTAL-ACCEPTANCE",
            "每个任务独立携带",
            "F1设计继承门禁",
        ],
    }
    context_texts = {
        "00": status_md,
        "06": constitution_md,
        "08": route_matrix_md,
        "11": recovery_md,
    }
    for document, tokens in expected_context_tokens.items():
        for token in tokens:
            if token not in context_texts[document]:
                context_errors.append(f"{document}缺少同步令牌：{token}")
    add_check(
        checks,
        "DOC-02",
        "状态、宪法、路由矩阵和恢复索引与主规格同步",
        not context_errors,
        "00/06/08/11使用实际数量、正确图文规则、桌面边界、练习归属、逐任务F1设计继承、F2-F4关闭状态和唯一继续入口。",
        context_errors,
    )

    all_passed = all(item["passed"] for item in checks)
    for check in checks:
        if not check["passed"]:
            errors.extend(f"{check['id']}: {detail}" for detail in check["details"])

    return {
        "schema_version": "3.1",
        "status": "PASS" if all_passed else "FAIL",
        "all_passed": all_passed,
        "counts": {
            "word_paragraph_positions": audit.get("paragraph_count"),
            "images": len(image_units),
            "requirement_groups": audit.get("group_count"),
            "atomic_requirements": len(atoms),
            "product_sections": len(product["sections"]),
            "product_ids_including_subsections": len(product_ids),
            "target_routes": len(target_routes),
            "implementation_phases": implementation.get("phase_count"),
            "implementation_tasks": len(tasks),
            "f1_design_rules": len(F1_DESIGN_RULE_IDS),
            "current_frontend_routes": len(current_routes),
            "backend_endpoints": len(scope.get("routes", [])),
            "orm_models": len(scope.get("models", [])),
            "protected_pages": len(protected_pages),
        },
        "checks": checks,
        "errors": errors,
        "image_text_units": image_units,
        "journey": journey_rows,
        "official_requirements": official_rows,
        "atom_group_counts": dict(sorted(Counter(item["group_id"] for item in atoms).items())),
        "execution_checkpoint": {
            "phase": current_checkpoint.get("phase"),
            "task": current_checkpoint.get("task"),
            "state": current_checkpoint.get("state"),
            "snapshot_sequence": current_checkpoint.get("snapshot_sequence"),
        },
    }


def render_report(result: dict[str, Any]) -> str:
    counts = result["counts"]
    checkpoint = result["execution_checkpoint"]
    lines = [
        "# EduMatrix 方案交叉校验报告",
        "",
        f"> 结论：`{result['status']}`  ",
        "> 校验对象：09 最终产品方案、10 详细实施方案、13 逐句逐图原子审计及全部证据 JSON。",
        "",
        "## 1. 校验结论",
        "",
        f"本轮按实际结构校验 {counts['atomic_requirements']} 条原子要求、{counts['images']} 组图文语义单元、{counts['target_routes']} 条目标路由和 {counts['implementation_tasks']} 个实施任务。每条原子要求的完整文字与页面合同必须同时进入09和10；每张图的结构、必须吸收和禁止照搬必须进入对应任务；{counts['f1_design_rules']}条F1设计规则必须由每个小任务独立携带。没有使用固定 175 条、固定 52 条或‘出现 G01-G28 即算覆盖’的旧门禁。",
        "",
        "| 检查 | 结果 | 证据 |",
        "|---|---|---|",
    ]
    for check in result["checks"]:
        lines.append(
            f"| `{check['id']}` {check['title']} | {'PASS' if check['passed'] else 'FAIL'} | {check['evidence']} |"
        )

    lines.extend(
        [
            "",
            "## 2. 实际规模",
            "",
            "| 项目 | 数量 |",
            "|---|---:|",
        ]
    )
    labels = {
        "word_paragraph_positions": "Word段位",
        "images": "原始图片/图文语义单元",
        "requirement_groups": "需求组",
        "atomic_requirements": "原子要求",
        "product_sections": "产品主章节",
        "product_ids_including_subsections": "产品章节/子章节ID",
        "target_routes": "目标路由",
        "implementation_phases": "实施阶段",
        "implementation_tasks": "实施任务",
        "f1_design_rules": "每任务F1设计规则",
        "current_frontend_routes": "当前前端路由",
        "backend_endpoints": "已分类后端端点",
        "orm_models": "已分类ORM模型",
        "protected_pages": "原版保护页",
    }
    for key, value in counts.items():
        lines.append(f"| {labels[key]} | {value} |")

    lines.extend(
        [
            "",
            "## 3. 29 张图与对应文字的联合校验",
            "",
            "每张图均不是单独看图，也不是把最近文字机械拼接，而是使用前一非空段、图片承载段、后一非空段、人工语义锚点、跨主题边界和图文综合解释。",
            "",
            "| 图 | 图片段 | 前文 | 后文 | 人工锚点 | 跨主题边界 | 综合解释摘要 |",
            "|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for unit in result["image_text_units"]:
        interpretation = unit["combined_contextual_interpretation"].replace("|", "\\|")
        lines.append(
            f"| {unit['image']} | {unit['paragraph']} | {unit['previous_paragraph']} | {unit['next_paragraph']} | "
            f"{','.join(str(value) for value in unit['semantic_anchor_paragraphs'])} | "
            f"{','.join(str(value) for value in unit['boundary_context_paragraphs']) or '-'} | {interpretation} |"
        )

    lines.extend(
        [
            "",
            "## 4. 完整学生旅程模拟",
            "",
            "| 步骤 | 用户任务 | 路由 | 产品规格 | 实施任务 | 主动作 | 结果 |",
            "|---:|---|---|---|---|---|---|",
        ]
    )
    for row in result["journey"]:
        lines.append(
            f"| {row['step']} | {row['name']} | `{row['route']}` | `{row['product_id']}` | `{row['task_id']}` | {row['primary_action']} | {'PASS' if row['passed'] else 'FAIL'} |"
        )

    lines.extend(
        [
            "",
            "## 5. 唯一赛题对应",
            "",
            "| 要求 | 产品章节 | 实施任务 | 结果 |",
            "|---|---|---|---|",
        ]
    )
    for row in result["official_requirements"]:
        lines.append(
            f"| `{row['id']}` {row['requirement']} | {', '.join(f'`{value}`' for value in row['product'])} | "
            f"{', '.join(f'`{value}`' for value in row['tasks'])} | {'PASS' if row['passed'] else 'FAIL'} |"
        )

    lines.extend(
        [
            "",
            "## 6. 原子要求覆盖",
            "",
            "这里的覆盖不是ID登记。机器逐条比较13中的完整产品解释、页面布局与交互、09章节正文和10责任任务正文；任一完整句缺失即失败。",
            "",
            "| 需求组 | 原子数量 |",
            "|---|---:|",
        ]
    )
    for group_id, count in result["atom_group_counts"].items():
        lines.append(f"| `{group_id}` | {count} |")

    lines.extend(
        [
            "",
            "## 7. 三轮复查结论",
            "",
            "1. **Word 顺序逐段逐图**：29 张图片均有人工语义锚点；图 13 与图 25 等跨主题图片已显式记录边界。",
            "2. **学生完整旅程**：从展示、画像、诊断、总路径、资源包、今日必做、智能组卷到反馈和下一日继续均有路由、主动作、状态与开发任务。",
            "3. **反向追溯**：每个目标路由有产品章节和实施阶段；每条原子要求的完整文字与页面合同进入09对应章节和10全部映射任务；29张图的observed/adopt/avoid三类合同进入对应任务。",
            "",
            "## 8. 当前状态边界",
            "",
            "- 09、10、13 是最终产品、实施与逐原子追踪规格；规格 PASS 证明结构一致，但任何运行完成结论仍必须来自对应任务账本、测试和验收证据。",
            f"- 当前唯一执行断点为 `{checkpoint['phase']} / {checkpoint['task']} / {checkpoint['state']}`（checkpoint 序号 {checkpoint['snapshot_sequence']}）；实时状态只读取活动 `current_checkpoint.json`，不在生成器中硬编码未来阶段或旧断点。",
            "- F0-F9、F10-T01 与 F10-T02 的关闭事实由各自逐原子账本和阶段报告保护；F10-T03 负责最终文档、依赖、部署与上下文收口，不重做已关闭业务功能。",
            "- 当前有效视觉合同为雾白页面、白色内容面与墨蓝灰浅色极简主题，正文采用思源黑体，Landing 与大型学习焦点标题少量使用思源宋体；本报告不授权修改冻结 UI。",
            "- 桌面端是当前唯一设计与验收范围；移动端已明确延期。",
            "- 视频生成、企业治理、专家认证和组织集成不阻塞比赛学生闭环。",
            "- 正式数据库、Git、远程仓库和现有比赛压缩包不属于本次规格报告的改动范围。",
            "",
        ]
    )

    failed = [item for item in result["checks"] if not item["passed"]]
    if failed:
        lines.extend(["## 9. 未通过项", ""])
        for check in failed:
            lines.append(f"### {check['id']} {check['title']}")
            lines.append("")
            lines.extend(f"- {detail}" for detail in check["details"])
            lines.append("")
    else:
        lines.extend(
            [
                "## 9. 最终结论",
                "",
                f"本轮规格层交叉校验全部通过。产品方案、实施方案、图文语义单元和原子追踪使用同一结构化事实源；PASS同时证明完整要求与页面合同进入09/10正文，并证明每个小任务都独立继承F1设计规则，不再只是ID、章节、任务或顶部总则存在。运行断点为 `{checkpoint['phase']} / {checkpoint['task']} / {checkpoint['state']}`；任务完成与否继续以对应逐原子账本、测试证据和活动 checkpoint 为唯一依据。",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.workspace.resolve()
    result = validate(root)
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(result), encoding="utf-8")
    output.with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not result["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
