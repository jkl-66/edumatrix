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

HOST = os.getenv("EDUMATRIX_HOST", "0.0.0.0")
PORT = int(os.getenv("EDUMATRIX_PORT", "8000"))
RELOAD = os.getenv("EDUMATRIX_RELOAD", "1") == "1"


def main():
    provider = os.getenv("EDUMATRIX_LLM_PROVIDER", "openai")
    api_key = os.getenv("EDUMATRIX_LLM_API_KEY", "")

    print("=" * 56)
    print("  EduMatrix 智教矩阵 v1.0")
    print("=" * 56)

    if api_key:
        print(f"  LLM:     {provider} ({os.getenv('EDUMATRIX_LLM_MODEL', 'gpt-4o-mini')})")
    else:
        print("  LLM:     DeterministicEducationLLM (模拟模式)")
        print("           设置 EDUMATRIX_LLM_API_KEY 启用真实 LLM")

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
