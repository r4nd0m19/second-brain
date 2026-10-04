"""认证端点：登录 / 登出 / 当前用户（契约见 specs/001-core-qa/contracts/api.md）。"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ratelimit
from app.auth.deps import get_current_user
from app.auth.security import (
    COOKIE_NAME,
    DUMMY_PASSWORD_HASH,
    SESSION_MAX_AGE,
    make_session,
    verify_password,
)
from app.config import settings
from app.db import get_session
from app.models import User

router_auth = APIRouter(prefix="/api/auth", tags=["auth"])
router_me = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    # 长度上限（T093）：防超长用户名撑限速器内存 / 超长密码放大 argon2 开销
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@router_auth.post("/login", status_code=204)
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    # 登录失败限速（T034；spec NFR Security：默认 5 次/15 分钟，可配置）
    # 双键（T093 审计）：单账号键防爆破；IP 键防"随机用户名绕过"（键永不重复则单账号键形同虚设，
    # 且未知用户也跑 argon2 时序对齐 → 无 IP 级上限时构成无认证资源耗尽）
    # 部署在反代后需以 --proxy-headers 启动 uvicorn，client.host 才是真实 IP（见 deploy/SECURITY.md）
    client_ip = request.client.host if request.client else "unknown"
    key = f"{client_ip}:{payload.username.strip().lower()}"
    ip_key = f"ip:{client_ip}"
    for k, lim in ((key, None), (ip_key, settings.login_rate_limit_ip)):
        retry_after = ratelimit.check(k, limit=lim)
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail=f"登录尝试过多，请 {retry_after} 秒后再试",
                headers={"Retry-After": str(retry_after)},
            )

    user = await session.scalar(select(User).where(User.username == payload.username))
    if user is None:
        # 时序对齐（审计二期 A1）：不存在的用户也跑一次哈希校验（恒假），防用户名枚举
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
        ratelimit.record_failure(key)
        ratelimit.record_failure(ip_key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(payload.password, user.password_hash):
        ratelimit.record_failure(key)
        ratelimit.record_failure(ip_key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    ratelimit.clear(key)
    ratelimit.clear(ip_key)  # 登录成功：IP 级计数一并清零（避免正常用户被历史失败拖累）
    response.set_cookie(
        COOKIE_NAME,
        make_session(str(user.id), user.session_epoch),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        # Secure 按环境自动（审计二期 B1）：HTTPS 场景自动带上（--proxy-headers 下 url.scheme 反映
        # X-Forwarded-Proto）；AUTH_COOKIE_SECURE=true 可显式强制
        secure=settings.cookie_secure or request.url.scheme == "https",
    )


@router_auth.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> None:
    # 纪元 +1（审计二期 A1）：无状态 cookie 的服务端吊销——所有设备上的旧 cookie 立即失效
    try:
        user = await get_current_user(request, session)
    except HTTPException:
        user = None
    if user is not None:
        user.session_epoch += 1
        await session.commit()
    response.delete_cookie(COOKIE_NAME)


@router_me.get("/api/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return {"username": user.username}
