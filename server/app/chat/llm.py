"""对话模型客户端 —— OpenAI 兼容流式（默认 DeepSeek，可切任意兼容服务）。

失效降级语义（spec US2 场景 2）：抛 LLMError，由编排层转成 SSE `error` 事件 +
可重试；不影响已上传资料与历史对话。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Protocol, TypedDict

import httpx

from app.config import settings


class ChatMessage(TypedDict):
    role: str  # system / user / assistant
    content: str


class LLMError(RuntimeError):
    """对话模型服务不可用 / 返回异常。"""


class LLMClient(Protocol):
    def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """流式生成：逐段 yield 文本增量。"""


class OpenAICompatLLM:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 180.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        payload = {"model": self.model, "messages": messages, "stream": True}
        async with httpx.AsyncClient(timeout=self.timeout) as client, client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        ) as response:
            if response.status_code != 200:
                body = (await response.aread())[:300]
                raise LLMError(f"对话模型返回 {response.status_code}: {body!r}")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta


def get_llm_client() -> LLMClient:
    return OpenAICompatLLM(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
