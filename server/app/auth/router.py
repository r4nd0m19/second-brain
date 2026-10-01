"""认证端点：登录 / 登出 / 当前用户（契约见 specs/001-core-qa/contracts/api.md）。"""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.auth.security import (
    COOKIE_NAME,
    SESSION_MAX_AGE,
    make_session,
    verify_password,
)
from app.db import get_session
from app.models import User

router_auth = APIRouter(prefix="/api/auth", tags=["auth"])
router_me = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


@router_auth.post("/login", status_code=204)
async def login(
    payload: LoginIn,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    user = await session.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    response.set_cookie(
        COOKIE_NAME,
        make_session(str(user.id)),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # 生产环境置于 HTTPS 反代后应改为 True（部署任务 T034/T035）
    )


@router_auth.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


@router_me.get("/api/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return {"username": user.username}
