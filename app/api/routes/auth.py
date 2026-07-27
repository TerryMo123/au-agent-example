"""认证 API：登录 / 当前用户."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.security import (
    authenticate,
    auth_user_from_row,
    create_access_token,
    get_current_user,
    AuthUser,
)
from app.db.mysql import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = authenticate(db, body.username.strip(), body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    token = create_access_token(user)
    return LoginResponse(
        access_token=token,
        user=auth_user_from_row(user).to_public(),
    )


@router.get("/me")
def me(user: AuthUser = Depends(get_current_user)) -> dict:
    return user.to_public()
