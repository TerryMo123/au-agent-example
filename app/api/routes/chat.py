from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.auth import AuthUser, get_current_user
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService, get_chat_service

router = APIRouter(prefix="/chat", tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
    user: AuthUser = Depends(get_current_user),
) -> ChatResponse:
    return await service.chat(request, role=user.role)


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
    user: AuthUser = Depends(get_current_user),
) -> StreamingResponse:
    return StreamingResponse(
        service.chat_stream(request, role=user.role),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
