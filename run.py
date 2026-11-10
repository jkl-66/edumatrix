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
import subprocess
import multiprocessing
import multiprocessing.spawn as multiprocessing_spawn
import time
import asyncio
import json
import socket
from pathlib import Path
from uuid import uuid4
import uvicorn

# Windows child processes must continue to use this project's virtual environment.
multiprocessing.set_executable(sys.executable)

# Local requests must stay local even on a machine using a network proxy.
os.environ["NO_PROXY"] = ','.join(filter(None, [os.getenv('NO_PROXY', ''),
    '127.0.0.1,localhost,bilibili.com,biliapi.net,biliapi.com']))

# 加载 .env 环境变量（必须在任何 os.getenv 之前）
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    _dotenv_disabled = os.getenv("PYTHON_DOTENV_DISABLED", "").strip().lower() in {"1", "true", "yes"}
    if _dotenv_disabled:
        print("[dotenv] 已按 PYTHON_DOTENV_DISABLED 跳过 .env 加载")
    elif os.path.exists(_env_path):
        load_dotenv(_env_path)
        print(f"[dotenv] 已加载: {_env_path}")
    else:
        print(f"[dotenv] 未找到 .env 文件: {_env_path}")
except ImportError:
    print("[dotenv] python-dotenv 未安装，跳过 .env 加载")


def _free_port(port: int) -> None:
    """Check availability; starting a copy must never stop an existing service."""
    with socket.socket() as probe:
        try:
            probe.bind((HOST, port))
        except OSError as exc:
            raise RuntimeError(f'端口 {port} 已被使用。打开已有服务，或在 .env 中设置 EDUMATRIX_PORT。') from exc

HOST = os.getenv("EDUMATRIX_HOST", "0.0.0.0")
PORT = int(os.getenv("EDUMATRIX_PORT", "8000"))
# Keep the evaluator/demo process on one interpreter by default. Developers can
# opt into reload explicitly with EDUMATRIX_RELOAD=1.
RELOAD = os.getenv("EDUMATRIX_RELOAD", "0") == "1"


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
        print(f"  端点:    {'已配置' if endpoint else '使用提供商默认值'}")
        print("  API Key: 已配置（仅后端读取）")
    elif provider in {'deterministic', 'local', 'offline'}:
        print("  LLM:     DeterministicEducationLLM (模拟模式)")
        print("           如需真实模型，请在后端 .env 中设置 EDUMATRIX_LLM_* 环境变量")
    else:
        print(f"  LLM:     {provider} / {model}；请在 .env 中填写模型密钥后生成新内容。")

    emb = os.getenv("EDUMATRIX_EMBEDDING_PROVIDER", "hash")
    print(f"  嵌入:    {emb}")

    faiss = os.getenv("EDUMATRIX_USE_FAISS", "0")
    print(f"  FAISS:   {'开启' if faiss == '1' else '关闭'}")
    print(f"  地址:    http://{HOST}:{PORT}")
    print(f"  文档:    http://{HOST}:{PORT}/docs")
    print(f"  Python:  {sys.executable}")
    print(f"  Child:   {multiprocessing_spawn.get_executable()}")
    print(f"  Reload:  {RELOAD}")
    print("=" * 56)

    _free_port(PORT)
    if RELOAD:
        uvicorn.run('app.main:app', host=HOST, port=PORT, reload=True)
    else:
        asyncio.run(serve_runtime())


RUNTIME_DIR = Path(__file__).resolve().parent / '.runtime'


def request_stop():
    instance_file = RUNTIME_DIR / 'instance.json'
    if not instance_file.exists():
        print('本目录没有运行中的服务。')
        return
    instance = json.loads(instance_file.read_text(encoding='utf8'))
    (RUNTIME_DIR / 'stop.json').write_text(json.dumps({'token': instance['token']}), encoding='utf8')
    print('已请求停止。当前生成保存完成后退出，未完成的排队任务将在下次启动继续。')


async def serve_runtime():
    RUNTIME_DIR.mkdir(exist_ok=True)
    token = uuid4().hex
    instance_file = RUNTIME_DIR / 'instance.json'
    stop_file = RUNTIME_DIR / 'stop.json'
    instance_file.write_text(json.dumps({'pid':os.getpid(), 'token':token, 'port':PORT,
        'root':str(Path(__file__).resolve().parent)}),encoding='utf8')
    server = uvicorn.Server(uvicorn.Config('app.main:app', host=HOST, port=PORT))
    async def observe_stop():
        while not server.should_exit:
            await asyncio.sleep(1)
            if not stop_file.exists():
                continue
            try:
                requested = json.loads(stop_file.read_text(encoding='utf8'))
            except (OSError, ValueError):
                continue
            if requested.get('token') != token:
                continue
            from app.generation_dispatch import GENERATION_DISPATCHER
            GENERATION_DISPATCHER.concurrency = 0
            if any(not work.done() for work in GENERATION_DISPATCHER.running.values()):
                continue
            server.should_exit = True
    watcher = asyncio.create_task(observe_stop())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        if instance_file.exists() and json.loads(instance_file.read_text(encoding='utf8')).get('token') == token:
            instance_file.unlink()
        if stop_file.exists() and json.loads(stop_file.read_text(encoding='utf8')).get('token') == token:
            stop_file.unlink()


if __name__ == "__main__":
    request_stop() if '--stop' in sys.argv else main()
