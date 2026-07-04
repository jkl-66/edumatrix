import os
# Ensure mock LLM provider is used during tests to prevent hanging/timeouts
os.environ["EDUMATRIX_LLM_PROVIDER"] = "mock"

import unittest
import json
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, DBStudentProfile
from models import Evidence, EvidenceModality
from rag_engine import hybrid_rag

class TestMultimodalChat(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.student_id = "test-multimodal-student"
        self.db = SessionLocal()

        # Insert test profile
        existing = self.db.query(DBStudentProfile).filter_by(student_id=self.student_id).first()
        if existing:
            self.db.delete(existing)
            self.db.commit()

        profile = DBStudentProfile(
            student_id=self.student_id,
            concept_mastery={"池化层": 0.5},
            learning_goals=["池化层"],
            weak_points=["池化层"],
            interaction_preferences=["代码实操"],
            cognitive_style="代码型"
        )
        self.db.add(profile)
        self.db.commit()

    def tearDown(self):
        existing = self.db.query(DBStudentProfile).filter_by(student_id=self.student_id).first()
        if existing:
            self.db.delete(existing)
            self.db.commit()
        self.db.close()

    def test_casual_chat_non_academic(self):
        """测试闲聊或非学术问答在 chat 模式下能被快速分类拦截"""
        payload = {
            "message": "你好啊，今天天气真不错",
            "student_id": self.student_id,
            "mode": "chat",
            "images": []
        }
        response = self.client.post("/api/stream/chat", json=payload)
        self.assertEqual(response.status_code, 200)
        
        # 验证 SSE 格式
        sse_lines = response.text.split("\n")
        events = []
        for line in sse_lines:
            if line.startswith("event: "):
                events.append(line[7:])
        
        self.assertIn("complete", events)

    def test_multimodal_homework_qa_socratic(self):
        """测试多模态图片题目答疑与 Socratic 启发式对话"""
        payload = {
            "message": "计算这个池化层输出",
            "student_id": self.student_id,
            "mode": "chat",
            "images": ["data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="]
        }
        response = self.client.post("/api/stream/chat", json=payload)
        self.assertEqual(response.status_code, 200)

        # 验证返回了包含图片引用的 complete 数据结构
        sse_text = response.text
        self.assertIn("chat_chunk", sse_text)
        self.assertIn("complete", sse_text)

        # 解析 complete 数据
        complete_line = [line for line in sse_text.split("\n") if line.startswith("data: ") and '"resources":' in line]
        self.assertTrue(len(complete_line) > 0)
        data = json.loads(complete_line[0][6:])
        self.assertIn("resources", data)
        # 验证 VisRAG 匹配到的图片被返回
        has_slide_ref = any(r.get("type") == "slide_reference" for r in data["resources"])
        self.assertTrue(has_slide_ref)

    def test_matrix_command_shortcut(self):
        """测试 /matrix 命令快捷切换至 Swarm 资源生成"""
        payload = {
            "message": "/matrix 池化层",
            "student_id": self.student_id,
            "mode": "chat",
            "images": []
        }
        response = self.client.post("/api/stream/chat", json=payload)
        self.assertEqual(response.status_code, 200)
        
        # Swarm 模式下会有 5 个智能体并行 done 事件
        sse_text = response.text
        self.assertIn("agent_done", sse_text)
        self.assertIn("complete", sse_text)

    def test_deepseek_multimodal_fallback_warning(self):
        """测试当主模型为 DeepSeek 且上传图片而未配置任何多模态备用节点时，正确输出系统提示警告"""
        from llm_client import AsyncOpenAIChatLLM
        import asyncio

        # Arrange
        # Set endpoint to contain "deepseek" to simulate DeepSeek active LLM
        llm = AsyncOpenAIChatLLM(
            endpoint="https://api.deepseek.com/v1/chat/completions",
            api_key="fake-key",
            model="deepseek-chat"
        )

        # Clear fallback configurations to trigger the warning path
        os.environ["EDUMATRIX_MULTIMODAL_LLM_ENDPOINT"] = ""
        os.environ["EDUMATRIX_MULTIMODAL_LLM_API_KEY"] = ""
        os.environ["EDUMATRIX_MULTIMODAL_LLM_MODEL"] = ""
        # Mock ZHIPUAI_API_KEY as empty too
        old_zhipu = os.environ.get("ZHIPUAI_API_KEY", "")
        if "ZHIPUAI_API_KEY" in os.environ:
            del os.environ["ZHIPUAI_API_KEY"]

        try:
            # We mock the internal text generator because it would call DeepSeek and hit network
            async def mock_internal_gen(*args, **kwargs):
                yield "text answer"
            llm._generate_stream_internal = mock_internal_gen

            # Act
            chunks = []
            async def run_test():
                async for chunk in llm.generate_stream(
                    "system", "user prompt", role="assistant", 
                    images=["data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="]
                ):
                    chunks.append(chunk)

            asyncio.run(run_test())

            # Assert
            full_reply = "".join(chunks)
            self.assertIn("系统提示", full_reply)
            self.assertIn("DeepSeek", full_reply)
            self.assertIn("text answer", full_reply)

        finally:
            # Restore ZHIPUAI_API_KEY
            if old_zhipu:
                os.environ["ZHIPUAI_API_KEY"] = old_zhipu

    def test_deepseek_multimodal_fallback_routing(self):
        """测试当主模型为 DeepSeek 且上传图片，且配置了多模态备用节点时，流式请求正确重定向路由"""
        from llm_client import AsyncOpenAIChatLLM
        import asyncio

        # Arrange
        llm = AsyncOpenAIChatLLM(
            endpoint="https://api.deepseek.com/v1/chat/completions",
            api_key="fake-key",
            model="deepseek-chat"
        )

        # Set fake Zhipu fallback key to guarantee routing logic runs
        old_zhipu = os.environ.get("ZHIPUAI_API_KEY", "")
        os.environ["ZHIPUAI_API_KEY"] = "fake-zhipu-key"

        chunks = []
        
        original_gen = AsyncOpenAIChatLLM.generate_stream
        
        async def patched_gen(self_obj, system_prompt, user_prompt, role, images=[]):
            # Check if this is the target fallback client being routed to
            if "mock-vlm" in self_obj.model or "glm-4v" in self_obj.model:
                yield f"routed to {self_obj.model} with {len(images)} images"
            else:
                async for c in original_gen(self_obj, system_prompt, user_prompt, role=role, images=images):
                    yield c

        import unittest.mock as mock
        with mock.patch.object(AsyncOpenAIChatLLM, 'generate_stream', patched_gen):
            async def run_test():
                async for chunk in llm.generate_stream(
                    "system", "user prompt", role="assistant", 
                    images=["data:image/png;base64,fake-image"]
                ):
                    chunks.append(chunk)
            asyncio.run(run_test())

        # Clean up env
        if old_zhipu:
            os.environ["ZHIPUAI_API_KEY"] = old_zhipu
        else:
            del os.environ["ZHIPUAI_API_KEY"]

        # Assert
        self.assertEqual(chunks, ["routed to glm-4v with 1 images"])
