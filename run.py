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
import uvicorn

# Windows child processes must continue to use this project's virtual environment.
multiprocessing.set_executable(sys.executable)

# 强力防御：防止评委或本地电脑开启全局系统代理导致 B站 WAF 阻断
os.environ["NO_PROXY"] = "bilibili.com,biliapi.net,biliapi.com,baidu.com,bing.com"

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


def _free_port(port: int) -> None:
    """Only clean an old EduMatrix backend; never kill an unrelated Python service."""
    if os.name != "nt":
        return

    powershell = f"""
$connections = @(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue)
foreach ($connection in $connections) {{
    $ownerPid = [int]$connection.OwningProcess
    $process = Get-CimInstance Win32_Process -Filter \"ProcessId = $ownerPid\" -ErrorAction SilentlyContinue
    $command = [string]$process.CommandLine
    if ($command -match 'uvicorn app\\.main:app' -or $command -match 'run\\.py') {{
        Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
        Write-Output \"KILLED|$ownerPid|$command\"
    }} else {{
        Write-Output \"FOREIGN|$ownerPid|$command\"
    }}
}}
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", powershell],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to inspect port {port}: {result.stderr.strip()}")

    foreign = []
    for line in result.stdout.splitlines():
        if line.startswith("KILLED|"):
            _, pid, command = line.split("|", 2)
            print(f"  [port] stopped old EduMatrix backend PID {pid}: {command[:120]}")
        elif line.startswith("FOREIGN|"):
            foreign.append(line)
    if foreign:
        raise RuntimeError(
            f"Port {port} is occupied by a non-EduMatrix process; refusing to terminate it: "
            + "\\n".join(foreign)
        )
    time.sleep(0.4)

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
    print(f"  Python:  {sys.executable}")
    print(f"  Child:   {multiprocessing_spawn.get_executable()}")
    print(f"  Reload:  {RELOAD}")
    print("=" * 56)

    # Replace an old backend before binding the project port.
    _free_port(PORT)

    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=RELOAD,
    )


if __name__ == "__main__":
    main()
