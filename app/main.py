from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, chat, data, health, sessions
from app.auth import ensure_demo_users
from app.config import get_settings
from app.db.mysql import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    ensure_demo_users()
    app.state.settings = settings
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="傲基企业级智能数据问答 Agent 后端 API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
    app.include_router(data.router, prefix="/api/v1")

    return app


app = create_app()
