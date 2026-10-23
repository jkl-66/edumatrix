from __future__ import annotations

"""A deterministic code task generated from the second-course path."""

import ast
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from app.code_sandbox import CodeSandboxRunState, LocalPythonExecutor
from app.m5_resources import CodeSandboxContent


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "SECOND-COURSE-TOTAL-PATH-01"
CODE_REPORT_PATH = EVIDENCE_DIR / "code_theory_report.json"


BINARY_SEARCH_CODE = '''def binary_search(nums, target):
    """在升序数组中返回 target 的任意下标，不存在时返回 -1。"""
    left, right = 0, len(nums) - 1
    while left <= right:
        mid = left + (right - left) // 2
        if nums[mid] == target:
            return mid
        if nums[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1


cases = [
    ([], 3, -1),
    ([5], 5, 0),
    ([1, 2, 2, 4, 9], 2, 2),
    ([1, 2, 2, 4, 9], 8, -1),
]
for values, target, expected in cases:
    result = binary_search(values, target)
    # 重复值允许返回任意一个匹配下标；其余用例必须精确命中预期。
    if values and target == 2 and result in {1, 2}:
        continue
    assert result == expected, (values, target, result, expected)
print("binary_search: PASS")
print("complexity: O(log n) time, O(1) space")
'''


def build_code_task() -> CodeSandboxContent:
    return CodeSandboxContent.model_validate(
        {
            "schemaVersion": "f6.code-sandbox.v1",
            "title": "路径任务 · 有序数组二分查找",
            "summary": "实现并验证二分查找，理解区间不变量和边界收缩。",
            "courseTitle": "数据结构与算法工程实践：从基础结构到算法设计与岗位刷题",
            "knowledgePoint": {"id": "DSA-KP-19", "title": "二分查找与边界"},
            "adaptation": {
                "learningGoal": "能在有序数组中稳定处理空输入、单元素、重复值和未命中边界。",
                "profileSummary": "路径基线默认中等难度；先修复杂度、数组和排序。",
                "masterySummary": "待完成：通过四组边界测试并解释循环不变量。",
                "recentLearningSummary": "由双课程总路径的查找阶段生成。",
            },
            "checkpoints": [
                {"id": "cp-1", "title": "维护闭区间", "instruction": "说明 left、right 表示的搜索区间。", "completionHint": "循环开始时目标若存在必在 [left, right]。"},
                {"id": "cp-2", "title": "覆盖边界", "instruction": "运行空数组、单元素、重复值和未命中测试。", "completionHint": "所有断言通过且输出 PASS。"},
            ],
            "files": [{"path": "main.py", "language": "python", "content": BINARY_SEARCH_CODE}],
            "entryFile": "main.py",
            "standardInput": "",
            "requiredChecks": [
                {"id": "exit", "label": "程序正常结束", "kind": "exit_code_zero"},
                {"id": "pass", "label": "边界测试通过", "kind": "stdout_contains", "expectedText": "binary_search: PASS"},
                {"id": "complexity", "label": "复杂度说明存在", "kind": "stdout_contains", "expectedText": "O(log n) time, O(1) space"},
            ],
            "completionRule": "四组边界测试全部通过，并能说明闭区间不变量、时间 O(log n)、额外空间 O(1)。",
            "runtime": {"language": "python", "mode": "trusted_local", "timeoutSeconds": 10, "boundary": "受限本地 Python 子进程；无网络和文件写入。"},
            "sourceRefIds": ["hello-algo:docs/chapter_searching/binary_search.md"],
            "linkedTrainingTaskId": "SECOND-COURSE-TOTAL-PATH-01-DSA-KP-19",
            "semanticContext": {"pathCourseId": "course-data-structures-algorithms-engineering-v1", "pathNodeKey": "DSA-KP-19", "difficulty": "core"},
        }
    )


def theory_check(code: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    tree = ast.parse(code)
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "binary_search"), None)
    checks.append({"id": "function", "label": "包含 binary_search 函数", "passed": function is not None})
    source_has_closed_loop = bool(re.search(r"while\s+left\s*<=\s*right", code))
    checks.append({"id": "invariant", "label": "使用闭区间循环不变量", "passed": source_has_closed_loop})
    checks.append({"id": "mid", "label": "中点计算避免直接溢出式相加", "passed": "left + (right - left) // 2" in code})
    checks.append({"id": "shrink", "label": "每轮严格收缩搜索区间", "passed": "left = mid + 1" in code and "right = mid - 1" in code})
    checks.append({"id": "complexity", "label": "声明 O(log n) 时间与 O(1) 空间", "passed": "O(log n) time, O(1) space" in code})
    checks.append({"id": "boundaries", "label": "覆盖空、单元素、重复值和未命中", "passed": all(token in code for token in ["([], 3", "([5], 5", "[1, 2, 2, 4, 9]", "8, -1"])})
    return {"status": "passed" if all(item["passed"] for item in checks) else "failed", "checks": checks, "complexity": {"time": "O(log n)", "space": "O(1)"}, "invariant": "若 target 存在，则每轮循环开始时仍在闭区间 [left, right]；比较中点后丢弃不可能的一半。"}


async def run_code_task() -> dict[str, Any]:
    content = build_code_task()
    theory = theory_check(BINARY_SEARCH_CODE)
    state = CodeSandboxRunState(
        runAttemptId="path-code-demo-binary-search",
        ownerPublicId="system-demo",
        sourceResourceId="path-resource-binary-search",
        sourceResourceVersionId="path-resource-binary-search-v1",
        courseId="course-data-structures-algorithms-engineering-v1",
        knowledgePointId="DSA-KP-19",
        entryFile=content.entryFile,
        runtimeBoundary=content.runtime.boundary,
        timeoutSeconds=content.runtime.timeoutSeconds,
        code=BINARY_SEARCH_CODE,
        codeSha256=__import__("hashlib").sha256(BINARY_SEARCH_CODE.encode("utf-8")).hexdigest(),
        standardInput="",
        requiredChecks=tuple(content.requiredChecks),
        status="queued",
        createdAt="2026-08-31T00:00:00Z",
        totalCount=len(content.requiredChecks),
    )
    executor = LocalPythonExecutor()
    result = await executor.execute(state)
    checks = [{"id": item.id, "label": item.label, "passed": item.passed, "detail": item.detail} for item in [*result.__dict__.get("checks", ())]] if hasattr(result, "checks") else []
    return {
        "schema_version": "edumatrix.path-code-theory.v1",
        "task": content.model_dump(mode="json"),
        "theory": theory,
        "runtime": {"status": result.status, "exit_code": result.exitCode, "stdout": result.stdout, "stderr": result.stderr},
        "required_checks": [item.model_dump(mode="json") for item in content.requiredChecks],
        "passed": result.status == "success" and theory["status"] == "passed" and "binary_search: PASS" in result.stdout,
    }


def write_code_theory_report() -> dict[str, Any]:
    report = asyncio.run(run_code_task())
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    CODE_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


if __name__ == "__main__":
    report = write_code_theory_report()
    print(json.dumps({"passed": report["passed"], "runtime": report["runtime"]["status"], "theory": report["theory"]["status"]}, ensure_ascii=False))
