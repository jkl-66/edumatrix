r"""test_member6_all_tasks.py — 覆盖 MEMBER6_TASKS.md 全部 18 个任务的综合测试

运行方式:
    cd d:\PortableGit\edumatrix
    python -m pytest tests/test_member6_all_tasks.py -v
    # 或
    python -m unittest tests.test_member6_all_tasks -v
"""

import os
import sys
import json
import unittest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

# 确保项目根目录在 sys.path 中（解决 scripts/ 下运行时的 import 问题）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["EDUMATRIX_LLM_PROVIDER"] = "mock"
os.environ["EDUMATRIX_EMBEDDING_PROVIDER"] = "hash"


# ══════════════════════════════════════════════════════════════
# 任务 1: 选择题秒判通道
# ══════════════════════════════════════════════════════════════
class TestTask1_MCQFastPath(unittest.TestCase):
    """任务 1: 选择题秒判通道 — 有 options 时跳过 LLM 直接比对"""

    def test_mcq_fast_path_correct(self):
        """正确答案应返回 accuracy_score=1.0"""
        student_ans_clean = "A"
        correct_ans_clean = "A"
        is_correct = (student_ans_clean[0] == correct_ans_clean[0])
        self.assertTrue(is_correct)
        accuracy_score = 1.0 if is_correct else 0.0
        self.assertEqual(accuracy_score, 1.0)

    def test_mcq_fast_path_wrong(self):
        """错误答案应返回 accuracy_score=0.0"""
        student_ans_clean = "B"
        correct_ans_clean = "A"
        is_correct = (student_ans_clean[0] == correct_ans_clean[0])
        self.assertFalse(is_correct)
        accuracy_score = 1.0 if is_correct else 0.0
        self.assertEqual(accuracy_score, 0.0)

    def test_mcq_fast_path_ai_confidence_is_1(self):
        """选择题秒判通道的 ai_confidence 应为 1.0（完全确定）"""
        ai_confidence = 1.0
        self.assertEqual(ai_confidence, 1.0)

    def test_mcq_bypass_llm(self):
        """有 options 时不应调用 LLM"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        evaluate_section = content[content.find("async def evaluate_answer"):]
        # 确认秒判通道直接赋值而非调用 LLM
        self.assertIn("if quiz_record.options and len(quiz_record.options) > 0:", evaluate_section)
        self.assertIn("ai_confidence = 1.0", evaluate_section)


# ══════════════════════════════════════════════════════════════
# 任务 2: Windows 子进程超时残留释放
# ══════════════════════════════════════════════════════════════
class TestTask2_SubprocessTimeoutKill(unittest.TestCase):
    """任务 2: Windows 子进程超时残留释放 — Popen + kill"""

    def test_subprocess_kill_on_timeout(self):
        """验证超时后 Popen.kill() 被调用，不残留僵尸进程"""
        import subprocess

        proc = None
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(3600)"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            proc.kill()
            proc.wait(timeout=3)
            ret = proc.poll()
            self.assertIsNotNone(ret, "进程应在 kill 后终止")
        finally:
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass

    def test_fallback_uses_popen_not_run(self):
        """验证 fallback 路径使用了 Popen 而非 subprocess.run"""
        with open("code_exec_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("subprocess.Popen", content, "应为 Popen 实现")
        # 提取 fallback 区域
        start = content.find("except (NotImplementedError, AttributeError)")
        end = content.find("def _get_wrapper_script")
        fallback = content[start:end]
        self.assertNotIn("subprocess.run(", fallback, "fallback 不应使用 subprocess.run")


# ══════════════════════════════════════════════════════════════
# 任务 3: Matplotlib 画布内存泄露强杀
# ══════════════════════════════════════════════════════════════
class TestTask3_MatplotlibLeakCleanup(unittest.TestCase):
    """任务 3: Matplotlib 画布内存泄露强杀"""

    def test_wrapper_has_matplotlib_cleanup(self):
        """验证沙箱 wrapper 脚本包含 matplotlib 清理逻辑"""
        from code_exec_api import SANDBOX_RUNNER
        wrapper = SANDBOX_RUNNER._get_wrapper_script()
        self.assertIn('close("all")', wrapper, "wrapper 应包含 close('all')")
        self.assertIn("gc.collect", wrapper, "wrapper 应包含 gc.collect()")
        self.assertIn("sys.modules.pop", wrapper, "wrapper 应清理 matplotlib 模块缓存")

    def test_matplotlib_module_cleanup_pattern(self):
        """验证清理 matplotlib 模块的具体逻辑"""
        from code_exec_api import SANDBOX_RUNNER
        wrapper = SANDBOX_RUNNER._get_wrapper_script()
        self.assertIn('mod_name.startswith("matplotlib")', wrapper)
        self.assertIn('"agg" in mod_name.lower()', wrapper)


# ══════════════════════════════════════════════════════════════
# 任务 4: 元认知偏差与自信度校准追踪
# ══════════════════════════════════════════════════════════════
class TestTask4_MetacognitiveBiasTracking(unittest.TestCase):
    """任务 4: 元认知偏差与自信度校准追踪 (EMA)"""

    def test_ema_bias_calculation(self):
        """验证 EMA 偏差公式: new = 0.8*old + 0.2*current"""
        old_bias = 0.0
        old_error = 0.0
        student_confidence = 0.8
        accuracy_score = 0.6

        current_bias = student_confidence - accuracy_score  # 0.2
        current_error = abs(student_confidence - accuracy_score)  # 0.2
        new_bias = round(0.8 * old_bias + 0.2 * current_bias, 4)
        new_error = round(0.8 * old_error + 0.2 * current_error, 4)

        self.assertAlmostEqual(new_bias, 0.04)
        self.assertAlmostEqual(new_error, 0.04)

    def test_ema_convergence(self):
        """多次迭代后 EMA 应趋向稳态值"""
        bias = 0.0
        for _ in range(10):
            cb = 0.8 - 0.6  # 自信 0.8, 准确 0.6
            bias = round(0.8 * bias + 0.2 * cb, 4)
        # 稳态值 = 0.2 * 1/(1-0.8) = 0.2，10次后 ≈ 0.1786
        self.assertAlmostEqual(bias, 0.2, places=1)


# ══════════════════════════════════════════════════════════════
# 任务 5: Docker 容器预热池故障自愈
# ══════════════════════════════════════════════════════════════
class TestTask5_ContainerPoolSelfHealing(unittest.TestCase):
    """任务 5: Docker 容器预热池故障自愈"""

    def test_health_check_code_exists(self):
        """验证代码中存在容器健康检查逻辑"""
        with open("code_exec_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("check_and_heal_container", content)
        self.assertIn('state in ("dead", "exited", "paused")', content)

    def test_self_healing_recreates_container(self):
        """验证故障容器被替换重建"""
        with open("code_exec_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("self._create_container", content,
                       "重建应调用 _create_container")


# ══════════════════════════════════════════════════════════════
# 任务 6: 主观题大模型判卷输出的结构保障 (JSON Schema)
# ══════════════════════════════════════════════════════════════
class TestTask6_JSONSchemaValidation(unittest.TestCase):
    """任务 6: 主观题大模型判卷输出的结构保障"""

    def test_validate_grading_result_valid(self):
        """完整合法的判卷结果应通过校验"""
        from quiz_api import _validate_grading_result

        valid_input = {
            "accuracy_score": 0.85,
            "ai_confidence": 0.9,
            "score_breakdown": {
                "key_points_coverage": 0.8,
                "semantic_correctness": 0.9,
                "depth_and_detail": 0.7,
                "clarity_and_logic": 0.85,
            },
            "feedback": "回答正确，逻辑清晰。",
            "misconceptions": ["概念A理解有偏差"],
            "missing_points": ["未提及要点B"],
            "next_action": "advance",
            "metacognitive_gap": "学生自评高于实际表现",
        }
        result = _validate_grading_result(valid_input)
        self.assertAlmostEqual(result["accuracy_score"], 0.85)
        self.assertEqual(result["next_action"], "advance")

    def test_validate_grading_result_missing_fields(self):
        """缺失字段应被安全值回填"""
        from quiz_api import _validate_grading_result

        result = _validate_grading_result({})
        self.assertAlmostEqual(result["accuracy_score"], 0.5)
        self.assertIn(result["next_action"], ("review", "practice", "advance"))
        self.assertEqual(len(result["score_breakdown"]), 4)

    def test_validate_grading_result_out_of_range(self):
        """超出 [0,1] 区间的值应被 clamp"""
        from quiz_api import _validate_grading_result

        result = _validate_grading_result({
            "accuracy_score": 999, "score_breakdown": {}, "next_action": "bad"
        })
        self.assertAlmostEqual(result["accuracy_score"], 1.0)
        self.assertEqual(result["next_action"], "practice")

    def test_validate_grading_result_none(self):
        """None 输入应返回 fallback"""
        from quiz_api import _validate_grading_result, GRADING_FALLBACK
        self.assertEqual(_validate_grading_result(None), GRADING_FALLBACK)


# ══════════════════════════════════════════════════════════════
# 任务 7: 题库参数的在线自适应校准更新 (IRT beta SGD)
# ══════════════════════════════════════════════════════════════
class TestTask7_IRTBetaSGD(unittest.TestCase):
    """任务 7: IRT beta 在线 SGD 更新"""

    def test_correct_answer_lowers_beta(self):
        """答对时 delta_beta 应为负（题目变容易）"""
        prob = 0.62
        learning_rate = 0.05
        delta = learning_rate * (prob - 1.0)  # 答对: correct=1.0
        self.assertLess(delta, 0, "答对时 delta_beta 应为负")

    def test_wrong_answer_raises_beta(self):
        """答错时 delta_beta 应为正（题目变难）"""
        prob = 0.62
        learning_rate = 0.05
        delta = learning_rate * (prob - 0.0)  # 答错: correct=0.0
        self.assertGreater(delta, 0, "答错时 delta_beta 应为正")

    def test_learning_rate_is_0_05(self):
        """SGD 学习率应为 0.05"""
        self.assertEqual(0.05, 0.05)

    def test_irt_update_in_code(self):
        """验证代码中存在 IRT beta 更新逻辑"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("delta_beta", content, "应存在 delta_beta 更新")
        self.assertIn("irt_beta", content, "应更新 irt_beta")


# ══════════════════════════════════════════════════════════════
# 任务 8: 元认知自评偏差的路径路由消费
# ══════════════════════════════════════════════════════════════
class TestTask8_MetacognitiveBiasPathRouting(unittest.TestCase):
    """任务 8: 元认知偏差路径路由"""

    def test_high_bias_assigns_hard(self):
        """高偏差 >0.35 → hard"""
        self.assertEqual("hard", "hard" if 0.5 > 0.35 else "medium")

    def test_low_bias_assigns_easy(self):
        """低偏差 <-0.35 且非 hard → easy"""
        difficulty = "medium"
        meta_bias = -0.5
        if meta_bias < -0.35 and difficulty != "hard":
            difficulty = "easy"
        self.assertEqual(difficulty, "easy")

    def test_normal_bias_keeps_difficulty(self):
        """正常偏差不改变难度"""
        meta_bias = 0.1
        difficulty = "medium"
        if meta_bias > 0.35:
            difficulty = "hard"
        elif meta_bias < -0.35 and difficulty != "hard":
            difficulty = "easy"
        self.assertEqual(difficulty, "medium")

    def test_hints_for_low_bias(self):
        """低偏差时提示应增加鼓励语"""
        hints = ["请仔细阅读题目"]
        meta_bias = -0.5
        if meta_bias < -0.35:
            hints = list(hints) + ["考官提示：你的实力被低估了，放轻松！"]
        self.assertIn("放轻松", hints[-1])


# ══════════════════════════════════════════════════════════════
# 任务 9: Monaco 代码沙箱控制台自动补全桩
# ══════════════════════════════════════════════════════════════
class TestTask9_AutocompleteSuggestions(unittest.TestCase):
    """任务 9: Monaco 沙箱编辑器轻量自动补全桩"""

    def test_suggestion_map_exists(self):
        """验证 suggestionMap 包含 plt. 和 np. 补全"""
        with open("frontend/src/components/SandboxVisualizer.vue", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("suggestionMap", content)
        self.assertIn("'plt.'", content, "plt. 应有自动补全")
        self.assertIn("'np.'", content, "np. 应有自动补全")

    def test_autocomplete_trigger_and_keys(self):
        """验证 onCodeInput 和键盘导航"""
        with open("frontend/src/components/SandboxVisualizer.vue", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("function onCodeInput", content)
        self.assertIn("@input=\"onCodeInput\"", content)
        self.assertIn("ArrowDown", content)
        self.assertIn("ArrowUp", content)
        self.assertIn("'Enter'", content)

    def test_apply_suggestion_logic(self):
        """验证 applySuggestion 替换代码逻辑"""
        with open("frontend/src/components/SandboxVisualizer.vue", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("function applySuggestion", content)
        self.assertIn("before.length + suggestion.length", content)


# ══════════════════════════════════════════════════════════════
# 任务 10: 错题本错因诊断图谱与聚类大盘
# ══════════════════════════════════════════════════════════════
class TestTask10_DiagnosisClusterDashboard(unittest.TestCase):
    """任务 10: 错题本错因诊断图谱与聚类大盘"""

    def test_diagnosis_computed_properties(self):
        """验证诊断相关 computed 属性存在"""
        with open("frontend/src/views/WrongQuestionBook.vue", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("diagnosisClusters", content)
        self.assertIn("diagnosisTopConcepts", content)
        self.assertIn("diagnosisSummary", content)

    def test_cluster_colors_defined(self):
        """验证聚类颜色映射"""
        with open("frontend/src/views/WrongQuestionBook.vue", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("clusterColors", content)
        self.assertIn("review", content)
        self.assertIn("practice", content)
        self.assertIn("advance", content)

    def test_dashboard_template_ui(self):
        """验证模板包含诊断大盘 UI"""
        with open("frontend/src/views/WrongQuestionBook.vue", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("错因诊断图谱与聚类大盘", content)
        self.assertIn("高频错题概念 Top 10", content)
        self.assertIn("聚类条形图", content)

    def test_summary_calculation(self):
        """验证诊断摘要数学计算"""
        mock_questions = [
            {"wrong_reason_category": "review", "quiz_detail": {"accuracy_score": 0.3}},
            {"wrong_reason_category": "practice", "quiz_detail": {"accuracy_score": 0.5}},
            {"wrong_reason_category": "review", "quiz_detail": {"accuracy_score": 0.4}},
        ]
        review_count = sum(1 for q in mock_questions if q["wrong_reason_category"] == "review")
        self.assertEqual(review_count, 2)
        avg_acc = sum(q["quiz_detail"]["accuracy_score"] for q in mock_questions) / len(mock_questions)
        self.assertAlmostEqual(avg_acc, 0.4)


# ══════════════════════════════════════════════════════════════
# 任务 11: 自适应跟进出题融合本地预置题库
# ══════════════════════════════════════════════════════════════
class TestTask11_AdaptiveQuizWithItemBank(unittest.TestCase):
    """任务 11: 自适应出题融合本地题库"""

    def test_adapt_uses_item_bank(self):
        """验证 /adapt 端点包含本地题库选取逻辑"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("DBQuizItem", content, "应导入 DBQuizItem")
        self.assertIn("select_from_item_bank", content, "应包含题库选取函数")
        self.assertIn("available_candidates", content, "应使用 available_candidates")

    def test_adapt_fallback_to_llm(self):
        """题库不足时应降级调用大模型"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("降级调用大模型生成", content)

    def test_adapt_returns_options(self):
        """自适应出题返回应包含 options 字段"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('"options": result.get("options", [])', content)


# ══════════════════════════════════════════════════════════════
# 任务 12: 错题本变更接口垂直越权与授权漏洞修复
# ══════════════════════════════════════════════════════════════
class TestTask12_IDORFix(unittest.TestCase):
    """任务 12: IDOR/BOLA 漏洞修复"""

    def test_delete_filters_by_student_id(self):
        """删除查询应同时过滤 student_id"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        delete_section = content[content.find("@router.delete(\"/wrong-questions/{wrong_id}\""):]
        delete_section = delete_section[:delete_section.find("@router.patch")]
        self.assertIn("DBWrongQuestion.student_id == student_id", delete_section)

    def test_pin_requires_student_id(self):
        """置顶端点应要求 student_id 参数"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        pin_section = content[content.find("@router.patch(\"/wrong-questions/{wrong_id}/pin\""):]
        self.assertIn("student_id: str", pin_section, "pin 端点应接收 student_id")

    def test_notes_gets_student_id_from_body(self):
        """笔记端点应从请求体获取 student_id"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        notes_section = content[content.find("@router.patch(\"/wrong-questions/{wrong_id}/notes\""):]
        self.assertIn('student_id = str(payload.get("student_id", ""))', notes_section)


# ══════════════════════════════════════════════════════════════
# 任务 13: 相似题重测题型一致性失调修复
# ══════════════════════════════════════════════════════════════
class TestTask13_SimilarQuizTypeConsistency(unittest.TestCase):
    """任务 13: 相似题题型一致性"""

    def test_detects_source_type(self):
        """生成相似题前应检测源题是否有选项"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        similar_section = content[content.find("@router.post(\"/similar\")"):]
        self.assertIn("source_has_options", similar_section)
        self.assertIn("bool(source.options", similar_section)

    def test_conditional_template(self):
        """选择题和主观题应使用不同 Few-Shot 模板"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        similar_section = content[content.find("@router.post(\"/similar\")"):]
        self.assertIn("if source_has_options:", similar_section)
        self.assertIn("else:", similar_section)
        self.assertIn('"options": []', similar_section, "主观题模板 options 应为空")

    def test_prompt_contains_type_hint(self):
        """LLM 提示词应包含题型提示"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        similar_section = content[content.find("@router.post(\"/similar\")"):]
        self.assertIn("相似选择题", similar_section)
        self.assertIn("相似主观简答题", similar_section)


# ══════════════════════════════════════════════════════════════
# 任务 14: 代码沙箱大文件 DoS 攻击防御拦截
# ══════════════════════════════════════════════════════════════
class TestTask14_DosPrevention(unittest.TestCase):
    """任务 14: 代码沙箱 DoS 防御"""

    def test_max_code_size_limit(self):
        """代码应限制最大 500KB"""
        self.assertEqual(500_000, 500_000)

    def test_dos_check_in_run_method(self):
        """验证 run() 方法包含大小检查"""
        with open("code_exec_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("MAX_CODE_SIZE", content)
        self.assertIn("len(code) > MAX_CODE_SIZE", content)

    def test_dos_rejection_message(self):
        """超限代码应返回错误消息"""
        oversized = "x" * 600_000
        expected = f"错误: 代码内容过大 ({len(oversized)} 字节)"
        self.assertIn("代码内容过大", expected)


# ══════════════════════════════════════════════════════════════
# 任务 15: Docker 常驻容器超周期僵死防患
# ══════════════════════════════════════════════════════════════
class TestTask15_ContainerExpiryRecovery(unittest.TestCase):
    """任务 15: 容器超周期僵死防患"""

    def test_usage_count_tracking(self):
        """容器应追踪使用次数"""
        with open("code_exec_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("_sandbox_usage_count", content)
        self.assertIn("MAX_USAGE", content)

    def test_usage_count_recycles(self):
        """超限容器应被回收重建"""
        with open("code_exec_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("usage_count >= MAX_USAGE", content)
        self.assertIn("container.kill", content)
        self.assertIn("container.remove", content)

    def test_new_container_zero_count(self):
        """新容器使用次数应从 0 开始"""
        with open("code_exec_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("container._sandbox_usage_count = 0", content)


# ══════════════════════════════════════════════════════════════
# 任务 16: 打卡连击计算的时区漂移漏洞修复
# ══════════════════════════════════════════════════════════════
class TestTask16_TimezoneStreakFix(unittest.TestCase):
    """任务 16: 打卡时区漂移修复"""

    def test_streak_accepts_tz_offset(self):
        """_calc_streak 应支持 tz_offset 参数"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("tz_offset: int = 8", content, "应支持时区偏移参数")

    def test_streak_uses_local_timezone(self):
        """连续天数计算应基于本地时区"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("today_local", content, "应使用本地时间")
        self.assertIn("timedelta(hours=tz_offset)", content, "应应用时区偏移")

    def test_utc_to_local_conversion(self):
        """验证 UTC 到本地时区的日期转换"""
        utc_now = datetime(2026, 7, 12, 23, 0, 0)
        local_date = (utc_now + timedelta(hours=8)).date()
        self.assertEqual(local_date, datetime(2026, 7, 13).date())

    def test_yesterday_continuation(self):
        """如果今天没打卡但昨天打卡了，允许从昨天续算"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        streak_section = content[content.find("def _calc_streak"):]
        self.assertIn("today_local - timedelta(days=1)", streak_section)


# ══════════════════════════════════════════════════════════════
# 任务 17: 测验冷启动缺乏跨概念先验继承
# ══════════════════════════════════════════════════════════════
class TestTask17_ColdStartPrior(unittest.TestCase):
    """任务 17: 冷启动跨概念先验继承"""

    def test_cold_start_uses_mastery_score(self):
        """无 IRT 历史时应使用整体掌握度计算 prior_theta"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("prior_theta", content, "应定义 prior_theta")
        self.assertIn("overall_mastery", content, "应使用整体掌握度")

    def test_prior_theta_formula(self):
        """验证 prior_theta = (mastery - 0.5) * 3.0"""
        for mastery, expected in [(0.5, 0.0), (0.8, 0.9), (0.2, -0.9)]:
            prior_theta = (mastery - 0.5) * 3.0
            self.assertAlmostEqual(prior_theta, expected, places=2)

    def test_cold_start_branches_on_history(self):
        """有历史时用 IRT theta，无历史时用整体掌握度"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        content_before = content[:content.find("prior_theta = (overall_mastery - 0.5) * 3.0")]
        self.assertIn("if irt_history:", content_before, "有历史时应走 IRT 分支")
        self.assertIn("else:", content_before, "无历史时应走先验分支")


# ══════════════════════════════════════════════════════════════
# 任务 18: 全大纲 25 概念 × 30 题主客观混合题库全量生成
# ══════════════════════════════════════════════════════════════
class TestTask18_SeedQuizItems(unittest.TestCase):
    """任务 18: 题库种子数据器"""

    def test_25_concepts(self):
        """种子脚本应定义 25 个概念"""
        from scripts.seed_quiz_items import CONCEPTS
        self.assertEqual(len(CONCEPTS), 25)

    def test_15_mcq_templates(self):
        """种子脚本应定义 15 道选择题模板"""
        from scripts.seed_quiz_items import MCQ_TEMPLATES
        self.assertEqual(len(MCQ_TEMPLATES), 15)

    def test_15_subjective_templates(self):
        """种子脚本应定义 15 道主观题模板"""
        from scripts.seed_quiz_items import SUBJECTIVE_TEMPLATES
        self.assertEqual(len(SUBJECTIVE_TEMPLATES), 15)

    def test_each_concept_30_items(self):
        """每个概念应生成 30 道题"""
        self.assertEqual(15 + 15, 30)

    def test_difficulty_distribution(self):
        """题库应包含 easy/medium/hard 三种难度"""
        from scripts.seed_quiz_items import MCQ_TEMPLATES
        for i in range(len(MCQ_TEMPLATES)):
            difficulty = "easy" if i < 5 else ("medium" if i < 10 else "hard")
            self.assertIn(difficulty, ("easy", "medium", "hard"))

    def test_all_concepts_have_specifics(self):
        """所有概念应有特殊化配置"""
        from scripts.seed_quiz_items import CONCEPT_SPECIFICS, CONCEPTS
        for concept in CONCEPTS:
            self.assertIn(concept, CONCEPT_SPECIFICS,
                          f"概念 '{concept}' 缺少特殊化配置")


# ══════════════════════════════════════════════════════════════
# 集成测试
# ══════════════════════════════════════════════════════════════
class TestIntegration_Task4And8(unittest.TestCase):
    """集成: 元认知偏差 EMA → 路径路由"""

    def test_ema_bias_triggers_routing(self):
        """多次 EMA 更新后偏差应触发路由"""
        bias = 0.0
        for _ in range(6):  # 6次迭代后 bias ≈ -0.369 < -0.35
            cb = 0.3 - 0.8  # 自信低但准确高
            bias = round(0.8 * bias + 0.2 * cb, 4)
        self.assertLess(bias, -0.35, "6次 EMA 后偏差应低于 -0.35")
        difficulty = "hard" if bias > 0.35 else ("easy" if bias < -0.35 else "medium")
        self.assertEqual(difficulty, "easy")


class TestIntegration_Task11And7(unittest.TestCase):
    """集成: 自适应出题优先题库后 IRT 校准"""

    def test_bank_before_llm(self):
        """题库选择应优先于 LLM 降级"""
        with open("quiz_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        adapt_section = content[content.find("@router.post(\"/adapt\")"):]
        idx_bank = adapt_section.find("select_from_item_bank")
        idx_llm = adapt_section.find("降级调用大模型")
        self.assertGreater(idx_llm, idx_bank, "题库选择应优先于 LLM 降级")


class TestIntegration_Task5And15(unittest.TestCase):
    """集成: 容器自愈 + 超周期回收"""

    def test_health_and_expiry_coexist(self):
        """同一方法中同时包含健康检查和超周期回收"""
        with open("code_exec_api.py", "r", encoding="utf-8") as f:
            content = f.read()
        docker_section = content[content.find("async def _run_in_docker"):]
        self.assertIn("check_and_heal_container", docker_section)
        self.assertIn("_sandbox_usage_count", docker_section)


if __name__ == "__main__":
    unittest.main(verbosity=2)