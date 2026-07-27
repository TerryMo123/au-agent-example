from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import AuthUser, get_current_user
from app.schemas.chat import (
    SessionCreateRequest,
    SessionDetail,
    SessionListResponse,
    SessionSummary,
    SessionUpdateRequest,
)
from app.services.session_service import SessionService, get_session_service

router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
    dependencies=[Depends(get_current_user)],
)

@router.post("", response_model=SessionSummary, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: SessionCreateRequest | None = None,
    service: SessionService = Depends(get_session_service),
) -> SessionSummary:
    body = request or SessionCreateRequest()
    session = service.create_session(title=body.title)
    return SessionSummary(
        session_id=session.session_id,
        title=session.title,
        status=session.status,
        message_count=0,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: SessionService = Depends(get_session_service),
) -> SessionListResponse:
    items, total = service.list_sessions(limit=limit, offset=offset)
    return SessionListResponse(
        items=[SessionSummary(**item) for item in items],
        total=total,
    )


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> SessionDetail:
    detail = service.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="会话不存在")
    return SessionDetail(**detail)


@router.patch("/{session_id}", response_model=SessionSummary)
async def update_session(
    session_id: str,
    request: SessionUpdateRequest,
    service: SessionService = Depends(get_session_service),
) -> SessionSummary:
    session = service.update_title(session_id, request.title)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    detail = service.get_session_detail(session_id)
    return SessionSummary(
        session_id=session.session_id,
        title=session.title,
        status=session.status,
        message_count=len(detail["messages"]) if detail else 0,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> None:
    if not service.soft_delete(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
