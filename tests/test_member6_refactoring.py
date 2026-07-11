import os
import sys
import unittest
import asyncio

# Ensure environment variables are mock for LLM and Embedding
os.environ["EDUMATRIX_LLM_PROVIDER"] = "mock"
os.environ["EDUMATRIX_EMBEDDING_PROVIDER"] = "hash"

from app.database import SessionLocal, DBQuizItem, DBQuizRecord, init_db
from code_exec_api import SANDBOX_RUNNER
from mirt_engine import estimate_irt_params_from_profile, AdaptiveTestEstimator, IRTItemParams
from quiz_api import _generate_quiz_id

class Member6RefactorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

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

        # 验证 os 导入被拦截
        self.assertIn("安全沙箱禁用了模块: os", res_os[1])
        self.assertEqual(res_os[0], "")

        # 验证 raw __import__ 被拦截
        self.assertIn("安全沙箱禁用了模块: subprocess", res_raw[1])
        self.assertEqual(res_raw[0], "")

        # 验证安全模块 numpy 运行正常
        self.assertIn("0", res_safe[0])
        self.assertEqual(res_safe[1], "")

    def test_irt_parameter_estimation_correct_direction(self):
        """验证 IRT 难度 beta 估计公式的正向对应逻辑（非颠倒）"""
        # Mastery 高对应正向高难度
        params_high = estimate_irt_params_from_profile(mastery=0.8, attempts=1)
        # Mastery 低对应正向低难度
        params_low = estimate_irt_params_from_profile(mastery=0.2, attempts=1)

        self.assertGreater(params_high.beta, params_low.beta, "高掌握度学生的题目参数估计难度应大于低掌握度学生")
        self.assertGreater(params_high.beta, 0.0, "mastery > 0.5 对应的 beta 应为正数")
        self.assertLess(params_low.beta, 0.0, "mastery < 0.5 对应的 beta 应为负数")

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

if __name__ == "__main__":
    unittest.main()
