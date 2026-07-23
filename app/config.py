from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="傲基智能数据问答 Agent", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=True, alias="DEBUG")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="qwen-max", alias="OPENAI_MODEL")
    openai_router_model: str = Field(
        default="qwen-turbo",
        alias="OPENAI_ROUTER_MODEL",
        description="问题路由专用小模型，规则未命中时使用",
    )
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    openai_embedding_model: str = Field(
        default="text-embedding-v3", alias="OPENAI_EMBEDDING_MODEL"
    )

    mysql_host: str = Field(default="127.0.0.1", alias="MYSQL_HOST")
    mysql_port: int = Field(default=3306, alias="MYSQL_PORT")
    mysql_user: str = Field(default="root", alias="MYSQL_USER")
    mysql_password: str = Field(default="root", alias="MYSQL_PASSWORD")
    mysql_database: str = Field(default="au_agent", alias="MYSQL_DATABASE")

    chroma_persist_dir: Path = Field(
        default=Path("./data/chroma"), alias="CHROMA_PERSIST_DIR"
    )
    chroma_collection_name: str = Field(
        default="au_internal_docs", alias="CHROMA_COLLECTION_NAME"
    )

    agent_max_iterations: int = Field(default=10, alias="AGENT_MAX_ITERATIONS")
    session_history_limit: int = Field(
        default=20, alias="SESSION_HISTORY_LIMIT", description="注入 Agent 的最大历史消息条数"
    )
    llm_max_retries: int = Field(
        default=3, alias="LLM_MAX_RETRIES", description="LLM API 瞬时错误最大尝试次数"
    )
    llm_retry_backoff_seconds: float = Field(
        default=0.8, alias="LLM_RETRY_BACKOFF_SECONDS", description="重试基础退避秒数"
    )

    # 语义问答缓存（Redis）
    semantic_cache_enabled: bool = Field(
        default=False, alias="SEMANTIC_CACHE_ENABLED"
    )
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", alias="REDIS_URL")
    semantic_cache_ttl_seconds: int = Field(
        default=3600, alias="SEMANTIC_CACHE_TTL_SECONDS"
    )
    semantic_cache_threshold: float = Field(
        default=0.92, alias="SEMANTIC_CACHE_THRESHOLD"
    )
    semantic_cache_max_entries: int = Field(
        default=500, alias="SEMANTIC_CACHE_MAX_ENTRIES"
    )

    @property
    def mysql_url(self) -> str:
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        return (
            f"mysql+pymysql://{user}:{password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
