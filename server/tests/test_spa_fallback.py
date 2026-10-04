"""SPA 回退路由路径穿越防护（T092 审计实测：修复前 /%2e%2e/… 可未认证读 .env 等任意文件）。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import WEB_DIR, app

pytestmark = pytest.mark.skipif(
    not WEB_DIR.exists(), reason="web/out 未构建（SPA 回退路由未注册）"
)


async def _get(path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_spa_traversal_blocked():
    """%2e%2e 编码穿越：必须回退 index.html，不得返回越界文件（server/app/config.py 在 web/out 之外）。"""
    r = await _get("/%2e%2e/%2e%2e/server/app/config.py")
    assert r.status_code == 200
    assert "SettingsConfigDict" not in r.text  # config.py 特征串 → 出现即穿越成功（回归失败）
    assert "<html" in r.text.lower()  # 越界请求应回退 index


async def test_spa_normal_paths_still_served():
    """修复不得伤正常服务：静态文件与 SPA 回退照常。"""
    ok = await _get("/login/index.html")
    assert ok.status_code == 200 and "<html" in ok.text.lower()
    fallback = await _get("/some/client/route")
    assert fallback.status_code == 200 and "<html" in fallback.text.lower()
