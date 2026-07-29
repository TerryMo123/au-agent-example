"""结构化日志辅助."""

from __future__ import annotations

import logging
from typing import Any

from app.observability.context import get_request_id, get_user_role


class RequestContextFilter(logging.Filter):
    """把 request_id / user_role 注入 LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"  # type: ignore[attr-defined]
        record.user_role = get_user_role() or "-"  # type: ignore[attr-defined]
        return True


def configure_structured_logging() -> None:
    """为 root logger 挂上上下文 Filter；格式含 request_id."""
    root = logging.getLogger()
    filt = RequestContextFilter()
    root.addFilter(filt)
    for handler in root.handlers:
        handler.addFilter(filt)
        # 若仍是默认格式，补充 request_id 字段
        if handler.formatter is None:
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s [req=%(request_id)s role=%(user_role)s] "
                    "%(name)s: %(message)s"
                )
            )


def log_extra(**fields: Any) -> dict[str, Any]:
    """构造 logger extra，自动带上 request_id."""
    payload = {k: v for k, v in fields.items() if v is not None}
    rid = get_request_id()
    if rid:
        payload.setdefault("request_id", rid)
    role = get_user_role()
    if role:
        payload.setdefault("user_role", role)
    return payload
