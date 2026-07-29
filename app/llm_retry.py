"""LLM API 级重试：对非确定性错误最多重试 3 次，耗尽后抛出供上层降级。"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeVar

from app.concurrency import ConcurrencyTimeoutError, llm_slot
from app.config import get_settings
from app.observability import observe_llm_result, observe_llm_retry

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 确定性错误：不应重试
_NON_RETRYABLE_NAME_PARTS = (
    "AuthenticationError",
    "PermissionDeniedError",
    "BadRequestError",
    "NotFoundError",
    "UnprocessableEntityError",
    "InvalidRequestError",
)

# 非确定性 / 瞬时错误：可重试
_RETRYABLE_NAME_PARTS = (
    "APIConnectionError",
    "APITimeoutError",
    "RateLimitError",
    "InternalServerError",
    "ServiceUnavailableError",
    "Timeout",
    "ConnectError",
    "RemoteProtocolError",
    "ReadTimeout",
    "WriteTimeout",
    "PoolTimeout",
)

_RETRYABLE_MESSAGE_PARTS = (
    "timeout",
    "timed out",
    "temporarily unavailable",
    "connection reset",
    "connection aborted",
    "server error",
    "overloaded",
    "rate limit",
    "too many requests",
    "429",
    "500",
    "502",
    "503",
    "504",
)


class LLMRetryExhaustedError(Exception):
    """LLM API 重试耗尽，上层应降级处理。"""

    def __init__(self, message: str, *, last_error: BaseException | None = None):
        super().__init__(message)
        self.last_error = last_error


def is_retryable_llm_error(exc: BaseException) -> bool:
    """判断是否为 LLM API 非确定性/瞬时错误。"""
    name = type(exc).__name__
    msg = str(exc).lower()

    if any(part in name for part in _NON_RETRYABLE_NAME_PARTS):
        return False

    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in {401, 403, 400, 404, 422}:
            return False
        if status == 429 or status >= 500:
            return True

    if any(part in name for part in _RETRYABLE_NAME_PARTS):
        return True

    if any(part in msg for part in _RETRYABLE_MESSAGE_PARTS):
        return True

    # OpenAI SDK 基类：未明确分类的 APIError 默认重试（保守）
    # 但排除已判定为不可重试的
    module = type(exc).__module__ or ""
    if "openai" in module and "Error" in name and "BadRequest" not in name:
        if "Authentication" in name or "Permission" in name:
            return False
        # APIError / APIStatusError 等
        if name in {"APIError", "APIStatusError"} or status is None:
            # 未知 API 错误：当作可重试的非确定原因
            return True

    return False


def _backoff_seconds(attempt: int, base: float) -> float:
    # attempt: 0,1,2 → 退避
    jitter = random.uniform(0, 0.25)
    return base * (2**attempt) + jitter


def invoke_llm_with_retry(fn: Callable[[], T], *, operation: str = "llm_invoke") -> T:
    """同步调用 LLM，瞬时错误最多重试 N 次。"""
    settings = get_settings()
    max_attempts = max(1, settings.llm_max_retries)
    last_error: BaseException | None = None

    try:
        with llm_slot():
            for attempt in range(max_attempts):
                try:
                    result = fn()
                    observe_llm_result(operation, "success")
                    return result
                except Exception as exc:  # noqa: BLE001 - 需按类型分流
                    last_error = exc
                    retryable = is_retryable_llm_error(exc)
                    if not retryable or attempt >= max_attempts - 1:
                        if retryable:
                            logger.error(
                                "%s 重试耗尽(%s/%s): %s",
                                operation,
                                attempt + 1,
                                max_attempts,
                                exc,
                            )
                            observe_llm_result(operation, "exhausted")
                            raise LLMRetryExhaustedError(
                                f"{operation} 在 {max_attempts} 次重试后仍失败",
                                last_error=exc,
                            ) from exc
                        logger.error("%s 遇到不可重试错误: %s", operation, exc)
                        observe_llm_result(operation, "error")
                        raise

                    observe_llm_retry(operation)
                    delay = _backoff_seconds(attempt, settings.llm_retry_backoff_seconds)
                    logger.warning(
                        "%s 第 %s/%s 次失败(可重试): %s；%.2fs 后重试",
                        operation,
                        attempt + 1,
                        max_attempts,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
    except ConcurrencyTimeoutError as exc:
        observe_llm_result(operation, "error")
        raise LLMRetryExhaustedError(
            f"{operation} 并发槽位获取超时", last_error=exc
        ) from exc

    observe_llm_result(operation, "exhausted")
    raise LLMRetryExhaustedError(
        f"{operation} 重试耗尽", last_error=last_error
    )


async def astream_llm_with_retry(
    make_stream: Callable[[], AsyncIterator[Any]],
    *,
    operation: str = "llm_astream",
) -> AsyncIterator[Any]:
    """流式调用：若在产出任何 token 前失败，则整体重试；已产出后失败则向上抛出."""
    from app.concurrency import async_llm_slot

    settings = get_settings()
    max_attempts = max(1, settings.llm_max_retries)
    last_error: BaseException | None = None

    try:
        async with async_llm_slot():
            for attempt in range(max_attempts):
                yielded_any = False
                try:
                    async for chunk in make_stream():
                        yielded_any = True
                        yield chunk
                    observe_llm_result(operation, "success")
                    return
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    retryable = is_retryable_llm_error(exc)

                    if yielded_any:
                        logger.error(
                            "%s 流式中途失败(已产出部分内容): %s", operation, exc
                        )
                        observe_llm_result(operation, "exhausted")
                        raise LLMRetryExhaustedError(
                            f"{operation} 流式中途失败",
                            last_error=exc,
                        ) from exc

                    if not retryable or attempt >= max_attempts - 1:
                        if retryable:
                            logger.error(
                                "%s 重试耗尽(%s/%s): %s",
                                operation,
                                attempt + 1,
                                max_attempts,
                                exc,
                            )
                            observe_llm_result(operation, "exhausted")
                            raise LLMRetryExhaustedError(
                                f"{operation} 在 {max_attempts} 次重试后仍失败",
                                last_error=exc,
                            ) from exc
                        logger.error("%s 遇到不可重试错误: %s", operation, exc)
                        observe_llm_result(operation, "error")
                        raise

                    observe_llm_retry(operation)
                    delay = _backoff_seconds(
                        attempt, settings.llm_retry_backoff_seconds
                    )
                    logger.warning(
                        "%s 第 %s/%s 次失败(可重试): %s；%.2fs 后重试",
                        operation,
                        attempt + 1,
                        max_attempts,
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
    except ConcurrencyTimeoutError as exc:
        observe_llm_result(operation, "error")
        raise LLMRetryExhaustedError(
            f"{operation} 并发槽位获取超时", last_error=exc
        ) from exc

    observe_llm_result(operation, "exhausted")
    raise LLMRetryExhaustedError(f"{operation} 重试耗尽", last_error=last_error)
