"""Embedding provider 抽象 + OpenAI 兼容实现。

默认：硅基流动 bge-m3（免费、国内直连）；备选：阿里云百炼 text-embedding-v4
（兼容模式 base_url=https://dashscope.aliyuncs.com/compatible-mode/v1）。
⚠️ 云 embedding 例外见 plan.md Complexity Tracking（constitution IV）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx

from app.config import settings
from app.costing import add_retrieval

# 逐批进度回调：(已处理条数, 总条数) —— 由入库管线用于"索引中 x/y 块"进度（R7 配套）
ProgressCallback = Callable[[int, int], Awaitable[None]]


class EmbeddingError(RuntimeError):
    """embedding 服务不可用 / 返回异常。"""


class EmbeddingProvider(Protocol):
    dim: int

    async def embed(
        self, texts: list[str], on_progress: ProgressCallback | None = None
    ) -> list[list[float]]:
        """批量向量化，返回与输入同序的向量列表；逐批回调进度。"""


class OpenAICompatEmbedding:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dim: int,
        batch_size: int = 32,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self.batch_size = batch_size
        self.timeout = timeout

    async def embed(
        self, texts: list[str], on_progress: ProgressCallback | None = None
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start : start + self.batch_size]
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": batch},
                )
                if response.status_code != 200:
                    raise EmbeddingError(
                        f"embedding 服务返回 {response.status_code}: {response.text[:300]}"
                    )
                body = response.json()
                # 全成本（T079）：embedding 按 tokens 计价（bge-m3 现免费 → 单价 0，token 照记）
                prompt_tokens = int((body.get("usage") or {}).get("prompt_tokens", 0))
                if prompt_tokens:
                    add_retrieval(
                        prompt_tokens / 1_000_000 * settings.price_embedding_per_million
                    )
                items = body["data"]
                items.sort(key=lambda item: item.get("index", 0))  # 保序，防止乱序响应
                vectors.extend(item["embedding"] for item in items)
                if on_progress is not None:
                    await on_progress(min(start + len(batch), len(texts)), len(texts))
        return vectors


def get_embedding_provider() -> EmbeddingProvider:
    return OpenAICompatEmbedding(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        model=settings.embedding_model,
        dim=settings.embedding_dim,
        batch_size=settings.embedding_batch_size,  # 快通道入库耗时主项（R7）
    )
