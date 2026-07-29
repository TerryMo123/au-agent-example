"""HTTP 可观测中间件：request_id + 基础指标."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.observability.context import set_request_id, set_user_role
from app.observability.metrics import observe_http

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"


class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER) or request.headers.get(
            "X-Request-ID"
        )
        request_id = (incoming or "").strip() or uuid.uuid4().hex
        set_request_id(request_id)
        set_user_role("")
        request.state.request_id = request_id

        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            elapsed = time.perf_counter() - started
            path = request.url.path
            # 跳过 metrics 自身，避免自反馈噪声
            if path != "/metrics":
                observe_http(request.method, path, status_code, elapsed)
