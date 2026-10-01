"""认证业务：单用户初始化（v1 = 白名单单账号，constitution VII 底线 3）。"""

from sqlalchemy import select

from app.auth.security import hash_password
from app.config import settings
from app.models import User


async def ensure_admin_user() -> None:
    """启动时确保单用户存在（不存在则按 .env 初始化）。"""
    from app.db import SessionLocal

    async with SessionLocal() as session:
        existing = await session.scalar(select(User).limit(1))
        if existing is not None:
            return
        session.add(
            User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
            )
        )
        await session.commit()
