from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_requests: int = 1

    _state: CircuitState = CircuitState.CLOSED
    _failure_count: int = 0
    _last_failure_time: float = 0.0
    _half_open_requests: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def call(self, coro_factory: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_requests = 0
                else:
                    raise CircuitBreakerOpenError(
                        f"熔断器 {self.name} 已打开，拒绝请求。"
                        f"将在 {self.recovery_timeout - (time.time() - self._last_failure_time):.0f}s 后尝试恢复。"
                    )

            if self._state == CircuitState.HALF_OPEN and self._half_open_requests >= self.half_open_max_requests:
                raise CircuitBreakerOpenError(
                    f"熔断器 {self.name} 半开状态已达最大探测数。"
                )

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_requests += 1

        try:
            result = await coro_factory()
        except Exception as exc:
            async with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.time()
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
            raise exc

        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
            else:
                self._failure_count = 0

        return result

    @property
    def state(self) -> CircuitState:
        return self._state

    def reset(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_requests = 0


class CircuitBreakerOpenError(Exception):
    pass


@dataclass
class TokenBucket:
    capacity: int
    refill_rate: float
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self._tokens = float(self.capacity)
        self._last_refill = time.time()

    async def acquire(self, tokens: float = 1.0, timeout: float = 30.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
            await asyncio.sleep(0.05)
        return False

    def _refill(self) -> None:
        now = time.time()
        elapsed = now - self._last_refill
        self._tokens = min(float(self.capacity), self._tokens + elapsed * self.refill_rate)
        self._last_refill = now


@dataclass
class APIRateLimiter:
    rpm_bucket: TokenBucket
    tpm_bucket: TokenBucket
    request_semaphore: asyncio.Semaphore

    def __init__(
        self,
        max_rpm: int = 120,
        max_tpm: int = 100000,
        max_concurrent: int = 8,
    ) -> None:
        self.rpm_bucket = TokenBucket(capacity=max_rpm, refill_rate=max_rpm / 60.0)
        self.tpm_bucket = TokenBucket(capacity=max_tpm, refill_rate=max_tpm / 60.0)
        self.request_semaphore = asyncio.Semaphore(max_concurrent)

    async def acquire(self, estimated_tokens: int = 1000, timeout: float = 60.0) -> bool:
        await self.request_semaphore.acquire()
        try:
            rpm_ok = await self.rpm_bucket.acquire(1.0, timeout=timeout)
            if not rpm_ok:
                self.request_semaphore.release()
                return False
            tpm_ok = await self.tpm_bucket.acquire(float(estimated_tokens), timeout=timeout)
            if not tpm_ok:
                self.request_semaphore.release()
                return False
            return True
        except Exception:
            self.request_semaphore.release()
            return False

    def release(self) -> None:
        self.request_semaphore.release()


@dataclass
class AsyncWorkerPool:
    max_workers: int
    _queue: asyncio.Queue = field(init=False)
    _workers: list[asyncio.Task] = field(default_factory=list)
    _running: bool = field(default=False)

    def __post_init__(self) -> None:
        self._queue = asyncio.Queue(maxsize=200)

    async def start(self) -> None:
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker_loop(i), name=f"worker-{i}")
            for i in range(self.max_workers)
        ]

    async def stop(self) -> None:
        self._running = False
        for _ in range(self.max_workers):
            await self._queue.put(None)
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()

    async def submit(
        self,
        fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        timeout: float = 120.0,
        **kwargs: Any,
    ) -> Any:
        result_future: asyncio.Future = asyncio.Future()
        await self._queue.put((fn, args, kwargs, result_future, timeout))
        return await result_future

    async def _worker_loop(self, worker_id: int) -> None:
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if item is None:
                self._queue.task_done()
                break
            fn, args, kwargs, result_future, timeout = item
            try:
                result = await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
                if not result_future.done():
                    result_future.set_result(result)
            except asyncio.CancelledError:
                if not result_future.done():
                    result_future.set_exception(asyncio.CancelledError())
            except Exception as exc:
                if not result_future.done():
                    result_future.set_exception(exc)
            finally:
                self._queue.task_done()


async def retry_with_backoff(
    coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
) -> Any:
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await coro_factory()
        except CircuitBreakerOpenError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                import random
                delay = min(max_delay, base_delay * (2 ** attempt))
                if jitter:
                    delay *= 0.5 + random.random() * 0.5
                await asyncio.sleep(delay)
    raise RuntimeError(
        f"重试 {max_attempts} 次后仍然失败: {last_exc}"
    ) from last_exc
