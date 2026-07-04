"""
EduMatrix 智教矩阵 - 后端启动入口

用法:
  # 开发模式（默认，不加载 FAISS 和真正嵌入）
  python run.py

  # 生产模式（OpenAI + 真实嵌入）
  set EDUMATRIX_LLM_API_KEY=sk-xxx
  set EDUMATRIX_EMBEDDING_PROVIDER=sentence_transformer
  python run.py

  # 生产模式（FAISS 加速）
  set EDUMATRIX_USE_FAISS=1
  python scripts/seed_faiss.py   # 先构建索引
  python run.py
"""

import os
import sys
import uvicorn

# 加载 .env 环境变量（必须在任何 os.getenv 之前）
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
        print(f"[dotenv] 已加载: {_env_path}")
    else:
        print(f"[dotenv] 未找到 .env 文件: {_env_path}")
except ImportError:
    print("[dotenv] python-dotenv 未安装，跳过 .env 加载")

HOST = os.getenv("EDUMATRIX_HOST", "0.0.0.0")
PORT = int(os.getenv("EDUMATRIX_PORT", "8000"))
RELOAD = os.getenv("EDUMATRIX_RELOAD", "1") == "1"


def main():
    provider = os.getenv("EDUMATRIX_LLM_PROVIDER", "openai")
    api_key = os.getenv("EDUMATRIX_LLM_API_KEY", "")
    endpoint = os.getenv("EDUMATRIX_LLM_ENDPOINT", "")
    model = os.getenv("EDUMATRIX_LLM_MODEL", "")

    print("=" * 56)
    print("  EduMatrix 智教矩阵 v1.0")
    print("=" * 56)

    if api_key:
        print(f"  LLM:     {provider} / {model}")
        print(f"  端点:    {endpoint}")
        print(f"  API Key: {api_key[:12]}...{api_key[-4:]}" if len(api_key) > 16 else f"  API Key: {api_key}")
    else:
        print("  LLM:     DeterministicEducationLLM (模拟模式)")
        print("           请在 .env 中设置 EDUMATRIX_LLM_API_KEY 或在浏览器 Settings 页面配置")

    emb = os.getenv("EDUMATRIX_EMBEDDING_PROVIDER", "hash")
    print(f"  嵌入:    {emb}")

    faiss = os.getenv("EDUMATRIX_USE_FAISS", "0")
    print(f"  FAISS:   {'开启' if faiss == '1' else '关闭'}")
    print(f"  地址:    http://{HOST}:{PORT}")
    print(f"  文档:    http://{HOST}:{PORT}/docs")
    print("=" * 56)

    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=RELOAD,
    )


if __name__ == "__main__":
    main()