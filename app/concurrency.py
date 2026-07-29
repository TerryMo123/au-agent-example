"""进程内并发闸门：限制 LLM / DB 同时占用，避免打满连接池与上游配额."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import TypeVar

from app.config import get_settings

_llm_sem: threading.Semaphore | None = None
_db_sem: threading.Semaphore | None = None
_lock = threading.Lock()

T = TypeVar("T")


def _llm_semaphore() -> threading.Semaphore:
    global _llm_sem
    if _llm_sem is None:
        with _lock:
            if _llm_sem is None:
                _llm_sem = threading.Semaphore(max(1, get_settings().llm_concurrency))
    return _llm_sem


def _db_semaphore() -> threading.Semaphore:
    global _db_sem
    if _db_sem is None:
        with _lock:
            if _db_sem is None:
                _db_sem = threading.Semaphore(max(1, get_settings().db_concurrency))
    return _db_sem


class ConcurrencyTimeoutError(TimeoutError):
    """获取并发槽位超时."""


def _acquire(sem: threading.Semaphore, timeout: float) -> None:
    ok = sem.acquire(timeout=timeout)
    if not ok:
        raise ConcurrencyTimeoutError("并发槽位获取超时，请稍后重试")


@contextmanager
def llm_slot() -> Iterator[None]:
    settings = get_settings()
    sem = _llm_semaphore()
    _acquire(sem, settings.concurrency_acquire_timeout)
    try:
        yield
    finally:
        sem.release()


@contextmanager
def db_slot() -> Iterator[None]:
    settings = get_settings()
    sem = _db_semaphore()
    _acquire(sem, settings.concurrency_acquire_timeout)
    try:
        yield
    finally:
        sem.release()


@asynccontextmanager
async def async_llm_slot() -> AsyncIterator[None]:
    settings = get_settings()
    sem = _llm_semaphore()
    try:
        await asyncio.to_thread(_acquire, sem, settings.concurrency_acquire_timeout)
    except ConcurrencyTimeoutError:
        raise
    try:
        yield
    finally:
        sem.release()
