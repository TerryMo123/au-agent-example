"""阿里云百炼 MaaS 聊天客户端（适配简化响应格式）."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from app.config import Settings, get_settings


def _message_to_dict(message: BaseMessage) -> dict[str, str]:
    if isinstance(message, SystemMessage):
        role = "system"
    elif isinstance(message, HumanMessage):
        role = "user"
    elif isinstance(message, AIMessage):
        role = "assistant"
    else:
        role = getattr(message, "type", "user")
        if role == "human":
            role = "user"
        elif role == "ai":
            role = "assistant"
    content = message.content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        content = "".join(parts)
    return {"role": role, "content": str(content)}


def _extract_text(payload: dict[str, Any]) -> str:
    """兼容标准 OpenAI choices 与百炼简化 {text} 响应."""
    if isinstance(payload.get("text"), str) and payload["text"]:
        return payload["text"]

    choices = payload.get("choices") or []
    if choices:
        first = choices[0] or {}
        message = first.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        delta = first.get("delta") or {}
        if isinstance(delta.get("content"), str):
            return delta["content"]
        if isinstance(first.get("text"), str):
            return first["text"]

    raise ValueError(f"无法解析模型响应: {json.dumps(payload, ensure_ascii=False)[:500]}")


def _chunk_text(text: str, size: int = 8) -> Iterator[str]:
    """接口不支持真正 token 流时，按小块模拟流式输出."""
    if not text:
        return
    for i in range(0, len(text), size):
        yield text[i : i + size]


class QwenMaaSChatModel(BaseChatModel):
    """调用阿里云 MaaS OpenAI 兼容接口（支持简化 text 响应）."""

    model_name: str = Field(default="qwen-max")
    api_key: str = Field(default="")
    base_url: str = Field(default="")
    temperature: float = 0.1
    timeout: float = 120.0
    fake_stream_chunk_size: int = 8

    @property
    def _llm_type(self) -> str:
        return "qwen-maas"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "base_url": self.base_url}

    def _chat_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    def _build_payload(self, messages: list[BaseMessage], *, stream: bool) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "messages": [_message_to_dict(m) for m in messages],
            "temperature": self.temperature,
            "stream": stream,
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload = self._build_payload(messages, stream=False)
        if stop:
            payload["stop"] = stop
        payload.update(kwargs)

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self._chat_url(), headers=self._headers(), json=payload)
            response.raise_for_status()
            data = response.json()

        text = _extract_text(data)
        generation = ChatGeneration(message=AIMessage(content=text))
        return ChatResult(generations=[generation], llm_output={"raw": data})

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload = self._build_payload(messages, stream=False)
        if stop:
            payload["stop"] = stop
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self._chat_url(), headers=self._headers(), json=payload
            )
            response.raise_for_status()
            data = response.json()

        text = _extract_text(data)
        generation = ChatGeneration(message=AIMessage(content=text))
        return ChatResult(generations=[generation], llm_output={"raw": data})

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        result = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        text = result.generations[0].message.content
        if not isinstance(text, str):
            text = str(text)
        for piece in _chunk_text(text, self.fake_stream_chunk_size):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if run_manager:
                run_manager.on_llm_new_token(piece)
            yield chunk

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        result = await self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        text = result.generations[0].message.content
        if not isinstance(text, str):
            text = str(text)
        for piece in _chunk_text(text, self.fake_stream_chunk_size):
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=piece))
            if run_manager:
                await run_manager.on_llm_new_token(piece)
            yield chunk


def build_chat_model(
    settings: Settings | None = None, *, temperature: float = 0.1
) -> QwenMaaSChatModel:
    settings = settings or get_settings()
    if not settings.openai_api_key:
        raise ValueError("缺少 OPENAI_API_KEY（阿里云百炼 API Key）")
    if not settings.openai_base_url:
        raise ValueError("缺少 OPENAI_BASE_URL")

    return QwenMaaSChatModel(
        model_name=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=temperature,
    )
