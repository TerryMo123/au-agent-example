from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.auth import AuthUser, get_current_user
from app.observability import REQUEST_ID_HEADER, get_request_id, set_user_role
from app.rate_limit import check_chat_rate_limit
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService, get_chat_service
from app.services.session_service import SessionOwnershipError

router = APIRouter(prefix="/chat", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    service: ChatService = Depends(get_chat_service),
    user: AuthUser = Depends(get_current_user),
) -> ChatResponse:
    set_user_role(user.role)
    check_chat_rate_limit(request=http_request, user=user)
    try:
        return await service.chat(request, user=user)
    except SessionOwnershipError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    service: ChatService = Depends(get_chat_service),
    user: AuthUser = Depends(get_current_user),
) -> StreamingResponse:
    set_user_role(user.role)
    check_chat_rate_limit(request=http_request, user=user)
    request_id = getattr(http_request.state, "request_id", None) or get_request_id()

    async def _gen():
        try:
            async for chunk in service.chat_stream(request, user=user):
                yield chunk
        except SessionOwnershipError:
            yield 'event: error\ndata: {"message":"会话不存在","degraded":true}\n\n'

    headers = dict(SSE_HEADERS)
    if request_id:
        headers[REQUEST_ID_HEADER] = request_id

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers=headers,
    )
