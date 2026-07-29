from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.mysql_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=max(1, settings.mysql_pool_size),
    max_overflow=max(0, settings.mysql_max_overflow),
    pool_timeout=max(1, settings.mysql_pool_timeout),
    echo=settings.debug,
    connect_args={
        "connect_timeout": max(1, settings.mysql_connect_timeout),
        "read_timeout": max(1, settings.mysql_read_timeout),
        "write_timeout": max(1, settings.mysql_read_timeout),
    },
)


@event.listens_for(engine, "connect")
def _set_session_timeouts(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    """为每条新连接设置 SELECT 最大执行时间（毫秒）。"""
    ms = int(settings.mysql_max_execution_time_ms or 0)
    if ms <= 0:
        return
    try:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET SESSION MAX_EXECUTION_TIME={ms}")
        finally:
            cursor.close()
    except Exception:  # noqa: BLE001
        # 部分托管 MySQL 可能禁改会话变量；忽略以免阻断启动
        pass


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def _ensure_chat_session_user_id() -> None:
    """兼容已有库：为 chat_sessions 补 user_id 列（create_all 不会 ALTER）."""
    try:
        insp = inspect(engine)
        if "chat_sessions" not in insp.get_table_names():
            return
        columns = {c["name"] for c in insp.get_columns("chat_sessions")}
        if "user_id" in columns:
            return
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE chat_sessions "
                    "ADD COLUMN user_id INT NULL, "
                    "ADD INDEX ix_chat_sessions_user_id (user_id)"
                )
            )
    except Exception:  # noqa: BLE001
        # 启动时不应因迁移细节阻断；表结构由 create_all / 运维保证
        pass


def init_db() -> None:
    # 延迟导入，避免循环依赖
    from app.db import models  # noqa: F401
    from app.auth import AppUser  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_chat_session_user_id()


def dispose_engine() -> None:
    engine.dispose()


def ping_mysql() -> None:
    """探活：失败抛异常."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
