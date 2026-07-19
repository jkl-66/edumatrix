import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from app.auth import enforce_student_access


ROOT = Path(__file__).resolve().parents[1]


class TestSecurityContracts(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_demo_auth_requires_explicit_flag(self):
        config = self.read("config.py")
        auth = self.read("app/auth.py")
        self.assertIn('demo_mode: bool = os.getenv("EDUMATRIX_DEMO_MODE", "0") == "1"', config)
        self.assertIn("if not CONFIG.demo_mode:", auth)
        self.assertIn("raise credentials_exception", auth)

    def test_student_scope_is_server_side(self):
        auth = self.read("app/auth.py")
        self.assertIn("def enforce_student_access", auth)
        self.assertIn("无权访问其他学生的数据", auth)
        for relative in ("code_exec_api.py", "stream_api.py", "profile_api.py", "knowledge_api.py"):
            source = self.read(relative)
            self.assertIn("Depends(get_current_user)", source, relative)
            self.assertIn("enforce_student_access", source, relative)

    def test_sandbox_does_not_fallback_to_host_process(self):
        source = self.read("code_exec_api.py")
        self.assertIn("Docker 沙箱不可用或未启用", source)
        self.assertIn('sandbox_mode: str = os.getenv("EDUMATRIX_SANDBOX_MODE", "disabled")', self.read("config.py"))
        self.assertIn('@router.get("/status")', source)
        run_section = source[source.index("    async def run("):source.index("    async def _run_in_docker")]
        self.assertNotIn("return await self._run_in_subprocess(code)", run_section)

    def test_user_rag_requires_owner_filter(self):
        source = self.read("rag_engine.py")
        self.assertIn("owner_id: str = \"\"", source)
        self.assertIn('"owner_id": owner_id', source)
        self.assertIn('item.metadata.get("owner_id") == owner_id', source)

    def test_upload_has_bounded_read(self):
        config = self.read("config.py")
        knowledge = self.read("knowledge_api.py")
        self.assertIn("max_upload_bytes", config)
        self.assertIn("file.read(CONFIG.max_upload_bytes + 1)", knowledge)
        self.assertIn("status_code=413", knowledge)

    def test_student_scope_rejects_cross_user_requests(self):
        user = SimpleNamespace(role="student", username="student-a")
        self.assertEqual(enforce_student_access(None, user), "student-a")
        self.assertEqual(enforce_student_access("default", user), "student-a")
        with self.assertRaises(HTTPException) as raised:
            enforce_student_access("student-b", user)
        self.assertEqual(raised.exception.status_code, 403)

    def test_body_identity_is_resolved_for_core_routes(self):
        for relative in ("quiz_api.py", "flashcard_api.py", "behavior_api.py", "app/main.py"):
            source = self.read(relative)
            self.assertIn("enforce_student_access(payload.get(\"student_id\"), current_user)", source, relative)

    def test_remote_download_is_chunk_limited(self):
        knowledge = self.read("knowledge_api.py")
        self.assertIn('client.stream("GET"', knowledge)
        self.assertIn("async for chunk in resp.aiter_bytes", knowledge)
        self.assertIn("file_size > CONFIG.max_upload_bytes", knowledge)
        self.assertIn("except HTTPException", knowledge)

    def test_mutations_filter_by_owner(self):
        crud = self.read("app/crud.py")
        main = self.read("app/main.py")
        self.assertIn("DBNote.student_id == student_id", crud)
        self.assertIn("DBReviewPlan.student_id == student_id", crud)
        self.assertIn("student_id=None if current_user.role == \"teacher\" else current_user.username", main)

    def test_production_auth_secret_cannot_use_placeholder(self):
        config = self.read("config.py")
        self.assertIn('os.getenv("EDUMATRIX_ENV", "development")', config)
        self.assertIn("_INSECURE_AUTH_SECRET", config)
        self.assertIn("len(configured) < 32", config)


if __name__ == "__main__":
    unittest.main()
