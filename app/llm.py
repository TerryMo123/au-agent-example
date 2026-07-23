"""LLM / Embedding 客户端工厂（阿里云百炼 OpenAI 兼容）。"""

from functools import lru_cache
from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import get_settings


def _client_kwargs() -> dict[str, Any]:
    settings = get_settings()
    kwargs: dict[str, Any] = {}
    if settings.openai_api_key:
        kwargs["api_key"] = settings.openai_api_key
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return kwargs


@lru_cache
def get_chat_llm(
    *, temperature: float = 0.1, model: str | None = None
) -> ChatOpenAI:
    """标准 OpenAI 兼容客户端，支持真正的 token 流式（astream）。"""
    settings = get_settings()
    return ChatOpenAI(
        model=model or settings.openai_model,
        temperature=temperature,
        streaming=True,
        # 关闭 SDK 内置重试，由 app.llm_retry 统一控制次数与降级
        max_retries=0,
        **_client_kwargs(),
    )


def get_router_llm() -> ChatOpenAI:
    """路由专用小模型（更快、更便宜）。"""
    settings = get_settings()
    return get_chat_llm(temperature=0, model=settings.openai_router_model)


@lru_cache
def get_embeddings() -> OpenAIEmbeddings:
    settings = get_settings()
    return OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        # 百炼 embedding 需要原始字符串，不能走 tiktoken 分词预处理
        check_embedding_ctx_length=False,
        **_client_kwargs(),
    )
