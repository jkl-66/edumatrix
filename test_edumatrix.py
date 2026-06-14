import os
os.environ["EDUMATRIX_LLM_PROVIDER"] = "mock"
os.environ["EDUMATRIX_EMBEDDING_PROVIDER"] = "hash"

import unittest

from agent_swarm import EduMatrixSwarm
from drag_debate import DebateAugmentedRAG
from ingestion import DocumentIngestionPipeline
from manifold_alignment import verify_consistency
from models import StudentProfile
from observability import TELEMETRY
from rag_engine import hybrid_rag
from retrieval_evaluation import RetrievalEvalCase, evaluate_retrieval
from vector_store import InMemoryVectorIndex
from web_demo import _teacher_dashboard


class EduMatrixPipelineTests(unittest.TestCase):
    def test_graph_visrag_retrieves_pooling_context(self):
        bundle = hybrid_rag.retrieve("用图演示最大池化层", target="池化层")
        self.assertEqual(bundle.target, "池化层")
        self.assertIn("特征图", bundle.graph_context.learning_path)
        self.assertTrue(any(item.id == "IMG_PATCH_POOL_01" for item in bundle.evidence))

    def test_drag_keeps_relevant_evidence(self):
        bundle = hybrid_rag.retrieve("用 PyTorch 代码演示最大池化层", target="池化层")
        result = DebateAugmentedRAG().clean(bundle)
        kept = {verdict.evidence_id for verdict in result.verdicts if verdict.keep}
        self.assertIn("IMG_PATCH_POOL_01", kept)
        self.assertTrue(result.clean_evidence)

    def test_alignment_detects_pooling_conflict(self):
        text = "本讲义讲最大池化，窗口取局部最大值。"
        code = "import torch.nn as nn\npool = nn.AvgPool2d(2)"
        self.assertFalse(verify_consistency(text, code, threshold=0.4).passed)

    def test_swarm_generates_full_resource_package(self):
        swarm = EduMatrixSwarm()
        package = swarm.process("我看不懂池化层，请用图和 PyTorch 代码演示最大池化。")
        self.assertTrue(package.alignment.passed, package.alignment.advice)
        self.assertEqual(len(package.resources), 5)
        self.assertEqual(
            {resource.resource_type for resource in package.resources},
            {"专业讲义", "思维导图", "代码实操案例", "练习题", "虚拟人视频脚本"},
        )
        self.assertIn("knowledge_mastery", package.profile.dimension_states)
        self.assertTrue(package.profile.learning_state_causes)
        combined = "\n".join(resource.content for resource in package.resources)
        self.assertIn("MaxPool2d", combined)

    def test_dialogue_profile_extracts_state_causes_and_percentages(self):
        profile = StudentProfile(student_id="s1")
        profile.update_from_message(
            "我是计算机专业，期末要考数据结构和 CNN。池化层还是看不懂，"
            "最大池化和平均池化总混，题干长会漏条件，复习时只会看答案，"
            "我以为会了一做就错，希望你用图、代码和一步步提示。"
        )

        self.assertEqual(profile.major, "计算机专业")
        self.assertIn("期末复习", profile.learning_goals)
        self.assertIn("池化层", profile.weak_points)
        self.assertIn("misconception", profile.learning_state_causes)
        self.assertIn("cognitive_load", profile.learning_state_causes)
        self.assertIn("strategy_gap", profile.learning_state_causes)
        self.assertIn("metacognitive_mismatch", profile.learning_state_causes)
        self.assertEqual(len(profile.dimension_states), 10)

        total = sum(cause.percentage for cause in profile.learning_state_causes.values())
        self.assertAlmostEqual(total, 100.0, delta=0.6)
        report = profile.state_report()
        self.assertIn("不会原因占比", report)
        self.assertIn("误概念/易混点", report)

    def test_feedback_updates_mastery_and_metacognition(self):
        profile = StudentProfile(student_id="s2")
        profile.update_from_message("我觉得池化层已经懂了，但不确定自己是不是真的会。")
        before = profile.concept_mastery.get("池化层", 0.5)
        profile.update_from_feedback(
            feedback="做最大池化诊断题时选成了平均池化，提示两次后才改对。",
            accuracy=0.35,
            self_confidence=0.85,
            hint_count=2,
        )

        self.assertLess(profile.concept_mastery["池化层"], before)
        self.assertIn("metacognitive_mismatch", profile.learning_state_causes)
        self.assertIn("strategy_gap", profile.learning_state_causes)

    def test_machine_learning_course_flow_generates_strategy_plan(self):
        swarm = EduMatrixSwarm()
        package = swarm.process(
            "我是计算机专业，期末要考机器学习。逻辑回归和混淆矩阵总混，"
            "accuracy 很高但 recall 低我不知道怎么判断，希望用图和例子一步步讲。",
            student_id="ml-student",
        )

        self.assertEqual(package.profile.target_course, "机器学习导论")
        self.assertIn(package.target, {"逻辑回归", "混淆矩阵", "模型评估"})
        self.assertTrue(package.strategy_plan)
        self.assertTrue(package.strategy_plan.actions)
        self.assertTrue(any("混淆矩阵" in item.content or "逻辑回归" in item.content for item in package.resources))

    def test_teacher_dashboard_exposes_heatmap_and_interventions(self):
        dashboard = _teacher_dashboard()
        self.assertEqual(dashboard["course"], "机器学习导论")
        self.assertTrue(dashboard["heatmap"])
        self.assertTrue(dashboard["interventions"])

    def test_ingestion_pipeline_indexes_future_course_materials(self):
        index = InMemoryVectorIndex("test-course-index")
        pipeline = DocumentIngestionPipeline(index, chunk_size=80, overlap=10)
        report = pipeline.ingest_text(
            "最大池化使用窗口取局部最大值。混淆矩阵可以帮助学生理解 precision 和 recall 的差异。",
            source="unit-test.md",
            title="工业化摄入测试",
        )

        self.assertGreaterEqual(report.chunks, 1)
        self.assertEqual(index.count(), report.chunks)
        hits = index.search("最大池化 局部最大值", top_k=3)
        self.assertTrue(hits)
        self.assertIn("最大池化", hits[0].content)

    def test_retrieval_evaluation_reports_recall_and_mrr(self):
        report = evaluate_retrieval(
            hybrid_rag,
            (
                RetrievalEvalCase(
                    query="用 PyTorch 演示最大池化",
                    target="池化层",
                    expected_evidence_ids=("IMG_PATCH_POOL_01",),
                ),
            ),
        )
        self.assertEqual(report.cases, 1)
        self.assertGreaterEqual(report.recall_at_k, 1.0)
        self.assertGreater(report.mean_reciprocal_rank, 0.0)

    def test_telemetry_records_pipeline_metrics(self):
        TELEMETRY.clear()
        swarm = EduMatrixSwarm()
        swarm.process("我看不懂池化层，请用代码演示最大池化。")
        snapshot = TELEMETRY.snapshot()
        metric_names = {item["name"] for item in snapshot["metrics"]}
        span_names = {item["name"] for item in snapshot["spans"]}
        self.assertIn("retrieval.evidence_count", metric_names)
        self.assertIn("alignment.rollback_count", metric_names)
        self.assertIn("swarm.process", span_names)

    def test_database_pool_wash_with_postgres_mock(self):
        from unittest.mock import MagicMock
        from app.database import before_cursor_execute, on_connection_checkin, set_tenant, tenant_context
        
        # 1. 测试租户上下文切换
        self.assertEqual(tenant_context.get(), "public")
        with set_tenant("tenant_abc"):
            self.assertEqual(tenant_context.get(), "tenant_abc")
        self.assertEqual(tenant_context.get(), "public")
        
        # 2. 测试 before_cursor_execute 在 PostgreSQL 方言下的设置
        mock_conn = MagicMock()
        mock_conn.dialect.name = "postgresql"
        mock_cursor = MagicMock()
        
        with set_tenant("tenant_123"):
            before_cursor_execute(mock_conn, mock_cursor, "SELECT 1", {}, None, False)
            mock_cursor.execute.assert_called_with("SET search_path TO tenant_123;")
            
        # 3. 测试为 public 时不设置
        mock_cursor.reset_mock()
        before_cursor_execute(mock_conn, mock_cursor, "SELECT 1", {}, None, False)
        mock_cursor.execute.assert_not_called()
        
        # 4. 测试在 SQLite 下不起作用（防止本地开发环境报错）
        mock_conn.dialect.name = "sqlite"
        mock_cursor.reset_mock()
        with set_tenant("tenant_123"):
            before_cursor_execute(mock_conn, mock_cursor, "SELECT 1", {}, None, False)
            mock_cursor.execute.assert_not_called()

        # 5. 测试归还连接池时执行洗白 SQL
        mock_dbapi_conn = MagicMock()
        mock_dbapi_conn.__class__.__module__ = "psycopg2.extensions"
        mock_dbapi_cursor = MagicMock()
        mock_dbapi_conn.cursor.return_value = mock_dbapi_cursor
        
        on_connection_checkin(mock_dbapi_conn, None)
        mock_dbapi_cursor.execute.assert_called_with("SET search_path TO public;")
        mock_dbapi_cursor.close.assert_called_once()

    def test_stream_disconnect_handling(self):
        import asyncio
        from unittest.mock import MagicMock
        from fastapi import Request
        from stream_api import stream_chat

        mock_request = MagicMock(spec=Request)
        
        # 模拟 is_disconnected 最初返回 False，之后返回 True
        disconnect_calls = [False, False, True]
        async def mock_is_disconnected():
            if disconnect_calls:
                return disconnect_calls.pop(0)
            return True
        mock_request.is_disconnected = mock_is_disconnected
        mock_request.headers = {}
        
        async def mock_json():
            return {"message": "我看不懂池化层", "student_id": "test-student"}
        mock_request.json = mock_json

        # 执行 stream_chat 并消费其返回的流
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def run_test():
            response = await stream_chat(mock_request)
            async for chunk in response.body_iterator:
                pass

        with self.assertRaises(asyncio.CancelledError):
            if loop.is_running():
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, run_test())
                    future.result()
            else:
                loop.run_until_complete(run_test())

    def test_guided_decoding_self_healing(self):
        import asyncio
        from unittest.mock import AsyncMock, patch
        from app.agents.coder import async_refine_code_agent, PyTorchPoolCodeSchema

        lecture = "我们要学习最大池化层，最大池化非常重要。"
        code = "import torch\nimport torch.nn as nn\nclass Model(nn.Module):\n    def __init__(self):\n        super().__init__()\n        self.pool = nn.AvgPool2d(kernel_size=2, stride=2)"
        
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        async def run_healing():
            return await async_refine_code_agent(lecture, code, "平均池化不符合最大池化讲义")
            
        if loop.is_running():
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, run_healing())
                healed_code = future.result()
        else:
            healed_code = loop.run_until_complete(run_healing())
            
        self.assertIn("nn.MaxPool2d", healed_code)
        self.assertNotIn("nn.AvgPool2d", healed_code)

        mock_schema = PyTorchPoolCodeSchema(
            import_blocks="import torch\nimport torch.nn as nn",
            tensor_init="x = torch.randn(1, 1, 4, 4)",
            pool_layer_api="pool = nn.MaxPool2d(2, 2)",
            forward_and_print="print(pool(x))"
        )
        
        async def run_success():
            with patch("instructor.patch") as mock_patch:
                mock_client = AsyncMock()
                mock_create = AsyncMock(return_value=mock_schema)
                mock_client.chat.completions.create = mock_create
                mock_patch.return_value = mock_client
                
                return await async_refine_code_agent(lecture, code, "对齐纠偏")

        if loop.is_running():
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, run_success())
                res_code = future.result()
        else:
            res_code = loop.run_until_complete(run_success())
            
        self.assertIn("x = torch.randn(1, 1, 4, 4)", res_code)
        self.assertIn("pool = nn.MaxPool2d(2, 2)", res_code)

    def test_sandbox_resource_limits_and_timeout(self):
        import asyncio
        from code_exec_api import SANDBOX_RUNNER
        
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        async def run_normal():
            return await SANDBOX_RUNNER.run("print('hello sandbox')")
            
        if loop.is_running():
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, run_normal())
                stdout, stderr, elapsed = future.result()
        else:
            stdout, stderr, elapsed = loop.run_until_complete(run_normal())
            
        self.assertIn("hello sandbox", stdout)
        self.assertEqual(stderr, "")
        
        async def run_timeout():
            return await SANDBOX_RUNNER.run("import time; time.sleep(5)")
            
        if loop.is_running():
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, run_timeout())
                stdout, stderr, elapsed = future.result()
        else:
            stdout, stderr, elapsed = loop.run_until_complete(run_timeout())
            
        self.assertEqual(stdout, "")
        self.assertIn("超时", stderr)
        self.assertLessEqual(elapsed, 5.0)


if __name__ == "__main__":
    unittest.main()
