import os
os.environ["EDUMATRIX_LLM_PROVIDER"] = "mock"
os.environ["EDUMATRIX_EMBEDDING_PROVIDER"] = "hash"

import unittest
from agent_swarm import EduMatrixSwarm
from rag_engine import hybrid_rag
from models import StudentProfile

class TestHallucinationPrevention(unittest.TestCase):
    """Test low-confidence blocking and out-of-domain graceful degradation."""

    def test_low_confidence_blocking(self):
        """Query with zero or very low relevance should trigger low_confidence Refusal block."""
        # 1. Test raw retrieval low_confidence calculation
        bundle = hybrid_rag.retrieve("xyz123")
        self.assertTrue(bundle.low_confidence)
        
        # 2. Test swarm processing refusal bypass
        swarm = EduMatrixSwarm()
        package = swarm.process("xyz123")
        
        refusal_msg = "抱歉，系统在知识库中未检索到与您提问相关的充足高置信度证据，为避免幻觉，建议您在‘课件管理’页面中上传包含该概念的教学资料。"
        
        self.assertTrue(package.alignment.passed)
        self.assertEqual(len(package.resources), 5)
        for res in package.resources:
            self.assertEqual(res.content, refusal_msg)

    def test_out_of_domain_graceful_degradation(self):
        """Query outside the ML domain should trigger out_of_domain and bypass GraphRAG default locking."""
        # 1. Test retrieval out_of_domain categorization
        bundle = hybrid_rag.retrieve("李白")
        self.assertTrue(bundle.out_of_domain)
        self.assertEqual(bundle.graph_context.learning_path, ())

        # 2. Test swarm processing degradation notice appending
        swarm = EduMatrixSwarm()
        package = swarm.process("李白")
        
        # Locate the "专业讲义" resource
        theory_res = next((res for res in package.resources if res.resource_type == "专业讲义"), None)
        self.assertIsNotNone(theory_res)
        
        degradation_msg = "EduMatrix 标准学科大纲知识图谱暂未涵盖该领域，系统已自动切换至多模态混合文本检索与实时互联网检索模式进行解答，您可以上传相关课件以扩充图谱。"
        self.assertIn(degradation_msg, theory_res.content)

if __name__ == "__main__":
    unittest.main()
