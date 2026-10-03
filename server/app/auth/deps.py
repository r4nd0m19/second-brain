"""路由依赖：从会话 Cookie 解析当前用户。"""

import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import COOKIE_NAME, read_session
from app.db import get_session
from app.models import User


async def get_current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User:
    data = read_session(request.cookies.get(COOKIE_NAME))
    if data is None:
        raise HTTPException(status_code=401, detail="未登录")
    uid, epoch = data
    try:
        user = await session.get(User, uuid.UUID(uid))
    except ValueError:
        user = None
    # 纪元不匹配 = 已被服务端吊销（登出/全设备下线，审计二期 A1）
    if user is None or user.session_epoch != epoch:
        raise HTTPException(status_code=401, detail="未登录")
    return user
