from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.auth.security import AppUser
from app.db.models import ChatMessage, ChatSession
from app.db.mysql import SessionLocal
from app.services.agent_trace import strip_trace_for_client


class SessionOwnershipError(Exception):
    """会话不属于当前用户."""


def _truncate_title(text: str, max_len: int = 40) -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return "新会话"
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


class SessionService:
    def create_session(
        self,
        *,
        user_id: int,
        title: str | None = None,
        session_id: str | None = None,
    ) -> ChatSession:
        db = SessionLocal()
        try:
            session = ChatSession(
                session_id=session_id or str(uuid4()),
                user_id=user_id,
                title=title or "新会话",
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            db.expunge(session)
            return session
        finally:
            db.close()

    def get_by_session_id(
        self,
        session_id: str,
        *,
        user_id: int,
        include_deleted: bool = False,
    ) -> ChatSession | None:
        db = SessionLocal()
        try:
            stmt = select(ChatSession).where(ChatSession.session_id == session_id)
            if not include_deleted:
                stmt = stmt.where(ChatSession.status == "active")
            session = db.scalar(stmt)
            if not session:
                return None
            if session.user_id is not None and session.user_id != user_id:
                raise SessionOwnershipError(session_id)
            if session:
                db.expunge(session)
            return session
        finally:
            db.close()

    def get_or_create(
        self,
        *,
        user_id: int,
        session_id: str | None = None,
        title: str | None = None,
    ) -> ChatSession:
        if session_id:
            existing = self.get_by_session_id(session_id, user_id=user_id)
            if existing:
                if existing.user_id is None:
                    return self._claim(session_id, user_id=user_id, title=title)
                return existing

            deleted = self.get_by_session_id(
                session_id, user_id=user_id, include_deleted=True
            )
            if deleted and deleted.status == "deleted":
                return self._reactivate(session_id, user_id=user_id, title=title)

            return self.create_session(
                user_id=user_id, title=title, session_id=session_id
            )
        return self.create_session(user_id=user_id, title=title)

    def _claim(
        self, session_id: str, *, user_id: int, title: str | None = None
    ) -> ChatSession:
        """认领历史无主会话（升级前数据），仅当 user_id 仍为 NULL."""
        db = SessionLocal()
        try:
            session = db.scalar(
                select(ChatSession).where(ChatSession.session_id == session_id)
            )
            assert session is not None
            if session.user_id is not None and session.user_id != user_id:
                raise SessionOwnershipError(session_id)
            session.user_id = user_id
            if title:
                session.title = title
            session.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(session)
            db.expunge(session)
            return session
        finally:
            db.close()

    def _reactivate(
        self, session_id: str, *, user_id: int, title: str | None = None
    ) -> ChatSession:
        db = SessionLocal()
        try:
            session = db.scalar(
                select(ChatSession).where(ChatSession.session_id == session_id)
            )
            assert session is not None
            if session.user_id is not None and session.user_id != user_id:
                raise SessionOwnershipError(session_id)
            session.user_id = user_id
            session.status = "active"
            if title:
                session.title = title
            session.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(session)
            db.expunge(session)
            return session
        finally:
            db.close()

    def list_sessions(
        self, *, user_id: int, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        db = SessionLocal()
        try:
            owner_filter = (
                ChatSession.status == "active",
                ChatSession.user_id == user_id,
            )
            total = (
                db.scalar(
                    select(func.count())
                    .select_from(ChatSession)
                    .where(*owner_filter)
                )
                or 0
            )

            rows = db.execute(
                select(
                    ChatSession,
                    func.count(ChatMessage.id).label("message_count"),
                )
                .outerjoin(ChatMessage, ChatMessage.session_pk == ChatSession.id)
                .where(*owner_filter)
                .group_by(ChatSession.id)
                .order_by(ChatSession.updated_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()

            items: list[dict[str, Any]] = []
            for session, message_count in rows:
                items.append(
                    {
                        "session_id": session.session_id,
                        "title": session.title,
                        "status": session.status,
                        "message_count": int(message_count or 0),
                        "created_at": session.created_at,
                        "updated_at": session.updated_at,
                    }
                )
            return items, int(total)
        finally:
            db.close()

    def get_session_detail(
        self,
        session_id: str,
        *,
        user_id: int,
        as_admin: bool = False,
        include_trace: bool = False,
    ) -> dict[str, Any] | None:
        db = SessionLocal()
        try:
            session = db.scalar(
                select(ChatSession)
                .options(selectinload(ChatSession.messages))
                .where(
                    ChatSession.session_id == session_id,
                    ChatSession.status == "active",
                )
            )
            if not session:
                return None
            if not as_admin:
                if session.user_id is not None and session.user_id != user_id:
                    raise SessionOwnershipError(session_id)
                if session.user_id is None:
                    session.user_id = user_id
                    db.commit()

            owner_username = None
            owner_display_name = None
            owner_role = None
            if session.user_id is not None:
                owner = db.scalar(
                    select(AppUser).where(AppUser.id == session.user_id)
                )
                if owner:
                    owner_username = owner.username
                    owner_display_name = owner.display_name or owner.username
                    owner_role = owner.role

            return {
                "session_id": session.session_id,
                "title": session.title,
                "status": session.status,
                "user_id": session.user_id,
                "username": owner_username,
                "display_name": owner_display_name,
                "user_role": owner_role,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "messages": [
                    {
                        "id": msg.id,
                        "role": msg.role,
                        "content": msg.content,
                        "route": msg.route,
                        "sources": msg.sources or [],
                        "metadata": strip_trace_for_client(
                            msg.metadata_json or {}, keep=include_trace
                        ),
                        "created_at": msg.created_at,
                    }
                    for msg in session.messages
                ],
            }
        finally:
            db.close()

    def list_sessions_all(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        """管理员：列出全部用户会话."""
        db = SessionLocal()
        try:
            owner_filter = (ChatSession.status == "active",)
            total = (
                db.scalar(
                    select(func.count())
                    .select_from(ChatSession)
                    .where(*owner_filter)
                )
                or 0
            )

            rows = db.execute(
                select(
                    ChatSession,
                    func.count(ChatMessage.id).label("message_count"),
                    AppUser.username,
                    AppUser.display_name,
                    AppUser.role,
                )
                .outerjoin(ChatMessage, ChatMessage.session_pk == ChatSession.id)
                .outerjoin(AppUser, AppUser.id == ChatSession.user_id)
                .where(*owner_filter)
                .group_by(ChatSession.id, AppUser.id)
                .order_by(ChatSession.updated_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()

            items: list[dict[str, Any]] = []
            for session, message_count, username, display_name, user_role in rows:
                items.append(
                    {
                        "session_id": session.session_id,
                        "title": session.title,
                        "status": session.status,
                        "message_count": int(message_count or 0),
                        "user_id": session.user_id,
                        "username": username,
                        "display_name": display_name or username,
                        "user_role": user_role,
                        "created_at": session.created_at,
                        "updated_at": session.updated_at,
                    }
                )
            return items, int(total)
        finally:
            db.close()

    def update_title(
        self, session_id: str, title: str, *, user_id: int
    ) -> ChatSession | None:
        db = SessionLocal()
        try:
            session = db.scalar(
                select(ChatSession).where(
                    ChatSession.session_id == session_id,
                    ChatSession.status == "active",
                )
            )
            if not session:
                return None
            if session.user_id is not None and session.user_id != user_id:
                raise SessionOwnershipError(session_id)
            session.user_id = user_id
            session.title = title
            session.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(session)
            db.expunge(session)
            return session
        finally:
            db.close()

    def soft_delete(self, session_id: str, *, user_id: int) -> bool:
        db = SessionLocal()
        try:
            session = db.scalar(
                select(ChatSession).where(
                    ChatSession.session_id == session_id,
                    ChatSession.status == "active",
                )
            )
            if not session:
                return False
            if session.user_id is not None and session.user_id != user_id:
                raise SessionOwnershipError(session_id)
            session.user_id = user_id
            session.status = "deleted"
            session.updated_at = datetime.utcnow()
            db.commit()
            return True
        finally:
            db.close()

    def load_history(
        self, session_id: str, *, user_id: int, limit: int = 20
    ) -> list[dict[str, str]]:
        """加载最近 limit 条消息，按时间正序返回."""
        db = SessionLocal()
        try:
            session = db.scalar(
                select(ChatSession).where(
                    ChatSession.session_id == session_id,
                    ChatSession.status == "active",
                )
            )
            if not session:
                return []
            if session.user_id is not None and session.user_id != user_id:
                raise SessionOwnershipError(session_id)

            rows = db.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_pk == session.id)
                .order_by(ChatMessage.id.desc())
                .limit(limit)
            ).all()

            return [{"role": m.role, "content": m.content} for m in reversed(rows)]
        finally:
            db.close()

    def append_turn(
        self,
        session_id: str,
        user_content: str,
        assistant_content: str,
        *,
        user_id: int,
        route: str | None = None,
        sources: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """追加一轮 user + assistant 消息，并刷新会话标题/时间."""
        db = SessionLocal()
        try:
            session = db.scalar(
                select(ChatSession).where(ChatSession.session_id == session_id)
            )
            if session and session.user_id is not None and session.user_id != user_id:
                raise SessionOwnershipError(session_id)
            if not session:
                session = ChatSession(
                    session_id=session_id,
                    user_id=user_id,
                    title=_truncate_title(user_content),
                )
                db.add(session)
                db.flush()
            else:
                session.user_id = user_id

            message_count = (
                db.scalar(
                    select(func.count())
                    .select_from(ChatMessage)
                    .where(ChatMessage.session_pk == session.id)
                )
                or 0
            )

            if message_count == 0 and (not session.title or session.title == "新会话"):
                session.title = _truncate_title(user_content)

            db.add(
                ChatMessage(
                    session_pk=session.id,
                    role="user",
                    content=user_content,
                )
            )
            db.add(
                ChatMessage(
                    session_pk=session.id,
                    role="assistant",
                    content=assistant_content,
                    route=route,
                    sources=sources or [],
                    metadata_json=metadata or {},
                )
            )
            session.status = "active"
            session.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()


_session_service: SessionService | None = None


def get_session_service() -> SessionService:
    global _session_service
    if _session_service is None:
        _session_service = SessionService()
    return _session_service
