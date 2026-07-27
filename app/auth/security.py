"""认证与权限：登录、JWT、角色敏感字段脱敏."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.config import get_settings
from app.db.mysql import Base, SessionLocal, get_db

RoleName = Literal["manager", "user"]

# 运营组员脱敏：成本、采购价、海运价、贡献利润等
USER_MASK_FIELDS: frozenset[str] = frozenset(
    {
        "cogs_usd",
        "unit_cost",
        "unit_cost_usd",
        "contribution_usd",
        "freight_cost_usd",
        "ocean_freight_unit_usd",
        "ocean_freight_total_usd",
        "rate_usd",
        "bunker_usd",
        "purchase_unit_cost",
        "factory_price",
        "landed_cost_usd",
    }
)

USER_FORBIDDEN_DATA_RESOURCES: frozenset[str] = frozenset(
    {"freight-rates", "cost-impact"}
)

USER_FORBIDDEN_SQL_TABLES: frozenset[str] = frozenset(
    {
        "ocean_freight_rates",
        "sku_cost_impact_daily",
        "purchase_order_items",
    }
)

DEMO_USERS: tuple[dict[str, str], ...] = (
    {
        "username": "moyong-manager",
        "password": "my123456",
        "role": "manager",
        "display_name": "运营组长",
    },
    {
        "username": "moyong-user",
        "password": "my123456",
        "role": "user",
        "display_name": "运营组员",
    },
)

_bearer = HTTPBearer(auto_error=False)


class AppUser(Base):
    __tablename__ = "app_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), index=True)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")


@dataclass
class AuthUser:
    id: int
    username: str
    role: RoleName
    display_name: str

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "display_name": self.display_name,
            "permissions": {
                "view_sensitive_finance": self.is_manager,
                "view_freight_rates": self.is_manager,
                "view_cost_impact": self.is_manager,
                "view_purchase_cost": self.is_manager,
            },
        }


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, salt, digest = password_hash.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    check = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return hmac.compare_digest(check, digest)


def create_access_token(user: AppUser) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.username,
        "uid": user.id,
        "role": user.role,
        "name": user.display_name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def ensure_demo_users(db: Session | None = None) -> None:
    own = db is None
    session = db or SessionLocal()
    try:
        for item in DEMO_USERS:
            exists = session.scalar(
                select(AppUser).where(AppUser.username == item["username"])
            )
            if exists:
                continue
            session.add(
                AppUser(
                    username=item["username"],
                    password_hash=hash_password(item["password"]),
                    role=item["role"],
                    display_name=item["display_name"],
                    status="active",
                )
            )
        session.commit()
    finally:
        if own:
            session.close()


def authenticate(db: Session, username: str, password: str) -> AppUser | None:
    user = db.scalar(select(AppUser).where(AppUser.username == username))
    if not user or user.status != "active":
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def auth_user_from_row(user: AppUser) -> AuthUser:
    role: RoleName = "manager" if user.role == "manager" else "user"
    return AuthUser(
        id=user.id,
        username=user.username,
        role=role,
        display_name=user.display_name or user.username,
    )


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AuthUser:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(creds.credentials)
    username = str(payload.get("sub") or "")
    user = db.scalar(select(AppUser).where(AppUser.username == username))
    if not user or user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号无效或已停用",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth_user_from_row(user)


def mask_sensitive_dict(data: dict[str, Any], *, role: RoleName) -> dict[str, Any]:
    if role == "manager":
        return data
    out = dict(data)
    for key in list(out.keys()):
        if key in USER_MASK_FIELDS:
            out[key] = None
        if key == "total_usd" and (
            "rate_usd" in data or "bunker_usd" in data or "lane_code" in data
        ):
            out[key] = None
    return out


def mask_sensitive_rows(
    rows: list[dict[str, Any]], *, role: RoleName
) -> list[dict[str, Any]]:
    if role == "manager":
        return rows
    return [mask_sensitive_dict(r, role=role) for r in rows]


def assert_data_resource_allowed(resource: str, role: RoleName) -> None:
    if role == "manager":
        return
    if resource in USER_FORBIDDEN_DATA_RESOURCES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号无权查看该财务敏感数据（海运费率 / 费用-营收）",
        )


def filter_sql_tables_for_role(tables: list[str] | tuple[str, ...], role: RoleName) -> list[str]:
    if role == "manager":
        return list(tables)
    return [t for t in tables if t not in USER_FORBIDDEN_SQL_TABLES]
