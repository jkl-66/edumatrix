"""Small thread-safe TTL + LRU cache used by bounded in-process caches."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import time
from threading import RLock
from typing import Callable, Generic, Iterable, Iterator, TypeVar


K = TypeVar("K")
V = TypeVar("V")


@dataclass
class _CacheEntry(Generic[V]):
    value: V
    expires_at: float


class TTLBoundedCache(Generic[K, V]):
    """An in-process cache with expiry, LRU eviction and explicit cleanup.

    The class intentionally exposes the small mapping surface used by the
    project (``get``, subscription, ``values`` and ``clear``), so existing
    cache invalidation code remains compatible.
    """

    def __init__(
        self,
        *,
        maxsize: int = 256,
        ttl_seconds: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.maxsize = max(1, int(maxsize))
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._clock = clock
        self._data: OrderedDict[K, _CacheEntry[V]] = OrderedDict()
        self._lock = RLock()

    def _purge_expired_locked(self, now: float | None = None) -> None:
        current = self._clock() if now is None else now
        expired = [key for key, entry in self._data.items() if entry.expires_at <= current]
        for key in expired:
            self._data.pop(key, None)

    def cleanup(self) -> int:
        with self._lock:
            before = len(self._data)
            self._purge_expired_locked()
            return before - len(self._data)

    def get(self, key: K, default: V | None = None) -> V | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return default
            if entry.expires_at <= self._clock():
                self._data.pop(key, None)
                return default
            self._data.move_to_end(key)
            return entry.value

    def set(self, key: K, value: V) -> None:
        with self._lock:
            now = self._clock()
            self._purge_expired_locked(now)
            self._data[key] = _CacheEntry(value=value, expires_at=now + self.ttl_seconds)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def __getitem__(self, key: K) -> V:
        value = self.get(key, None)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key: K, value: V) -> None:
        self.set(key, value)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            entry = self._data.get(key)  # type: ignore[arg-type]
            if entry is None:
                return False
            if entry.expires_at <= self._clock():
                self._data.pop(key, None)  # type: ignore[arg-type]
                return False
            return True

    def values(self) -> list[V]:
        with self._lock:
            self._purge_expired_locked()
            return [entry.value for entry in self._data.values()]

    def items(self) -> list[tuple[K, V]]:
        with self._lock:
            self._purge_expired_locked()
            return [(key, entry.value) for key, entry in self._data.items()]

    def __len__(self) -> int:
        with self._lock:
            self._purge_expired_locked()
            return len(self._data)

    def __iter__(self) -> Iterator[K]:
        with self._lock:
            self._purge_expired_locked()
            return iter(list(self._data.keys()))

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def pop(self, key: K, default: V | None = None) -> V | None:
        with self._lock:
            entry = self._data.pop(key, None)
            if entry is None or entry.expires_at <= self._clock():
                return default
            return entry.value
