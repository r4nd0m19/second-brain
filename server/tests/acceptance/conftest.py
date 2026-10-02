"""验收测试基建（T032）：对"运行中的真实服务"做 HTTP 端到端验收。

- 默认目标 `http://localhost:8000`（可用 SECOND_BRAIN_BASE_URL 覆盖）；服务不可达 → 整套 skip
- 验收假设：库中已有样本书（sc002 场景要求 ≥2 份 indexed 资料，否则对应用例 skip）
- 所有用例自带清理（上传的文档、评测对话与回写），跑完不留残留
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings  # noqa: E402

BASE_URL = os.environ.get("SECOND_BRAIN_BASE_URL", "http://localhost:8000")

pytestmark = pytest.mark.acceptance


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=300) as c:
            health = await c.get("/health")
            health.raise_for_status()
            login = await c.post(
                "/api/auth/login",
                json={"username": settings.admin_username, "password": settings.admin_password},
            )
            if login.status_code == 429:
                pytest.skip("登录被限速（429）——等待窗口过后再跑验收")
            assert login.status_code == 204, f"登录失败 {login.status_code}"
            yield c
    except httpx.TransportError:
        pytest.skip(f"服务不可达（{BASE_URL}）——先启动服务再跑验收")
