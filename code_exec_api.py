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
from config import CONFIG

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

    def _validate_code_ast(self, code: str) -> str | None:
        """使用 AST 静态分析扫描学生代码，拦截反射逃逸、任意代码执行等不安全操作。
        返回 None 表示验证通过，返回错误字符串表示拦截。"""
        import ast
        try:
            tree = ast.parse(code)
        except SyntaxError as se:
            return f"语法错误: {se}"

        # 拦截：任何包含双下划线 '__' 的属性访问、拦截 globals()/locals()/vars()、eval()/exec()、getattr()/setattr()/delattr()
        banned_calls = {"eval", "exec", "globals", "locals", "vars", "getattr", "setattr", "delattr", "open", "compile"}
        high_risk_attrs = {
            "__class__", "__bases__", "__base__", "__mro__", "__subclasses__", 
            "__globals__", "__code__", "__builtins__", "__import__", "__dict__",
            "__getattribute__", "__getattr__", "__setattr__", "__delattr__"
        }
        banned_system_attrs = {"os", "sys", "subprocess", "system", "popen", "spawn", "execute", "sh", "bash"}
        
        for node in ast.walk(tree):
            # 检查属性访问，如 obj.__class__ or obj.os.system or np.os.system
            if isinstance(node, ast.Attribute):
                curr = node
                while isinstance(curr, ast.Attribute):
                    if curr.attr in high_risk_attrs or curr.attr in banned_system_attrs:
                        return f"安全拦截: 禁止访问系统或高危属性/方法 '{curr.attr}'，防止沙箱逃逸。"
                    curr = curr.value
                if isinstance(curr, ast.Name):
                    if curr.id in banned_calls or curr.id in banned_system_attrs:
                        return f"安全拦截: 禁用了内置或高危函数/模块调用 '{curr.id}'。"
            # 检查函数/变量直接调用，如 eval() or getattr() or os
            elif isinstance(node, ast.Name):
                if node.id in banned_calls or node.id in banned_system_attrs:
                    return f"安全拦截: 禁用了内置或高危函数/模块调用 '{node.id}'，防止安全隐患。"
                # 检查直接访问双下划线变量，如 __builtins__
                if node.id in high_risk_attrs:
                    return f"安全拦截: 禁止访问系统内部变量 '{node.id}'。"
            # 检查直接通过下标（Subscript）键值对逃逸，如 vars(re)['__builtins__']
            elif isinstance(node, ast.Subscript):
                slice_node = node.slice
                val = None
                if isinstance(slice_node, ast.Constant):
                    val = slice_node.value
                elif hasattr(slice_node, 'value') and isinstance(slice_node.value, ast.Constant):
                    # 兼容 Python 3.8 Index 包装
                    val = slice_node.value.value
                elif hasattr(slice_node, 'value') and isinstance(slice_node.value, str):
                    val = slice_node.value
                
                if isinstance(val, str):
                    if "__" in val or val in banned_calls or val in banned_system_attrs or val in high_risk_attrs:
                        return f"安全拦截: 禁止通过下标方式访问高危系统属性或函数调用 '{val}'，防止沙箱逃逸。"
        return None

    async def run(self, code: str) -> tuple[str, str, float]:
        # === 任务 14: 代码沙箱大文件 DoS 攻击防御拦截 ===
        MAX_CODE_SIZE = 50000  # 50KB 限制
        code_bytes_len = len(code.encode('utf-8'))
        if code_bytes_len > MAX_CODE_SIZE:
            return "", f"错误: 代码内容过大 ({code_bytes_len} 字节), 超过沙箱限制 ({MAX_CODE_SIZE} 字节)", 0.0

        # AST 安全扫描校验
        validation_error = self._validate_code_ast(code)
        if validation_error:
            return "", validation_error, 0.0

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

        # === 任务 5 & 15: Docker 容器预热池故障自愈 + 超周期僵死防患 ===
        async def check_and_heal_container():
            nonlocal container
            if container is None:
                return False
            try:
                await loop.run_in_executor(self.executor, lambda: container.status)
                inspect = await loop.run_in_executor(self.executor, container.attrs.__getitem__, "State")
                state = inspect.get("Status", "")
                if state in ("dead", "exited", "paused"):
                    print(f"  [Sandbox] Container {container.short_id} is {state}, replacing...")
                    try:
                        await loop.run_in_executor(self.executor, container.remove)
                    except Exception:
                        pass
                    container = await loop.run_in_executor(self.executor, self._create_container)
                    return True
                return True
            except Exception:
                try:
                    container = await loop.run_in_executor(self.executor, self._create_container)
                except Exception:
                    pass
                return container is not None

        healthy = await check_and_heal_container()
        if not healthy or container is None:
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
            exit_code, output = await asyncio.wait_for(execute_in_thread(), timeout=CONFIG.sandbox_timeout)
            output_str = output.decode('utf-8', errors='replace')
            
            if "===STDERR_SEPARATOR===" in output_str:
                stdout, stderr = output_str.split("===STDERR_SEPARATOR===", 1)
            else:
                stdout, stderr = output_str, ""

            # === 任务 15: 容器超周期使用计数，防止僵死 ===
            usage_count = getattr(container, "_sandbox_usage_count", 0) + 1
            container._sandbox_usage_count = usage_count
            MAX_USAGE = 100
            if usage_count >= MAX_USAGE:
                print(f"  [Sandbox] Container {container.short_id} reached max usage ({MAX_USAGE}), recycling...")
                try:
                    await loop.run_in_executor(self.executor, container.kill)
                    await loop.run_in_executor(self.executor, container.remove)
                except Exception:
                    pass
                container = await loop.run_in_executor(self.executor, self._create_container)
                container._sandbox_usage_count = 0

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
            new_container._sandbox_usage_count = 0
            async with self._lock:
                self.containers.append(new_container)

            exec_time = time.time() - start_time
            return "", f"错误: 代码运行超时 (超过 {CONFIG.sandbox_timeout} 秒被强制熔断)", exec_time
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

        import os
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                exec_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=CONFIG.sandbox_timeout
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
                return "", f"错误: 代码运行超时 (超过 {CONFIG.sandbox_timeout} 秒被强制熔断)", exec_time

        except (NotImplementedError, AttributeError):
            # 如果事件循环不支持异步子进程（如 Windows 上的 SelectorEventLoop），
            # 则退回到使用 ThreadPoolExecutor 运行 subprocess.Popen 并强制 kill 僵尸进程
            import subprocess
            loop = asyncio.get_running_loop()

            def run_sync_subprocess():
                proc = None
                try:
                    proc = subprocess.Popen(
                        [sys.executable, "-c", exec_command],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=env
                    )
                    try:
                        stdout_bytes, stderr_bytes = proc.communicate(timeout=CONFIG.sandbox_timeout)
                        return proc.returncode or 0, stdout_bytes, stderr_bytes
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            stdout_bytes, stderr_bytes = proc.communicate(timeout=3)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                            stdout_bytes, stderr_bytes = b"", b"timeout"
                        return -1, b"", b"timeout"
                except Exception:
                    return -1, b"", b"subprocess error"
                finally:
                    if proc is not None:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        try:
                            proc.wait(timeout=3)
                        except Exception:
                            pass

            try:
                ret_code, stdout_bytes, stderr_bytes = await loop.run_in_executor(
                    self.executor,
                    run_sync_subprocess
                )
                if ret_code == -1 and stderr_bytes == b"timeout":
                    exec_time = time.time() - start_time
                    return "", f"错误: 代码运行超时 (超过 {CONFIG.sandbox_timeout} 秒被强制熔断)", exec_time

                stdout = stdout_bytes.decode('utf-8', errors='replace')
                stderr = stderr_bytes.decode('utf-8', errors='replace')

                if "===STDERR_SEPARATOR===" in stdout:
                    part_out, part_err = stdout.split("===STDERR_SEPARATOR===", 1)
                    stdout = part_out
                    stderr = part_err + stderr

                exec_time = time.time() - start_time
                return stdout, stderr, exec_time
            except Exception as e:
                exec_time = time.time() - start_time
                return "", f"沙箱子进程启动失败 (线程池退路): {e}", exec_time

        except Exception as e:
            exec_time = time.time() - start_time
            return "", f"沙箱子进程启动失败: {e}", exec_time

    def _get_wrapper_script(self) -> str:
        return """
import sys
import io
import traceback
import builtins
from contextlib import redirect_stdout, redirect_stderr

code_to_run = sys.stdin.read()

output_buffer = io.StringIO()
error_buffer = io.StringIO()

def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    allowed = {
        "math", "json", "random", "statistics", "collections", "itertools",
        "datetime", "re", "numpy", "pandas", "matplotlib", "sklearn",
        "torch", "nn", "np", "pd", "plt", "time"
    }
    root_name = name.split('.')[0]
    if root_name not in allowed:
        raise ImportError(f"安全沙箱禁用了模块: {name}")
    return builtins.__import__(name, globals, locals, fromlist, level)

restricted_globals = {
    "__name__": "__main__",
    "__doc__": None,
    "__package__": None,
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
        "__import__": safe_import,
        "__build_class__": builtins.__build_class__,
        "super": builtins.super,
        "callable": builtins.callable,
        "hash": builtins.hash,
        "setattr": builtins.setattr,
        "getattr": builtins.getattr,
        "hasattr": builtins.hasattr,
        "delattr": builtins.delattr,
        "iter": builtins.iter,
        "classmethod": builtins.classmethod,
        "staticmethod": builtins.staticmethod,
        "property": builtins.property,
    }
}

safe_modules = {}
for mod_name in ("math", "json", "random", "statistics", "collections", "itertools", "datetime", "re"):
    try:
        safe_modules[mod_name] = __import__(mod_name)
    except ImportError:
        pass
restricted_globals.update(safe_modules)

for extra in ("numpy", "np", "pandas", "pd", "matplotlib", "plt", "sklearn", "torch", "nn"):
    if extra in code_to_run:
        try:
            if extra == "matplotlib":
                import matplotlib
                matplotlib.use("Agg")
                matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', 'sans-serif']
                matplotlib.rcParams['axes.unicode_minus'] = False
                restricted_globals["matplotlib"] = matplotlib
            elif extra == "plt":
                import matplotlib.pyplot as plt
                plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', 'sans-serif']
                plt.rcParams['axes.unicode_minus'] = False
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
            elif extra == "torch":
                import torch
                restricted_globals["torch"] = torch
            elif extra == "nn":
                import torch.nn as nn
                restricted_globals["nn"] = nn
        except ImportError:
            pass

try:
    import warnings
    warnings.filterwarnings("ignore")
    import logging
    logging.getLogger("matplotlib").setLevel(logging.ERROR)
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
            # === 任务 3: Matplotlib 画布内存泄露强杀 ===
            import sys, gc
            for mod_name in list(sys.modules.keys()):
                if mod_name.startswith("matplotlib") or "agg" in mod_name.lower() or "backend" in mod_name.lower() and "matplotlib" in mod_name.lower():
                    sys.modules.pop(mod_name, None)
            gc.collect()
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

    # === 任务 14: 代码沙箱大文件 DoS 攻击防御拦截 (FastAPI 前置拦截) ===
    if len(code.encode('utf-8')) > 50000:
        raise HTTPException(status_code=400, detail="恶意代码长度超限，沙箱拒绝运行 (Max 50KB)")

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