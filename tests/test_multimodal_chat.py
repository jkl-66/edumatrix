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

        # Clear profile store cache in all cached swarms to ensure test isolation
        from swarm_factory import _swarm_cache
        for swarm in _swarm_cache.values():
            if hasattr(swarm, "profile_store"):
                swarm.profile_store.clear()

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

    def test_chat_multi_turn_memory(self):
        """测试流式对话多轮对话记忆功能"""
        # 第一轮提问
        payload1 = {
            "message": "什么是梯度下降？",
            "student_id": self.student_id,
            "mode": "chat",
            "images": []
        }
        response1 = self.client.post("/api/stream/chat", json=payload1)
        self.assertEqual(response1.status_code, 200)

        # 检查数据库中已记录第一轮对话
        from app.crud import get_conversation_history
        conversations = get_conversation_history(self.db, self.student_id, limit=5)
        self.assertTrue(len(conversations) > 0)
        # 验证 SQLite 中写入了真实的流式回答（而不是占位符 "单轮流式对话"）
        first_resp = conversations[0].response_summary
        self.assertNotEqual(first_resp, "单轮流式对话")
        self.assertTrue(
            any(role in first_resp for role in ("自适应助教", "自适应考官", "概念可视化导师"))
            and "已基于检索证据处理主题：" in first_resp
        )

        # 验证内存/数据库 profile 中的 history_logs 已经追加了第1轮对话
        from app.crud import load_student_profile
        profile = load_student_profile(self.db, self.student_id)
        self.assertIn("什么是梯度下降？", profile.history)
        self.assertIn(first_resp, profile.history)

        # 第二轮追问
        payload2 = {
            "message": "它主要有哪些变体？",
            "student_id": self.student_id,
            "mode": "chat",
            "images": []
        }
        # 我们使用 unittest.mock 来捕获传递给大模型的 prompts 包含历史记录
        from unittest.mock import patch
        from llm_client import AsyncDeterministicEducationLLM

        original_stream = AsyncDeterministicEducationLLM.generate_stream
        captured_prompts = []

        async def mock_generate_stream(self_obj, system_prompt, user_prompt, *args, **kwargs):
            captured_prompts.append((system_prompt, user_prompt))
            async for chunk in original_stream(self_obj, system_prompt, user_prompt, *args, **kwargs):
                yield chunk

        with patch.object(AsyncDeterministicEducationLLM, 'generate_stream', mock_generate_stream):
            response2 = self.client.post("/api/stream/chat", json=payload2)
            self.assertEqual(response2.status_code, 200)

        # 验证传递给大模型的 user_prompt 中包含了第一轮的历史对话
        self.assertTrue(len(captured_prompts) > 0)
        sys_p, usr_p = captured_prompts[0]
        self.assertIn("【历史对话记录】", usr_p)
        self.assertIn("什么是梯度下降？", usr_p)
        self.assertIn(first_resp, usr_p)
        self.assertIn("它主要有哪些变体？", usr_p)
