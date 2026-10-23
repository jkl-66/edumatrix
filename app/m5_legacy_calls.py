from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Callable

from app.database import DBModelCall, SessionLocal, run_db_op
from app.m5_gateway import StreamingModelCallLifecycle
from config import CONFIG


def model_identity(llm: Any) -> tuple[str, str]:
    provider = getattr(llm, "provider", None) or (
        "deterministic"
        if llm.__class__.__name__ == "AsyncDeterministicEducationLLM"
        else CONFIG.llm_provider
    )
    model = getattr(
        llm,
        "model",
        "deterministic" if provider == "deterministic" else CONFIG.llm_model,
    )
    return provider or "unknown", model or "unknown"


async def audited_legacy_text_call(
    llm: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    role: str,
    operation: str,
    capability: str,
    owner_public_id: str,
    input_summary: dict[str, Any],
    course_id: str | None = None,
    trace_id: str | None = None,
    response_validator: Callable[[str], Any] | None = None,
    database_runner=run_db_op,
) -> str:
    provider, model = model_identity(llm)
    lifecycle = StreamingModelCallLifecycle(
        capability=capability,
        prompt_key=f"legacy_{operation}",
        prompt_version="1.0",
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        owner_public_id=owner_public_id,
        course_id=course_id,
        trace_id=trace_id,
        input_summary={"operation": operation, **input_summary},
        database_runner=database_runner,
    )
    await lifecycle.start()
    try:
        output = await llm.generate(system_prompt, user_prompt, role=role)
    except asyncio.CancelledError:
        await asyncio.shield(lifecycle.fail("client_disconnected"))
        raise
    except Exception:
        await lifecycle.fail(f"{operation}_provider_failed")
        raise
    if response_validator is not None:
        try:
            response_validator(output)
        except Exception:
            await lifecycle.fail(f"{operation}_output_invalid", output)
            raise
    await lifecycle.complete(output)
    return output


def audited_legacy_sync_text_call(
    llm: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    role: str,
    operation: str,
    capability: str,
    owner_public_id: str,
    input_summary: dict[str, Any],
    course_id: str | None = None,
    trace_id: str | None = None,
    response_validator: Callable[[str], Any] | None = None,
    session_factory=SessionLocal,
) -> str:
    provider, model = model_identity(llm)
    trace_id = trace_id or f"m5-{operation}-{__import__('uuid').uuid4().hex}"
    started = time.perf_counter()
    session = session_factory()
    row = DBModelCall(
        trace_id=trace_id,
        owner_public_id=owner_public_id,
        course_id=course_id,
        capability=capability,
        prompt_version=f"legacy_{operation}:1.0",
        provider=provider,
        model=model,
        status="running",
        input_summary={
            "capability": capability,
            "prompt_key": f"legacy_{operation}",
            "system_prompt_chars": len(system_prompt),
            "user_prompt_chars": len(user_prompt),
            "operation": operation,
            **input_summary,
        },
        input_tokens=max(1, (len(system_prompt + user_prompt) + 3) // 4),
        token_source="estimated",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    try:
        output = llm.generate(system_prompt, user_prompt, role=role)
    except Exception:
        row.status = "failed"
        row.error_code = f"{operation}_provider_failed"
        row.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        row.completed_at = datetime.now(timezone.utc)
        session.commit()
        raise
    else:
        if response_validator is not None:
            try:
                response_validator(output)
            except Exception:
                row.status = "failed"
                row.error_code = f"{operation}_output_invalid"
                row.output_tokens = max(1, (len(output) + 3) // 4) if output else 0
                row.output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest() if output else ""
                row.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
                row.completed_at = datetime.now(timezone.utc)
                session.commit()
                raise
        row.status = "completed"
        row.output_tokens = max(1, (len(output) + 3) // 4) if output else 0
        row.output_hash = hashlib.sha256(output.encode("utf-8")).hexdigest() if output else ""
        row.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        row.completed_at = datetime.now(timezone.utc)
        session.commit()
        return output
    finally:
        session.close()
