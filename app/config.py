from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_JWT_SECRETS = frozenset(
    {
        "",
        "au-agent-dev-secret-change-me",
        "change-me-in-production",
        "changeme",
        "secret",
    }
)


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
    mysql_pool_size: int = Field(default=5, alias="MYSQL_POOL_SIZE")
    mysql_max_overflow: int = Field(default=10, alias="MYSQL_MAX_OVERFLOW")
    mysql_pool_timeout: int = Field(
        default=30, alias="MYSQL_POOL_TIMEOUT", description="获取连接超时秒数"
    )
    mysql_connect_timeout: int = Field(default=5, alias="MYSQL_CONNECT_TIMEOUT")
    mysql_read_timeout: int = Field(
        default=60, alias="MYSQL_READ_TIMEOUT", description="单次读超时秒数"
    )
    mysql_max_execution_time_ms: int = Field(
        default=15000,
        alias="MYSQL_MAX_EXECUTION_TIME_MS",
        description="SELECT 最大执行时间（毫秒，0 表示不限制）",
    )

    chroma_persist_dir: Path = Field(
        default=Path("./data/chroma"), alias="CHROMA_PERSIST_DIR"
    )
    chroma_collection_name: str = Field(
        default="au_internal_docs", alias="CHROMA_COLLECTION_NAME"
    )
    # local=进程内持久化目录；http=连接独立 Chroma Server（API 可无状态多副本）
    vector_backend: str = Field(
        default="local",
        alias="VECTOR_BACKEND",
        description="向量库后端：local | http",
    )
    chroma_host: str = Field(default="127.0.0.1", alias="CHROMA_HOST")
    chroma_port: int = Field(default=8000, alias="CHROMA_PORT")
    chroma_ssl: bool = Field(default=False, alias="CHROMA_SSL")
    chroma_tenant: str = Field(default="default_tenant", alias="CHROMA_TENANT")
    chroma_database: str = Field(default="default_database", alias="CHROMA_DATABASE")

    # 限流（默认依赖 Redis；未启用 Redis 时使用进程内计数）
    rate_limit_enabled: bool = Field(default=False, alias="RATE_LIMIT_ENABLED")
    rate_limit_chat_per_minute: int = Field(
        default=30, alias="RATE_LIMIT_CHAT_PER_MINUTE", description="每用户每分钟问答上限"
    )
    rate_limit_ip_per_minute: int = Field(
        default=60, alias="RATE_LIMIT_IP_PER_MINUTE", description="每 IP 每分钟问答上限"
    )

    agent_max_iterations: int = Field(default=10, alias="AGENT_MAX_ITERATIONS")
    session_history_limit: int = Field(
        default=20, alias="SESSION_HISTORY_LIMIT", description="注入 Agent 的最大历史消息条数"
    )
    answer_history_messages: int = Field(
        default=6,
        alias="ANSWER_HISTORY_MESSAGES",
        description="最终生成时注入的最近历史消息条数（不含当前问题）",
    )
    answer_history_max_chars: int = Field(
        default=800,
        alias="ANSWER_HISTORY_MAX_CHARS",
        description="单条历史消息注入生成时的最大字符数",
    )
    llm_max_retries: int = Field(
        default=3, alias="LLM_MAX_RETRIES", description="LLM API 瞬时错误最大尝试次数"
    )
    llm_retry_backoff_seconds: float = Field(
        default=0.8, alias="LLM_RETRY_BACKOFF_SECONDS", description="重试基础退避秒数"
    )
    llm_concurrency: int = Field(
        default=8, alias="LLM_CONCURRENCY", description="进程内并发 LLM 调用上限"
    )
    db_concurrency: int = Field(
        default=8, alias="DB_CONCURRENCY", description="进程内并发 DB 查询上限"
    )
    concurrency_acquire_timeout: float = Field(
        default=30.0,
        alias="CONCURRENCY_ACQUIRE_TIMEOUT",
        description="获取并发槽位超时秒数",
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
    redis_reconnect_interval_seconds: float = Field(
        default=30.0,
        alias="REDIS_RECONNECT_INTERVAL_SECONDS",
        description="缓存 Redis 断开后最小重连间隔",
    )

    # JWT 认证
    jwt_secret: str = Field(
        default="au-agent-dev-secret-change-me",
        alias="JWT_SECRET",
        description="生产环境务必更换为强随机串",
    )
    jwt_expire_hours: int = Field(default=24, alias="JWT_EXPIRE_HOURS")

    # CORS：逗号分隔；生产环境禁止使用 *
    cors_origins: str = Field(
        default="*",
        alias="CORS_ORIGINS",
        description="允许的前端 Origin，逗号分隔",
    )

    # 演示账号种子（生产建议关闭）
    ensure_demo_users: bool = Field(
        default=True,
        alias="ENSURE_DEMO_USERS",
        description="启动时写入演示账号；生产请设 false",
    )
    metrics_enabled: bool = Field(
        default=True,
        alias="METRICS_ENABLED",
        description="是否暴露 /metrics Prometheus 端点",
    )

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def vector_backend_normalized(self) -> str:
        value = (self.vector_backend or "local").strip().lower()
        if value in {"http", "remote", "server", "chroma_http"}:
            return "http"
        return "local"

    @property
    def is_vector_stateless(self) -> bool:
        """HTTP 向量库时 API 可不挂本地 Chroma PVC，可水平扩展."""
        return self.vector_backend_normalized == "http"

    @property
    def mysql_url(self) -> str:
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        return (
            f"mysql+pymysql://{user}:{password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset=utf8mb4"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("jwt_secret")
    @classmethod
    def _strip_jwt(cls, value: str) -> str:
        return (value or "").strip()

    @model_validator(mode="after")
    def _validate_production_security(self) -> "Settings":
        if not self.is_production:
            return self
        secret = self.jwt_secret
        if secret in _INSECURE_JWT_SECRETS or len(secret) < 24:
            raise ValueError(
                "生产环境必须设置强 JWT_SECRET（长度≥24，且不可使用默认占位值）"
            )
        origins = self.cors_origin_list
        if not origins or origins == ["*"]:
            raise ValueError(
                "生产环境必须设置 CORS_ORIGINS 白名单（逗号分隔，禁止使用 *）"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
