"""Formal code-sandbox resources, real local runs, and explicit evidence submission."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from config import CONFIG
from app.database import DBArtifact, DBArtifactVersion, DBLearningEvent, DBUser, run_db_op
from app.m1_repository import add_artifact_version
from app.m2_contracts import StrictModel
from app.schemas import ContextRef
from app.m5_learning import LearningEventInput, process_path_event, record_learning_event
from app.m5_resources import (
    CodeSandboxContent,
    CodeSandboxRequiredCheck,
    canonical_resource_type,
    parse_code_sandbox_content,
    resource_detail,
)


RUN_ARTIFACT_TYPE = "code_sandbox_run"
RUN_SCHEMA_VERSION = "f6.code-sandbox-run.v1"
RUN_STATUSES = ("queued", "running", "stopped", "success", "runtime_error", "timeout")
FINAL_RUN_STATUSES = frozenset({"stopped", "success", "runtime_error", "timeout"})
_DATA_IMAGE = re.compile(r"data:image/png;base64,([A-Za-z0-9+/=]+)")
_COMPLETE_OUTPUT_STORAGE_CAP = 1_000_000


class CodeSandboxError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise CodeSandboxError(code, message)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{hashlib.sha256(chr(31).join(parts).encode()).hexdigest()[:32]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class OutputCapture(StrictModel):
    totalBytes: int = Field(ge=0)
    capturedBytes: int = Field(ge=0)
    limitBytes: int = Field(ge=1)
    omittedBytes: int = Field(ge=0)
    truncated: bool


class CompleteOutput(StrictModel):
    text: str = ""
    capture: OutputCapture
    available: bool = False
    reason: str = ""


class CodeSandboxPlot(StrictModel):
    id: str
    title: str
    dataUrl: str
    bytes: int = Field(ge=1)


class CodeSandboxCheckResult(StrictModel):
    id: str
    label: str
    kind: str
    passed: bool
    detail: str


class CodeSandboxRunState(StrictModel):
    schemaVersion: Literal["f6.code-sandbox-run.v1"] = RUN_SCHEMA_VERSION
    runAttemptId: str
    ownerPublicId: str
    sourceResourceId: str
    sourceResourceVersionId: str
    courseId: str | None = None
    knowledgePointId: str | None = None
    entryFile: str
    language: Literal["python"] = "python"
    runtimeMode: Literal["trusted_local"] = "trusted_local"
    runtimeBoundary: str
    timeoutSeconds: int = Field(ge=1, le=60)
    code: str = Field(min_length=1, max_length=50_000)
    codeSha256: str
    standardInput: str = Field(default="", max_length=20_000)
    requiredChecks: tuple[CodeSandboxRequiredCheck, ...]
    status: Literal["queued", "running", "stopped", "success", "runtime_error", "timeout"]
    createdAt: str
    startedAt: str | None = None
    completedAt: str | None = None
    executionTimeMs: int = Field(default=0, ge=0)
    exitCode: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdoutCapture: OutputCapture | None = None
    stderrCapture: OutputCapture | None = None
    stdoutComplete: CompleteOutput | None = None
    stderrComplete: CompleteOutput | None = None
    plots: tuple[CodeSandboxPlot, ...] = ()
    plotError: str = ""
    checks: tuple[CodeSandboxCheckResult, ...] = ()
    passedCount: int = Field(default=0, ge=0)
    totalCount: int = Field(default=0, ge=0)
    stopReason: str = ""
    errorCode: str = ""


class ExecutionResult(StrictModel):
    status: Literal["stopped", "success", "runtime_error", "timeout"]
    executionTimeMs: int = Field(ge=0)
    exitCode: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdoutCapture: OutputCapture
    stderrCapture: OutputCapture
    stdoutComplete: CompleteOutput | None = None
    stderrComplete: CompleteOutput | None = None
    plots: tuple[CodeSandboxPlot, ...] = ()
    plotError: str = ""
    stopReason: str = ""
    errorCode: str = ""


_WRAPPER = r'''
import base64
import builtins
import io
import json
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout

payload_path, result_path = sys.argv[1], sys.argv[2]
with open(payload_path, "r", encoding="utf-8") as handle:
    payload = json.load(handle)

class BoundedText(io.TextIOBase):
    def __init__(self, limit, complete_limit):
        self.limit = max(1024, int(limit))
        self.head_limit = max(512, self.limit * 2 // 3)
        self.tail_limit = self.limit - self.head_limit
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0
        self.complete_limit = max(self.limit, int(complete_limit))
        self.complete_head_limit = max(512, self.complete_limit * 2 // 3)
        self.complete_tail_limit = self.complete_limit - self.complete_head_limit
        self.complete_head = bytearray()
        self.complete_tail = bytearray()
        self.complete_total = 0

    @staticmethod
    def _append_bounded(data, head, tail, head_limit, tail_limit):
        head_room = head_limit - len(head)
        if head_room > 0:
            head.extend(data[:head_room])
            data = data[head_room:]
        if data and tail_limit > 0:
            tail.extend(data)
            if len(tail) > tail_limit:
                del tail[:-tail_limit]

    def write(self, value):
        data = str(value).encode("utf-8", errors="replace")
        self.total += len(data)
        self._append_bounded(data, self.head, self.tail, self.head_limit, self.tail_limit)
        self.complete_total += len(data)
        self._append_bounded(
            data,
            self.complete_head,
            self.complete_tail,
            self.complete_head_limit,
            self.complete_tail_limit,
        )
        return len(value)

    def flush(self):
        return None

    def export(self):
        captured = len(self.head) + len(self.tail)
        omitted = max(0, self.total - captured)
        if omitted:
            marker = f"\n\n[中间输出已省略 {omitted} 字节；以下保留末尾结果]\n\n".encode("utf-8")
            value = bytes(self.head) + marker + bytes(self.tail)
        else:
            value = bytes(self.head) + bytes(self.tail)
        return value.decode("utf-8", errors="replace"), {
            "totalBytes": self.total,
            "capturedBytes": captured,
            "limitBytes": self.limit,
            "omittedBytes": omitted,
            "truncated": omitted > 0,
        }

    def export_complete(self):
        captured = len(self.complete_head) + len(self.complete_tail)
        omitted = max(0, self.complete_total - captured)
        if omitted:
            marker = f"\n\n[完整结果存储上限已达到，仍省略 {omitted} 字节；以下保留开头和末尾]\n\n".encode("utf-8")
            value = bytes(self.complete_head) + marker + bytes(self.complete_tail)
        else:
            value = bytes(self.complete_head) + bytes(self.complete_tail)
        return value.decode("utf-8", errors="replace"), {
            "totalBytes": self.complete_total,
            "capturedBytes": captured,
            "limitBytes": self.complete_limit,
            "omittedBytes": omitted,
            "truncated": omitted > 0,
        }

allowed_modules = {
    "math", "json", "random", "statistics", "collections", "itertools",
    "datetime", "re", "time", "numpy", "pandas", "matplotlib", "sklearn",
    "torch", "mpl_toolkits",
}

def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if root not in allowed_modules:
        raise ImportError(f"本地研究模式禁用了模块: {name}")
    return builtins.__import__(name, globals, locals, fromlist, level)

safe_builtins = {
    "abs": abs, "all": all, "any": any, "bool": bool, "callable": callable,
    "classmethod": classmethod, "dict": dict, "dir": dir, "enumerate": enumerate,
    "Exception": Exception, "float": float, "format": format, "frozenset": frozenset,
    "hasattr": hasattr, "hash": hash, "help": help, "hex": hex, "id": id,
    "ImportError": ImportError, "IndexError": IndexError, "input": input, "int": int,
    "isinstance": isinstance, "issubclass": issubclass, "iter": iter, "KeyError": KeyError,
    "len": len, "list": list, "map": map, "max": max, "min": min, "next": next,
    "object": object, "oct": oct, "ord": ord, "pow": pow, "print": print,
    "property": property, "range": range, "repr": repr, "reversed": reversed,
    "round": round, "RuntimeError": RuntimeError, "set": set, "slice": slice,
    "sorted": sorted, "staticmethod": staticmethod, "StopIteration": StopIteration,
    "str": str, "sum": sum, "super": super, "tuple": tuple, "TypeError": TypeError,
    "ValueError": ValueError, "ZeroDivisionError": ZeroDivisionError, "zip": zip,
    "__build_class__": builtins.__build_class__, "__import__": safe_import,
}

stdout_buffer = BoundedText(payload["maxOutputBytes"], payload["completeOutputBytes"])
stderr_buffer = BoundedText(payload["maxOutputBytes"], payload["completeOutputBytes"])
plots = []
plot_error = ""
runtime_error = False
os.environ["MPLBACKEND"] = "Agg"
sys.stdin = io.StringIO(payload.get("standardInput", ""))
scope = {"__name__": "__main__", "__package__": None, "__builtins__": safe_builtins}

try:
    compiled = compile(payload["code"], payload.get("entryFile", "main.py"), "exec")
    with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
        exec(compiled, scope)
except Exception:
    runtime_error = True
    stderr_buffer.write(traceback.format_exc())

try:
    if "matplotlib.pyplot" in sys.modules:
        import matplotlib.pyplot as plt
        total_visual = 0
        for index, number in enumerate(plt.get_fignums()[:4], start=1):
            buffer = io.BytesIO()
            plt.figure(number).savefig(buffer, format="png", dpi=110, bbox_inches="tight")
            data = buffer.getvalue()
            if total_visual + len(data) > int(payload["maxVisualBytes"]):
                plot_error = "图表超过本地研究模式的可视化上限，文本结果仍已保留。"
                break
            total_visual += len(data)
            plots.append({
                "id": f"plot-{index}",
                "title": f"运行图表 {index}",
                "dataUrl": "data:image/png;base64," + base64.b64encode(data).decode("ascii"),
                "bytes": len(data),
            })
        plt.close("all")
except Exception:
    plot_error = "图表捕获失败：" + traceback.format_exc(limit=1).strip()

stdout, stdout_meta = stdout_buffer.export()
stdout_complete, stdout_complete_meta = stdout_buffer.export_complete()
stderr, stderr_meta = stderr_buffer.export()
stderr_complete, stderr_complete_meta = stderr_buffer.export_complete()
result = {
    "runtimeError": runtime_error,
    "stdout": stdout,
    "stderr": stderr,
    "stdoutCapture": stdout_meta,
    "stderrCapture": stderr_meta,
    "stdoutComplete": stdout_complete,
    "stderrComplete": stderr_complete,
    "stdoutCompleteCapture": stdout_complete_meta,
    "stderrCompleteCapture": stderr_complete_meta,
    "plots": plots,
    "plotError": plot_error,
}
with open(result_path, "w", encoding="utf-8") as handle:
    json.dump(result, handle, ensure_ascii=False)
'''


def validate_code(code: str) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"语法错误: {exc}"
    allowed_modules = {
        "math", "json", "random", "statistics", "collections", "itertools",
        "datetime", "re", "time", "numpy", "pandas", "matplotlib", "sklearn",
        "torch", "mpl_toolkits",
    }
    banned_names = {
        "eval", "exec", "compile", "open", "globals", "locals", "vars", "getattr",
        "setattr", "delattr", "breakpoint", "__import__", "os", "sys", "subprocess",
        "socket", "pathlib", "shutil", "multiprocessing", "requests", "httpx", "urllib",
    }
    banned_attributes = {"system", "popen", "spawn", "fork", "kill", "remove", "unlink", "rmdir"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                if name.split(".")[0] not in allowed_modules:
                    return f"本地研究模式禁用了模块: {name}"
        elif isinstance(node, ast.Name) and node.id in banned_names:
            return f"本地研究模式禁用了高风险名称: {node.id}"
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") or node.attr in banned_attributes:
                return f"本地研究模式禁用了高风险属性: {node.attr}"
    return None


def _empty_capture(limit: int) -> OutputCapture:
    return OutputCapture(totalBytes=0, capturedBytes=0, limitBytes=limit, omittedBytes=0, truncated=False)


def _complete_output(text: str, capture: OutputCapture, *, reason: str = "") -> CompleteOutput:
    return CompleteOutput(
        text=text,
        capture=capture,
        available=not capture.truncated,
        reason=reason or ("完整结果超过受控存储上限。" if capture.truncated else ""),
    )


def _complete_output_limit(preview_limit: int) -> int:
    """Keep full-result persistence bounded without changing execution limits."""
    return min(_COMPLETE_OUTPUT_STORAGE_CAP, max(int(preview_limit), int(preview_limit) * 8))


class LocalPythonExecutor:
    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._stop_requests: set[str] = set()
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return CONFIG.sandbox_mode == "trusted_local" and os.getenv(
            "EDUMATRIX_ENV", "development"
        ).strip().lower() not in {"production", "prod"}

    def status(self) -> dict[str, Any]:
        return {
            "schemaVersion": "f6.code-sandbox-runtime.v1",
            "mode": "trusted_local" if self.enabled else "disabled",
            "executionEnabled": self.enabled,
            "isolation": "trusted_local_child_process" if self.enabled else "none",
            "securityLevel": "research_only_no_container_isolation" if self.enabled else "execution_disabled",
            "message": (
                "本地研究模式已启用：代码在受限 Python 子进程和临时目录中运行，不具备 Docker 容器隔离。"
                if self.enabled else
                "代码执行未启用；设置 EDUMATRIX_SANDBOX_MODE=trusted_local 后可运行团队预置课程示例。"
            ),
            "timeoutSeconds": int(CONFIG.sandbox_timeout),
            "maxOutputBytes": int(CONFIG.sandbox_max_output_bytes),
            "maxVisualBytes": int(CONFIG.sandbox_max_visual_bytes),
            "pythonExecutable": sys.executable,
        }

    async def execute(self, state: CodeSandboxRunState) -> ExecutionResult:
        started = asyncio.get_running_loop().time()
        validation_error = validate_code(state.code)
        if validation_error:
            capture = _empty_capture(int(CONFIG.sandbox_max_output_bytes))
            return ExecutionResult(
                status="runtime_error",
                executionTimeMs=0,
                exitCode=1,
                stderr=validation_error,
                stdoutCapture=capture,
                stderrCapture=OutputCapture(
                    totalBytes=len(validation_error.encode("utf-8")),
                    capturedBytes=len(validation_error.encode("utf-8")),
                    limitBytes=int(CONFIG.sandbox_max_output_bytes),
                    omittedBytes=0,
                    truncated=False,
                ),
                stdoutComplete=_complete_output("", capture),
                stderrComplete=_complete_output(validation_error, OutputCapture(
                    totalBytes=len(validation_error.encode("utf-8")),
                    capturedBytes=len(validation_error.encode("utf-8")),
                    limitBytes=_complete_output_limit(int(CONFIG.sandbox_max_output_bytes)),
                    omittedBytes=0,
                    truncated=False,
                )),
                errorCode="code_validation_failed",
            )
        workdir = Path(tempfile.mkdtemp(prefix="edumatrix_code_run_"))
        payload_path = workdir / "payload.json"
        result_path = workdir / "result.json"
        wrapper_path = workdir / "runner.py"
        payload_path.write_text(_canonical({
            "code": state.code,
            "entryFile": state.entryFile,
            "standardInput": state.standardInput,
            "maxOutputBytes": int(CONFIG.sandbox_max_output_bytes),
            "completeOutputBytes": _complete_output_limit(int(CONFIG.sandbox_max_output_bytes)),
            "maxVisualBytes": int(CONFIG.sandbox_max_visual_bytes),
        }), encoding="utf-8")
        wrapper_path.write_text(_WRAPPER, encoding="utf-8")
        secret_markers = ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "DATABASE_URL", "COOKIE", "CREDENTIAL")
        env = {
            key: value for key, value in os.environ.items()
            if not any(marker in key.upper() for marker in secret_markers)
        }
        env.pop("PYTHONPATH", None)
        env["PYTHONIOENCODING"] = "utf-8"
        env["MPLBACKEND"] = "Agg"
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(wrapper_path),
                str(payload_path),
                str(result_path),
                cwd=str(workdir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **kwargs,
            )
            async with self._lock:
                self._processes[state.runAttemptId] = process
                stop_requested = state.runAttemptId in self._stop_requests
            if stop_requested:
                await self._terminate(process)
            try:
                wrapper_stdout, wrapper_stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=min(float(state.timeoutSeconds), float(CONFIG.sandbox_timeout)),
                )
            except asyncio.TimeoutError:
                await self._terminate(process)
                await process.wait()
                elapsed = int((asyncio.get_running_loop().time() - started) * 1000)
                capture = _empty_capture(int(CONFIG.sandbox_max_output_bytes))
                return ExecutionResult(
                    status="timeout",
                    executionTimeMs=elapsed,
                    exitCode=None,
                    stderr=f"代码运行超时：超过 {min(state.timeoutSeconds, int(CONFIG.sandbox_timeout))} 秒，进程树已清理。",
                    stdoutCapture=capture,
                    stderrCapture=capture,
                    stdoutComplete=_complete_output("", capture),
                    stderrComplete=_complete_output(
                        f"代码运行超时：超过 {min(state.timeoutSeconds, int(CONFIG.sandbox_timeout))} 秒，进程树已清理。",
                        OutputCapture(
                            totalBytes=len(f"代码运行超时：超过 {min(state.timeoutSeconds, int(CONFIG.sandbox_timeout))} 秒，进程树已清理。".encode("utf-8")),
                            capturedBytes=len(f"代码运行超时：超过 {min(state.timeoutSeconds, int(CONFIG.sandbox_timeout))} 秒，进程树已清理。".encode("utf-8")),
                            limitBytes=_complete_output_limit(int(CONFIG.sandbox_max_output_bytes)),
                            omittedBytes=0,
                            truncated=False,
                        ),
                    ),
                    stopReason="timeout",
                    errorCode="code_run_timeout",
                )
            async with self._lock:
                stopped = state.runAttemptId in self._stop_requests
            elapsed = int((asyncio.get_running_loop().time() - started) * 1000)
            if stopped:
                capture = _empty_capture(int(CONFIG.sandbox_max_output_bytes))
                return ExecutionResult(
                    status="stopped",
                    executionTimeMs=elapsed,
                    exitCode=process.returncode,
                    stderr="运行已由用户停止，主进程与子进程树已清理。",
                    stdoutCapture=capture,
                    stderrCapture=capture,
                    stdoutComplete=_complete_output("", capture),
                    stderrComplete=_complete_output(
                        "运行已由用户停止，主进程与子进程树已清理。",
                        OutputCapture(
                            totalBytes=len("运行已由用户停止，主进程与子进程树已清理。".encode("utf-8")),
                            capturedBytes=len("运行已由用户停止，主进程与子进程树已清理。".encode("utf-8")),
                            limitBytes=_complete_output_limit(int(CONFIG.sandbox_max_output_bytes)),
                            omittedBytes=0,
                            truncated=False,
                        ),
                    ),
                    stopReason="user_requested",
                    errorCode="code_run_stopped",
                )
            if not result_path.is_file():
                message = wrapper_stderr.decode("utf-8", errors="replace") or wrapper_stdout.decode("utf-8", errors="replace")
                message = message.strip() or "代码运行器没有生成结果文件。"
                capture = _empty_capture(int(CONFIG.sandbox_max_output_bytes))
                return ExecutionResult(
                    status="runtime_error",
                    executionTimeMs=elapsed,
                    exitCode=process.returncode,
                    stderr=message,
                    stdoutCapture=capture,
                    stderrCapture=OutputCapture(
                        totalBytes=len(message.encode("utf-8")),
                        capturedBytes=min(len(message.encode("utf-8")), int(CONFIG.sandbox_max_output_bytes)),
                        limitBytes=int(CONFIG.sandbox_max_output_bytes),
                        omittedBytes=max(0, len(message.encode("utf-8")) - int(CONFIG.sandbox_max_output_bytes)),
                        truncated=len(message.encode("utf-8")) > int(CONFIG.sandbox_max_output_bytes),
                    ),
                    stdoutComplete=_complete_output("", capture),
                    stderrComplete=_complete_output(
                        message,
                        OutputCapture(
                            totalBytes=len(message.encode("utf-8")),
                            capturedBytes=len(message.encode("utf-8")),
                            limitBytes=_complete_output_limit(int(CONFIG.sandbox_max_output_bytes)),
                            omittedBytes=0,
                            truncated=False,
                        ),
                    ),
                    errorCode="code_runner_failed",
                )
            result = json.loads(result_path.read_text(encoding="utf-8"))
            status = "runtime_error" if result.get("runtimeError") or process.returncode not in {0, None} else "success"
            return ExecutionResult(
                status=status,
                executionTimeMs=elapsed,
                exitCode=1 if result.get("runtimeError") else int(process.returncode or 0),
                stdout=str(result.get("stdout") or ""),
                stderr=str(result.get("stderr") or ""),
                stdoutCapture=OutputCapture.model_validate(result.get("stdoutCapture") or {}),
                stderrCapture=OutputCapture.model_validate(result.get("stderrCapture") or {}),
                stdoutComplete=_complete_output(
                    str(result.get("stdoutComplete") or ""),
                    OutputCapture.model_validate(result.get("stdoutCompleteCapture") or {}),
                ),
                stderrComplete=_complete_output(
                    str(result.get("stderrComplete") or ""),
                    OutputCapture.model_validate(result.get("stderrCompleteCapture") or {}),
                ),
                plots=tuple(CodeSandboxPlot.model_validate(item) for item in result.get("plots") or []),
                plotError=str(result.get("plotError") or ""),
                errorCode="code_runtime_error" if status == "runtime_error" else "",
            )
        except (NotImplementedError, OSError) as exc:
            elapsed = int((asyncio.get_running_loop().time() - started) * 1000)
            message = f"本机事件循环无法启动受限子进程：{exc}"
            capture = _empty_capture(int(CONFIG.sandbox_max_output_bytes))
            return ExecutionResult(
                status="runtime_error",
                executionTimeMs=elapsed,
                exitCode=None,
                stderr=message,
                stdoutCapture=capture,
                stderrCapture=OutputCapture(
                    totalBytes=len(message.encode("utf-8")),
                    capturedBytes=len(message.encode("utf-8")),
                    limitBytes=int(CONFIG.sandbox_max_output_bytes),
                    omittedBytes=0,
                    truncated=False,
                ),
                stdoutComplete=_complete_output("", capture),
                stderrComplete=_complete_output(
                    message,
                    OutputCapture(
                        totalBytes=len(message.encode("utf-8")),
                        capturedBytes=len(message.encode("utf-8")),
                        limitBytes=_complete_output_limit(int(CONFIG.sandbox_max_output_bytes)),
                        omittedBytes=0,
                        truncated=False,
                    ),
                ),
                errorCode="code_process_unavailable",
            )
        finally:
            async with self._lock:
                self._processes.pop(state.runAttemptId, None)
                self._stop_requests.discard(state.runAttemptId)
            shutil.rmtree(workdir, ignore_errors=True)

    async def stop(self, run_id: str) -> bool:
        async with self._lock:
            self._stop_requests.add(run_id)
            process = self._processes.get(run_id)
        if process is not None and process.returncode is None:
            await self._terminate(process)
        return True

    async def shutdown(self) -> None:
        async with self._lock:
            items = list(self._processes.items())
            self._stop_requests.update(run_id for run_id, _ in items)
        await asyncio.gather(*(self._terminate(process) for _, process in items), return_exceptions=True)

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            await asyncio.to_thread(
                subprocess.run,
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


def _owned_resource(db: Any, resource_id: str, owner: str) -> tuple[DBArtifact, DBArtifactVersion, CodeSandboxContent]:
    artifact = db.get(DBArtifact, resource_id)
    if artifact is None:
        _fail("code_sandbox_resource_unknown", "代码沙盒资源不存在或已经不可用。")
    if artifact.owner_public_id != owner:
        _fail("code_sandbox_resource_forbidden", "该代码沙盒资源属于其他用户。")
    version = db.get(DBArtifactVersion, artifact.current_version_id) if artifact.current_version_id else None
    metadata = dict(version.metadata_json or {}) if version else {}
    if version is None or canonical_resource_type(artifact.artifact_type, metadata) != "code_sandbox":
        _fail("code_sandbox_resource_type_invalid", "当前资源不是代码沙盒。")
    if version.content_format != "json":
        _fail("code_sandbox_resource_legacy", "旧版代码说明只能阅读，不能运行。")
    content = parse_code_sandbox_content(version.content)
    detail = resource_detail(db, artifact)
    readiness = ((detail.get("code_sandbox") or {}).get("current") or {}).get("source_readiness") or {}
    if readiness.get("publishable") is not True:
        _fail("code_sandbox_resource_unavailable", str(readiness.get("reason") or "代码沙盒来源不可用。"))
    return artifact, version, content


def _owned_run(db: Any, run_id: str, owner: str) -> tuple[DBArtifact, DBArtifactVersion, CodeSandboxRunState]:
    artifact = db.get(DBArtifact, run_id)
    if artifact is None or artifact.artifact_type != RUN_ARTIFACT_TYPE:
        _fail("code_sandbox_run_unknown", "运行记录不存在或已经不可用。")
    if artifact.owner_public_id != owner:
        _fail("code_sandbox_run_forbidden", "该运行记录属于其他用户。")
    version = db.get(DBArtifactVersion, artifact.current_version_id)
    return artifact, version, CodeSandboxRunState.model_validate_json(version.content)


def _append_state(db: Any, artifact: DBArtifact, state: CodeSandboxRunState, *, action: str) -> DBArtifactVersion:
    version = add_artifact_version(
        db,
        artifact=artifact,
        content=_canonical(state.model_dump(mode="json")),
        content_format="json",
        created_by_public_id=state.ownerPublicId,
        metadata={
            "source_resource_id": state.sourceResourceId,
            "source_resource_version_id": state.sourceResourceVersionId,
            "run_attempt_id": state.runAttemptId,
            "status": state.status,
            "action": action,
            "stdout_preview_truncated": bool(state.stdoutCapture and state.stdoutCapture.truncated),
            "stderr_preview_truncated": bool(state.stderrCapture and state.stderrCapture.truncated),
            "stdout_complete_available": bool(state.stdoutComplete and state.stdoutComplete.available),
            "stderr_complete_available": bool(state.stderrComplete and state.stderrComplete.available),
        },
    )
    artifact.status = "approved" if state.status in FINAL_RUN_STATUSES else "draft"
    return version


def prepare_run(
    db: Any,
    *,
    owner: str,
    resource_id: str,
    resource_version_id: str,
    code: str,
    standard_input: str,
    idempotency_key: str,
) -> tuple[CodeSandboxRunState, bool]:
    artifact, version, content = _owned_resource(db, resource_id, owner)
    if version.id != resource_version_id:
        _fail("code_sandbox_resource_version_stale", "请先刷新代码沙盒，再运行当前版本。")
    code = code.rstrip()
    if not code:
        _fail("code_sandbox_code_required", "代码不能为空。")
    if len(code.encode("utf-8")) > 50_000:
        _fail("code_sandbox_code_too_large", "代码超过 50000 字节的本地研究模式上限。")
    if len(standard_input) > 20_000:
        _fail("code_sandbox_input_too_large", "标准输入超过 20000 字符的上限。")
    request = {
        "resource_id": resource_id,
        "resource_version_id": resource_version_id,
        "code": code,
        "standard_input": standard_input,
    }
    request_hash = _digest(request)
    run_id = _stable_id("run", owner, resource_id, idempotency_key)
    existing = db.get(DBArtifact, run_id)
    if existing is not None:
        existing_version = db.query(DBArtifactVersion).filter_by(artifact_id=run_id, version_number=1).one()
        if (existing_version.metadata_json or {}).get("create_request_sha256") != request_hash:
            _fail("code_sandbox_run_idempotency_conflict", "运行幂等键已经绑定到其他代码或输入。")
        _, _, state = _owned_run(db, run_id, owner)
        return state, False
    state = CodeSandboxRunState(
        runAttemptId=run_id,
        ownerPublicId=owner,
        sourceResourceId=artifact.id,
        sourceResourceVersionId=version.id,
        courseId=artifact.course_id,
        knowledgePointId=(version.metadata_json or {}).get("knowledge_point_id"),
        entryFile=content.entryFile,
        runtimeBoundary=content.runtime.boundary,
        timeoutSeconds=min(content.runtime.timeoutSeconds, max(1, int(CONFIG.sandbox_timeout))),
        code=code,
        codeSha256=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        standardInput=standard_input,
        requiredChecks=tuple(content.requiredChecks),
        status="queued",
        createdAt=_now(),
        totalCount=len(content.requiredChecks),
    )
    run_artifact = DBArtifact(
        id=run_id,
        owner_public_id=owner,
        course_id=artifact.course_id,
        artifact_type=RUN_ARTIFACT_TYPE,
        title=f"{artifact.title} · 运行记录",
        status="draft",
    )
    db.add(run_artifact)
    db.flush()
    created_version = _append_state(db, run_artifact, state, action="queued")
    metadata = dict(created_version.metadata_json or {})
    metadata["create_request_sha256"] = request_hash
    created_version.metadata_json = metadata
    return state, True


def mark_run_running(db: Any, run_id: str) -> CodeSandboxRunState:
    artifact = db.get(DBArtifact, run_id)
    if artifact is None:
        _fail("code_sandbox_run_unknown", "运行记录不存在。")
    version = db.get(DBArtifactVersion, artifact.current_version_id)
    state = CodeSandboxRunState.model_validate_json(version.content)
    if state.status != "queued":
        return state
    next_state = state.model_copy(update={"status": "running", "startedAt": _now()})
    _append_state(db, artifact, next_state, action="running")
    return next_state


def _check_result(check: CodeSandboxRequiredCheck, result: ExecutionResult) -> CodeSandboxCheckResult:
    if check.kind == "exit_code_zero":
        passed = result.status == "success" and result.exitCode == 0
        detail = "程序正常结束。" if passed else "程序未正常结束。"
    elif check.kind == "stdout_contains":
        passed = bool(check.expectedText and check.expectedText in result.stdout)
        detail = f"标准输出{'包含' if passed else '缺少'} {check.expectedText!r}。"
    elif check.kind == "stderr_empty":
        passed = not result.stderr.strip()
        detail = "没有错误输出。" if passed else "仍存在错误输出。"
    else:
        minimum = int(check.minimum or 1)
        passed = len(result.plots) >= minimum
        detail = f"已生成 {len(result.plots)} 张图表，要求至少 {minimum} 张。"
    return CodeSandboxCheckResult(
        id=check.id,
        label=check.label,
        kind=check.kind,
        passed=passed,
        detail=detail,
    )


def finalize_run(db: Any, run_id: str, result: ExecutionResult) -> CodeSandboxRunState:
    artifact = db.get(DBArtifact, run_id)
    if artifact is None:
        _fail("code_sandbox_run_unknown", "运行记录不存在。")
    version = db.get(DBArtifactVersion, artifact.current_version_id)
    state = CodeSandboxRunState.model_validate_json(version.content)
    if state.status in FINAL_RUN_STATUSES:
        return state
    checks = tuple(_check_result(check, result) for check in state.requiredChecks)
    next_state = state.model_copy(update={
        "status": result.status,
        "completedAt": _now(),
        "executionTimeMs": result.executionTimeMs,
        "exitCode": result.exitCode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "stdoutCapture": result.stdoutCapture,
        "stderrCapture": result.stderrCapture,
        "stdoutComplete": result.stdoutComplete,
        "stderrComplete": result.stderrComplete,
        "plots": result.plots,
        "plotError": result.plotError,
        "checks": checks,
        "passedCount": sum(item.passed for item in checks),
        "totalCount": len(checks),
        "stopReason": result.stopReason,
        "errorCode": result.errorCode,
    })
    _append_state(db, artifact, next_state, action=result.status)
    return next_state


def get_run(db: Any, *, owner: str, run_id: str, include_complete: bool = False) -> dict[str, Any]:
    _, version, state = _owned_run(db, run_id, owner)
    payload = state.model_dump(mode="json")
    if not include_complete:
        for key in ("stdoutComplete", "stderrComplete"):
            complete = payload.get(key)
            if complete:
                complete["text"] = ""
    payload["completeOutputIncluded"] = include_complete
    return {**payload, "versionId": version.id, "versionNumber": version.version_number}


def list_runs(db: Any, *, owner: str, resource_id: str, limit: int = 20) -> list[dict[str, Any]]:
    artifacts = db.query(DBArtifact).filter_by(
        owner_public_id=owner,
        artifact_type=RUN_ARTIFACT_TYPE,
    ).order_by(DBArtifact.created_at.desc()).all()
    output: list[dict[str, Any]] = []
    for artifact in artifacts:
        version = db.get(DBArtifactVersion, artifact.current_version_id)
        state = CodeSandboxRunState.model_validate_json(version.content)
        if state.sourceResourceId != resource_id:
            continue
        output.append({
            "runAttemptId": state.runAttemptId,
            "sourceResourceVersionId": state.sourceResourceVersionId,
            "status": state.status,
            "createdAt": state.createdAt,
            "completedAt": state.completedAt,
            "executionTimeMs": state.executionTimeMs,
            "passedCount": state.passedCount,
            "totalCount": state.totalCount,
            "codeSha256": state.codeSha256,
            "hasStdout": bool(state.stdout),
            "hasStderr": bool(state.stderr),
            "stdoutTruncated": bool(state.stdoutCapture and state.stdoutCapture.truncated),
            "stderrTruncated": bool(state.stderrCapture and state.stderrCapture.truncated),
            "stdoutCompleteAvailable": bool(state.stdoutComplete and state.stdoutComplete.available),
            "stderrCompleteAvailable": bool(state.stderrComplete and state.stderrComplete.available),
            "plotCount": len(state.plots),
        })
        if len(output) >= limit:
            break
    return output


def complete_run_learning(
    db: Any,
    *,
    owner: str,
    user: DBUser,
    resource_id: str,
    run_id: str,
    idempotency_key: str,
    context: dict[str, Any] | None,
    actual_minutes: int | None,
) -> dict[str, Any]:
    artifact, resource_version, content = _owned_resource(db, resource_id, owner)
    _, _, run = _owned_run(db, run_id, owner)
    if run.sourceResourceId != artifact.id:
        _fail("code_sandbox_run_resource_mismatch", "运行记录不属于当前代码沙盒。")
    if run.sourceResourceVersionId != resource_version.id:
        _fail("code_sandbox_run_stale", "代码沙盒已保存新版本，请基于当前版本重新运行。")
    if run.status != "success" or run.totalCount < 1 or run.passedCount != run.totalCount:
        _fail("code_sandbox_run_incomplete", "只有通过全部必需检查的真实运行才能完成学习。")
    payload = {
        "passed_count": run.passedCount,
        "total_count": run.totalCount,
        "test_scope": "required",
        "run_id": run.runAttemptId,
        "resource_version_id": resource_version.id,
        "completion_rule": content.completionRule,
        "code_sha256": run.codeSha256,
    }
    if actual_minutes is not None:
        payload["actual_minutes"] = actual_minutes
    existing = db.query(DBLearningEvent).filter_by(
        owner_public_id=owner,
        idempotency_key=idempotency_key,
    ).first()
    if existing is not None:
        existing_payload = dict(existing.payload or {})
        context_matches = all(
            (context or {}).get(key) in {None, (existing.context_ref or {}).get(key)}
            for key in ("courseId", "pathId", "taskId")
        )
        if (
            existing.event_type != "code_tests_passed"
            or existing.object_type != "artifact"
            or existing.object_id != artifact.id
            or existing_payload.get("run_id") != run.runAttemptId
            or existing_payload.get("resource_version_id") != resource_version.id
            or existing_payload.get("actual_minutes") != actual_minutes
            or not context_matches
        ):
            _fail(
                "code_sandbox_completion_idempotency_conflict",
                "完成幂等键已经绑定到其他运行或学习上下文。",
            )
        consumption = process_path_event(db, event=existing)
        return {
            "schemaVersion": "f6.code-sandbox-completion.v1",
            "eventId": existing.id,
            "created": False,
            "runAttemptId": run.runAttemptId,
            "evidenceStatus": existing.evidence_status,
            "masteryEligible": bool(existing.mastery_eligible),
            "completionEffect": existing.completion_effect,
            "pathConsumptionStatus": consumption.status if consumption else None,
        }
    event, created = record_learning_event(
        db,
        owner_public_id=owner,
        user=user,
        trusted_source=True,
        event=LearningEventInput(
            idempotency_key=idempotency_key,
            event_type="code_tests_passed",
            context=ContextRef.model_validate(context) if context else None,
            course_id=artifact.course_id,
            object_type="artifact",
            object_id=artifact.id,
            source="sandbox",
            payload=payload,
        ),
    )
    consumption = process_path_event(db, event=event)
    return {
        "schemaVersion": "f6.code-sandbox-completion.v1",
        "eventId": event.id,
        "created": created,
        "runAttemptId": run.runAttemptId,
        "evidenceStatus": event.evidence_status,
        "masteryEligible": bool(event.mastery_eligible),
        "completionEffect": event.completion_effect,
        "pathConsumptionStatus": consumption.status if consumption else None,
    }


CODE_SANDBOX_EXECUTOR = LocalPythonExecutor()


class CodeSandboxRunCoordinator:
    def __init__(self, executor: LocalPythonExecutor) -> None:
        self.executor = executor
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def schedule(self, run_id: str) -> None:
        if not self.executor.enabled:
            _fail("code_sandbox_runtime_unavailable", self.executor.status()["message"])
        async with self._lock:
            existing = self._tasks.get(run_id)
            if existing is not None and not existing.done():
                return
            task = asyncio.create_task(self._worker(run_id), name=f"code-sandbox-{run_id}")
            self._tasks[run_id] = task

    async def _worker(self, run_id: str) -> None:
        try:
            state = await run_db_op(lambda db: self._mark_running_commit(db, run_id))
            result = await self.executor.execute(state)
            await run_db_op(lambda db: self._finalize_commit(db, run_id, result))
        except Exception as exc:
            message = f"代码运行协调器失败：{exc}"
            capture = OutputCapture(
                totalBytes=len(message.encode("utf-8")),
                capturedBytes=len(message.encode("utf-8")),
                limitBytes=max(1, int(CONFIG.sandbox_max_output_bytes)),
                omittedBytes=0,
                truncated=False,
            )
            result = ExecutionResult(
                status="runtime_error",
                executionTimeMs=0,
                exitCode=None,
                stderr=message,
                stdoutCapture=_empty_capture(int(CONFIG.sandbox_max_output_bytes)),
                stderrCapture=capture,
                errorCode="code_coordinator_failed",
            )
            try:
                await run_db_op(lambda db: self._finalize_commit(db, run_id, result))
            except Exception:
                pass
        finally:
            async with self._lock:
                self._tasks.pop(run_id, None)

    @staticmethod
    def _mark_running_commit(db: Any, run_id: str) -> CodeSandboxRunState:
        state = mark_run_running(db, run_id)
        db.commit()
        return state

    @staticmethod
    def _finalize_commit(db: Any, run_id: str, result: ExecutionResult) -> CodeSandboxRunState:
        state = finalize_run(db, run_id, result)
        db.commit()
        return state

    async def stop(self, run_id: str) -> None:
        await self.executor.stop(run_id)

    async def shutdown(self) -> None:
        await self.executor.shutdown()
        async with self._lock:
            tasks = list(self._tasks.values())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


CODE_SANDBOX_RUN_COORDINATOR = CodeSandboxRunCoordinator(CODE_SANDBOX_EXECUTOR)
