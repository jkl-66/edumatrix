import asyncio
import json
import code_exec_api
from dataclasses import replace
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile
import unittest

from cache_utils import TTLBoundedCache
from code_exec_api import SandboxProcessRunner
from config import CONFIG
from document_parser import DocumentLimitError, validate_document_limits
from drag_debate import DebateAugmentedRAG
from mirt_engine import AdaptiveTestEstimator, IRTItemParams, mcmc_calibrate_item_parameters
from models import Evidence, EvidenceModality, GraphContext, RetrievalBundle
from swarm_factory import build_swarm_from_headers


class TestHardening(unittest.TestCase):
    def test_ttl_cache_expires_and_evicts_lru(self):
        now = [0.0]
        cache = TTLBoundedCache(maxsize=2, ttl_seconds=10, clock=lambda: now[0])
        cache["a"] = 1
        cache["b"] = 2
        self.assertEqual(cache.get("a"), 1)
        cache["c"] = 3
        self.assertIsNone(cache.get("b"))
        now[0] = 11.0
        self.assertEqual(len(cache), 0)

    def test_pptx_page_and_archive_limits(self):
        payload = BytesIO()
        with ZipFile(payload, "w") as archive:
            archive.writestr("ppt/slides/slide1.xml", "slide")
        with self.assertRaises(DocumentLimitError):
            validate_document_limits(payload.getvalue(), "lesson.pptx", max_pages=0)

        payload = BytesIO()
        with ZipFile(payload, "w") as archive:
            archive.writestr("word/document.xml", "x")
            archive.writestr("word/styles.xml", "x")
        with self.assertRaises(DocumentLimitError):
            validate_document_limits(payload.getvalue(), "lesson.docx", max_archive_members=1)

    def test_mirt_extreme_values_are_bounded(self):
        estimator = AdaptiveTestEstimator(prior_std=[0, float("nan"), -1])
        item = IRTItemParams(alpha=[float("nan")], beta=[float("inf")], gamma=float("nan"))
        self.assertTrue(all(0.0 <= value <= 1.0 for value in (
            estimator._probability_correct([0.0, 0.0, 0.0], item),
        )))
        calibrated = mcmc_calibrate_item_parameters(
            [[1]], [[0.0, 0.0, 0.0]], [item], iterations=2, burn_in=10
        )
        self.assertEqual(len(calibrated), 1)
        self.assertTrue(all(0.2 <= value <= 3.0 for value in calibrated[0].alpha))

    def test_async_debate_does_not_nest_event_loop(self):
        class Judge:
            async def generate(self, system_prompt, user_prompt, *, role):
                return json.dumps([
                    {"evidence_id": "e1", "pro_score": 0.9, "con_score": 0.1,
                     "judge_score": 0.85, "reason": "相关"},
                    {"evidence_id": "e2", "pro_score": 0.8, "con_score": 0.1,
                     "judge_score": 0.75, "reason": "相关"},
                ])

        evidence = tuple(
            Evidence(
                id=f"e{i}", title=f"证据{i}", content="机器学习内容",
                modality=EvidenceModality.TEXT, source="test", score=0.8,
            ) for i in (1, 2)
        )
        bundle = RetrievalBundle(
            query="机器学习", target="机器学习",
            graph_context=GraphContext("机器学习", ("机器学习",), (), ()),
            evidence=evidence,
        )
        result = asyncio.run(DebateAugmentedRAG(llm=Judge()).aclean(bundle))
        self.assertEqual(len(result.clean_evidence), 2)
        self.assertTrue(all(item["method"] == "llm_debate" for item in result.trajectory))

    def test_deterministic_acceptance_header_uses_local_llm(self):
        swarm = build_swarm_from_headers({"x-edumatrix-llm-mode": "deterministic"})
        self.assertEqual(type(swarm.llm).__name__, "AsyncDeterministicEducationLLM")


class TestTrustedLocalSandbox(unittest.TestCase):
    """Regression coverage for the no-Docker research/demo execution path."""

    def setUp(self):
        self.runner = SandboxProcessRunner()
        self.runner.mode = "trusted_local"
        self.runner.docker_available = False

    def tearDown(self):
        asyncio.run(self.runner.shutdown())

    def run_code(self, code: str):
        return asyncio.run(self.runner.run(code))

    def test_status_identifies_research_mode_without_container_isolation(self):
        self.assertTrue(self.runner.execution_enabled)
        self.assertEqual(self.runner.mode, "trusted_local")
        self.assertEqual(self.runner.status_message().startswith("本地可信研究模式"), True)

    def test_trusted_local_executes_safe_python(self):
        output, error, _ = self.run_code("print(6 * 7)")
        self.assertIn("42", output)
        self.assertEqual(error, "")

    def test_trusted_local_rejects_os_import_before_execution(self):
        output, error, _ = self.run_code("import os\nos.system('echo unsafe')")
        self.assertEqual(output, "")
        self.assertTrue(error)

    def test_trusted_local_kills_timeout(self):
        test_config = replace(CONFIG, sandbox_timeout=0.5)
        with patch.object(code_exec_api, "CONFIG", test_config):
            output, error, _ = self.run_code("while True:\n    pass")
        self.assertEqual(output, "")
        self.assertTrue(error)

    def test_trusted_local_caps_output(self):
        test_config = replace(CONFIG, sandbox_max_output_bytes=1024)
        with patch.object(code_exec_api, "CONFIG", test_config):
            output, error, _ = self.run_code("print('x' * 5000)")
        self.assertLessEqual(len(output.encode("utf-8")), 1024)
        self.assertTrue(error)


if __name__ == "__main__":
    unittest.main()
