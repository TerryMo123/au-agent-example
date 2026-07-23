from functools import lru_cache

from langchain_chroma import Chroma

from app.config import get_settings
from app.llm import get_embeddings


@lru_cache
def get_vector_store() -> Chroma:
    settings = get_settings()
    settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=settings.chroma_collection_name,
        embedding_function=get_embeddings(),
        persist_directory=str(settings.chroma_persist_dir),
    )
