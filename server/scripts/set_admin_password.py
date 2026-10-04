#!/usr/bin/env python3
"""管理员密码重置（单用户）：更新 users.password_hash 并递增 session_epoch（吊销全部已登录会话）。

用法::

    cd server && .venv/bin/python scripts/set_admin_password.py <新密码>
    # 或（推荐，避免 argv 可见）：
    cd server && SB_NEW_PASSWORD='<新密码>' .venv/bin/python scripts/set_admin_password.py

完成后需同步更新 .env 的 ADMIN_PASSWORD（脚本只动数据库；.env 用于启动哨兵校验与将来重种子）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.auth.security import hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402


async def main() -> None:
    password = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SB_NEW_PASSWORD", "")).strip()
    if len(password) < 8:
        raise SystemExit("密码至少 8 位（拒绝过短密码）")
    async with SessionLocal() as session:
        user = await session.scalar(select(User).limit(1))
        if user is None:
            raise SystemExit("库中无用户——先启动服务完成初始化")
        user.password_hash = hash_password(password)
        user.session_epoch += 1  # cookie 纪元校验（T063）：递增即吊销全部既有会话
        await session.commit()
        print(f"已更新用户 {user.username} 的密码；session_epoch -> {user.session_epoch}（已全部登出）")


if __name__ == "__main__":
    asyncio.run(main())
