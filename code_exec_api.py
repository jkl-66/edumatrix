from __future__ import annotations

import sys
import io
import time
import uuid
import traceback
from typing import Any
from contextlib import redirect_stdout, redirect_stderr

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import DBCodeExecution, get_db

router = APIRouter(prefix="/api/code", tags=["code_execution"])


def _generate_id() -> str:
    return uuid.uuid4().hex[:16]


@router.post("/run")
async def run_code(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    code = str(payload.get("code", "")).strip()
    language = str(payload.get("language", "python")).strip().lower()
    student_id = str(payload.get("student_id", "default"))

    if not code:
        raise HTTPException(status_code=400, detail="代码不能为空")

    if language == "python":
        output, error, exec_time = _execute_python(code)
    else:
        output, error, exec_time = _execute_python(code)

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
    db.add(db_exec)
    db.commit()

    return {
        "exec_id": exec_id,
        "output": output,
        "error": error,
        "execution_time_ms": int(exec_time * 1000),
        "language": language,
    }


def _execute_python(code: str) -> tuple[str, str, float]:
    output_buffer = io.StringIO()
    error_buffer = io.StringIO()
    start_time = time.time()

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

    try:
        import numpy as np
        restricted_globals["numpy"] = np
        restricted_globals["np"] = np
    except ImportError:
        pass

    try:
        import pandas as pd
        restricted_globals["pandas"] = pd
        restricted_globals["pd"] = pd
    except ImportError:
        pass

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        restricted_globals["matplotlib"] = matplotlib
        restricted_globals["plt"] = plt
    except ImportError:
        pass

    try:
        from sklearn import datasets, model_selection, linear_model, metrics, preprocessing, tree, svm, neighbors
        restricted_globals["sklearn"] = __import__("sklearn")
    except ImportError:
        pass

    try:
        compiled = compile(code, "<sandbox>", "exec")
    except SyntaxError as e:
        return "", f"语法错误: {e}", time.time() - start_time

    try:
        with redirect_stdout(output_buffer), redirect_stderr(error_buffer):
            exec(compiled, restricted_globals)

            # Check if matplotlib figure was created
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
                    output_buffer.write(f"\n![可视化输出](data:image/png;base64,{img_b64})")

        output = output_buffer.getvalue()
        error = error_buffer.getvalue()
    except Exception as e:
        error = traceback.format_exc()
        output = output_buffer.getvalue()

    exec_time = time.time() - start_time
    return output, error, exec_time


@router.get("/history/{student_id}")
async def get_code_history(
    student_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    records = (
        db.query(DBCodeExecution)
        .filter(DBCodeExecution.student_id == student_id)
        .order_by(DBCodeExecution.created_at.desc())
        .limit(limit)
        .all()
    )
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
