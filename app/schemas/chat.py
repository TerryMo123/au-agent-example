from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["user", "assistant", "system"] = "user"
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="用户问题")
    session_id: str | None = Field(default=None, description="会话 ID，用于多轮对话")
    history: list[Message] = Field(
        default_factory=list,
        description="可选：前端临时历史；若提供 session_id，优先使用数据库持久化历史",
    )


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    route: str | None = Field(default=None, description="Agent 路由结果: sql | rag | hybrid")
    sources: list[dict[str, Any]] = Field(default_factory=list, description="引用来源")
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255, description="会话标题")


class SessionUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class SessionMessageOut(BaseModel):
    id: int
    role: str
    content: str
    route: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionSummary(BaseModel):
    session_id: str
    title: str
    status: str
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class SessionDetail(BaseModel):
    session_id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[SessionMessageOut] = Field(default_factory=list)


class SessionListResponse(BaseModel):
    items: list[SessionSummary]
    total: int
