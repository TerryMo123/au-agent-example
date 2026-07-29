"""管理员：全员会话与执行轨迹."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import AuthUser
from app.auth.security import require_admin
from app.services.session_service import SessionService, get_session_service

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


class AdminSessionSummary(BaseModel):
    session_id: str
    title: str
    status: str
    message_count: int = 0
    user_id: int | None = None
    username: str | None = None
    display_name: str | None = None
    user_role: str | None = None
    created_at: datetime
    updated_at: datetime


class AdminSessionListResponse(BaseModel):
    items: list[AdminSessionSummary]
    total: int


class AdminSessionMessage(BaseModel):
    id: int
    role: str
    content: str
    route: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AdminSessionDetail(BaseModel):
    session_id: str
    title: str
    status: str
    user_id: int | None = None
    username: str | None = None
    display_name: str | None = None
    user_role: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[AdminSessionMessage] = Field(default_factory=list)


@router.get("/sessions", response_model=AdminSessionListResponse)
async def list_all_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: SessionService = Depends(get_session_service),
    _admin: AuthUser = Depends(require_admin),
) -> AdminSessionListResponse:
    items, total = service.list_sessions_all(limit=limit, offset=offset)
    return AdminSessionListResponse(
        items=[AdminSessionSummary(**item) for item in items],
        total=total,
    )


@router.get("/sessions/{session_id}", response_model=AdminSessionDetail)
async def get_any_session(
    session_id: str,
    service: SessionService = Depends(get_session_service),
    admin: AuthUser = Depends(require_admin),
) -> AdminSessionDetail:
    detail = service.get_session_detail(
        session_id,
        user_id=admin.id,
        as_admin=True,
        include_trace=True,
    )
    if not detail:
        raise HTTPException(status_code=404, detail="会话不存在")
    return AdminSessionDetail(**detail)
