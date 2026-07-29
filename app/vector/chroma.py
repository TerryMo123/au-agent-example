"""向量库工厂：本地 Chroma 目录 或 远程 Chroma HTTP Server."""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain_chroma import Chroma

from app.config import get_settings
from app.llm import get_embeddings

logger = logging.getLogger(__name__)


def _local_store(settings) -> Chroma:
    settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=settings.chroma_collection_name,
        embedding_function=get_embeddings(),
        persist_directory=str(settings.chroma_persist_dir),
    )


def _http_store(settings) -> Chroma:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=int(settings.chroma_port),
        ssl=bool(settings.chroma_ssl),
        tenant=settings.chroma_tenant,
        database=settings.chroma_database,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    # 探活：列出集合（失败则抛出，由上层感知）
    client.heartbeat()
    logger.info(
        "已连接远程 Chroma: %s:%s ssl=%s",
        settings.chroma_host,
        settings.chroma_port,
        settings.chroma_ssl,
    )
    return Chroma(
        client=client,
        collection_name=settings.chroma_collection_name,
        embedding_function=get_embeddings(),
    )


@lru_cache
def get_vector_store() -> Chroma:
    settings = get_settings()
    backend = settings.vector_backend_normalized
    if backend == "http":
        return _http_store(settings)
    return _local_store(settings)


def ping_vector_store() -> None:
    """就绪探针用：失败抛异常."""
    settings = get_settings()
    if settings.vector_backend_normalized == "http":
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=int(settings.chroma_port),
            ssl=bool(settings.chroma_ssl),
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        client.heartbeat()
        return

    path = settings.chroma_persist_dir
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".ready_probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
