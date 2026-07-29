"""请求上下文：request_id 等跨层传递."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_role_var: ContextVar[str] = ContextVar("user_role", default="")


def get_request_id() -> str:
    return request_id_var.get() or ""


def set_request_id(value: str) -> None:
    request_id_var.set(value or "")


def get_user_role() -> str:
    return user_role_var.get() or ""


def set_user_role(value: str) -> None:
    user_role_var.set(value or "")
