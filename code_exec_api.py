from __future__ import annotations

import sys
import io
import time
import uuid
import base64
import traceback
import asyncio
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from app.database import DBCodeExecution, run_db_op

router = APIRouter(prefix="/api/code", tags=["code_execution"])


class SandboxProcessRunner:
    def __init__(self, pool_size: int = 3, image: str = "python:3.10-slim"):
        self.docker_available = False
        self.client = None
        self.containers = []
        self.executor = ThreadPoolExecutor(max_workers=5)
        self.pool_size = pool_size
        self.image = image
        self._lock = asyncio.Lock()

    async def start(self):
        try:
            import docker
            loop = asyncio.get_running_loop()
            self.client = await loop.run_in_executor(self.executor, docker.from_env)
            # Test connection
            await loop.run_in_executor(self.executor, self.client.ping)
            self.docker_available = True
            print("  [Sandbox] Docker daemon detected. Initializing container pool...")
            await self._prewarm_pool()
        except Exception as e:
            self.docker_available = False
            print(f"  [Sandbox] Docker daemon not available ({e}). Falling back to Subprocess sandbox.")

    async def _prewarm_pool(self):
        loop = asyncio.get_running_loop()
        try:
            print(f"  [Sandbox] Checking/Pulling image {self.image}...")
            await loop.run_in_executor(self.executor, self.client.images.pull, self.image)
        except Exception as e:
            print(f"  [Sandbox] Failed to pull image {self.image}: {e}. Falling back to Subprocess.")
            self.docker_available = False
            return

        for i in range(self.pool_size):
            try:
                container = await loop.run_in_executor(self.executor, self._create_container)
                async with self._lock:
                    self.containers.append(container)
                print(f"  [Sandbox] Container {i+1} pre-warmed: {container.short_id}")
            except Exception as ce:
                print(f"  [Sandbox] Failed to pre-warm container {i+1}: {ce}")
                self.docker_available = False
                break

    def _create_container(self):
        return self.client.containers.run(
            self.image,
            command="python -c 'import time; time.sleep(36000)'",
            detach=True,
            network_mode="none",
            mem_limit="512m",
            nano_cpus=1000000000,  # Limit to 1 core
            remove=False
        )

    async def run(self, code: str) -> tuple[str, str, float]:
        if self.docker_available:
            return await self._run_in_docker(code)
        else:
            return await self._run_in_subprocess(code)

    async def _run_in_docker(self, code: str) -> tuple[str, str, float]:
        loop = asyncio.get_running_loop()
        start_time = time.time()
        container = None

        async with self._lock:
            if self.containers:
                container = self.containers.pop(0)
            else:
                try:
                    container = await loop.run_in_executor(self.executor, self._create_container)
                except Exception as ce:
                    print(f"  [Sandbox] Failed to create container dynamically: {ce}. Falling back to subprocess.")
                    return await self._run_in_subprocess(code)

        wrapper_script = self._get_wrapper_script()
        encoded_wrapper = base64.b64encode(wrapper_script.encode('utf-8')).decode('utf-8')
        encoded_code = base64.b64encode(code.encode('utf-8')).decode('utf-8')

        exec_command = (
            f"python -c \"import base64, sys, io; "
            f"sys.stdin = io.StringIO(base64.b64decode('{encoded_code}').decode('utf-8')); "
            f"exec(base64.b64decode('{encoded_wrapper}').decode('utf-8'))\""
        )

        async def execute_in_thread():
            return await loop.run_in_executor(
                self.executor,
                container.exec_run,
                ["sh", "-c", exec_command]
            )

        try:
            exit_code, output = await asyncio.wait_for(execute_in_thread(), timeout=3.0)
            output_str = output.decode('utf-8', errors='replace')
            
            if "===STDERR_SEPARATOR===" in output_str:
                stdout, stderr = output_str.split("===STDERR_SEPARATOR===", 1)
            else:
                stdout, stderr = output_str, ""

            async with self._lock:
                self.containers.append(container)

            exec_time = time.time() - start_time
            return stdout, stderr, exec_time

        except asyncio.TimeoutError:
            print(f"  [Sandbox] Code execution timed out. Killing container: {container.short_id}")
            try:
                await loop.run_in_executor(self.executor, container.kill)
                await loop.run_in_executor(self.executor, container.remove)
            except Exception:
                pass

            new_container = await loop.run_in_executor(self.executor, self._create_container)
            async with self._lock:
                self.containers.append(new_container)

            exec_time = time.time() - start_time
            return "", "错误: 代码运行超时 (超过 3.0 秒被强制熔断)", exec_time
        except Exception as e:
            # Cleanup on failure and return container
            async with self._lock:
                self.containers.append(container)
            exec_time = time.time() - start_time
            return "", f"沙箱执行异常: {e}", exec_time

    async def _run_in_subprocess(self, code: str) -> tuple[str, str, float]:
        start_time = time.time()
        wrapper_script = self._get_wrapper_script()
        encoded_wrapper = base64.b64encode(wrapper_script.encode('utf-8')).decode('utf-8')
        encoded_code = base64.b64encode(code.encode('utf-8')).decode('utf-8')

        exec_command = (
            f"import base64, sys, io; "
            f"sys.stdin = io.StringIO(base64.b64decode('{encoded_code}').decode('utf-8')); "
            f"exec(base64.b64decode('{encoded_wrapper}').decode('utf-8'))"
        )

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                exec_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=3.0
                )
                stdout = stdout_bytes.decode('utf-8', errors='replace')
                stderr = stderr_bytes.decode('utf-8', errors='replace')

                if "===STDERR_SEPARATOR===" in stdout:
                    part_out, part_err = stdout.split("===STDERR_SEPARATOR===", 1)
                    stdout = part_out
                    stderr = part_err + stderr

                exec_time = time.time() - start_time
                return stdout, stderr, exec_time

            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
                exec_time = time.time() - start_time
                return "", "错误: 代码运行超时 (超过 3.0 秒被强制熔断)", exec_time

        except Exception as e:
            exec_time = time.time() - start_time
            return "", f"沙箱子进程启动失败: {e}", exec_time

    def _get_wrapper_script(self) -> str:
        return """
import sys
import io
import traceback
from contextlib import redirect_stdout, redirect_stderr

code_to_run = sys.stdin.read()

output_buffer = io.StringIO()
error_buffer = io.StringIO()

restricted_globals = {
    "__builtins__": {
        "abs": abs, "all": all, "any": any, "bool": bool,
        "dict": dict, "dir": dir, "enumerate": enumerate,
        "float": float, "format": format, "frozenset": frozenset,
        "help": help, "hex": hex, "id": id, "int": int,
        "isinstance": isinstance, "issubclass": issubclass,
        "len": len, "list": list, "map": map, "max": max,
        "min": min, "next": next, "object": object,
        "oct": oct, "ord": ord, "pow": pow, "print": print,
        "range": range, "repr": repr, "reversed": reversed,
        "round": round, "set": set, "slice": slice,
        "sorted": sorted, "str": str, "sum": sum,
        "tuple": tuple, "type": type, "zip": zip,
        "True": True, "False": False, "None": None,
        "Exception": Exception, "ValueError": ValueError,
        "TypeError": TypeError, "KeyError": KeyError,
        "IndexError": IndexError, "StopIteration": StopIteration,
        "RuntimeError": RuntimeError, "AttributeError": AttributeError,
        "ImportError": ImportError, "ModuleNotFoundError": ModuleNotFoundError,
        "ZeroDivisionError": ZeroDivisionError,
        "__import__": __import__,
    }
}

safe_modules = {}
for mod_name in ("math", "json", "random", "statistics", "collections", "itertools", "datetime", "re"):
    try:
        safe_modules[mod_name] = __import__(mod_name)
    except ImportError:
        pass
restricted_globals.update(safe_modules)

for extra in ("numpy", "np", "pandas", "pd", "matplotlib", "plt", "sklearn"):
    if extra in code_to_run:
        try:
            if extra == "matplotlib":
                import matplotlib
                matplotlib.use("Agg")
                restricted_globals["matplotlib"] = matplotlib
            elif extra == "plt":
                import matplotlib.pyplot as plt
                restricted_globals["plt"] = plt
            elif extra in ("numpy", "np"):
                import numpy as np
                restricted_globals["numpy"] = np
                restricted_globals["np"] = np
            elif extra in ("pandas", "pd"):
                import pandas as pd
                restricted_globals["pandas"] = pd
                restricted_globals["pd"] = pd
            elif extra == "sklearn":
                import sklearn
                restricted_globals["sklearn"] = sklearn
        except ImportError:
            pass

try:
    compiled = compile(code_to_run, "<sandbox>", "exec")
    with redirect_stdout(output_buffer), redirect_stderr(error_buffer):
        exec(compiled, restricted_globals)
        
        if "plt" in restricted_globals:
            import matplotlib.pyplot as plt_local
            if plt_local.get_fignums():
                import base64
                from io import BytesIO
                buf = BytesIO()
                plt_local.savefig(buf, format="png", dpi=100, bbox_inches="tight")
                buf.seek(0)
                img_b64 = base64.b64encode(buf.read()).decode("utf-8")
                plt_local.close("all")
                output_buffer.write(f"\\n![可视化输出](data:image/png;base64,{img_b64})")
except Exception as e:
    error_buffer.write(traceback.format_exc())

sys.stdout.write(output_buffer.getvalue())
sys.stdout.write("===STDERR_SEPARATOR===")
sys.stdout.write(error_buffer.getvalue())
"""

    async def shutdown(self):
        loop = asyncio.get_running_loop()
        async with self._lock:
            while self.containers:
                container = self.containers.pop(0)
                try:
                    print(f"  [Sandbox] Cleaning up container: {container.short_id}")
                    await loop.run_in_executor(self.executor, container.kill)
                    await loop.run_in_executor(self.executor, container.remove)
                except Exception:
                    pass
        self.executor.shutdown(wait=False)


SANDBOX_RUNNER = SandboxProcessRunner()


def _generate_id() -> str:
    return uuid.uuid4().hex[:16]


@router.post("/run")
async def run_code(
    payload: dict[str, Any],
) -> dict[str, Any]:
    code = str(payload.get("code", "")).strip()
    language = str(payload.get("language", "python")).strip().lower()
    student_id = str(payload.get("student_id", "default"))

    if not code:
        raise HTTPException(status_code=400, detail="代码不能为空")

    # Syntax validation of code before execution
    if language == "python":
        try:
            compile(code, "<sandbox>", "exec")
        except SyntaxError as e:
            return {
                "exec_id": _generate_id(),
                "output": "",
                "error": f"语法错误: {e}",
                "execution_time_ms": 0,
                "language": language,
            }

        output, error, exec_time = await _execute_python(code)
    else:
        # Currently default to Python sandbox for other languages
        output, error, exec_time = await _execute_python(code)

    exec_id = _generate_id()
    db_exec = DBCodeExecution(
        id=exec_id,
        student_id=student_id,
        code=code[:5000],
        language=language,
        output=output[:10000],
        error=error[:5000] if error else "",
        execution_time_ms=int(exec_time * 1000),
    )
    
    def save_exec(session):
        session.add(db_exec)
        session.commit()
        
    await run_db_op(save_exec)

    return {
        "exec_id": exec_id,
        "output": output,
        "error": error,
        "execution_time_ms": int(exec_time * 1000),
        "language": language,
    }


async def _execute_python(code: str) -> tuple[str, str, float]:
    return await SANDBOX_RUNNER.run(code)


@router.get("/history/{student_id}")
async def get_code_history(
    student_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    def fetch_history(session):
        return (
            session.query(DBCodeExecution)
            .filter(DBCodeExecution.student_id == student_id)
            .order_by(DBCodeExecution.created_at.desc())
            .limit(limit)
            .all()
        )
        
    records = await run_db_op(fetch_history)
    return [
        {
            "id": r.id,
            "code": r.code[:200],
            "language": r.language,
            "output": r.output[:200],
            "execution_time_ms": r.execution_time_ms,
            "has_error": bool(r.error),
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in records
    ]
