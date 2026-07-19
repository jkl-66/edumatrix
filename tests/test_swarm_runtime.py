import unittest

from agent_swarm import EduMatrixSwarm
from llm_client import AsyncDeterministicEducationLLM
from rag_engine import hybrid_rag


class OfflineRAG:
    """Keep runtime tests deterministic and independent of arXiv/video search."""

    def retrieve(self, query, target=None, top_k=6, profile=None, doc_constraint=None):
        return hybrid_rag.retrieve(
            query,
            target=target,
            top_k=top_k,
            profile=profile,
            disable_external=True,
            doc_constraint=doc_constraint,
        )


class IntentStub(AsyncDeterministicEducationLLM):
    async def generate(self, system_prompt, user_prompt, *, role):
        if role == "意图分类":
            return '{"is_academic": false, "reply": "## 智能答疑 / 系统说明\\n\\n请提出学习问题。"}'
        return await super().generate(system_prompt, user_prompt, role=role)


class TestSwarmRuntime(unittest.TestCase):
    def test_non_academic_guard_returns_valid_learning_signal(self):
        package = EduMatrixSwarm(
            rag=OfflineRAG(), llm=IntentStub()
        ).process("你好，谢谢。")

        self.assertEqual(package.target, "系统沟通")
        self.assertEqual(package.learning_signal.accuracy, 1.0)
        self.assertFalse(package.learning_signal.needs_replan)
        self.assertEqual(package.learning_signal.sandbox_error_rate, 0.0)

    def test_academic_input_returns_five_resource_package(self):
        package = EduMatrixSwarm(
            rag=OfflineRAG(), llm=AsyncDeterministicEducationLLM()
        ).process(
            "我看不懂池化层，请用图和 PyTorch 代码演示最大池化。"
        )

        self.assertTrue(package.alignment.passed, package.alignment.advice)
        self.assertEqual(len(package.resources), 5)
        self.assertEqual(
            {resource.resource_type for resource in package.resources},
            {"专业讲义", "思维导图", "代码实操案例", "练习题", "自适应推荐视频"},
        )


if __name__ == "__main__":
    unittest.main()
