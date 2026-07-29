from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, chat, data, health, sessions
from app.auth import ensure_demo_users
from app.config import get_settings
from app.db.mysql import dispose_engine, init_db
from app.observability import (
    RequestObservabilityMiddleware,
    configure_structured_logging,
    render_metrics,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_structured_logging()
    settings = get_settings()
    init_db()
    if settings.ensure_demo_users:
        if settings.is_production:
            logger.warning("生产环境仍开启 ENSURE_DEMO_USERS，请确认这是有意为之")
        ensure_demo_users()
    app.state.settings = settings
    try:
        yield
    finally:
        dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    origins = settings.cors_origin_list
    allow_credentials = origins != ["*"]

    app = FastAPI(
        title=settings.app_name,
        description="傲基企业级智能数据问答 Agent 后端 API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 先加业务 CORS，再加观测中间件（Starlette 后加的更外层）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )
    app.add_middleware(RequestObservabilityMiddleware)

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(data.router, prefix="/api/v1")

    if settings.metrics_enabled:

        @app.get("/metrics", include_in_schema=False)
        def metrics() -> Response:
            payload, content_type = render_metrics()
            return Response(content=payload, media_type=content_type)

    return app


app = create_app()
