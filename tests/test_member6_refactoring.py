import os
import sys
import unittest
import asyncio
from fastapi.testclient import TestClient

# Ensure environment variables are mock for LLM and Embedding
os.environ["EDUMATRIX_LLM_PROVIDER"] = "mock"
os.environ["EDUMATRIX_EMBEDDING_PROVIDER"] = "hash"

from app.database import SessionLocal, DBQuizItem, DBQuizRecord, init_db
from app.main import app
from code_exec_api import SANDBOX_RUNNER
from mirt_engine import (
    estimate_irt_params_from_profile,
    AdaptiveTestEstimator,
    IRTItemParams,
    mcmc_calibrate_item_parameters,
)
from quiz_api import _generate_quiz_id


class Member6RefactorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def test_sandbox_security_blocks_unsafe_imports(self):
        """验证安全沙箱是否成功阻断了恶意系统导入（防 RCE 逃逸）"""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def run_malicious_code():
            # 试图导入 os 执行命令
            code_os = "import os\nos.system('echo Hacked')"
            out_os, err_os, _ = await SANDBOX_RUNNER.run(code_os)

            # 试图使用 raw __import__ 绕过
            code_raw = "__import__('subprocess').run(['echo', 'Hacked'])"
            out_raw, err_raw, _ = await SANDBOX_RUNNER.run(code_raw)

            # 正常安全代码
            code_safe = "import numpy as np\nprint(np.sin(0))"
            out_safe, err_safe, _ = await SANDBOX_RUNNER.run(code_safe)

            return (out_os, err_os), (out_raw, err_raw), (out_safe, err_safe)

        if loop.is_running():
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                res_os, res_raw, res_safe = executor.submit(asyncio.run, run_malicious_code()).result()
        else:
            res_os, res_raw, res_safe = loop.run_until_complete(run_malicious_code())

        # 验证 os 导入被拦截 (AST 或 运行时)
        self.assertTrue("安全拦截" in res_os[1] or "禁用" in res_os[1])
        self.assertEqual(res_os[0], "")

        # 验证 raw __import__ 被拦截
        self.assertTrue("安全拦截" in res_raw[1] or "禁用" in res_raw[1])
        self.assertEqual(res_raw[0], "")

        # 验证安全模块 numpy 运行正常
        self.assertIn("0", res_safe[0])
        self.assertEqual(res_safe[1], "")

    def test_sandbox_ast_blocks_reflection_and_eval(self):
        """验证 AST 静态验证器拦截双下划线反射逃逸与危险内置函数"""
        # 1. 拦截反射属性访问 (如 __class__)
        code_reflection = "x = ().__class__.__base__"
        out, err, _ = asyncio.run(SANDBOX_RUNNER.run(code_reflection))
        self.assertIn("安全拦截", err)
        self.assertTrue("__class__" in err or "__base__" in err)

        # 2. 拦截危险内置调用 (如 eval, exec)
        code_eval = "eval('1+1')"
        out, err, _ = asyncio.run(SANDBOX_RUNNER.run(code_eval))
        self.assertIn("安全拦截", err)
        self.assertIn("eval", err)

        # 3. 拦截双下划线内置变量 (如 __builtins__)
        code_builtins = "print(__builtins__)"
        out, err, _ = asyncio.run(SANDBOX_RUNNER.run(code_builtins))
        self.assertIn("安全拦截", err)
        self.assertIn("__builtins__", err)

        # 4. 拦截通过 Subscript 下标绕过 (如 vars(re)['__builtins__'] 或 d['exec'])
        code_subscript_bypass = "import re\nreal_builtins = vars(re)['__builtins__']"
        out, err, _ = asyncio.run(SANDBOX_RUNNER.run(code_subscript_bypass))
        self.assertIn("安全拦截", err)
        self.assertTrue("vars" in err or "下标" in err or "__builtins__" in err)

        code_exec_subscript = "d = {}\nfn = d['exec']"
        out, err, _ = asyncio.run(SANDBOX_RUNNER.run(code_exec_subscript))
        self.assertIn("安全拦截", err)
        self.assertTrue("exec" in err or "下标" in err)

    def test_run_endpoint_50kb_dos_interception(self):
        """验证 API 路由入口前置 50KB 字节限制拦截，直接返回 400"""
        payload_large = {"code": "print('hello')" * 10000, "language": "python", "student_id": "test-student"}
        # 长度大于 50KB (14 * 10000 = 140000 字节)
        response = self.client.post("/api/code/run", json=payload_large)
        self.assertEqual(response.status_code, 400)
        self.assertIn("长度超限", response.json()["detail"])

    def test_mirt_3d_estimation(self):
        """验证三维 MIRT 能力估计向量估计的准确性与偏向性更新"""
        # 初始化 3D 估计器，初始能力 [0, 0, 0]
        estimator = AdaptiveTestEstimator(
            theta=[0.0, 0.0, 0.0],
            theta_std=[1.0, 1.0, 1.0],
            prior_mean=[0.0, 0.0, 0.0],
            prior_std=[1.0, 1.0, 1.0],
        )

        # 偏向维度 0 (Theory) 的题目: alpha=[2.0, 0.2, 0.1], beta=[0.0, 0.0, 0.0]
        item_theory = IRTItemParams(alpha=[2.0, 0.2, 0.1], beta=[0.0, 0.0, 0.0], gamma=0.25)
        # 答对该题，更新能力
        theta_new = estimator.update_ability(item_theory, True)
        
        # 维度 0 的能力增加幅度应明显大于维度 1 和维度 2
        self.assertGreater(theta_new[0], theta_new[1])
        self.assertGreater(theta_new[0], theta_new[2])

        # 偏向维度 1 (Coding) 的题目: alpha=[0.1, 2.0, 0.2], beta=[0.0, 0.0, 0.0]
        item_coding = IRTItemParams(alpha=[0.1, 2.0, 0.2], beta=[0.0, 0.0, 0.0], gamma=0.25)
        # 答错该题，更新能力
        theta_final = estimator.update_ability(item_coding, False)

        # 维度 1 的能力估计应该下降
        self.assertLess(theta_final[1], theta_new[1])

    def test_mcmc_calibration(self):
        """验证 Metropolis-Hastings MCMC 题目参数在线/离线校准"""
        # 模拟 3 位学生答 2 道题
        response_matrix = [
            [1, 0],  # 学生 1
            [1, 1],  # 学生 2
            [0, 0],  # 学生 3
        ]
        student_abilities = [
            [0.5, 0.2, 0.1],
            [1.2, 1.0, 0.8],
            [-1.0, -0.8, -0.5],
        ]
        initial_items = [
            IRTItemParams(alpha=[1.0, 1.0, 1.0], beta=[0.0, 0.0, 0.0], gamma=0.25),
            IRTItemParams(alpha=[1.0, 1.0, 1.0], beta=[0.5, 0.5, 0.5], gamma=0.25),
        ]

        calibrated = mcmc_calibrate_item_parameters(
            response_matrix=response_matrix,
            student_abilities=student_abilities,
            initial_items=initial_items,
            iterations=50,
            burn_in=10,
        )

        self.assertEqual(len(calibrated), 2)
        for item in calibrated:
            self.assertEqual(len(item.alpha), 3)
            self.assertEqual(len(item.beta), 3)
            self.assertGreater(item.alpha[0], 0.0)

    def test_mirt_covariance_matrix_update(self):
        """验证三维 MIRT 协方差矩阵的非对角线项是否被正确计算，并且 theta_std 由协方差对角开根号获得"""
        # 初始化 3D 估计器，初始能力 [0, 0, 0]
        estimator = AdaptiveTestEstimator(
            theta=[0.0, 0.0, 0.0],
            theta_std=[1.0, 1.0, 1.0],
            prior_mean=[0.0, 0.0, 0.0],
            prior_std=[1.0, 1.0, 1.0],
        )
        
        # 验证初始协方差矩阵是对角线
        self.assertIsNotNone(estimator.theta_cov)
        self.assertEqual(estimator.theta_cov[0][1], 0.0)
        self.assertEqual(estimator.theta_cov[0][2], 0.0)
        
        # 偏向维度 0 和维度 1 联合考察的题目: alpha=[2.0, 2.0, 0.1], beta=[0.0, 0.0, 0.0]
        item_joint = IRTItemParams(alpha=[2.0, 2.0, 0.1], beta=[0.0, 0.0, 0.0], gamma=0.25)
        
        # 答对该题，更新能力和协方差
        estimator.update_ability(item_joint, True)
        
        # 因为该题同时考察了维度 0 和维度 1，所以在观测信息矩阵中会引入非零的交叉项 (g0 * g1)
        # 从而求逆后，协方差矩阵的 theta_cov[0][1] (以及 theta_cov[1][0]) 不应该为 0
        self.assertNotEqual(estimator.theta_cov[0][1], 0.0, "维度相关题应当在协方差矩阵中引入非零非对角项")
        
        # 验证 theta_std 确实是由协方差矩阵对角元素开根号得到
        import math
        self.assertAlmostEqual(estimator.theta_std[0], math.sqrt(estimator.theta_cov[0][0]), places=6)
        self.assertAlmostEqual(estimator.theta_std[1], math.sqrt(estimator.theta_cov[1][1]), places=6)
        self.assertAlmostEqual(estimator.theta_std[2], math.sqrt(estimator.theta_cov[2][2]), places=6)
        
        # 验证 D-optimality 计算能正常执行
        d_opt = estimator.compute_d_optimality(estimator.theta, item_joint)
        self.assertGreater(d_opt, 0.0)

    def test_irt_parameter_estimation_correct_direction(self):
        """验证 IRT 难度 beta 估计公式的正向对应逻辑（非颠倒）"""
        # Mastery 高对应正向高难度
        params_high = estimate_irt_params_from_profile(mastery=0.8, attempts=1)
        # Mastery 低对应正向低难度
        params_low = estimate_irt_params_from_profile(mastery=0.2, attempts=1)

        self.assertGreater(params_high.beta[0], params_low.beta[0], "高掌握度学生的题目参数估计难度应大于低掌握度学生")
        self.assertGreater(params_high.beta[0], 0.0, "mastery > 0.5 对应的 beta 应为正数")
        self.assertLess(params_low.beta[0], 0.0, "mastery < 0.5 对应的 beta 应为负数")

    def test_item_bank_seeded_successfully(self):
        """验证本地题库是否成功被 Seeder 初始化写入数据库"""
        session = SessionLocal()
        try:
            items = session.query(DBQuizItem).filter(DBQuizItem.concept == "最大池化").all()
            self.assertGreaterEqual(len(items), 3, "本地种子题库中 '最大池化' 概念应至少有 3 道题以触发 Fisher 自适应选题")
            for item in items:
                self.assertIn(item.difficulty, ("easy", "medium", "hard"))
                self.assertIsNotNone(item.question)
                self.assertGreater(len(item.options), 0)
        finally:
            session.close()

    def test_sandbox_hardened_ast_blocks_indirect_system_calls(self):
        """验证硬化后的 AST 静态验证器是否成功检测并拦截了如 np.os.system 等嵌套式系统调用逃逸"""
        code_np_os = "import numpy as np\nnp.os.system('calc')"
        out, err, _ = asyncio.run(SANDBOX_RUNNER.run(code_np_os))
        self.assertIn("安全拦截", err)
        self.assertTrue("system" in err or "os" in err)

        # 嵌套更多的属性链
        code_nested = "import numpy as np\nnp.random.os.system('calc')"
        out2, err2, _ = asyncio.run(SANDBOX_RUNNER.run(code_nested))
        self.assertIn("安全拦截", err2)

    def test_evaluate_endpoint_sandbox_autograding_and_mirt_vectors(self):
        """验证 /evaluate 接口在收到编程题时，会自动触发沙箱运行，并将运行报告回传 LLM 进行判卷"""
        session = SessionLocal()
        try:
            from app.crud import load_student_profile
            student_id = "test-eval-student"
            quiz_id = "eval-test-quiz-123"
            
            # Clean up potential leftover record from previous runs
            session.query(DBQuizRecord).filter(DBQuizRecord.id == quiz_id).delete()
            session.commit()
            
            # 预置学生画像
            from app.crud import load_student_profile, save_student_profile
            profile = load_student_profile(session, student_id)
            profile.concept_mastery = {"神经网络": 0.5}
            save_student_profile(session, profile)
            
            record = DBQuizRecord(
                id=quiz_id,
                student_id=student_id,
                question="请编写一个 Python 函数，计算输入列表的平均值。",
                student_answer="",
                correct_answer="def avg(l): return sum(l)/len(l)",
                ai_confidence=0.0,
                student_confidence=0.0,
                accuracy_score=0.0,
                target_concept="神经网络",
                attempt_number=1,
                session_id="test-session",
                options=[],
                irt_alpha_vec=[1.0, 1.0, 1.0],
                irt_beta_vec=[0.0, 0.0, 0.0]
            )
            session.add(record)
            session.commit()
            
            # 2. 调用 /api/quiz/evaluate 接口提交一个代码答案
            student_code = "```python\ndef get_average(l):\n    return sum(l) / len(l)\nprint(get_average([1,2,3]))\n```"
            payload = {
                "quiz_id": quiz_id,
                "student_id": student_id,
                "answer": student_code,
                "student_confidence": 0.8,
                "attempt_number": 1,
                "duration_seconds": 12
            }
            response = self.client.post("/api/quiz/evaluate", json=payload)
            self.assertEqual(response.status_code, 200)
            
            res_json = response.json()
            self.assertIn("accuracy_score", res_json)
            self.assertIn("feedback", res_json)
            self.assertIn("irt", res_json)
            
            # 验证 theta 是 3D 向量形式
            theta = res_json["irt"].get("theta")
            self.assertTrue(isinstance(theta, list))
            self.assertEqual(len(theta), 3)
            
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
